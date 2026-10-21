import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import discord

from PIL import Image
from community_domain import Catalog, consensus, validate_chat, ROOT
from community_store import CommunityStore, COMMUNITY_TABLES
from community_ui import render_grid, tier_payload, relay_embed, safe, unit_embed
from runtime_health import RuntimeHealth
from storage_maintenance import snapshot_database, verify_database

REASON = "Testei essa forma no modo escolhido com a mesma equipe e condições."


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.now = 2000000000
        self.path = Path(self.tmp.name) / "community.sqlite3"
        self.store = CommunityStore(self.path, clock=lambda: self.now)
        for gid in ("1", "2", "3"):
            self.store.configure(gid, "Servidor " + gid, "tier", gid + "00")
            self.store.configure(gid, "Servidor " + gid, "global", gid + "01")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def review(
        self,
        uid,
        gid="1",
        tier="A",
        share=True,
        unit="rukia",
        role="damage",
        mode="general",
    ):
        self.store.submit_review(
            uid, gid, unit, role, mode, tier, REASON, share_global=share
        )

    def relay(self, uid="user", event="event", gid="1"):
        self.store.consent(uid)
        return self.store.enqueue(
            uid,
            gid,
            gid + "01",
            event,
            "Pessoa",
            "Servidor",
            "Olá, comunidade!",
            original_id="777",
        )

    def test_global_requires_explicit_consent(self):
        with self.assertRaises(ValueError):
            self.store.enqueue("u", "1", "101", "e", "U", "S", "Olá")
        self.assertEqual(self.store.jobs(), [])

    def test_draft_is_not_distributed_before_confirmation_and_only_actor_accepts(self):
        draft = self.store.draft("u", "1", "101", "e", "U", "S", "Olá")
        self.assertEqual(self.store.jobs(), [])
        with self.assertRaises(ValueError):
            self.store.accept_draft(draft["id"], "stranger")
        row = self.store.accept_draft(draft["id"], "u")
        self.assertTrue(self.store.consented("u"))
        self.assertEqual(len(self.store.jobs()), 1)
        self.assertEqual(row["body"], "Olá")

    def test_expired_draft_and_reconfigured_source_do_not_forward(self):
        draft = self.store.draft("u", "1", "101", "e", "U", "S", "Olá")
        self.now += 601
        with self.assertRaises(ValueError):
            self.store.accept_draft(draft["id"], "u")
        self.store.configure("1", "Servidor", "global", "999")
        with self.assertRaises(ValueError):
            self.store.accept_draft(draft["id"], "u")

    def test_only_one_active_confirmation_per_person(self):
        self.store.draft("u", "1", "101", "e", "U", "S", "Olá")
        with self.assertRaises(ValueError):
            self.store.draft("u", "2", "201", "e2", "U", "S", "Outra")

    def test_source_delivery_must_succeed_before_fanout_or_delete(self):
        row = self.relay()
        jobs = self.store.jobs()
        self.assertEqual(len(jobs), 1)
        self.assertTrue(jobs[0]["is_source"])
        self.assertEqual(self.store.originals_to_delete(), [])
        self.store.mark_sent(jobs[0]["id"], "receipt")
        self.assertEqual(len(self.store.jobs()), 2)
        self.assertEqual(self.store.originals_to_delete()[0]["id"], row["id"])

    def test_local_failure_preserves_original_and_blocks_other_servers(self):
        self.relay()
        self.store.fail_job(self.store.jobs()[0], permanent=True)
        self.assertEqual(self.store.jobs(), [])
        self.assertEqual(self.store.originals_to_delete(), [])

    def test_outbox_survives_restart_with_stable_identity(self):
        row = self.relay()
        job = self.store.jobs()[0]
        self.store.fail_job(job)
        self.store.close()
        self.now += 100
        self.store = CommunityStore(self.path, clock=lambda: self.now)
        self.assertEqual(self.store.jobs()[0]["relay_id"], row["id"])
        self.assertEqual(self.store.jobs()[0]["attempts"], 1)

    def test_repeated_gateway_event_does_not_create_second_relay(self):
        first = self.relay()
        second = self.relay()
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(
            self.store.connection.execute(
                "SELECT COUNT(*) FROM community_relays"
            ).fetchone()[0],
            1,
        )

    def test_cooldown_blocks_different_event_from_same_author(self):
        self.relay()
        with self.assertRaises(ValueError):
            self.relay(event="another")

    def test_disconnect_source_revokes_delivery(self):
        self.relay()
        job = self.store.jobs()[0]
        self.store.disable("1", "global")
        self.assertFalse(self.store.delivery_valid(job))

    def test_withdrawal_and_block_revokes_unsent_jobs(self):
        self.relay()
        job = self.store.jobs()[0]
        self.store.withdraw("user")
        self.assertFalse(self.store.delivery_valid(job))
        self.store.consent("user")
        self.store.block("user", "Violação das regras")
        self.assertFalse(self.store.delivery_valid(job))
        self.assertFalse(self.store.consented("user"))

    def test_withdraw_then_immediate_rejoin_does_not_revive_old_message(self):
        self.relay()
        self.store.withdraw("user")
        self.store.consent("user")
        self.assertEqual(self.store.jobs(), [])

    def test_disable_then_reenable_does_not_revive_old_outbox(self):
        self.relay()
        self.store.mark_sent(self.store.jobs()[0]["id"], "receipt")
        self.store.disable("1", "global")
        self.store.configure("1", "S", "global", "101")
        self.assertEqual(self.store.jobs(), [])

    def test_late_receipt_after_withdrawal_is_retained_for_removal(self):
        self.relay()
        job = self.store.jobs()[0]
        self.store.withdraw("user")
        self.store.mark_sent(job["id"], "late")
        self.assertEqual(self.store.deletions()[0]["message_id"], "late")
        self.assertEqual(self.store.originals_to_delete(), [])

    def test_unrelated_server_admin_cannot_delete_anothers_message(self):
        row = self.relay()
        with self.assertRaises(ValueError):
            self.store.delete_relay(row["id"], "stranger")
        self.store.delete_relay(row["id"], "user")
        self.assertEqual(self.store.relay(row["id"])["status"], "deleted")

    def test_reports_require_matching_copy_guild_and_message(self):
        row = self.relay()
        job = self.store.jobs()[0]
        self.store.mark_sent(job["id"], "888")
        with self.assertRaises(ValueError):
            self.store.report(row["id"], "u", "2", "888", "Abuso")
        self.store.report(row["id"], "u", "1", "888", "Abuso na conversa")
        self.store.report(row["id"], "u", "1", "888", "Repetida")
        self.assertEqual(len(self.store.reports()), 1)

    def test_private_reviews_do_not_enter_global(self):
        self.review("u", share=False)
        self.assertEqual(
            len(self.store.reviews("rukia", "damage", "general", scope="guild:1")), 1
        )
        self.assertEqual(self.store.reviews("rukia", "damage", "general"), [])

    def test_global_one_vote_per_person_across_servers(self):
        self.review("u")
        self.now += 601
        self.review("u", "2", tier="B")
        rows = self.store.reviews("rukia", "damage", "general")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["guild_id"], "2")

    def test_review_update_has_cooldown_and_replaces_previous(self):
        self.review("u")
        with self.assertRaises(ValueError):
            self.review("u", tier="S")
        self.now += 601
        self.review("u", tier="S")
        self.assertEqual(len(self.store.reviews("rukia", "damage", "general")), 1)
        self.assertEqual(
            self.store.reviews("rukia", "damage", "general")[0]["score"], 4
        )

    def test_modes_roles_forms_and_periods_are_isolated(self):
        self.review("u")
        self.now += 61
        self.review("v", mode="raid", unit="rukia_2")
        self.assertEqual(self.store.reviews("rukia", "support", "general"), [])
        self.assertEqual(self.store.reviews("rukia", "damage", "raid"), [])
        old = self.store.get("period")
        self.store.set_period("Novo balanceamento")
        self.assertEqual(self.store.reviews("rukia", "damage", "general"), [])
        self.assertEqual(
            len(self.store.reviews("rukia", "damage", "general", period=old)), 1
        )

    def test_local_and_global_thresholds_are_different(self):
        for i in range(5):
            self.review("a" + str(i))
        self.store.refresh_tiers()
        self.assertEqual(
            self.store.tier_rows("damage", "general", scope="guild:1")[0]["tier"], "A"
        )
        self.assertIsNone(self.store.tier_rows("damage", "general")[0]["tier"])
        for gid in ("2", "3"):
            for i in range(3):
                self.review(gid + str(i), gid)
        self.store.refresh_tiers()
        self.assertEqual(self.store.tier_rows("damage", "general")[0]["tier"], "A")

    def test_changes_require_stability_and_cooldown(self):
        for gid in ("1", "2", "3"):
            for i in range(3):
                self.review(gid + str(i), gid)
        self.store.refresh_tiers()
        self.now += 601
        for gid in ("1", "2", "3"):
            for i in range(3):
                self.review(gid + str(i), gid, tier="S")
        self.store.refresh_tiers()
        self.assertEqual(self.store.tier_rows("damage", "general")[0]["tier"], "A")
        self.now += 901
        self.store.refresh_tiers()
        self.assertEqual(self.store.tier_rows("damage", "general")[0]["tier"], "A")
        self.now += 2100
        self.store.refresh_tiers()
        self.assertEqual(self.store.tier_rows("damage", "general")[0]["tier"], "S")

    def test_expired_reviews_withdraw_classification(self):
        for i in range(5):
            self.review(str(i))
        self.store.refresh_tiers()
        self.now += 31 * 86400
        self.store.refresh_tiers()
        self.assertIsNone(
            self.store.tier_rows("damage", "general", scope="guild:1")[0]["tier"]
        )

    def test_editorial_is_labeled_and_does_not_invent_consensus(self):
        self.store.editorial("global", "rukia", "support", "raid", "S", REASON)
        self.store.refresh_tiers()
        row = self.store.tier_rows("support", "raid")[0]
        self.assertEqual((row["basis"], row["tier"]), ("editorial", "S"))
        self.assertEqual(row["metrics"]["players"], 0)

    def test_mentions_never_create_ranks_or_store_conversation(self):
        for _ in range(100):
            self.store.record_mentions("u", "1", {"rukia"})
        self.assertEqual(self.store.mentions("rukia"), 1)
        self.store.refresh_tiers()
        self.assertEqual(self.store.tier_rows("damage", "general"), [])
        row = self.store._one("SELECT * FROM community_mentions")
        self.assertNotIn("body", row)
        self.assertNotEqual(row["actor_hash"], "u")

    def test_cleanup_redacts_delivered_body_but_keeps_history_mapping(self):
        row = self.relay()
        for _ in range(2):
            for job in self.store.jobs():
                self.store.mark_sent(job["id"], "m" + str(job["id"]))
        self.now += 8 * 86400
        self.store.cleanup()
        self.assertEqual(self.store.relay(row["id"])["body"], "")
        self.assertEqual(
            self.store.connection.execute(
                "SELECT COUNT(*) FROM community_deliveries"
            ).fetchone()[0],
            3,
        )

    def test_stale_queued_message_expires_instead_of_arriving_days_later(self):
        self.relay()
        self.now += 2 * 86400
        self.store.cleanup()
        self.assertEqual(self.store.jobs(), [])
        self.assertEqual(self.store.originals_to_delete(), [])

    def test_reviews_can_be_erased(self):
        self.review("u")
        self.store.erase_reviews("u")
        self.assertEqual(self.store.reviews("rukia", "damage", "general"), [])

    def test_backup_schema_and_row_factory_readiness(self):
        backup = Path(self.tmp.name) / "backup.sqlite3"
        snapshot_database(self.path, backup, required_tables=COMMUNITY_TABLES)
        verify_database(backup, required_tables=COMMUNITY_TABLES)
        health = RuntimeHealth(lambda: True, lambda: self.store.connection)
        self.assertTrue(health.database_ready())

    def test_disabled_or_unconfigured_server_cannot_submit(self):
        with self.assertRaises(ValueError):
            self.review("u", "9")

    def test_conditions_and_evidence_limits(self):
        with self.assertRaises(ValueError):
            self.store.submit_review(
                "u",
                "1",
                "rukia",
                "damage",
                "general",
                "A",
                REASON,
                evidence="file:///etc/passwd",
            )
        with self.assertRaises(ValueError):
            self.store.submit_review(
                "u", "1", "rukia", "damage", "general", "A", "curto"
            )

    def test_capacity_stops_new_collection_without_erasing_existing_data(self):
        self.review("u")
        with patch("community_store.MAX_DATABASE_BYTES", 1):
            with self.assertRaises(ValueError):
                self.review("v")
        self.assertEqual(len(self.store.reviews("rukia", "damage", "general")), 1)

    def test_review_display_stays_inside_discord_limits_after_escaping(self):
        self.store.submit_review(
            "u",
            "1",
            "rukia",
            "damage",
            "general",
            "A",
            "*" * 700,
            conditions="*" * 300,
            evidence="https://example.org/" + "x" * 350,
        )
        embed = unit_embed(
            self.store,
            Catalog(),
            Catalog().resolve("rukia"),
            "damage",
            "general",
            "global",
        )
        for field in embed.fields:
            self.assertLessEqual(len(field.value.encode("utf-16-le")) // 2, 1024)


class DomainCase(unittest.TestCase):
    def test_large_server_cannot_outweigh_two_independent_servers(self):
        rows = [{"guild_id": "big", "score": 4} for _ in range(1000)]
        rows += [{"guild_id": g, "score": 1} for g in ("b", "c") for _ in range(3)]
        self.assertEqual(consensus(rows)["tier"], "C")

    def test_insufficient_and_divided_evidence_stays_unclassified(self):
        self.assertIsNone(consensus([{"guild_id": "x", "score": 4}] * 100)["tier"])
        self.assertIsNone(
            consensus(
                [
                    {"guild_id": g, "score": s}
                    for g, s in [("a", 0), ("b", 2), ("c", 4)]
                    for _ in range(3)
                ]
            )["tier"]
        )

    def test_within_tier_rating_uses_equal_server_weight(self):
        a = [{"guild_id": g, "score": 3} for g in ("a", "b", "c") for _ in range(3)]
        b = a + [{"guild_id": "a", "score": 4}] * 4
        self.assertEqual(consensus(a)["tier"], consensus(b)["tier"])
        self.assertGreater(consensus(b)["rating"], consensus(a)["rating"])

    def test_chat_bounds_and_invites(self):
        for value in ("x" * 1001, "https://discord.gg/abc"):
            with self.assertRaises(ValueError):
                validate_chat(value)
        self.assertEqual(validate_chat("olá\u202e"), "olá")

    def test_catalog_exact_forms_and_ambiguous_alias(self):
        catalog = Catalog()
        self.assertGreater(len(catalog.units), 500)
        self.assertNotEqual(catalog.resolve("rukia").id, catalog.resolve("rukia_2").id)
        self.assertTrue(any(u.id == "rukia_2" for u in catalog.search("Snow Reaper")))
        with self.assertRaises(ValueError):
            catalog.resolve("not a unit")

    def test_portraits_are_original_local_assets_without_known_placeholders(self):
        manifest = json.loads((ROOT / "data/community_portraits.json").read_text())
        self.assertGreater(len(manifest["assets"]), 400)
        for uid, item in manifest["assets"].items():
            self.assertTrue((ROOT / item["path"]).is_file())
            self.assertTrue(
                item["source_url"].startswith(
                    "https://static.wikia.nocookie.net/animeadventures/"
                )
            )
            rejected = manifest.get("rejected_placeholders", {}).get(uid)
            if rejected:
                self.assertNotEqual(item["source_url"], rejected["source_url"])

    def test_render_has_bounded_size_and_correct_alt(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = CommunityStore(Path(tmp) / "db.sqlite3")
            cat = Catalog()
            embed, file, _ = tier_payload(store, cat, "damage", "general", "global")
            self.assertEqual(file.description, ".")
            with Image.open(file.fp) as im:
                self.assertLess(im.width, 1400)
                self.assertLess(im.height, 2000)
            self.assertLess(len(str(embed.to_dict())), 6000)
            file.close()
            store.close()

    def test_render_does_not_make_a_character_for_missing_art(self):
        blob, page, pages = render_grid(
            [{"unit_id": "absent", "tier": "C"}],
            title="Teste",
            subtitle="Teste",
            media={},
        )
        self.assertEqual((page, pages), (1, 1))
        self.assertTrue(blob.startswith(b"\x89PNG"))

    def test_relay_text_cannot_ping_or_inject_markdown(self):
        embed = relay_embed(
            {
                "body": "@everyone **admin** <@1234>",
                "author_name": "Pessoa",
                "guild_name": "Servidor",
                "id": "abc",
            }
        )
        self.assertIn("\\*\\*admin", embed.description)
        self.assertNotIn("@everyone", embed.description)

    def test_astral_unicode_and_markdown_escape_respect_native_length(self):
        for text in ("*" * 1000, "\U0001f600" * 1000):
            self.assertLessEqual(len(safe(text).encode("utf-16-le")) // 2, 1000)


class RuntimeCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from community_bot import CommunityBot

        self.tmp = tempfile.TemporaryDirectory()
        self.app = CommunityBot(self.tmp.name)
        self.app.store.configure("1", "S1", "global", "101")
        self.app.store.configure("2", "S2", "global", "201")
        self.app.store.consent("7")
        self.channel = SimpleNamespace(
            id=101, get_partial_message=lambda mid: SimpleNamespace(delete=self.delete)
        )
        self.delete = AsyncMock()
        self.send = AsyncMock(return_value={"id": "999"})
        self.app.http.send_message = self.send

    async def asyncTearDown(self):
        await self.app.close()
        self.tmp.cleanup()

    def enqueue(self):
        return self.app.store.enqueue(
            "7",
            "1",
            "101",
            "e",
            "Pessoa",
            "Servidor",
            "Olá @everyone",
            original_id="777",
        )

    async def test_runtime_registers_community_and_archives_quiz(self):
        names = {c.name for c in self.app.tree.get_commands()}
        self.assertIn("tierlist", names)
        self.assertIn("avaliar", names)
        self.assertIn("global", names)
        self.assertNotIn("adventures", names)

    async def test_delivery_sets_nonce_and_disables_mentions_then_deletes_original(
        self,
    ):
        self.enqueue()
        job = self.app.store.jobs()[0]
        with patch.object(self.app, "get_channel", return_value=self.channel):
            await self.app.remove_originals()
            self.delete.assert_not_awaited()
            await self.app.deliver(job)
            payload = self.send.call_args.kwargs["params"].payload
            self.assertTrue(payload["enforce_nonce"])
            self.assertEqual(payload["allowed_mentions"]["parse"], [])
            self.assertTrue(payload["nonce"].isdigit())
            await self.app.remove_originals()
            self.delete.assert_awaited_once()

    async def test_ack_failure_does_not_delete_original_or_release_fanout(self):
        self.enqueue()
        self.send.side_effect = OSError("network")
        with patch.object(self.app, "get_channel", return_value=self.channel):
            await self.app.deliver(self.app.store.jobs()[0])
            await self.app.remove_originals()
        self.delete.assert_not_awaited()
        self.assertEqual(self.app.store.jobs(), [])
        self.assertEqual(
            self.app.store.connection.execute(
                "SELECT COUNT(*) FROM community_deliveries WHERE is_source=0 AND state='sent'"
            ).fetchone()[0],
            0,
        )

    async def test_paused_network_preserves_queue_without_sending(self):
        self.enqueue()
        self.app.store.set("global_paused", "1")
        with patch.object(self.app, "get_channel", return_value=self.channel):
            await self.app.deliver(self.app.store.jobs()[0])
        self.send.assert_not_awaited()
        self.assertEqual(len(self.app.store.jobs()), 1)

    async def test_server_administrator_is_not_network_moderator(self):
        i = SimpleNamespace(
            user=SimpleNamespace(id=999),
            guild_id=1,
            permissions=SimpleNamespace(manage_guild=True),
        )
        self.app.require_admin(i)
        with self.assertRaises(ValueError):
            self.app.require_mod(i)

    async def test_consent_withdrawn_during_send_schedules_copy_for_removal(self):
        self.enqueue()

        async def ack(*args, **kwargs):
            self.app.store.withdraw("7")
            return {"id": "late-receipt"}

        self.send.side_effect = ack
        with patch.object(self.app, "get_channel", return_value=self.channel):
            await self.app.deliver(self.app.store.jobs()[0])
            await self.app.remove_originals()
        self.delete.assert_not_awaited()
        self.assertEqual(self.app.store.deletions()[0]["message_id"], "late-receipt")

    async def test_bot_messages_cannot_form_a_relay_loop(self):
        message = SimpleNamespace(
            author=SimpleNamespace(bot=True),
            webhook_id=None,
            guild=SimpleNamespace(id=1),
            channel=SimpleNamespace(id=101),
            content="ignored",
        )
        await self.app.on_message(message)
        self.assertEqual(self.app.store.jobs(), [])

    async def test_first_message_has_exact_preview_and_no_remote_delivery(self):
        user = SimpleNamespace(
            id=8,
            bot=False,
            display_name="Pessoa",
            created_at=discord.utils.utcnow()
            - __import__("datetime").timedelta(days=100),
        )
        message = SimpleNamespace(
            id=555,
            author=user,
            webhook_id=None,
            guild=SimpleNamespace(id=1, name="S1"),
            channel=SimpleNamespace(id=101),
            content="Meu relato",
            attachments=[],
            stickers=[],
            reply=AsyncMock(),
        )
        await self.app.on_message(message)
        self.assertEqual(
            message.reply.call_args.kwargs["embed"].description, "Meu relato"
        )
        self.assertEqual(self.app.store.jobs(), [])

    async def test_panel_reuses_message_and_does_not_edit_unchanged_image(self):
        self.app.store.configure("1", "S1", "tier", "102")
        self.app.store.set("panel_minutes:1", 60)
        partial = SimpleNamespace(edit=AsyncMock())
        channel = SimpleNamespace(
            send=AsyncMock(return_value=SimpleNamespace(id=555)),
            get_partial_message=lambda mid: partial,
        )
        with (
            patch.object(self.app, "get_channel", return_value=channel),
            patch("community_bot.time.time", return_value=2000000000),
        ):
            await self.app.panel_loop.coro(self.app)
            await self.app.panel_loop.coro(self.app)
        channel.send.assert_awaited_once()
        with (
            patch.object(self.app, "get_channel", return_value=channel),
            patch("community_bot.time.time", return_value=2000003601),
        ):
            await self.app.panel_loop.coro(self.app)
        channel.send.assert_awaited_once()
        partial.edit.assert_not_awaited()
