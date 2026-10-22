"""Game updates cannot mix old evidence, stale inference or votes across the boundary."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import tier_balance
from tier_analysis import TierAnalyzer
from tier_catalog import TierCatalog
from tier_image import poll_embed
from tier_schedule import poll_progress, progress_text
from tier_seed import seed_initial
from tier_store import TierStore


NOTE = "Atualização artificial do teste; nenhuma informação real do jogo foi alterada."


class GameUpdateCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.now = 2_000_000_000
        self.path = Path(self.temp.name) / "tierlist.sqlite3"
        self.store = TierStore(self.path, clock=lambda: self.now)
        self.store.register_guild(1)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def update(self, **kwargs):
        return tier_balance.register(
            self.store,
            expected=tier_balance.revision(self.store),
            label="Update de teste",
            effective_at=self.now - 30,
            reason=NOTE,
            actor=7,
            **kwargs,
        )

    def propose(self):
        self.store.create_proposal(
            [{"unit_id": "daki", "tier": "GOOD_GROUND"}],
            {},
            details={
                "daki": {
                    "tier": "GOOD_GROUND",
                    "before": None,
                    "reason": NOTE,
                    "sources": [],
                }
            },
            source_version="test",
            model="test",
            comments=[],
        )
        return self.store.active_proposal()

    def resume(self):
        return tier_balance.resume(
            self.store,
            expected=tier_balance.revision(self.store),
            source_version="reviewed-source",
            reason=NOTE,
            actor=7,
        )

    def test_update_cancels_running_poll_but_preserves_votes_images_and_old_results(
        self,
    ):
        proposal = self.propose()
        self.store.remember_poll(proposal["id"], 1, 10, 100)
        for n in range(5):
            self.store.vote(proposal["id"], n, 1, 10, 100, "approve")
        board = self.store.board()
        self.update()
        self.assertEqual(self.store.proposal(proposal["id"])["status"], "game-updated")
        self.assertEqual(self.store.proposal(proposal["id"])["outcome"]["approve"], 5)
        self.assertEqual(self.store.poll_counts(proposal["id"])["approve"], 5)
        with self.assertRaises(ValueError):
            self.store.vote(proposal["id"], 8, 1, 10, 100, "approve")
        self.now += 1000
        self.store.resolve_due(source_version="test")
        self.assertEqual(self.store.board(), board)
        text = str(
            poll_embed(
                self.store, TierCatalog(), self.store.proposal(proposal["id"])
            ).to_dict()
        )
        self.assertIn("atualização", text)
        self.assertIn("dados anteriores", text)
        self.assertEqual(self.store.decisions(), [])

    def test_old_reports_cannot_be_reimported_or_used_as_context_after_update(self):
        self.assertTrue(
            self.store.ingest(
                "old",
                1,
                1,
                10,
                "Daki causa sangramento no infinito, relato anterior.",
                {"daki"},
                sent_at=self.now - 60,
            )
        )
        old = self.store.pending()
        self.update()
        self.assertFalse(self.store.has_pending_comments())
        self.assertEqual(self.store.pending(), [])
        self.assertEqual(self.store.recent(), [])
        self.assertFalse(self.store.still_allowed(old))
        self.assertFalse(
            self.store.ingest(
                "reimport",
                2,
                1,
                10,
                "Daki tinha dano antigo no modo infinito antes da atualização.",
                {"daki"},
                sent_at=self.now - 60,
            )
        )
        self.assertTrue(
            self.store.ingest(
                "new",
                3,
                1,
                10,
                "Daki recebeu alcance no infinito, novo relato de teste.",
                {"daki"},
                sent_at=self.now,
            )
        )
        self.assertEqual([c["message_id"] for c in self.store.pending()], ["new"])
        self.resume()
        self.assertEqual([c["message_id"] for c in self.store.pending()], ["new"])
        self.assertEqual(len(self.store.rows("SELECT * FROM tier_comments")), 2)

    async def test_paused_analysis_spends_no_api_budget_and_survives_restart(self):
        update = self.update()
        backend = SimpleNamespace(enabled=True, model="test", analyze=AsyncMock())
        self.assertFalse(
            await TierAnalyzer(self.store, TierCatalog(), backend=backend).run()
        )
        backend.analyze.assert_not_awaited()
        self.assertIsNone(self.store.get("budget"))
        self.store.close()
        self.store = TierStore(self.path, clock=lambda: self.now)
        self.assertEqual(tier_balance.state(self.store), update)
        progress = poll_progress(self.store, ai_enabled=True)
        self.assertEqual(progress.stage, "game-update")
        self.assertIn("posições anteriores preservadas", progress_text(progress))
        self.assertFalse(self.store.may_propose())
        with self.assertRaisesRegex(ValueError, "atualizado"):
            self.propose()
        self.resume()
        self.assertFalse(tier_balance.paused(self.store))

    async def test_inflight_response_cannot_publish_after_update_even_if_resumed(self):
        self.store.ingest(
            "new",
            1,
            1,
            10,
            "Daki tem dano e sangramento no infinito neste relato de teste.",
            {"daki"},
        )

        async def response(packet):
            self.update()
            self.resume()
            return {"changes": []}, 20

        backend = SimpleNamespace(
            enabled=True, model="test", analyze=AsyncMock(side_effect=response)
        )
        analyzer = TierAnalyzer(self.store, TierCatalog(), backend=backend)
        self.assertFalse(await analyzer.run())
        backend.analyze.assert_awaited_once()
        self.assertEqual(self.store.rows("SELECT * FROM tier_proposals"), [])
        self.assertEqual(self.store.get("analysis_status"), "waiting")

    def test_stale_owner_form_and_stale_proposal_generation_are_rejected(self):
        self.update()
        with self.assertRaisesRegex(ValueError, "mudou"):
            tier_balance.register(
                self.store,
                expected="",
                label="Outra atualização",
                effective_at=self.now,
                reason=NOTE,
                actor=7,
            )
        self.resume()
        with self.assertRaisesRegex(ValueError, "atualizado"):
            self.store.create_proposal(
                [{"unit_id": "daki", "tier": "GOOD_GROUND"}],
                {},
                details={},
                source_version="test",
                model="test",
                comments=[],
                game_revision="",
            )
        with self.assertRaises(ValueError):
            tier_balance.resume(
                self.store,
                expected=tier_balance.revision(self.store),
                source_version="test",
                reason=NOTE,
                actor=7,
            )
        self.assertEqual(self.store.board()["id"], 0)

    def test_seed_is_not_reapplied_after_any_recorded_game_update(self):
        self.update()
        self.resume()
        seed_initial(self.store, TierCatalog())
        self.assertEqual(self.store.board()["id"], 0)
        self.assertEqual(
            self.store.rows("SELECT * FROM tier_audit WHERE kind='wiki-baseline'"), []
        )

    def test_invalid_dates_do_not_cancel_a_pending_proposal(self):
        before = self.propose()
        for when in [self.now + 60, float("nan"), True, -1]:
            with self.assertRaises(ValueError):
                tier_balance.register(
                    self.store,
                    expected="",
                    label="Teste de data",
                    effective_at=when,
                    reason=NOTE,
                    actor=7,
                )
        self.assertEqual(self.store.active_proposal(), before)
        self.assertEqual(tier_balance.state(self.store), {})
