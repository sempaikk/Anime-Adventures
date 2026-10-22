import io
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from PIL import Image

from community_domain import Catalog
from tier_analysis import (
    AnalysisUnavailable,
    EvidenceLibrary,
    GroqBackend,
    MAX_INPUT_BYTES,
    SYSTEM,
    QuotaReached,
    TierAnalyzer,
)
from tier_image import render, log_embed
from tier_store import TierStore, TIERS, REQUIRED_TABLES
from storage_maintenance import snapshot_database

QUOTE = "Texto de referência de teste sobre mecânicas e condições. Não descreve os atributos reais do jogo."
REASON = "Explicação de teste sobre pontos fortes e condições de uso, sem afirmar um balanceamento real do jogo."


class TierCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.now = 2000000000
        self.store = TierStore(self.root / "tierlist.sqlite3", clock=lambda: self.now)
        self.catalog = Catalog()
        self.store.enable_channel("100", "101")
        self.store.enable_channel("200", "201")
        self.comments = []
        for index, gid, cid in [
            (0, "100", "101"),
            (1, "200", "201"),
            (2, "100", "101"),
        ]:
            uid = "user" + str(index)
            self.store.consent(uid)
            self.store.ingest(
                "message" + str(index),
                uid,
                gid,
                cid,
                [
                    "Daki e Gyutaro têm comparações de sangramento nesta avaliação de teste.",
                    "Neste ensaio verificamos o alcance entre Gyutaro e Daki nesta partida de teste.",
                    "Daki oferece suporte para um time com Gyutaro nesta simulação de partida.",
                ][index],
                {"daki", "gyutaro"},
            )
        data = {
            "version": "test-only",
            "sources": {
                u + ":article": {
                    "unit_id": u,
                    "text": QUOTE,
                    "url": "https://animeadventures.fandom.com/wiki/" + u + "?oldid=1",
                }
                for u in ("daki", "gyutaro")
            },
        }
        path = self.root / "evidence.json"
        path.write_text(json.dumps(data))
        self.evidence = EvidenceLibrary(path)
        self.backend = SimpleNamespace(
            enabled=True, model="test-model", analyze=AsyncMock()
        )
        self.analyzer = TierAnalyzer(
            self.store, self.catalog, backend=self.backend, evidence=self.evidence
        )
        self.packet, self.comments = self.analyzer.packet()

    async def asyncTearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def output(self, *, uid="daki", tier="META_HILL", before=None):
        evidence = [{"source_id": uid + ":article", "quote": QUOTE}]
        if before:
            evidence.append({"source_id": before + ":article", "quote": QUOTE})
        return {
            "changes": [
                {
                    "unit_id": uid,
                    "tier": tier,
                    "mode": "infinite",
                    "before": before,
                    "confidence": 0.95,
                    "supporting_comments": ["c0", "c1", "c2"],
                    "reason": REASON,
                    "conditions": "Condições de uso descritas nas fontes desta simulação.",
                    "caveat": "É preciso conferir as limitações antes de concluir a comparação.",
                    "evidence": evidence,
                }
            ]
        }

    def publish_fixture(self, ranking):
        reasons = {
            r["unit_id"]: {
                "reason": REASON,
                "sources": [
                    {
                        "url": self.evidence.sources[r["unit_id"] + ":article"]["url"],
                        "quote": QUOTE,
                    }
                ],
            }
            for r in ranking
            if r["tier"] == "META_HILL"
        }
        self.store.publish(
            ranking, reasons, source_version="test", model="test", comments=[]
        )

    def approve_poll(self):
        proposal = self.store.active_proposal()
        self.store.remember_poll(proposal["id"], "100", "101", "999")
        for i in range(5):
            self.store.vote(
                proposal["id"], "voter" + str(i), "100", "101", "999", "approve"
            )
        self.now += 601
        self.store.resolve_due(source_version=self.evidence.version)

    async def test_verified_structured_output_opens_poll_before_a_global_image_revision(
        self,
    ):
        self.backend.analyze.return_value = (self.output(), 300)
        self.assertTrue(await self.analyzer.run())
        self.assertEqual(self.store.latest()["id"], 0)
        self.approve_poll()
        self.assertEqual(
            self.store.latest()["ranking"],
            [{"unit_id": "daki", "tier": "META_HILL"}],
        )
        self.assertEqual(self.store.latest()["explanations"]["daki"]["reason"], REASON)
        self.assertEqual(len(self.store.history()), 1)

    async def test_relative_order_moves_right_without_demoting_the_previous_meta(self):
        self.publish_fixture([{"unit_id": "gyutaro", "tier": "META_HILL"}])
        self.backend.analyze.return_value = (self.output(before="gyutaro"), 300)
        await self.analyzer.run()
        self.approve_poll()
        self.assertEqual(
            self.store.latest()["ranking"],
            [
                {"unit_id": "daki", "tier": "META_HILL"},
                {"unit_id": "gyutaro", "tier": "META_HILL"},
            ],
        )
        self.assertEqual(self.store.history()[0]["to_position"], 2)

    async def test_missing_ai_key_never_calls_model_or_fakes_a_publication(self):
        self.backend.enabled = False
        self.assertFalse(await self.analyzer.run())
        self.backend.analyze.assert_not_awaited()
        self.assertEqual(self.store.latest()["id"], 0)

    async def test_quota_keeps_the_previous_ranking_and_pending_evidence(self):
        self.publish_fixture([{"unit_id": "gyutaro", "tier": "META_HILL"}])
        old = self.store.latest()
        self.backend.analyze.side_effect = QuotaReached("quota")
        self.assertFalse(await self.analyzer.run())
        self.assertEqual(self.store.latest(), old)
        self.assertEqual(len(self.store.pending()), 3)
        self.assertEqual(self.store.get("analysis_status"), "quota")

    async def test_budget_refuses_paid_fallback_or_calls_above_the_local_limit(self):
        day = datetime.fromtimestamp(self.now, timezone.utc).strftime("%Y-%m-%d")
        self.store.set("budget", json.dumps({"day": day, "calls": 48, "tokens": 0}))
        self.assertFalse(await self.analyzer.run())
        self.backend.analyze.assert_not_awaited()

    async def test_token_budget_also_stops_new_requests(self):
        day = datetime.fromtimestamp(self.now, timezone.utc).strftime("%Y-%m-%d")
        self.store.set("budget", json.dumps({"day": day, "calls": 0, "tokens": 149999}))
        self.assertFalse(await self.analyzer.run())
        self.backend.analyze.assert_not_awaited()

    async def test_retry_waits_the_selected_interval(self):
        self.backend.analyze.side_effect = AnalysisUnavailable("offline")
        await self.analyzer.run()
        await self.analyzer.run()
        self.assertEqual(self.backend.analyze.await_count, 1)
        self.now += 3601
        await self.analyzer.run()
        self.assertEqual(self.backend.analyze.await_count, 2)

    async def test_withdrawal_during_inference_discards_result(self):
        async def answer(packet):
            self.store.withdraw("user0")
            return self.output(), 300

        self.backend.analyze.side_effect = answer
        self.assertFalse(await self.analyzer.run())
        self.assertEqual(self.store.latest()["id"], 0)

    async def test_disabling_source_during_inference_discards_result(self):
        async def answer(packet):
            self.store.remove_guild("200")
            return self.output(), 300

        self.backend.analyze.side_effect = answer
        self.assertFalse(await self.analyzer.run())
        self.assertEqual(self.store.latest()["id"], 0)

    async def test_no_changes_does_not_fake_a_new_update_time(self):
        self.backend.analyze.return_value = ({"changes": []}, 200)
        self.assertFalse(await self.analyzer.run())
        self.assertEqual(self.store.latest()["id"], 0)
        self.assertEqual(self.store.pending(), [])

    def test_numeric_claim_missing_from_citations_is_rejected(self):
        output = self.output()
        output["changes"][0]["reason"] += " Tem 5% a mais de dano."
        with self.assertRaises(ValueError):
            self.analyzer.validate(output, self.packet, self.comments)

    def test_invented_quote_is_rejected(self):
        output = self.output()
        output["changes"][0]["evidence"][0]["quote"] = (
            "Uma frase que não aparece na fonte fornecida."
        )
        with self.assertRaises(ValueError):
            self.analyzer.validate(output, self.packet, self.comments)

    def test_other_forms_source_cannot_justify_this_form(self):
        output = self.output()
        output["changes"][0]["evidence"] = [
            {"source_id": "gyutaro:article", "quote": QUOTE}
        ]
        with self.assertRaises(ValueError):
            self.analyzer.validate(output, self.packet, self.comments)

    def test_unknown_unit_or_tier_cannot_be_published(self):
        for key, value in [("unit_id", "not-a-unit"), ("tier", "SSSS")]:
            output = self.output()
            output["changes"][0][key] = value
            with self.assertRaises(ValueError):
                self.analyzer.validate(output, self.packet, self.comments)

    def test_order_requires_competitor_evidence_and_same_tier(self):
        self.publish_fixture([{"unit_id": "gyutaro", "tier": "GOOD_GROUND"}])
        output = self.output(before="gyutaro")
        with self.assertRaises(ValueError):
            self.analyzer.validate(output, self.packet, self.comments)
        output["changes"][0]["evidence"] = output["changes"][0]["evidence"][:1]
        with self.assertRaises(ValueError):
            self.analyzer.validate(output, self.packet, self.comments)

    def test_single_comment_or_server_cannot_take_over_the_meta(self):
        output = self.output()
        output["changes"][0]["supporting_comments"] = ["c0", "c0", "c0"]
        with self.assertRaises(ValueError):
            self.analyzer.validate(output, self.packet, self.comments)
        output = self.output()
        output["changes"][0]["supporting_comments"] = ["c0"]
        ranking, explanations, details = self.analyzer.validate(
            output, self.packet, self.comments
        )
        self.store.create_proposal(
            ranking,
            explanations,
            details=details,
            source_version="test-only",
            model="test",
            comments=self.comments,
        )
        self.assertEqual(self.store.latest()["id"], 0)
        self.assertIsNotNone(self.store.active_proposal())

    def test_low_confidence_and_boolean_confidence_are_rejected(self):
        for value in (0.4, True, float("nan")):
            output = self.output()
            output["changes"][0]["confidence"] = value
            with self.assertRaises(ValueError):
                self.analyzer.validate(output, self.packet, self.comments)

    def test_response_cannot_request_other_actions_or_duplicate_units(self):
        output = self.output()
        output["shell"] = "delete database"
        with self.assertRaises(ValueError):
            self.analyzer.validate(output, self.packet, self.comments)
        output = self.output()
        output["changes"] *= 2
        with self.assertRaises(ValueError):
            self.analyzer.validate(output, self.packet, self.comments)

    def test_detailed_explanations_only_exist_for_meta_units(self):
        ranking, explanations, details = self.analyzer.validate(
            self.output(tier="GOOD_SUPPORT"), self.packet, self.comments
        )
        self.assertEqual(explanations, {})
        self.store.publish(
            ranking,
            explanations,
            source_version="test",
            model="test",
            comments=self.comments,
            change_details=details,
        )
        self.assertEqual(self.store.history(), [])

    def test_leaving_meta_keeps_a_detailed_change_log(self):
        self.publish_fixture([{"unit_id": "daki", "tier": "META_HILL"}])
        ranking, explanations, details = self.analyzer.validate(
            self.output(tier="GOOD_GROUND"), self.packet, self.comments
        )
        self.store.publish(
            ranking,
            explanations,
            source_version="test",
            model="test",
            comments=self.comments,
            change_details=details,
        )
        self.assertIn(
            "Saiu do Meta para Good Ground", self.store.history()[0]["reason"]
        )
        self.assertNotIn("daki", self.store.latest()["explanations"])

    def test_packet_fits_the_free_model_limit_and_omits_discord_identifiers(self):
        raw = json.dumps(self.packet, ensure_ascii=False, separators=(",", ":"))
        self.assertLessEqual(len(SYSTEM.encode()) + len(raw.encode()), MAX_INPUT_BYTES)
        self.assertNotIn("user_id", raw)
        self.assertNotIn("message_id", raw)
        self.assertNotIn("guild_id", raw)
        self.assertNotIn("user0", raw)
        self.assertNotIn("message0", raw)

    def test_installed_guild_and_unit_context_are_required_before_collection(self):
        self.assertFalse(
            self.store.ingest(
                "x", "stranger", "999", "101", "Daki tem uma mecânica.", {"daki"}
            )
        )
        self.assertFalse(
            self.store.ingest(
                "x", "user0", "100", "999", "Daki tem uma mecânica.", set()
            )
        )
        self.assertTrue(
            self.store.ingest(
                "x",
                "stranger",
                "100",
                "999",
                "Daki tem uma nova mecânica neste exemplo.",
                {"daki"},
            )
        )

    def test_duplicate_event_and_hourly_spam_are_bounded(self):
        self.assertFalse(
            self.store.ingest(
                "message0", "user0", "100", "101", "Daki tem uma mecânica.", {"daki"}
            )
        )
        for i in range(20):
            self.store.ingest(
                str(i),
                "user0",
                "100",
                "101",
                f"Daki tem uma mecânica. teste{i} teste{i}",
                {"daki"},
            )
        self.assertEqual(
            self.store.connection.execute(
                "SELECT COUNT(*) FROM tier_comments WHERE user_id='user0'"
            ).fetchone()[0],
            10,
        )

    def test_comments_expire_and_consent_withdrawal_erases_text(self):
        self.store.withdraw("user0")
        self.assertEqual(len(self.store.recent()), 2)
        self.now += 8 * 86400
        self.store.cleanup()
        self.assertEqual(self.store.recent(), [])

    def test_published_rank_and_settings_survive_restart(self):
        self.publish_fixture([{"unit_id": "daki", "tier": "META_HILL"}])
        self.store.set_interval(60)
        self.store.close()
        self.store = TierStore(self.root / "tierlist.sqlite3", clock=lambda: self.now)
        self.assertEqual(self.store.latest()["ranking"][0]["unit_id"], "daki")
        self.assertEqual(self.store.interval(), 3600)
        self.assertTrue(self.store.consented("user0"))

    def test_snapshot_contains_the_new_tier_schema(self):
        snapshot_database(
            self.store.path,
            self.root / "backup.sqlite3",
            required_tables=REQUIRED_TABLES,
        )
        self.assertTrue((self.root / "backup.sqlite3").exists())

    def test_updates_need_a_distinct_channel_and_survive_restart(self):
        with self.assertRaises(ValueError):
            self.store.set_update_channel("100", "102")
        self.store.remember_panel("100", "101", "900", 0)
        self.assertEqual(self.store.update_channels(), [])
        with self.assertRaises(ValueError):
            self.store.set_update_channel("100", "101")
        self.store.set_update_channel("100", "102")
        self.store.close()
        self.store = TierStore(self.root / "tierlist.sqlite3", clock=lambda: self.now)
        self.assertEqual(self.store.update_channels()[0]["channel_id"], "102")
        self.assertFalse(self.store.is_update_channel("200", "102"))

    def test_history_ui_has_no_invitation_to_old_commands(self):
        self.publish_fixture([{"unit_id": "daki", "tier": "META_HILL"}])
        embed = log_embed(self.store, self.catalog)
        raw = json.dumps(embed.to_dict())
        self.assertNotIn("/avaliar", raw)
        self.assertNotIn("alcance", raw)
        self.assertIn("Wiki", raw)


