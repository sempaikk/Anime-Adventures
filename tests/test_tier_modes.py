"""Independent mode decisions, attributed bootstrap, retention and image delivery."""

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import test_tierlist as fixtures
from tier_catalog import TierCatalog
from tier_categories import comment_context, make_row
from tier_image import PanelRenderer, render_modes, index_text
from tier_seed import load_reference, seed_initial
from tier_store import TierStore
from tier_analysis import TierAnalyzer, SYSTEM, MAX_INPUT_BYTES


class ModeStoreCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "tierlist.sqlite3"
        self.now = 2000000000
        self.store = TierStore(self.path, clock=lambda: self.now)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def publish(self, uid, tier, mode="infinite"):
        return self.store.publish(
            [make_row(uid, tier)],
            {},
            source_version="test",
            model="test",
            comments=[],
            mode=mode,
        )

    def test_each_mode_keeps_a_different_position_for_the_same_form(self):
        self.publish("a", "META_HILL")
        self.publish("a", "GOOD_GROUND", "casual")
        self.assertEqual(self.store.latest()["ranking"], [make_row("a", "META_HILL")])
        self.assertEqual(
            self.store.latest("casual")["ranking"], [make_row("a", "GOOD_GROUND")]
        )
        self.assertEqual(self.store.board()["id"], self.store.latest("casual")["id"])
        self.store.close()
        self.store = TierStore(self.path)
        self.assertEqual(
            self.store.latest("casual")["ranking"], [make_row("a", "GOOD_GROUND")]
        )

    def test_approval_changes_only_the_named_mode_and_checks_its_own_base(self):
        self.publish("a", "GOOD_GROUND", "casual")
        self.store.create_proposal(
            [make_row("a", "META_GROUND")],
            {},
            details={},
            source_version="test",
            model="test",
            comments=[],
            mode="casual",
        )
        proposal = self.store.active_proposal()
        self.store.remember_poll(proposal["id"], 1, 2, 3)
        for uid in range(5):
            self.store.vote(proposal["id"], uid, 1, 2, 3, "approve")
        self.publish("b", "META_SUPPORT")
        infinite = self.store.latest()["id"]
        self.now += 601
        self.store.resolve_due(source_version="test")
        self.assertEqual(self.store.proposal(proposal["id"])["status"], "approved")
        self.assertEqual(
            self.store.latest("casual")["ranking"], [make_row("a", "META_GROUND")]
        )
        self.assertEqual(self.store.latest()["id"], infinite)

    def test_rollback_does_not_cross_modes_or_cancel_the_other_mode_poll(self):
        self.publish("a", "GOOD_GROUND", "casual")
        first = self.store.latest("casual")["ranking"]
        self.publish("a", "META_SUPPORT")
        self.publish("a", "META_GROUND", "casual")
        self.store.create_proposal(
            [make_row("b", "GOOD_HILL")],
            {},
            details={},
            source_version="test",
            model="test",
            comments=[],
        )
        pending = self.store.active_proposal()["id"]
        self.store.rollback(
            self.store.latest("casual")["id"],
            7,
            "Correção artificial e exclusiva da lista Casual.",
            mode="casual",
        )
        self.assertEqual(self.store.latest("casual")["ranking"], first)
        self.assertEqual(
            self.store.latest()["ranking"], [make_row("a", "META_SUPPORT")]
        )
        self.assertEqual(self.store.proposal(pending)["status"], "queued")

    def test_retention_keeps_the_latest_less_active_mode(self):
        self.publish("a", "GOOD_GROUND", "casual")
        casual = self.store.latest("casual")["id"]
        for n in range(30):
            self.publish(str(n), "GOOD_HILL")
        self.store.cleanup()
        self.assertEqual(self.store.latest("casual")["id"], casual)
        self.assertEqual(len(self.store.rows("SELECT id FROM tier_publications")), 21)

    def test_retired_forms_are_removed_from_both_modes(self):
        self.publish("uraraka", "GOOD_GROUND")
        self.publish("uraraka", "META_SUPPORT", "casual")
        self.store.bind_catalog(TierCatalog())
        self.assertEqual(self.store.latest()["ranking"], [])
        self.assertEqual(self.store.latest("casual")["ranking"], [])

    def test_wiki_baseline_is_attributed_partial_and_creates_no_votes(self):
        seed_initial(self.store, TierCatalog())
        for mode in ("infinite", "casual"):
            self.assertEqual(self.store.latest(mode)["model"], "wiki-baseline")
            self.assertEqual(len(self.store.latest(mode)["ranking"]), 37)
        self.assertEqual(self.store.rows("SELECT * FROM tier_votes"), [])
        self.assertIsNone(self.store.active_proposal())
        self.store.remember_panel(1, 2, 3, self.store.board()["id"])
        text = index_text(self.store, self.store.panels()[0])
        self.assertIn("importada parcialmente", text)
        self.assertIn("posições são referência", text)
        self.assertEqual(
            len(self.store.rows("SELECT * FROM tier_audit WHERE kind='wiki-baseline'")),
            2,
        )

    def test_restart_and_owner_correction_do_not_reimport_the_initial_wiki(self):
        seed_initial(self.store, TierCatalog())
        self.publish("daki", "GOOD_GROUND")
        self.store.rollback(
            self.store.latest()["id"],
            7,
            "Teste de restauração da base inicial nesta lista.",
        )
        publication = self.store.board()["id"]
        self.store.close()
        self.store = TierStore(self.path)
        seed_initial(self.store, TierCatalog())
        self.assertEqual(self.store.board()["id"], publication)
        self.assertEqual(
            len(self.store.rows("SELECT * FROM tier_audit WHERE kind='wiki-baseline'")),
            2,
        )

    def test_bootstrap_preserves_a_running_first_poll_without_changing_its_base(self):
        self.store.create_proposal(
            [make_row("daki", "META_GROUND")],
            {},
            details={},
            source_version="test",
            model="test",
            comments=[],
        )
        proposal = self.store.active_proposal()
        seed_initial(self.store, TierCatalog())
        self.assertEqual(self.store.latest()["id"], proposal["base_publication"])
        self.assertEqual(self.store.proposal(proposal["id"])["status"], "queued")
        self.assertEqual(self.store.latest("casual")["model"], "wiki-baseline")

    def test_existing_live_list_is_never_overwritten_by_bootstrap(self):
        self.publish("daki", "META_GROUND")
        before = self.store.latest()["id"]
        seed_initial(self.store, TierCatalog())
        self.assertEqual(self.store.latest()["id"], before)
        self.assertEqual(self.store.latest("casual")["model"], "wiki-baseline")
        self.assertEqual(
            self.store.get("wiki_seed:placements-v1:infinite"), "preserved-existing"
        )

    def test_reference_matches_pinned_source_and_excludes_unknown_names(self):
        data = load_reference()
        active = TierCatalog()
        self.assertEqual(data["revision"], 46773)
        self.assertEqual(len(data["unresolved"]), 76)
        for mode, rows in data["modes"].items():
            self.assertTrue(all(r["unit_id"] in active.units for r in rows), mode)
            self.assertEqual(len({r["unit_id"] for r in rows}), len(rows))
        data["modes"]["infinite"][0]["source_name"] = "UNRELATED NAME"
        path = Path(self.temp.name) / "bad.json"
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "fonte registrada"):
            load_reference(path)

    def test_real_wiki_sources_and_two_mode_positions_fit_the_free_input_budget(self):
        catalog = TierCatalog()
        seed_initial(self.store, catalog)
        self.store.enable_channel(1, 2)
        uids = {r["unit_id"] for r in self.store.latest()["ranking"][:2]}
        names = " e ".join(catalog.display_name(uid) for uid in sorted(uids))
        for n, clause in enumerate(
            ("dano e custo", "sangramento e alcance", "condições dos upgrades")
        ):
            body = (
                names + " têm mais " + clause + " nesta avaliação de Anime Adventures. "
            ) * 4
            self.assertTrue(self.store.ingest(str(n), str(n), 1, 2, body, uids))
        packet, comments = TierAnalyzer(self.store, catalog).packet()
        self.assertIsNotNone(packet)
        self.assertEqual(len(comments), 3)
        self.assertLessEqual(
            len(SYSTEM.encode())
            + len(
                json.dumps(packet, ensure_ascii=False, separators=(",", ":")).encode()
            ),
            MAX_INPUT_BYTES,
        )

    def test_renderer_keeps_separate_original_pixels_for_each_mode(self):
        root = Path(self.temp.name)
        (root / "assets").mkdir()
        Image.new("RGB", (88, 88), "red").save(root / "assets/a.png")
        Image.new("RGB", (88, 88), "blue").save(root / "assets/b.png")
        self.publish("a", "META_HILL")
        self.publish("b", "GOOD_GROUND", "casual")
        media = {u: {"path": f"assets/{u}.png"} for u in ("a", "b")}
        with patch("tier_image.ROOT", root):
            blob = render_modes(self.store.board()["modes"], media=media)
        with Image.open(io.BytesIO(blob)) as image:
            self.assertEqual(image.size, (1098, 1260))
            self.assertEqual(image.getpixel((180, 102)), (255, 0, 0))
            self.assertEqual(image.getpixel((180, 1116)), (0, 0, 255))
            self.assertEqual(image.getpixel((180, 486)), (17, 20, 21))
            self.assertEqual(image.getpixel((180, 732)), (17, 20, 21))

    def test_board_cache_invalidates_when_only_casual_changes(self):
        renderer = PanelRenderer(None)
        self.publish("daki", "GOOD_GROUND")
        _, first = renderer.get(self.store.board(), {}, 0, 524)
        self.publish("gyutaro", "META_HILL", "casual")
        _, second = renderer.get(self.store.board(), {}, 0, 524)
        self.assertNotEqual(first, second)


