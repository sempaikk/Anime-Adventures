"""Public countdowns reflect durable gates without promising unapproved polls."""

import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import test_tier_thread as runtime
import test_tierlist as inference
from tier_analysis import AnalysisUnavailable, DAILY_CALLS, DAILY_TOKENS
from tier_schedule import poll_progress, progress_text
from tier_store import TierStore


class PollScheduleCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "tierlist.sqlite3"
        self.now = 2_000_000_000
        self.store = TierStore(self.path, clock=lambda: self.now)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def progress(self, **kwargs):
        return poll_progress(self.store, ai_enabled=True, **kwargs)

    def comment(self):
        self.store.register_guild(1)
        self.assertTrue(
            self.store.ingest(
                100,
                7,
                1,
                10,
                "Relato artificial para verificar análise de dano e alcance da Daki.",
                {"daki"},
            )
        )

    def propose(self):
        self.store.create_proposal(
            [{"unit_id": "daki", "tier": "S"}],
            {},
            details={},
            source_version="test",
            model="test",
            comments=[],
        )
        return self.store.active_proposal()

    def budget(self, *, calls=0, tokens=0, day=None):
        day = day or datetime.fromtimestamp(self.now, timezone.utc).strftime("%Y-%m-%d")
        self.store.set(
            "budget", json.dumps({"day": day, "calls": calls, "tokens": tokens})
        )

    def test_without_reports_there_is_no_scheduled_poll(self):
        progress = self.progress()
        self.assertEqual(progress.stage, "waiting-reports")
        self.assertIsNone(progress.next_analysis_at)
        self.assertIn("nenhuma proposta pronta", progress_text(progress))
        self.assertNotIn("<t:", progress_text(progress))

    def test_countdown_targets_analysis_availability_not_a_guaranteed_poll(self):
        self.store.set("last_attempt", self.now - 1800)
        progress = self.progress()
        self.assertEqual(progress.stage, "cooldown")
        self.assertEqual(progress.next_analysis_at, self.now + 1800)
        text = progress_text(progress)
        self.assertIn(f"<t:{self.now + 1800}:R>", text)
        self.assertIn("se houver relatos", text)
        self.assertIn("Ainda não confirmada", text)

    def test_opening_time_wins_over_analysis_time_and_leaves_fifty_minutes_after_close(
        self,
    ):
        self.store.set_interval(30)
        self.store.set("last_attempt", self.now)
        proposal = self.propose()
        self.now += 125
        self.store.remember_poll(proposal["id"], 1, 10, 101, published_at=self.now)
        opened = self.now
        progress = self.progress()
        self.assertEqual(progress.stage, "open")
        self.assertEqual(progress.next_analysis_at, opened + 3600)
        self.assertEqual(progress.closes_at, opened + 600)
        self.now += 600
        self.store.resolve_due(source_version="test")
        self.assertEqual(self.progress().next_analysis_at - self.now, 50 * 60)
        self.assertFalse(self.store.may_propose())

    def test_restart_keeps_the_same_countdown(self):
        self.store.set("last_attempt", self.now)
        expected = self.progress().next_analysis_at
        self.store.close()
        self.now += 1000
        self.store = TierStore(self.path, clock=lambda: self.now)
        self.assertEqual(self.progress().next_analysis_at, expected)

    def test_queued_proposal_has_no_deadline_until_discord_confirms_publication(self):
        self.propose()
        progress = poll_progress(self.store, ai_enabled=False, maintenance=True)
        self.assertEqual(progress.stage, "queued")
        self.assertIsNone(progress.closes_at)
        self.assertIn("proposta pronta", progress_text(progress))
        self.assertNotIn("<t:", progress_text(progress))

    def test_expired_open_poll_shows_counting_results_instead_of_time_in_the_past(self):
        proposal = self.propose()
        self.store.remember_poll(proposal["id"], 1, 10, 101)
        self.now += 600
        self.assertEqual(self.progress().stage, "closing")
        self.assertIn("apurando o resultado", progress_text(self.progress()))
        self.assertNotIn("encerra <t:", progress_text(self.progress()))

    def test_existing_poll_still_shows_its_deadline_when_new_analysis_is_paused(self):
        proposal = self.propose()
        self.store.remember_poll(proposal["id"], 1, 10, 101)
        progress = poll_progress(self.store, ai_enabled=False)
        self.assertEqual(progress.stage, "open")
        self.assertIsNone(progress.next_analysis_at)
        self.assertIn(f"<t:{self.now + 600}:R>", progress_text(progress))

    def test_no_proposal_result_is_explained_while_waiting_for_another_analysis(self):
        self.store.set("last_attempt", self.now)
        self.store.set("analysis_status", "no-proposal")
        self.assertIn(
            "A última análise não gerou proposta", progress_text(self.progress())
        )

    def test_failed_attempt_is_explained_without_exposing_provider_details(self):
        self.store.set("last_attempt", self.now)
        self.store.set("analysis_status", "retry")
        self.store.set("analysis_error", "provider-503")
        text = progress_text(self.progress())
        self.assertIn("posições preservadas", text)
        self.assertNotIn("503", text)

    def test_pending_reports_can_start_now_only_after_both_gates(self):
        self.comment()
        self.store.set("last_attempt", self.now - 3600 + 1)
        self.assertEqual(self.progress().stage, "cooldown")
        self.now += 1
        self.assertEqual(self.progress().stage, "ready")
        self.assertIn("pode começar agora", progress_text(self.progress()))

    def test_processed_expired_and_exhausted_reports_do_not_promise_new_analysis(self):
        self.comment()
        for column, value in (
            ("processed", 1),
            ("attempts", 3),
            ("created_at", self.now - 7 * 86400 - 1),
        ):
            with self.subTest(column=column):
                with self.store.connection:
                    self.store.connection.execute(
                        "UPDATE tier_comments SET processed=0,attempts=0,created_at=?",
                        (self.now,),
                    )
                    self.store.connection.execute(
                        f"UPDATE tier_comments SET {column}=?", (value,)
                    )
                self.assertEqual(self.progress().stage, "waiting-reports")

    def test_daily_limit_and_low_remaining_budget_hide_unreliable_countdown(self):
        for calls, tokens in ((DAILY_CALLS, 0), (0, DAILY_TOKENS - 1)):
            with self.subTest(calls=calls, tokens=tokens):
                self.budget(calls=calls, tokens=tokens)
                progress = self.progress()
                self.assertEqual(progress.stage, "paused")
                self.assertNotIn("<t:", progress_text(progress))
                self.assertNotIn("tokens", progress_text(progress))

    def test_old_utc_budget_does_not_keep_the_next_day_paused(self):
        self.budget(calls=DAILY_CALLS, day="2000-01-01")
        self.store.set("analysis_status", "quota")
        self.assertEqual(self.progress().stage, "waiting-reports")

    def test_inflight_last_budgeted_request_is_still_shown_as_analysis(self):
        self.budget(calls=DAILY_CALLS)
        self.assertEqual(self.progress(analyzing=True).stage, "analyzing")
        self.assertEqual(self.progress().stage, "paused")

    def test_missing_engine_maintenance_or_invalid_budget_do_not_offer_a_countdown(
        self,
    ):
        for options in (
            {"ai_enabled": False},
            {"ai_enabled": True, "maintenance": True},
        ):
            progress = poll_progress(self.store, **options)
            self.assertEqual(progress.stage, "paused")
        self.store.set("budget", "[]")
        self.assertEqual(self.progress().stage, "paused")

    def test_preparation_does_not_claim_that_a_model_request_has_started(self):
        progress = self.progress(preparing=True)
        self.assertEqual(progress.stage, "preparing")
        self.assertIn("organizando os relatos", progress_text(progress))

    def test_progress_is_read_only_and_does_not_consume_budget(self):
        self.comment()
        self.budget(calls=3, tokens=500)
        before = self.store.connection.total_changes
        for _ in range(20):
            self.progress()
        self.assertEqual(self.store.connection.total_changes, before)