class ImageCase(unittest.TestCase):
    def test_reference_rows_and_unfilled_layout(self):
        blob = render([])
        with Image.open(io.BytesIO(blob)) as image:
            self.assertEqual(image.height, 6 * 96)
            self.assertEqual(image.getpixel((4, 4)), (146, 7, 0))
            self.assertEqual(image.getpixel((4, 100)), (93, 70, 0))
        self.assertEqual(
            TIERS,
            (
                "META_HILL",
                "META_GROUND",
                "META_SUPPORT",
                "GOOD_HILL",
                "GOOD_GROUND",
                "GOOD_SUPPORT",
            ),
        )

    def test_row_expands_when_characters_exceed_one_line(self):
        rows = [{"unit_id": "absent" + str(i), "tier": "META_HILL"} for i in range(11)]
        with Image.open(io.BytesIO(render(rows, media={}))) as image:
            self.assertEqual(image.height, 7 * 96)

    def test_left_to_right_order_is_preserved_in_composition(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "assets").mkdir()
            Image.new("RGBA", (88, 88), "red").save(root / "assets/a.png")
            Image.new("RGBA", (88, 88), "blue").save(root / "assets/b.png")
            media = {k: {"path": f"assets/{k}.png"} for k in ("a", "b")}
            with patch("tier_image.ROOT", root):
                blob = render(
                    [
                        {"unit_id": "a", "tier": "META_HILL"},
                        {"unit_id": "b", "tier": "META_HILL"},
                    ],
                    media=media,
                )
            with Image.open(io.BytesIO(blob)) as image:
                self.assertEqual(image.getpixel((180, 48)), (255, 0, 0))
                self.assertEqual(image.getpixel((276, 48)), (0, 0, 255))


