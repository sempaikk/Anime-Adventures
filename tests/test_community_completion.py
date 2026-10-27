"""Release announcements follow confirmed work in every guild, using private fixtures."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import discord

from banner_votes import BannerVotes
from community_hub import CommunityHub, CENTRAL_GUILD_ID, CENTRAL_UPDATE_CHANNEL_ID
import test_banner_vote_order as fixtures


class CommunityCompletionCase(unittest.IsolatedAsyncioTestCase):
    asyncTearDown = fixtures.BannerVoteOrderCase.asyncTearDown
    add_channel = fixtures.BannerVoteOrderCase.add_channel
    send = fixtures.BannerVoteOrderCase.send
    event = fixtures.BannerVoteOrderCase.event
    emoji = fixtures.BannerVoteOrderCase.emoji
    message = fixtures.BannerVoteOrderCase.message
    history_page = fixtures.BannerVoteOrderCase.history_page
    voted_banner = fixtures.BannerVoteOrderCase.voted_banner
    owned = fixtures.BannerVoteOrderCase.owned

    async def asyncSetUp(self):
        await fixtures.BannerVoteOrderCase.asyncSetUp(self)
        self.hub = self.app.community
        data = json.loads((Path(__file__).resolve().parents[1] / 'data/community_updates.json').read_text())
        self.app.build = {'version': data['version'], 'verified': True}
        self.app.store.clock = lambda: self.now
        guild = self.channel.guild
        guild.unavailable = False
        guild.get_channel = lambda ident: self.channels.get(ident)
        self.app.get_guild = lambda ident: guild if ident == CENTRAL_GUILD_ID else None
        self.updates = self.add_channel(CENTRAL_GUILD_ID, CENTRAL_UPDATE_CHANNEL_ID)
        self.updates.guild = guild
        self.app.http.send_message = AsyncMock(return_value={'id': '9999'})

    async def announce(self):
        self.now += 301
        await self.hub.publish_update()

    def assert_waiting(self):
        self.app.http.send_message.assert_not_awaited()
        self.assertIn('waiting', self.hub.status)
        self.assertIsNone(self.app.store.get(
            f'community-update:{CENTRAL_GUILD_ID}:{self.app.build["version"]}'))

    async def test_waits_for_all_guilds_and_partial_history_then_resumes_after_restart(self):
        self.relay.configure(1, 10)
        self.relay.configure(2, 20)
        self.channels[20].permissions_for.return_value.manage_messages = True
        banners = [self.voted_banner(channel=self.channels[20], ident=900 - index) for index in range(4)]
        self.history_page(banners, 20)
        # Even ready emojis do not prove that the migration has started.
        await self.announce()
        self.assert_waiting()
        # The official guild and the first player's guild finish first.
        await self.votes.cycle()
        await self.votes.cycle()
        await self.announce()
        self.assert_waiting()
        await self.votes.cycle()
        self.assertEqual(sum(message.clear_reaction.await_count for message in banners), 9)
        await self.announce()
        self.assert_waiting()
        self.relay.votes = self.votes = BannerVotes(self.relay)
        self.hub = CommunityHub(self.app)
        await self.announce()
        self.assert_waiting()
        await self.votes.cycle()
        await self.announce()
        self.app.http.send_message.assert_awaited_once()
        self.assertEqual(self.app.http.send_message.call_args.args[0], CENTRAL_UPDATE_CHANNEL_ID)
        self.assertEqual(sum(message.clear_reaction.await_count for message in banners), 12)
        # Restarting and a new member vote cannot trigger another reset or notice.
        self.owned(banners[0])[1].count += 1
        self.relay.votes = self.votes = BannerVotes(self.relay)
        self.hub = CommunityHub(self.app)
        await self.votes.cycle()
        await self.announce()
        self.app.http.send_message.assert_awaited_once()
        self.assertEqual(self.owned(banners[0])[1].count, 2)
        self.assertEqual(sum(message.clear_reaction.await_count for message in banners), 12)

    async def test_missing_permission_in_a_player_server_delays_notice_until_repaired(self):
        self.relay.configure(1, 10)
        banner = self.voted_banner(channel=self.channels[10])
        self.history_page([banner])
        await self.votes.cycle()
        await self.votes.cycle()
        await self.announce()
        self.assert_waiting()
        self.assertIn('Manage Messages', self.votes.description(1))
        self.channels[10].permissions_for.return_value.manage_messages = True
        await self.votes.cycle()
        await self.announce()
        self.app.http.send_message.assert_awaited_once()

    async def test_lost_reaction_ack_delays_notice_without_clearing_new_votes_on_retry(self):
        banner = self.voted_banner()
        add = banner.add_reaction.side_effect

        async def lost_ack(emoji):
            await add(emoji)
            raise TimeoutError('Synthetic lost reaction acknowledgment')

        banner.add_reaction.side_effect = lost_ack
        self.history_page([banner], 30)
        await self.votes.cycle()
        await self.announce()
        self.assert_waiting()
        self.owned(banner)[0].count += 1
        banner.add_reaction.side_effect = add
        await self.votes.cycle()
        await self.announce()
        self.app.http.send_message.assert_awaited_once()
        self.assertEqual([reaction.count for reaction in self.owned(banner)], [2, 1, 1])
        self.assertEqual(banner.clear_reaction.await_count, 3)

    async def test_completed_scan_with_reaction_limit_is_not_announced_as_success(self):
        banner = self.message(900, channel=self.channel)
        banner.add_reaction.side_effect = discord.HTTPException(
            SimpleNamespace(status=400, reason='Bad Request'),
            {'code': 30010, 'message': 'Maximum reactions reached'})
        self.history_page([banner], 30)
        await self.votes.cycle()
        row = self.relay.db.execute('SELECT done,skipped FROM banner_vote_backfill').fetchone()
        self.assertEqual((row['done'], row['skipped']), (1, 1))
        await self.announce()
        self.assert_waiting()
        self.assertIn('reaction limit', self.hub.status)

    async def test_live_reaction_confirmation_and_active_work_lock_delay_publication(self):
        # Start with a finished historical scan but a freshly delivered image.
        await self.votes.cycle()
        with self.relay.db:
            self.relay.db.execute('''INSERT INTO banner_image_receipts
                (source_message,digest,guild_id,channel_id,filename,state,message_id,expires_at)
                VALUES('source','digest',?,'30','banner-aaaaaaaaaaaaaaaa.png','sent','999',?)''',
                (str(CENTRAL_GUILD_ID), self.now + 3600))
        await self.announce()
        self.assert_waiting()
        with self.relay.db:
            self.relay.db.execute('UPDATE banner_image_receipts SET reactions=7')
        async with self.votes.lock:
            await self.announce()
            self.assert_waiting()
        await self.announce()
        self.app.http.send_message.assert_awaited_once()

    async def test_removed_targets_and_expired_live_receipts_do_not_block_current_work(self):
        self.relay.configure(1, 10)
        self.relay.disable(1)
        with self.relay.db:
            self.relay.db.execute('''INSERT INTO banner_vote_order_repairs
                (guild_id,channel_id,message_id) VALUES('1','10','900')''')
            self.relay.db.execute('''INSERT INTO banner_image_receipts
                (source_message,digest,guild_id,channel_id,filename,state,message_id,expires_at)
                VALUES('source','digest',?,'30','banner-aaaaaaaaaaaaaaaa.png','sent','999',?)''',
                (str(CENTRAL_GUILD_ID), self.now - 1))
        await self.votes.cycle()
        await self.announce()
        self.app.http.send_message.assert_awaited_once()

    async def test_future_notice_without_optional_wml_flag_still_waits_for_completion(self):
        path = Path(self.temp.name) / 'future-notes.json'
        path.write_text(json.dumps({'schema': 1, 'version': self.app.build['version'],
                                    'changes': ['Uma melhoria visível para os membros.']}))
        with patch('community_hub.UPDATES_PATH', path):
            await self.announce()
            self.assert_waiting()
            await self.votes.cycle()
            await self.announce()
        self.app.http.send_message.assert_awaited_once()

    async def test_rechecks_completion_after_an_await_before_creating_notice_receipt(self):
        await self.votes.cycle()

        async def new_destination(guild):
            await asyncio.sleep(0)
            self.relay.configure(1, 10)
            return False

        self.hub.correct_legacy_notice = AsyncMock(side_effect=new_destination)
        await self.announce()
        self.assert_waiting()

    async def test_incomplete_repair_receipt_does_not_count_as_finished(self):
        await self.votes.cycle()
        with self.relay.db:
            self.relay.db.execute('''INSERT INTO banner_vote_order_repairs
                (guild_id,channel_id,message_id,phase,cleared,seeded) VALUES(?,'30','900','seed',7,1)''',
                (str(CENTRAL_GUILD_ID),))
        await self.announce()
        self.assert_waiting()
        self.assertIn('repair', self.hub.status)


if __name__ == '__main__':
    unittest.main()
