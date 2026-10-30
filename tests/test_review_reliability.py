"""Combined fault regressions from the second review; temporary state and fake APIs only."""

import asyncio
import io
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import discord
from PIL import Image

import test_banners as feeds
import test_banner_images as images
import test_global_chat as chats
from banner_relay import image_extension
from global_relay import formatted_chunks
from media_validation import validate_file
from global_ops import GlobalOperations


class FeedRecoveryReview(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = feeds.BannerCase.asyncSetUp
    asyncTearDown = feeds.BannerCase.asyncTearDown
    add_channel = feeds.BannerCase.add_channel
    send = feeds.BannerCase.send
    event = feeds.BannerCase.event
    jobs = feeds.BannerCase.jobs
    interaction = feeds.BannerCase.interaction
    accept_images = images.ImageDeliveryCase.accept_images

    async def test_permissions_recover_for_both_feeds_without_reconfiguration_or_duplicates(self):
        from game_sources import DAILY_CHANNEL_ID
        for feed, guild, channel in ((self.relay,1,10),(self.app.daily,2,20)):
            feed.clock=lambda:self.now
            feed.status='ready'
            feed.download=AsyncMock(return_value=self.blob)
            feed.configure(guild,channel)
            self.channels[channel].permissions_for.return_value.attach_files=False
            await feed.accept(self.event(channel_id=str(feed.source_ids[0])))
            await feed.cycle()
            self.assertEqual(feed.query('SELECT state FROM banner_jobs').fetchone()[0],'unavailable')
        self.assertFalse(self.sent)
        self.now+=61
        for channel in (10,20):
            self.channels[channel].permissions_for.return_value.attach_files=True
        for feed in (self.relay,self.app.daily):
            await feed.cycle()
            await feed.cycle()
            self.assertEqual(feed.query('SELECT state FROM banner_jobs').fetchone()[0],'sent')
        self.assertEqual(sorted(x['channel'] for x in self.sent),[10,20])

    async def test_only_latest_blocked_banner_is_resumed_after_permissions_return(self):
        self.relay.configure(1,10)
        self.channels[10].permissions_for.return_value.attach_files=False
        await self.relay.accept(self.event())
        await self.relay.cycle()
        self.now+=1
        await self.relay.accept(self.event(message_id='123456789012345679'))
        await self.relay.cycle()
        self.now+=61
        self.channels[10].permissions_for.return_value.attach_files=True
        await self.relay.cycle()
        self.assertEqual(len(self.sent),1)
        self.assertEqual([r['state'] for r in self.jobs()],['unavailable','sent'])

    async def test_withdrawal_during_first_upload_prevents_other_parts_and_preserves_receipt(self):
        self.relay.configure(1,10)
        await self.accept_images(['red','green','blue'])
        async def withdraw(channel_id,*,params):
            reply=await self.send(channel_id,params=params)
            self.relay.diagnostics.retract(self.event()['message_id'])
            return reply
        self.app.http.send_message.side_effect=withdraw
        await self.relay.cycle()
        self.assertEqual(len(self.sent),1)
        self.assertEqual(self.jobs()[0]['state'],'superseded')
        self.assertEqual(self.relay.db.execute("SELECT count(*) FROM banner_image_receipts WHERE state='sent'").fetchone()[0],1)
        self.now+=61
        await self.relay.cycle()
        self.assertEqual(len(self.sent),1)

    async def test_source_edit_in_flight_stops_old_remaining_parts(self):
        self.relay.configure(1,10)
        await self.accept_images(['red','green','blue'])
        async def edit(channel_id,*,params):
            reply=await self.send(channel_id,params=params)
            if len(self.sent)==1:
                self.relay.download=AsyncMock(return_value=images.colored('yellow'))
                await self.relay.accept(self.event(created_at=self.now+1))
            return reply
        self.app.http.send_message.side_effect=edit
        await self.relay.cycle()
        self.assertEqual(len(self.sent),1)
        await self.relay.cycle()
        self.assertEqual(len(self.sent),2)
        self.assertEqual(self.sent[-1]['files'][0]['blob'],images.colored('yellow'))

    async def test_reaction_retry_survives_cache_expiry_without_clearing_votes(self):
        self.relay.configure(1,10)
        await self.relay.accept(self.event())
        await self.relay.cycle()
        self.now+=3901
        self.relay.prune()
        self.assertFalse(self.relay.assets(self.jobs()[0]['event_id']) if self.jobs() else [])
        votes=self.relay.votes
        self.channels[10].permissions_for.return_value.add_reactions=True
        async def rate(message,mask=0,progress=None):
            progress(7)
        votes.rate=AsyncMock(side_effect=rate)
        await votes.live_reactions()
        votes.rate.assert_awaited_once()
        self.channels[10].get_partial_message.return_value.clear_reaction.assert_not_called()
        self.assertEqual(self.relay.db.execute('SELECT reactions FROM banner_image_receipts').fetchone()[0],7)

    async def test_mixed_source_urls_keep_valid_banner_but_daily_is_atomic(self):
        self.relay.configure(1,10)
        event=self.event(images=[self.event()['images'][0],'https://example.invalid/private.png'])
        self.assertTrue(await self.relay.accept(event))
        self.relay.download.assert_awaited_once()
        daily=self.app.daily
        daily.clock=lambda:self.now
        daily.download=AsyncMock(return_value=self.blob)
        self.assertFalse(await daily.accept({**event,'channel_id':str(daily.source_ids[0])}))
        daily.download.assert_not_awaited()

    async def test_definite_upload_rejections_are_not_saved_as_unknown_confirmation(self):
        self.relay.configure(1,10)
        await self.relay.accept(self.event())
        self.app.http.send_message.side_effect=discord.HTTPException(SimpleNamespace(status=413,reason='Too large'),{'code':40005,'message':'too large'})
        await self.relay.cycle()
        self.assertEqual(self.jobs()[0]['state'],'oversize')
        self.assertEqual(self.relay.db.execute('SELECT state FROM banner_image_receipts').fetchone()[0],'oversize')
        self.assertFalse(self.sent)

    async def test_rejected_payload_is_not_reported_as_sent(self):
        self.relay.configure(1,10)
        await self.relay.accept(self.event())
        self.app.http.send_message.side_effect=discord.HTTPException(SimpleNamespace(status=400,reason='Bad request'),{'code':50035,'message':'invalid payload'})
        await self.relay.cycle()
        self.assertEqual(self.jobs()[0]['state'],'rejected')

    async def test_rate_limit_retry_after_is_persisted_without_marking_success_or_unknown_ack(self):
        self.relay.configure(1,10)
        await self.accept_images(['red','green','blue'])
        limited=discord.HTTPException(SimpleNamespace(status=429,reason='Rate limited',headers={'Retry-After':'120'}),{'code':0,'message':'Rate limited'})
        self.app.http.send_message.side_effect=limited
        await self.relay.cycle()
        self.assertEqual(self.jobs()[0]['state'],'pending')
        self.assertGreaterEqual(self.jobs()[0]['next_try'],self.now+120)
        self.assertEqual(self.app.http.send_message.await_count,1)
        self.app.http.send_message.side_effect=self.send
        self.now+=119
        await self.relay.cycle()
        self.assertFalse(self.sent)
        self.now+=2
        await self.relay.cycle()
        self.assertEqual(len(self.sent),3)

    async def test_temporary_maintenance_preserves_jobs_and_expires_without_reconfiguration(self):
        self.relay.configure(1,10)
        await self.relay.accept(self.event())
        self.relay.pause(True,7,seconds=900)
        await self.relay.cycle()
        self.assertFalse(self.sent)
        self.assertTrue(self.relay.ready())
        self.now+=901
        await self.relay.cycle()
        self.assertEqual(len(self.sent),1)

    async def test_readiness_detects_stalled_reception_even_with_fresh_poll(self):
        self.relay.configure(1,10)
        self.relay.status='ready'
        self.relay.diagnostics.observe(self.event()['message_id'],self.now)
        self.now+=181
        self.relay.diagnostics.poll()
        self.assertFalse(self.relay.ready())
        self.assertTrue(self.relay.alert_conditions()['banner_receive'][0])


class GlobalReview(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=chats.ChatCase.asyncSetUp
    asyncTearDown=chats.ChatCase.asyncTearDown
    fetch=chats.ChatCase.fetch
    history=chats.ChatCase.history
    send_notice=chats.ChatCase.send_notice
    message=chats.ChatCase.message
    interaction=chats.ChatCase.interaction
    copies=chats.ChatCase.copies
    flush=chats.ChatCase.flush
    asset=chats.ChatCase.asset

    async def test_second_message_reaches_fast_destination_while_first_is_still_stalled_elsewhere(self):
        started,release=asyncio.Event(),asyncio.Event()
        send=self.hooks[120].send
        async def stalled(*args,**kwargs):
            started.set()
            await release.wait()
            return await send(*args,**kwargs)
        self.hooks[120].send=stalled
        self.engine.last_recovery=self.now[0]
        first=self.message(content='First message')
        await self.engine.ingest(first)
        await self.engine.cycle()
        await asyncio.wait_for(started.wait(),1)
        second=self.message(content='Second message')
        await self.engine.ingest(second)
        await self.engine.cycle()
        self.assertEqual(self.engine.store.delivery(second.id,30)['state'],'sent')
        self.assertEqual(self.engine.store.delivery(second.id,20)['state'],'queued')
        release.set()
        await asyncio.gather(*self.engine.deliveries.values())
        await self.engine.cycle()
        self.assertEqual(self.engine.store.delivery(second.id,20)['state'],'sent')
        self.assertEqual(sum(m.content=='First message' for m in self.copies(first)),2)
        self.assertEqual(sum(m.content=='Second message' for m in self.copies(second)),2)

    async def test_lost_ack_reconciliation_continues_beyond_one_page_and_survives_restart(self):
        # Fill the earliest part of the search window before the actual accepted POST.
        for _ in range(120):
            self.message(self.channels[20],content='Unrelated local traffic')
        self.hooks[120].lose_ack=True
        source=self.message(content='Lost ACK target')
        await self.engine.ingest(source)
        await self.flush()
        job=self.engine.store.delivery(source.id,20)
        self.assertEqual(job['state'],'uncertain')
        self.now[0]+=31
        await self.engine.deliver(self.engine.store.delivery(source.id,20))
        self.assertEqual(self.engine.store.delivery(source.id,20)['state'],'uncertain')
        from global_relay import GlobalRelay
        await self.engine.close()
        self.app.globalchat=self.engine=GlobalRelay(self.app)
        self.engine.webhook=lambda ident:self.hooks[int(ident)]
        self.now[0]+=31
        await self.engine.deliver(self.engine.store.delivery(source.id,20))
        await self.flush()
        self.assertEqual(self.engine.store.delivery(source.id,20)['state'],'sent')
        self.assertEqual(len(self.hooks[120].calls),1)

    async def test_no_proof_after_repeated_scans_never_blindly_reposts(self):
        self.hooks[120].send=AsyncMock(side_effect=TimeoutError('No ACK and no visible copy'))
        source=self.message()
        await self.engine.ingest(source)
        for _ in range(9):
            await self.flush()
            self.now[0]+=31
        self.assertEqual(self.engine.store.delivery(source.id,20)['state'],'uncertain')
        self.hooks[120].send.assert_awaited_once()

    async def test_alert_flapping_does_not_reset_persistent_cooldown(self):
        ops=self.engine.operations
        ops.notify=AsyncMock(return_value=True)
        self.app.health.storage_level='critical'
        await ops.check_alerts()
        self.now[0]+=121
        self.engine.last_cycle=self.now[0]
        await ops.check_alerts()
        self.app.health.storage_level='ok'
        await ops.check_alerts()
        self.now[0]+=1
        self.app.health.storage_level='critical'
        self.engine.operations=ops=GlobalOperations(self.engine)
        ops.notify=AsyncMock(return_value=True)
        await ops.check_alerts()
        self.now[0]+=121
        self.engine.last_cycle=self.now[0]
        await ops.check_alerts()
        ops.notify.assert_not_awaited()
        self.app.health.storage_level='ok'
        await ops.check_alerts()
        self.now[0]+=121
        self.engine.last_cycle=self.now[0]
        await ops.check_alerts()
        ops.notify.assert_awaited_once()
        self.assertIn('Service recovered',ops.notify.call_args.args[0])
        self.app.health.storage_level='critical'
        await ops.check_alerts()
        self.now[0]+=121
        self.engine.last_cycle=self.now[0]
        await ops.check_alerts()
        self.assertEqual(ops.notify.await_count,1)


class ImageIntegrityReview(unittest.TestCase):
    def test_truncated_jpeg_that_passes_verify_is_rejected_by_full_decode(self):
        output=io.BytesIO()
        Image.new('RGB',(1000,1000),'navy').save(output,'JPEG')
        truncated=output.getvalue()[:len(output.getvalue())//2]
        with Image.open(io.BytesIO(truncated)) as image:
            image.verify()
        with self.assertRaises(ValueError):
            image_extension(truncated)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'image.jpg'
            path.write_bytes(truncated)
            with self.assertRaises(ValueError):
                validate_file(path,path.name)

    def test_long_fenced_text_uses_balanced_readable_parts_and_keeps_source_untouched(self):
        text='```python\n'+('print("😀")\n'*600)+'```'
        original=text
        parts=formatted_chunks(text)
        self.assertGreater(len(parts),1)
        self.assertTrue(all(p.count('```')==2 for p in parts))
        self.assertTrue(all(len(p.encode('utf-16-le'))//2<=1900 for p in parts))
        self.assertEqual(text,original)