class BackendCase(unittest.IsolatedAsyncioTestCase):
    def response(self, status=200, result=None):
        payload = {
            "choices": [
                {"message": {"content": json.dumps(result or {"changes": []})}}
            ],
            "usage": {"total_tokens": 100},
        }
        response = SimpleNamespace(
            status=status,
            content=SimpleNamespace(
                read=AsyncMock(side_effect=[json.dumps(payload).encode(), b""])
            ),
        )

        class Context:
            async def __aenter__(self):
                return response

            async def __aexit__(self, *args):
                return False

        class Session:
            def __init__(self):
                self.post_args = None

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            def post(self, *args, **kwargs):
                self.post_args = (args, kwargs)
                return Context()

        session = Session()
        return session, lambda **kw: session

    async def test_backend_uses_fixed_endpoint_and_json_only_without_tools(self):
        session, factory = self.response()
        backend = GroqBackend(api_key="test-key-not-a-secret", session_factory=factory)
        result, usage = await backend.analyze({"comments": {}})
        args, kwargs = session.post_args
        self.assertEqual(args[0], "https://api.groq.com/openai/v1/chat/completions")
        self.assertEqual(kwargs["json"]["response_format"], {"type": "json_object"})
        self.assertNotIn("tools", kwargs["json"])
        self.assertEqual(result, {"changes": []})
        self.assertEqual(usage, 100)

    async def test_fragmented_provider_json_is_read_to_completion(self):
        session, factory = self.response()
        raw = json.dumps(
            {
                "choices": [{"message": {"content": '{"changes":[]}'}}],
                "usage": {"total_tokens": 100},
            }
        ).encode()

        class FragmentedContext:
            async def __aenter__(self):
                return SimpleNamespace(
                    status=200,
                    content=SimpleNamespace(
                        read=AsyncMock(
                            side_effect=[raw[:15], raw[15:40], raw[40:], b""]
                        )
                    ),
                )

            async def __aexit__(self, *args):
                return False

        session.post = lambda *a, **k: FragmentedContext()
        backend = GroqBackend(api_key="test-key", session_factory=factory)
        output, usage = await backend.analyze({})
        self.assertEqual(output, {"changes": []})
        self.assertEqual(usage, 100)

    async def test_provider_quota_is_a_stop_without_model_fallback(self):
        session, factory = self.response(status=429)
        backend = GroqBackend(api_key="test-key", session_factory=factory)
        with self.assertRaises(QuotaReached):
            await backend.analyze({})

    async def test_key_missing_does_not_connect(self):
        backend = GroqBackend(api_key="")
        with self.assertRaises(AnalysisUnavailable):
            await backend.analyze({})

    async def test_oversized_request_is_rejected_before_network(self):
        session, factory = self.response()
        backend = GroqBackend(api_key="test-key", session_factory=factory)
        with self.assertRaises(AnalysisUnavailable):
            await backend.analyze({"body": "x" * 10000})
        self.assertIsNone(session.post_args)


