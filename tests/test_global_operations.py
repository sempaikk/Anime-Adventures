"""Operational journeys, scoped moderation, fair delivery and game-only presentation."""

import asyncio
import io
import unittest
from types import SimpleNamespace

from PIL import Image
import test_global_chat as fixtures
from global_reports import ReportInbox, ReportDecision
from global_ops import GlobalOperations, OperationsView, NetworkPause
from global_policy import check_links
from global_views import MyMessagesView, GlobalAdminView
from runtime_health import RuntimeHealth
from bot_style import GameTheme, GAME_KEYS
from bot_style import ICONS
from bot_ui import payload, visible_text


class OperationsCase(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.ChatCase.asyncSetUp
    asyncTearDown = fixtures.ChatCase.asyncTearDown
    fetch = fixtures.ChatCase.fetch
    history = fixtures.ChatCase.history
    send_notice = fixtures.ChatCase.send_notice
    message = fixtures.ChatCase.message
    interaction = fixtures.ChatCase.interaction
    copies = fixtures.ChatCase.copies
    flush = fixtures.ChatCase.flush
    asset = fixtures.ChatCase.asset

    async def test_global_admin_controls_separate_personal_local_and_owner_actions(
        self,
    ):
        for user in (7, 8):
            with self.subTest(user=user):
                view = GlobalAdminView(
                    self.app, self.interaction(user=user, admin=True)
                )
                if user == 7:
                    self.engine.store.restrict(
                        "*", "guild", 1, 600, 7, "Contenção temporária de teste"
                    )
                    self.engine.store.pause_network(
                        True, 7, "Pausa temporária para conferir a tela completa"
                    )
                card = payload(bot=self.app, content=view.description(), view=view)[
                    "view"
                ]
                text = visible_text(card)
                self.assertIn('Server connection', text)
                self.assertIn('Server moderation', text)
                self.assertIn('Your participation', text)
                self.assertEqual("Operations · bot owner" in text, user == 7)
                self.assertEqual("Network moderation · bot owner" in text, user == 7)
                self.assertLessEqual(card.total_children_count, 40)
                self.assertEqual(view.personal.row, 2)
                if user == 7:
                    self.assertEqual(view.network.row, 3)
                    self.assertEqual(view.operations.row, 4)

    async def reported(self, guild=2):
        source = self.message(content="Uma mensagem compartilhada para revisão")
        await self.engine.ingest(source)
        await self.flush()
        self.engine.store.report(
            source.id, 8, guild, "Este conteúdo precisa de uma revisão cuidadosa."
        )
        return source, self.engine.store.report_page(guild)[0][0]

    async def test_local_report_review_cannot_reach_another_guild(self):
        source, row = await self.reported()
        with self.assertRaises(ValueError):
            self.engine.store.review_report(
                row["id"], 3, 9, 0, "remove", "Tentativa em outro servidor"
            )
        self.assertFalse(self.engine.store.message(source.id)["deleted"])
        self.assertEqual(
            self.engine.store.report_record(row["id"], 2)["status"], "pending"
        )

    async def test_local_removal_preserves_original_and_copies_in_other_servers(self):
        source, row = await self.reported()
        self.engine.store.review_report(
            row["id"], 2, 9, 0, "remove", "Remoção local confirmada pelo moderador"
        )
        await self.flush()
        self.assertEqual({m.channel.id for m in self.copies(source)}, {30})
        self.assertFalse(self.engine.store.message(source.id)["deleted"])
        source.content = "Editada depois da remoção local"
        await self.engine.ingest(source)
        await self.flush()
        self.assertEqual({m.channel.id for m in self.copies(source)}, {30})
        source.delete.assert_not_awaited()

    async def test_network_review_removes_copies_and_preserves_the_human_original(self):
        source, row = await self.reported()
        self.engine.store.review_report(
            row["id"], None, 7, 0, "remove", "Remoção confirmada na rede inteira"
        )
        await self.flush()
        self.assertFalse(self.copies(source))
        self.assertIn(source.id, self.messages)
        source.delete.assert_not_awaited()

    async def test_local_removal_recovers_a_lost_ack_before_deleting_only_that_copy(
        self,
    ):
        source = self.message()
        self.hooks[120].lose_ack = True
        await self.engine.ingest(source)
        await self.flush()
        self.engine.store.report(source.id, 8, 2, "Remover a cópia após revisão local")
        row = self.engine.store.report_page(2)[0][0]
        self.engine.store.review_report(
            row["id"], 2, 9, 0, "remove", "Remoção local com confirmação pendente"
        )
        await self.flush()
        await self.flush()
        self.assertEqual({m.channel.id for m in self.copies(source)}, {30})
        self.assertEqual(len(self.hooks[120].calls), 1)
        self.assertEqual(self.engine.store.delivery(source.id, 20)["state"], "deleted")

    async def test_local_report_removal_during_post_cleans_up_the_returned_receipt(
        self,
    ):
        source = self.message()
        await self.engine.ingest(source)
        self.engine.store.report(source.id, 8, 2, "Remover a cópia após revisão local")
        row = self.engine.store.report_page(2)[0][0]
        send = self.hooks[120].send

        async def during_post(*args, **kwargs):
            self.engine.store.review_report(
                row["id"],
                2,
                9,
                0,
                "remove",
                "Remoção local enquanto a entrega estava em curso",
            )
            return await send(*args, **kwargs)

        self.hooks[120].send = during_post
        await self.flush()
        await self.flush()
        self.assertEqual({m.channel.id for m in self.copies(source)}, {30})
        self.assertEqual(self.engine.store.delivery(source.id, 20)["state"], "deleted")

    async def test_report_decisions_are_versioned_and_reopenable(self):
        _, row = await self.reported()
        self.engine.store.review_report(
            row["id"], 2, 9, 0, "dismiss", "Motivo não confirmado após revisão"
        )
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.engine.store.review_report(
                row["id"], 2, 9, 0, "resolve", "Um segundo envio do formulário"
            )
        self.engine.store.review_report(
            row["id"], 2, 9, 1, "reopen", "Há uma nova informação para revisar"
        )
        record = self.engine.store.report_record(row["id"], 2)
        self.assertEqual((record["status"], record["version"]), ("pending", 2))

    async def test_hour_block_expires_and_only_applies_to_the_reviewing_server(self):
        _, row = await self.reported()
        self.engine.store.review_report(
            row["id"], 2, 9, 0, "block-hour", "Bloqueio temporário durante apuração"
        )
        self.assertTrue(self.engine.store.blocked(7, 2))
        self.assertFalse(self.engine.store.blocked(7, 3))
        self.now[0] += 3601
        self.assertFalse(self.engine.store.blocked(7, 2))

    async def test_report_excerpt_requires_access_to_the_channel_and_its_history(self):
        source, _ = await self.reported()
        view = ReportInbox(self.app, self.interaction(gid=2, admin=True))
        permissions = self.channels[20].permissions_for.return_value
        self.assertIn(source.content, view.description())
        permissions.read_message_history = False
        self.assertNotIn(source.content, view.description())
        permissions.read_message_history = True
        permissions.view_channel = False
        self.assertNotIn(source.content, view.description())

    async def test_report_inbox_has_pages_filters_and_no_private_content_for_other_people(
        self,
    ):
        source, row = await self.reported()
        for n in range(9):
            self.engine.store.report(
                source.id, 100 + n, 2, "Outra denúncia válida para revisar"
            )
        i = self.interaction(gid=2, admin=True)
        view = ReportInbox(self.app, i)
        self.assertEqual((view.total, len(view.rows)), (10, 5))
        await view.next.callback(i)
        self.assertEqual(view.page, 1)
        self.assertFalse(
            await view.interaction_check(self.interaction(gid=2, user=9, admin=True))
        )
        self.assertLess(
            len(
                visible_text(
                    payload(bot=self.app, content=view.description(), view=view)["view"]
                ).encode("utf-16-le")
            )
            // 2,
            4000,
        )
        self.assertEqual(self.engine.store.report_page(3)[1], 0)

    async def test_regular_administrator_cannot_forge_a_network_review_modal(self):
        _, row = await self.reported()
        i = self.interaction(gid=2, user=9, admin=True)
        modal = ReportDecision(self.app, i, row, None)
        modal.action._values = ["remove"]
        modal.reason._value = "Tentativa de atingir todos os servidores"
        with self.assertRaises(ValueError):
            await modal.on_submit(i)
        self.assertEqual(
            self.engine.store.report_record(row["id"], 2)["status"], "pending"
        )

    async def test_eight_accounts_repeating_invites_causes_only_temporary_containment(
        self,
    ):
        for uid in range(100, 108):
            author = SimpleNamespace(**{**vars(self.author), "id": uid})
            self.engine.store.consent(uid)
            await self.engine.ingest(
                self.message(
                    content='Repeated invitation discord.gg/example', author=author
                )
            )
        self.assertTrue(self.engine.store.restriction(7, 1))
        self.assertFalse(self.engine.store.rows("SELECT * FROM global_blocks"))
        self.now[0] += 601
        self.assertFalse(self.engine.store.restriction(7, 1))
        await self.engine.ingest(
            self.message(content="Conversa normal depois da contenção")
        )
        self.assertIsNotNone(self.engine.store.message(self.counter))

    async def test_repeated_short_greetings_are_not_treated_as_a_coordinated_attack(
        self,
    ):
        for uid in range(100, 110):
            author = SimpleNamespace(**{**vars(self.author), "id": uid})
            self.engine.store.consent(uid)
            await self.engine.ingest(self.message(content="oi", author=author))
        self.assertFalse(self.engine.store.restriction(7, 1))

    async def test_disguised_links_are_rejected_but_ordinary_links_and_invites_work(
        self,
    ):
        check_links(
            "[Wiki](https://animeadventures.fandom.com/wiki/Units) discord.gg/example"
        )
        for body in (
            "[https://discord.com/login](https://evil.example/login)",
            "[abrir](javascript:alert(1))",
        ):
            with self.assertRaises(ValueError):
                check_links(body)
        source = self.message(
            content="[https://discord.com/login](https://evil.example/login)"
        )
        await self.engine.ingest(source)
        self.assertIsNone(self.engine.store.message(source.id))
        source.reply.assert_not_awaited()
        source.delete.assert_not_awaited()

    async def test_network_pause_stops_new_posts_and_resume_does_not_import_pause_messages(
        self,
    ):
        first = self.message()
        await self.engine.ingest(first)
        self.engine.store.pause_network(
            True, 7, "Pausa de emergência para verificar a rede"
        )
        await self.flush()
        self.assertFalse(self.copies(first))
        paused = self.message(content="Mensagem escrita durante a pausa")
        await self.engine.ingest(paused)
        self.now[0] += 1
        self.engine.store.pause_network(
            False, 7, "Retomada confirmada após conferência"
        )
        await self.engine.ingest(paused, recovery=True)
        self.assertIsNone(self.engine.store.message(paused.id))
        fresh = self.message(content="Mensagem nova depois da retomada")
        await self.engine.ingest(fresh)
        await self.flush()
        self.assertEqual(len(self.copies(fresh)), 2)

    async def test_network_pause_preserves_requested_deletions(self):
        source = self.message()
        await self.engine.ingest(source)
        await self.flush()
        self.engine.store.erase(source.id)
        self.engine.store.pause_network(
            True, 7, "Pausa durante uma remoção já solicitada"
        )
        await self.flush()
        self.assertFalse(self.copies(source))

    async def test_fair_queue_rotates_between_destinations(self):
        source = self.message()
        await self.engine.ingest(source)
        a = self.engine.store.jobs(limit=1)[0]
        b = self.engine.store.jobs(limit=1)[0]
        self.assertNotEqual(a["channel_id"], b["channel_id"])

    async def test_a_slow_webhook_does_not_block_the_other_destination(self):
        source = self.message()
        await self.engine.ingest(source)
        release, fast = asyncio.Event(), asyncio.Event()
        slow_send = self.hooks[120].send
        fast_send = self.hooks[130].send

        async def delayed(*args, **kwargs):
            await release.wait()
            return await slow_send(*args, **kwargs)

        async def quick(*args, **kwargs):
            result = await fast_send(*args, **kwargs)
            fast.set()
            return result

        self.hooks[120].send = delayed
        self.hooks[130].send = quick
        task = asyncio.create_task(self.engine.cycle())
        try:
            await asyncio.wait_for(fast.wait(), 2)
            self.assertFalse(task.done())
        finally:
            release.set()
            await task
        self.assertEqual(len(self.copies(source)), 2)

    async def test_stale_worker_changes_readiness_and_intentional_pause_remains_healthy(
        self,
    ):
        health = RuntimeHealth(lambda: True, lambda: self.base.connection)
        health.add_probe("chat", self.engine.ready)
        self.assertTrue(health.services_ready())
        self.now[0] += 241
        self.assertFalse(health.services_ready())
        self.engine.store.pause_network(True, 7, "Pausa intencional pelo dono do bot")
        self.assertTrue(health.services_ready())

    async def test_owner_alerts_wait_for_sustained_failure_and_do_not_spam(self):
        self.app.owner_ids_set = {7}
        self.app.get_user = lambda uid: self.author
        self.app.health.storage_level = "critical"
        for delta in (0, 119, 1, 30):
            self.now[0] += delta
            self.engine.last_cycle = self.now[0]
            await self.engine.operations.check_alerts()
        self.author.send.assert_awaited_once()
        self.engine.operations = GlobalOperations(self.engine)
        await self.engine.operations.check_alerts()
        self.assertEqual(self.author.send.await_count, 1)
        self.app.health.storage_level = "ok"
        await self.engine.operations.check_alerts()
        await self.engine.operations.check_alerts()
        self.assertEqual(self.author.send.await_count, 1)
        self.now[0] += 120
        self.engine.last_cycle = self.now[0]
        await self.engine.operations.check_alerts()
        self.assertEqual(self.author.send.await_count, 2)

    async def test_owner_can_disable_alerts_and_regular_administrators_cannot_open_status_controls(
        self,
    ):
        self.app.owner_ids_set = {7}
        self.app.get_user = lambda uid: self.author
        self.base.set("global-owner-alerts", "0")
        self.app.health.storage_level = "critical"
        await self.engine.operations.check_alerts()
        self.now[0] += 180
        await self.engine.operations.check_alerts()
        self.author.send.assert_not_awaited()
        i = self.interaction(user=8, admin=True)
        view = OperationsView(self.app, i)
        self.assertFalse(await view.interaction_check(i))

    async def test_failed_owner_dm_does_not_create_a_false_recovery_notification(self):
        self.app.owner_ids_set = {7}
        self.app.get_user = lambda uid: self.author
        self.author.send.side_effect = fixtures.missing()
        self.app.health.storage_level = "critical"
        await self.engine.operations.check_alerts()
        self.now[0] += 121
        self.engine.last_cycle = self.now[0]
        await self.engine.operations.check_alerts()
        self.assertEqual(self.author.send.await_count, 1)
        self.app.health.storage_level = "ok"
        await self.engine.operations.check_alerts()
        self.assertEqual(self.author.send.await_count, 1)

    async def test_pause_form_revalidates_owner_and_rejects_stale_state(self):
        i = self.interaction(admin=True)
        modal = NetworkPause(self.app, i)
        modal.reason._value = "Uma pausa de manutenção confirmada"
        self.engine.store.pause_network(True, 7, "Outra sessão pausou a rede primeiro")
        with self.assertRaisesRegex(ValueError, 'changed'):
            await modal.on_submit(i)

    async def test_local_pause_rechecks_newer_configuration_after_acknowledging(self):
        i = self.interaction(admin=True)
        view = GlobalAdminView(self.app, i)

        async def changed(**kwargs):
            self.engine.store.active(i.guild_id, False)

        i.response.defer.side_effect = changed
        with self.assertRaisesRegex(ValueError, 'settings changed'):
            await view.toggle.callback(i)
        self.assertFalse(self.engine.store.channel(i.guild_id)['active'])

    async def test_personal_sent_messages_have_private_navigation(self):
        for n in range(8):
            self.now[0] += 11
            await self.engine.ingest(self.message(content=f"Envio pessoal {n}"))
        i = self.interaction()
        view = MyMessagesView(self.app, i)
        self.assertIn("Envio pessoal 7", view.description())
        await view.next.callback(i)
        self.assertEqual(view.page, 1)
        self.assertIn("Envio pessoal 0", view.description())
        self.assertNotIn("Envio pessoal 7", view.description())
        self.assertFalse(await view.interaction_check(self.interaction(user=8)))

    async def test_only_the_private_status_icon_is_registered(self):
        theme=GameTheme()
        theme.available=set(ICONS)
        self.assertEqual(GAME_KEYS,{'clock'})
        self.assertEqual(theme.icon('clock').id,int(ICONS['clock']['id']))


    async def test_game_icon_appears_only_once_in_bot_status_and_nowhere_in_other_menus(self):
        from global_views import GlobalMemberView, GlobalDirectView, ConsentView
        from bot_ui import component_dicts

        self.app.ui_theme = GameTheme()
        self.app.ui_theme.available = set(ICONS)
        i = self.interaction(admin=True)
        views = [
            GlobalAdminView(self.app, i), GlobalMemberView(self.app, i),
            GlobalDirectView(self.app), ConsentView(self.app, i, self.engine.store.channel(i.guild_id)),
            MyMessagesView(self.app, i), OperationsView(self.app, i),
        ]
        for view in views:
            with self.subTest(view=type(view).__name__):
                card = payload(bot=self.app, content='## Controls\n\nFirst section\n\nSecond section', view=view)['view']
                components = list(component_dicts(card))
                thumbnails = [part for part in components if part.get('type') == 11]
                self.assertEqual(len(thumbnails), 1 if isinstance(view, OperationsView) else 0)
                self.assertFalse(any(part.get('emoji') for part in components))
                if thumbnails:
                    self.assertIn(ICONS['clock']['id'], thumbnails[0]['media']['url'])

    async def test_embedded_sections_do_not_add_decorative_game_icons(self):
        self.app.ui_theme = GameTheme()
        self.app.ui_theme.available = set(ICONS)
        embed = __import__('discord').Embed(title='Status')
        embed.set_footer(text='Proposta #123')
        embed.add_field(name='Prazo', value='In ten minutes')
        embed.add_field(name='O que muda', value='A configuration change')
        card = payload(bot=self.app, embed=embed)['view']
        from bot_ui import component_dicts

        self.assertFalse(any(part.get('type') == 11 for part in component_dicts(card)))
        self.assertNotIn('<:', visible_text(card))


    async def test_local_review_cannot_claim_to_remove_the_original(self):
        source, row = await self.reported(guild=1)
        with self.assertRaisesRegex(ValueError, "original"):
            self.engine.store.review_report(
                row["id"], 1, 9, 0, "remove", "Uma tentativa de remover a original"
            )
        self.assertIn(source.id, self.messages)
        self.assertEqual(
            self.engine.store.report_record(row["id"], 1)["status"], "pending"
        )

    async def test_rapid_edits_are_bounded_and_recover_after_the_window(self):
        source = self.message()
        await self.engine.ingest(source)
        await self.flush()
        for n in range(20):
            source.content = f"Uma edição rápida número {n}"
            await self.engine.ingest(source)
        self.assertLessEqual(self.engine.store.message(source.id)["revision"], 13)
        self.now[0] += 11
        await self.engine.ingest(source, recovery=True)
        await self.flush()
        self.assertTrue(all(m.content == source.content for m in self.copies(source)))

    async def test_code_examples_with_link_syntax_remain_ordinary_code(self):
        check_links("Exemplo: `[x](javascript:example)`")
        check_links("```\n[https://discord.com](https://other.example)\n```")

    async def test_expired_report_actions_are_pruned_with_the_report(self):
        _, row = await self.reported()
        self.engine.store.review_report(
            row["id"], 2, 9, 0, "resolve", "Encerrada após revisão do moderador"
        )
        self.now[0] += 30 * 86400 + 1
        self.engine.store.cleanup()
        self.assertFalse(self.engine.store.rows("SELECT * FROM global_report_actions"))

    async def test_readonly_preflight_does_not_open_a_network_or_modify_state(self):
        from scripts.check_release import check_release
        from bot_release import manifest
        import json
        from pathlib import Path

        root = Path(self.temp.name) / "release"
        (root / "data").mkdir(parents=True)
        (root / "requirements.txt").write_text("")
        (root / "data/build.json").write_text(json.dumps(manifest("test", root)))
        before = self.base.path.read_bytes()
        result = check_release(root, self.base.path.parent)
        self.assertTrue(result["passed"])
        self.assertFalse(result["network_used"])
        self.assertFalse(result["credentials_read"])
        self.assertEqual(before, self.base.path.read_bytes())
        (root / "requirements.txt").write_text("tampered")
        self.assertFalse(check_release(root, self.base.path.parent)["passed"])
