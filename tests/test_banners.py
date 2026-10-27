"""Local-only banner journeys: scope, image isolation, permissions and receipts."""

import io
import json
import tempfile
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from PIL import Image

from banner_reader import image_message
from banner_relay import BannerControls, SOURCE_CHANNEL_IDS, image_extension, image_url
from game_sources import DAILY_CHANNEL_ID, SOURCE_CHANNELS, IMAGE_SOURCE_CHANNELS, reader_token
from community_bot import CommunityBot


def png():
    out = io.BytesIO()
    Image.new("RGB", (160, 90), "navy").save(out, format="PNG")
    return out.getvalue()


async def iterate(values):
    for value in values:
        yield value


class BannerCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = CommunityBot(self.temp.name)
        self.relay = self.app.banners
        self.now = 2_000_000_000.0
        self.relay.clock = lambda: self.now
        self.app.health.storage_level = "ok"
        self.app._connection.user = SimpleNamespace(id=42)
        self.channels, self.sent, self.history = {}, [], {}
        self.blob = png()
        self.relay.download = AsyncMock(return_value=self.blob)
        self.app.get_channel = lambda ident: self.channels.get(ident)
        self.app.http.send_message = AsyncMock(side_effect=self.send)
        for gid in (1, 2):
            self.add_channel(gid, gid * 10)

    def add_channel(self, gid, cid):
        channel = MagicMock(spec=discord.TextChannel)
        channel.id = cid
        channel.guild = SimpleNamespace(id=gid, me=SimpleNamespace(id=42), filesize_limit=10 * 1024 * 1024)
        channel.permissions_for.return_value = discord.Permissions(view_channel=True, send_messages=True, attach_files=True, read_message_history=True)
        channel.history.side_effect = lambda **kw: iterate(self.history.get(cid, []))
        self.channels[cid] = channel
        return channel

    async def asyncTearDown(self):
        await self.app.close()
        self.temp.cleanup()

    async def send(self, channel_id, *, params):
        files = [{"filename": file.filename, "blob": file.fp.read()} for file in params.files]
        payload = params.payload if params.payload is not None else json.loads(next(part["value"] for part in params.multipart if part["name"] == "payload_json"))
        data = {"channel": channel_id, "payload": dict(payload), "files": files}
        self.sent.append(data)
        return {"id": str(9000 + len(self.sent))}

    def event(self, **overrides):
        return {"channel_id": str(SOURCE_CHANNEL_IDS[0]), "message_id": "123456789012345678",
                "created_at": self.now, "images": ["https://cdn.discordapp.com/attachments/993219350179876874/123/banner.png"], **overrides}

    def interaction(self, guild=1, channel=10, *, admin=True, actor=7):
        return SimpleNamespace(guild_id=guild, channel_id=channel, channel=self.channels[channel],
                               guild=self.channels[channel].guild, user=SimpleNamespace(id=actor),
                               permissions=discord.Permissions(manage_guild=admin), client=self.app,
                               response=SimpleNamespace(defer=AsyncMock(), is_done=lambda: True),
                               followup=SimpleNamespace(send=AsyncMock()))

    def jobs(self):
        return self.relay.db.execute("SELECT * FROM banner_jobs ORDER BY channel_id").fetchall()

    async def test_setbanner_uses_current_channel_private_confirmation_and_admin_permission(self):
        self.assertEqual({command.name for command in self.app.tree.get_commands()}, {"setbanner", "globalchat", "dailychallenge"})
        self.assertFalse(self.app.tierlist_enabled)
        command = self.app.tree.get_command("setbanner")
        self.assertEqual(command.default_permissions.value, discord.Permissions(manage_guild=True).value)
        self.assertFalse(command.parameters)
        i = self.interaction()
        await command.callback(i)
        self.assertEqual(self.relay.target(1)["channel_id"], "10")
        i.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
        self.assertTrue(i.followup.send.call_args.kwargs["ephemeral"])
        self.assertEqual(self.sent, [])

    async def test_paused_tierlist_does_not_collect_server_messages_or_remove_saved_data(self):
        self.app.store.set("synthetic-preserved-ranking", "keep")
        self.assertIsNone(self.app.collect_message(SimpleNamespace()))
        await self.app.close()
        self.app = CommunityBot(self.temp.name)
        self.assertEqual(self.app.store.get("synthetic-preserved-ranking"), "keep")
        self.assertIsNone(self.app.tree.get_command("tierlist"))

    async def test_members_and_missing_bot_permissions_cannot_configure(self):
        command = self.app.tree.get_command("setbanner")
        with self.assertRaises(ValueError):
            await command.callback(self.interaction(admin=False))
        self.channels[10].permissions_for.return_value.attach_files = False
        with self.assertRaisesRegex(ValueError, "Attach Files"):
            await command.callback(self.interaction())
        self.assertIsNone(self.relay.target(1))

    async def test_only_configured_source_is_processed_before_any_download(self):
        for event in [self.event(channel_id="999"), self.event(images=[]), self.event(images=["https://example.com/private.png"]),
                      self.event(created_at=self.now - 4000), self.event(created_at=float("inf"))]:
            self.assertFalse(await self.relay.accept(event))
        self.relay.download.assert_not_awaited()
        self.assertEqual(self.jobs(), [])

    async def test_images_only_fan_out_to_each_configured_server_unchanged(self):
        before = self.app.store.connection.execute("SELECT COUNT(*) FROM tier_publications").fetchone()[0]
        self.relay.configure(1, 10)
        self.relay.configure(2, 20)
        self.assertTrue(await self.relay.accept(self.event(body="Do not forward this text", author="Do not forward")))
        await self.relay.cycle()
        self.assertEqual({item["channel"] for item in self.sent}, {10, 20})
        for item in self.sent:
            self.assertFalse(item["payload"].get("content"))
            self.assertFalse(item["payload"].get("embeds"))
            self.assertEqual(item["files"][0]["blob"], self.blob)
            self.assertTrue(item["payload"]["enforce_nonce"])
            self.assertEqual(item["payload"]["allowed_mentions"]["parse"], [])
        self.assertEqual([row["state"] for row in self.jobs()], ["sent", "sent"])
        self.assertEqual(self.app.store.connection.execute("SELECT COUNT(*) FROM tier_publications").fetchone()[0], before)

    async def test_repeated_events_edits_and_reconfiguration_do_not_duplicate_images(self):
        self.relay.configure(1, 10)
        await self.relay.accept(self.event())
        await self.relay.cycle()
        self.assertFalse(await self.relay.accept(self.event(created_at=self.now + 1)))
        self.relay.configure(1, 10)
        await self.relay.cycle()
        self.relay.disable(1)
        self.relay.configure(1, 10)
        await self.relay.cycle()
        self.assertEqual(len(self.sent), 1)

    async def test_channel_move_cancels_pending_old_destination_and_new_server_receives_latest(self):
        self.relay.configure(1, 10)
        await self.relay.accept(self.event())
        self.add_channel(1, 11)
        self.relay.configure(1, 11)
        self.relay.configure(2, 20)
        await self.relay.cycle()
        self.assertEqual({item["channel"] for item in self.sent}, {11, 20})

    async def test_disable_is_bound_to_admin_actor_and_guild_and_cancels_jobs(self):
        self.relay.configure(1, 10)
        self.relay.configure(2, 20)
        await self.relay.accept(self.event())
        i = self.interaction()
        view = BannerControls(self.app, i)
        self.assertFalse(await view.interaction_check(self.interaction(actor=8)))
        self.assertFalse(await view.interaction_check(self.interaction(admin=False)))
        self.assertTrue(await view.interaction_check(i))
        await view.disable.callback(i)
        await self.relay.cycle()
        self.assertEqual([item["channel"] for item in self.sent], [20])
        self.assertIsNone(self.relay.target(1))
        self.assertIsNotNone(self.relay.target(2))

    async def test_source_edits_with_new_image_are_delivered_and_replace_pending_older_image(self):
        self.relay.configure(1, 10)
        await self.relay.accept(self.event())
        out = io.BytesIO()
        Image.new("RGB", (160, 90), "red").save(out, format="PNG")
        self.relay.download.return_value = out.getvalue()
        self.now += 1
        self.assertTrue(await self.relay.accept(self.event()))
        await self.relay.cycle()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0]["files"][0]["blob"], out.getvalue())

    async def test_uncertain_send_is_reconciled_without_republishing(self):
        self.relay.configure(1, 10)
        await self.relay.accept(self.event())
        async def lose_ack(channel_id, *, params):
            await self.send(channel_id, params=params)
            item = self.sent[-1]
            self.history[10] = [SimpleNamespace(id=999, author=SimpleNamespace(id=42), nonce=item["payload"]["nonce"],
                                                attachments=[SimpleNamespace(filename=file["filename"]) for file in item["files"]])]
            raise TimeoutError("synthetic lost acknowledgement")
        self.app.http.send_message.side_effect = lose_ack
        await self.relay.cycle()
        self.assertEqual(self.jobs()[0]["state"], "uncertain")
        self.now += 31
        await self.relay.cycle()
        self.assertEqual(self.jobs()[0]["state"], "sent")
        self.assertEqual(len(self.sent), 1)

    async def test_unknown_send_stays_pending_confirmation_without_duplicate_retry(self):
        self.relay.configure(1, 10)
        await self.relay.accept(self.event())
        self.app.http.send_message.side_effect = TimeoutError("synthetic")
        await self.relay.cycle()
        self.now += 31
        await self.relay.cycle()
        self.assertEqual(self.jobs()[0]["state"], "uncertain")
        self.assertEqual(self.app.http.send_message.await_count, 1)

    async def test_disable_and_reenable_preserve_uncertain_receipt_instead_of_resending(self):
        self.relay.configure(1, 10)
        await self.relay.accept(self.event())
        self.app.http.send_message.side_effect = TimeoutError("synthetic")
        await self.relay.cycle()
        self.relay.disable(1)
        self.now += 31
        await self.relay.cycle()
        self.relay.configure(1, 10)
        await self.relay.cycle()
        self.assertEqual(self.jobs()[0]["state"], "uncertain")
        self.assertEqual(self.app.http.send_message.await_count, 1)

    async def test_persistence_preserves_target_and_confirmed_delivery(self):
        self.relay.configure(1, 10)
        await self.relay.accept(self.event())
        await self.relay.cycle()
        await self.app.close()
        self.app = CommunityBot(self.temp.name)
        self.relay = self.app.banners
        self.relay.clock = lambda: self.now
        self.assertEqual(self.relay.target(1)["channel_id"], "10")
        self.assertEqual(self.jobs()[0]["state"], "sent")

    async def test_expired_images_and_queue_are_removed(self):
        self.relay.configure(1, 10)
        await self.relay.accept(self.event())
        self.now += 4000
        await self.relay.cycle()
        self.assertEqual(self.jobs(), [])
        self.assertEqual(self.relay.db.execute("SELECT COUNT(*) FROM banner_assets").fetchone()[0], 0)
        self.assertIsNotNone(self.relay.target(1))

    async def test_reader_receives_account_secret_over_pipe_without_bot_or_groq_credentials(self):
        process = SimpleNamespace(stdin=SimpleNamespace(write=MagicMock(), drain=AsyncMock(), close=MagicMock()),
                                  stdout=iterate([b'{"event":"login_failed"}\n']), wait=AsyncMock(return_value=2), returncode=2)
        self.app.wait_until_ready = AsyncMock()
        with patch.dict("os.environ", {"BANNER_READER_TOKEN": "synthetic-account-secret", "DISCORD_TOKEN": "synthetic-bot-secret", "GROQ_API_KEY": "synthetic-groq-secret"}), patch("asyncio.create_subprocess_exec", AsyncMock(return_value=process)) as spawn:
            await self.relay.supervise()
        kwargs = spawn.call_args.kwargs
        for key in ["BANNER_READER_TOKEN", "DISCORD_TOKEN", "GROQ_API_KEY"]:
            self.assertNotIn(key, kwargs["env"])
        self.assertNotIn("synthetic-account-secret", repr(spawn.call_args))
        data = json.loads(process.stdin.write.call_args.args[0])
        self.assertEqual(data["source_channel_ids"], list(IMAGE_SOURCE_CHANNELS))
        self.assertFalse(data['questions_enabled'])
        self.assertEqual(data['questions_channel_id'],0)
        self.assertEqual(self.relay.status, "login_failed")

    async def test_source_failures_do_not_hide_the_other_image_feed_status(self):
        async def events():
            yield json.dumps({'event':'ready','channel_id':str(SOURCE_CHANNEL_IDS[0])}).encode()+b'\n'
            yield json.dumps({'event':'source_unavailable','channel_id':str(DAILY_CHANNEL_ID),'reason':'Forbidden'}).encode()+b'\n'
            raise __import__('asyncio').CancelledError()
        process=SimpleNamespace(stdin=SimpleNamespace(write=MagicMock(),drain=AsyncMock(),close=MagicMock()),stdout=events(),returncode=2)
        self.app.wait_until_ready=AsyncMock()
        with patch.dict('os.environ',{'SECONDARY_ACCOUNT_TOKEN':'synthetic-only'}),patch('asyncio.create_subprocess_exec',AsyncMock(return_value=process)):
            with self.assertRaises(__import__('asyncio').CancelledError):await self.relay.supervise()
        self.assertEqual(self.relay.status,'ready')
        self.assertEqual(self.app.daily.status,'source_unavailable')
        self.assertIn('Reader connected',self.relay.description())
        self.assertIn('could not confirm source access',self.app.daily.description())

    async def test_daily_challenge_has_its_own_source_destinations_and_longer_retention(self):
        daily = self.app.daily
        daily.clock = lambda: self.now
        daily.download = AsyncMock(return_value=self.blob)
        self.relay.configure(1, 10)
        i = self.interaction(guild=2, channel=20)
        await self.app.tree.get_command("dailychallenge").callback(i)
        event = self.event(channel_id=str(DAILY_CHANNEL_ID), created_at=self.now - 12 * 3600)
        self.assertFalse(await self.relay.accept(event))
        self.assertTrue(await daily.accept(event))
        await daily.cycle()
        self.assertEqual([item["channel"] for item in self.sent], [20])
        view = BannerControls(self.app, i, kind="daily")
        await view.disable.callback(i)
        self.assertIsNone(daily.target(2))
        self.assertIsNotNone(self.relay.target(1))

    async def test_daily_worker_progresses_while_banner_worker_fails(self):
        import asyncio
        self.app.banners.cycle = AsyncMock(side_effect=RuntimeError('synthetic banner failure'))
        self.app.daily.cycle = AsyncMock()
        await asyncio.gather(self.app.banner_loop.coro(self.app), self.app.daily_loop.coro(self.app))
        self.app.daily.cycle.assert_awaited_once()

    async def test_deleted_destination_disables_only_its_feed(self):
        self.relay.configure(1, 10)
        self.add_channel(1, 11)
        self.app.daily.configure(1, 11)
        await self.app.on_guild_channel_delete(self.channels[10])
        self.assertIsNone(self.relay.target(1))
        self.assertEqual(self.app.daily.target(1)['channel_id'], '11')

    async def test_shared_reader_exit_marks_both_feeds_unavailable(self):
        import asyncio
        process = SimpleNamespace(
            stdin=SimpleNamespace(write=MagicMock(), drain=AsyncMock(), close=MagicMock()),
            stdout=iterate([b'{"event":"ready"}\n']), wait=AsyncMock(return_value=1), returncode=1)
        self.app.wait_until_ready = AsyncMock()
        with patch.dict('os.environ', {'SECONDARY_ACCOUNT_TOKEN': 'synthetic-only'}), patch('asyncio.create_subprocess_exec', AsyncMock(return_value=process)), patch('asyncio.sleep', AsyncMock(side_effect=asyncio.CancelledError())):
            with self.assertRaises(asyncio.CancelledError):
                await self.relay.supervise()
        self.assertEqual(self.relay.status, 'reader_failed')
        self.assertEqual(self.app.daily.status, 'reader_failed')

    async def test_status_does_not_report_an_old_channels_uncertain_delivery_after_move(self):
        self.relay.configure(1, 10)
        await self.relay.accept(self.event())
        self.relay.state(self.jobs()[0], 'uncertain')
        # The old receipt still exists, but no fresh event can seed the new channel.
        self.now += 4000
        self.add_channel(1, 11)
        self.relay.configure(1, 11)
        self.assertNotIn('awaiting confirmation', self.relay.description(1))
        await self.relay.accept(self.event(message_id='123456789012345679'))
        await self.relay.cycle()
        self.assertIn('Last confirmed delivery:', self.relay.private_status(1))


