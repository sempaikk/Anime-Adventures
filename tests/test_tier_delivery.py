from tier_ui import visible_text, component_dicts
from tier_test_ui import call_text

"""Member journeys and failure recovery for visible, temporary poll notices."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord

import test_tier_thread as runtime
from tier_delivery import PUBLIC_RESULT_SECONDS
from tier_image import poll_embed
from tier_store import TierStore
from tier_views import PollView


class VisiblePollCase(unittest.IsolatedAsyncioTestCase):
    asyncTearDown = runtime.ThreadRuntimeCase.asyncTearDown
    interaction = runtime.ThreadRuntimeCase.interaction
    setup_panel = runtime.ThreadRuntimeCase.setup_panel
    propose = runtime.ThreadRuntimeCase.propose

    async def asyncSetUp(self):
        await runtime.ThreadRuntimeCase.asyncSetUp(self)
        await self.setup_panel()
        self.panel = self.app.store.panels()[0]

    def receipt(self, channel):
        rows = self.app.store.rows(
            "SELECT * FROM tier_poll_messages WHERE channel_id=? ORDER BY proposal_id DESC LIMIT 1",
            (str(channel.id),),
        )
        return rows[0] if rows else None

    def message(self, channel):
        receipt = self.receipt(channel)
        return self.env.partial(channel, int(receipt["message_id"]))

    async def open(self):
        proposal = self.propose()
        await self.app.poll_loop.coro(self.app)
        return self.app.store.proposal(proposal["id"])

    async def finish(self, *, count=5, choice="approve"):
        proposal = await self.open()
        receipt = self.receipt(self.env.channel)
        for user in range(8, 8 + count):
            self.app.store.vote(
                proposal["id"],
                user,
                1,
                receipt["channel_id"],
                receipt["message_id"],
                choice,
            )
        self.now += 600
        await self.app.poll_loop.coro(self.app)
        return self.app.store.proposal(proposal["id"])

    async def test_member_votes_in_main_channel_and_sees_private_confirmation_and_deadline(
        self,
    ):
        proposal = await self.open()
        notice = self.message(self.env.channel)
        i = self.interaction(admin=False, user=8, channel=self.env.channel)
        i.message = notice
        await PollView(self.app).cast(i, "approve")
        response = i.response.send_message.await_args
        self.assertTrue(response.kwargs["ephemeral"])
        self.assertIn(f"<t:{int(proposal['closes_at'])}:R>", call_text(response))
        self.assertEqual(self.app.store.poll_counts(proposal["id"])["approve"], 1)
        self.assertIsNone(self.receipt(self.env.thread))

    async def test_poll_has_direct_links_to_image_and_history_without_pings(self):
        await self.open()
        payload = self.env.payloads[-1][1]
        links = [item for item in component_dicts(payload) if item.get("url")]
        self.assertEqual(
            {item["label"] for item in links}, {"Ver tier list", "Histórico"}
        )
        self.assertTrue(
            any(item["url"].endswith("/" + self.panel["message_id"]) for item in links)
        )
        self.assertEqual(payload["allowed_mentions"]["parse"], [])

    async def test_thread_index_links_to_actual_visible_poll(self):
        await self.open()
        await self.app.panel_loop.coro(self.app)
        index = self.env.partial(
            self.env.thread, int(self.app.store.thread(1)["intro_id"])
        )
        receipt = self.receipt(self.env.channel)
        self.assertIn(f"/1/10/{receipt['message_id']}", visible_text(index))
        self.assertIn("Enquete atual", visible_text(index))

    async def test_concurrent_publication_creates_one_notice_and_one_deadline(self):
        self.propose()
        await asyncio.gather(*(self.app._poll_cycle() for _ in range(24)))
        self.assertEqual(len(self.app.store.poll_messages()), 1)
        self.assertEqual(len([p for cid, p in self.env.payloads if cid == 10]), 2)
        self.assertEqual(self.app.store.active_proposal()["closes_at"], self.now + 600)

    async def test_result_saved_before_notice_removed_and_image_identity_preserved(
        self,
    ):
        proposal = await self.finish()
        notice, archive = self.message(self.env.channel), self.message(self.env.thread)
        self.assertEqual(proposal["status"], "approved")
        self.assertTrue(notice.exists and archive.exists)
        self.assertIn("**Aprovar:** 5", visible_text(archive))
        votes = [
            c
            for c in component_dicts(archive)
            if c.get("custom_id") in {"tier:v3:approve", "tier:v3:keep", "tier:v3:test"}
        ]
        self.assertTrue(all(c["disabled"] for c in votes))
        self.now += PUBLIC_RESULT_SECONDS - 1
        await self.app.poll_loop.coro(self.app)
        self.assertTrue(notice.exists)
        self.now += 1
        await self.app.poll_loop.coro(self.app)
        self.assertFalse(notice.exists)
        self.assertTrue(archive.exists)
        self.assertEqual(self.receipt(self.env.channel)["status"], "removed")
        self.assertTrue(
            self.env.partial(self.env.channel, int(self.panel["message_id"])).exists
        )
        self.assertEqual(self.app.store.poll_counts(proposal["id"])["approve"], 5)

    async def test_no_votes_still_leave_a_result_without_moving_positions(self):
        proposal = await self.finish(count=0)
        self.assertEqual(proposal["status"], "not-enough-votes")
        self.assertIn(
            "participação insuficiente",
            visible_text(self.message(self.env.thread)),
        )
        self.assertEqual(self.app.store.latest()["ranking"], [])

    async def test_keep_and_more_tests_do_not_move_positions(self):
        for choice, expected in (("keep", "maintained"), ("test", "needs-tests")):
            with self.subTest(choice=choice):
                proposal = await self.finish(choice=choice)
                self.assertEqual(proposal["status"], expected)
                self.assertEqual(self.app.store.latest()["ranking"], [])
                self.now += 86401

    async def test_archive_failure_retains_disabled_notice_then_recovers(self):
        await self.open()
        deliver = self.app.deliver

        async def unavailable(channel, key, **kwargs):
            if key.startswith("poll-history:"):
                raise TimeoutError("simulated history outage")
            return await deliver(channel, key, **kwargs)

        self.now += 600
        with patch.object(self.app, "deliver", side_effect=unavailable):
            await self.app.poll_loop.coro(self.app)
            self.now += 181
            await self.app.poll_loop.coro(self.app)
        notice = self.message(self.env.channel)
        self.assertTrue(notice.exists)
        self.assertIsNone(self.receipt(self.env.thread))
        self.assertEqual(self.app.store.public_results_waiting(), 1)
        self.assertIn(
            "aguardando arquivo ou limpeza",
            self.app.server_status(self.interaction(user=8)),
        )
        await self.app.poll_loop.coro(self.app)
        self.assertTrue(self.message(self.env.thread).exists)
        self.assertFalse(notice.exists)
        self.assertEqual(self.app.store.public_results_waiting(), 0)

    async def test_lost_archive_ack_does_not_duplicate_result_or_reset_cleanup_time(
        self,
    ):
        await self.open()
        self.now += 600
        self.env.fail_after_send = True
        await self.app.poll_loop.coro(self.app)
        closed_at = self.receipt(self.env.channel)["updated_at"]
        self.assertIsNone(self.receipt(self.env.thread))
        self.now += PUBLIC_RESULT_SECONDS
        await self.app.poll_loop.coro(self.app)
        self.assertEqual(self.receipt(self.env.channel)["updated_at"], closed_at)
        archived = [
            p
            for cid, p in self.env.payloads
            if cid == self.env.thread.id and "Proposta #" in visible_text(p)
        ]
        self.assertEqual(len(archived), 1)
        self.assertTrue(self.message(self.env.thread).exists)
        self.assertFalse(self.message(self.env.channel).exists)

    async def test_restart_resumes_cleanup_without_republishing_or_losing_votes(self):
        proposal = await self.finish()
        sent = len(self.env.payloads)
        path = self.app.store.path
        self.app.store.close()
        self.app.store = TierStore(path, clock=lambda: self.now)
        self.app.analyzer.store = self.app.media.store = self.app.store
        self.now += PUBLIC_RESULT_SECONDS
        await self.app.poll_loop.coro(self.app)
        self.assertEqual(len(self.env.payloads), sent)
        self.assertFalse(self.message(self.env.channel).exists)
        self.assertTrue(self.message(self.env.thread).exists)
        self.assertEqual(self.app.store.poll_counts(proposal["id"])["approve"], 5)

    async def test_delete_failure_keeps_result_and_retries_without_duplicate_archive(
        self,
    ):
        await self.finish()
        notice = self.message(self.env.channel)
        forbidden = discord.Forbidden(
            SimpleNamespace(status=403, reason="Forbidden"),
            {"code": 50013, "message": "Missing Permissions"},
        )
        notice.delete.side_effect = forbidden
        sent = len(self.env.payloads)
        self.now += PUBLIC_RESULT_SECONDS
        await self.app.poll_loop.coro(self.app)
        self.assertTrue(notice.exists and self.message(self.env.thread).exists)
        self.assertNotEqual(self.receipt(self.env.channel)["status"], "removed")
        notice.delete.side_effect = notice._delete
        await self.app.poll_loop.coro(self.app)
        self.assertFalse(notice.exists)
        self.assertEqual(len(self.env.payloads), sent)

    async def test_disappeared_archive_blocks_cleanup_instead_of_losing_both_copies(
        self,
    ):
        await self.finish()
        await self.message(self.env.thread).delete()
        self.now += PUBLIC_RESULT_SECONDS
        await self.app.poll_loop.coro(self.app)
        self.assertTrue(self.message(self.env.channel).exists)
        self.assertEqual(self.receipt(self.env.thread)["status"], "removed")

    async def test_moderator_removed_archive_is_respected_and_main_result_retained(
        self,
    ):
        await self.finish()
        archive = self.message(self.env.thread)
        await archive.delete()
        await self.app.on_raw_message_delete(SimpleNamespace(message_id=archive.id))
        sent = len(self.env.payloads)
        self.now += PUBLIC_RESULT_SECONDS
        await self.app.poll_loop.coro(self.app)
        self.assertTrue(self.message(self.env.channel).exists)
        self.assertEqual(len(self.env.payloads), sent)

    async def test_unrelated_archive_or_notice_cannot_trigger_deleting_a_message(self):
        await self.finish()
        notice = self.message(self.env.channel)
        archive = self.message(self.env.thread)
        self.now += PUBLIC_RESULT_SECONDS
        for target in (notice, archive):
            with self.subTest(message=target.id):
                old = target.author
                target.author = SimpleNamespace(id=999)
                await self.app.poll_loop.coro(self.app)
                self.assertTrue(notice.exists)
                notice.delete.assert_not_awaited()
                target.author = old

    async def test_deleted_active_notice_is_not_reposted_and_cannot_apply_fake_approval(
        self,
    ):
        proposal = await self.open()
        receipt = self.receipt(self.env.channel)
        for user in range(5):
            self.app.store.vote(
                proposal["id"], user, 1, 10, receipt["message_id"], "approve"
            )
        notice = self.message(self.env.channel)
        await notice.delete()
        await self.app.on_raw_message_delete(SimpleNamespace(message_id=notice.id))
        self.now += 600
        await self.app.poll_loop.coro(self.app)
        self.assertEqual(
            self.app.store.proposal(proposal["id"])["status"], "unavailable"
        )
        self.assertEqual(self.app.store.latest()["ranking"], [])
        self.assertTrue(self.message(self.env.thread).exists)

    async def test_legacy_open_thread_poll_finishes_in_place_with_original_deadline(
        self,
    ):
        proposal = self.propose()
        message = await self.app.deliver(
            self.env.thread,
            "legacy-simulation",
            embed=poll_embed(self.app.store, self.app.catalog, proposal),
            view=PollView(self.app),
        )
        self.app.store.remember_poll(proposal["id"], 1, self.env.thread.id, message.id)
        deadline = self.app.store.active_proposal()["closes_at"]
        await self.app.poll_loop.coro(self.app)
        self.assertIsNone(self.receipt(self.env.channel))
        self.assertEqual(self.app.store.active_proposal()["closes_at"], deadline)
        self.now += 600 + PUBLIC_RESULT_SECONDS
        await self.app.poll_loop.coro(self.app)
        self.assertTrue(message.exists)
        self.assertIn("participação insuficiente", visible_text(message))

    async def test_archived_result_cannot_accept_votes_but_can_be_reported(self):
        proposal = await self.finish()
        i = self.interaction(admin=False, user=8, channel=self.env.thread)
        i.response.send_modal = AsyncMock()
        i.message = self.message(self.env.thread)
        with self.assertRaisesRegex(ValueError, "terminou"):
            await PollView(self.app).cast(i, "keep")
        await PollView(self.app).report.callback(i)
        i.response.send_modal.assert_awaited_once()
        self.assertEqual(self.app.store.poll_counts(proposal["id"])["approve"], 5)

    async def test_late_server_does_not_receive_poll_with_less_than_a_minute_left(self):
        proposal = self.propose()
        self.app.store.remember_poll(proposal["id"], 2, 20, 999)
        self.now += 541
        sent = len(self.env.payloads)
        await self.app.poll_loop.coro(self.app)
        self.assertIsNone(self.receipt(self.env.channel))
        self.assertEqual(len(self.env.payloads), sent)

    async def test_countdown_and_poll_delivery_do_not_make_extra_model_calls(self):
        await self.finish()
        self.now += PUBLIC_RESULT_SECONDS
        await self.app.poll_loop.coro(self.app)
        await self.app.panel_loop.coro(self.app)
        self.backend.analyze.assert_not_awaited()

    async def test_offline_deleted_notice_is_checked_before_applying_five_votes(self):
        proposal = await self.open()
        receipt = self.receipt(self.env.channel)
        for user in range(5):
            self.app.store.vote(
                proposal["id"], user, 1, 10, receipt["message_id"], "approve"
            )
        await self.message(self.env.channel).delete()
        self.now += 600  # No gateway event: the bot was disconnected.
        await self.app.poll_loop.coro(self.app)
        self.assertEqual(
            self.app.store.proposal(proposal["id"])["status"], "unavailable"
        )
        self.assertEqual(self.app.store.latest()["ranking"], [])

    async def test_uncertain_api_at_deadline_defers_decision_without_renewing_deadline(
        self,
    ):
        proposal = await self.open()
        self.now += 600
        with patch.object(self.env.channel, "fetch_message", side_effect=TimeoutError):
            await self.app.poll_loop.coro(self.app)
        current = self.app.store.proposal(proposal["id"])
        self.assertEqual(current["status"], "open")
        self.assertEqual(current["closes_at"], proposal["closes_at"])
        self.assertEqual(self.app.store.latest()["ranking"], [])
        await self.app.poll_loop.coro(self.app)
        self.assertEqual(
            self.app.store.proposal(proposal["id"])["status"], "not-enough-votes"
        )

    async def test_record_pointing_to_unrelated_message_does_not_confirm_publication(
        self,
    ):
        proposal = await self.open()
        notice = self.message(self.env.channel)
        notice.embeds = []
        notice.components = []
        self.now += 600
        await self.app.poll_loop.coro(self.app)
        self.assertEqual(
            self.app.store.proposal(proposal["id"])["status"], "unavailable"
        )
        notice.delete.assert_not_awaited()

    async def test_index_with_open_vote_previous_approval_revision_and_all_links_fits_discord(
        self,
    ):
        await self.finish()
        self.app.store.rollback(
            self.app.store.latest()["id"],
            7,
            "Revisão artificial para verificar todos os atalhos simultâneos.",
        )
        await self.app.panel_loop.coro(self.app)
        self.now += 86401
        await self.open()
        self.app.store.set("previous-thread:1", "9999999999999999999")
        self.app.health.storage_level = "critical"
        await self.app.panel_loop.coro(self.app)
        index = self.env.partial(
            self.env.thread, int(self.app.store.thread(1)["intro_id"])
        )
        self.assertIn("Última revisão", visible_text(index))
        self.assertIn("Última votação aprovada", visible_text(index))
        self.assertIn("abrir votação", visible_text(index))
        self.assertIn("Histórico do tópico anterior", visible_text(index))
        self.assertLessEqual(len(visible_text(index).encode("utf-16-le")) // 2, 2000)

    async def test_legacy_archive_must_receive_final_status_before_main_notice_is_removed(
        self,
    ):
        await self.finish()
        archive = self.message(self.env.thread)
        with self.app.store.connection:
            self.app.store.connection.execute(
                "UPDATE tier_poll_messages SET status='open' WHERE channel_id=?",
                (str(self.env.thread.id),),
            )
        self.now += PUBLIC_RESULT_SECONDS
        with patch.object(archive, "edit", side_effect=TimeoutError):
            await self.app.poll_loop.coro(self.app)
        self.assertTrue(self.message(self.env.channel).exists)
        await self.app.poll_loop.coro(self.app)
        await self.app.poll_loop.coro(self.app)
        self.assertFalse(self.message(self.env.channel).exists)
