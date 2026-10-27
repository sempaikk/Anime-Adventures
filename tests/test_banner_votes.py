"""Exact uploaded assets, independent reactions and safe resumable history scanning."""

import hashlib
import io
import json
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord
from PIL import Image

from banner_votes import BannerVotes
import test_banners as fixtures


class BannerVoteCase(unittest.IsolatedAsyncioTestCase):
    asyncTearDown = fixtures.BannerCase.asyncTearDown
    add_channel = fixtures.BannerCase.add_channel
    send = fixtures.BannerCase.send
    event = fixtures.BannerCase.event

    async def asyncSetUp(self):
        await fixtures.BannerCase.asyncSetUp(self)
        self.votes = self.relay.votes
        self.registry, self.reacted = [], set()
        self.reaction_calls = []
        self.app.fetch_application_emojis = AsyncMock(side_effect=lambda: list(self.registry))

        async def create(*, name, image):
            emoji = self.emoji(name, 300 + len(self.registry))
            self.registry.append(emoji)
            return emoji

        self.app.create_application_emoji = AsyncMock(side_effect=create)
        for channel in self.channels.values():
            channel.permissions_for.return_value.add_reactions = True
            channel.get_partial_message.side_effect = lambda ident, c=channel: self.message(ident, channel=c)
        self.relay.configure(1, 10)

    def emoji(self, name, ident):
        emoji = SimpleNamespace(name=name, id=ident)

        async def edit(*, name):
            updated = self.emoji(name, ident)
            self.registry[:] = [updated if item.id == ident else item for item in self.registry]
            return updated

        emoji.edit = AsyncMock(side_effect=edit)
        return emoji

    def legacy_emojis(self):
        manifest = Path(__file__).resolve().parents[1] / 'data/banner_votes.json'
        for index, item in enumerate(json.loads(manifest.read_text())['images']):
            self.registry.append(self.emoji(item['key'] + '_' + item['sha256'][:12], 300 + index))

    def message(self, ident, *, channel=None, author=42, filename='banner-aaaaaaaaaaaaaaaa-0.png', webhook=None):
        message = SimpleNamespace(id=ident, author=SimpleNamespace(id=author), webhook_id=webhook,
                                  attachments=[SimpleNamespace(filename=filename)], reactions=[],
                                  edit=AsyncMock(), delete=AsyncMock())
        channel = channel or self.channels[10]

        async def add(emoji):
            self.reaction_calls.append((channel.id, ident, emoji.id))
            self.reacted.add((channel.id, ident, emoji.id))
            existing = next((reaction for reaction in message.reactions if reaction.emoji.id == emoji.id), None)
            if existing:
                if not existing.me:
                    existing.count += 1
                existing.me, existing.emoji = True, emoji
            else:
                message.reactions.append(SimpleNamespace(emoji=emoji, me=True, count=1))

        async def remove(emoji, user):
            self.assertEqual(user.id, self.app.user.id)
            existing = next(reaction for reaction in message.reactions if reaction.emoji.id == emoji.id)
            if existing.me:
                existing.me = False
                existing.count -= 1
                if not existing.count:
                    message.reactions.remove(existing)
            self.reacted.discard((channel.id, ident, emoji.id))

        message.add_reaction = AsyncMock(side_effect=add)
        message.remove_reaction = AsyncMock(side_effect=remove)
        return message

    def history_page(self, messages):
        def page(*, limit, before=None, **kwargs):
            selected = [m for m in messages if before is None or m.id < before.id][:limit]
            return fixtures.iterate(selected)
        self.channels[10].history.side_effect = page

    async def publish(self):
        await self.relay.accept(self.event())
        await self.relay.cycle()

    async def test_original_png_bytes_are_registered_unchanged_and_reused_after_restart(self):
        expected = ['a695742eab67b392a44405b8aa641ce4319d67b4e9e79f2574137bfc371c0aae',
                    '5e9d55d0b029e4ee51c4aa27700fd5ea32485514856e9faf0a953477b7bc48c2',
                    'de701d7e4d4692e96fdfbb6d9f2684091f9b3f5791ef6d06d31152e15803f382']
        await self.votes.cycle()
        self.assertEqual(self.app.create_application_emoji.await_count, 3)
        self.assertEqual([emoji.name for emoji in self.votes.emojis], ['win', 'mid', 'lose'])
        for call, digest in zip(self.app.create_application_emoji.call_args_list, expected):
            self.assertEqual(hashlib.sha256(call.kwargs['image']).hexdigest(), digest)
            with Image.open(io.BytesIO(call.kwargs['image'])) as image:
                self.assertEqual((image.size, image.mode), ((40, 40), 'RGBA'))
        restarted = BannerVotes(self.relay)
        await restarted.cycle()
        self.assertEqual(self.app.create_application_emoji.await_count, 3)

    async def test_legacy_names_are_shortened_in_place_preserving_existing_votes(self):
        self.legacy_emojis()
        original = list(self.registry)
        message = self.message(900)
        message.reactions = [SimpleNamespace(emoji=emoji, me=True, count=5) for emoji in original]
        self.assertTrue(await self.votes.ensure_emojis())
        self.assertEqual([emoji.name for emoji in self.votes.emojis], ['win', 'mid', 'lose'])
        self.assertEqual([emoji.id for emoji in self.votes.emojis], [emoji.id for emoji in original])
        self.app.create_application_emoji.assert_not_awaited()
        for emoji, name in zip(original, ('win', 'mid', 'lose')):
            emoji.edit.assert_awaited_once_with(name=name)
        await self.votes.rate(message)
        message.add_reaction.assert_not_awaited()
        self.assertEqual([reaction.count for reaction in message.reactions], [5, 5, 5])
        self.now += 61
        self.assertTrue(await BannerVotes(self.relay).ensure_emojis())
        self.app.create_application_emoji.assert_not_awaited()
        for emoji in self.registry:
            emoji.edit.assert_not_awaited()

    async def test_lost_rename_ack_recovers_by_saved_id_after_restart_without_replacing_emojis(self):
        self.legacy_emojis()
        original_ids = [emoji.id for emoji in self.registry]
        edit = self.registry[0].edit.side_effect

        async def lost(**kwargs):
            await edit(**kwargs)
            raise TimeoutError('Lost rename acknowledgment')

        self.registry[0].edit.side_effect = lost
        self.assertFalse(await self.votes.ensure_emojis())
        self.assertEqual(self.registry[0].name, 'win')
        await self.publish()
        self.assertEqual(len(self.sent), 1)
        self.now += 61
        self.votes = BannerVotes(self.relay)
        self.assertTrue(await self.votes.ensure_emojis())
        self.assertEqual([emoji.name for emoji in self.votes.emojis], ['win', 'mid', 'lose'])
        self.assertEqual([emoji.id for emoji in self.votes.emojis], original_ids)
        self.app.create_application_emoji.assert_not_awaited()

    async def test_setup_does_not_report_ready_until_a_fresh_lookup_confirms_the_names(self):
        self.legacy_emojis()
        for emoji in self.registry:
            emoji.edit.side_effect = lambda *, name, ident=emoji.id: self.emoji(name, ident)
        self.assertFalse(await self.votes.ensure_emojis())
        self.assertFalse(self.votes.emojis)
        self.assertIn('awaiting Discord confirmation', self.votes.description(1))
        await self.publish()
        self.assertEqual(len(self.sent), 1)
        self.registry[:] = [self.emoji(name, emoji.id) for name, emoji in zip(('win', 'mid', 'lose'), self.registry)]
        self.now += 61
        self.assertTrue(await self.votes.ensure_emojis())
        self.assertIn('Discord-confirmed names: win, mid, lose', self.votes.description(1))
        self.app.create_application_emoji.assert_not_awaited()

    async def test_historical_names_refresh_only_the_bot_seed_preserving_member_votes(self):
        self.legacy_emojis()
        old = list(self.registry)
        message = self.message(900)
        message.reactions = [SimpleNamespace(emoji=emoji, me=True, count=5) for emoji in old]
        self.history_page([message])
        await self.votes.cycle()
        self.assertEqual([reaction.count for reaction in message.reactions], [5, 5, 5])
        self.assertEqual([reaction.emoji.id for reaction in message.reactions], [emoji.id for emoji in old])
        self.assertEqual(message.remove_reaction.await_count, 3)
        self.assertEqual(message.add_reaction.await_count, 3)
        for call in message.remove_reaction.await_args_list:
            self.assertIs(call.args[1], self.app.user)
        message.edit.assert_not_awaited()
        message.delete.assert_not_awaited()

    async def test_lost_seed_removal_ack_resumes_without_losing_member_votes(self):
        self.legacy_emojis()
        message = self.message(900)
        message.reactions = [SimpleNamespace(emoji=emoji, me=True, count=5) for emoji in self.registry]
        remove = message.remove_reaction.side_effect

        async def lost(emoji, user):
            await remove(emoji, user)
            message.remove_reaction.side_effect = remove
            raise TimeoutError('Lost own-reaction removal acknowledgment')

        message.remove_reaction.side_effect = lost
        self.history_page([message])
        await self.votes.cycle()
        self.assertEqual([reaction.count for reaction in message.reactions], [4, 5, 5])
        self.assertIsNone(self.relay.db.execute('SELECT before_id FROM banner_vote_backfill').fetchone()[0])
        self.now += 61
        self.votes = BannerVotes(self.relay)
        await self.votes.cycle()
        self.assertEqual([reaction.count for reaction in message.reactions], [5, 5, 5])
        self.assertTrue(all(reaction.me for reaction in message.reactions))
        self.assertEqual(self.relay.db.execute('SELECT done FROM banner_vote_backfill').fetchone()[0], 1)

    async def test_name_refresh_reopens_completed_history_once_and_keeps_the_cursor_after_restart(self):
        with self.relay.db:
            self.relay.db.execute('''INSERT INTO banner_vote_backfill(guild_id,channel_id,before_id,done,rated)
                VALUES('1','10','123',1,37)''')
        messages = [self.message(ident) for ident in (900, 800, 700, 600)]
        self.history_page(messages)
        await self.votes.cycle()
        row = self.relay.db.execute('SELECT * FROM banner_vote_backfill').fetchone()
        self.assertEqual((row['before_id'], row['done'], row['rated']), ('700', 0, 3))
        self.now += 61
        self.votes = BannerVotes(self.relay)
        await self.votes.cycle()
        row = self.relay.db.execute('SELECT * FROM banner_vote_backfill').fetchone()
        self.assertEqual((row['done'], row['rated']), (1, 4))

    async def test_real_sdk_renames_the_registry_and_refreshes_only_its_own_reaction(self):
        self.legacy_emojis()
        records = [{'id': str(emoji.id), 'name': emoji.name} for emoji in self.registry]
        self.app._connection.application_id = 4242
        self.app.fetch_application_emojis = discord.Client.fetch_application_emojis.__get__(self.app)
        self.app.http.get_application_emojis = AsyncMock(
            side_effect=lambda app_id: {'items': [dict(record) for record in records]})

        async def edit(app_id, emoji_id, *, payload):
            self.assertEqual(app_id, 4242)
            record = next(record for record in records if record['id'] == str(emoji_id))
            record.update(payload)
            return dict(record)

        self.app.http.edit_application_emoji = AsyncMock(side_effect=edit)
        self.assertTrue(await self.votes.ensure_emojis())
        self.assertEqual(self.app.http.get_application_emojis.await_count, 2)
        message = self.message(900)
        message.channel, message._state = self.channels[10], self.app._connection
        message.reactions = [SimpleNamespace(emoji=discord.PartialEmoji(name=emoji.name, id=emoji.id),
                                            me=True, count=5) for emoji in self.registry]
        message.add_reaction = discord.PartialMessage.add_reaction.__get__(message)
        message.remove_reaction = discord.PartialMessage.remove_reaction.__get__(message)
        self.app.http.add_reaction = AsyncMock()
        self.app.http.remove_own_reaction = AsyncMock()
        self.app.http.remove_reaction = AsyncMock(side_effect=AssertionError('Must not remove member votes'))
        await self.votes.rate(message, refresh_names=True)
        self.assertEqual(self.app.http.remove_own_reaction.await_count, 3)
        self.app.http.remove_reaction.assert_not_awaited()
        self.assertEqual([call.args[2] for call in self.app.http.add_reaction.await_args_list],
                         ['win:300', 'mid:301', 'lose:302'])
        self.app.create_application_emoji.assert_not_awaited()

    async def test_lost_emoji_creation_ack_does_not_create_a_duplicate(self):
        create = self.app.create_application_emoji.side_effect

        async def lost(**kwargs):
            emoji = await create(**kwargs)
            if len(self.registry) == 1:
                raise TimeoutError('Lost emoji acknowledgment')
            return emoji

        self.app.create_application_emoji.side_effect = lost
        await self.votes.cycle()
        self.now += 61
        await self.votes.cycle()
        self.assertEqual(len(self.registry), 3)
        self.assertEqual(self.app.create_application_emoji.await_count, 3)

    async def test_each_banner_gets_w_m_l_without_any_additional_image_post(self):
        await self.publish()
        await self.votes.cycle()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.reaction_calls, [(10, 9001, emoji.id) for emoji in self.registry])
        self.now += 31
        await self.votes.cycle()
        self.assertEqual(len(self.reaction_calls), 3)
        self.assertEqual(self.relay.db.execute('SELECT reactions FROM banner_image_receipts').fetchone()[0], 7)

    async def test_every_separate_image_gets_its_own_three_reactions(self):
        from test_banner_images import colored
        self.relay.download = AsyncMock(side_effect=[colored('red'), colored('green')])
        await self.relay.accept(self.event(images=['https://cdn.discordapp.com/attachments/1/2/one.png',
                                                  'https://cdn.discordapp.com/attachments/1/2/two.png']))
        await self.relay.cycle()
        await self.votes.cycle()
        self.assertEqual(len(self.sent), 2)
        self.assertEqual({item[1] for item in self.reacted}, {9001, 9002})
        self.assertEqual(len(self.reacted), 6)

    async def test_altered_asset_cannot_be_registered_or_block_image_delivery(self):
        folder = Path(self.temp.name)
        images = folder / 'assets/banner-votes'
        images.mkdir(parents=True)
        records = []
        for key in ('win', 'mid', 'lose'):
            (images / f'{key}.png').write_bytes(b'corrupted')
            records.append({'key': key, 'path': f'assets/banner-votes/{key}.png', 'sha256': '0' * 64})
        manifest = folder / 'votes.json'
        manifest.write_text(json.dumps({'schema': 1, 'images': records}))
        with patch('banner_votes.ROOT', folder), patch('banner_votes.ASSET_FILE', manifest):
            await self.votes.cycle()
        self.app.create_application_emoji.assert_not_awaited()
        await self.publish()
        self.assertEqual(len(self.sent), 1)

    async def test_mixed_daily_channel_does_not_rate_ambiguous_legacy_daily_messages(self):
        self.app.daily.configure(1, 10)
        old_daily = self.message(900)
        new_banner = self.message(800, filename='banner-bbbbbbbbbbbbbbbb.png')
        self.history_page([old_daily, new_banner])
        await self.votes.cycle()
        old_daily.add_reaction.assert_not_awaited()
        self.assertEqual({item[1] for item in self.reacted}, {800})

    async def test_missing_reaction_permission_preserves_images_and_retries_after_repair(self):
        self.channels[10].permissions_for.return_value.add_reactions = False
        await self.publish()
        await self.votes.cycle()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.reacted, set())
        self.assertIn('Add Reactions', self.votes.description(1))
        self.channels[10].permissions_for.return_value.add_reactions = True
        self.now += 31
        await self.votes.cycle()
        self.assertEqual(len(self.reacted), 3)
        self.assertEqual(len(self.sent), 1)

    async def test_partial_reaction_failure_survives_restart_without_extra_votes_or_uploads(self):
        await self.publish()
        message = self.message(9001)
        add = message.add_reaction.side_effect

        async def lost(emoji):
            await add(emoji)
            if len(self.reaction_calls) == 2:
                raise TimeoutError('Lost reaction acknowledgment')

        message.add_reaction.side_effect = lost
        self.channels[10].get_partial_message.return_value = message
        self.channels[10].get_partial_message.side_effect = None
        await self.votes.cycle()
        self.assertEqual(self.relay.db.execute('SELECT reactions FROM banner_image_receipts').fetchone()[0], 1)
        self.now += 31
        self.votes = BannerVotes(self.relay)
        await self.votes.cycle()
        self.assertEqual(len(self.reacted), 3)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.relay.db.execute('SELECT reactions FROM banner_image_receipts').fetchone()[0], 7)

    async def test_backfill_only_touches_bot_banner_images_and_preserves_old_messages(self):
        messages = [self.message(900), self.message(800, author=77), self.message(700, filename='report.png'),
                    self.message(600, webhook=999), self.message(500)]
        self.history_page(messages)
        await self.votes.cycle()
        self.assertEqual({item[1] for item in self.reacted}, {900, 500})
        self.assertEqual(len(self.reacted), 6)
        self.assertEqual(self.sent, [])
        for message in messages:
            message.edit.assert_not_awaited()
            message.delete.assert_not_awaited()
        row = self.relay.db.execute('SELECT * FROM banner_vote_backfill').fetchone()
        self.assertEqual((row['done'], row['rated'], row['scanned']), (1, 2, 5))

    async def test_historical_backfill_resumes_across_restarts_until_all_old_banners_are_rated(self):
        messages = [self.message(ident) for ident in (900, 800, 700, 600, 500, 400, 300)]
        self.history_page(messages)
        await self.votes.cycle()
        self.assertEqual(self.relay.db.execute('SELECT before_id FROM banner_vote_backfill').fetchone()[0], '700')
        self.votes = BannerVotes(self.relay)
        for _ in range(2):
            self.now += 31
            await self.votes.cycle()
        self.assertEqual(len(self.reacted), 21)
        self.assertEqual(len(self.reaction_calls), 21)
        row = self.relay.db.execute('SELECT * FROM banner_vote_backfill').fetchone()
        self.assertEqual((row['done'], row['rated']), (1, 7))
        reads = self.channels[10].history.call_count
        self.now += 31
        await self.votes.cycle()
        self.assertEqual(self.channels[10].history.call_count, reads)

    async def test_a_full_reaction_bar_does_not_stop_the_rest_of_the_history(self):
        full, next_message = self.message(900), self.message(800)
        full.add_reaction.side_effect = discord.HTTPException(
            SimpleNamespace(status=400, reason='Bad Request'), {'code': 30010, 'message': 'Maximum reactions'})
        self.history_page([full, next_message])
        await self.votes.cycle()
        self.assertEqual({item[1] for item in self.reacted}, {800})
        row = self.relay.db.execute('SELECT * FROM banner_vote_backfill').fetchone()
        self.assertEqual((row['done'], row['rated'], row['skipped']), (1, 1, 1))

    async def test_disabled_target_is_rechecked_after_history_fetch(self):
        message = self.message(900)

        async def history(**kwargs):
            self.relay.disable(1)
            yield message

        self.channels[10].history.side_effect = history
        await self.votes.cycle()
        self.assertEqual(self.reacted, set())

    async def test_history_failure_does_not_advance_cursor_or_block_new_banner_reactions(self):
        await self.publish()
        self.channels[10].history.side_effect = TimeoutError('History unavailable')
        await self.votes.cycle()
        self.assertEqual(len(self.reacted), 3)
        self.assertIsNone(self.relay.db.execute('SELECT before_id FROM banner_vote_backfill').fetchone()[0])

    async def test_emoji_setup_failure_cannot_block_banner_images(self):
        self.app.fetch_application_emojis.side_effect = TimeoutError('Emoji service unavailable')
        await self.votes.cycle()
        await self.publish()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.reacted, set())
