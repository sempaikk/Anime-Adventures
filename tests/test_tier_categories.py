"""Category projection, legacy migration and atomic role-aware decisions."""

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from tier_categories import TIERS, make_row, rows_for, valid_ranking
from tier_domain import place
from tier_image import render, index_text
from tier_store import TierStore
import test_tierlist as fixtures


class CategoryCase(unittest.TestCase):
    def test_meta_is_stored_once_and_displayed_in_its_role_too(self):
        ranking = [make_row("a", "META", "BUFF"), make_row("b", "BUFF", "BUFF")]
        self.assertTrue(valid_ranking(ranking))
        self.assertEqual(len(ranking), 2)
        self.assertEqual([r["unit_id"] for r in rows_for(ranking, "META")], ["a"])
        self.assertEqual([r["unit_id"] for r in rows_for(ranking, "BUFF")], ["a", "b"])
        self.assertEqual(rows_for(ranking, "DAMAGE"), [])
        self.assertEqual(place(ranking, "a"), "Meta #1 · Buff #1")
        self.assertEqual(place(ranking, "b"), "Buff #2")

    def test_all_roles_have_stable_order_with_meta_first(self):
        for role in TIERS[1:]:
            ranking = [
                make_row("c", role, role),
                make_row("a", "META", role),
                make_row("b", role, role),
            ]
            self.assertEqual(
                [r["unit_id"] for r in rows_for(ranking, role)], ["a", "c", "b"]
            )

    def test_invalid_duplicate_ambiguous_or_mismatched_roles_are_rejected(self):
        for ranking in (
            [{"unit_id": "a", "tier": "S"}],
            [{"unit_id": "a", "tier": "META"}],
            [{"unit_id": "a", "tier": "META", "role": "META"}],
            [{"unit_id": "a", "tier": "DAMAGE", "role": "BUFF"}],
            [make_row("a", "META", "DAMAGE"), make_row("a", "DAMAGE", "DAMAGE")],
            [{"unit_id": [], "tier": "META"}],
            [{"unit_id": "a", "tier": []}],
        ):
            with self.subTest(ranking=ranking):
                self.assertFalse(valid_ranking(ranking))
        with self.assertRaises(ValueError):
            make_row("a", "BUFF", "SUPPORT")

    def test_original_pixels_repeat_only_in_meta_and_the_correct_role(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "assets").mkdir()
            Image.new("RGB", (88, 88), "red").save(root / "assets/a.png")
            Image.new("RGB", (88, 88), "blue").save(root / "assets/b.png")
            ranking = [
                make_row("a", "META", "SUPPORT"),
                make_row("b", "DAMAGE", "DAMAGE"),
            ]
            with patch("tier_image.ROOT", root):
                blob = render(
                    ranking, media={u: {"path": f"assets/{u}.png"} for u in ("a", "b")}
                )
            with Image.open(io.BytesIO(blob)) as image:
                self.assertEqual(image.size, (1098, 480))
                self.assertEqual(image.getpixel((180, 48)), (255, 0, 0))
                self.assertEqual(image.getpixel((180, 144)), (0, 0, 255))
                self.assertEqual(image.getpixel((180, 240)), (255, 0, 0))
                self.assertEqual(image.getpixel((180, 336)), (17, 20, 21))


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

    def test_legacy_snapshot_votes_and_panel_survive_a_single_audited_boundary(self):
        ranking = [make_row("a", "DAMAGE", "DAMAGE")]
        self.store.publish(ranking, {}, source_version="old", model="old", comments=[])
        self.store.create_proposal(
            [make_row("b", "DAMAGE", "DAMAGE")],
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
            "Aguardando a primeira classificação por função",
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
        with self.assertRaisesRegex(ValueError, "antigas notas"):
            self.store.rollback(
                publication, 4, "Tentativa de reverter à classificação antiga de teste."
            )
        self.reopen()
        self.assertEqual(self.store.latest()["id"], publication)
        self.assertEqual(
            len(
                self.store.rows(
                    "SELECT * FROM tier_audit WHERE kind='category-migration'"
                )
            ),
            1,
        )

    def test_new_role_snapshot_is_preserved_across_restart(self):
        ranking = [make_row("a", "META", "FARM")]
        self.store.publish(ranking, {}, source_version="v", model="test", comments=[])
        self.reopen()
        self.assertEqual(self.store.latest()["ranking"], ranking)
        self.assertEqual(self.store.rows("SELECT * FROM tier_audit"), [])

    def test_store_rejects_duplicate_role_and_meta_records_before_writing(self):
        ranking = [make_row("a", "META", "FARM"), make_row("a", "FARM", "FARM")]
        with self.assertRaises(ValueError):
            self.store.publish(
                ranking, {}, source_version="v", model="test", comments=[]
            )
        self.assertEqual(self.store.latest()["id"], 0)


class RoleAnalysisCase(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.TierCase.asyncSetUp
    asyncTearDown = fixtures.TierCase.asyncTearDown
    output = fixtures.TierCase.output
    publish_fixture = fixtures.TierCase.publish_fixture

    async def test_meta_support_is_one_record_and_changes_its_role_on_new_evidence(
        self,
    ):
        self.publish_fixture([make_row("daki", "META", "DAMAGE")])
        output = self.output()
        output["changes"][0]["role"] = "SUPPORT"
        ranking, explanations, details = self.analyzer.validate(
            output, self.packet, self.comments
        )
        self.assertEqual(ranking, [make_row("daki", "META", "SUPPORT")])
        self.assertEqual(details["daki"]["role"], "SUPPORT")
        self.assertEqual(explanations["daki"]["role"], "SUPPORT")
        self.assertEqual(rows_for(ranking, "DAMAGE"), [])

    async def test_mismatched_or_missing_role_never_reaches_a_proposal(self):
        for role in (None, "META", "UNKNOWN", [], "FARM"):
            output = self.output(tier="SUPPORT")
            output["changes"][0]["role"] = role
            with self.subTest(role=role), self.assertRaises(ValueError):
                self.analyzer.validate(output, self.packet, self.comments)
        output = self.output()
        del output["changes"][0]["role"]
        with self.assertRaises(ValueError):
            self.analyzer.validate(output, self.packet, self.comments)
        self.assertIsNone(self.store.active_proposal())

    async def test_cross_role_meta_order_preserves_each_primary_role(self):
        self.publish_fixture([make_row("gyutaro", "META", "SUPPORT")])
        ranking, _, _ = self.analyzer.validate(
            self.output(before="gyutaro"), self.packet, self.comments
        )
        self.assertEqual(
            ranking,
            [
                make_row("daki", "META", "DAMAGE"),
                make_row("gyutaro", "META", "SUPPORT"),
            ],
        )
        self.assertEqual(len(rows_for(ranking, "META")), 2)
        self.assertEqual(len(rows_for(ranking, "DAMAGE")), 1)
        self.assertEqual(len(rows_for(ranking, "SUPPORT")), 1)
