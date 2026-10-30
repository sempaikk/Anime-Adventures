"""Private, mocked incident notifications: scope, recovery gates and durable receipts."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

import discord

from feed_notices import CAMPAIGN, EXPIRES_AT, FeedNotices
import test_banners as fixtures


class FeedNoticeCase(unittest.IsolatedAsyncioTestCase):
    asyncSetUpBase = fixtures.BannerCase.asyncSetUp
    asyncTearDown = fixtures.BannerCase.asyncTearDown
    add_channel = fixtures.BannerCase.add_channel
    event = fixtures.BannerCase.event

    async def send(self, channel_id, *, params):
        self.sent.append({'channel': channel_id, 'payload': dict(params.payload), 'files': params.files or []})
        return {'id': str(9000 + len(self.sent))}

    async def asyncSetUp(self):
        await self.asyncSetUpBase()
        self.now = datetime(2026, 10, 28, 15, tzinfo=timezone.utc).timestamp()
        self.app.store.clock = lambda: self.now
        self.app.daily.clock = lambda: self.now
        self.app.build = {'verified': True, 'version': '2026.10.28.3'}
        self.app.is_ready = lambda: True
        self.app.get_guild = lambda ident: next((c.guild for c in self.channels.values() if c.guild.id == ident), None)
        self.app.http.publish_message = AsyncMock(side_effect=AssertionError('No crossposting'))
        self.notices = self.app.feed_notices
        for gid in range(1, 5):
            for feed, offset in ((self.app.banners, 0), (self.app.daily, 1)):
                channel = self.add_channel(gid, gid * 10 + offset)
                channel.guild.unavailable = False
                channel.permissions_for.return_value.add_reactions = True
                feed.configure(gid, channel.id)
        self.healthy()

    def healthy(self):
        for feed in (self.app.banners, self.app.daily):
            feed.status = 'ready'
            feed.diagnostics.poll()

    def rows(self):
        return self.app.store.rows('SELECT * FROM bot_feed_notices WHERE campaign=? ORDER BY channel_id', (CAMPAIGN,))

    async def finish(self):
        # At most four channels per cycle; two HTTP sends at a time.
        await self.notices.cycle()
        await self.notices.cycle()

    async def test_every_existing_guild_and_both_feeds_receive_one_plain_portuguese_notice(self):
        await asyncio.gather(self.finish(), self.notices.cycle())
        await self.finish()
        self.assertEqual({item['channel'] for item in self.sent}, {10, 11, 20, 21, 30, 31, 40, 41})
        self.assertEqual(len(self.sent), 8)
        for item in self.sent:
            payload = item['payload']
            self.assertTrue(payload['content'].startswith('Pedimos desculpas pela interrupção'))
            self.assertIn('A falha foi corrigida', payload['content'])
            self.assertIn('desafios diários' if item['channel'] % 10 else 'banners', payload['content'])
            self.assertEqual(payload['allowed_mentions']['parse'], [])
            self.assertTrue(payload['enforce_nonce'])
            self.assertFalse(payload.get('embeds'))
            self.assertFalse(payload.get('components'))
            self.assertFalse(item['files'])
        self.assertTrue(all(row['state'] == 'sent' for row in self.rows()))
        self.assertIn('8/8 channels confirmed', self.notices.description())
        self.app.http.publish_message.assert_not_awaited()
        self.assertEqual(self.relay.query('SELECT count(*) FROM banner_jobs').fetchone()[0], 0)

    async def test_unverified_or_offline_startup_never_sends_or_freezes_recipients(self):
        self.app.build['verified'] = False
        await self.finish()
        self.app.build['verified'] = True
        self.app.is_ready = lambda: False
        await self.finish()
        self.assertEqual(self.rows(), [])
        self.assertEqual(self.sent, [])

    async def test_one_unhealthy_source_does_not_announce_success_or_block_the_other_feed(self):
        self.app.daily.status = 'connecting'
        await self.finish()
        self.assertEqual({item['channel'] for item in self.sent}, {10, 20, 30, 40})
        self.now += 31
        self.healthy()
        self.app.daily.diagnostics.observe('200', self.now)
        await self.finish()
        self.assertEqual(len(self.sent), 4)
        with self.relay.db:
            self.app.daily.diagnostics.received(message_id='200', created=self.now)
        self.now += 31
        self.healthy()
        await self.finish()
        self.assertEqual(len(self.sent), 8)

    async def test_old_successful_poll_is_not_a_recovery_confirmation(self):
        self.now += 121
        await self.finish()
        self.assertEqual(self.sent, [])
        self.healthy()
        self.now += 31
        await self.finish()
        self.assertEqual(len(self.sent), 8)

    async def test_receipts_survive_a_real_restart_and_do_not_repeat_the_notice(self):
        await self.finish()
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
        self.relay = self.app.banners
        self.notices = self.app.feed_notices
        await self.finish()
        self.assertEqual(len(self.sent), 8)
        self.app.http.send_message.assert_not_awaited()

    async def test_lost_ack_is_reconciled_after_restart_without_reposting(self):
        original = self.send
        async def lost_ack(channel_id, *, params):
            result = await original(channel_id, params=params)
            payload = self.sent[-1]['payload']
            self.history.setdefault(channel_id, []).append(SimpleNamespace(id=int(result['id']),
                author=SimpleNamespace(id=42), webhook_id=None, nonce=None,
                content=payload['content'], created_at=datetime.fromtimestamp(self.now, timezone.utc)))
            raise TimeoutError('Synthetic lost acknowledgement')
        self.app.http.send_message.side_effect = lost_ack
        await self.finish()
        self.assertTrue(all(row['state'] == 'uncertain' for row in self.rows()))
        self.now += 301
        self.notices = FeedNotices(self.app)
        await self.finish()
        self.assertEqual(len(self.sent), 8)
        self.assertTrue(all(row['state'] == 'sent' for row in self.rows()))

    async def test_cancelled_send_without_remote_proof_is_never_blindly_repeated(self):
        for gid in (2, 3, 4):
            self.app.banners.disable(gid)
            self.app.daily.disable(gid)
        self.app.daily.disable(1)
        self.app.http.send_message.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.notices.cycle()
        self.assertEqual(self.rows()[0]['state'], 'uncertain')
        self.now += 301
        self.notices = FeedNotices(self.app)
        await self.notices.cycle()
        self.assertEqual(self.app.http.send_message.await_count, 1)
        self.assertIn('1 awaiting confirmation', self.notices.description())

    async def test_permission_rejection_retries_only_affected_channels_after_repair(self):
        original = self.send
        async def rejected(channel_id, *, params):
            if channel_id == 10:
                raise discord.Forbidden(SimpleNamespace(status=403, reason='Forbidden'), 'Synthetic rejection')
            return await original(channel_id, params=params)
        self.app.http.send_message.side_effect = rejected
        await self.finish()
        self.assertEqual(len(self.sent), 7)
        self.assertEqual(self.rows()[0]['state'], 'blocked')
        self.now += 301
        self.healthy()
        self.app.http.send_message.side_effect = original
        await self.finish()
        self.assertEqual(len(self.sent), 8)
        self.assertTrue(all(row['state'] == 'sent' for row in self.rows()))

    async def test_scope_is_frozen_and_changed_or_disabled_destinations_are_not_redirected(self):
        self.notices.snapshot()
        new = self.add_channel(5, 50)
        new.guild.unavailable = False
        self.app.banners.configure(5, 50)
        self.app.daily.disable(1)
        moved = self.add_channel(1, 12)
        moved.guild.unavailable = False
        self.app.banners.configure(1, 12)
        await self.finish()
        self.assertEqual({item['channel'] for item in self.sent}, {20, 21, 30, 31, 40, 41})
        self.assertEqual(sum(row['state'] == 'cancelled' for row in self.rows()), 2)
        self.assertEqual(len(self.rows()), 8)

    async def test_shared_feed_channel_gets_one_combined_notice_when_both_sources_recover(self):
        self.app.daily.configure(1, 10)
        self.app.daily.status = 'connecting'
        await self.finish()
        self.assertNotIn(10, {item['channel'] for item in self.sent})
        self.now += 31
        self.healthy()
        await self.finish()
        combined = [item for item in self.sent if item['channel'] == 10]
        self.assertEqual(len(combined), 1)
        self.assertIn('banners e desafios diários', combined[0]['payload']['content'])
        self.assertEqual(len(self.sent), 7)

    async def test_incident_expires_without_sending_to_future_installations(self):
        self.notices.snapshot()
        self.now = EXPIRES_AT
        await self.finish()
        self.assertEqual(self.sent, [])
        self.assertTrue(all(row['state'] == 'expired' for row in self.rows()))
        self.assertIn('8 closed without a send', self.notices.description())

    async def test_operations_loop_drives_notices_without_changing_the_service_count(self):
        self.app.globalchat.operations.check_alerts = AsyncMock()
        self.app.community.publish_update = AsyncMock()
        self.notices.cycle = AsyncMock()
        await self.app.operations_loop.coro(self.app)
        self.notices.cycle.assert_awaited_once()
        self.assertEqual(len(self.app.service_loops()), 9)
