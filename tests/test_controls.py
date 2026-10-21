import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord
import bot as app
import quiz_ui as screen
from test_session import Channel, Deck, Message, until, user, view_text


def interaction(session, actor=None, message=None):
    return SimpleNamespace(
        channel=session.channel, channel_id=session.channel.id, guild=object(),
        user=actor or session.host, message=message or session.control_message,
        app_permissions=SimpleNamespace(view_channel=True, send_messages=True, embed_links=True),
        response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock()),
    )


class ControlTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.patches = [patch.object(app, 'QUESTION_TIME', .15), patch.object(app, 'BETWEEN_QUESTIONS', .02),
                        patch.object(app, 'COUNTDOWN_INTERVAL', .04), patch.object(app, 'LOBBY_TIMEOUT', 60),
                        patch.object(app.bot, 'scores', Mock(points=Mock(return_value=17), award=Mock(return_value=18)))]
        for p in self.patches:
            p.start()
        self.sessions = []

    async def asyncTearDown(self):
        sessions = self.sessions + list(app.active_sessions.values())
        tasks = []
        for session in sessions:
            for task in (session.runner, session.lobby_timer, session.ticker):
                if task:
                    task.cancel()
                    tasks.append(task)
            if session.control_view:
                session.control_view.stop()
        await asyncio.gather(*tasks, return_exceptions=True)
        app.active_sessions.clear()
        for p in self.patches:
            p.stop()

    async def lobby(self):
        session = app.QuizSession(Channel(), user(), app.bot.scores, deck=Deck())
        self.sessions.append(session)
        app.active_sessions[session.channel.id] = session
        await session.open_lobby()
        return session

    async def playing(self):
        session = await self.lobby()
        session.launch()
        await until(lambda: session.question_message is not None)
        return session

    async def test_slash_opens_lobby_and_button_starts_questions(self):
        seed = app.QuizSession(Channel(), user(), app.bot.scores)
        event = interaction(seed)
        await app.adventures.callback(event)
        session = app.active_sessions[seed.channel.id]
        self.sessions.append(session)
        self.assertEqual(session.phase, 'lobby')
        self.assertIsNone(session.question_message)
        self.assertIn('Sua próxima aventura', view_text(session.control_view))
        start = next(item for item in session.control_view.walk_children() if getattr(item, 'custom_id', '') == 'aa:start')
        await start.callback(interaction(session))
        await until(lambda: session.question_message is not None)
        self.assertEqual(session.phase, 'question')

    async def test_host_can_choose_scope_and_time_before_starting(self):
        session = await self.lobby()
        await app.handle_control(interaction(session), 'category', 'worlds')
        await app.handle_control(interaction(session), 'time', '60')
        self.assertEqual(session.question_time, 60)
        self.assertTrue(all(q.category in {'Mundos', 'Chefes', 'Atos'} for q in session.selected_questions()))
        self.assertIn('60s', view_text(session.control_view))
        self.assertIsNone(session.question_message)
        await app.handle_control(interaction(session), 'start')
        await until(lambda: session.question_message is not None)
        self.assertTrue(all(q.category in {'Mundos', 'Chefes', 'Atos'} for q in session.deck.questions))
        self.assertGreater(session.deadline - session.clock(), 59)

    async def test_other_player_cannot_change_options_or_start(self):
        session = await self.lobby()
        for action, value in [('category', 'worlds'), ('time', '60'), ('start', None)]:
            event = interaction(session, user(99))
            await app.handle_control(event, action, value)
            self.assertTrue(event.response.send_message.call_args.kwargs['ephemeral'])
        self.assertEqual(session.group, 'all')
        self.assertEqual(session.question_time, .15)
        self.assertIsNone(session.runner)

    async def test_invalid_menu_value_does_not_change_settings(self):
        session = await self.lobby()
        for action, value in [('category', 'update_1'), ('time', '0'), ('time', '999')]:
            await app.handle_control(interaction(session), action, value)
        self.assertEqual(session.group, 'all')
        self.assertEqual(session.question_time, .15)

    async def test_concurrent_start_clicks_launch_one_runner(self):
        session = await self.lobby()
        await asyncio.gather(app.handle_control(interaction(session), 'start'), app.handle_control(interaction(session), 'start'))
        runner = session.runner
        await until(lambda: session.question_message is not None)
        self.assertIs(session.runner, runner)
        self.assertEqual(session.question_number, 1)

    async def test_stale_panel_cannot_pause_current_question(self):
        session = await self.lobby()
        old = session.control_message
        session.launch()
        await until(lambda: session.question_message is not None)
        event = interaction(session, message=old)
        await app.handle_control(event, 'pause')
        self.assertFalse(session.pause_requested)
        self.assertIn('painel', event.response.send_message.call_args.args[0])

    async def test_pause_waits_for_answer_then_resume_preserves_progress(self):
        session = await self.playing()
        remaining = session.deadline
        await app.handle_control(interaction(session), 'pause')
        self.assertEqual(session.phase, 'question')
        self.assertEqual(session.deadline, remaining)
        self.assertTrue(session.pause_requested)
        session.submit(Message(session.channel, content='50'))
        await until(lambda: session.phase == 'paused' and session.control_message is not session.question_message)
        await asyncio.sleep(.04)
        self.assertEqual(session.question_number, 1)
        self.assertEqual(session.correct_count, 1)
        self.assertIn('Aventura em pausa', view_text(session.control_view))
        await app.handle_control(interaction(session), 'resume')
        await until(lambda: session.question_number == 2)
        self.assertEqual(session.correct_count, 1)

    async def test_requested_pause_can_be_cancelled_before_round_ends(self):
        session = await self.playing()
        await app.handle_control(interaction(session), 'pause')
        await app.handle_control(interaction(session), 'pause')
        self.assertFalse(session.pause_requested)
        session.submit(Message(session.channel, content='50'))
        await until(lambda: session.question_number == 2)

    async def test_stop_during_question_preserves_the_claimed_point(self):
        session = await self.playing()
        await app.handle_control(interaction(session), 'stop')
        self.assertTrue(session.running)
        self.assertTrue(session.stop_requested)
        self.assertTrue(session.submit(Message(session.channel, content='50')))
        await session.runner
        self.assertEqual(session.correct_count, 1)
        self.assertEqual(session.question_number, 1)
        app.bot.scores.award.assert_called_once()
        self.assertIn('Encerrada pelo anfitrião', view_text(session.control_view))
        self.assertNotIn(session.channel.id, app.active_sessions)

    async def test_paused_session_can_be_ended_without_starting_another_round(self):
        session = await self.playing()
        await app.handle_control(interaction(session), 'pause')
        session.submit(Message(session.channel, content='50'))
        await until(lambda: session.phase == 'paused' and session.control_message is not session.question_message)
        await app.handle_control(interaction(session), 'stop')
        await asyncio.sleep(.03)
        self.assertFalse(session.running)
        self.assertEqual(session.question_number, 1)
        self.assertNotIn(session.channel.id, app.active_sessions)

    async def test_failed_stop_acknowledgement_still_cleans_up_paused_session(self):
        session = await self.playing()
        await app.handle_control(interaction(session), 'pause')
        session.submit(Message(session.channel, content='50'))
        await until(lambda: session.phase == 'paused' and session.control_message is not session.question_message)
        event = interaction(session)
        event.response.defer.side_effect = discord.HTTPException(SimpleNamespace(status=500, reason='error'), 'temporary')
        with self.assertRaises(discord.HTTPException):
            await app.handle_control(event, 'stop')
        self.assertFalse(session.running)
        self.assertTrue(session.runner.done())
        self.assertNotIn(session.channel.id, app.active_sessions)

    async def test_moderator_can_end_lobby_but_other_players_cannot(self):
        session = await self.lobby()
        await app.handle_control(interaction(session, user(99)), 'stop')
        self.assertTrue(session.running)
        moderator = user(77)
        moderator.guild_permissions = SimpleNamespace(manage_channels=True)
        await app.handle_control(interaction(session, moderator), 'stop')
        self.assertFalse(session.running)
        self.assertNotIn(session.channel.id, app.active_sessions)

    async def test_help_and_scores_are_private_and_do_not_count_as_attempts(self):
        session = await self.playing()
        for action in ('help', 'scores'):
            event = interaction(session, user(99))
            await app.handle_control(event, action)
            payload = event.response.send_message.call_args.kwargs
            self.assertTrue(payload['ephemeral'])
            self.assertIsInstance(payload['view'], discord.ui.LayoutView)
        self.assertFalse(session.had_participation)
        await session.runner
        self.assertFalse(session.running)
        app.bot.scores.award.assert_not_called()

    async def test_expired_lobby_releases_channel_and_edits_in_place(self):
        with patch.object(app, 'LOBBY_TIMEOUT', .02):
            session = await self.lobby()
            await session.lobby_timer
        self.assertEqual(len(session.channel.sent), 1)
        self.assertFalse(session.running)
        self.assertIn('não foi iniciada', view_text(session.control_view))
        self.assertNotIn(session.channel.id, app.active_sessions)

    async def test_panel_from_before_restart_offers_help_and_explains_stale_actions(self):
        seed = app.QuizSession(Channel(), user(), app.bot.scores)
        event = interaction(seed)
        await app.handle_control(event, 'start')
        self.assertIn('concluído', event.response.send_message.call_args.args[0])
        await app.handle_control(event, 'help')
        self.assertIn('Seu guia', view_text(event.response.send_message.call_args.kwargs['view']))
        controls = screen.PersistentControls(app.handle_control)
        self.assertTrue(controls.is_persistent())

    async def test_replay_uses_existing_panel_if_a_session_already_exists(self):
        session = await self.lobby()
        event = interaction(session)
        await app.handle_control(event, 'replay')
        self.assertIs(app.active_sessions[session.channel.id], session)
        self.assertIn('Já existe', event.response.send_message.call_args.args[0])

    async def test_replay_opens_a_new_lobby_when_channel_is_free(self):
        seed = app.QuizSession(Channel(), user(), app.bot.scores)
        event = interaction(seed)
        await app.handle_control(event, 'replay')
        session = app.active_sessions[seed.channel.id]
        self.sessions.append(session)
        self.assertEqual(session.phase, 'lobby')
        self.assertIs(session.host, event.user)

    async def test_private_score_without_live_session_omits_fabricated_session_total(self):
        seed = app.QuizSession(Channel(), user(), app.bot.scores)
        event = interaction(seed)
        await app.handle_control(event, 'scores')
        content = view_text(event.response.send_message.call_args.kwargs['view'])
        self.assertIn('17 pontos acumulados', content)
        self.assertNotIn('pontos nesta sessão', content)

    async def test_pause_requested_during_intermission_does_not_lose_resume_signal(self):
        session = await self.playing()
        session.submit(Message(session.channel, content='50'))
        await until(lambda: session.phase == 'intermission' and session.control_message is not session.question_message)
        await app.handle_control(interaction(session), 'pause')
        await app.handle_control(interaction(session), 'resume')
        await until(lambda: session.question_number == 2)
        self.assertEqual(session.correct_count, 1)

    async def test_all_lobby_options_and_end_states_have_valid_native_payloads(self):
        session = await self.lobby()
        panels = [screen.help_panel(), screen.ended_panel(session, 'Fim', app.handle_control)]
        for group in screen.GROUPS:
            session.group = group
            for seconds in (30, 45, 60):
                session.question_time = seconds
                panels.append(screen.lobby_panel(session, app.handle_control))
        for panel in panels:
            self.assertLessEqual(panel.total_children_count, 40)
            self.assertLessEqual(panel.content_length(), 4000)
            self.assertTrue(panel.has_components_v2())
            private_payload = discord.http.handle_message_parameters(view=panel, flags=discord.MessageFlags(ephemeral=True)).payload
            self.assertEqual(private_payload['flags'], 32768 | 64)
            ids = [x.custom_id for x in panel.walk_children() if getattr(x, 'custom_id', None)]
            self.assertEqual(len(ids), len(set(ids)))
            for x in panel.walk_children():
                if isinstance(x, discord.ui.ActionRow):
                    self.assertLessEqual(len(x.children), 5)
        for name in ['**fake** @everyone', '\u202eevil', 'Ágata 👑']:
            formatted = screen.safe_name(name)
            self.assertNotIn('\u202e', formatted)
            self.assertNotIn('@everyone', formatted)
