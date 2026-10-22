"""Private administrative records and safe removal of their old public copies."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import unittest

import discord

import test_tier_thread as runtime
from tier_audit import hide_audit_messages
from tier_ui import visible_text


class PrivateAuditCase(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = runtime.ThreadRuntimeCase.asyncSetUp
    asyncTearDown = runtime.ThreadRuntimeCase.asyncTearDown
    interaction = runtime.ThreadRuntimeCase.interaction
    setup_panel = runtime.ThreadRuntimeCase.setup_panel

    async def notice(
        self, *, kind="wiki-baseline", channel=None, receipt=True, legacy=False
    ):
        channel = channel or self.env.thread
        with self.app.store.connection:
            ident = self.app.store.audit(
                kind, "system", "Registro administrativo artificial do teste."
            )
        embed = discord.Embed(
            title="Revisão da comunidade", description="Registro artificial, sem votos."
        )
        embed.set_footer(text=f"Revisão #{ident} · 22/10/2026")
        message = await self.app.deliver(
            channel, f"audit:{ident}:{channel.id}", embed=embed
        )
        if legacy:
            message.components = []
            message.embeds = [embed]
        if receipt:
            with self.app.store.connection:
                self.app.store.connection.execute(
                    "INSERT INTO tier_audit_messages VALUES(?,?,?)",
                    (ident, "1", str(message.id)),
                )
        return ident, message

    async def cleanup(self):
        await hide_audit_messages(self.app, self.app.store.panels()[0], self.env.thread)

    async def test_cleanup_removes_native_and_legacy_copies_but_preserves_internal_history(
        self,
    ):
        await self.setup_panel()
        _, native = await self.notice()
        _, legacy = await self.notice(kind="rollback", legacy=True)
        community = await self.app.deliver(
            self.env.thread,
            "poll-history:test",
            content="Proposta #1 · decisão da comunidade",
        )
        with self.app.store.connection:
            self.app.store.audit(
                "portrait-restored", 7, "Outro registro interno, nunca publicado."
            )
        before = self.app.store.board()
        await self.app.panel_loop.coro(self.app)
        sent = len(self.env.payloads)
        await self.app.panel_loop.coro(self.app)
        self.assertFalse(native.exists)
        self.assertFalse(legacy.exists)
        self.assertTrue(community.exists)
        self.assertEqual(len(self.env.payloads), sent)
        self.assertEqual(self.app.store.board(), before)
        self.assertEqual(len(self.app.store.rows("SELECT * FROM tier_audit")), 3)
        self.assertEqual(self.app.store.rows("SELECT * FROM tier_audit_messages"), [])
        self.assertFalse(
            self.app.store.rows(
                "SELECT * FROM tier_deliveries WHERE key LIKE 'audit:%'"
            )
        )
        index = self.env.partial(
            self.env.thread, int(self.app.store.thread(1)["intro_id"])
        )
        self.assertNotIn("Última revisão", visible_text(index))

    async def test_failed_delete_retries_without_discarding_the_receipt(self):
        await self.setup_panel()
        _, message = await self.notice()
        denied = discord.Forbidden(
            SimpleNamespace(status=403, reason="Forbidden"),
            {"code": 50013, "message": "Missing Permissions"},
        )
        for error in (denied, TimeoutError()):
            with patch.object(message, "delete", side_effect=error):
                await self.cleanup()
            self.assertTrue(message.exists)
            self.assertEqual(
                len(self.app.store.rows("SELECT * FROM tier_audit_messages")), 1
            )
        await self.cleanup()
        self.assertFalse(message.exists)
        self.assertEqual(len(self.app.store.rows("SELECT * FROM tier_audit")), 1)

    async def test_missing_message_can_clear_only_its_public_receipt(self):
        await self.setup_panel()
        _, message = await self.notice()
        message.exists = False
        await self.cleanup()
        message.delete.assert_not_awaited()
        self.assertFalse(self.app.store.rows("SELECT * FROM tier_audit_messages"))
        self.assertEqual(len(self.app.store.rows("SELECT * FROM tier_audit")), 1)

    async def test_author_and_marker_must_both_match_before_deletion(self):
        await self.setup_panel()
        _, foreign = await self.notice()
        _, unrelated = await self.notice()
        foreign.author = SimpleNamespace(id=7)
        unrelated.components = []
        unrelated.embeds = [discord.Embed(title="Proposta da comunidade")]
        await self.cleanup()
        foreign.delete.assert_not_awaited()
        unrelated.delete.assert_not_awaited()
        self.assertEqual(
            len(self.app.store.rows("SELECT * FROM tier_audit_messages")), 2
        )

    async def test_orphan_delivery_in_previous_topic_is_removed_without_touching_another_guild(
        self,
    ):
        await self.setup_panel()
        old = MagicMock(spec=discord.Thread)
        old.id, old.guild = 999, self.env.guild
        old.get_partial_message.side_effect = lambda ident: self.env.partial(old, ident)

        async def fetch(ident):
            return await self.env.partial(old, ident).fetch()

        old.fetch_message = AsyncMock(side_effect=fetch)
        self.env.channels[old.id] = old
        self.app.store.set("previous-thread:1", str(old.id))
        _, message = await self.notice(channel=old, receipt=False)
        old.guild = SimpleNamespace(id=2)
        await self.cleanup()
        message.delete.assert_not_awaited()
        old.guild = self.env.guild
        await self.cleanup()
        self.assertFalse(message.exists)
        self.assertEqual(len(self.app.store.rows("SELECT * FROM tier_audit")), 1)
