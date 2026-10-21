import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import discord

import quiz_legacy as app
import quiz_ui as screen
from scores import AwardResult, ScoreStore
from test_controls import interaction
from test_session import Channel, Deck, Message, until, user, view_text


class RoundTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        app.click_limits.clear()
        self.store = Mock(credit=Mock(return_value=AwardResult(10, True)))
        self.patches = [patch.object(app, 'QUESTION_TIME', .2), patch.object(app, 'BETWEEN_QUESTIONS', .001),
                        patch.object(app, 'COUNTDOWN_INTERVAL', .1), patch.object(app.bot, 'scores', self.store)]
        for p in self.patches:
            p.start()
        self.sessions = []

    async def asyncTearDown(self):
        tasks = set()
        for s in self.sessions:
            for task in (s.runner, s.lobby_timer, s.ticker, s.pause_expiry):
                if task:
                    task.cancel()
                    tasks.add(task)
            if s.control_view:
                s.control_view.stop()
        await asyncio.gather(*tasks, return_exceptions=True)
        app.active_sessions.clear()
        app.click_limits.clear()
        for p in self.patches:
            p.stop()

    async def lobby(self, store=None):
        s = app.QuizSession(Channel(800 + len(self.sessions)), user(), store or self.store, deck=Deck())
        self.sessions.append(s)
        app.active_sessions[s.channel.id] = s
        await s.open_lobby()
        return s

    async def answer(self, s, number):
        await until(lambda: s.question_number == number and s.question_message is not None and s.phase == 'question')
        self.assertTrue(s.submit(Message(s.channel, content='50')))

    async def test_host_can_choose_lengths_and_others_cannot_change_them(self):
        s = await self.lobby()
        self.assertEqual(s.round_limit, 10)
        for value, expected in [('20', 20), ('30', 30), ('continuous', None), ('10', 10)]:
            await app.handle_control(interaction(s), 'rounds', value)
            self.assertEqual(s.round_limit, expected)
        for value in ('20', 'continuous', '-1', '10000', ''):
            await app.handle_control(interaction(s, user(99)), 'rounds', value)
        self.assertEqual(s.round_limit, 10)
        for value in ('-1', '10000', '', None):
            await app.handle_control(interaction(s), 'rounds', value)
        self.assertEqual(s.round_limit, 10)
        s.launch()
        await until(lambda: s.question_message is not None)
        await app.handle_control(interaction(s), 'rounds', '30')
        self.assertEqual(s.round_limit, 10)

    async def test_each_fixed_length_finishes_after_exactly_that_many_questions(self):
        for limit in (10, 20, 30):
            with self.subTest(limit=limit):
                s = await self.lobby()
                s.round_limit = limit
                s.launch()
                for number in range(1, limit + 1):
                    await self.answer(s, number)
                await s.runner
                self.assertEqual(s.question_number, limit)
                self.assertEqual(s.correct_count, limit)
                self.assertFalse(s.running)
                self.assertNotIn(s.channel.id, app.active_sessions)
                self.assertIn(f'As {limit} perguntas foram concluídas', view_text(s.control_view))

    async def test_continuous_mode_can_pass_ten_rounds(self):
        s = await self.lobby()
        s.round_limit = None
        s.launch()
        for number in range(1, 13):
            await until(lambda: s.question_number == number and s.question_message is not None and s.phase == 'question')
            if number == 12:
                s.stop_requested = True
            self.assertTrue(s.submit(Message(s.channel, content='50')))
        await s.runner
        self.assertEqual(s.question_number, 12)
        self.assertEqual(s.correct_count, 12)

    async def test_first_silent_round_still_ends_a_fixed_length_game(self):
        s = await self.lobby()
        s.launch()
        await s.runner
        self.assertEqual(s.question_number, 1)
        self.assertIn('Ninguém tentou', view_text(s.control_view))

    async def test_replayed_question_keeps_session_point_but_not_another_global_point(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'scores.sqlite3'
            for expected_credit in (True, False):
                store = ScoreStore(path)
                try:
                    s = await self.lobby(store)
                    s.round_limit = 1
                    s.launch()
                    await self.answer(s, 1)
                    await s.runner
                    self.assertEqual(s.session_scores[42]['points'], 1)
                    self.assertEqual(s.correct_count, 1)
                    self.assertEqual(store.points(42), 1)
                    self.assertIs(s.global_credited, expected_credit)
                    if not expected_credit:
                        self.assertIn('já contou no seu total', view_text(s.control_view))
                finally:
                    store.close()

    async def test_all_lengths_fit_native_lobby_and_persistent_controls_limits(self):
        s = await self.lobby()
        for limit in (10, 20, 30, None):
            s.round_limit = limit
            view = screen.lobby_panel(s, app.handle_control)
            self.assertLessEqual(view.total_children_count, 40)
            self.assertLessEqual(view.content_length(), 4000)
            selects = [i for i in view.walk_children() if isinstance(i, discord.ui.Select)]
            self.assertEqual(len(selects), 3)
            menu = next(i for i in selects if i.custom_id == 'aa:rounds')
            self.assertEqual(sum(o.default for o in menu.options), 1)
            self.assertNotRegex(view_text(view), r'(?i)quiz|anime adventures')
            discord.http.handle_message_parameters(view=view)
        self.assertTrue(screen.PersistentControls(app.handle_control).is_persistent())

    async def test_final_summary_reports_ties_without_inventing_a_winner(self):
        s = await self.lobby()
        s.session_scores = {i: {'name': f'Player {i}', 'points': 2, 'first': i} for i in range(10)}
        self.assertIn('Empate na liderança', screen.match_leaders(s))
        self.assertIn('e mais 7', screen.match_leaders(s))
        s.session_scores[0]['points'] = 3
        self.assertIn('Liderou a partida: **Player 0**', screen.match_leaders(s))
