"""Independent source workers, fair destinations, freshness and private previews."""

import asyncio
from datetime import datetime,timezone
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,MagicMock

import discord
import io
from PIL import Image

import test_banners as fixtures
from feed_receiver import FeedReceiver
from feed_views import preview,FeedPanel
from game_sources import BANNER_CHANNEL_ID,DAILY_CHANNEL_ID


class RuntimeFeeds(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.BannerCase.asyncSetUp
    asyncTearDown=fixtures.BannerCase.asyncTearDown
    add_channel=fixtures.BannerCase.add_channel
    send=fixtures.BannerCase.send
    event=fixtures.BannerCase.event
    interaction=fixtures.BannerCase.interaction

    async def test_slow_reception_does_not_block_other_feed_or_observation(self):
        release,started,fast=asyncio.Event(),asyncio.Event(),asyncio.Event()
        async def slow(event):
            started.set()
            await release.wait()
        async def quick(event):
            fast.set()
        self.relay.accept=slow
        self.app.daily.accept=quick
        self.app.daily.clock=lambda:self.now
        receiver=FeedReceiver(self.app)
        receiver.start()
        try:
            receiver.handle({'event':'image',**self.event()})
            receiver.handle({'event':'image',**self.event(channel_id=str(DAILY_CHANNEL_ID),message_id='200')})
            receiver.handle({'event':'ready','channel_id':str(DAILY_CHANNEL_ID)})
            await asyncio.wait_for(started.wait(),1)
            await asyncio.wait_for(fast.wait(),1)
            self.assertEqual(self.app.daily.status,'ready')
            self.assertEqual(self.app.daily.query('SELECT source_message FROM daily_source_head').fetchone()[0],'200')
            self.assertFalse(release.is_set())
        finally:
            release.set()
            await receiver.close()

    async def test_slow_destination_does_not_hold_fast_server_or_configuration_lock(self):
        self.relay.configure(1,10)
        self.relay.configure(2,20)
        await self.relay.accept(self.event())
        release,started=asyncio.Event(),asyncio.Event()
        async def send(channel_id,*,params):
            if channel_id==10:
                started.set()
                await release.wait()
            return await self.send(channel_id,params=params)
        self.app.http.send_message.side_effect=send
        await self.relay.cycle()
        await asyncio.wait_for(started.wait(),1)
        self.assertEqual([item['channel'] for item in self.sent],[20])
        async with asyncio.timeout(1):
            async with self.app.guild_lock(1):
                self.assertTrue(True)
        release.set()
        await asyncio.gather(*self.relay.deliveries.values())
        self.assertEqual({item['channel'] for item in self.sent},{10,20})

    async def test_text_edit_with_new_image_version_blocks_older_queued_daily_revision(self):
        daily=self.app.daily
        daily.clock=lambda:self.now
        daily.download=AsyncMock(return_value=self.blob)
        daily.configure(1,10)
        old=self.event(channel_id=str(DAILY_CHANNEL_ID),message_id='200')
        await daily.accept(old)
        daily.current_daily.observe('200',self.now+10)
        await daily.cycle()
        self.assertEqual(self.sent,[])
        self.assertFalse(await daily.accept(old))
        self.assertIsNone(daily.current_daily.active_id())

    async def test_withdrawn_source_is_not_replayed_but_existing_votes_and_posts_remain(self):
        self.relay.configure(1,10)
        event=self.event()
        await self.relay.accept(event)
        self.relay.diagnostics.retract(event['message_id'])
        await self.relay.cycle()
        self.assertEqual(self.sent,[])
        self.assertFalse(await self.relay.accept(event))

    async def test_fresh_poll_with_no_new_images_is_healthy_without_delivery_alert(self):
        self.relay.configure(1,10)
        self.relay.status='ready'
        self.relay.diagnostics.poll()
        self.assertTrue(self.relay.ready())
        self.assertFalse(any(value[0] for value in self.relay.alert_conditions().values()))
        self.now+=121
        self.assertFalse(self.relay.ready())

    async def test_observed_but_unreceived_new_image_is_reported_even_with_empty_jobs(self):
        self.relay.configure(1,10)
        self.relay.status='ready'
        self.relay.diagnostics.observe('200',self.now)
        self.now+=121
        self.relay.diagnostics.poll()
        self.assertTrue(self.relay.alert_conditions()['banner_receive'][0])
        self.assertEqual(self.relay.diagnostics.snapshot()['pending'],0)

    async def test_native_source_does_not_need_secondary_account_or_publications(self):
        self.app.banners.start=MagicMock()
        channel=self.add_channel(99,BANNER_CHANNEL_ID)
        channel.history.side_effect=lambda **kw:fixtures.iterate([SimpleNamespace(
            id=200,channel=channel,created_at=datetime.fromtimestamp(self.now,timezone.utc),edited_at=None,
            attachments=[SimpleNamespace(filename='banner.png',content_type='image/png',url=self.event()['images'][0])],embeds=[])])
        self.relay.configure(1,10)
        await self.app.native_sources.poll()
        await asyncio.wait_for(self.app.native_sources.receiver.queues[str(BANNER_CHANNEL_ID)].join(),1)
        self.assertTrue(self.relay.native)
        self.assertEqual(self.relay.status,'ready')
        self.assertIsNone(self.relay.process)
        await self.relay.cycle()
        self.assertEqual([item['channel'] for item in self.sent],[10])

    async def test_secondary_status_cannot_overwrite_authorized_native_source(self):
        self.relay.native=True
        self.relay.status='ready'
        FeedReceiver(self.app).handle({'event':'login_failed'})
        self.assertEqual(self.relay.status,'ready')
        self.assertEqual(self.app.daily.status,'login_failed')

    async def test_private_preview_revalidates_access_and_never_posts_or_reconfigures(self):
        self.relay.configure(1,10)
        await self.relay.accept(self.event())
        self.relay.status='ready'
        i=self.interaction()
        member=MagicMock(spec=discord.Member)
        member.id=7
        i.user=member
        before=self.relay.generation(1)
        await preview(self.relay,i)
        self.assertTrue(i.followup.send.call_args.kwargs['ephemeral'])
        self.assertEqual(self.relay.generation(1),before)
        self.assertEqual(self.sent,[])
        self.channels[10].permissions_for.return_value.view_channel=False
        with self.assertRaises(ValueError):
            await preview(self.relay,i)

    async def test_members_only_see_member_actions_and_expired_setup_is_rejected(self):
        member=FeedPanel(self.app,self.interaction(admin=False),kind='banner')
        self.assertEqual({item.label for item in member.children},{'View current images','How it works','Open last delivery','Recent deliveries','Delivery status','Report image issue'})
        i=self.interaction()
        old=FeedPanel(self.app,i,kind='banner')
        self.relay.configure(1,10)
        with self.assertRaises(ValueError):
            await old.enable.callback(i)

    async def test_source_ledger_remains_bounded_without_reopening_forgotten_old_posts(self):
        with self.relay.db:
            for n in range(2050):
                self.relay.diagnostics.remember(str(10000+n),['digest'+str(n)],self.now)
            self.relay.diagnostics.prune()
        self.assertEqual(self.relay.query('SELECT count(*) FROM banner_seen').fetchone()[0],2048)
        self.assertTrue(self.relay.diagnostics.obsolete('10000'))

    async def test_source_acceptance_does_not_keep_old_image_bytes_for_deduplication(self):
        await self.relay.accept(self.event())
        self.now+=self.relay.max_age+1
        self.relay.prune()
        self.assertEqual(self.relay.query('SELECT count(*) FROM banner_assets').fetchone()[0],0)
        self.assertEqual(self.relay.query('SELECT count(*) FROM banner_seen').fetchone()[0],1)

    async def test_transient_failure_for_one_banner_image_recovers_without_reposting_valid_part(self):
        self.relay.configure(1,10)
        out=io.BytesIO();Image.new('RGB',(9,9),'red').save(out,format='PNG')
        second=out.getvalue()
        event=self.event(images=[self.event()['images'][0],'https://cdn.discordapp.com/attachments/1/2/second.png'])
        self.relay.download.side_effect=[self.blob,TimeoutError('synthetic'),self.blob,second]
        self.assertTrue(await self.relay.accept(event))
        await self.relay.cycle()
        self.assertEqual(len(self.sent),1)
        self.assertEqual(self.relay.query('SELECT count(*) FROM banner_source_receipts').fetchone()[0],0)
        self.assertTrue(await self.relay.accept(event))
        await self.relay.cycle()
        self.assertEqual(len(self.sent),2)
        self.assertEqual(self.relay.query('SELECT count(*) FROM banner_source_receipts').fetchone()[0],1)

    async def test_background_upload_cancellation_leaves_reconcilable_receipt(self):
        self.relay.configure(1,10)
        await self.relay.accept(self.event())
        self.app.http.send_message.side_effect=asyncio.CancelledError()
        await self.relay.cycle()
        row=self.relay.db.execute('SELECT state,first_attempt FROM banner_image_receipts').fetchone()
        self.assertEqual(row['state'],'sending')
        self.assertGreater(row['first_attempt'],0)

    async def test_receipt_recovered_from_previous_version_updates_receive_diagnostics(self):
        event=self.event()
        await self.relay.accept(event)
        with self.relay.db:
            self.relay.query("UPDATE banner_diagnostics SET received_source='',received_version=0")
        receiver=FeedReceiver(self.app)
        receiver.start()
        try:
            receiver.handle({'event':'image',**event})
            await receiver.queues[str(BANNER_CHANNEL_ID)].join()
            self.assertEqual(self.relay.diagnostics.snapshot()['received_source'],event['message_id'])
        finally:
            await receiver.close()
