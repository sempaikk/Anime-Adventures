"""The new apology requires current bytes and this destination's confirmed image."""

import asyncio
from datetime import datetime, timezone
import io
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from PIL import Image

from feed_notices import (CAMPAIGN, FORWARDED_CAMPAIGN, RECEPTION_CAMPAIGN,
                         RECEPTION_STARTS_AT, RECEPTION_EXPIRES_AT, RECEPTION_NOTICE,
                         ReceptionRecoveryNotices)
import test_banners as banner_fixtures
import test_feed_notices as fixtures


class ReceptionNoticeCase(unittest.IsolatedAsyncioTestCase):
    asyncSetUpBase = fixtures.FeedNoticeCase.asyncSetUpBase
    asyncTearDown = fixtures.FeedNoticeCase.asyncTearDown
    add_channel = fixtures.FeedNoticeCase.add_channel
    event = fixtures.FeedNoticeCase.event
    healthy = fixtures.FeedNoticeCase.healthy
    finish = fixtures.FeedNoticeCase.finish

    async def send(self, channel_id, *, params):
        if params.files:
            return await banner_fixtures.BannerCase.send(self, channel_id, params=params)
        return await fixtures.FeedNoticeCase.send(self, channel_id, params=params)

    async def asyncSetUp(self):
        await fixtures.FeedNoticeCase.asyncSetUp(self)
        self.now = datetime(2026, 10, 31, 12, tzinfo=timezone.utc).timestamp()
        self.app.build = {'verified': True, 'version': '2026.10.31.1'}
        self.notices = self.app.banner_reception_notices
        self.healthy()

    def rows(self):
        return self.app.store.rows('SELECT * FROM bot_feed_notices WHERE campaign=? ORDER BY channel_id',
                                   (RECEPTION_CAMPAIGN,))

    def confirm(self, *channels):
        for row in self.relay.query('SELECT * FROM banner_jobs').fetchall():
            if not channels or int(row['channel_id']) in channels:
                self.relay.state(row, 'sent', 8000 + int(row['channel_id']))

    async def test_current_images_are_delivered_before_one_apology_in_each_banner_channel(self):
        await self.relay.accept(self.event())
        await self.finish()
        self.assertEqual(self.sent, [])
        await self.relay.cycle()
        self.assertEqual(len(self.sent), 4)
        self.assertTrue(all(item['files'] for item in self.sent))
        self.now += 31
        self.healthy()
        await asyncio.gather(self.finish(), self.notices.cycle())
        apologies = [item for item in self.sent if not item['files']]
        self.assertEqual({item['channel'] for item in apologies}, {10, 20, 30, 40})
        for item in apologies:
            self.assertEqual(item['payload']['content'], RECEPTION_NOTICE)
            self.assertEqual(item['payload']['allowed_mentions']['parse'], [])
            self.assertTrue(item['payload']['enforce_nonce'])
            self.assertFalse(item['payload'].get('components'))
            self.assertFalse(item['payload'].get('embeds'))
        self.assertIn('Pedimos desculpas', RECEPTION_NOTICE)
        self.assertIn('Corrigimos uma falha', RECEPTION_NOTICE)
        self.assertIn('este canal já voltou', RECEPTION_NOTICE)
        self.assertNotIn('MiB', RECEPTION_NOTICE)
        self.assertLess(len(RECEPTION_NOTICE.encode('utf-16-le')) // 2, 1900)
        self.assertTrue(all(row['state'] == 'sent' for row in self.rows()))
        self.app.http.publish_message.assert_not_awaited()

    async def test_metadata_and_other_channels_success_cannot_announce_this_channel_recovered(self):
        self.relay.diagnostics.observe('200', self.now)
        with self.relay.db:
            self.relay.diagnostics.received(message_id='200', created=self.now)
        await self.finish()
        self.assertEqual(self.sent, [])
        await self.relay.accept(self.event(message_id='200'))
        for row, state in zip(self.relay.query('SELECT * FROM banner_jobs ORDER BY channel_id').fetchall(),
                              ('pending', 'unavailable', 'uncertain', 'oversize')):
            self.relay.state(row, state)
        self.now += 31
        self.healthy()
        await self.finish()
        self.assertEqual(self.sent, [])
        self.confirm(10)
        self.now += 31
        self.healthy()
        await self.finish()
        self.assertEqual([item['channel'] for item in self.sent], [10])

    async def test_partial_receive_and_new_image_revision_wait_for_complete_current_delivery(self):
        event = self.event(message_id='200', images=[self.event()['images'][0],
            'https://cdn.discordapp.com/attachments/1/2/new.png'])
        out = io.BytesIO()
        Image.new('RGB', (20, 20), 'red').save(out, format='PNG')
        second = out.getvalue()
        self.relay.download.side_effect = [self.blob, TimeoutError('synthetic'), self.blob, second]
        await self.relay.accept(event)
        self.confirm()
        await self.finish()
        self.assertEqual(self.sent, [])
        self.assertTrue(await self.relay.accept(event))
        self.now += 31
        self.healthy()
        await self.finish()
        self.assertEqual(self.sent, [])  # Old, partial event's sent state is insufficient.
        self.confirm()
        self.now += 31
        self.healthy()
        await self.finish()
        self.assertEqual(len(self.sent), 4)

    async def test_prior_incident_receipts_and_frozen_destinations_remain_unchanged(self):
        self.app.feed_notices.snapshot()
        self.app.banner_forward_notices.snapshot()
        old = self.app.store.rows('SELECT * FROM bot_feed_notices WHERE campaign IN (?,?) ORDER BY campaign,channel_id',
                                  (CAMPAIGN, FORWARDED_CAMPAIGN))
        self.notices.snapshot()
        channel = self.add_channel(5, 50)
        channel.guild.unavailable = False
        self.relay.configure(5, 50)
        await self.relay.accept(self.event())
        self.confirm()
        await self.finish()
        self.assertEqual({item['channel'] for item in self.sent}, {10, 20, 30, 40})
        self.assertEqual(self.app.store.rows('SELECT * FROM bot_feed_notices WHERE campaign IN (?,?) ORDER BY campaign,channel_id',
                                           (CAMPAIGN, FORWARDED_CAMPAIGN)), old)
        self.assertEqual(len(self.rows()), 4)

    async def test_restart_and_later_release_never_repeat_the_apology(self):
        await self.relay.accept(self.event())
        self.confirm()
        await self.finish()
        before = self.rows()
        await self.app.close()
        from community_bot import CommunityBot
        self.app = CommunityBot(self.temp.name)
        self.app._connection.user = SimpleNamespace(id=42)
        self.app.build = {'verified': True, 'version': 'future-release'}
        self.app.is_ready = lambda: True
        self.app.store.clock = lambda: self.now
        self.app.get_channel = lambda ident: self.channels.get(ident)
        self.app.get_guild = lambda ident: next((c.guild for c in self.channels.values() if c.guild.id == ident), None)
        self.app.http.send_message = AsyncMock(side_effect=self.send)
        self.notices = self.app.banner_reception_notices
        await self.finish()
        self.assertEqual(self.rows(), before)
        self.assertEqual(len(self.sent), 4)
        self.app.http.send_message.assert_not_awaited()

    async def test_lost_ack_reconciles_instead_of_repeating_the_apology(self):
        await self.relay.accept(self.event())
        self.confirm()
        async def lost_ack(channel_id, *, params):
            result = await self.send(channel_id, params=params)
            self.history.setdefault(channel_id, []).append(SimpleNamespace(id=int(result['id']),
                author=SimpleNamespace(id=42), webhook_id=None, nonce=None, content=RECEPTION_NOTICE,
                created_at=datetime.fromtimestamp(self.now, timezone.utc)))
            raise TimeoutError('Synthetic lost notice acknowledgment')
        self.app.http.send_message.side_effect = lost_ack
        await self.finish()
        self.assertTrue(all(row['state'] == 'uncertain' for row in self.rows()))
        self.now += 301
        self.notices = ReceptionRecoveryNotices(self.app)
        await self.finish()
        self.assertEqual(len(self.sent), 4)
        self.assertTrue(all(row['state'] == 'sent' for row in self.rows()))

    async def test_campaign_window_and_unverified_start_never_announce_success(self):
        self.now = RECEPTION_STARTS_AT - 1
        await self.finish()
        self.assertEqual(self.rows(), [])
        self.now = RECEPTION_STARTS_AT
        self.app.build['verified'] = False
        await self.finish()
        self.assertEqual(self.rows(), [])
        self.app.build['verified'] = True
        self.notices.snapshot()
        self.now = RECEPTION_EXPIRES_AT
        await self.finish()
        self.assertTrue(all(row['state'] == 'expired' for row in self.rows()))
        self.assertEqual(self.sent, [])

    async def test_existing_operations_loop_drives_new_campaign(self):
        self.app.globalchat.operations.check_alerts = AsyncMock()
        self.app.community.publish_update = AsyncMock()
        self.app.feed_notices.cycle = AsyncMock()
        self.app.banner_forward_notices.cycle = AsyncMock()
        self.app.banner_reception_notices.cycle = AsyncMock()
        await self.app.operations_loop.coro(self.app)
        self.app.feed_notices.cycle.assert_awaited_once()
        self.app.banner_forward_notices.cycle.assert_awaited_once()
        self.app.banner_reception_notices.cycle.assert_awaited_once()