class ModeAnalysisCase(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.TierCase.asyncSetUp
    asyncTearDown = fixtures.TierCase.asyncTearDown
    output = fixtures.TierCase.output

    async def test_packet_contains_both_independent_lists(self):
        self.store.publish(
            [make_row("daki", "GOOD_GROUND")],
            {},
            source_version="test",
            model="test",
            comments=[],
            mode="casual",
        )
        packet, _ = self.analyzer.packet()
        self.assertEqual(packet["current"]["infinite"], [])
        self.assertEqual(packet["current"]["casual"], [make_row("daki", "GOOD_GROUND")])

    async def test_comment_from_another_mode_cannot_support_a_change(self):
        comments = [dict(c) for c in self.comments]
        for c in comments:
            c["body"] = "Daki tem mais dano no modo Infinite, conforme este teste."
        output = self.output()
        output["changes"][0]["mode"] = "casual"
        with self.assertRaisesRegex(ValueError, "outro modo"):
            self.analyzer.validate(output, self.packet, comments)

    async def test_backend_creates_a_casual_proposal_without_touching_infinite(self):
        output = self.output()
        output["changes"][0]["mode"] = "casual"
        self.backend.analyze.return_value = (output, 300)
        self.assertTrue(await self.analyzer.run())
        self.assertEqual(self.store.active_proposal()["mode"], "casual")
        self.assertEqual(self.store.latest()["id"], 0)
        self.assertEqual(self.store.latest("casual")["id"], 0)
        self.assertEqual(
            self.store.active_proposal()["details"]["daki"]["mode"], "casual"
        )

    async def test_local_context_detection_has_no_ai_cost(self):
        for text, mode in [
            ("melhor no infinito", "infinite"),
            ("boa para Raid e Story", "casual"),
            ("Infinite e Legend Stage", "both"),
            ("Daki tem sangramento melhor", "general"),
        ]:
            self.assertEqual(comment_context(text), mode)
