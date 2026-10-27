"""Private server inventory and bounded, restart-safe release notices; no Discord access."""

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from community_bot import CommunityBot
from community_hub import CENTRAL_GUILD_ID, CENTRAL_UPDATE_CHANNEL_ID
from global_ops import OperationsView


async def messages(values):
    for value in values:
        yield value


PREVIOUS_PORTUGUESE_NOTICE = '\n'.join([
    '- Os menus e botões agora usam texto. O único ícone decorativo fica no painel privado de status do bot.',
    '- As atualizações continuam chegando neste canal mesmo se o nome dele mudar.',
    '- Os banners e desafios diários são enviados de forma independente. Uma falha em um deles não interrompe o outro.',
    '- O painel privado mostra os canais configurados, a conexão com as fontes e as últimas entregas confirmadas.',
    '- Os controles do chat global conferem a configuração atual antes de pausar ou retomar a conexão, evitando alterações feitas por painéis antigos.',
    '- As novidades relevantes do bot serão publicadas aqui. As confirmações de configuração e os relatórios continuam privados.',
])


class CommunityHubCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.bot = CommunityBot(self.temp.name)
        self.bot.owner_ids_set = {7}
        self.bot._connection.user = SimpleNamespace(id=42)
        self.bot.build = {'version': '2026.10.27.6', 'verified': True}
        self.hub = self.bot.community
        self.now = 2_000_000_000.0
        self.bot.store.clock = lambda: self.now
        default = MagicMock(spec=discord.Role)
        default.id, default.name, default.position = CENTRAL_GUILD_ID, '@everyone', 0
        default.permissions, default.managed = discord.Permissions.none(), False
        default.is_default.return_value = True
        default.__lt__.return_value = True
        role = MagicMock(spec=discord.Role)
        role.id, role.name, role.position = 100, 'Member', 1
        role.permissions, role.managed = discord.Permissions(view_channel=True), False
        role.is_default.return_value = False
        role.__lt__.return_value = True
        self.guild = SimpleNamespace(
            id=CENTRAL_GUILD_ID, name='Synthetic community', unavailable=False,
            me=SimpleNamespace(id=42, top_role=SimpleNamespace(position=10),
                               guild_permissions=discord.Permissions(manage_roles=True)),
            member_count=2, preferred_locale='en-US', rules_channel=None,
            channels=[], text_channels=[], roles=[default, role], default_role=default,
        )
        self.bot.get_guild = lambda ident: self.guild if ident == CENTRAL_GUILD_ID else None
        self.guild.get_channel = lambda ident: next((c for c in self.guild.channels if c.id == ident), None)
        self.channel = self.add_channel(CENTRAL_UPDATE_CHANNEL_ID, '🛠️┃updates-logs')
        self.channel.type = discord.ChannelType.news
        self.history = []
        self.bot.http.send_message = AsyncMock(return_value={'id': '999'})

    async def asyncTearDown(self):
        await self.bot.close()
        self.temp.cleanup()

    def add_channel(self, ident, name):
        channel = MagicMock(spec=discord.TextChannel)
        channel.id, channel.name, channel.guild = ident, name, self.guild
        channel.position, channel.category_id, channel.type = 0, None, discord.ChannelType.text
        channel.topic = 'Synthetic channel purpose, not a message.'
        channel.overwrites = {self.guild.roles[1]: discord.PermissionOverwrite(view_channel=True), object(): discord.PermissionOverwrite(view_channel=False)}
        channel.permissions_for.side_effect = lambda who: discord.Permissions(
            view_channel=who is self.guild.me, send_messages=True, read_message_history=True)
        channel.history.side_effect = lambda **kw: messages(self.history)
        self.guild.channels.append(channel)
        self.guild.text_channels.append(channel)
        return channel

    def interaction(self, *, actor=7, guild=CENTRAL_GUILD_ID, admin=True):
        return SimpleNamespace(
            user=SimpleNamespace(id=actor), guild_id=guild, channel_id=CENTRAL_UPDATE_CHANNEL_ID, client=self.bot,
            permissions=discord.Permissions(manage_guild=admin),
            response=SimpleNamespace(defer=AsyncMock(), is_done=lambda: True),
            followup=SimpleNamespace(send=AsyncMock()),
        )

    def receipt(self):
        return json.loads(self.bot.store.get(f"community-update:{CENTRAL_GUILD_ID}:{self.bot.build['version']}") or '{}')

    async def test_only_designated_server_and_verified_matching_release_can_publish(self):
        self.guild.id = 1
        self.bot.get_guild = lambda ident: None
        await self.hub.publish_update()
        self.bot.http.send_message.assert_not_awaited()
        self.guild.id = CENTRAL_GUILD_ID
        self.bot.get_guild = lambda ident: self.guild
        self.now += 300
        self.bot.build['verified'] = False
        await self.hub.publish_update()
        self.bot.http.send_message.assert_not_awaited()
        self.now += 300
        self.bot.build.update(verified=True, version='unannounced-version')
        await self.hub.publish_update()
        self.bot.http.send_message.assert_not_awaited()

    async def test_confirmed_announcement_channel_is_used_despite_plural_name_or_similar_channels(self):
        self.add_channel(201, 'update-log')
        self.add_channel(202, 'update_log')
        await self.hub.publish_update()
        self.assertEqual(self.bot.http.send_message.call_args.args[0], CENTRAL_UPDATE_CHANNEL_ID)

    async def test_missing_confirmed_channel_does_not_fall_back_to_a_similar_name(self):
        self.guild.channels.remove(self.channel)
        self.add_channel(201, 'update-log')
        await self.hub.publish_update()
        self.bot.http.send_message.assert_not_awaited()

    async def test_missing_permissions_or_relay_destination_blocks_publication(self):
        self.channel.permissions_for.side_effect = None
        self.channel.permissions_for.return_value = discord.Permissions(view_channel=True, send_messages=True)
        await self.hub.publish_update()
        self.bot.http.send_message.assert_not_awaited()
        self.channel.permissions_for.return_value.read_message_history = True
        for feed in (self.bot.banners, self.bot.daily):
            feed.configure(CENTRAL_GUILD_ID, CENTRAL_UPDATE_CHANNEL_ID)
            self.now += 300
            await self.hub.publish_update()
            self.bot.http.send_message.assert_not_awaited()
            feed.disable(CENTRAL_GUILD_ID)
        self.bot.globalchat.store.configure(CENTRAL_GUILD_ID, CENTRAL_UPDATE_CHANNEL_ID, 123, 'synthetic-not-a-token', 0)
        self.now += 300
        await self.hub.publish_update()
        self.bot.http.send_message.assert_not_awaited()

    async def test_restart_and_concurrent_cycles_publish_once_without_mentions(self):
        payloads = []

        async def send(channel_id, *, params):
            payloads.append(dict(params.payload))
            await asyncio.sleep(0)
            return {'id': '999'}

        self.bot.http.send_message.side_effect = send
        await asyncio.gather(self.hub.publish_update(), self.hub.publish_update())
        self.assertEqual(self.bot.http.send_message.await_count, 1)
        self.assertTrue(payloads[0]['enforce_nonce'])
        self.assertEqual(payloads[0]['allowed_mentions']['parse'], [])
        self.assertTrue(payloads[0]['content'].startswith('- Os menus do bot'))
        self.assertNotIn('Anime Adventures · Update', payloads[0]['content'])
        self.assertNotIn(self.bot.build['version'], payloads[0]['content'])
        from community_hub import CommunityHub
        self.hub = CommunityHub(self.bot)
        await self.hub.publish_update()
        self.assertEqual(self.bot.http.send_message.await_count, 1)
        self.assertEqual(self.receipt()['state'], 'sent')

    def previous_notice(self, *, version='2026.10.27.4', content=None):
        receipt = {'state': 'sent', 'channel_id': str(CENTRAL_UPDATE_CHANNEL_ID),
                   'message_id': '888', 'nonce': '1234', 'attempted_at': self.now - 300}
        self.bot.store.set(f'community-update:{CENTRAL_GUILD_ID}:{version}', json.dumps(receipt))
        message = SimpleNamespace(id=888, author=SimpleNamespace(id=42), webhook_id=None,
                                  content=content or f'Anime Adventures · Update {version}\n\n- Previous English notice.',
                                  edit=AsyncMock())
        self.channel.fetch_message = AsyncMock(return_value=message)
        return message

    async def test_previous_english_notice_is_corrected_in_place_once(self):
        message = self.previous_notice()
        await self.hub.publish_update()
        message.edit.assert_awaited_once()
        content = message.edit.call_args.kwargs['content']
        self.assertTrue(content.startswith('- Os menus do bot'))
        self.assertNotIn('2026.10.27.', content)
        self.assertEqual(message.edit.call_args.kwargs['allowed_mentions'].to_dict()['parse'], [])
        self.assertEqual(self.receipt()['message_id'], '888')
        self.bot.http.send_message.assert_not_awaited()

        from community_hub import CommunityHub
        self.hub = CommunityHub(self.bot)
        await self.hub.publish_update()
        message.edit.assert_awaited_once()
        self.bot.http.send_message.assert_not_awaited()

    async def test_current_portuguese_notice_is_trimmed_to_member_facing_changes(self):
        message = self.previous_notice(version='2026.10.27.5', content=PREVIOUS_PORTUGUESE_NOTICE)
        await self.hub.publish_update()
        message.edit.assert_awaited_once()
        text = message.edit.call_args.kwargs['content']
        self.assertEqual(len(text.splitlines()), 2)
        self.assertNotIn('privado', text)
        self.assertNotIn('configuração', text)
        self.assertEqual(self.receipt()['message_id'], '888')
        self.bot.http.send_message.assert_not_awaited()

    async def test_later_small_updates_create_new_messages_and_preserve_previous_notice(self):
        message = self.previous_notice()
        await self.hub.publish_update()
        message.edit.assert_awaited_once()
        corrected_receipt = self.bot.store.get(f'community-update:{CENTRAL_GUILD_ID}:2026.10.27.6')
        path = Path(self.temp.name) / 'future-updates.json'
        self.bot.http.send_message.side_effect = [{'id': '999'}, {'id': '1000'}]
        with patch('community_hub.UPDATES_PATH', path):
            for version, message_id in (('2026.10.27.7', '999'), ('2026.10.27.8', '1000')):
                self.bot.build['version'] = version
                path.write_text(json.dumps({'schema': 1, 'version': version,
                                            'changes': ['Uma pequena melhoria para quem usa o bot.'],
                                            'replaces': '2026.10.27.6'}), encoding='utf-8')
                self.now += 300
                await self.hub.publish_update()
                self.assertEqual(self.receipt()['message_id'], message_id)
            from community_hub import CommunityHub
            await CommunityHub(self.bot).publish_update()
        self.assertEqual(self.bot.http.send_message.await_count, 2)
        message.edit.assert_awaited_once()
        self.assertEqual(self.bot.store.get(f'community-update:{CENTRAL_GUILD_ID}:2026.10.27.6'), corrected_receipt)

    async def test_lost_edit_ack_is_reconciled_without_a_duplicate_notice(self):
        message = self.previous_notice()

        async def edit(**kwargs):
            message.content = kwargs['content']
            raise TimeoutError('Synthetic lost edit acknowledgment')

        message.edit.side_effect = edit
        await self.hub.publish_update()
        self.assertEqual(self.receipt(), {})
        self.now += 300
        await self.hub.publish_update()
        self.assertEqual(self.receipt()['state'], 'sent')
        message.edit.assert_awaited_once()
        self.bot.http.send_message.assert_not_awaited()

    async def test_correction_rejects_other_authors_webhooks_or_unrelated_messages(self):
        for field, value in (('author', SimpleNamespace(id=99)), ('webhook_id', 123), ('content', 'A different message')):
            with self.subTest(field=field):
                message = self.previous_notice()
                setattr(message, field, value)
                self.now += 300
                await self.hub.publish_update()
                message.edit.assert_not_awaited()
                self.bot.http.send_message.assert_not_awaited()
                self.assertEqual(self.receipt(), {})

    async def test_lost_ack_is_reconciled_in_original_channel_without_reposting(self):
        self.bot.http.send_message.side_effect = TimeoutError('synthetic lost acknowledgment')
        await self.hub.publish_update()
        receipt = self.receipt()
        self.assertEqual(receipt['state'], 'uncertain')
        self.channel.name = 'renamed-channel'
        self.add_channel(201, 'update-log')
        self.history.append(SimpleNamespace(id=999, author=SimpleNamespace(id=42), webhook_id=None,
                                            nonce=receipt['nonce'], content='', created_at=datetime.now(timezone.utc)))
        self.now += 300
        await self.hub.publish_update()
        self.bot.http.send_message.assert_awaited_once()
        self.assertEqual(self.receipt()['state'], 'sent')
        self.assertEqual(self.receipt()['channel_id'], str(CENTRAL_UPDATE_CHANNEL_ID))

    async def test_unconfirmed_or_crashed_send_is_never_blindly_repeated(self):
        self.bot.http.send_message.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.hub.publish_update()
        self.assertEqual(self.receipt()['state'], 'sending')
        self.now += 300
        await self.hub.publish_update()
        self.bot.http.send_message.assert_awaited_once()
        self.assertIn('awaiting confirmation', self.hub.status)

    async def test_permission_rejection_can_retry_after_repair(self):
        self.bot.http.send_message.side_effect = discord.Forbidden(SimpleNamespace(status=403, reason='Forbidden'), 'Synthetic rejection')
        await self.hub.publish_update()
        self.assertEqual(self.receipt()['state'], 'blocked')
        self.bot.http.send_message.side_effect = None
        await self.hub.publish_update()
        self.bot.http.send_message.assert_awaited_once()
        self.now += 300
        await self.hub.publish_update()
        self.assertEqual(self.receipt()['state'], 'sent')

    async def test_report_is_owner_admin_and_central_guild_only(self):
        for i in (self.interaction(actor=8), self.interaction(guild=1), self.interaction(admin=False)):
            with self.assertRaises(ValueError):
                self.hub.report(i)
        self.bot.http.send_message.assert_not_awaited()

    async def test_report_uses_metadata_only_and_never_fetches_messages_or_creates_channels(self):
        report = self.hub.report(self.interaction())
        try:
            data = json.loads(report.fp.read())
        finally:
            report.close()
        self.assertEqual(data['server']['id'], str(CENTRAL_GUILD_ID))
        self.assertEqual(data['channels'][0]['name'], self.channel.name)
        self.assertEqual(data['channels'][0]['member_override_count'], 1)
        self.assertFalse(data['channels'][0]['everyone_can_view'])
        self.assertEqual(data['channels'][0]['role_overrides'][0]['role_id'], '100')
        self.assertTrue(data['roles'][1]['bot_can_assign'])
        self.assertFalse(data['roles'][0]['bot_can_assign'])
        self.assertEqual(set(data['image_feeds']), {'banner', 'daily'})
        self.channel.history.assert_not_called()
        self.channel.fetch_message.assert_not_called()
        self.bot.http.send_message.assert_not_awaited()

    async def test_report_button_sends_only_an_ephemeral_attachment(self):
        i = self.interaction()
        seen = []

        async def receive(**kwargs):
            self.assertTrue(kwargs['ephemeral'])
            seen.append(json.loads(kwargs['file'].fp.read()))

        i.followup.send.side_effect = receive
        view = OperationsView(self.bot, i)
        await view.server_report.callback(i)
        i.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
        self.assertEqual(seen[0]['server']['id'], str(CENTRAL_GUILD_ID))
        self.bot.http.send_message.assert_not_awaited()
        other = OperationsView(self.bot, self.interaction(guild=1))
        self.assertNotIn(other.server_report, other.children)
        self.assertFalse(await view.interaction_check(self.interaction(actor=8)))

    async def test_status_includes_each_local_feed_and_fits_a_private_card(self):
        from tier_ui import payload
        self.bot.banners.configure(CENTRAL_GUILD_ID, 200)
        self.bot.daily.configure(CENTRAL_GUILD_ID, 201)
        i = self.interaction()
        view = OperationsView(self.bot, i)
        text = view.description()
        self.assertIn('**Banners:** <#200>', text)
        self.assertIn('**Daily challenges:** <#201>', text)
        self.assertNotIn('PC question service', text)
        self.assertLessEqual(payload(bot=self.bot, content=text, view=view)['view'].total_children_count, 40)
