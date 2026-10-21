import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord
from scores import AwardResult

import bot as app
import quiz_ui as screen
from test_session import Channel, Deck, IDS, Message, until, user, view_text


def interaction(session, actor=None, message=None):
    return SimpleNamespace(
        id=next(IDS), channel=session.channel, channel_id=session.channel.id, guild=object(),
        user=actor or session.host, message=message or session.control_message,
        app_permissions=SimpleNamespace(view_channel=True, send_messages=True, embed_links=True),
        response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock()),
    )


class ControlTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        app.click_limits.clear()
        self.patches = [patch.object(app, 'QUESTION_TIME', .15), patch.object(app, 'BETWEEN_QUESTIONS', .02),
                        patch.object(app, 'COUNTDOWN_INTERVAL', .04), patch.object(app, 'LOBBY_TIMEOUT', 60),
                        patch.object(app.bot, 'scores', Mock(points=Mock(return_value=17), credit=Mock(return_value=AwardResult(18, True))))]
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
        app.click_limits.clear()
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
        self.assertIn('Preparar partida', view_text(session.control_view))
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
        self.assertFalse(session.is_paused)
        self.assertIn('painel', event.response.send_message.call_args.args[0])

    async def test_old_panel_cannot_pause_a_question_still_being_published(self):
        session = await self.lobby()
        old = session.control_message
        original_send = session.channel.send
        publishing = asyncio.Event()
        release = asyncio.Event()

        async def slow_send(*args, **kwargs):
            publishing.set()
            await release.wait()
            return await original_send(*args, **kwargs)

        session.channel.send = slow_send
        session.launch()
        await publishing.wait()
        try:
            event = interaction(session, message=old)
            await app.handle_control(event, 'pause')
            self.assertFalse(session.is_paused)
            self.assertIn('painel', event.response.send_message.call_args.args[0])
        finally:
            release.set()
        await until(lambda: session.question_message is not None)
        self.assertEqual(session.phase, 'question')
        self.assertFalse(session.is_paused)

    async def test_pause_freezes_current_question_and_resume_preserves_remaining_time(self):
        session = await self.playing()
        deadline = session.deadline
        await app.handle_control(interaction(session), 'pause')
        self.assertEqual(session.phase, 'paused_question')
        self.assertIsNone(session.deadline)
        frozen = session.remaining_seconds
        await asyncio.sleep(.18)
        self.assertEqual(session.remaining_seconds, frozen)
        self.assertFalse(session.answer_future.done())
        self.assertFalse(session.submit(Message(session.channel, content='50')))
        self.assertFalse(session.had_participation)
        self.assertIn('Tempo congelado', view_text(session.control_view))
        self.assertNotIn('<t:', view_text(session.control_view))
        self.assertTrue(any(getattr(x, 'custom_id', None) == 'aa:resume' for x in session.control_view.walk_children()))
        await app.handle_control(interaction(session), 'resume')
        self.assertEqual(session.phase, 'question')
        self.assertGreater(session.deadline, deadline)
        self.assertLessEqual(session.remaining_seconds, frozen)
        self.assertGreater(session.remaining_seconds, frozen - .02)
        self.assertTrue(session.submit(Message(session.channel, content='50')))
        await until(lambda: session.question_number == 2)
        self.assertEqual(session.correct_count, 1)

    async def test_double_pause_is_idempotent_and_resume_is_an_explicit_action(self):
        session = await self.playing()
        await app.handle_control(interaction(session), 'pause')
        remaining = session.remaining_seconds
        await app.handle_control(interaction(session), 'pause')
        self.assertTrue(session.is_paused)
        self.assertEqual(session.remaining_seconds, remaining)
        await app.handle_control(interaction(session), 'resume')
        self.assertFalse(session.is_paused)
        session.submit(Message(session.channel, content='50'))
        await until(lambda: session.question_number == 2)

    async def test_answers_created_during_pause_are_rejected_after_resume(self):
        session = await self.playing()
        await app.handle_control(interaction(session), 'pause')
        delayed = Message(session.channel, content='50')
        self.assertFalse(session.submit(delayed))
        await app.handle_control(interaction(session), 'resume')
        self.assertFalse(session.submit(delayed))
        self.assertFalse(session.had_participation)
        self.assertTrue(session.submit(Message(session.channel, content='50')))
        await until(lambda: session.correct_count == 1)
        app.bot.scores.credit.assert_called_once()

    async def test_failed_pause_acknowledgement_still_updates_the_frozen_panel(self):
        session = await self.playing()
        event = interaction(session)
        event.response.defer.side_effect = discord.HTTPException(SimpleNamespace(status=500, reason='error'), 'temporary')
        with self.assertRaises(discord.HTTPException):
            await app.handle_control(event, 'pause')
        self.assertTrue(session.is_paused)
        self.assertIn('Tempo congelado', view_text(session.control_view))

    async def test_pause_cannot_steal_an_already_claimed_correct_answer(self):
        session = await self.playing()
        self.assertTrue(session.submit(Message(session.channel, content='50')))
        event = interaction(session)
        await app.handle_control(event, 'pause')
        self.assertFalse(session.is_paused)
        await until(lambda: session.correct_count == 1)
        app.bot.scores.credit.assert_called_once()

    async def test_repeated_pause_recovers_a_failed_panel_edit_without_resetting_time(self):
        session = await self.playing()
        session.control_message.edit_error = discord.HTTPException(SimpleNamespace(status=500, reason='error'), 'temporary')
        with self.assertRaises(discord.HTTPException):
            await app.handle_control(interaction(session), 'pause')
        frozen = session.remaining_seconds
        session.control_message.edit_error = None
        await app.handle_control(interaction(session), 'pause')
        self.assertTrue(session.is_paused)
        self.assertEqual(session.remaining_seconds, frozen)
        self.assertIn('Tempo congelado', view_text(session.control_message.edits[-1]['view']))

    async def test_repeated_resume_recovers_failed_panel_edit_without_extending_time(self):
        session = await self.playing()
        await app.handle_control(interaction(session), 'pause')
        session.control_message.edit_error = discord.HTTPException(SimpleNamespace(status=500, reason='error'), 'temporary')
        with self.assertRaises(discord.HTTPException):
            await app.handle_control(interaction(session), 'resume')
        deadline = session.deadline
        session.control_message.edit_error = None
        await app.handle_control(interaction(session), 'resume')
        self.assertEqual(session.deadline, deadline)
        self.assertFalse(session.is_paused)
        self.assertNotIn('Tempo congelado', view_text(session.control_message.edits[-1]['view']))
        self.assertTrue(any(getattr(item, 'custom_id', None) == 'aa:pause'
                            for item in session.control_message.edits[-1]['view'].walk_children()))

    async def test_intermission_pause_preserves_its_budget_and_does_not_advance(self):
        session = await self.playing()
        session.between_questions = .08
        session.submit(Message(session.channel, content='50'))
        await until(lambda: session.phase == 'intermission' and session.control_message is not session.question_message)
        await app.handle_control(interaction(session), 'pause')
        frozen = session.remaining_seconds
        await asyncio.sleep(.10)
        self.assertEqual(session.question_number, 1)
        self.assertEqual(session.remaining_seconds, frozen)
        self.assertIn('Intervalo congelado', view_text(session.control_view))
        self.assertNotIn('<t:', view_text(session.control_view))
        await app.handle_control(interaction(session), 'resume')
        self.assertGreater(session.remaining_seconds, frozen - .02)
        await until(lambda: session.question_number == 2)

    async def test_lobby_has_a_working_close_button(self):
        session = await self.lobby()
        close = next(item for item in session.control_view.walk_children() if getattr(item, 'custom_id', '') == 'aa:stop')
        await close.callback(interaction(session))
        self.assertFalse(session.running)
        self.assertNotIn(session.channel.id, app.active_sessions)

    async def test_deleting_a_paused_panel_does_not_leave_a_stuck_channel(self):
        session = await self.playing()
        await app.handle_control(interaction(session), 'pause')
        await app.on_raw_message_delete(SimpleNamespace(channel_id=session.channel.id, message_id=session.control_message.id))
        self.assertFalse(session.running)
        self.assertNotIn(session.channel.id, app.active_sessions)
        self.assertTrue(session.runner.done())

    async def test_deleting_panel_after_correct_claim_preserves_the_point(self):
        session = await self.playing()
        self.assertTrue(session.submit(Message(session.channel, content='50')))
        await app.on_raw_message_delete(SimpleNamespace(channel_id=session.channel.id, message_id=session.control_message.id))
        await session.runner
        self.assertEqual(session.correct_count, 1)
        app.bot.scores.credit.assert_called_once()
        self.assertNotIn(session.channel.id, app.active_sessions)

    async def test_bulk_deletion_of_old_messages_cannot_close_a_new_session(self):
        session = await self.lobby()
        await app.on_raw_bulk_message_delete(SimpleNamespace(channel_id=session.channel.id, message_ids={session.control_message.id-1}))
        self.assertTrue(session.running)
        self.assertIs(app.active_sessions[session.channel.id], session)

    async def test_channel_deletion_preserves_an_already_claimed_point(self):
        session = await self.playing()
        self.assertTrue(session.submit(Message(session.channel, content='50')))
        await app.on_guild_channel_delete(session.channel)
        await session.runner
        self.assertEqual(session.correct_count, 1)
        app.bot.scores.credit.assert_called_once()
        self.assertNotIn(session.channel.id, app.active_sessions)

    async def test_stop_during_question_preserves_the_claimed_point(self):
        session = await self.playing()
        await app.handle_control(interaction(session), 'stop')
        self.assertTrue(session.running)
        self.assertTrue(session.stop_requested)
        self.assertTrue(session.submit(Message(session.channel, content='50')))
        await session.runner
        self.assertEqual(session.correct_count, 1)
        self.assertEqual(session.question_number, 1)
        app.bot.scores.credit.assert_called_once()
        self.assertIn('Partida encerrada pelo anfitrião', view_text(session.control_view))
        self.assertNotIn(session.channel.id, app.active_sessions)

    async def test_paused_session_can_be_ended_without_starting_another_round(self):
        session = await self.playing()
        await app.handle_control(interaction(session), 'pause')
        self.assertEqual(session.phase, 'paused_question')
        await app.handle_control(interaction(session), 'stop')
        await asyncio.sleep(.03)
        self.assertFalse(session.running)
        self.assertEqual(session.question_number, 1)
        self.assertNotIn(session.channel.id, app.active_sessions)

    async def test_failed_stop_acknowledgement_still_cleans_up_paused_session(self):
        session = await self.playing()
        await app.handle_control(interaction(session), 'pause')
        self.assertEqual(session.phase, 'paused_question')
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
        app.bot.scores.credit.assert_not_called()

    async def test_expired_lobby_releases_channel_and_edits_in_place(self):
        with patch.object(app, 'LOBBY_TIMEOUT', .02):
            session = await self.lobby()
            await session.lobby_timer
        self.assertEqual(len(session.channel.sent), 1)
        self.assertFalse(session.running)
        self.assertIn('Ninguém iniciou', view_text(session.control_view))
        self.assertNotIn(session.channel.id, app.active_sessions)

    async def test_panel_from_before_restart_offers_help_and_explains_stale_actions(self):
        seed = app.QuizSession(Channel(), user(), app.bot.scores)
        event = interaction(seed)
        await app.handle_control(event, 'start')
        self.assertIn('encerrado', event.response.send_message.call_args.args[0])
        await app.handle_control(event, 'help')
        self.assertIn('Como jogar', view_text(event.response.send_message.call_args.kwargs['view']))
        controls = screen.PersistentControls(app.handle_control)
        self.assertTrue(controls.is_persistent())

    async def test_replay_uses_existing_panel_if_a_session_already_exists(self):
        session = await self.lobby()
        event = interaction(session)
        await app.handle_control(event, 'replay')
        self.assertIs(app.active_sessions[session.channel.id], session)
        self.assertIn('Já tem', event.response.send_message.call_args.args[0])

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
        self.assertIn('Total: 17 pontos', content)
        self.assertNotIn('Nesta partida:', content)

    async def test_pause_during_intermission_does_not_lose_resume_signal(self):
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
            self.assertNotIn('2022', view_text(panel))
            self.assertNotIn('RELEASE', view_text(panel))
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

    async def test_identification_shows_the_image_without_names_in_image_metadata(self):
        session = await self.lobby()
        session.current_question = next(q for q in app.PACK.questions if q.id == 'unit:uraraka')
        session.ends_at = app.datetime.now(app.timezone.utc)
        panel = screen.question_panel(session, app.handle_control, 45)
        self.assertIn('Reconheça a unidade pela imagem', view_text(panel))
        image = next(item for item in panel.walk_children() if isinstance(item, (discord.ui.MediaGallery, discord.ui.Thumbnail)))
        payload = str(image.to_component_dict()).lower()
        for name in ('uraraka', 'gravity hero', 'ochaco', 'ochako'):
            self.assertNotIn(name, payload)

    async def test_missing_portrait_cannot_create_an_anime_riddle(self):
        self.assertFalse(any(q.id == 'unit:deku' for q in app.PACK.questions))
        self.assertTrue(any(q.id == 'rarity:deku' for q in app.PACK.questions))

    async def test_previous_result_does_not_keep_a_past_next_question_timestamp(self):
        session = await self.playing()
        session.between_questions = .05
        session.submit(Message(session.channel, content='50'))
        await until(lambda: session.phase == 'intermission' and session.control_message is not session.question_message)
        result = session.control_view
        message = session.control_message
        self.assertIn('Próxima pergunta <t:', view_text(result))
        await until(lambda: session.question_number == 2)
        self.assertIn('Rodada concluída', view_text(result))
        self.assertNotIn('Próxima pergunta <t:', view_text(result))
        self.assertIs(message.edits[-1]['view'], result)
