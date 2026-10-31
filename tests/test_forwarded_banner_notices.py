"""The forwarding explanation is one banner-only incident, using fake APIs."""

import asyncio
from datetime import datetime, timezone
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

import discord

from feed_notices import (CAMPAIGN, FORWARDED_CAMPAIGN, FORWARDED_EXPIRES_AT,
                          FORWARDED_NOTICE, FORWARDED_STARTS_AT, ForwardedBannerNotices)
import test_feed_notices as fixtures


class ForwardedNoticeCase(unittest.IsolatedAsyncioTestCase):
    asyncSetUpBase=fixtures.FeedNoticeCase.asyncSetUpBase
    asyncTearDown=fixtures.FeedNoticeCase.asyncTearDown
    add_channel=fixtures.FeedNoticeCase.add_channel
    event=fixtures.FeedNoticeCase.event
    send=fixtures.FeedNoticeCase.send
    healthy=fixtures.FeedNoticeCase.healthy
    finish=fixtures.FeedNoticeCase.finish

    async def asyncSetUp(self):
        await fixtures.FeedNoticeCase.asyncSetUp(self)
        self.now=datetime(2026,10,31,tzinfo=timezone.utc).timestamp()
        self.app.build={'verified':True,'version':'2026.10.30.4'}
        self.notices=self.app.banner_forward_notices
        self.healthy()

    def rows(self):
        return self.app.store.rows('SELECT * FROM bot_feed_notices WHERE campaign=? ORDER BY channel_id',(FORWARDED_CAMPAIGN,))

    async def test_each_current_banner_channel_gets_one_explanation_without_daily_or_mentions(self):
        await asyncio.gather(self.finish(),self.notices.cycle())
        await self.finish()
        self.assertEqual([item['channel'] for item in self.sent],[10,20,30,40])
        self.assertEqual(len(FORWARDED_NOTICE),len(FORWARDED_NOTICE.encode('utf-16-le'))//2)
        self.assertLessEqual(len(FORWARDED_NOTICE.encode('utf-16-le'))//2,1900)
        for item in self.sent:
            payload=item['payload']
            self.assertEqual(payload['content'],FORWARDED_NOTICE)
            self.assertEqual(payload['allowed_mentions']['parse'],[])
            self.assertTrue(payload['enforce_nonce'])
            self.assertFalse(payload.get('embeds'))
            self.assertFalse(payload.get('components'))
            self.assertFalse(item['files'])
        self.assertIn('por encaminhamento',FORWARDED_NOTICE)
        self.assertIn('O problema foi corrigido',FORWARDED_NOTICE)
        self.assertIn('histórico completo',FORWARDED_NOTICE)
        self.assertIn('não será republicado',FORWARDED_NOTICE)
        self.assertTrue(all(json.loads(row['kinds'])[0]['kind']=='banner' for row in self.rows()))
        self.assertTrue(all(row['state']=='sent' for row in self.rows()))
        self.app.http.publish_message.assert_not_awaited()
        self.assertEqual(self.relay.query('SELECT count(*) FROM banner_jobs').fetchone()[0],0)

    async def test_requires_verified_ready_process_and_current_received_banner_source(self):
        self.app.build['verified']=False
        await self.finish()
        self.assertEqual(self.rows(),[])
        self.app.build['verified']=True
        self.app.is_ready=lambda:False
        await self.finish()
        self.assertEqual(self.rows(),[])
        self.app.is_ready=lambda:True
        self.relay.status='connecting'
        await self.finish()
        self.assertEqual(self.sent,[])
        self.now+=31
        self.healthy()
        self.relay.diagnostics.observe('200',self.now)
        await self.finish()
        self.assertEqual(self.sent,[])
        with self.relay.db:self.relay.diagnostics.received(message_id='200',created=self.now)
        self.now+=31
        self.healthy()
        self.app.daily.status='connecting'
        await self.finish()
        self.assertEqual(len(self.sent),4)

    async def test_old_campaign_receipts_and_new_campaign_are_independent(self):
        self.app.feed_notices.snapshot()
        old=self.app.store.rows('SELECT * FROM bot_feed_notices WHERE campaign=?',(CAMPAIGN,))
        self.assertEqual(len(old),8)
        old_key=self.app.store.get('feed-notice-snapshot:'+CAMPAIGN)
        await self.finish()
        self.assertEqual(len(self.sent),4)
        self.assertEqual(self.app.store.rows('SELECT * FROM bot_feed_notices WHERE campaign=?',(CAMPAIGN,)),old)
        self.assertEqual(self.app.store.get('feed-notice-snapshot:'+CAMPAIGN),old_key)
        self.assertNotEqual({row['nonce'] for row in old if row['channel_id']=='10'},
                            {row['nonce'] for row in self.rows() if row['channel_id']=='10'})

    async def test_real_restart_and_future_release_do_not_repeat_notice(self):
        await self.finish()
        before=self.rows()
        await self.app.close()
        from community_bot import CommunityBot
        self.app=CommunityBot(self.temp.name)
        self.app._connection.user=SimpleNamespace(id=42)
        self.app.build={'verified':True,'version':'future-release'}
        self.app.is_ready=lambda:True
        self.app.store.clock=lambda:self.now
        self.app.get_channel=lambda ident:self.channels.get(ident)
        self.app.get_guild=lambda ident:next((c.guild for c in self.channels.values() if c.guild.id==ident),None)
        self.app.http.send_message=AsyncMock(side_effect=self.send)
        self.notices=self.app.banner_forward_notices
        await self.finish()
        self.assertEqual(self.rows(),before)
        self.assertEqual(len(self.sent),4)
        self.app.http.send_message.assert_not_awaited()

    async def test_lost_ack_is_reconciled_without_sending_another_explanation(self):
        async def lost_ack(channel_id,*,params):
            result=await self.send(channel_id,params=params)
            self.history.setdefault(channel_id,[]).append(SimpleNamespace(id=int(result['id']),
                author=SimpleNamespace(id=42),webhook_id=None,nonce=None,
                content=self.sent[-1]['payload']['content'],
                created_at=datetime.fromtimestamp(self.now,timezone.utc)))
            raise TimeoutError('Synthetic lost notice acknowledgment')
        self.app.http.send_message.side_effect=lost_ack
        await self.finish()
        self.assertTrue(all(row['state']=='uncertain' for row in self.rows()))
        self.now+=301
        self.notices=ForwardedBannerNotices(self.app)
        await self.finish()
        self.assertEqual(len(self.sent),4)
        self.assertTrue(all(row['state']=='sent' for row in self.rows()))

    async def test_unknown_send_without_proof_never_reposts(self):
        self.app.http.send_message.side_effect=TimeoutError('Synthetic unknown notice outcome')
        await self.finish()
        self.assertEqual(self.app.http.send_message.await_count,4)
        self.now+=301
        self.notices=ForwardedBannerNotices(self.app)
        await self.finish()
        self.assertEqual(self.app.http.send_message.await_count,4)
        self.assertTrue(all(row['state']=='uncertain' for row in self.rows()))

    async def test_snapshot_excludes_future_channels_and_never_redirects_moved_destinations(self):
        self.notices.snapshot()
        channel=self.add_channel(5,50)
        channel.guild.unavailable=False
        self.app.banners.configure(5,50)
        channel=self.add_channel(1,12)
        channel.guild.unavailable=False
        self.app.banners.configure(1,12)
        self.app.banners.disable(2)
        await self.finish()
        self.assertEqual({item['channel'] for item in self.sent},{30,40})
        self.assertEqual(sum(row['state']=='cancelled' for row in self.rows()),2)
        self.assertEqual(len(self.rows()),4)

    async def test_repaired_permissions_resume_only_the_blocked_channel(self):
        async def rejected(channel_id,*,params):
            if channel_id==10:
                raise discord.Forbidden(SimpleNamespace(status=403,reason='Forbidden'),'Synthetic rejection')
            return await self.send(channel_id,params=params)
        self.app.http.send_message.side_effect=rejected
        await self.finish()
        self.assertEqual({item['channel'] for item in self.sent},{20,30,40})
        self.assertEqual(self.rows()[0]['state'],'blocked')
        self.now+=301
        self.healthy()
        self.app.http.send_message.side_effect=self.send
        await self.finish()
        self.assertEqual(len(self.sent),4)
        self.assertTrue(all(row['state']=='sent' for row in self.rows()))

    async def test_campaign_window_does_not_freeze_or_send_to_future_installations(self):
        self.now=FORWARDED_STARTS_AT-1
        await self.finish()
        self.assertEqual(self.rows(),[])
        self.assertFalse(self.app.store.get('feed-notice-snapshot:'+FORWARDED_CAMPAIGN))
        self.now=FORWARDED_STARTS_AT
        self.notices.snapshot()
        self.now=FORWARDED_EXPIRES_AT
        await self.finish()
        self.assertEqual(self.sent,[])
        self.assertTrue(all(row['state']=='expired' for row in self.rows()))

    async def test_operations_loop_drives_both_campaigns_with_no_new_worker_loop(self):
        self.app.globalchat.operations.check_alerts=AsyncMock()
        self.app.community.publish_update=AsyncMock()
        self.app.feed_notices.cycle=AsyncMock()
        self.app.banner_forward_notices.cycle=AsyncMock()
        await self.app.operations_loop.coro(self.app)
        self.app.feed_notices.cycle.assert_awaited_once()
        self.app.banner_forward_notices.cycle.assert_awaited_once()
        self.assertEqual(len(self.app.service_loops()),8)
