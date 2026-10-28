"""Direct bot feeds continue while retired announcement forwarding stays inert."""

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

import discord

from community_bot import CommunityBot
from game_sources import DAILY_CHANNEL_ID
import test_banner_votes as fixtures


class DirectFeedsCase(unittest.IsolatedAsyncioTestCase):
    asyncTearDown = fixtures.BannerVoteCase.asyncTearDown
    add_channel = fixtures.BannerVoteCase.add_channel
    send = fixtures.BannerVoteCase.send
    event = fixtures.BannerVoteCase.event
    emoji = fixtures.BannerVoteCase.emoji
    message = fixtures.BannerVoteCase.message

    async def asyncSetUp(self):
        await fixtures.BannerVoteCase.asyncSetUp(self)
        self.app.store.clock = lambda: self.now
        self.app.daily.clock = lambda: self.now
        self.app.daily.download = AsyncMock(return_value=self.blob)
        self.app.http.publish_message = AsyncMock(side_effect=AssertionError('Announcement forwarding was removed'))
        self.add_channel(3, 30)
        for channel in self.channels.values():
            channel.type = discord.ChannelType.text if channel.id == 20 else discord.ChannelType.news
            channel.permissions_for.return_value.add_reactions = True
            channel.get_partial_message.side_effect = lambda ident, c=channel: self.message(ident, channel=c)
            channel.fetch_message = AsyncMock(side_effect=AssertionError('No crosspost lookup is needed'))

    def seed_legacy_queue(self):
        # Exact old table shape: data can survive a deployment, but no worker
        # should consume it or require a database reset to disable forwarding.
        with self.relay.db:
            self.relay.db.execute('''CREATE TABLE feed_publications(
                kind TEXT NOT NULL,guild_id TEXT NOT NULL,channel_id TEXT NOT NULL,message_id TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'pending',next_attempt REAL NOT NULL DEFAULT 0,
                expires_at REAL NOT NULL,issue TEXT NOT NULL DEFAULT '',PRIMARY KEY(kind,channel_id,message_id))''')
            self.relay.db.executemany('''INSERT INTO feed_publications
                (kind,guild_id,channel_id,message_id,state,expires_at) VALUES(?,?,?,?,?,?)''',
                [('banner', '1', '10', '800', 'pending', self.now + 3600),
                 ('daily', '2', '20', '801', 'sending', self.now + 3600)])

    async def deliver(self, guilds=(1,)):
        for guild_id in guilds:
            self.relay.configure(guild_id, guild_id * 10)
            self.app.daily.configure(guild_id, guild_id * 10)
        await self.relay.accept(self.event())
        await self.app.daily.accept(self.event(channel_id=str(DAILY_CHANNEL_ID)))
        await asyncio.gather(self.app.banner_loop.coro(self.app), self.app.daily_loop.coro(self.app))

    async def restart(self):
        await self.app.close()
        self.app = CommunityBot(self.temp.name)
        self.app._connection.user = SimpleNamespace(id=42)
        self.app.health.storage_level = 'ok'
        self.app.get_channel = lambda ident: self.channels.get(ident)
        self.app.store.clock = lambda: self.now
        self.app.http.send_message = AsyncMock(side_effect=self.send)
        self.app.http.publish_message = AsyncMock(side_effect=AssertionError('No legacy publication retry'))
        self.relay = self.app.banners
        self.relay.clock = lambda: self.now
        self.relay.download = AsyncMock(return_value=self.blob)
        self.app.daily.clock = lambda: self.now
        self.app.daily.status = 'ready'
        self.app.daily.download = AsyncMock(return_value=self.blob)

    async def test_all_guilds_receive_direct_images_and_banner_votes_without_publishing_to_followers(self):
        await self.deliver((1, 2, 3))
        for _ in range(3):
            await self.votes.cycle()
        self.assertEqual(len(self.sent), 6)
        self.assertEqual([sum(item['channel'] == ident for item in self.sent) for ident in (10, 20, 30)], [2, 2, 2])
        self.assertEqual(len(self.reaction_calls), 9)
        self.assertTrue(all(row['reactions'] == 7 for row in self.relay.db.execute('SELECT reactions FROM banner_image_receipts')))
        self.assertTrue(all(not item['payload'].get('content') and not item['payload'].get('embeds') for item in self.sent))
        self.app.http.publish_message.assert_not_awaited()
        for channel in self.channels.values():
            channel.fetch_message.assert_not_awaited()
        self.assertEqual(self.channels[10].type, discord.ChannelType.news)
        self.assertFalse(hasattr(self.app, 'feed_publications_loop'))

    async def test_old_pending_and_sending_publications_remain_inert_after_restart(self):
        self.seed_legacy_queue()
        await self.restart()
        await self.deliver((1, 2))
        self.assertEqual(len(self.sent), 4)
        self.app.http.publish_message.assert_not_awaited()
        self.assertFalse(hasattr(self.app, 'feed_publications'))
        rows = self.relay.db.execute('SELECT state FROM feed_publications ORDER BY message_id').fetchall()
        self.assertEqual([row['state'] for row in rows], ['pending', 'sending'])

    async def test_both_feed_hash_receipts_survive_restart_without_duplicate_downloads_or_uploads(self):
        await self.deliver((1, 2, 3))
        await self.restart()
        await self.deliver((1, 2, 3))
        self.assertEqual(len(self.sent), 6)
        self.relay.download.assert_not_awaited()
        self.app.daily.download.assert_not_awaited()
        self.app.http.publish_message.assert_not_awaited()

    async def test_retired_queue_does_not_block_release_notices_or_claim_publishing_in_private_status(self):
        self.seed_legacy_queue()
        await self.votes.cycle()
        self.assertTrue(self.app.community.update_complete())
        self.assertNotIn('Announcement publishing', self.relay.description(1))
        self.assertNotIn('Announcement publishing', self.app.daily.description(2))
        self.app.http.publish_message.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