class SourceImageCase(unittest.TestCase):
    def test_source_serializer_forwards_only_images_and_handles_edited_old_messages(self):
        message = SimpleNamespace(id=123, channel=SimpleNamespace(id=SOURCE_CHANNEL_IDS[0]),
                                  created_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
                                  edited_at=datetime(2026, 10, 26, tzinfo=timezone.utc),
                                  content="Never forward this", author=SimpleNamespace(id=999),
                                  attachments=[SimpleNamespace(filename="banner.png", content_type="image/png", url="https://cdn.discordapp.com/attachments/a/b/c.png"),
                                               SimpleNamespace(filename="clip.mp4", content_type="video/mp4", url="https://cdn.discordapp.com/attachments/a/b/c.mp4")],
                                  embeds=[])
        payload = image_message(message, set(SOURCE_CHANNEL_IDS))
        self.assertEqual(len(payload["images"]), 1)
        self.assertNotIn("content", payload)
        self.assertNotIn("author", payload)
        self.assertEqual(payload["created_at"], message.edited_at.timestamp())
        self.assertIsNone(image_message(SimpleNamespace(channel=SimpleNamespace(id=8)), set(SOURCE_CHANNEL_IDS)))

    def test_download_urls_and_actual_file_types_are_restricted(self):
        self.assertTrue(image_url("https://cdn.discordapp.com/attachments/1/2/banner.png?ex=123"))
        for url in ["https://evil.example/a.png", "http://cdn.discordapp.com/attachments/a", "https://user:pass@cdn.discordapp.com/attachments/a", "https://cdn.discordapp.com:8443/attachments/a", "file:///etc/passwd", "https://cdn.discordapp.com/avatars/a.png"]:
            self.assertFalse(image_url(url), url)
        self.assertEqual(image_extension(png()), "png")
        for blob in [b'<svg onload="alert(1)"/>', b"not an image", b"", png()[:20]]:
            with self.assertRaises(ValueError):
                image_extension(blob)

    def test_gif_and_animated_png_webp_are_rejected_even_with_image_extensions(self):
        for fmt in ["GIF", "PNG", "WEBP"]:
            out = io.BytesIO()
            Image.new("RGB", (64, 64), "red").save(out, format=fmt, save_all=True,
                                                    append_images=[Image.new("RGB", (64, 64), "blue")],duration=100,loop=0)
            with self.assertRaises(ValueError):
                image_extension(out.getvalue())

    def test_secondary_account_secret_name_takes_precedence_with_legacy_fallback(self):
        with patch.dict("os.environ", {"SECONDARY_ACCOUNT_TOKEN": "synthetic-current", "BANNER_READER_TOKEN": "synthetic-old"}):
            self.assertEqual(reader_token(), "synthetic-current")
        with patch.dict("os.environ", {"SECONDARY_ACCOUNT_TOKEN": "", "BANNER_READER_TOKEN": "synthetic-old"}):
            self.assertEqual(reader_token(), "synthetic-old")