class PollCase(unittest.IsolatedAsyncioTestCase):
    output = TierCase.output
    asyncTearDown = TierCase.asyncTearDown

    async def asyncSetUp(self):
        await TierCase.asyncSetUp(self)
        ranking, explanations, details = self.analyzer.validate(
            self.output(), self.packet, self.comments
        )
        self.store.create_proposal(
            ranking,
            explanations,
            details=details,
            source_version=self.evidence.version,
            model="test",
            comments=self.comments,
        )
        self.proposal = self.store.active_proposal()
        self.store.remember_poll(self.proposal["id"], "100", "101", "999")
        self.store.remember_poll(self.proposal["id"], "200", "201", "888")
        self.proposal = self.store.active_proposal()

    # Poll tests use the shared fixture, not the inherited inference tests.
    def cast(self, choices):
        for i, choice in enumerate(choices):
            self.store.vote(
                self.proposal["id"], "v" + str(i), "100", "101", "999", choice
            )

    def resolve(self):
        self.now = self.proposal["closes_at"] + 1
        return self.store.resolve_due(source_version=self.evidence.version)

    def test_one_vote_across_servers_can_be_changed(self):
        self.store.vote(self.proposal["id"], "same", "100", "101", "999", "approve")
        self.store.vote(self.proposal["id"], "same", "200", "201", "888", "keep")
        self.assertEqual(
            self.store.poll_counts(self.proposal["id"]),
            {"approve": 0, "keep": 1, "test": 0},
        )

    def test_revision_number_alone_does_not_reopen_rejected_evidence(self):
        self.cast(["keep"] * 5)
        self.resolve()
        self.now += 3600
        detail = json.loads(json.dumps(self.proposal["details"]))
        detail["daki"]["sources"][0]["url"] = (
            "https://animeadventures.fandom.com/wiki/daki?oldid=99"
        )
        self.assertFalse(
            self.store.create_proposal(
                self.proposal["ranking"],
                self.proposal["explanations"],
                details=detail,
                source_version="new-revision-same-content",
                model="test",
                comments=[],
            )
        )
        detail["daki"]["sources"][0]["quote"] += (
            " Novas condições verificadas neste exemplo."
        )
        self.assertTrue(
            self.store.create_proposal(
                self.proposal["ranking"],
                self.proposal["explanations"],
                details=detail,
                source_version="new-evidence",
                model="test",
                comments=[],
            )
        )

    def test_legacy_schema_migration_preserves_running_deadline_and_vote(self):
        self.store.vote(self.proposal["id"], "same", "100", "101", "999", "keep")
        self.store.connection.execute(
            "ALTER TABLE tier_proposals DROP COLUMN opened_at"
        )
        self.store.connection.commit()
        self.store.close()
        self.now += 120
        self.store = TierStore(self.root / "tierlist.sqlite3", clock=lambda: self.now)
        running = self.store.active_proposal()
        self.assertEqual(running["opened_at"], self.proposal["created_at"])
        self.assertEqual(running["closes_at"], self.proposal["closes_at"])
        self.assertEqual(self.store.poll_counts(running["id"])["keep"], 1)

    def test_vote_is_bound_to_the_recorded_message_and_guild(self):
        with self.assertRaises(ValueError):
            self.store.vote(self.proposal["id"], "v", "100", "201", "888", "approve")

    def test_removed_poll_copy_cannot_accept_a_vote(self):
        self.store.remember_poll(self.proposal["id"], "100", "101", "999", "removed")
        with self.assertRaises(ValueError):
            self.store.vote(self.proposal["id"], "v", "100", "101", "999", "approve")

    def test_channel_cannot_be_changed_while_its_poll_is_open(self):
        self.store.remember_panel("100", "103", "900", 0)
        with self.assertRaises(ValueError):
            self.store.set_update_channel("100", "104")
        self.resolve()
        self.store.set_update_channel("100", "104")
        self.assertEqual(self.store.update_channels()[0]["channel_id"], "104")

    def test_late_votes_do_not_count_even_before_the_next_scheduler_tick(self):
        self.now = self.proposal["closes_at"]
        with self.assertRaises(ValueError):
            self.store.vote(self.proposal["id"], "v", "100", "101", "999", "approve")

    def test_approval_applies_at_ten_minutes_and_only_once(self):
        self.cast(["approve"] * 5)
        self.assertEqual(self.store.latest()["id"], 0)
        self.assertTrue(self.resolve())
        first = self.store.latest()
        self.assertFalse(self.store.resolve_due(source_version=self.evidence.version))
        self.assertEqual(self.store.latest(), first)
        self.assertEqual(self.store.proposal(self.proposal["id"])["status"], "approved")

    def test_few_votes_keep_ranking_unchanged(self):
        self.cast(["approve"] * 4)
        self.assertFalse(self.resolve())
        self.assertEqual(self.store.latest()["id"], 0)
        self.assertEqual(
            self.store.proposal(self.proposal["id"])["status"], "not-enough-votes"
        )

    def test_simple_majority_below_two_thirds_does_not_change_rank(self):
        self.cast(["approve"] * 3 + ["keep"] * 2)
        self.assertFalse(self.resolve())
        self.assertEqual(
            self.store.proposal(self.proposal["id"])["status"], "maintained"
        )

    def test_more_tests_option_prevents_approval(self):
        self.cast(["approve"] + ["test"] * 4)
        self.assertFalse(self.resolve())
        self.assertEqual(
            self.store.proposal(self.proposal["id"])["status"], "needs-tests"
        )

    def test_next_poll_cannot_start_until_fifty_minutes_after_this_close(self):
        self.cast(["approve"] * 5)
        self.resolve()
        self.assertFalse(self.store.may_propose())
        self.now = self.proposal["created_at"] + 3600
        self.assertTrue(self.store.may_propose())

    def test_source_update_invalidates_an_old_proposal(self):
        self.cast(["approve"] * 5)
        self.now += 601
        self.assertFalse(
            self.store.resolve_due(source_version="different-wiki-version")
        )
        self.assertEqual(self.store.latest()["id"], 0)
        self.assertEqual(self.store.proposal(self.proposal["id"])["status"], "outdated")

    def test_restart_restores_deadline_and_global_votes(self):
        self.cast(["approve"] * 5)
        self.store.close()
        self.store = TierStore(self.root / "tierlist.sqlite3", clock=lambda: self.now)
        self.assertEqual(
            self.store.active_proposal()["closes_at"], self.proposal["closes_at"]
        )
        self.assertTrue(self.resolve())

    def test_votes_become_context_without_training_or_disclosing_voter_ids(self):
        self.cast(["test"] * 5)
        self.resolve()
        raw = json.dumps(self.store.decisions())
        self.assertIn("needs-tests", raw)
        self.assertNotIn("v0", raw)
        self.assertNotIn("user_id", raw)


class ApprovalAtomicityCase(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = PollCase.asyncSetUp
    asyncTearDown = PollCase.asyncTearDown
    output = TierCase.output
    cast = PollCase.cast
    resolve = PollCase.resolve

    # Reuse the realistic proposal setup, then focus on the crash boundary.
    def test_failed_publication_rolls_back_poll_resolution(self):
        import sqlite3

        self.cast(["approve"] * 5)
        self.store.connection.execute(
            "CREATE TRIGGER fail_publish BEFORE INSERT ON tier_publications BEGIN SELECT RAISE(ABORT,'test failure'); END"
        )
        with self.assertRaises(sqlite3.DatabaseError):
            self.resolve()
        self.assertEqual(self.store.proposal(self.proposal["id"])["status"], "open")
        self.assertEqual(self.store.latest()["id"], 0)
        self.store.connection.execute("DROP TRIGGER fail_publish")
        self.assertTrue(self.store.resolve_due(source_version=self.evidence.version))
