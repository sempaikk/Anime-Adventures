"""Cross-server journeys, persistence, adversarial actions and uncertain Discord acknowledgements."""

import asyncio
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from PIL import Image

from community_bot import CommunityBot
from global_relay import GlobalRelay, chunks, relay_name
from global_store import GlobalStore
from global_views import (
    GlobalPanelView,
    GlobalMemberView,
    GlobalDirectView,
    GlobalAdminView,
    ConsentView,
    MessageAction,
    ModerationModal,
    TERMS,
    HELP,
    find_message,
)
from global_media import cdn_url, filename
from tier_store import TierStore
from tier_ui import payload, visible_text
from tier_backup import make_snapshot, restore_snapshot


def missing():
    return discord.NotFound(
        SimpleNamespace(status=404, reason="Not Found"),
        {"code": 10008, "message": "Unknown Message"},
    )


class UploadResponse:
    def __init__(self, data):
        self.status = 200
        self.content_length = len(data)
        self.data = data
        self.content = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def iter_chunked(self, size):
        for start in range(0, len(self.data), size):
            yield self.data[start : start + size]


class Hook:
    def __init__(self, env, channel):
        self.env, self.channel = env, channel
        self.id = channel.id + 100
        self.token = "synthetic-private-hook-" + str(channel.id)
        self.name = "Anime Adventures · Global"
        self.user = SimpleNamespace(id=42)
        self.calls = []
        self.lose_ack = False
        self.crash = False

    async def send(self, content, **kwargs):
        self.calls.append(kwargs)
        files = []
        for item in kwargs.get("files", []):
            value = item.fp.read()
            files.append(
                SimpleNamespace(filename=item.filename, size=len(value), blob=value)
            )
        message = self.env.message(
            self.channel,
            content or "",
            author=SimpleNamespace(id=42, name=kwargs["username"], bot=True),
            attachments=files,
            webhook_id=self.id,
        )
        if self.lose_ack:
            self.lose_ack = False
            raise TimeoutError("artificial lost acknowledgement")
        if self.crash:
            raise asyncio.CancelledError()
        return message

    async def edit_message(self, ident, **kwargs):
        message = await self.channel.fetch_message(ident)
        message.content = kwargs["content"]
        message.attachments = [
            SimpleNamespace(
                filename=f.filename, size=len(blob := f.fp.read()), blob=blob
            )
            for f in kwargs.get("attachments", [])
        ]
        return message

    async def delete_message(self, ident):
        await self.channel.fetch_message(ident)
        self.env.messages.pop(ident)
        self.env.app.globalchat.on_delete(SimpleNamespace(message_id=ident))


class ChatCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.now = [2_000_000_000.0]
        self.base = TierStore(
            Path(self.temp.name) / "tierlist.sqlite3", clock=lambda: self.now[0]
        )
        self.messages = {}
        self.channels = {}
        self.hooks = {}
        self.blobs = {}
        self.counter = 1_000_000
        self.app = SimpleNamespace(
            store=self.base,
            directory=Path(self.temp.name),
            get_channel=lambda x: self.channels.get(int(x)),
            user=SimpleNamespace(id=42),
            health=SimpleNamespace(storage_level="ok"),
            is_owner_id=lambda x: x == 7,
            guild_lock=lambda x: asyncio.Lock(),
        )
        self.app.require_admin = lambda i: CommunityBot.require_admin(self.app, i)
        self.app.require_owner = lambda i: CommunityBot.require_owner(self.app, i)
        self.app.require_human = lambda i: CommunityBot.require_human(self.app, i)
        self.app.globalchat = GlobalRelay(self.app)
        self.engine = self.app.globalchat
        self.engine.webhook = lambda ident: self.hooks[int(ident)]
        self.engine.http_session = AsyncMock()
        self.engine.media.session = AsyncMock(
            return_value=SimpleNamespace(
                get=lambda url, **kwargs: UploadResponse(self.blobs[url])
            )
        )
        for gid in (1, 2, 3):
            guild = SimpleNamespace(
                id=gid,
                name=f"Servidor {gid}",
                me=SimpleNamespace(id=42),
                filesize_limit=10 * 1024 * 1024,
                get_channel=lambda cid: self.channels.get(cid),
                get_member=lambda uid: self.author if uid == self.author.id else None,
                fetch_member=AsyncMock(side_effect=missing()),
            )
            channel = MagicMock(spec=discord.TextChannel)
            channel.id = gid * 10
            channel.guild = guild
            channel.is_nsfw.return_value = False
            channel.permissions_for.return_value = SimpleNamespace(
                view_channel=True,
                read_message_history=True,
                manage_webhooks=True,
                send_messages=True,
                attach_files=True,
            )

            async def fetch_message(ident, c=channel):
                return await self.fetch(c, ident)

            channel.fetch_message = AsyncMock(side_effect=fetch_message)
            channel.history.side_effect = lambda c=channel, **kwargs: self.history(
                channel_id=c.id, **kwargs
            )
            channel.send = AsyncMock(
                side_effect=lambda c=channel, **kwargs: self.send_notice(c, kwargs)
            )
            self.channels[channel.id] = channel
            hook = Hook(self, channel)
            self.hooks[hook.id] = hook
            channel.webhooks = AsyncMock(return_value=[hook])
            channel.create_webhook = AsyncMock(return_value=hook)
            channel.get_partial_message.return_value = SimpleNamespace(edit=AsyncMock())
            self.engine.store.configure(gid, channel.id, hook.id, hook.token, 0)
            with self.base.connection:
                self.base.connection.execute(
                    "UPDATE global_channels SET panel_id=? WHERE guild_id=?",
                    (str(gid * 100), str(gid)),
                )
        self.author = SimpleNamespace(
            id=7,
            name="juninho",
            display_name="Juninho",
            bot=False,
            created_at=discord.utils.utcnow() - timedelta(days=30),
            display_avatar=SimpleNamespace(
                url="https://cdn.discordapp.com/embed/avatars/0.png"
            ),
        )
        self.dm = SimpleNamespace(id=5000, guild=None, recipient=self.author)

        async def fetch_dm(ident):
            return await self.fetch(self.dm, ident)

        self.dm.fetch_message = AsyncMock(side_effect=fetch_dm)
        self.channels[5000] = self.dm
        self.author.send = AsyncMock(
            side_effect=lambda **kwargs: self.send_notice(self.dm, kwargs)
        )
        self.engine.store.consent(7)

    async def asyncTearDown(self):
        await self.engine.close()
        self.base.close()
        self.temp.cleanup()

    async def fetch(self, channel, ident):
        message = self.messages.get(int(ident))
        if not message or message.channel.id != channel.id:
            raise missing()
        return message

    async def history(
        self,
        channel_id,
        limit=100,
        after=None,
        before=None,
        oldest_first=False,
        **kwargs,
    ):
        rows = [m for m in self.messages.values() if m.channel.id == channel_id]
        if before:
            rows = [m for m in rows if m.id < before.id]
        if after:
            if isinstance(after, datetime):
                rows = [m for m in rows if m.created_at > after]
            else:
                rows = [m for m in rows if m.id > after.id]
        rows.sort(key=lambda m: m.id, reverse=not oldest_first)
        for row in rows[:limit]:
            yield row

    def send_notice(self, channel, kwargs):
        message = self.message(
            channel,
            visible_text(kwargs),
            author=SimpleNamespace(id=42, bot=True),
            webhook_id=None,
        )
        view = kwargs.get("view")
        message.components = view.to_components() if view else []
        return message

    def message(
        self,
        channel=None,
        content="Olá **comunidade**!",
        *,
        author=None,
        attachments=None,
        webhook_id=None,
    ):
        channel = channel or self.channels[10]
        self.counter += 1
        message = SimpleNamespace(
            id=self.counter,
            channel=channel,
            guild=channel.guild,
            author=author or self.author,
            content=content,
            attachments=attachments or [],
            webhook_id=webhook_id,
            stickers=[],
            components=[],
            reference=None,
            mentions=[],
            role_mentions=[],
            created_at=datetime.fromtimestamp(self.now[0], timezone.utc),
        )
        message.reply = AsyncMock(
            side_effect=lambda **kwargs: self.send_notice(channel, kwargs)
        )
        message.delete = AsyncMock(
            side_effect=lambda: self.messages.pop(message.id, None)
        )
        self.messages[message.id] = message
        return message

    def interaction(self, gid=1, user=7, *, admin=False):
        return SimpleNamespace(
            client=self.app,
            user=SimpleNamespace(**{**vars(self.author), "id": user}),
            guild_id=gid,
            channel_id=gid * 10,
            channel=self.channels[gid * 10],
            permissions=SimpleNamespace(manage_guild=admin),
            message=SimpleNamespace(id=gid * 100),
            response=SimpleNamespace(
                is_done=lambda: False,
                send_message=AsyncMock(),
                edit_message=AsyncMock(),
                defer=AsyncMock(),
                send_modal=AsyncMock(),
            ),
            followup=SimpleNamespace(send=AsyncMock()),
            delete_original_response=AsyncMock(),
            edit_original_response=AsyncMock(),
        )

    def direct_interaction(self):
        row = self.engine.store.invitation(7)
        i = self.interaction()
        i.guild_id, i.channel_id, i.channel = None, self.dm.id, self.dm
        i.message = self.messages[int(row["message_id"])]
        return i

    def copies(self, source):
        return [m for m in self.messages.values() if m.webhook_id and m.id != source.id]

    async def flush(self):
        for _ in range(8):
            jobs = self.engine.store.jobs()
            if not jobs:
                return
            for job in jobs:
                await self.engine.deliver(job)

    def asset(self, name="image.png", blob=None):
        if blob is None:
            buf = io.BytesIO()
            Image.new("RGB", (8, 8), "red").save(buf, format="PNG")
            blob = buf.getvalue()
        ident = self.counter + 100
        url = f"https://cdn.discordapp.com/attachments/10/{ident}/{name}"
        self.blobs[url] = blob
        return SimpleNamespace(id=ident, url=url, filename=name, size=len(blob))

    async def test_normal_conversation_has_two_copies_and_preserves_original(self):
        source = self.message()
        await self.engine.ingest(source)
        await self.flush()
        copies = self.copies(source)
        self.assertEqual({m.channel.id for m in copies}, {20, 30})
        self.assertTrue(all(m.content == source.content for m in copies))
        self.assertEqual(
            len(self.engine.store.rows("SELECT * FROM global_messages")), 1
        )
        source.delete.assert_not_awaited()
        for copy in copies:
            await self.engine.ingest(copy)
        self.assertEqual(
            len(self.engine.store.rows("SELECT * FROM global_messages")), 1
        )

    async def test_owner_and_tester_labels_are_identity_bound_and_fit_discord(self):
        guild = self.channels[10].guild
        self.assertTrue(relay_name(self.app, self.author).endswith(" [Owner]"))
        tester = SimpleNamespace(**{**vars(self.author), "id": 1401953040004550858})
        self.assertTrue(relay_name(self.app, tester).endswith(" [Tester]"))
        fake = SimpleNamespace(
            **{**vars(self.author), "id": 8, "display_name": "[Owner] [Tester] Juninho"}
        )
        guild.name = "[Owner] Servidor"
        rendered = relay_name(self.app, fake)
        self.assertNotIn("[Owner]", rendered)
        self.assertNotIn("[Tester]", rendered)
        self.assertNotIn("@juninho", rendered)
        self.assertEqual(rendered, "Juninho")
        tester.display_name = "😀" * 50
        tester.name = "a" * 32
        guild.name = "😀" * 50
        self.assertLessEqual(
            len(relay_name(self.app, tester).encode("utf-16-le")) // 2, 80
        )

    async def test_consent_is_account_wide_and_persistent(self):
        for gid in (2, 3):
            i = self.interaction(gid)
            await GlobalMemberView(self.app, i).join.callback(i)
            text = visible_text(i.response.send_message.await_args.kwargs["view"])
            self.assertIn("Você já participa", text)
            self.assertNotIn("Antes de participar", text)
        self.assertEqual(
            len(self.engine.store.rows("SELECT * FROM global_consents")), 1
        )
        self.assertTrue(GlobalStore(self.base).consented(7))

    async def test_unconfirmed_first_message_stays_local_and_prompt_is_bound(self):
        self.engine.store.consent(7, False)
        source = self.message()
        await self.engine.ingest(source)
        self.assertFalse(self.engine.store.jobs())
        source.delete.assert_not_awaited()
        self.assertEqual(
            len(self.engine.store.rows("SELECT * FROM global_invitations")), 1
        )
        self.assertFalse(self.engine.store.rows("SELECT * FROM global_prompts"))
        source.reply.assert_not_awaited()
        cfg = self.engine.store.channel(1)
        view = ConsentView(self.app, self.interaction(), cfg)
        self.assertFalse(await view.interaction_check(self.interaction(user=8)))
        self.assertFalse(self.engine.store.consented(7))
        i = self.interaction()
        await view.accept.callback(i)
        self.assertTrue(self.engine.store.consented(7))
        i.delete_original_response.assert_awaited_once()

    async def test_native_edit_and_delete_update_the_same_copies(self):
        source = self.message()
        await self.engine.ingest(source)
        await self.flush()
        ids = {m.id for m in self.copies(source)}
        source.content = "Agora está *corrigido*."
        await self.engine.on_edit(
            SimpleNamespace(message_id=source.id, data={"content": source.content})
        )
        await self.flush()
        self.assertEqual({m.id for m in self.copies(source)}, ids)
        self.assertTrue(all(m.content == source.content for m in self.copies(source)))
        self.messages.pop(source.id)
        self.engine.on_delete(SimpleNamespace(message_id=source.id))
        await self.flush()
        self.assertFalse(self.copies(source))

    async def test_long_messages_shrink_without_marking_surviving_copy_as_moderated(
        self,
    ):
        source = self.message(content="a" * 4000)
        await self.engine.ingest(source)
        await self.flush()
        self.assertEqual(len(self.copies(source)), 6)
        source.content = "Texto curto."
        await self.engine.ingest(source)
        await self.flush()
        self.assertEqual(len(self.copies(source)), 2)
        source.content = "Mais uma edição."
        await self.engine.ingest(source)
        await self.flush()
        self.assertTrue(all(m.content == source.content for m in self.copies(source)))

    async def test_a_copy_removed_by_moderation_is_not_resurrected(self):
        source = self.message()
        await self.engine.ingest(source)
        await self.flush()
        copy = next(m for m in self.copies(source) if m.channel.id == 20)
        self.messages.pop(copy.id)
        self.engine.on_delete(SimpleNamespace(message_id=copy.id))
        source.content = "Editado depois da remoção."
        await self.engine.ingest(source)
        await self.flush()
        self.assertEqual({m.channel.id for m in self.copies(source)}, {30})

    async def test_lost_acknowledgement_is_recovered_without_duplicate(self):
        source = self.message()
        self.hooks[120].lose_ack = True
        await self.engine.ingest(source)
        await self.flush()
        self.assertEqual(len([m for m in self.copies(source) if m.channel.id == 20]), 1)
        self.now[0] += 10
        await self.flush()
        await self.flush()
        self.assertEqual(len(self.copies(source)), 2)
        self.assertEqual(len(self.hooks[120].calls), 1)
        self.assertEqual(self.engine.store.delivery(source.id, 20)["state"], "sent")

    async def test_restart_after_remote_post_before_local_ack_is_safe(self):
        source = self.message()
        self.hooks[120].crash = True
        await self.engine.ingest(source)
        job = self.engine.store.delivery(source.id, 20)
        with self.assertRaises(asyncio.CancelledError):
            await self.engine.deliver(job)
        self.assertEqual(self.engine.store.delivery(source.id, 20)["state"], "sending")
        self.engine.store = GlobalStore(self.base)
        self.hooks[120].crash = False
        await self.flush()
        await self.flush()
        self.assertEqual(len(self.hooks[120].calls), 1)

    async def test_delete_during_lost_ack_locates_and_removes_the_unknown_copy(self):
        source = self.message()
        self.hooks[120].lose_ack = True
        await self.engine.ingest(source)
        await self.flush()
        self.messages.pop(source.id)
        self.engine.on_delete(SimpleNamespace(message_id=source.id))
        await self.flush()
        await self.flush()
        self.assertFalse(self.copies(source))
        self.assertEqual(len(self.hooks[120].calls), 1)

    async def test_edit_during_uncertain_post_reconciles_old_copy_then_applies_new_text(
        self,
    ):
        source = self.message(content="Primeira versão")
        self.hooks[120].lose_ack = True
        await self.engine.ingest(source)
        await self.flush()
        source.content = "Segunda versão"
        await self.engine.ingest(source)
        self.now[0] += 10
        await self.flush()
        await self.flush()
        self.assertEqual(len(self.hooks[120].calls), 1)
        self.assertTrue(all(m.content == "Segunda versão" for m in self.copies(source)))

    async def test_person_can_leave_and_local_or_global_blocks_stop_deliveries(self):
        self.engine.store.block(2, "user", 7, 8, "Bloqueio de teste local")
        source = self.message()
        await self.engine.ingest(source)
        await self.flush()
        self.assertEqual({m.channel.id for m in self.copies(source)}, {30})
        self.engine.store.consent(7, False)
        next_message = self.message(content="Não compartilhar")
        await self.engine.ingest(next_message)
        self.assertIsNone(self.engine.store.message(next_message.id))
        self.engine.store.consent(7)
        self.engine.store.block("*", "user", 7, 8, "Bloqueio de teste global")
        await self.engine.ingest(next_message)
        self.assertIsNone(self.engine.store.message(next_message.id))

    async def test_source_history_before_activation_is_not_shared(self):
        source = self.message()
        source.created_at -= timedelta(seconds=1)
        await self.engine.ingest(source)
        self.assertIsNone(self.engine.store.message(source.id))

    async def test_pause_during_source_fetch_stops_post(self):
        source = self.message()
        await self.engine.ingest(source)

        async def paused(ident):
            self.engine.store.active(2, False)
            return source

        self.channels[10].fetch_message.side_effect = paused
        await self.engine.deliver(self.engine.store.delivery(source.id, 20))
        self.assertFalse(self.hooks[120].calls)

    async def test_mentions_are_readable_without_notification_permissions(self):
        source = self.message(
            content="<@8> <@&9> <#10> @everyone **oi** ||spoiler|| <:teste:123>"
        )
        source.mentions = [SimpleNamespace(id=8, display_name="João")]
        source.role_mentions = [SimpleNamespace(id=9, name="Grupo")]
        self.channels[10].name = "global"
        await self.engine.ingest(source)
        await self.flush()
        self.assertIn("@João @Grupo #global", self.copies(source)[0].content)
        self.assertIn("||spoiler|| <:teste:123>", self.copies(source)[0].content)
        mentions = self.hooks[120].calls[0]["allowed_mentions"].to_dict()
        self.assertEqual(mentions["parse"], [])

    async def test_reply_to_copy_preserves_context_without_quoting_unshared_people(
        self,
    ):
        source = self.message(content="Pergunta compartilhada")
        await self.engine.ingest(source)
        await self.flush()
        copy = next(m for m in self.copies(source) if m.channel.id == 20)
        answer = self.message(self.channels[20], content="Minha resposta")
        answer.reference = SimpleNamespace(message_id=copy.id)
        await self.engine.ingest(answer)
        await self.flush()
        replies = [
            m
            for m in self.messages.values()
            if m.webhook_id and "Minha resposta" in m.content
        ]
        self.assertTrue(all("Pergunta compartilhada" in m.content for m in replies))

    async def test_images_videos_and_spoilers_are_uploaded_as_identical_files(self):
        assets = [
            self.asset("SPOILER_image.png"),
            self.asset("clip.mp4", b"\x00\x00\x00\x18ftypmp42synthetic-video"),
        ]
        source = self.message(content="", attachments=assets)
        await self.engine.ingest(source)
        await self.flush()
        for copy in self.copies(source):
            self.assertEqual(
                [a.filename for a in copy.attachments], [a.filename for a in assets]
            )
            self.assertEqual(
                [a.blob for a in copy.attachments], [self.blobs[a.url] for a in assets]
            )
        source.delete.assert_not_awaited()

    async def test_oversize_file_does_not_silently_disappear(self):
        self.channels[20].guild.filesize_limit = 1
        source = self.message(content="Veja a imagem", attachments=[self.asset()])
        await self.engine.ingest(source)
        await self.flush()
        copy = next(m for m in self.copies(source) if m.channel.id == 20)
        self.assertIn("acima do limite", copy.content)
        self.assertFalse(copy.attachments)
        self.assertTrue(
            next(m for m in self.copies(source) if m.channel.id == 30).attachments
        )

    async def test_missing_cache_after_restart_is_rebuilt_from_verified_original(self):
        source = self.message(attachments=[self.asset()])
        await self.engine.ingest(source)
        for path in self.engine.media.root.iterdir():
            path.unlink()
        await self.flush()
        await self.flush()
        self.assertEqual(len(self.copies(source)), 2)

    async def test_no_source_deleted_or_revoked_during_download_can_be_published(self):
        source = self.message(attachments=[self.asset()])
        original_download = self.engine.media.download

        async def revoked(asset, limit):
            data = await original_download(asset, limit)
            self.channels[10].permissions_for.return_value.view_channel = False
            return data

        with patch.object(self.engine.media, "download", side_effect=revoked):
            await self.engine.ingest(source)
        await self.flush()
        self.assertFalse(self.copies(source))

    async def test_forbidden_source_refetch_finishes_without_publishing_or_unhandled_error(
        self,
    ):
        source = self.message(attachments=[self.asset()])
        self.channels[10].fetch_message.side_effect = discord.Forbidden(
            SimpleNamespace(status=403, reason="Forbidden"),
            {"code": 50013, "message": "Missing Permissions"},
        )
        await self.engine.ingest(source)
        self.assertEqual(self.engine.store.delivery(source.id, 20)["state"], "failed")
        self.assertFalse(self.copies(source))
        source.delete.assert_not_awaited()

    async def test_storage_cleanup_expires_queue_and_keeps_ids_consent_and_discord_history(
        self,
    ):
        source = self.message()
        await self.engine.ingest(source)
        await self.flush()
        pending = self.message(content="Uma mensagem que ficará pendente")
        await self.engine.ingest(pending)
        self.now[0] += 3601
        self.engine.store.cleanup()
        self.assertEqual(self.engine.store.message(source.id)["payload"], "{}")
        self.assertTrue(self.engine.store.consented(7))
        self.assertTrue(
            self.engine.store.resolve(
                2, 20, next(m for m in self.copies(source) if m.channel.id == 20).id
            )
        )
        self.assertTrue(self.copies(source))
        self.assertEqual(self.engine.store.delivery(pending.id, 20)["state"], "failed")
        source.delete.assert_not_awaited()

    async def test_edit_after_body_cache_expires_still_updates_copies(self):
        source = self.message()
        await self.engine.ingest(source)
        await self.flush()
        self.now[0] += 3601
        self.engine.store.cleanup()
        source.content = "Uma edição depois de uma hora"
        await self.engine.ingest(source)
        await self.flush()
        self.assertTrue(all(m.content == source.content for m in self.copies(source)))

    async def test_private_admin_controls_and_user_data_are_scoped(self):
        owner = self.interaction(admin=True)
        view = GlobalAdminView(self.app, owner)
        with self.assertRaises(ValueError):
            await view.activate.callback(self.interaction(user=8))
        self.assertFalse(
            await view.interaction_check(self.interaction(gid=2, user=7, admin=True))
        )
        self.assertNotIn("synthetic-private-hook", view.description())
        with self.assertRaises(ValueError):
            find_message(
                self.app, self.interaction(), "https://discord.com/channels/2/20/100"
            )
        for content in (TERMS, HELP):
            self.assertLess(
                len(visible_text(payload(content=content)["view"]).encode("utf-16-le"))
                // 2,
                4000,
            )

    async def test_a_normal_member_cannot_forge_network_moderation(self):
        i = self.interaction(user=8, admin=True)
        modal = ModerationModal(self.app, i, network=True)
        modal.action._values = ["block-user"]
        modal.target._value = "7"
        modal.reason._value = "Uma tentativa forjada"
        with self.assertRaises(ValueError):
            await modal.on_submit(i)
        self.assertFalse(self.engine.store.blocked(7, 1))

    async def test_a_user_cannot_remove_someone_elses_copies(self):
        source = self.message()
        await self.engine.ingest(source)
        await self.flush()
        i = self.interaction(user=8)
        modal = MessageAction(self.app, i, "erase")
        modal.link._value = str(source.id)
        with self.assertRaises(ValueError):
            await modal.on_submit(i)
        self.assertFalse(self.engine.store.message(source.id)["deleted"])

    async def test_abusive_sends_have_bounded_attempts_and_no_original_deletion(self):
        messages = [self.message(content=f"Mensagem {n}") for n in range(30)]
        await asyncio.gather(*(self.engine.ingest(m) for m in messages))
        self.assertEqual(
            len(self.engine.store.rows("SELECT * FROM global_messages")), 6
        )
        self.assertTrue(all(m.delete.await_count == 0 for m in messages))

    async def test_native_unicode_split_never_exceeds_discord_content_budget(self):
        text = "😀" * 2500 + " **fim**"
        parts = chunks(text)
        self.assertEqual("".join(parts), text)
        self.assertTrue(all(len(p.encode("utf-16-le")) // 2 <= 1900 for p in parts))

    async def test_media_rejects_ssrf_redirects_and_unsupported_files(self):
        self.assertFalse(
            cdn_url("https://cdn.discordapp.com.evil.test/attachments/1/a.png")
        )
        self.assertFalse(cdn_url("http://127.0.0.1/attachments/a.png"))
        self.assertFalse(cdn_url("https://cdn.discordapp.com:8443/attachments/a.png"))
        with self.assertRaises(ValueError):
            filename("payload.exe")
        with self.assertRaises(ValueError):
            await self.engine.media.download(
                {"url": "https://localhost/secret", "filename": "a.png", "size": 1}, 100
            )

    async def test_transport_hash_contains_no_message_body_and_survives_restart(self):
        source = self.message(content="Mensagem que não deve ir para cada recibo")
        self.hooks[120].lose_ack = True
        await self.engine.ingest(source)
        await self.flush()
        job = self.engine.store.delivery(source.id, 20)
        self.assertNotIn(source.content, job["attempt_payload"])
        self.assertEqual(len(json.loads(job["attempt_payload"])["fingerprint"]), 64)

    async def test_backup_restores_consent_and_receipts_without_archiving_chat_text(
        self,
    ):
        import sqlite3
        from contextlib import closing
        from tier_catalog import TierCatalog
        from tier_media import MediaLibrary

        MediaLibrary(self.base, TierCatalog())
        source = self.message(content="PRIVATE_CHAT_CACHE_SENTINEL")
        await self.engine.ingest(source)
        await self.flush()
        directory, _ = make_snapshot(self.base.path, now=self.now[0])
        with closing(sqlite3.connect(directory / "tierlist.sqlite3")) as database:
            self.assertEqual(
                database.execute("SELECT payload FROM global_messages").fetchone()[0],
                "{}",
            )
        self.assertNotIn(
            b"PRIVATE_CHAT_CACHE_SENTINEL",
            (directory / "tierlist.sqlite3").read_bytes(),
        )
        restored = restore_snapshot(directory, Path(self.temp.name) / "restored")
        recovered = TierStore(restored, clock=lambda: self.now[0])
        try:
            global_store = GlobalStore(recovered)
            self.assertTrue(global_store.consented(7))
            self.assertEqual(len(global_store.rows("SELECT * FROM global_receipts")), 2)
        finally:
            recovered.close()

    async def test_confirmation_does_not_import_earlier_messages_or_reset_accepted_time(
        self,
    ):
        self.counter = discord.utils.time_snowflake(
            datetime.fromtimestamp(self.now[0], timezone.utc)
        )
        self.engine.store.consent(7, False)
        before = self.message(content="Antes de confirmar")
        older = [
            self.message(content=f"Histórico sem confirmação {n}") for n in range(20)
        ]
        self.now[0] += 2
        self.engine.store.consent(7)
        accepted = self.now[0]
        after = self.message(content="Depois de confirmar")
        for message in [before, *older]:
            await self.engine.ingest(message, recovery=True)
        await self.engine.recover()
        await self.flush()
        self.assertIsNone(self.engine.store.message(before.id))
        self.assertIsNotNone(self.engine.store.message(after.id))
        self.now[0] += 10
        self.engine.store.consent(7)
        self.assertEqual(
            self.engine.store.one(
                "SELECT accepted FROM global_consents WHERE user_id='7'"
            )["accepted"],
            accepted,
        )

    async def test_dm_confirmation_shares_only_messages_written_after_accepting(self):
        self.engine.store.consent(7, False)
        earlier = self.message(content="Mensagem sem autorização")
        await self.engine.ingest(earlier)
        row = self.engine.store.invitation(7)
        self.now[0] += 2
        i = self.interaction()
        i.guild_id = None
        i.channel_id = self.dm.id
        i.channel = self.dm
        i.message = self.messages[int(row["message_id"])]
        await GlobalDirectView(self.app).accept.callback(i)
        self.assertTrue(self.engine.store.consented(7))
        self.assertNotIn(i.message.id, self.messages)
        await self.engine.ingest(earlier, recovery=True)
        later = self.message(content="Depois da confirmação")
        await self.engine.ingest(later)
        await self.flush()
        self.assertIsNone(self.engine.store.message(earlier.id))
        self.assertEqual(len(self.copies(later)), 2)

    async def test_live_download_and_completed_asset_are_safe_from_cleanup(self):
        import os
        import time

        media = self.engine.media
        asset = vars(self.asset())
        prepared = await media.download(asset, 1024)
        path = media.path(prepared)
        os.utime(path, (time.time() - 100, time.time() - 100))
        media.cleanup(set())
        self.assertTrue(path.exists())
        media.release([prepared])
        media.cleanup(set())
        self.assertFalse(path.exists())

        async def slow_chunks(size):
            download = next(media.root.iterdir())
            os.utime(download, (time.time() - 100, time.time() - 100))
            media.cleanup(set())
            self.assertTrue(download.exists())
            yield self.blobs[asset["url"]]

        response = UploadResponse(self.blobs[asset["url"]])
        response.iter_chunked = slow_chunks
        media.session = AsyncMock(
            return_value=SimpleNamespace(get=lambda *a, **kw: response)
        )
        prepared = await media.download(asset, 1024)
        media.release([prepared])
        self.assertEqual(media.reserved, 0)
        self.assertFalse(media.downloads)

    async def test_concurrent_media_reservations_enforce_cache_ceiling(self):
        media = self.engine.media
        started, resume = asyncio.Event(), asyncio.Event()
        response = UploadResponse(b"12345678")

        async def paused(size):
            started.set()
            await resume.wait()
            yield b"12345678"

        response.iter_chunked = paused
        media.session = AsyncMock(
            return_value=SimpleNamespace(get=lambda *a, **kw: response)
        )
        asset = vars(self.asset("a.txt", b"12345678"))
        with patch("global_media.CACHE_LIMIT", 10):
            pending = asyncio.create_task(media.download(asset, 100))
            await started.wait()
            try:
                with self.assertRaisesRegex(ValueError, "cache temporário"):
                    await media.download(asset, 100)
            finally:
                resume.set()
                prepared = await pending
                media.release([prepared])
        self.assertEqual(media.reserved, 0)

    async def test_incomplete_or_redirected_media_is_never_published(self):
        asset = vars(self.asset("a.txt", b"original"))
        for status, blob in ((302, b"original"), (200, b"short")):
            response = UploadResponse(blob)
            response.status = status
            self.engine.media.session = AsyncMock(
                return_value=SimpleNamespace(get=lambda *a, **kw: response)
            )
            with self.assertRaises(ValueError):
                await self.engine.media.download(asset, 100)
            self.assertFalse(list(self.engine.media.root.iterdir()))
            self.assertEqual(self.engine.media.reserved, 0)

    async def test_activation_reuses_owned_hook_and_enforces_permissions_and_scope(
        self,
    ):
        channel = self.channels[10]
        self.engine.onboarding.cleanup_public = AsyncMock()
        await self.engine.activate(channel)
        channel.create_webhook.assert_not_awaited()
        self.assertEqual(self.engine.store.channel(1)["hook_id"], "110")
        channel.permissions_for.return_value.manage_webhooks = False
        with self.assertRaisesRegex(ValueError, "Gerenciar webhooks"):
            await self.engine.activate(channel)
        channel.permissions_for.return_value.manage_webhooks = True
        channel.is_nsfw.return_value = True
        with self.assertRaisesRegex(ValueError, "restrição de idade"):
            await self.engine.activate(channel)

    async def test_permission_revocation_at_destination_prevents_webhook_token_bypass(
        self,
    ):
        source = self.message()
        await self.engine.ingest(source)
        self.channels[20].permissions_for.return_value.manage_webhooks = False
        await self.flush()
        self.assertEqual({m.channel.id for m in self.copies(source)}, {30})
        self.assertIn("permissões", self.engine.store.delivery(source.id, 20)["error"])

    async def test_local_blocks_also_exclude_reply_quotes(self):
        source = self.message(content="Não mostrar citação neste destino")
        await self.engine.ingest(source)
        await self.flush()
        self.engine.store.block(3, "user", 7, 8, "Bloqueio local de teste")
        other = SimpleNamespace(**{**vars(self.author), "id": 8})
        self.engine.store.consent(8)
        answer = self.message(
            self.channels[20], content="Resposta permitida", author=other
        )
        answer.reference = SimpleNamespace(
            message_id=next(m.id for m in self.copies(source) if m.channel.id == 20)
        )
        await self.engine.ingest(answer)
        await self.flush()
        target = [
            m
            for m in self.messages.values()
            if m.webhook_id and m.channel.id == 30 and "Resposta permitida" in m.content
        ]
        self.assertEqual(len(target), 1)
        self.assertNotIn(source.content, target[0].content)

    async def test_recovery_finds_an_offline_source_deletion(self):
        source = self.message()
        await self.engine.ingest(source)
        await self.flush()
        self.messages.pop(source.id)
        self.now[0] += 301
        await self.engine.recover()
        await self.flush()
        self.assertFalse(self.copies(source))

    async def test_receipts_expire_after_thirty_days_but_consent_and_discord_history_stay(
        self,
    ):
        source = self.message()
        await self.engine.ingest(source)
        await self.flush()
        self.now[0] += 30 * 86400 + 1
        self.engine.store.cleanup()
        self.assertIsNone(self.engine.store.message(source.id))
        self.assertFalse(self.engine.store.rows("SELECT * FROM global_receipts"))
        self.assertTrue(self.engine.store.consented(7))
        self.assertEqual(len(self.copies(source)), 2)

    async def test_a_retry_cannot_revive_a_paused_delivery(self):
        source = self.message()
        await self.engine.ingest(source)
        job = self.engine.store.delivery(source.id, 20)
        self.engine.store.active(2, False)
        self.engine.store.retry(job, "Artificial late failure")
        self.assertEqual(
            self.engine.store.delivery(source.id, 20)["state"], "cancelled"
        )

    async def test_pausing_does_not_cancel_an_already_requested_removal(self):
        source = self.message()
        await self.engine.ingest(source)
        await self.flush()
        self.engine.store.erase(source.id)
        self.engine.store.active(1, False)
        self.engine.store.active(2, False)
        await self.flush()
        self.assertFalse(self.copies(source))

    async def test_activation_never_publishes_a_panel(self):
        self.engine.store.db.execute("UPDATE global_channels SET panel_id=NULL")
        await self.engine.activate(self.channels[10])
        self.channels[10].send.assert_not_awaited()
        self.assertIsNone(self.engine.store.channel(1)["panel_id"])

    async def test_owner_diagnostics_do_not_appear_to_other_administrators(self):
        self.assertIn(
            "Somente para você",
            GlobalAdminView(self.app, self.interaction(admin=True)).description(),
        )
        self.assertNotIn(
            "Somente para você",
            GlobalAdminView(
                self.app, self.interaction(user=8, admin=True)
            ).description(),
        )
        view = GlobalAdminView(self.app, self.interaction(admin=True))
        self.engine.store.active(1, False)
        with self.assertRaisesRegex(ValueError, "configurações mudaram"):
            await view.activate.callback(self.interaction(admin=True))

    async def test_first_invite_is_once_per_account_across_guilds_bursts_and_restart(
        self,
    ):
        self.engine.store.consent(7, False)
        sources = [
            self.message(
                self.channels[10 if n % 2 else 20], content=f"Primeiro contato {n}"
            )
            for n in range(30)
        ]
        await asyncio.gather(*(self.engine.ingest(m) for m in sources))
        self.author.send.assert_awaited_once()
        self.assertEqual(self.engine.store.invitation(7)["status"], "pending")
        self.assertTrue(GlobalStore(self.base).invitation(7))
        await self.engine.ingest(self.message(self.channels[30]))
        self.assertEqual(self.author.send.await_count, 1)
        self.assertFalse(self.engine.store.rows("SELECT * FROM global_messages"))
        for channel in (self.channels[x] for x in (10, 20, 30)):
            channel.send.assert_not_awaited()
        for message in sources:
            message.reply.assert_not_awaited()
            message.delete.assert_not_awaited()

    async def test_blocked_dm_has_no_public_fallback_and_member_can_confirm_privately(
        self,
    ):
        self.engine.store.consent(7, False)
        self.author.send.side_effect = discord.Forbidden(
            SimpleNamespace(status=403, reason="Forbidden"),
            {"code": 50007, "message": "Cannot send messages to this user"},
        )
        for _ in range(3):
            source = self.message()
            await self.engine.ingest(source)
            source.reply.assert_not_awaited()
        self.author.send.assert_awaited_once()
        self.assertEqual(self.engine.store.invitation(7)["status"], "unavailable")
        i = self.interaction()
        await GlobalMemberView(self.app, i).join.callback(i)
        self.assertTrue(i.response.send_message.await_args.kwargs["ephemeral"])
        await ConsentView(self.app, i, self.engine.store.channel(1)).accept.callback(i)
        i.delete_original_response.assert_awaited_once()
        self.assertTrue(self.engine.store.consented(7))
        later = self.message(content="Mensagem após confirmar pelo comando")
        await self.engine.ingest(later)
        await self.flush()
        self.assertEqual(len(self.copies(later)), 2)

    async def test_declining_dm_removes_invitation_without_consent_or_repeated_prompts(
        self,
    ):
        self.engine.store.consent(7, False)
        source = self.message()
        await self.engine.ingest(source)
        i = self.direct_interaction()
        await GlobalDirectView(self.app).cancel.callback(i)
        self.assertFalse(self.engine.store.consented(7))
        self.assertNotIn(i.message.id, self.messages)
        self.assertEqual(self.engine.store.invitation(7)["status"], "declined")
        await self.engine.ingest(self.message(self.channels[20]))
        self.assertEqual(self.author.send.await_count, 1)
        self.assertFalse(self.engine.store.jobs())

    async def test_dm_buttons_cannot_be_reused_by_another_person_channel_or_message(
        self,
    ):
        self.engine.store.consent(7, False)
        await self.engine.ingest(self.message())
        view = GlobalDirectView(self.app)
        for key, value in [
            ("user", SimpleNamespace(**{**vars(self.author), "id": 8})),
            ("channel_id", 999),
            ("message", SimpleNamespace(id=999)),
            ("guild_id", 1),
        ]:
            i = self.direct_interaction()
            setattr(i, key, value)
            with self.assertRaises(ValueError):
                await view.accept.callback(i)
        self.assertFalse(self.engine.store.consented(7))

    async def test_stale_or_blocked_dm_never_grants_participation(self):
        self.engine.store.consent(7, False)
        await self.engine.ingest(self.message())
        i = self.direct_interaction()
        self.engine.store.block("*", "user", 7, 8, "Bloqueio durante convite")
        with self.assertRaisesRegex(ValueError, "bloqueada"):
            await GlobalDirectView(self.app).accept.callback(i)
        self.engine.store.block(
            "*", "user", 7, 8, "Removendo bloqueio de teste", enabled=False
        )
        self.engine.store.active(1, False)
        with self.assertRaisesRegex(ValueError, "conexão"):
            await GlobalDirectView(self.app).accept.callback(i)
        self.assertFalse(self.engine.store.consented(7))

    async def test_dm_cannot_confirm_after_leaving_source_guild(self):
        self.engine.store.consent(7, False)
        await self.engine.ingest(self.message())
        self.channels[10].guild.get_member = lambda uid: None
        with self.assertRaisesRegex(ValueError, "acesso ao servidor"):
            await GlobalDirectView(self.app).accept.callback(self.direct_interaction())
        self.assertFalse(self.engine.store.consented(7))

    async def test_slash_confirmation_also_removes_a_pending_dm_invitation(self):
        self.engine.store.consent(7, False)
        await self.engine.ingest(self.message())
        invitation_id = int(self.engine.store.invitation(7)["message_id"])
        i = self.interaction()
        await ConsentView(self.app, i, self.engine.store.channel(1)).accept.callback(i)
        self.assertNotIn(invitation_id, self.messages)
        self.assertEqual(self.engine.store.invitation(7)["status"], "accepted")
        with self.assertRaises(ValueError):
            stale = self.interaction()
            stale.guild_id = None
            stale.channel_id = self.dm.id
            stale.message = SimpleNamespace(id=invitation_id)
            await GlobalDirectView(self.app).cancel.callback(stale)
        self.assertTrue(self.engine.store.consented(7))

    async def test_private_error_notice_never_replies_in_public(self):
        source = self.message()
        for _ in range(5):
            await self.engine.notice(source, "O envio não pôde ser confirmado.")
        self.author.send.assert_awaited_once()
        source.reply.assert_not_awaited()
        self.channels[10].send.assert_not_awaited()

    async def test_legacy_cleanup_preserves_people_webhooks_and_other_bot_messages(
        self,
    ):
        channel = self.channels[10]
        legacy = payload(
            content="## Participe do chat global", view=GlobalPanelView(self.app)
        )
        old = self.send_notice(channel, legacy)
        other_bot = self.send_notice(channel, legacy)
        other_bot.author = SimpleNamespace(id=99, bot=True)
        human = self.message(content="## Participe do chat global")
        human.components = old.components
        webhook = self.send_notice(channel, legacy)
        webhook.webhook_id = 110
        unrelated = self.send_notice(
            channel, payload(content="Uma mensagem da tier list")
        )
        self.engine.store.db.execute(
            "UPDATE global_channels SET panel_id=? WHERE guild_id=?", (str(old.id), "1")
        )
        self.now[0] += 1
        await self.engine.onboarding.cleanup_public(self.engine.store.channel(1))
        self.assertNotIn(old.id, self.messages)
        for message in (other_bot, human, webhook, unrelated):
            self.assertIn(message.id, self.messages)
            message.delete.assert_not_awaited()
        channel.send.assert_not_awaited()

    async def test_legacy_cleanup_paginates_and_does_not_recreate_public_ui(self):
        channel = self.channels[10]
        self.engine.store.db.execute(
            "UPDATE global_channels SET panel_id=NULL,enabled_at=enabled_at-1"
        )
        old = [
            self.send_notice(
                channel,
                payload(
                    content="## Participe do chat global",
                    view=GlobalPanelView(self.app),
                ),
            )
            for _ in range(120)
        ]
        for _ in range(4):
            await self.engine.onboarding.cleanup_public(self.engine.store.channel(1))
        self.assertTrue(all(m.id not in self.messages for m in old))
        self.assertEqual(self.base.get("global-private-ui-migration:10"), "done")
        channel.send.assert_not_awaited()

    async def test_legacy_buttons_only_redirect_privately(self):
        i = self.interaction()
        await GlobalPanelView(self.app).children[0].callback(i)
        self.assertTrue(i.response.send_message.await_args.kwargs["ephemeral"])
        self.assertIn(
            "/chatglobal",
            visible_text(i.response.send_message.await_args.kwargs["view"]),
        )

    async def test_new_copies_never_use_username_or_guild_from_an_old_queued_payload(
        self,
    ):
        source = self.message()
        await self.engine.ingest(source)
        row = self.engine.store.message(source.id)
        data = json.loads(row["payload"])
        data["username"] = "[Owner] Nome (@nome_real) · Servidor antigo"
        self.engine.store.db.execute(
            "UPDATE global_messages SET payload=? WHERE id=?",
            (json.dumps(data), str(source.id)),
        )
        await self.flush()
        self.assertTrue(
            all(m.author.name == "Juninho [Owner]" for m in self.copies(source))
        )

    async def test_declining_while_the_dm_send_is_pending_does_not_restore_the_invite(
        self,
    ):
        self.engine.store.consent(7, False)
        started, release = asyncio.Event(), asyncio.Event()

        async def delayed(**kwargs):
            started.set()
            await release.wait()
            return self.send_notice(self.dm, kwargs)

        self.author.send.side_effect = delayed
        pending = asyncio.create_task(self.engine.ingest(self.message()))
        await started.wait()
        try:
            i = self.interaction()
            await ConsentView(
                self.app, i, self.engine.store.channel(1)
            ).cancel.callback(i)
        finally:
            release.set()
            await pending
        self.assertFalse(self.engine.store.consented(7))
        self.assertEqual(self.engine.store.invitation(7)["status"], "declined")
        self.assertFalse(
            [m for m in self.messages.values() if m.channel.id == self.dm.id]
        )

    async def test_dm_confirmation_rechecks_pause_after_a_membership_fetch(self):
        self.engine.store.consent(7, False)
        await self.engine.ingest(self.message())
        self.channels[10].guild.get_member = lambda uid: None

        async def paused(uid):
            self.engine.store.active(1, False)
            return self.author

        self.channels[10].guild.fetch_member.side_effect = paused
        with self.assertRaisesRegex(ValueError, "conexão"):
            await GlobalDirectView(self.app).accept.callback(self.direct_interaction())
        self.assertFalse(self.engine.store.consented(7))

    async def test_expired_private_invites_are_removed_without_new_automatic_attempts(
        self,
    ):
        self.engine.store.consent(7, False)
        await self.engine.ingest(self.message())
        invitation = self.direct_interaction().message
        self.now[0] += 30 * 86400 + 1
        await self.engine.onboarding.cleanup_private()
        self.assertNotIn(invitation.id, self.messages)
        self.assertEqual(self.engine.store.invitation(7)["status"], "expired")
        await self.engine.ingest(self.message())
        self.author.send.assert_awaited_once()
