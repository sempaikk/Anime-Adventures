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
            emoji = SimpleNamespace(name=name, id=300 + len(self.registry))
            self.registry.append(emoji)
            return emoji

        self.app.create_application_emoji = AsyncMock(side_effect=create)
        for channel in self.channels.values():
            channel.permissions_for.return_value.add_reactions = True
            channel.get_partial_message.side_effect = lambda ident, c=channel: self.message(ident, channel=c)
        self.relay.configure(1, 10)

    def message(self, ident, *, channel=None, author=42, filename='banner-aaaaaaaaaaaaaaaa-0.png', webhook=None):
        message = SimpleNamespace(id=ident, author=SimpleNamespace(id=author), webhook_id=webhook,
                                  attachments=[SimpleNamespace(filename=filename)], reactions=[],
                                  edit=AsyncMock(), delete=AsyncMock())
        channel = channel or self.channels[10]

        async def add(emoji):
            self.reaction_calls.append((channel.id, ident, emoji.id))
            self.reacted.add((channel.id, ident, emoji.id))
            message.reactions.append(SimpleNamespace(emoji=emoji, me=True))

        message.add_reaction = AsyncMock(side_effect=add)
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
        for call, digest in zip(self.app.create_application_emoji.call_args_list, expected):
            self.assertEqual(hashlib.sha256(call.kwargs['image']).hexdigest(), digest)
            with Image.open(io.BytesIO(call.kwargs['image'])) as image:
                self.assertEqual((image.size, image.mode), ((40, 40), 'RGBA'))
        restarted = BannerVotes(self.relay)
        await restarted.cycle()
        self.assertEqual(self.app.create_application_emoji.await_count, 3)

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
