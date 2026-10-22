from tier_ui import visible_text

"""Release workflows: retired identities, live contribution files and durable repairs."""

import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord

from PIL import Image

import test_tier_thread as fixtures
from community_domain import Catalog, ROOT
from tier_analysis import EvidenceLibrary, TierAnalyzer
from tier_backup import make_snapshot, restore_snapshot
from tier_catalog import TierCatalog
from tier_domain import relevant_units
from tier_image import PanelRenderer, poll_embed
from tier_media import MediaLibrary
from tier_portraits import PortraitInventory
from tier_preview import check_portrait_sequence
from tier_store import TierStore
from tier_views import ImageModal, PLAYER_GUIDE
from tier_wiki import WikiSync

NOTE = "Retrato artificial exclusivo do teste, sem imagem ou avaliação de jogo real."


def row(uid, tier="DAMAGE"):
    return (
        {"unit_id": uid, "tier": tier, "role": "DAMAGE"}
        if tier == "META"
        else {"unit_id": uid, "tier": tier}
    )


class ActiveCatalogCase(unittest.TestCase):
    def test_retirements_are_explicit_and_keep_original_catalogue_for_history(self):
        archived, active = Catalog(), TierCatalog()
        manifest = json.loads((ROOT / "data/community_portraits.json").read_text())
        self.assertEqual(len(archived.units), 549)
        self.assertEqual(len(active.units), 524)
        self.assertEqual(set(active.retired), set(manifest["rejected_placeholders"]))
        self.assertEqual(len(set(manifest["missing"]) - set(active.retired)), 71)
        self.assertIn("uraraka", archived.units)
        self.assertNotIn("uraraka", active.units)
        self.assertEqual(active.display_name("uraraka"), "Gravity Hero")
        for uid in active.retired:
            with self.subTest(uid=uid), self.assertRaises(ValueError):
                active.resolve(uid)

    def test_wiki_refresh_cannot_restore_excluded_id_or_inject_its_alias(self):
        catalog = TierCatalog()
        catalog.merge_units(
            [
                {"id": "bakugou", "name": "Daki", "aliases": ["Nova forma falsa"]},
                {"id": "nova_unidade", "name": "Nova unidade de teste", "aliases": []},
            ]
        )
        self.assertNotIn("bakugou", catalog.units)
        self.assertEqual(catalog.resolve("Daki").id, "daki")
        self.assertEqual(catalog.mentions("Nova forma falsa"), set())
        self.assertIn("nova_unidade", catalog.units)
        self.assertEqual(
            relevant_units(
                catalog, "Explosion Hero é melhor no infinito pelo dano e alcance."
            ),
            set(),
        )

    def test_new_wiki_cache_is_filtered_before_becoming_runtime_catalogue(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            text = "Texto artificial da wiki exclusivamente para este teste de filtro."
            source = {
                "unit_id": "bakugou",
                "url": "https://animeadventures.fandom.com/wiki/Explosion_Hero?oldid=1",
                "revision": 1,
                "text": text,
                "sha256": hashlib.sha256(text.encode()).hexdigest(),
            }
            (root / "wiki-cache.json").write_text(
                json.dumps(
                    {
                        "units": [
                            {"id": "bakugou", "name": "Explosion Hero", "aliases": []}
                        ],
                        "sources": {"bakugou:article": source},
                    }
                )
            )
            (root / "evidence.json").write_text(
                json.dumps({"version": "test", "sources": {}})
            )
            store = TierStore(root / "tierlist.sqlite3")
            try:
                catalog = TierCatalog()
                evidence = EvidenceLibrary(root / "evidence.json")
                WikiSync(store, catalog, evidence)
                self.assertNotIn("bakugou", catalog.units)
                self.assertEqual(evidence.sources, {})
            finally:
                store.close()


class CatalogMigrationCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.now = 2_000_000_000
        self.store = TierStore(self.root / "tierlist.sqlite3", clock=lambda: self.now)
        self.media = MediaLibrary(self.store, Catalog())

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def publish(self, ranking):
        self.store.publish(
            ranking, {}, source_version="test", model="fixture", comments=[]
        )

    def test_migration_preserves_old_snapshot_votes_order_and_cancels_incompatible_poll(
        self,
    ):
        self.publish([row("uraraka"), row("daki"), row("gyutaro")])
        original = self.store.latest()["id"]
        self.store.create_proposal(
            [row("uraraka"), row("gyutaro"), row("daki")],
            {},
            details={},
            source_version="test",
            model="fixture",
            comments=[],
        )
        proposal = self.store.active_proposal()
        self.store.remember_poll(proposal["id"], 1, 10, 100)
        self.store.vote(proposal["id"], 7, 1, 10, 100, "approve")
        self.store.bind_catalog(TierCatalog())
        self.assertEqual(self.store.latest()["ranking"], [row("daki"), row("gyutaro")])
        self.assertIn(
            "uraraka",
            self.store.rows(
                "SELECT ranking FROM tier_publications WHERE id=?", (original,)
            )[0]["ranking"],
        )
        self.assertEqual(self.store.proposal(proposal["id"])["status"], "outdated")
        self.assertEqual(self.store.poll_counts(proposal["id"])["approve"], 1)
        self.assertEqual(
            self.store.rows("SELECT kind FROM tier_audit"),
            [{"kind": "catalog-retired"}],
        )
        publication = self.store.latest()["id"]
        self.store.bind_catalog(TierCatalog())
        self.assertEqual(self.store.latest()["id"], publication)
        # Old proposal results still render, even with a retired comparison.
        proposal = self.store.proposal(proposal["id"])
        proposal["details"] = {
            "uraraka": {"reason": NOTE, "tier": "DAMAGE", "before": None, "sources": []}
        }
        self.assertIn(
            "Gravity Hero", poll_embed(self.store, TierCatalog(), proposal).title
        )

    def test_initial_migration_does_not_create_fake_classification(self):
        self.store.bind_catalog(TierCatalog())
        self.assertEqual(self.store.latest()["id"], 0)
        self.assertEqual(self.store.get("last_analysis"), "0")
        self.assertEqual(self.store.rows("SELECT * FROM tier_audit"), [])

    def test_pending_and_approved_retired_portraits_are_preserved_only_as_history(self):
        approved = self.media.submit("uraraka", 7, 1, "", NOTE, fixtures.png())
        self.media.decide(approved, 7, approve=True)
        pending = self.media.submit("bakugou", 8, 1, "", NOTE, fixtures.png("green"))
        self.store.bind_catalog(TierCatalog())
        active_media = MediaLibrary(self.store, TierCatalog())
        self.assertEqual(active_media.approved(), {})
        self.assertEqual(active_media.pending(), [])
        self.assertEqual(active_media.suggestion(pending)["status"], "unavailable")
        self.assertEqual(active_media.suggestion(approved)["status"], "approved")
        self.assertTrue(
            active_media.path(
                active_media.suggestion(approved)["preview_hash"]
            ).is_file()
        )

    def test_new_proposals_ingestion_and_rollback_cannot_restore_retired_forms(self):
        self.publish([row("uraraka"), row("daki")])
        self.store.bind_catalog(TierCatalog())
        self.publish([row("daki", "SUPPORT")])
        self.store.rollback(
            self.store.latest()["id"],
            7,
            "Correção artificial de teste para conferir o retorno seguro.",
        )
        self.assertEqual(self.store.latest()["ranking"], [row("daki")])
        self.store.register_guild(1)
        self.assertFalse(self.store.ingest(1, 7, 1, 10, NOTE, {"bakugou"}))
        for action in (
            lambda: self.publish([row("uraraka")]),
            lambda: self.store.create_proposal(
                [row("bakugou")],
                {},
                details={},
                source_version="test",
                model="test",
                comments=[],
            ),
            lambda: self.store.create_proposal(
                [row("daki")],
                {},
                details={"daki": {"before": "bakugou"}},
                source_version="test",
                model="test",
                comments=[],
            ),
        ):
            with self.assertRaisesRegex(ValueError, "catálogo ativo"):
                action()

    def test_backup_restore_reapplies_policy_without_losing_other_data(self):
        self.publish([row("uraraka"), row("daki")])
        snapshot, _ = make_snapshot(self.store.path, now=self.now)
        destination = self.root / "restored"
        restore_snapshot(snapshot, destination)
        restored = TierStore(destination / "tierlist.sqlite3")
        try:
            restored.bind_catalog(TierCatalog())
            self.assertEqual(restored.latest()["ranking"], [row("daki")])
            self.assertEqual(len(restored.rows("SELECT * FROM tier_publications")), 2)
        finally:
            restored.close()

    def test_processed_comments_about_retired_forms_do_not_return_as_context(self):
        self.store.register_guild(1)
        for index, units in enumerate(({"bakugou"}, {"bakugou", "daki"})):
            self.store.ingest(index, index, 1, 10, NOTE + str(index), units)
        self.store.bind_catalog(TierCatalog())
        self.assertTrue(
            all(set(json.loads(c["units"])) <= {"daki"} for c in self.store.recent())
        )
        self.assertTrue(all(json.loads(c["units"]) for c in self.store.recent()))

    def test_malformed_wiki_cache_falls_back_without_preventing_startup(self):
        (self.root / "evidence.json").write_text(
            json.dumps({"version": "fallback", "sources": {}})
        )
        for malformed in ([], {"sources": []}, {"sources": {}, "checked": []}):
            with self.subTest(cache=malformed):
                (self.root / "wiki-cache.json").write_text(json.dumps(malformed))
                wiki = WikiSync(
                    self.store,
                    TierCatalog(),
                    EvidenceLibrary(self.root / "evidence.json"),
                )
                self.assertEqual(wiki.status, "unavailable")
                self.assertEqual(wiki.evidence.version, "fallback")

    def test_invalid_or_future_wiki_timestamps_cannot_freeze_refreshes(self):
        (self.root / "evidence.json").write_text(
            json.dumps({"version": "fallback", "sources": {}})
        )
        (self.root / "wiki-cache.json").write_text(
            json.dumps(
                {
                    "sources": {},
                    "checked": {
                        "Module:UnitData/Data/Names": self.now + 86400,
                        "Daki": "invalid",
                        "Gyutaro": self.now - 60,
                        "Other": float("nan"),
                        "Boolean": True,
                    },
                }
            )
        )
        wiki = WikiSync(
            self.store, TierCatalog(), EvidenceLibrary(self.root / "evidence.json")
        )
        self.assertEqual(wiki.checked, {"Gyutaro": self.now - 60})


class PortraitIntegrityCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = TierStore(self.root / "tierlist.sqlite3")
        self.catalog = TierCatalog()
        self.media = MediaLibrary(self.store, self.catalog)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def submit(self, color="red", unit="pain", user=7):
        return self.media.submit(unit, user, 1, "", NOTE, fixtures.png(color))

    def test_corrupt_override_reappears_in_needs_and_invalidates_render_cache(self):
        inventory = PortraitInventory(self.catalog, self.media)
        renderer = PanelRenderer(self.media.root)
        initial = inventory.get()
        self.assertEqual(initial.count, 71)
        suggestion = self.submit()
        self.media.decide(suggestion, 7, approve=True)
        self.assertEqual(inventory.get().count, 70)
        publication = {"id": 1, "ranking": [row("pain")], "created_at": 0}
        revision = int(self.store.get("media_revision"))
        approved, first = renderer.get(
            publication, self.media.approved(), revision, len(self.catalog.units)
        )
        self.media.path(self.media.suggestion(suggestion)["preview_hash"]).write_bytes(
            b"corrupted"
        )
        self.assertEqual(self.media.approved(), {})
        self.assertEqual(inventory.get().count, 71)
        fallback, second = renderer.get(
            publication, self.media.approved(), revision, len(self.catalog.units)
        )
        self.assertNotEqual(first, second)
        with Image.open(io.BytesIO(fallback)) as image:
            self.assertEqual(image.format, "PNG")
        self.assertNotEqual(approved, fallback)

    def test_corrupt_previous_portrait_does_not_replace_valid_current_one(self):
        first = self.submit()
        self.media.decide(first, 7, approve=True)
        second = self.submit("green", user=8)
        self.media.decide(second, 7, approve=True)
        self.media.path(self.media.suggestion(first)["preview_hash"]).write_bytes(
            b"bad"
        )
        with self.assertRaisesRegex(ValueError, "preservada"):
            self.media.undo("pain", second, 7)
        self.assertEqual(self.media.approved()["pain"]["suggestion_id"], second)
        self.assertEqual(self.media.suggestion(second)["status"], "approved")

    def test_unknown_model_packet_does_not_spend_a_request_for_retired_comments(self):
        self.store.register_guild(1)
        self.store.ingest(1, 7, 1, 10, NOTE, {"bakugou"})
        backend = SimpleNamespace(enabled=True, model="test", analyze=AsyncMock())
        analyzer = TierAnalyzer(self.store, self.catalog, backend=backend)
        self.assertEqual(analyzer.packet(), (None, []))
        backend.analyze.assert_not_awaited()

    def test_model_response_cannot_use_retired_id_from_an_old_packet(self):
        analyzer = TierAnalyzer(
            self.store, self.catalog, backend=SimpleNamespace(enabled=False)
        )
        change = {
            "unit_id": "bakugou",
            "tier": "DAMAGE",
            "role": "DAMAGE",
            "before": None,
            "confidence": 0.99,
            "supporting_comments": [],
            "reason": NOTE,
            "conditions": NOTE,
            "caveat": NOTE,
            "evidence": [],
        }
        with self.assertRaisesRegex(ValueError, "Unidade ou tier inválido"):
            analyzer.validate(
                {"changes": [change]}, {"units": {"bakugou": "Explosion Hero"}}, []
            )

    def test_renderer_recovers_a_repaired_file_without_restarting_or_changing_ranking(
        self,
    ):
        path = self.media.root / "fixture.png"
        original = fixtures.png()
        path.write_bytes(original)
        renderer = PanelRenderer(self.media.root)
        publication = {"id": 1, "ranking": [row("pain")], "created_at": 0}
        overrides = {"pain": {"absolute_path": str(path)}}
        _, valid = renderer.get(publication, overrides, 0, 524)
        path.write_bytes(b"corrupt")
        _, missing = renderer.get(publication, overrides, 0, 524)
        path.write_bytes(original)
        _, restored = renderer.get(publication, overrides, 0, 524)
        self.assertNotEqual(valid, missing)
        self.assertEqual(valid, restored)

    def test_unreadable_bundled_portrait_stays_on_contribution_list(self):
        assets = self.root / "assets"
        assets.mkdir()
        path = assets / "fixture.png"
        path.write_bytes(b"not a png")
        catalog = SimpleNamespace(units={"pain": self.catalog.units["pain"]})
        with patch("tier_portraits.ROOT", self.root):
            inventory = PortraitInventory(
                catalog, self.media, bundled={"pain": {"path": "assets/fixture.png"}}
            )
            self.assertEqual(inventory.get().count, 1)
            path.write_bytes(fixtures.png())
            inventory._key = None
            self.assertEqual(inventory.get().count, 0)


class ReleaseRuntimeCase(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.ThreadRuntimeCase.asyncSetUp
    asyncTearDown = fixtures.ThreadRuntimeCase.asyncTearDown
    interaction = fixtures.ThreadRuntimeCase.interaction
    setup_panel = fixtures.ThreadRuntimeCase.setup_panel

    def index(self):
        return self.env.partial(
            self.env.thread, int(self.app.store.thread(1)["intro_id"])
        )

    def suggest(self, unit="pain", color="red", user=7):
        return self.app.media.submit(unit, user, 1, "", NOTE, fixtures.png(color))

    async def test_approve_reject_and_restore_refresh_one_file_without_ranking_export(
        self,
    ):
        await self.setup_panel()
        index = self.index()
        original_id = index.id
        initial = await index.attachments[0].read()
        self.assertIn(b"71 formas", initial)
        self.assertNotIn(b"Gravity Hero", initial)
        self.assertNotIn(b"META", initial)
        self.assertNotIn(b"user_id", initial)
        pending = self.suggest()
        await self.app.panel_loop.coro(self.app)
        self.assertEqual(await self.index().attachments[0].read(), initial)
        self.app.media.decide(pending, 7, approve=True)
        await self.app.panel_loop.coro(self.app)
        self.assertIn(b"70 formas", await self.index().attachments[0].read())
        rejected = self.suggest("amon", "green", user=8)
        self.app.media.decide(rejected, 7, approve=False)
        await self.app.panel_loop.coro(self.app)
        self.assertIn(b"70 formas", await self.index().attachments[0].read())
        self.app.media.undo("pain", pending, 7)
        await self.app.panel_loop.coro(self.app)
        self.assertEqual(await self.index().attachments[0].read(), initial)
        self.assertEqual(self.index().id, original_id)
        self.assertEqual(len([p for cid, p in self.env.payloads if cid == 10]), 1)
        self.assertEqual(self.app.store.latest()["id"], 0)

    async def test_approving_last_missing_portrait_removes_attachment_and_returns_on_restore(
        self,
    ):
        self.app.catalog.units = {"pain": self.app.catalog.units["pain"]}
        self.app.catalog.extra_aliases = {}
        self.app.catalog._index()
        await self.setup_panel()
        self.assertIn(b"1 forma aguarda", await self.index().attachments[0].read())
        suggestion = self.suggest()
        self.app.media.decide(suggestion, 7, approve=True)
        await self.app.panel_loop.coro(self.app)
        self.assertEqual(self.index().attachments, [])
        self.assertNotIn("aguardam retrato", visible_text(self.index()))
        self.app.media.undo("pain", suggestion, 7)
        await self.app.panel_loop.coro(self.app)
        self.assertEqual(
            [a.filename for a in self.index().attachments], ["retratos-pendentes.txt"]
        )

    async def test_deleted_index_repairs_itself_without_replacing_main_image(self):
        await self.setup_panel()
        old = self.index()
        main = dict(self.app.store.panels()[0])
        await old.delete()
        await self.app.on_raw_message_delete(SimpleNamespace(message_id=old.id))
        await self.app.panel_loop.coro(self.app)
        self.assertNotEqual(old.id, self.index().id)
        self.assertEqual(self.app.store.panels()[0]["message_id"], main["message_id"])
        self.assertEqual(
            [a.filename for a in self.index().attachments], ["retratos-pendentes.txt"]
        )
        self.assertEqual(self.app.store.thread(1)["status"], "ok")

    async def test_repair_lost_acknowledgement_reuses_sent_index_and_current_contribution_list(
        self,
    ):
        await self.setup_panel()
        old = self.index()
        await old.delete()
        await self.app.on_raw_message_delete(SimpleNamespace(message_id=old.id))
        self.env.fail_after_send = True
        await self.app.panel_loop.coro(self.app)
        count_after_loss = len(
            [
                p
                for _, p in self.env.payloads
                if visible_text(p).startswith("## Votações e histórico")
            ]
        )
        self.assertIsNone(self.app.store.thread(1)["intro_id"])
        suggestion = self.suggest()
        self.app.media.decide(suggestion, 7, approve=True)
        await self.app.panel_loop.coro(self.app)
        self.assertEqual(
            len(
                [
                    p
                    for _, p in self.env.payloads
                    if visible_text(p).startswith("## Votações e histórico")
                ]
            ),
            count_after_loss,
        )
        self.assertIn(b"70 formas", await self.index().attachments[0].read())
        self.assertEqual(self.app.store.thread(1)["status"], "ok")

    async def test_offline_deleted_index_is_detected_on_first_check_after_restart(self):
        await self.setup_panel()
        previous = self.index()
        await previous.delete()
        # These volatile checks start empty in a fresh bot process.
        self.app.index_checks.clear()
        await self.app.panel_loop.coro(self.app)
        self.assertNotEqual(self.index().id, previous.id)
        self.assertTrue(self.index().exists)

    async def test_repeated_background_checks_do_not_reupload_unchanged_list(self):
        await self.setup_panel()
        index = self.index()
        index.edit.reset_mock()
        for _ in range(20):
            await self.app.panel_loop.coro(self.app)
        index.edit.assert_not_awaited()
        self.now += 900
        await self.app.panel_loop.coro(self.app)
        index.edit.assert_awaited_once()

    async def test_daily_upload_limit_rejects_before_download_or_image_processing(self):
        await self.setup_panel()
        for color in ("red", "green", "blue"):
            self.suggest("daki", color)
        i = self.interaction(channel=self.env.thread)
        modal = ImageModal(self.app, i)
        modal.unit._value = "Daki"
        modal.note._value = NOTE
        modal.portrait._values = [SimpleNamespace()]
        self.app.read_upload = AsyncMock(return_value=fixtures.png())
        with patch("tier_media.prepare") as process:
            with self.assertRaisesRegex(ValueError, "três sugestões"):
                await modal.on_submit(i)
            process.assert_not_called()
        self.app.read_upload.assert_not_awaited()

    async def test_public_text_remains_within_discord_limits_with_all_links(self):
        await self.setup_panel()
        panel = self.app.store.panels()[0]
        self.app.store.set("previous-thread:1", "9999999999999999999")
        self.app.health.storage_level = "critical"
        await self.app.sync_index(panel, self.env.thread, force=True)
        self.assertLessEqual(
            len(visible_text(self.index()).encode("utf-16-le")) // 2, 2000
        )
        self.assertLessEqual(len(PLAYER_GUIDE.encode("utf-16-le")) // 2, 2000)
        self.assertIn("retratos-pendentes.txt", visible_text(self.index()))

    async def test_repeatable_verifier_checks_five_real_attachment_transitions_in_isolation(
        self,
    ):
        await self.setup_panel()
        message = await self.env.thread.send("Ensaio isolado de retratos.")
        before = self.app.store.latest()
        steps = await check_portrait_sequence(self.app, message)
        self.assertEqual([s["pending"] for s in steps], [1, 1, 0, 1, 1])
        self.assertEqual(steps[0]["sha256"], steps[-1]["sha256"])
        self.assertEqual(self.app.store.latest(), before)
        self.assertEqual(self.app.media.approved(), {})
        self.assertEqual(len(self.app.media.pending()), 0)

    async def test_verifier_rejects_discord_returning_wrong_text_file(self):
        await self.setup_panel()
        message = await self.env.thread.send("Ensaio isolado de retratos.")
        fetch = self.env.thread.fetch_message

        async def corrupted(ident):
            actual = await self.env.thread_fetch_message(ident)
            if actual.attachments:
                actual.attachments[0].read = AsyncMock(return_value=b"wrong")
            return actual

        fetch.side_effect = corrupted
        with self.assertRaisesRegex(ValueError, "difere da lista enviada"):
            await check_portrait_sequence(self.app, message)
        self.assertEqual(self.app.store.latest()["id"], 0)

    async def test_discord_cached_deleted_nonce_retries_once_without_losing_image_bytes(
        self,
    ):
        attempts = []

        async def send(channel_id, *, params):
            payload = params.payload or json.loads(
                next(
                    p["value"] for p in params.multipart if p["name"] == "payload_json"
                )
            )
            if channel_id == self.env.channel.id:
                file = params.files[0]
                position = file.fp.tell()
                file.fp.seek(0)
                contents = file.fp.read()
                file.fp.seek(position)
                attempts.append((payload["nonce"], contents))
                if len(attempts) == 1:
                    raise discord.NotFound(
                        SimpleNamespace(status=404, reason="Not found"),
                        {"code": 10008, "message": "Unknown Message"},
                    )
            return await self.env.send(channel_id, params=params)

        self.app.http.send_message = AsyncMock(side_effect=send)
        await self.setup_panel()
        self.assertEqual(len(attempts), 2)
        self.assertNotEqual(attempts[0][0], attempts[1][0])
        self.assertEqual(attempts[0][1], attempts[1][1])
        with Image.open(io.BytesIO(attempts[1][1])) as image:
            self.assertEqual(image.format, "PNG")
        self.assertEqual(len(self.app.store.panels()), 1)

    async def test_other_not_found_errors_do_not_trigger_nonce_retry(self):
        self.app.http.send_message = AsyncMock(
            side_effect=discord.NotFound(
                SimpleNamespace(status=404, reason="Not found"),
                {"code": 10003, "message": "Unknown Channel"},
            )
        )
        with self.assertRaises(discord.NotFound):
            await self.setup_panel()
        self.app.http.send_message.assert_awaited_once()

    async def test_guild_removal_while_upload_is_read_prevents_committing_a_suggestion(
        self,
    ):
        await self.setup_panel()
        i = self.interaction(channel=self.env.thread)
        modal = ImageModal(self.app, i)
        modal.unit._value = "Daki"
        modal.note._value = NOTE
        modal.portrait._values = [SimpleNamespace()]

        async def leave(_):
            self.app.store.remove_guild(1)
            return fixtures.png()

        self.app.read_upload = AsyncMock(side_effect=leave)
        with self.assertRaisesRegex(ValueError, "tópico oficial"):
            await modal.on_submit(i)
        self.assertEqual(self.app.media.pending(), [])
        self.assertEqual(list(self.app.media.root.glob("*.png")), [])

    async def test_failed_edit_cannot_reuse_an_exhausted_attachment_stream_for_repair(
        self,
    ):
        await self.setup_panel()
        old = self.index()
        await old.delete()

        async def exhausted_edit(**kwargs):
            for file in kwargs["attachments"]:
                file.fp.read()
            raise fixtures.missing()

        async def sent_from_current_position(channel_id, *, params):
            for file in params.files or []:
                position = file.fp.tell()
                received = file.fp.read()
                file.fp.seek(position)
                self.assertEqual(received, self.app.portrait_inventory.get().blob)
            return await self.env.send(channel_id, params=params)

        old.edit.side_effect = exhausted_edit
        self.app.http.send_message = AsyncMock(side_effect=sent_from_current_position)
        panel = self.app.store.panels()[0]
        await self.app.sync_index(panel, self.env.thread, force=True)
        self.assertNotEqual(self.index().id, old.id)
        self.assertGreater(self.index().attachments[0].size, 0)

    async def test_invalid_files_consume_attempts_and_stop_before_seventh_download(
        self,
    ):
        await self.setup_panel()
        self.app.read_upload = AsyncMock(return_value=b"invalid image")
        for _ in range(6):
            i = self.interaction(channel=self.env.thread)
            modal = ImageModal(self.app, i)
            modal.unit._value = "Daki"
            modal.note._value = NOTE
            modal.portrait._values = [SimpleNamespace()]
            with self.assertRaises(ValueError):
                await modal.on_submit(i)
        self.assertEqual(self.app.read_upload.await_count, 6)
        with self.assertRaisesRegex(ValueError, "muitas imagens"):
            await modal.on_submit(i)
        self.assertEqual(self.app.read_upload.await_count, 6)
        self.assertEqual(self.app.media.pending(), [])

    async def test_upload_attempt_limit_survives_restart_and_releases_after_window(
        self,
    ):
        from community_bot import CommunityBot

        for _ in range(6):
            self.app.media.begin_upload(7, 1)
        await self.app.close()
        self.app = CommunityBot(self.temp.name, backend=self.backend)
        self.app.store.clock = lambda: self.now
        with self.assertRaisesRegex(ValueError, "muitas imagens"):
            self.app.media.begin_upload(7, 2)
        self.now += 600
        self.app.media.begin_upload(7, 1)
        self.assertEqual(
            len(self.app.store.rows("SELECT * FROM tier_upload_attempts")), 1
        )

    async def test_guild_upload_attempt_limit_preserves_capacity_for_other_guilds(self):
        for actor in range(30):
            self.app.media.begin_upload(actor, 1)
        with self.assertRaisesRegex(ValueError, "Este servidor"):
            self.app.media.begin_upload(100, 1)
        self.app.media.begin_upload(100, 2)
        self.assertEqual(
            len(self.app.store.rows("SELECT * FROM tier_upload_attempts")), 31
        )
