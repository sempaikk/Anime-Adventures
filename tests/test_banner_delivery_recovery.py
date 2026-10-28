"""Recover missed source images without turning reception retries into duplicate uploads."""

from datetime import datetime, timezone
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from banner_reader import ImageTracker, listen
from community_bot import CommunityBot
from game_sources import BANNER_CHANNEL_ID, DAILY_CHANNEL_ID, IMAGE_SOURCE_CHANNELS
import test_banners as fixtures


class SourceRecoveryCase(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.BannerCase.asyncSetUp
    asyncTearDown = fixtures.BannerCase.asyncTearDown
    add_channel = fixtures.BannerCase.add_channel
    send = fixtures.BannerCase.send
    event = fixtures.BannerCase.event

    async def drive_reader(self, histories, scenario):
        events, harness = [], self

        class Channel:
            def __init__(self, ident):
                self.id = ident
                self.guild = SimpleNamespace(subscribe=AsyncMock())

            def history(self, **kwargs):
                return fixtures.iterate(histories.get(self.id, []))

        channels = {ident: Channel(ident) for ident in IMAGE_SOURCE_CHANNELS}
        for ident, messages in histories.items():
            for message in messages:
                message.channel = channels[ident]

        class Client:
            def __init__(self, **kwargs):
                pass

            def get_channel(self, ident):
                return channels[ident]

            async def start(self, token):
                self.image_tracker.clock = lambda: harness.elapsed
                await self.on_ready()
                await scenario(self, events, channels)

            async def close(self):
                pass

        self.elapsed = 0
        fake = SimpleNamespace(Client=Client, TextChannel=Channel,
                               CaptchaRequired=type('CaptchaRequired', (Exception,), {}),
                               LoginFailure=type('LoginFailure', (Exception,), {}))
        with patch.dict(sys.modules, {'discord': fake}), patch(
                'banner_reader.emit', side_effect=lambda event, **kw: events.append({'event': event, **kw})), patch(
                'banner_reader.time.time', side_effect=lambda: self.now):
            await listen({'token': 'synthetic-only', 'source_channel_ids': IMAGE_SOURCE_CHANNELS,
                          'daily_channel_id': DAILY_CHANNEL_ID, 'questions_enabled': False})
        return events

    def source_message(self, ident, *, age=0):
        return SimpleNamespace(id=ident, edited_at=None,
                               created_at=datetime.fromtimestamp(self.now - age, timezone.utc),
                               attachments=[SimpleNamespace(filename='banner.png', content_type='image/png',
                                   url=f'https://cdn.discordapp.com/attachments/1/{ident}/banner.png?ex=old')],
                               embeds=[])

    async def test_transient_banner_download_failure_recovers_while_daily_delivers_and_success_is_not_redownloaded(self):
        self.relay.configure(1, 10)
        daily = self.app.daily
        daily.clock = lambda: self.now
        daily.download = AsyncMock(return_value=self.blob)
        daily.configure(2, 20)
        self.relay.download.side_effect = [TimeoutError('Synthetic CDN timeout'), self.blob]
        failed = []

        async def drain(events):
            for event in list(events):
                if event['event'] != 'image':
                    continue
                feed = self.relay if event['channel_id'] == str(BANNER_CHANNEL_ID) else daily
                try:
                    await feed.accept(event)
                except TimeoutError:
                    failed.append(event['message_id'])
            events.clear()
            await self.relay.cycle()
            await daily.cycle()

        async def scenario(client, events, channels):
            await drain(events)
            self.assertEqual(failed, ['123'])
            self.assertEqual([item['channel'] for item in self.sent], [20])
            self.elapsed = 61
            await client.scan_image(channels[BANNER_CHANNEL_ID])
            await drain(events)
            self.assertEqual([item['channel'] for item in self.sent], [20, 10])
            self.elapsed = 122
            await client.scan_image(channels[BANNER_CHANNEL_ID])
            await drain(events)
            self.assertEqual(len(self.sent), 2)
            self.assertEqual(self.relay.download.await_count, 2)

        await self.drive_reader({BANNER_CHANNEL_ID: [self.source_message(123)],
                                 DAILY_CHANNEL_ID: [self.source_message(456)]}, scenario)

    async def test_poll_recovers_older_missed_images_even_when_the_newest_image_was_already_seen(self):
        first, second, latest = (self.source_message(ident) for ident in (123, 124, 125))
        histories = {BANNER_CHANNEL_ID: []}

        async def scenario(client, events, channels):
            client.publish_image(latest)
            histories[BANNER_CHANNEL_ID] = [latest, second, first]
            await client.scan_image(channels[BANNER_CHANNEL_ID])

        # Set the channel on messages introduced after the initial scan too.
        async def configured(client, events, channels):
            for message in (first, second, latest):
                message.channel = channels[BANNER_CHANNEL_ID]
            await scenario(client, events, channels)

        events = await self.drive_reader(histories, configured)
        self.assertEqual([event['message_id'] for event in events if event['event'] == 'image'], ['125', '123', '124'])

    async def test_confirmed_reception_survives_a_restart_and_renewed_cdn_signature_without_redownload(self):
        self.relay.configure(1, 10)
        event = self.event()
        self.assertTrue(await self.relay.accept(event))
        await self.relay.cycle()
        await self.app.close()
        self.app = CommunityBot(self.temp.name)
        self.app.health.storage_level = 'ok'
        self.app._connection.user = SimpleNamespace(id=42)
        self.app.get_channel = lambda ident: self.channels.get(ident)
        self.app.http.send_message = AsyncMock(side_effect=self.send)
        self.relay = self.app.banners
        self.relay.clock = lambda: self.now
        self.relay.download = AsyncMock(return_value=self.blob)
        self.assertFalse(await self.relay.accept({**event, 'images': [event['images'][0] + '?ex=renewed']}))
        self.relay.download.assert_not_awaited()
        await self.relay.cycle()
        self.assertEqual(len(self.sent), 1)

    async def test_reception_retries_preserve_the_existing_feed_age_windows(self):
        async def scenario(client, events, channels):
            pass

        recent_banner = self.source_message(123)
        expired_banner = self.source_message(124, age=3901)
        recent_daily = self.source_message(125, age=12 * 3600)
        expired_daily = self.source_message(126, age=26 * 3600 + 1)
        events = await self.drive_reader({BANNER_CHANNEL_ID: [recent_banner, expired_banner],
                                          DAILY_CHANNEL_ID: [recent_daily, expired_daily]}, scenario)
        self.assertEqual({event['message_id'] for event in events if event['event'] == 'image'}, {'123', '125'})

    async def test_storage_pause_does_not_confirm_reception_and_expired_source_receipts_are_pruned(self):
        self.relay.configure(1, 10)
        self.app.health.storage_level = 'critical'
        self.assertFalse(await self.relay.accept(self.event()))
        self.relay.download.assert_not_awaited()
        self.app.health.storage_level = 'ok'
        self.assertTrue(await self.relay.accept(self.event()))
        self.assertEqual(self.relay.query('SELECT count(*) FROM banner_source_receipts').fetchone()[0], 1)
        self.now += self.relay.max_age + 1
        self.relay.prune()
        self.assertEqual(self.relay.query('SELECT count(*) FROM banner_source_receipts').fetchone()[0], 0)

    async def test_failed_validation_does_not_confirm_reception_and_block_a_later_valid_retry(self):
        self.relay.configure(1, 10)
        self.relay.download.side_effect = [b'not an image', self.blob]
        with self.assertRaises(ValueError):
            await self.relay.accept(self.event())
        self.assertTrue(await self.relay.accept(self.event()))
        await self.relay.cycle()
        self.assertEqual(len(self.sent), 1)

    async def test_edited_source_and_new_message_with_identical_bytes_are_still_checked(self):
        self.relay.configure(1, 10)
        event = self.event()
        self.assertTrue(await self.relay.accept(event))
        await self.relay.cycle()
        self.assertFalse(await self.relay.accept({**event, 'created_at': self.now + 1}))
        self.assertFalse(await self.relay.accept({**event, 'created_at': self.now + 1}))
        self.assertEqual(self.relay.download.await_count, 2)
        self.assertTrue(await self.relay.accept({**event, 'message_id': '123456789012345679'}))
        await self.relay.cycle()
        self.assertEqual(len(self.sent), 2)


class SourceRetryTrackerCase(unittest.TestCase):
    def test_retry_is_bounded_to_one_minute_without_duplicate_gateway_bursts(self):
        tracker = ImageTracker()
        now = [0]
        tracker.clock = lambda: now[0]
        payload = {'channel_id': '1', 'message_id': '2', 'created_at': 123,
                   'images': ['https://cdn.discordapp.com/attachments/1/2/a.png?ex=old']}
        self.assertTrue(tracker.new(payload))
        now[0] = 30
        self.assertFalse(tracker.new(payload))
        now[0] = 61
        self.assertTrue(tracker.new({**payload, 'images': [payload['images'][0] + '&renewed=1']}))
        self.assertFalse(tracker.new(payload))


if __name__ == '__main__':
    unittest.main()
