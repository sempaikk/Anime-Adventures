"""Six exclusive categories, legacy boundaries and exact portrait placement."""

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import test_tierlist as fixtures
from tier_categories import TIERS, make_row, rows_for, valid_ranking
from tier_domain import place
from tier_image import render, index_text
from tier_store import TierStore


class CategoryCase(unittest.TestCase):
    def test_one_form_occupies_exactly_one_category(self):
        ranking = [make_row("a", "META_SUPPORT"), make_row("b", "GOOD_SUPPORT")]
        self.assertTrue(valid_ranking(ranking))
        self.assertEqual(sum(len(rows_for(ranking, tier)) for tier in TIERS), 2)
        self.assertEqual(place(ranking, "a"), "META Support #1")
        self.assertEqual(place(ranking, "b"), "Good Support #1")

    def test_each_category_has_stable_left_to_right_order(self):
        for tier in TIERS:
            ranking = [make_row(uid, tier) for uid in ("c", "a", "b")]
            self.assertEqual(
                [r["unit_id"] for r in rows_for(ranking, tier)], ["c", "a", "b"]
            )

    def test_invalid_duplicate_or_previous_categories_are_rejected(self):
        for ranking in (
            [{"unit_id": "a", "tier": "S"}],
            [{"unit_id": "a", "tier": "META"}],
            [{"unit_id": "a", "tier": "META", "role": "DAMAGE"}],
            [{"unit_id": "a", "tier": "DAMAGE"}],
            [make_row("a", "META_HILL"), make_row("a", "GOOD_HILL")],
            [{"unit_id": [], "tier": "META_HILL"}],
            [{"unit_id": "a", "tier": []}],
        ):
            with self.subTest(ranking=ranking):
                self.assertFalse(valid_ranking(ranking))
        with self.assertRaises(ValueError):
            make_row("a", "UNKNOWN")

    def test_original_pixels_appear_in_only_their_exact_category(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "assets").mkdir()
            Image.new("RGB", (88, 88), "red").save(root / "assets/a.png")
            Image.new("RGB", (88, 88), "blue").save(root / "assets/b.png")
            ranking = [make_row("a", "META_SUPPORT"), make_row("b", "GOOD_GROUND")]
            with patch("tier_image.ROOT", root):
                blob = render(
                    ranking, media={u: {"path": f"assets/{u}.png"} for u in ("a", "b")}
                )
            with Image.open(io.BytesIO(blob)) as image:
                self.assertEqual(image.size, (1098, 576))
                self.assertEqual(image.getpixel((180, 48)), (17, 20, 21))
                self.assertEqual(image.getpixel((180, 240)), (255, 0, 0))
                self.assertEqual(image.getpixel((180, 432)), (0, 0, 255))
                self.assertEqual(image.getpixel((180, 528)), (17, 20, 21))


class CategoryMigrationCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "state.sqlite3"
        self.store = TierStore(self.path, clock=lambda: 2000000000)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def reopen(self):
        self.store.close()
        self.store = TierStore(self.path, clock=lambda: 2000000001)

    def test_old_grades_votes_and_panel_survive_a_single_audited_boundary(self):
        self.store.publish(
            [make_row("a", "GOOD_GROUND")],
            {},
            source_version="old",
            model="old",
            comments=[],
        )
        self.store.create_proposal(
            [make_row("b", "GOOD_GROUND")],
            {},
            details={},
            source_version="old",
            model="old",
            comments=[],
        )
        proposal = self.store.active_proposal()
        self.store.remember_poll(proposal["id"], 1, 2, 3)
        self.store.vote(proposal["id"], 4, 1, 2, 3, "approve")
        self.store.remember_panel(1, 2, 9, self.store.latest()["id"])
        legacy = json.dumps([{"unit_id": "a", "tier": "S"}])
        with self.store.connection:
            self.store.connection.execute(
                "UPDATE tier_publications SET ranking=?", (legacy,)
            )
            self.store.connection.execute(
                "UPDATE tier_proposals SET ranking=?", (legacy,)
            )
            self.store.connection.execute(
                "DELETE FROM tier_meta WHERE key='category_policy'"
            )
        self.reopen()
        self.assertEqual(self.store.latest()["ranking"], [])
        self.assertEqual(self.store.latest()["model"], "category-migration")
        self.assertIn(
            "aguardando novas categorias",
            index_text(self.store, self.store.panels()[0]),
        )
        self.assertEqual(
            self.store.rows("SELECT ranking FROM tier_publications WHERE id=1")[0][
                "ranking"
            ],
            legacy,
        )
        self.assertEqual(self.store.proposal(proposal["id"])["status"], "outdated")
        self.assertEqual(self.store.poll_counts(proposal["id"])["approve"], 1)
        self.assertEqual(self.store.panels()[0]["message_id"], "9")
        self.assertEqual(
            len(
                self.store.rows(
                    "SELECT * FROM tier_audit WHERE kind='category-migration'"
                )
            ),
            1,
        )
        publication = self.store.latest()["id"]
        with self.assertRaisesRegex(ValueError, "categorias antigas"):
            self.store.rollback(
                publication, 4, "Tentativa de reverter à classificação antiga de teste."
            )
        self.reopen()
        self.assertEqual(self.store.latest()["id"], publication)

    def test_new_category_survives_restart_and_old_role_schema_is_archived(self):
        self.store.publish(
            [make_row("a", "META_SUPPORT")],
            {},
            source_version="v",
            model="test",
            comments=[],
        )
        self.reopen()
        self.assertEqual(
            self.store.latest()["ranking"], [make_row("a", "META_SUPPORT")]
        )
        with self.store.connection:
            self.store.connection.execute(
                "UPDATE tier_publications SET ranking=?",
                (json.dumps([{"unit_id": "a", "tier": "META", "role": "BUFF"}]),),
            )
            self.store.connection.execute(
                "DELETE FROM tier_meta WHERE key='category_policy'"
            )
        self.reopen()
        self.assertEqual(self.store.latest()["ranking"], [])
        self.assertEqual(self.store.latest()["model"], "category-migration")

    def test_store_rejects_duplicate_forms_before_writing(self):
        with self.assertRaises(ValueError):
            self.store.publish(
                [make_row("a", "META_HILL"), make_row("a", "GOOD_GROUND")],
                {},
                source_version="v",
                model="test",
                comments=[],
            )
        self.assertEqual(self.store.latest()["id"], 0)


class CategoryAnalysisCase(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.TierCase.asyncSetUp
    asyncTearDown = fixtures.TierCase.asyncTearDown
    output = fixtures.TierCase.output
    publish_fixture = fixtures.TierCase.publish_fixture

    async def test_meta_can_change_group_without_duplicating_the_form(self):
        self.publish_fixture([make_row("daki", "META_HILL")])
        ranking, explanations, details = self.analyzer.validate(
            self.output(tier="META_SUPPORT"), self.packet, self.comments
        )
        self.assertEqual(ranking, [make_row("daki", "META_SUPPORT")])
        self.assertEqual(details["daki"]["tier"], "META_SUPPORT")
        self.assertIn("daki", explanations)

    async def test_missing_or_unknown_game_mode_never_creates_a_proposal(self):
        for mode in (None, "unknown", [], False):
            output = self.output()
            output["changes"][0]["mode"] = mode
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.analyzer.validate(output, self.packet, self.comments)
        output = self.output()
        del output["changes"][0]["mode"]
        with self.assertRaises(ValueError):
            self.analyzer.validate(output, self.packet, self.comments)
        self.assertIsNone(self.store.active_proposal())

    async def test_comparison_cannot_move_before_another_category(self):
        self.publish_fixture([make_row("gyutaro", "META_SUPPORT")])
        with self.assertRaisesRegex(ValueError, "mesmo tier"):
            self.analyzer.validate(
                self.output(before="gyutaro"), self.packet, self.comments
            )