class InferenceProgressCase(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = inference.TierCase.asyncSetUp
    asyncTearDown = inference.TierCase.asyncTearDown

    async def test_real_analysis_lifecycle_shows_inflight_then_empty_result(self):
        started, finish = asyncio.Event(), asyncio.Event()

        async def answer(_):
            started.set()
            await finish.wait()
            return {"changes": []}, 300

        self.backend.analyze.side_effect = answer
        task = asyncio.create_task(self.analyzer.run())
        try:
            await started.wait()
            self.assertTrue(self.analyzer.running)
            self.assertEqual(
                poll_progress(
                    self.store, ai_enabled=True, analyzing=self.analyzer.running
                ).stage,
                "analyzing",
            )
        finally:
            finish.set()
            await task
        self.assertFalse(self.analyzer.running)
        self.assertIsNone(self.store.active_proposal())
        self.assertIn(
            "não gerou proposta",
            progress_text(poll_progress(self.store, ai_enabled=True)),
        )

    async def test_cancelled_analysis_clears_running_flag_and_preserves_retry_time(
        self,
    ):
        started, finish = asyncio.Event(), asyncio.Event()

        async def answer(_):
            started.set()
            await finish.wait()

        self.backend.analyze.side_effect = answer
        task = asyncio.create_task(self.analyzer.run())
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(self.analyzer.running)
        progress = poll_progress(self.store, ai_enabled=True)
        self.assertEqual(progress.stage, "cooldown")
        self.assertEqual(progress.next_analysis_at, self.now + 3600)
        self.assertIsNone(self.store.active_proposal())

    async def test_provider_failure_clears_running_flag(self):
        self.backend.analyze.side_effect = AnalysisUnavailable("provider-503")
        await self.analyzer.run()
        self.assertFalse(self.analyzer.running)
        self.assertEqual(self.store.get("analysis_status"), "retry")


class RuntimeCountdownCase(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = runtime.ThreadRuntimeCase.asyncSetUp
    asyncTearDown = runtime.ThreadRuntimeCase.asyncTearDown
    interaction = runtime.ThreadRuntimeCase.interaction
    setup_panel = runtime.ThreadRuntimeCase.setup_panel

    async def test_native_discord_counter_does_not_require_reediting_each_tick(self):
        self.backend.enabled = True
        self.app.store.set("last_attempt", self.now)
        await self.setup_panel()
        record = self.app.store.thread(1)
        index = self.env.partial(self.env.thread, int(record["intro_id"]))
        self.assertIn(f"<t:{self.now + 3600}:R>", index.content)
        index.edit.reset_mock()
        self.now += 30
        await self.app.panel_loop.coro(self.app)
        index.edit.assert_not_awaited()
        self.now += 3570
        await self.app.panel_loop.coro(self.app)
        index.edit.assert_awaited_once()
        self.assertIn("nenhuma proposta pronta", index.content)
        self.assertNotIn("<t:", index.content)
        self.backend.analyze.assert_not_awaited()

    async def test_public_index_reports_inflight_analysis_without_technical_controls(
        self,
    ):
        self.backend.enabled = True
        self.app.analyzer.running = True
        await self.setup_panel()
        index = self.env.partial(
            self.env.thread, int(self.app.store.thread(1)["intro_id"])
        )
        self.assertIn("avaliando os relatos agora", index.content)
        self.assertIn("depende do resultado", index.content)
        self.assertNotIn("Diagnóstico", index.content)
        self.assertNotIn("tokens", index.content)
        self.assertLessEqual(len(index.content.encode("utf-16-le")) // 2, 2000)
