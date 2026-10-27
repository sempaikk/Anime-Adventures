"""Authorized historical vote reset: ordering, scope and interrupted operations."""

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

import discord

from banner_votes import BannerVotes
from community_hub import CENTRAL_GUILD_ID
import test_banner_votes as fixtures


class BannerVoteOrderCase(unittest.IsolatedAsyncioTestCase):
    asyncTearDown = fixtures.BannerVoteCase.asyncTearDown
    add_channel = fixtures.BannerVoteCase.add_channel
    send = fixtures.BannerVoteCase.send
    event = fixtures.BannerVoteCase.event
    emoji = fixtures.BannerVoteCase.emoji
    message = fixtures.BannerVoteCase.message
    history_page = fixtures.BannerVoteCase.history_page
    publish = fixtures.BannerVoteCase.publish

    async def asyncSetUp(self):
        await fixtures.BannerVoteCase.asyncSetUp(self)
        self.relay.disable(1)
        self.channel = self.add_channel(CENTRAL_GUILD_ID, 30)
        self.channel.permissions_for.return_value.add_reactions = True
        self.channel.permissions_for.return_value.manage_messages = True
        self.channel.get_partial_message.side_effect = lambda ident: self.message(ident, channel=self.channel)
        self.relay.configure(CENTRAL_GUILD_ID, 30)
        await self.votes.ensure_emojis()

    def voted_banner(self, *, channel=None, ident=900):
        message = self.message(ident, channel=channel or self.channel)
        message.reactions = [SimpleNamespace(emoji=self.registry[index], me=True, count=count)
                             for index, count in ((1, 2), (0, 1), (2, 1))]
        return message

    def owned(self, message):
        return [reaction for reaction in message.reactions
                if getattr(reaction.emoji, 'id', None) in {emoji.id for emoji in self.registry}]

    async def test_resets_only_misordered_wml_once_and_preserves_unrelated_reactions(self):
        message = self.voted_banner()
        unrelated = SimpleNamespace(emoji='👍', me=False, count=7)
        message.reactions.append(unrelated)
        self.history_page([message], 30)
        await self.votes.cycle()
        self.assertEqual([reaction.emoji.name for reaction in self.owned(message)], ['win', 'mid', 'lose'])
        self.assertEqual([reaction.count for reaction in self.owned(message)], [1, 1, 1])
        self.assertIn(unrelated, message.reactions)
        self.assertEqual(unrelated.count, 7)
        self.assertEqual(message.clear_reaction.await_count, 3)
        message.clear_reactions.assert_not_awaited()
        message.edit.assert_not_awaited()
        message.delete.assert_not_awaited()
        self.assertEqual(self.sent, [])
        self.assertEqual(self.relay.db.execute('SELECT phase FROM banner_vote_order_repairs').fetchone()[0], 'done')

        # Even an explicit history rescan must preserve votes cast after repair.
        self.owned(message)[1].count += 1
        with self.relay.db:
            self.relay.db.execute('UPDATE banner_vote_backfill SET done=0,before_id=NULL,next_scan=0')
        self.now += 61
        self.votes = BannerVotes(self.relay)
        await self.votes.cycle()
        self.assertEqual(message.clear_reaction.await_count, 3)
        self.assertEqual([reaction.count for reaction in self.owned(message)], [1, 2, 1])

    async def test_keeps_existing_votes_when_order_and_names_are_already_correct(self):
        message = self.voted_banner()
        message.reactions[:] = sorted(message.reactions, key=lambda reaction: reaction.emoji.id)
        self.history_page([message], 30)
        await self.votes.cycle()
        self.assertEqual([reaction.count for reaction in message.reactions], [1, 2, 1])
        message.clear_reaction.assert_not_awaited()
        self.assertEqual(self.relay.db.execute('SELECT count(*) FROM banner_vote_order_repairs').fetchone()[0], 0)

    async def test_does_not_reset_messages_created_after_the_channel_cutoff(self):
        message = self.voted_banner()
        self.app.store.set('banner-vote-order-cutoff:1:30', '800')
        self.history_page([message], 30)
        await self.votes.cycle()
        message.clear_reaction.assert_not_awaited()
        self.assertEqual([reaction.count for reaction in message.reactions], [2, 1, 1])

    async def test_repairs_all_configured_guilds_with_independent_restart_safe_receipts(self):
        messages = []
        for guild_id, channel_id in ((CENTRAL_GUILD_ID, 30), (1, 10), (2, 20)):
            channel = self.channels[channel_id]
            channel.permissions_for.return_value.manage_messages = True
            self.relay.configure(guild_id, channel_id)
            message = self.voted_banner(channel=channel)
            self.history_page([message], channel_id)
            messages.append(message)
        for _ in messages:
            await self.votes.cycle()
            self.now += 31
        for message in messages:
            self.assertEqual(message.clear_reaction.await_count, 3)
            self.assertEqual([reaction.emoji.name for reaction in self.owned(message)], ['win', 'mid', 'lose'])
            self.owned(message)[1].count += 1
        rows = self.relay.db.execute('SELECT guild_id,phase FROM banner_vote_order_repairs').fetchall()
        self.assertEqual({row['guild_id'] for row in rows}, {str(CENTRAL_GUILD_ID), '1', '2'})
        self.assertTrue(all(row['phase'] == 'done' for row in rows))
        self.votes = BannerVotes(self.relay)
        for _ in messages:
            await self.votes.cycle()
            self.now += 31
        for message in messages:
            self.assertEqual(message.clear_reaction.await_count, 3)
            self.assertEqual([reaction.count for reaction in self.owned(message)], [1, 2, 1])

    async def test_migrates_old_cutoff_without_restarting_completed_channels_or_limiting_new_guilds(self):
        self.app.store.set('banner-vote-order-cutoff:1', '1000')
        self.app.store.set('banner-vote-order-scan:1:30', '1')
        with self.relay.db:
            self.relay.db.execute('''INSERT INTO banner_vote_backfill(guild_id,channel_id,done,rated)
                VALUES(?,?,1,37)''', (str(CENTRAL_GUILD_ID), '30'))
        self.channel.permissions_for.return_value.manage_messages = True
        self.channels[10].permissions_for.return_value.manage_messages = True
        self.relay.configure(1, 10)
        message = self.voted_banner(channel=self.channels[10], ident=2000)
        self.history_page([message])
        await self.votes.cycle()
        self.assertEqual(self.votes.order.cutoffs['30'], 1000)
        self.assertGreater(self.votes.order.cutoffs['10'], 2000)
        self.assertEqual(message.clear_reaction.await_count, 3)
        row = self.relay.db.execute('SELECT done,rated FROM banner_vote_backfill WHERE channel_id=?', ('30',)).fetchone()
        self.assertEqual((row['done'], row['rated']), (1, 37))

    async def test_does_not_clear_an_unconfigured_channel_in_a_connected_guild(self):
        channel = self.add_channel(CENTRAL_GUILD_ID, 40)
        channel.permissions_for.return_value.manage_messages = True
        self.votes.order.prepare_scan()
        message = self.voted_banner(channel=channel)
        self.assertFalse(await self.votes.order.repair(message, channel))
        message.clear_reaction.assert_not_awaited()

    async def test_one_guild_missing_permission_does_not_block_or_mislabel_another_guild(self):
        blocked = self.voted_banner()
        self.channel.permissions_for.return_value.manage_messages = False
        self.history_page([blocked], 30)
        self.relay.configure(1, 10)
        self.channels[10].permissions_for.return_value.manage_messages = True
        other = self.voted_banner(channel=self.channels[10])
        self.history_page([other])
        for _ in range(2):
            await self.votes.cycle()
            self.now += 10
        blocked.clear_reaction.assert_not_awaited()
        self.assertEqual(other.clear_reaction.await_count, 3)
        self.assertIn('Manage Messages', self.votes.description(CENTRAL_GUILD_ID))
        self.assertNotIn('Manage Messages', self.votes.description(1))

    async def test_missing_manage_messages_pauses_repair_without_blocking_images(self):
        message = self.voted_banner()
        self.history_page([message], 30)
        self.channel.permissions_for.return_value.manage_messages = False
        await self.votes.cycle()
        message.clear_reaction.assert_not_awaited()
        self.assertIn('Manage Messages', self.votes.description(CENTRAL_GUILD_ID))
        self.assertIsNone(self.relay.db.execute('SELECT before_id FROM banner_vote_backfill').fetchone()[0])
        await self.publish()
        self.assertEqual(len(self.sent), 1)
        self.channel.permissions_for.return_value.manage_messages = True
        self.now += 61
        await self.votes.cycle()
        self.assertEqual([reaction.count for reaction in self.owned(message)], [1, 1, 1])

    async def test_lost_clear_ack_resumes_from_a_fresh_snapshot_without_duplicate_clears(self):
        message = self.voted_banner()
        clear = message.clear_reaction.side_effect

        async def lost(emoji):
            await clear(emoji)
            message.clear_reaction.side_effect = clear
            raise TimeoutError('Lost reaction clear acknowledgment')

        message.clear_reaction.side_effect = lost
        self.history_page([message], 30)
        await self.votes.cycle()
        self.assertEqual(message.add_reaction.await_count, 0)
        self.now += 61
        self.votes = BannerVotes(self.relay)
        await self.votes.cycle()
        self.assertEqual(message.clear_reaction.await_count, 3)
        self.assertEqual([reaction.emoji.name for reaction in self.owned(message)], ['win', 'mid', 'lose'])

    async def test_lost_seed_ack_never_repeats_clears_or_erases_new_votes_after_restart(self):
        message = self.voted_banner()
        add = message.add_reaction.side_effect

        async def lost(emoji):
            await add(emoji)
            if emoji.name == 'mid':
                message.add_reaction.side_effect = add
                raise TimeoutError('Lost restored-reaction acknowledgment')

        message.add_reaction.side_effect = lost
        self.history_page([message], 30)
        await self.votes.cycle()
        self.assertEqual(message.clear_reaction.await_count, 3)
        self.owned(message)[1].count += 1
        self.now += 61
        self.votes = BannerVotes(self.relay)
        # Clearing permission is no longer needed to finish the seeding phase.
        self.channel.permissions_for.return_value.manage_messages = False
        await self.votes.cycle()
        self.assertEqual(message.clear_reaction.await_count, 3)
        self.assertEqual([reaction.emoji.name for reaction in self.owned(message)], ['win', 'mid', 'lose'])
        self.assertEqual([reaction.count for reaction in self.owned(message)], [1, 2, 1])

    async def test_real_sdk_uses_only_the_three_custom_emoji_clear_endpoints(self):
        message = self.voted_banner()
        message.channel, message._state = self.channel, self.app._connection
        self.votes.emojis = tuple(discord.PartialEmoji(name=emoji.name, id=emoji.id) for emoji in self.registry)
        self.votes.order.prepare_scan()
        message.clear_reaction = discord.PartialMessage.clear_reaction.__get__(message)
        message.add_reaction = discord.PartialMessage.add_reaction.__get__(message)
        self.app.http.clear_single_reaction = AsyncMock()
        self.app.http.clear_reactions = AsyncMock(side_effect=AssertionError('Must preserve unrelated reactions'))
        self.app.http.add_reaction = AsyncMock()
        self.assertTrue(await self.votes.order.repair(message, self.channel))
        expected = ['win:300', 'mid:301', 'lose:302']
        self.assertEqual([call.args[2] for call in self.app.http.clear_single_reaction.await_args_list], expected)
        self.assertEqual([call.args[2] for call in self.app.http.add_reaction.await_args_list], expected)
        self.app.http.clear_reactions.assert_not_awaited()
