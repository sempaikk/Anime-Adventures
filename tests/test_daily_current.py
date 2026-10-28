"""The daily feed recovers its current challenge without replaying yesterday."""

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

import discord

from community_bot import CommunityBot
from daily_current import DailyCurrent
from game_sources import DAILY_CHANNEL_ID
import test_banner_delivery_recovery as reader_fixtures
import test_banners as fixtures


class DailyCurrentCase(unittest.IsolatedAsyncioTestCase):
    asyncTearDown = fixtures.BannerCase.asyncTearDown
    add_channel = fixtures.BannerCase.add_channel
    send = fixtures.BannerCase.send
    event = fixtures.BannerCase.event
    drive_reader = reader_fixtures.SourceRecoveryCase.drive_reader
    source_message = reader_fixtures.SourceRecoveryCase.source_message

    async def asyncSetUp(self):
        await fixtures.BannerCase.asyncSetUp(self)
        self.app.store.clock = lambda: self.now
        self.daily = self.app.daily
        self.daily.clock = lambda: self.now
        self.daily.download = AsyncMock(return_value=self.blob)
        self.daily.configure(1, 10)

    def daily_event(self, ident, *, age=0):
        return self.event(channel_id=str(DAILY_CHANNEL_ID), message_id=str(ident), created_at=self.now - age)

    async def restart(self, *, source_ready=True):
        await self.app.close()
        self.app = CommunityBot(self.temp.name)
        self.app._connection.user = SimpleNamespace(id=42)
        self.app.health.storage_level = 'ok'
        self.app.get_channel = lambda ident: self.channels.get(ident)
        self.app.store.clock = lambda: self.now
        self.app.http.send_message = AsyncMock(side_effect=self.send)
        self.daily = self.app.daily
        self.daily.clock = lambda: self.now
        self.daily.download = AsyncMock(return_value=self.blob)
        if source_ready:
            self.daily.status = 'ready'

    async def test_daily_poll_recovers_only_the_latest_image_inside_the_overlapping_26_hour_window(self):
        yesterday = self.source_message(100, age=24 * 3600)
        today = self.source_message(200)

        async def scenario(client, events, channels):
            # The newest image already being seen must not make the poll fall
            # through to yesterday. A later receive retry is still allowed.
            await client.scan_image(channels[DAILY_CHANNEL_ID])
            self.elapsed = 61
            await client.scan_image(channels[DAILY_CHANNEL_ID])

        events = await self.drive_reader({DAILY_CHANNEL_ID: [today, yesterday]}, scenario)
        self.assertEqual([event['message_id'] for event in events if event['event'] == 'image'], ['200', '200'])

    async def test_restart_with_today_delivered_does_not_receive_or_repost_yesterday_in_any_guild(self):
        self.daily.configure(2, 20)
        today = self.daily_event(200)
        await self.daily.accept(today)
        await self.daily.cycle()
        self.assertEqual(len(self.sent), 2)
        await self.restart()
        self.assertFalse(await self.daily.accept(self.daily_event(100, age=24 * 3600)))
        self.daily.download.assert_not_awaited()
        self.assertFalse(await self.daily.accept(today))
        await self.daily.cycle()
        self.assertEqual(len(self.sent), 2)

    async def test_new_daily_supersedes_yesterdays_pending_jobs_before_any_upload(self):
        await self.daily.accept(self.daily_event(100, age=24 * 3600))
        await self.daily.accept(self.daily_event(200))
        await self.daily.cycle()
        rows = self.daily.query('SELECT e.source_message,j.state FROM banner_jobs j JOIN banner_events e ON e.id=j.event_id ORDER BY e.source_message').fetchall()
        self.assertEqual([(row['source_message'], row['state']) for row in rows], [('100', 'superseded'), ('200', 'sent')])
        self.assertEqual(len(self.sent), 1)

    async def test_restart_waits_for_source_scan_before_delivering_a_cached_challenge(self):
        await self.daily.accept(self.daily_event(100, age=24 * 3600))
        await self.restart(source_ready=False)
        await self.daily.cycle()
        self.assertEqual(len(self.sent), 0)
        self.daily.status = 'connecting'
        await self.daily.accept(self.daily_event(200))
        await self.daily.cycle()
        self.assertEqual(len(self.sent), 0)
        self.daily.status = 'ready'
        await self.daily.cycle()
        self.assertEqual(len(self.sent), 1)
        current = self.daily.query("SELECT e.source_message FROM banner_jobs j JOIN banner_events e ON e.id=j.event_id WHERE j.state='sent'").fetchone()
        self.assertEqual(current[0], '200')

    async def test_new_source_download_failure_blocks_yesterday_without_confirming_the_new_image(self):
        await self.daily.accept(self.daily_event(100, age=24 * 3600))
        self.daily.download.side_effect = TimeoutError('Synthetic new-source download failure')
        with self.assertRaises(TimeoutError):
            await self.daily.accept(self.daily_event(200))
        await self.restart()
        await self.daily.cycle()
        self.assertEqual(len(self.sent), 0)
        self.assertIsNone(self.daily.current_daily.active_id())
        self.assertFalse(await self.daily.accept(self.daily_event(100, age=24 * 3600)))
        self.daily.download.assert_not_awaited()
        self.assertTrue(await self.daily.accept(self.daily_event(200)))
        await self.daily.cycle()
        self.assertEqual(len(self.sent), 1)

    async def test_old_caption_edit_cannot_overtake_a_newer_source_message(self):
        await self.daily.accept(self.daily_event(200, age=60))
        await self.daily.cycle()
        self.assertFalse(await self.daily.accept(self.daily_event(100)))
        self.assertEqual(self.daily.download.await_count, 1)
        self.add_channel(2, 21)
        self.daily.configure(2, 21)
        await self.daily.cycle()
        self.assertEqual({item['channel'] for item in self.sent}, {10, 21})
        self.assertEqual(len(self.sent), 2)
        self.assertEqual(self.daily.current_daily.current()['source_message'], '200')

    async def test_cache_expiration_and_caption_edit_of_the_same_image_do_not_erase_the_delivery_guard(self):
        await self.daily.accept(self.daily_event(200))
        await self.daily.cycle()
        self.now += 27 * 3600
        self.daily.prune()
        self.assertEqual(self.daily.query('SELECT count(*) FROM banner_jobs').fetchone()[0], 0)
        await self.restart()
        # An old source post being edited must not make its unchanged image new.
        self.assertFalse(await self.daily.accept(self.daily_event(200)))
        await self.daily.cycle()
        self.assertEqual(len(self.sent), 1)
        self.assertTrue(await self.daily.accept(self.daily_event(300)))
        await self.daily.cycle()
        self.assertEqual(len(self.sent), 2)

    async def test_owner_deleting_the_delivered_message_and_reconfiguring_does_not_recreate_it(self):
        event = self.daily_event(200)
        await self.daily.accept(event)
        await self.daily.cycle()
        # Empty Discord history represents the owner deleting the original.
        self.history[10] = []
        await self.restart()
        self.daily.configure(1, 10)
        await self.daily.accept(event)
        await self.daily.cycle()
        self.assertEqual(len(self.sent), 1)

    async def test_actual_image_update_on_the_same_source_message_remains_deliverable(self):
        await self.daily.accept(self.daily_event(200))
        await self.daily.cycle()
        self.now += 1
        # Use another real static image, without changing the source message ID.
        import io
        from PIL import Image
        out = io.BytesIO()
        Image.new('RGB', (160, 90), 'green').save(out, 'PNG')
        self.daily.download.return_value = out.getvalue()
        self.assertTrue(await self.daily.accept(self.daily_event(200)))
        await self.daily.cycle()
        self.assertEqual(len(self.sent), 2)
        self.assertFalse(await self.daily.accept(self.daily_event(200)))
        await self.daily.cycle()
        self.assertEqual(len(self.sent), 2)

    async def test_migration_uses_source_order_instead_of_an_old_posts_newer_edit_timestamp(self):
        await self.daily.accept(self.daily_event(100, age=24 * 3600))
        await self.daily.accept(self.daily_event(200, age=60))
        with self.daily.db:
            self.daily.db.execute('DELETE FROM daily_current')
            self.daily.query('UPDATE banner_events SET created_at=? WHERE source_message=?', (self.now, '100'))
            self.daily.query("UPDATE banner_jobs SET state='pending'")
        self.daily.current_daily = DailyCurrent(self.daily)
        self.assertEqual(self.daily.current_daily.current()['source_message'], '200')
        await self.daily.cycle()
        self.assertEqual(len(self.sent), 1)

    async def test_unknown_old_upload_is_preserved_but_never_retried_after_a_new_challenge(self):
        await self.daily.accept(self.daily_event(100, age=24 * 3600))
        self.app.http.send_message.side_effect = TimeoutError('Synthetic unknown delivery')
        await self.daily.cycle()
        unknown = self.daily.query("SELECT * FROM banner_jobs WHERE state='uncertain'").fetchone()
        self.assertIsNotNone(unknown)
        self.app.http.send_message.side_effect = self.send
        await self.daily.accept(self.daily_event(200))
        await self.daily.cycle()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.daily.query('SELECT state FROM banner_jobs WHERE event_id=?', (unknown['event_id'],)).fetchone()[0], 'uncertain')

    async def test_restart_after_upload_cancellation_reconciles_without_creating_another_message(self):
        await self.daily.accept(self.daily_event(200))

        async def cancelled(channel_id, *, params):
            response = await self.send(channel_id, params=params)
            item = self.sent[-1]
            self.history[10] = [SimpleNamespace(id=int(response['id']), author=SimpleNamespace(id=42),
                nonce=item['payload']['nonce'], attachments=[SimpleNamespace(filename=file['filename']) for file in item['files']])]
            raise asyncio.CancelledError()

        self.app.http.send_message.side_effect = cancelled
        with self.assertRaises(asyncio.CancelledError):
            await self.daily.cycle()
        await self.restart()
        self.now += 31
        await self.daily.cycle()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.daily.query('SELECT state FROM banner_jobs').fetchone()[0], 'sent')

    async def test_stale_daily_crosspost_queue_is_ignored_without_publishing_yesterday(self):
        self.channels[10].type = discord.ChannelType.news
        await self.daily.accept(self.daily_event(100, age=24 * 3600))
        await self.daily.cycle()
        self.app.feed_publications.prepare()
        old = self.daily.db.execute('SELECT * FROM feed_publications').fetchone()
        await self.daily.accept(self.daily_event(200))
        self.app.feed_publications.prepare()
        await self.app.feed_publications.publish(old)
        self.channels[10].fetch_message.assert_not_called()
        self.assertEqual(self.daily.db.execute('SELECT state FROM feed_publications').fetchone()[0], 'ignored')

    async def test_daily_crosspost_also_waits_for_source_confirmation_after_restart(self):
        self.channels[10].type = discord.ChannelType.news
        await self.daily.accept(self.daily_event(100, age=24 * 3600))
        await self.daily.cycle()
        self.daily.status = 'connecting'
        await self.app.feed_publications.cycle()
        self.channels[10].fetch_message.assert_not_called()
        row = self.daily.db.execute('SELECT * FROM feed_publications').fetchone()
        self.assertEqual((row['state'], row['issue']), ('pending', 'source'))


if __name__ == '__main__':
    unittest.main()
