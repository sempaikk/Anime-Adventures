"""Private crosspost journeys using confirmed feed deliveries and mocked Discord."""

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import discord

from community_bot import CommunityBot
from feed_publications import FeedPublications
from game_sources import DAILY_CHANNEL_ID
import test_banners as fixtures


class FeedPublishingCase(unittest.IsolatedAsyncioTestCase):
    asyncTearDown = fixtures.BannerCase.asyncTearDown
    add_channel = fixtures.BannerCase.add_channel
    send = fixtures.BannerCase.send
    event = fixtures.BannerCase.event

    async def asyncSetUp(self):
        await fixtures.BannerCase.asyncSetUp(self)
        self.app.store.clock = lambda: self.now
        self.app.daily.clock = lambda: self.now
        self.app.daily.download = AsyncMock(return_value=self.blob)
        self.publisher = self.app.feed_publications
        self.messages = {}
        for channel in self.channels.values():
            channel.type = discord.ChannelType.news
            channel.fetch_message = AsyncMock(side_effect=lambda ident, c=channel: self.messages[c.id, str(ident)])

        async def upload(channel_id, *, params):
            result = await self.send(channel_id, params=params)
            message = SimpleNamespace(
                id=int(result['id']), author=SimpleNamespace(id=42), webhook_id=None,
                attachments=[SimpleNamespace(filename=file.filename) for file in params.files],
                flags=discord.MessageFlags(), publish=AsyncMock())

            async def publish():
                message.flags.crossposted = True

            message.publish.side_effect = publish
            self.messages[channel_id, result['id']] = message
            return result

        self.app.http.send_message.side_effect = upload

    async def upload_banner(self, guilds=(1,)):
        for guild_id in guilds:
            self.relay.configure(guild_id, guild_id * 10)
        await self.relay.accept(self.event())
        await self.relay.cycle()

    def rows(self):
        return self.relay.db.execute('SELECT * FROM feed_publications ORDER BY channel_id,message_id').fetchall()

    async def test_banner_and_daily_publish_in_every_configured_news_guild_without_uploading_again(self):
        await self.upload_banner((1, 2))
        for guild_id in (1, 2):
            self.app.daily.configure(guild_id, guild_id * 10)
        await self.app.daily.accept(self.event(channel_id=str(DAILY_CHANNEL_ID)))
        await self.app.daily.cycle()
        self.assertEqual(len(self.sent), 4)
        self.assertIsNotNone(self.publisher.release_pending())
        await self.publisher.cycle()
        self.assertEqual({(row['kind'], row['guild_id']) for row in self.rows()},
                         {('banner', '1'), ('banner', '2'), ('daily', '1'), ('daily', '2')})
        self.assertTrue(all(row['state'] == 'published' for row in self.rows()))
        for message in self.messages.values():
            message.publish.assert_awaited_once()
        self.assertIsNone(self.publisher.release_pending())
        self.publisher = FeedPublications(self.app)
        await asyncio.gather(self.publisher.cycle(), self.publisher.cycle())
        for message in self.messages.values():
            message.publish.assert_awaited_once()
        self.assertEqual(len(self.sent), 4)

    async def test_normal_text_channels_keep_delivering_without_crossposts(self):
        self.channels[10].type = discord.ChannelType.text
        await self.upload_banner()
        await self.publisher.cycle()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.rows(), [])
        self.channels[10].fetch_message.assert_not_awaited()
        self.assertIsNone(self.publisher.description('banner', 1))
        self.assertIsNone(self.publisher.release_pending())

    async def test_manual_publication_is_detected_without_a_second_post(self):
        await self.upload_banner()
        message = next(iter(self.messages.values()))
        message.flags.crossposted = True
        await self.publisher.cycle()
        message.publish.assert_not_awaited()
        self.assertEqual(self.rows()[0]['state'], 'published')

    async def test_lost_ack_is_reconciled_after_real_bot_restart_without_republishing(self):
        await self.upload_banner()
        message = next(iter(self.messages.values()))

        async def publish():
            message.flags.crossposted = True
            raise TimeoutError('Synthetic lost crosspost acknowledgment')

        message.publish.side_effect = publish
        await self.publisher.cycle()
        self.assertEqual(self.rows()[0]['state'], 'pending')
        await self.app.close()
        self.app = CommunityBot(self.temp.name)
        self.app._connection.user = SimpleNamespace(id=42)
        self.app.get_channel = lambda ident: self.channels.get(ident)
        self.app.store.clock = lambda: self.now
        self.app.health.storage_level = 'ok'
        self.relay = self.app.banners
        self.publisher = self.app.feed_publications
        self.now += 31
        await self.publisher.cycle()
        message.publish.assert_awaited_once()
        self.assertEqual(self.rows()[0]['state'], 'published')
        self.assertEqual(len(self.sent), 1)

    async def test_cancelled_publication_recovers_the_persisted_sending_phase(self):
        await self.upload_banner()
        message = next(iter(self.messages.values()))

        async def publish():
            message.flags.crossposted = True
            raise asyncio.CancelledError()

        message.publish.side_effect = publish
        with self.assertRaises(asyncio.CancelledError):
            await self.publisher.cycle()
        self.assertEqual(self.rows()[0]['state'], 'sending')
        self.publisher = FeedPublications(self.app)
        self.now += 31
        await self.publisher.cycle()
        message.publish.assert_awaited_once()
        self.assertEqual(self.rows()[0]['state'], 'published')

    async def test_permission_failure_in_one_guild_does_not_block_others_or_resend_images(self):
        await self.upload_banner((1, 2))
        self.channels[10].permissions_for.return_value.send_messages = False
        await self.publisher.cycle()
        self.assertEqual([row['state'] for row in self.rows()], ['pending', 'published'])
        self.assertIn('Grant', self.publisher.description('banner', 1))
        self.assertNotIn('waiting', self.publisher.description('banner', 2))
        self.assertIsNotNone(self.publisher.release_pending())
        self.channels[10].permissions_for.return_value.send_messages = True
        self.now += 301
        await self.publisher.cycle()
        self.assertTrue(all(row['state'] == 'published' for row in self.rows()))
        self.assertEqual(len(self.sent), 2)

    async def test_discord_rate_limit_defers_one_destination_and_allows_other_guilds(self):
        await self.upload_banner((1, 2))
        first = self.messages[10, '9001']
        first.publish.side_effect = discord.HTTPException(
            SimpleNamespace(status=429, reason='Too Many Requests'), {'code': 0, 'message': 'Synthetic rate limit'})
        await self.publisher.cycle()
        self.assertEqual([row['state'] for row in self.rows()], ['pending', 'published'])
        await self.publisher.cycle()
        first.publish.assert_awaited_once()
        self.assertEqual(len(self.sent), 2)

    async def test_native_rate_limit_wait_is_bounded_without_waiting_for_the_real_timeout(self):
        await self.upload_banner((1, 2))
        calls = []
        real_timeout = asyncio.timeout

        def short_timeout(seconds):
            calls.append(seconds)
            return real_timeout(0.01)

        async def waiting():
            await asyncio.sleep(30)

        self.messages[10, '9001'].publish.side_effect = waiting
        with patch('feed_publications.asyncio.timeout', short_timeout):
            await self.publisher.cycle()
        self.assertEqual(calls, [10, 10])
        self.assertEqual([row['state'] for row in self.rows()], ['pending', 'published'])

    async def test_already_crossposted_race_is_treated_as_confirmed(self):
        await self.upload_banner()
        message = next(iter(self.messages.values()))
        message.publish.side_effect = discord.HTTPException(
            SimpleNamespace(status=400, reason='Bad Request'), {'code': 40033, 'message': 'Already crossposted'})
        await self.publisher.cycle()
        self.assertEqual(self.rows()[0]['state'], 'published')

    async def test_deleted_message_is_never_recreated(self):
        await self.upload_banner()
        self.channels[10].fetch_message.side_effect = discord.NotFound(
            SimpleNamespace(status=404, reason='Not Found'), {'code': 10008, 'message': 'Unknown Message'})
        await self.publisher.cycle()
        self.assertEqual(self.rows()[0]['state'], 'gone')
        self.assertIsNone(self.publisher.release_pending())
        self.assertEqual(len(self.sent), 1)

    async def test_other_authors_webhooks_followed_copies_and_unrecognized_files_are_never_published(self):
        for field, value in (
                ('author', SimpleNamespace(id=77)), ('webhook_id', 88),
                ('flags', discord.MessageFlags._from_value(2)),
                ('attachments', [SimpleNamespace(filename='conversation.png')])):
            with self.subTest(field=field):
                self.now += 1
                await self.relay.accept(self.event(message_id=str(123456789012345678 + int(self.now))))
                self.relay.configure(1, 10)
                await self.relay.cycle()
                message = list(self.messages.values())[-1]
                setattr(message, field, value)
                await self.publisher.cycle()
                message.publish.assert_not_awaited()
                self.assertEqual(self.rows()[-1]['state'], 'ignored')

    async def test_retargeting_or_disabling_before_publication_drops_the_old_destination(self):
        await self.upload_banner()
        self.publisher.prepare()
        row = self.rows()[0]
        self.relay.configure(1, 11)
        await self.publisher.publish(row)
        next(iter(self.messages.values())).publish.assert_not_awaited()
        await self.publisher.cycle()
        self.assertEqual(self.rows(), [])
        self.assertIsNone(self.publisher.release_pending())

    async def test_expired_receipts_are_pruned_without_publishing_old_banners(self):
        await self.upload_banner()
        self.publisher.prepare()
        self.now += self.relay.max_age + 1
        await self.publisher.cycle()
        self.assertEqual(self.rows(), [])
        next(iter(self.messages.values())).publish.assert_not_awaited()

    async def test_target_is_rechecked_after_fetch_without_holding_the_image_delivery_lock(self):
        await self.upload_banner()
        message = next(iter(self.messages.values()))

        async def moved(ident):
            self.assertFalse(self.app.guild_lock(1).locked())
            self.relay.configure(1, 11)
            return message

        self.channels[10].fetch_message.side_effect = moved
        await self.publisher.cycle()
        message.publish.assert_not_awaited()

    async def test_uncertain_upload_does_not_crosspost_until_the_image_delivery_is_confirmed(self):
        await self.upload_banner()
        with self.relay.db:
            self.relay.db.execute("UPDATE banner_image_receipts SET state='uncertain'")
        await self.publisher.cycle()
        self.assertEqual(self.rows(), [])
        with self.relay.db:
            self.relay.db.execute("UPDATE banner_image_receipts SET state='sent'")
        await self.publisher.cycle()
        self.assertEqual(self.rows()[0]['state'], 'published')

    async def test_legacy_confirmed_images_are_published_in_place_without_reactions_or_new_uploads(self):
        await self.upload_banner()
        with self.relay.db:
            self.relay.db.execute("UPDATE banner_image_receipts SET state='legacy'")
        await self.publisher.cycle()
        self.assertEqual(self.rows()[0]['state'], 'published')
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.relay.db.execute('SELECT count(*) FROM banner_vote_order_repairs').fetchone()[0], 0)

    async def test_real_sdk_uses_the_crosspost_endpoint_for_the_existing_message(self):
        await self.upload_banner()
        channel = self.channels[10]
        channel._state = self.app._connection
        partial = discord.PartialMessage(channel=channel, id=9001)
        self.app.http.publish_message = AsyncMock()
        self.messages[10, '9001'].publish.side_effect = partial.publish
        await self.publisher.cycle()
        self.app.http.publish_message.assert_awaited_once_with(10, 9001)
        self.assertEqual(len(self.sent), 1)

    async def test_update_log_waits_for_crossposting_and_no_update_log_message_is_enqueued(self):
        await self.upload_banner()
        with patch.object(self.relay.votes, 'release_pending', return_value=None):
            self.assertFalse(self.app.community.update_complete())
            await self.publisher.cycle()
            self.assertTrue(self.app.community.update_complete())
        self.assertEqual({row['channel_id'] for row in self.rows()}, {'10'})

    async def test_critical_storage_does_not_start_publishing_work(self):
        await self.upload_banner()
        self.app.health.storage_level = 'critical'
        await self.publisher.cycle()
        self.assertEqual(self.rows(), [])
        next(iter(self.messages.values())).publish.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
