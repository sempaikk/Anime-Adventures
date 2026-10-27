"""Per-image delivery, source edits, legacy receipts and interrupted uploads."""

import asyncio
import io
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from PIL import Image

from community_bot import CommunityBot
from game_sources import DAILY_CHANNEL_ID
import test_banners as fixtures


def colored(color):
    out = io.BytesIO()
    Image.new('RGB', (160, 90), color).save(out, 'PNG')
    return out.getvalue()


class ImageDeliveryCase(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.BannerCase.asyncSetUp
    asyncTearDown = fixtures.BannerCase.asyncTearDown
    add_channel = fixtures.BannerCase.add_channel
    send = fixtures.BannerCase.send
    event = fixtures.BannerCase.event
    interaction = fixtures.BannerCase.interaction
    jobs = fixtures.BannerCase.jobs

    async def accept_images(self, colors):
        blobs = [colored(color) for color in colors]
        self.relay.download = AsyncMock(side_effect=blobs)
        event = self.event(images=[f'https://cdn.discordapp.com/attachments/1/2/{index}.png' for index in range(len(blobs))])
        await self.relay.accept(event)
        return blobs

    def receipt_history(self, item, ident):
        return SimpleNamespace(id=ident, author=SimpleNamespace(id=42), webhook_id=None,
                               nonce=item['payload']['nonce'], attachments=[SimpleNamespace(filename=f['filename']) for f in item['files']])

    async def test_each_image_has_its_own_message_with_original_bytes_and_nonce(self):
        self.relay.configure(1, 10)
        blobs = await self.accept_images(['red', 'green', 'blue'])
        await self.relay.cycle()
        self.assertEqual(len(self.sent), 3)
        self.assertEqual([item['files'][0]['blob'] for item in self.sent], blobs)
        self.assertTrue(all(len(item['files']) == 1 for item in self.sent))
        self.assertEqual(len({item['payload']['nonce'] for item in self.sent}), 3)
        for item in self.sent:
            self.assertFalse(item['payload'].get('content'))
            self.assertFalse(item['payload'].get('embeds'))
            self.assertTrue(item['payload']['enforce_nonce'])
        self.assertEqual(self.jobs()[0]['state'], 'sent')

    async def test_second_image_lost_ack_does_not_repeat_first_or_third(self):
        self.relay.configure(1, 10)
        await self.accept_images(['red', 'green', 'blue'])

        async def send(channel_id, *, params):
            response = await self.send(channel_id, params=params)
            if len(self.sent) == 2:
                self.history[10] = [self.receipt_history(self.sent[-1], response['id'])]
                raise TimeoutError('Lost image acknowledgment')
            return response

        self.app.http.send_message.side_effect = send
        await self.relay.cycle()
        self.assertEqual(len(self.sent), 3)
        self.assertEqual(self.jobs()[0]['state'], 'uncertain')
        self.now += 31
        await self.relay.cycle()
        self.assertEqual(len(self.sent), 3)
        self.assertEqual(self.jobs()[0]['state'], 'sent')

    async def test_restart_during_upload_recovers_receipt_and_sends_only_remaining_images(self):
        self.relay.configure(1, 10)
        await self.accept_images(['red', 'green', 'blue'])

        async def interrupted(channel_id, *, params):
            response = await self.send(channel_id, params=params)
            self.history[10] = [self.receipt_history(self.sent[-1], response['id'])]
            raise asyncio.CancelledError()

        self.app.http.send_message.side_effect = interrupted
        with self.assertRaises(asyncio.CancelledError):
            await self.relay.cycle()
        self.assertEqual(len(self.sent), 1)
        await self.app.close()
        self.app = CommunityBot(self.temp.name)
        self.app._connection.user = SimpleNamespace(id=42)
        self.app.health.storage_level = 'ok'
        self.app.get_channel = lambda ident: self.channels.get(ident)
        self.app.http.send_message = AsyncMock(side_effect=self.send)
        self.relay = self.app.banners
        self.relay.clock = lambda: self.now
        self.now += 31
        await self.relay.cycle()
        self.assertEqual(len(self.sent), 3)
        self.assertEqual(self.jobs()[0]['state'], 'sent')

    async def test_source_edit_does_not_repost_an_unchanged_image(self):
        self.relay.configure(1, 10)
        await self.accept_images(['red', 'blue'])
        await self.relay.cycle()
        self.now += 60
        await self.accept_images(['red', 'green'])
        await self.relay.cycle()
        self.assertEqual(len(self.sent), 3)
        self.assertEqual([item['files'][0]['blob'] for item in self.sent], [colored(c) for c in ('red', 'blue', 'green')])

    async def test_reordered_images_preserve_original_delivery_time_without_reposting(self):
        self.relay.configure(1, 10)
        await self.accept_images(['red', 'blue'])
        await self.relay.cycle()
        original = self.jobs()[0]['attempted_at']
        self.now += 60
        await self.accept_images(['blue', 'red'])
        await self.relay.cycle()
        self.assertEqual(len(self.sent), 2)
        self.assertEqual({job['attempted_at'] for job in self.jobs()}, {original})

    async def test_confirmed_legacy_batch_is_not_split_or_reposted_after_upgrade(self):
        self.relay.configure(1, 10)
        await self.accept_images(['red', 'blue'])
        self.relay.state(self.jobs()[0], 'sent', 999)
        self.relay.configure(1, 10)
        await self.relay.cycle()
        self.assertEqual(self.sent, [])
        self.now += 60
        await self.accept_images(['red', 'green'])
        await self.relay.cycle()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0]['files'][0]['blob'], colored('green'))

    async def test_unknown_legacy_batch_does_not_become_new_image_uploads(self):
        self.relay.configure(1, 10)
        await self.accept_images(['red', 'blue'])
        self.relay.state(self.jobs()[0], 'uncertain')
        self.now += 31
        await self.relay.cycle()
        self.assertEqual(self.sent, [])
        self.now += 60
        await self.accept_images(['red', 'green'])
        await self.relay.cycle()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0]['files'][0]['blob'], colored('green'))
        self.assertIn('legacy_uncertain', {row[0] for row in self.relay.db.execute('SELECT state FROM banner_image_receipts')})

    async def test_repeated_slash_commands_do_not_republish_cached_banner_or_daily(self):
        self.relay.configure(1, 10)
        await self.accept_images(['red'])
        await self.relay.cycle()
        for _ in range(3):
            await self.app.tree.get_command('setbanner').callback(self.interaction())
            await self.relay.cycle()
        self.assertEqual(len(self.sent), 1)
        daily = self.app.daily
        daily.clock = lambda: self.now
        daily.download = AsyncMock(return_value=colored('green'))
        await self.app.tree.get_command('dailychallenge').callback(self.interaction(guild=2, channel=20))
        await daily.accept(self.event(channel_id=str(DAILY_CHANNEL_ID), created_at=self.now - 12 * 3600))
        await daily.cycle()
        for _ in range(3):
            await self.app.tree.get_command('dailychallenge').callback(self.interaction(guild=2, channel=20))
            await daily.cycle()
        self.assertEqual(len(self.sent), 2)
