from tier_ui import visible_text

"""Player-facing stress, forged interactions, malformed uploads and provider failures."""

import asyncio
import io
import json
import random
import os
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import discord
from PIL import Image, PngImagePlugin
import test_tier_thread as fixtures
from test_tier_thread import png
from tier_views import PollView, ThreadView, AdminView, ImageModal, CorrectionModal
from tier_verify import verify, VerificationClick
from tier_wiki import WikiSync, NAMES, DATA
from tier_media import prepare


class PlayerAbuseCase(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.ThreadRuntimeCase.asyncSetUp
    asyncTearDown = fixtures.ThreadRuntimeCase.asyncTearDown
    interaction = fixtures.ThreadRuntimeCase.interaction
    setup_panel = fixtures.ThreadRuntimeCase.setup_panel
    propose = fixtures.ThreadRuntimeCase.propose
    source = fixtures.ThreadRuntimeCase.source

    async def test_twenty_simultaneous_install_clicks_create_one_panel_and_thread(self):
        await asyncio.gather(*(self.setup_panel() for _ in range(20)))
        self.assertEqual(
            len([p for channel, p in self.env.payloads if channel == 10]), 1
        )
        self.assertEqual(len(self.app.store.thread_targets()), 1)

    async def test_two_hundred_fifty_vote_clicks_from_one_account_count_once(self):
        await self.setup_panel()
        proposal = self.propose()
        await self.app.poll_loop.coro(self.app)
        receipt = self.app.store.poll_messages()[0]
        view = PollView(self.app)

        async def click(n):
            i = self.interaction(admin=False, user=8, channel=self.env.channel)
            i.message = SimpleNamespace(id=int(receipt["message_id"]))
            await view.cast(i, ("approve", "keep", "test")[n % 3])

        await asyncio.gather(*(click(n) for n in range(250)))
        self.assertEqual(sum(self.app.store.poll_counts(proposal["id"]).values()), 1)

    async def test_forged_message_and_wrong_guild_cannot_cast_votes(self):
        await self.setup_panel()
        proposal = self.propose()
        await self.app.poll_loop.coro(self.app)
        receipt = self.app.store.poll_messages()[0]
        for guild, channel, message in (
            (1, receipt["channel_id"], "999"),
            (2, receipt["channel_id"], receipt["message_id"]),
            (1, "888", receipt["message_id"]),
        ):
            with self.assertRaises(ValueError):
                self.app.store.vote(
                    proposal["id"], 8, guild, channel, message, "approve"
                )
        self.assertEqual(sum(self.app.store.poll_counts(proposal["id"]).values()), 0)

    async def test_stale_vote_buttons_reject_clicks_without_waiting_for_visual_refresh(
        self,
    ):
        await self.setup_panel()
        self.propose()
        await self.app.poll_loop.coro(self.app)
        receipt = self.app.store.poll_messages()[0]
        self.now += 600
        i = self.interaction(admin=False, user=8, channel=self.env.channel)
        i.message = SimpleNamespace(id=int(receipt["message_id"]))
        with self.assertRaisesRegex(ValueError, "terminou"):
            await PollView(self.app).cast(i, "approve")
        self.assertEqual(self.app.store.latest()["id"], 0)

    async def test_deleting_every_poll_copy_prevents_publication_even_after_five_votes(
        self,
    ):
        await self.setup_panel()
        proposal = self.propose()
        await self.app.poll_loop.coro(self.app)
        receipt = self.app.store.poll_messages()[0]
        for n in range(5):
            self.app.store.vote(
                proposal["id"],
                n,
                1,
                receipt["channel_id"],
                receipt["message_id"],
                "approve",
            )
        await self.app.on_raw_message_delete(
            SimpleNamespace(message_id=int(receipt["message_id"]))
        )
        self.now += 600
        await self.app.poll_loop.coro(self.app)
        self.assertEqual(
            self.app.store.proposal(proposal["id"])["status"], "unavailable"
        )
        self.assertEqual(self.app.store.latest()["id"], 0)

    async def test_server_admin_cannot_directly_invoke_any_owner_review(self):
        i = self.interaction(user=8)
        view = AdminView(self.app, self.interaction())
        callbacks = [
            item
            for item in view.children
            if item.custom_id
            in (
                "review-images",
                "review-reports",
                "rollback",
                "undo-image",
                "connection-test",
                "full-verification",
                "visual-test",
            )
        ]
        for button in callbacks:
            with self.subTest(button=button.custom_id), self.assertRaises(ValueError):
                await button.callback(i)
        self.assertEqual(self.app.store.latest()["id"], 0)

    async def test_modal_cannot_be_submitted_by_another_person_or_server(self):
        owner = self.interaction(channel=self.env.thread)
        for modal in (ImageModal(self.app, owner), CorrectionModal(self.app, owner)):
            other = self.interaction(user=8, channel=self.env.thread)
            self.assertFalse(await modal.interaction_check(other))
            other = self.interaction(channel=self.env.thread)
            other.guild_id = 2
            self.assertFalse(await modal.interaction_check(other))

    async def test_copied_image_suggestion_button_outside_official_index_is_refused(
        self,
    ):
        await self.setup_panel()
        i = self.interaction(channel=self.env.thread)
        i.message = SimpleNamespace(id=999)
        for button in (ThreadView(self.app).suggest, ThreadView(self.app).submissions):
            with self.subTest(button=button.custom_id), self.assertRaises(ValueError):
                await button.callback(i)

    async def test_forwarded_quotes_and_bulk_deleted_sources_are_not_evidence(self):
        message = self.source()
        message.message_snapshots = ["forwarded"]
        await self.app.on_message(message)
        self.assertEqual(self.app.store.pending(), [])
        message.message_snapshots = []
        await self.app.on_message(message)
        await self.app.on_raw_bulk_message_delete(SimpleNamespace(message_ids={999}))
        self.assertEqual(self.app.store.pending(), [])

    async def test_invalid_choice_does_not_write_a_vote(self):
        await self.setup_panel()
        proposal = self.propose()
        await self.app.poll_loop.coro(self.app)
        receipt = self.app.store.poll_messages()[0]
        for choice in (
            "META_HILL",
            None,
            "approve; DROP TABLE tier_votes",
            "",
            {"approve": True},
        ):
            with self.subTest(choice=str(choice)), self.assertRaises(ValueError):
                self.app.store.vote(
                    proposal["id"],
                    8,
                    1,
                    receipt["channel_id"],
                    receipt["message_id"],
                    choice,
                )
        self.assertEqual(sum(self.app.store.poll_counts(proposal["id"]).values()), 0)

    async def test_account_below_seven_days_cannot_vote_or_send_images(self):
        i = self.interaction(user=8)
        i.user.created_at = discord.utils.utcnow() - timedelta(hours=1)
        with self.assertRaises(ValueError):
            self.app.require_human(i)

    async def test_no_network_calls_when_no_installed_panel_or_key(self):
        with patch.object(self.app.analyzer, "run", new_callable=AsyncMock) as run:
            await self.app.analysis_loop.coro(self.app)
        run.assert_not_awaited()
        self.backend.analyze.assert_not_awaited()

    async def test_reports_are_unique_and_daily_limit_is_bounded(self):
        proposal = self.propose()
        for n in range(20):
            self.app.store.report(
                proposal["id"],
                8,
                1,
                "Texto de teste para revisar uma forma, envio " + str(n),
            )
        self.assertEqual(len(self.app.store.rows("SELECT * FROM tier_reports")), 1)
        self.assertEqual(self.app.store.latest()["id"], 0)

    async def test_registered_server_cannot_flood_another_servers_pending_queue(self):
        self.app.store.register_guild(1)
        self.app.store.register_guild(2)
        for n in range(50):
            self.app.store.ingest(
                "a" + str(n),
                n,
                1,
                10,
                f"Daki no infinito possui alternativa teste{n} outro{n}.",
                {"daki"},
            )
        self.app.store.ingest(
            "small",
            1000,
            2,
            20,
            "Daki tem mais alcance no infinito neste relato independente.",
            {"daki"},
        )
        pending = self.app.store.pending(2)
        self.assertEqual({r["guild_id"] for r in pending}, {"1", "2"})

    async def test_wiki_markdown_unicode_and_long_links_cannot_overflow_discord_fields(
        self,
    ):
        from tier_image import poll_embed

        self.app.catalog.merge_units([{"id": "daki", "name": "*" * 150, "aliases": []}])
        proposal = self.propose()
        detail = proposal["details"]["daki"]
        detail["reason"] = "*" * 700
        detail["conditions"] = "😀" * 300
        detail["sources"] = [
            {
                "quote": "*" * 600,
                "url": "https://animeadventures.fandom.com/wiki/"
                + "%E7%95%8C" * 150
                + "?oldid=123",
            }
        ]
        embed = poll_embed(self.app.store, self.app.catalog, proposal)
        units = lambda text: len(text.encode("utf-16-le")) // 2
        self.assertLessEqual(units(embed.title), 256)
        self.assertLessEqual(units(embed.description), 4096)
        self.assertTrue(all(units(field.value) <= 1024 for field in embed.fields))
        self.assertNotIn("fandom.com", str(embed.to_dict()))
        self.assertEqual(len(detail["sources"]), 1)
        self.assertTrue(detail["sources"][0]["url"].endswith("?oldid=123"))

    async def test_maintenance_makes_a_restorable_snapshot_without_test_rankings(self):
        await self.setup_panel()
        await self.app.maintenance_loop.coro(self.app)
        self.assertTrue((Path(self.temp.name) / "backups/latest.json").exists())
        self.assertEqual(self.app.store.latest()["ranking"], [])

    async def test_player_journey_from_natural_comment_to_vote_image_history_and_rollback(
        self,
    ):
        await self.setup_panel()
        panel = self.app.store.panels()[0]
        conversation = fixtures.MagicMock(spec=discord.TextChannel)
        conversation.id = 20
        conversation.guild = self.env.guild
        conversation.permissions_for.return_value = self.env.permissions
        self.env.channels[20] = conversation
        await self.app.on_message(self.source(channel=conversation))
        packet, _ = self.app.analyzer.packet()
        sid = next(k for k, v in packet["sources"].items() if v["unit_id"] == "daki")
        quote = packet["sources"][sid]["text"][:120]
        self.backend.enabled = True
        self.backend.analyze.return_value = (
            {
                "changes": [
                    {
                        "unit_id": "daki",
                        "tier": "GOOD_GROUND",
                        "mode": "infinite",
                        "before": None,
                        "confidence": 0.95,
                        "supporting_comments": ["c0"],
                        "reason": "Justificativa artificial para testar o percurso completo, sem declarar uma posição real do jogo.",
                        "conditions": "Condições controladas exclusivamente para este teste.",
                        "caveat": "É uma simulação local, sem avaliação real de balanceamento.",
                        "evidence": [{"source_id": sid, "quote": quote}],
                    }
                ]
            },
            100,
        )
        await self.app.analysis_loop.coro(self.app)
        await self.app.poll_loop.coro(self.app)
        proposal = self.app.store.active_proposal()
        receipt = self.app.store.poll_messages()[0]
        for user in range(8, 13):
            i = self.interaction(admin=False, user=user, channel=self.env.channel)
            i.message = SimpleNamespace(id=int(receipt["message_id"]))
            await PollView(self.app).cast(i, "approve")
        self.now += 600
        await self.app.poll_loop.coro(self.app)
        await self.app.panel_loop.coro(self.app)
        self.assertEqual(self.app.store.proposal(proposal["id"])["status"], "approved")
        self.assertEqual(
            self.app.store.latest()["ranking"],
            [{"unit_id": "daki", "tier": "GOOD_GROUND"}],
        )
        self.assertEqual(self.app.store.panels()[0]["message_id"], panel["message_id"])
        archived = self.app.store.rows(
            "SELECT * FROM tier_poll_messages WHERE proposal_id=? AND channel_id=?",
            (proposal["id"], str(self.env.thread.id)),
        )[0]
        result = self.env.partial(self.env.thread, int(archived["message_id"]))
        self.assertIn("Aprovada", visible_text(result))
        self.app.store.rollback(
            self.app.store.latest()["id"],
            7,
            "Reversão artificial no encerramento do percurso completo.",
        )
        await self.app.panel_loop.coro(self.app)
        self.assertEqual(self.app.store.latest()["ranking"], [])
        self.assertEqual(len([p for cid, p in self.env.payloads if cid == 10]), 2)
        self.assertEqual(
            len(self.app.store.rows("SELECT * FROM tier_audit_messages")), 0
        )
        self.assertTrue(
            self.app.store.rows("SELECT * FROM tier_audit WHERE kind='rollback'")
        )


class VerificationCase(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.ThreadRuntimeCase.asyncSetUp
    asyncTearDown = fixtures.ThreadRuntimeCase.asyncTearDown
    interaction = fixtures.ThreadRuntimeCase.interaction

    async def test_isolation_retains_host_prefix_dependencies_with_temporary_home(self):
        from tier_verify import isolated_suite

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            prefix = root / "home" / ".local" / "lib" / "python3.12" / "site-packages"
            prefix.mkdir(parents=True)
            (prefix / "hosting_prefix_probe.py").write_text(
                'VALUE="host-prefix-found"\n'
            )
            (root / "tests").mkdir()
            (root / "tests" / "test_tier_hosting.py").write_text("""
import unittest,os,socket
import hosting_prefix_probe,dotenv,discord
from PIL import Image
class HostingCase(unittest.TestCase):
    def test_runtime(self):
        self.assertEqual(hosting_prefix_probe.VALUE,'host-prefix-found')
        self.assertEqual(os.environ['HOME'],os.environ['DATA_DIR'])
        self.assertNotIn('CUSTOM_CREDENTIAL',os.environ)
        self.assertNotIn('DISCORD_TOKEN',os.environ)
        self.assertFalse(dotenv.load_dotenv())
        with self.assertRaises(OSError):socket.getaddrinfo('blocked.invalid',443)
""")
            with (
                patch("tier_verify.ROOT", root),
                patch.object(sys, "path", [str(prefix), *sys.path]),
                patch.dict(os.environ, {"CUSTOM_CREDENTIAL": "synthetic-only"}),
            ):
                passed, count, output = await isolated_suite()
            self.assertTrue(passed, output)
            self.assertEqual(count, 1)

    async def test_full_verification_uses_isolated_scenarios_and_real_api_adapter(self):
        self.backend.enabled = True
        self.backend.analyze.return_value = ({"changes": []}, 50)
        i = self.interaction()
        i.edit_original_response = AsyncMock()
        with patch(
            "tier_verify.isolated_suite",
            new_callable=AsyncMock,
            return_value=(True, 100, "OK"),
        ):
            report = await verify(self.app, i)
        self.assertFalse(any(c["result"] == "failed" for c in report["checks"]), report)
        self.assertEqual(self.app.store.latest()["id"], 0)
        self.assertEqual(self.app.store.poll_messages(), [])
        self.assertTrue(self.env.thread.archived)
        self.assertTrue(all(not m.exists for m in self.env.messages.values()))
        self.assertEqual(len(self.env.payloads), 3)
        self.assertEqual(
            i.edit_original_response.await_args.kwargs["view"]
            .controller.children[0]
            .label,
            "Confirmar teste de interação",
        )

    async def test_non_owner_cannot_start_full_verification(self):
        i = self.interaction(user=8)
        with self.assertRaises(ValueError):
            await verify(self.app, i)
        self.assertEqual(self.env.payloads, [])

    async def test_host_report_distinguishes_running_code_from_files_changed_without_restart(
        self,
    ):
        self.backend.enabled = True
        self.backend.analyze.return_value = ({"changes": []}, 50)
        i = self.interaction()
        i.edit_original_response = AsyncMock()
        installed = {
            "version": "synthetic-new-version",
            "fingerprint": self.app.build["fingerprint"],
            "verified": True,
            "files_checked": 100,
            "changed_files": [],
        }
        with (
            patch("tier_verify.build_info", return_value=installed),
            patch(
                "tier_verify.isolated_suite",
                new_callable=AsyncMock,
                return_value=(True, 100, "OK"),
            ),
        ):
            report = await verify(self.app, i)
        check = next(
            c
            for c in report["checks"]
            if c["name"] == "Versão e integridade dos arquivos"
        )
        self.assertEqual(check["result"], "failed")
        self.assertEqual(report["build"], self.app.build)
        self.assertEqual(report["installed_build"], installed)
        self.assertIn("reinicie", check["detail"])

    async def test_private_technical_thread_is_preferred_and_owner_is_invited(self):
        self.env.permissions.create_private_threads = True
        i = self.interaction()
        i.edit_original_response = AsyncMock()
        with patch(
            "tier_verify.isolated_suite",
            new_callable=AsyncMock,
            return_value=(True, 100, "OK"),
        ):
            report = await verify(self.app, i)
        self.assertEqual(
            self.env.channel.create_thread.await_args.kwargs["type"],
            discord.ChannelType.private_thread,
        )
        self.assertFalse(self.env.channel.create_thread.await_args.kwargs["invitable"])
        self.env.thread.add_user.assert_awaited_once_with(i.user)
        self.assertEqual(len(report["visual_steps"]), 10)

    async def test_missing_private_thread_permission_does_not_create_public_test_messages(
        self,
    ):
        self.env.permissions.create_private_threads = False
        i = self.interaction()
        i.edit_original_response = AsyncMock()
        with patch(
            "tier_verify.isolated_suite",
            new_callable=AsyncMock,
            return_value=(True, 100, "OK"),
        ):
            report = await verify(self.app, i)
        self.assertEqual(self.env.payloads, [])
        self.env.channel.create_thread.assert_not_awaited()
        self.assertTrue(any(r["result"] == "failed" for r in report["checks"]))

    async def test_human_verification_click_uses_actual_vote_callback_in_temporary_database(
        self,
    ):
        i = self.interaction(channel=self.env.thread)
        i.message = SimpleNamespace(id=123)
        i.edit_original_response = AsyncMock()
        origin = SimpleNamespace(edit_original_response=AsyncMock())
        report = {"checks": []}
        view = VerificationClick(self.app, 7, 1, report, origin)
        self.assertTrue(await view.interaction_check(i))
        await view.click.callback(i)
        self.assertEqual(report["checks"][0]["result"], "passed")
        self.assertEqual(self.app.store.rows("SELECT * FROM tier_votes"), [])
        self.assertEqual(self.app.store.latest()["id"], 0)
        self.assertTrue(view.children[0].disabled)

    async def test_another_user_cannot_use_the_verification_click(self):
        view = VerificationClick(self.app, 7, 1, {"checks": []}, SimpleNamespace())
        self.assertFalse(await view.interaction_check(self.interaction(user=8)))

    async def test_shutdown_cancels_verification_before_closing_database(self):
        entered = asyncio.Event()

        async def waiting():
            entered.set()
            await asyncio.Event().wait()

        i = self.interaction()
        i.edit_original_response = AsyncMock()
        with patch("tier_verify.isolated_suite", side_effect=waiting):
            task = asyncio.create_task(verify(self.app, i))
            await entered.wait()
            await self.app.close()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(self.app.verification_tasks, set())

    async def test_wrong_remote_command_registration_is_reported_without_test_posts(
        self,
    ):
        self.app.tree.fetch_commands.return_value = [
            SimpleNamespace(name="quiz", options=[])
        ]
        i = self.interaction()
        i.edit_original_response = AsyncMock()
        with patch(
            "tier_verify.isolated_suite",
            new_callable=AsyncMock,
            return_value=(True, 100, "OK"),
        ):
            report = await verify(self.app, i)
        self.assertTrue(any(r["result"] == "failed" for r in report["checks"]))
        self.assertEqual(self.env.payloads, [])

    async def test_verification_rejects_remote_tierlist_with_unrestricted_permissions(
        self,
    ):
        self.app.tree.fetch_commands.return_value[0].default_member_permissions = None
        i = self.interaction()
        i.edit_original_response = AsyncMock()
        with patch(
            "tier_verify.isolated_suite",
            new_callable=AsyncMock,
            return_value=(True, 100, "OK"),
        ):
            report = await verify(self.app, i)
        failed = [row for row in report["checks"] if row["result"] == "failed"]
        self.assertTrue(failed, report)
        self.assertIn("Gerenciar servidor", str(failed))
        self.env.channel.create_thread.assert_not_awaited()
        self.assertEqual(self.env.payloads, [])

    async def test_real_probe_cleanup_preserves_another_persons_message(self):
        self.env.permissions.manage_threads = True
        self.env.thread.id = 900
        other = self.env.partial(self.env.thread, 8080)
        other.exists = True
        other.author = SimpleNamespace(id=8)
        i = self.interaction()
        i.edit_original_response = AsyncMock()
        with patch(
            "tier_verify.isolated_suite",
            new_callable=AsyncMock,
            return_value=(True, 100, "OK"),
        ):
            await verify(self.app, i)
        self.assertTrue(other.exists)
        self.assertTrue(self.env.thread.archived)
        self.env.thread.delete.assert_not_awaited()

    async def test_cancelling_isolated_runner_reaps_subprocess_and_drops_credentials(
        self,
    ):
        from tier_verify import isolated_suite

        launch = asyncio.create_subprocess_exec
        started = asyncio.Event()
        processes = []
        environments = []

        async def tracked(*args, **kwargs):
            process = await launch(*args, **kwargs)
            processes.append(process)
            environments.append(kwargs["env"])
            started.set()
            return process

        with (
            patch("tier_verify.BOOTSTRAP", "import time; time.sleep(60)"),
            patch("tier_verify.asyncio.create_subprocess_exec", side_effect=tracked),
            patch.dict(os.environ, {"CUSTOM_CREDENTIAL": "synthetic-only"}),
        ):
            task = asyncio.create_task(isolated_suite())
            await asyncio.wait_for(started.wait(), 5)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertTrue(all(process.returncode is not None for process in processes))
        self.assertTrue(
            all(
                "CUSTOM_CREDENTIAL" not in env
                and "DISCORD_TOKEN" not in env
                and "GROQ_API_KEY" not in env
                for env in environments
            )
        )


class UploadAbuseCase(unittest.TestCase):
    setUp = fixtures.MediaCase.setUp
    tearDown = fixtures.MediaCase.tearDown
    submit = fixtures.MediaCase.submit

    def test_svg_html_and_disguised_executables_are_not_images(self):
        for data in (
            b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
            b'<html><img src="file:///etc/passwd"></html>',
            b"MZ" + b"0" * 1000,
            b"PK\x03\x04" + b"0" * 1000,
        ):
            with self.subTest(data=data[:10]), self.assertRaises(ValueError):
                prepare(data)

    def test_decode_pixel_limit_is_checked_before_large_conversion(self):
        output = io.BytesIO()
        Image.new("RGB", (2048, 2048), "black").save(output, format="PNG")
        with self.assertRaises(ValueError):
            prepare(output.getvalue())

    def test_png_text_metadata_is_removed(self):
        output = io.BytesIO()
        info = PngImagePlugin.PngInfo()
        info.add_text("Description", "Untrusted external text")
        Image.new("RGB", (128, 128), "red").save(output, format="PNG", pnginfo=info)
        with Image.open(io.BytesIO(prepare(output.getvalue()))) as image:
            self.assertNotIn("Description", image.info)

    def test_path_traversal_and_unrecognized_unit_are_rejected(self):
        for name in ("../outside", "a" * 63, "g" * 64, "/etc/passwd"):
            with self.assertRaises(ValueError):
                self.media.path(name)
        with self.assertRaises(ValueError):
            self.media.submit(
                "not-a-unit",
                1,
                1,
                "",
                "Uma sugestão de teste de identidade inválida.",
                png(),
            )

    def test_low_quality_or_empty_forms_do_not_enter_review_queue(self):
        for note in ("", "curto", "x" * 701):
            with self.assertRaises(ValueError):
                self.media.submit("daki", 1, 1, "", note, png())
        self.assertEqual(self.media.pending(), [])

    def test_old_owner_action_cannot_restore_over_a_newer_replacement(self):
        first = self.submit()
        self.media.decide(first, 7, approve=True)
        second = self.submit("blue")
        self.media.decide(second, 7, approve=True)
        with self.assertRaises(ValueError):
            self.media.undo("daki", first, 7)
        self.assertEqual(self.media.approved()["daki"]["suggestion_id"], second)

    def test_compressed_proof_cannot_expand_beyond_backup_file_limit(self):
        image = Image.frombytes(
            "RGB", (1920, 1080), random.Random(42).randbytes(1920 * 1080 * 3)
        )
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=90)
        prepared = prepare(output.getvalue(), proof=True)
        self.assertLessEqual(len(prepared), 4 * 1024 * 1024)
        with Image.open(io.BytesIO(prepared)) as result:
            self.assertEqual(result.format, "PNG")

    def test_mobile_exif_orientation_is_applied_then_removed(self):
        image = Image.new("RGB", (80, 120), "red")
        exif = Image.Exif()
        exif[274] = 6
        output = io.BytesIO()
        image.save(output, format="JPEG", exif=exif)
        with Image.open(io.BytesIO(prepare(output.getvalue()))) as result:
            self.assertEqual(result.size, (120, 80))
            self.assertFalse(result.getexif())

    def test_resubmission_repairs_corrupt_content_without_altering_ranks(self):
        ident = self.submit()
        self.media.decide(ident, 7, approve=True)
        path = self.media.path(self.media.suggestion(ident)["preview_hash"])
        path.write_bytes(b"corrupt")
        repaired = self.submit(user=2)
        self.media.decide(repaired, 7, approve=True)
        with Image.open(path) as result:
            result.verify()
        self.assertEqual(self.store.latest()["ranking"], [])

    def test_snapshot_accepts_relative_data_path_and_retains_verified_predecessor(self):
        from tier_backup import make_snapshot, verify_snapshot

        ident = self.submit()
        self.media.decide(ident, 7, approve=True)
        relative = Path(os.path.relpath(self.store.path))
        directory, _ = make_snapshot(relative, now=self.now)
        verify_snapshot(directory)
        (directory / "tierlist.sqlite3").write_bytes(b"corrupt")
        repaired, state = make_snapshot(relative, now=self.now + 1)
        self.assertEqual(state, "created")
        self.assertNotEqual(repaired, directory)
        verify_snapshot(repaired)

    def test_snapshot_detects_sqlite_changes_even_when_database_is_structurally_valid(
        self,
    ):
        import sqlite3
        from tier_backup import make_snapshot, verify_snapshot

        directory, _ = make_snapshot(self.store.path, now=self.now)
        database = sqlite3.connect(directory / "tierlist.sqlite3")
        with database:
            database.execute("INSERT INTO tier_meta VALUES('unexpected-change','test')")
        self.assertEqual(database.execute("PRAGMA quick_check").fetchone()[0], "ok")
        database.close()
        with self.assertRaisesRegex(ValueError, "hash"):
            verify_snapshot(directory)


class WikiCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = __import__("tier_store").TierStore(
            Path(self.temp.name) / "tierlist.sqlite3", clock=lambda: 2_000_000_000
        )
        self.catalog = __import__("community_domain").Catalog()
        self.evidence = __import__("tier_analysis").EvidenceLibrary()

    async def asyncTearDown(self):
        self.store.close()
        self.temp.cleanup()

    def factory(self, pages, status=200):
        blob = json.dumps({"query": {"pages": pages}}).encode()
        response = SimpleNamespace(
            status=status,
            content=SimpleNamespace(read=AsyncMock(side_effect=[blob, b""])),
        )

        class Context:
            async def __aenter__(self):
                return response

            async def __aexit__(self, *args):
                return False

        self.requests = []
        requests = self.requests

        class Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            def get(self, *args, **kwargs):
                requests.append((args, kwargs))
                return Context()

        return lambda **kwargs: Session()

    def page(self, title, text):
        return {
            "title": title,
            "revisions": [{"revid": 9_000_000, "slots": {"main": {"content": text}}}],
        }

    async def test_latest_revision_is_cited_and_persisted_without_executing_wikitext(
        self,
    ):
        title = self.catalog.units["daki"].name
        body = "Unit mechanics and verified references for a controlled fixture, damage and conditions."
        sync = WikiSync(
            self.store,
            self.catalog,
            self.evidence,
            session_factory=self.factory([self.page(title, body)]),
        )
        old = self.evidence.version
        self.assertTrue(await sync.refresh(["daki"]))
        self.assertNotEqual(self.evidence.version, old)
        self.assertIn("oldid=9000000", self.evidence.sources["daki:article"]["url"])
        self.assertTrue(sync.cache.exists())
        self.assertFalse(self.requests[0][1]["allow_redirects"])

    async def test_unavailable_wiki_preserves_last_valid_source(self):
        old = self.evidence.version
        sync = WikiSync(
            self.store,
            self.catalog,
            self.evidence,
            session_factory=self.factory([], status=403),
        )
        self.assertFalse(await sync.refresh(["daki"]))
        self.assertEqual(self.evidence.version, old)
        self.assertEqual(sync.status, "unavailable")

    async def test_unknown_page_cannot_replace_a_source(self):
        old = self.evidence.version
        sync = WikiSync(
            self.store,
            self.catalog,
            self.evidence,
            session_factory=self.factory([self.page("Not requested", "No valid data")]),
        )
        self.assertFalse(await sync.refresh(["daki"]))
        self.assertEqual(self.evidence.version, old)

    async def test_new_identity_is_added_from_names_and_data_without_a_tier(self):
        names = """return {\n ["Novel Hero"] = {name = 'novel_hero'},\n}\n"""
        data = "return {\n\tnovel_hero = {\n damage = 100,\n },\n}\n"
        sync = WikiSync(
            self.store,
            self.catalog,
            self.evidence,
            session_factory=self.factory(
                [self.page(NAMES, names), self.page(DATA, data)]
            ),
        )
        self.assertTrue(await sync.refresh())
        self.assertIn("novel_hero", self.catalog.units)
        self.assertIn("novel_hero:data", self.evidence.sources)
        self.assertEqual(self.store.latest()["ranking"], [])

    async def test_active_vote_defers_source_refresh(self):
        self.store.create_proposal(
            [{"unit_id": "daki", "tier": "GOOD_SUPPORT"}],
            {},
            details={},
            source_version="test",
            model="test",
            comments=[],
        )
        factory = self.factory([])
        sync = WikiSync(
            self.store, self.catalog, self.evidence, session_factory=factory
        )
        self.assertFalse(await sync.refresh(["daki"]))
        self.assertEqual(self.requests, [])
