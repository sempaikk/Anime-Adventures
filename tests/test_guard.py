import asyncio
import unittest
from unittest.mock import Mock, patch

from scores import AwardResult

import bot as app
import quiz_ui as screen
from quiz_guard import Cooldowns
from test_controls import interaction
from test_session import Channel, Deck, Message, until, user, view_text


class CooldownTests(unittest.TestCase):
    def test_rejected_requests_do_not_extend_wait_and_players_are_independent(self):
        now = [0]
        limit = Cooldowns(clock=lambda: now[0])
        self.assertTrue(limit.allow(('scores', 1), 1))
        now[0] = .9
        self.assertFalse(limit.allow(('scores', 1), 1))
        self.assertTrue(limit.allow(('scores', 2), 1))
        now[0] = 1
        self.assertTrue(limit.allow(('scores', 1), 1))

    def test_memory_remains_bounded_under_many_distinct_players(self):
        limit = Cooldowns(clock=lambda: 0, capacity=100)
        for actor in range(10000):
            limit.allow(('scores', actor), 1)
        self.assertEqual(len(limit.entries), 100)
        self.assertFalse(limit.allow(('scores', 9999), 1))


class GuardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.now = [0]
        self.limits = Cooldowns(clock=lambda: self.now[0])
        self.patches = [patch.object(app, 'QUESTION_TIME', .6), patch.object(app, 'BETWEEN_QUESTIONS', .03),
                        patch.object(app, 'COUNTDOWN_INTERVAL', .3), patch.object(app, 'click_limits', self.limits),
                        patch.object(app.bot, 'scores', Mock(points=Mock(return_value=9), credit=Mock(return_value=AwardResult(10, True))))]
        for p in self.patches:
            p.start()
        self.sessions = []

    async def asyncTearDown(self):
        sessions = self.sessions + list(app.active_sessions.values())
        tasks = set()
        for s in sessions:
            for task in (s.runner, s.lobby_timer, s.ticker, s.pause_expiry):
                if task:
                    task.cancel()
                    tasks.add(task)
            if s.control_view:
                s.control_view.stop()
        await asyncio.gather(*tasks, return_exceptions=True)
        app.active_sessions.clear()
        for p in self.patches:
            p.stop()

    async def playing(self):
        s = app.QuizSession(Channel(), user(), app.bot.scores, deck=Deck())
        self.sessions.append(s)
        app.active_sessions[s.channel.id] = s
        await s.open_lobby()
        s.launch()
        await until(lambda: s.question_message is not None)
        return s

    async def test_chat_brute_force_is_limited_without_blocking_other_players(self):
        s = await self.playing()
        for answer in ('errado 1', 'errado 2', 'errado 3'):
            self.assertFalse(s.submit(Message(s.channel, content=answer)))
        self.assertFalse(s.submit(Message(s.channel, content='50')))
        self.assertFalse(s.answer_future.done())
        self.assertTrue(s.submit(Message(s.channel, user(99), '50')))
        await until(lambda: s.correct_count == 1)
        self.assertNotIn(42, s.session_scores)
        self.assertEqual(s.session_scores[99]['points'], 1)

    async def test_duplicate_normalized_answers_do_not_spend_more_attempts(self):
        s = await self.playing()
        for answer in ('NÃO', 'nao!', '  não  ', 'nao'):
            self.assertFalse(s.submit(Message(s.channel, content=answer)))
        self.assertEqual(s.chat_attempts[42], {'nao'})
        self.assertTrue(s.submit(Message(s.channel, content='50')))

    async def test_player_limit_also_bounds_chat_attempt_storage(self):
        s = await self.playing()
        for uid in range(1, 201):
            self.assertFalse(s.submit(Message(s.channel, user(uid), 'errado')))
        for uid in range(201, 1201):
            self.assertFalse(s.submit(Message(s.channel, user(uid), '50')))
        self.assertEqual(len(s.performance), 200)
        self.assertEqual(len(s.chat_attempts), 200)
        self.assertFalse(s.answer_future.done())
        self.assertTrue(s.submit(Message(s.channel, user(42), '50')))
        await until(lambda: s.correct_count == 1)
        self.assertEqual(s.session_scores[42]['points'], 1)

    async def test_empty_oversized_and_webhook_messages_do_not_count(self):
        s = await self.playing()
        for answer in ('', '   ', '!!!', 'x' * (app.MAX_ANSWER_LENGTH + 1)):
            self.assertFalse(s.submit(Message(s.channel, content=answer)))
        self.assertFalse(s.submit(Message(s.channel, content='50', webhook_id=999)))
        self.assertFalse(s.had_participation)
        self.assertFalse(s.chat_attempts)
        self.assertTrue(s.submit(Message(s.channel, content='50')))

    async def test_chat_limit_survives_pause_and_resets_only_on_next_question(self):
        s = await self.playing()
        for answer in ('a', 'b', 'c'):
            s.submit(Message(s.channel, content=answer))
        await app.handle_control(interaction(s), 'pause')
        await app.handle_control(interaction(s), 'resume')
        self.assertFalse(s.submit(Message(s.channel, content='50')))
        self.assertTrue(s.submit(Message(s.channel, user(99), '50')))
        await until(lambda: s.question_number == 2 and s.question_message is not None)
        self.assertFalse(s.chat_attempts)
        self.assertTrue(s.submit(Message(s.channel, content='50')))

    async def test_score_spam_is_acknowledged_once_without_repeated_database_reads(self):
        s = await self.playing()
        clicks = [interaction(s) for _ in range(40)]
        await asyncio.gather(*(app.handle_control(e, 'scores') for e in clicks))
        app.bot.scores.points.assert_called_once()
        self.assertEqual(sum(e.response.send_message.await_count for e in clicks), 1)
        self.assertEqual(sum(e.response.defer.await_count for e in clicks), 39)
        self.assertFalse(s.had_participation)
        self.now[0] = .75
        await app.handle_control(interaction(s), 'scores')
        self.assertEqual(app.bot.scores.points.call_count, 2)

    async def test_private_ui_cooldown_does_not_block_an_answer_or_another_player(self):
        s = await self.playing()
        await app.handle_control(interaction(s), 'help')
        await app.handle_control(interaction(s), 'scores')
        event = interaction(s, user(99))
        await app.handle_control(event, 'help')
        event.response.send_message.assert_awaited_once()
        self.assertTrue(s.submit(Message(s.channel, content='50')))

    async def test_one_player_cannot_flood_multiple_channels_with_lobbies(self):
        seeds = [app.QuizSession(Channel(500 + i), user(), app.bot.scores) for i in range(20)]
        await asyncio.gather(*(app.begin_lobby(interaction(s)) for s in seeds))
        self.assertEqual(len(app.active_sessions), 1)
        self.assertEqual(sum(len(s.channel.sent) for s in seeds), 1)
        self.now[0] = 3
        await app.begin_lobby(interaction(seeds[-1]))
        self.assertEqual(len(app.active_sessions), 2)

    async def test_forty_duplicate_pause_clicks_make_one_edit_and_keep_original_expiry(self):
        s = await self.playing()
        message = s.control_message
        await app.handle_control(interaction(s), 'pause')
        watchdog = s.pause_expiry
        edits = len(message.edits)
        await asyncio.gather(*(app.handle_control(interaction(s), 'pause') for _ in range(40)))
        self.assertEqual(len(message.edits), edits)
        self.assertIs(s.pause_expiry, watchdog)

    async def test_abandoned_question_pause_ends_and_releases_channel(self):
        s = await self.playing()
        s.pause_timeout = .02
        await app.handle_control(interaction(s), 'pause')
        expiry = s.pause_expiry
        await expiry
        self.assertFalse(s.running)
        self.assertNotIn(s.channel.id, app.active_sessions)
        self.assertIn('A pausa chegou', view_text(s.control_view))
        app.bot.scores.credit.assert_not_called()

    async def test_resume_cancels_old_pause_expiry(self):
        s = await self.playing()
        s.pause_timeout = .03
        await app.handle_control(interaction(s), 'pause')
        expiry = s.pause_expiry
        await app.handle_control(interaction(s), 'resume')
        await asyncio.sleep(.05)
        self.assertTrue(expiry.cancelled())
        self.assertTrue(s.running)
        self.assertIsNone(s.pause_expiry)

    async def test_abandoned_interval_pause_preserves_the_awarded_point(self):
        s = await self.playing()
        s.between_questions = .6
        s.submit(Message(s.channel, content='50'))
        await until(lambda: s.phase == 'intermission' and s.control_message is not s.question_message)
        s.pause_timeout = .02
        await app.handle_control(interaction(s), 'pause')
        await s.pause_expiry
        self.assertFalse(s.running)
        self.assertEqual(s.session_scores[42]['points'], 1)
        app.bot.scores.credit.assert_called_once()

    def test_player_name_cannot_insert_fake_score_rows_or_mentions(self):
        value = screen.safe_name('Jogador\n1. **Admin**\t@everyone\u202eevil')
        self.assertNotIn('\n', value)
        self.assertNotIn('\t', value)
        self.assertNotIn('\u202e', value)
        self.assertNotIn('@everyone', value)
        self.assertIn('\\*\\*Admin\\*\\*', value)
