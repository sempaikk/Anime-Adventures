"""Private regressions for the seven reproduced review cases."""

import io
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from PIL import Image

import test_banners as feeds
import test_global_chat as chat
from banner_relay import BannerControls
from global_policy import check_links
from global_relay import relay_name


class FeedImprovements(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = feeds.BannerCase.asyncSetUp
    asyncTearDown = feeds.BannerCase.asyncTearDown
    add_channel = feeds.BannerCase.add_channel
    send = feeds.BannerCase.send
    event = feeds.BannerCase.event
    interaction = feeds.BannerCase.interaction

    async def test_text_edit_after_image_cache_expiration_does_not_republish(self):
        self.relay.configure(1, 10)
        event = self.event()
        await self.relay.accept(event)
        await self.relay.cycle()
        self.now += self.relay.max_age + 1
        self.relay.prune()
        self.assertFalse(await self.relay.accept({**event, 'created_at': self.now}))
        await self.relay.cycle()
        self.assertEqual(len(self.sent), 1)
        # A genuinely new source can legitimately reuse this artwork.
        self.assertTrue(await self.relay.accept(self.event(message_id='123456789012345679')))
        await self.relay.cycle()
        self.assertEqual(len(self.sent), 2)

    async def test_old_stop_button_preserves_new_configuration_in_same_channel(self):
        self.relay.configure(1, 10)
        i = self.interaction()
        view = BannerControls(self.app, i)
        self.relay.configure(1, 10)
        await view.disable.callback(i)
        self.assertIsNotNone(self.relay.target(1))

    async def test_unsupported_extra_image_does_not_discard_valid_banner(self):
        out = io.BytesIO()
        Image.new('RGB', (8, 8), 'red').save(out, format='GIF')
        self.relay.configure(1, 10)
        self.relay.download.side_effect = [self.blob, out.getvalue()]
        self.assertTrue(await self.relay.accept(self.event(images=[self.event()['images'][0],
            'https://cdn.discordapp.com/attachments/1/2/extra.gif'])))
        await self.relay.cycle()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0]['files'][0]['blob'], self.blob)


class ChatImprovements(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = chat.ChatCase.asyncSetUp
    asyncTearDown = chat.ChatCase.asyncTearDown
    fetch = chat.ChatCase.fetch
    history = chat.ChatCase.history
    send_notice = chat.ChatCase.send_notice
    message = chat.ChatCase.message
    copies = chat.ChatCase.copies
    flush = chat.ChatCase.flush
    asset = chat.ChatCase.asset

    async def test_small_known_file_does_not_reserve_maximum_guild_upload_size(self):
        self.engine.media.available_space = AsyncMock(return_value=64*1024*1024)
        asset = vars(self.asset())
        result = await self.engine.media.download(asset, 100*1024*1024)
        self.assertTrue(self.engine.media.path(result).is_file())
        self.engine.media.release([result])

    async def test_channel_age_policy_change_pauses_only_affected_connection(self):
        self.channels[10].is_nsfw.return_value = True
        source = self.message(content='A harmless synthetic test message')
        await self.engine.ingest(source)
        await self.flush()
        self.assertFalse(self.copies(source))
        self.assertFalse(self.engine.store.channel(1)['active'])
        self.assertTrue(self.engine.store.channel(2)['active'])

    async def test_renamed_executable_is_not_forwarded_as_image(self):
        source = self.message(attachments=[self.asset('image.png', b'MZ'+b'\x00'*40)])
        await self.engine.ingest(source)
        await self.flush()
        self.assertFalse(self.copies(source))


class IdentityAndLinks(unittest.TestCase):
    def test_controls_are_removed_before_reserved_identity_tags(self):
        bot = SimpleNamespace(is_owner_id=lambda ident: ident == 7)
        for label in ('Ow\u200bner', 'Te\u200bster'):
            author = SimpleNamespace(id=99, display_name=f'Player [{label}]')
            self.assertEqual(relay_name(bot, author), 'Player')
        self.assertEqual(relay_name(bot, SimpleNamespace(id=7,display_name='Player [Te\u200bster]')), 'Player [Owner]')

    def test_domain_without_protocol_is_checked_but_descriptive_labels_are_allowed(self):
        for label in ('discord.com', 'www.discord.com', 'https://discord.com'):
            with self.assertRaises(ValueError):
                check_links(f'[{label}](https://example.invalid)')
        check_links('[Read more](https://example.invalid)')
        check_links('[discord.com](https://www.discord.com/help)')
