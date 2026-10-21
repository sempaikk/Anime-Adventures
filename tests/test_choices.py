import asyncio
import unittest
from unittest.mock import Mock, patch

import discord

import bot as app
from test_controls import interaction
from test_session import Channel, Message, until, user


QUESTION = next(q for q in app.PACK.questions if q.id == 'lobby:summon-position')


class ChoiceDeck:
    def draw(self):
        return QUESTION


class ChoiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.patches = [patch.object(app, 'QUESTION_TIME', .25), patch.object(app, 'BETWEEN_QUESTIONS', .01),
                        patch.object(app, 'COUNTDOWN_INTERVAL', .08),
                        patch.object(app.bot, 'scores', Mock(award=Mock(return_value=1)))]
        for p in self.patches:
            p.start()
        self.sessions = []

    async def asyncTearDown(self):
        tasks = []
        for s in self.sessions:
            for task in (s.runner, s.lobby_timer, s.ticker):
                if task:
                    task.cancel()
                    tasks.append(task)
            if s.control_view:
                s.control_view.stop()
        await asyncio.gather(*tasks, return_exceptions=True)
        app.active_sessions.clear()
        for p in self.patches:
            p.stop()

    async def playing(self):
        s = app.QuizSession(Channel(), user(), app.bot.scores, deck=ChoiceDeck())
        self.sessions.append(s)
        app.active_sessions[s.channel.id] = s
        await s.open_lobby()
        old = s.control_message
        s.launch()
        await until(lambda: s.question_message is not None)
        self.old_panel = old
        return s

    def correct(self, s):
        return next(i for i, label in enumerate(s.choice_order) if QUESTION.accepts(label))

    async def click(self, s, index, actor=None):
        event = interaction(s, actor)
        await app.handle_control(event, f'answer:{index}')
        return event

    async def test_forty_simultaneous_correct_clicks_produce_one_winner_and_one_award(self):
        s = await self.playing()
        events = [interaction(s, user(i, f'Player {i}')) for i in range(100, 140)]
        await asyncio.gather(*(app.handle_control(e, f'answer:{self.correct(s)}') for e in events))
        await until(lambda: s.correct_count == 1)
        app.bot.scores.award.assert_called_once()
        self.assertEqual(sum('chegou primeiro' in e.response.send_message.call_args.args[0] for e in events), 1)
        self.assertEqual(sum(row['points'] for row in s.session_scores.values()), 1)

    async def test_wrong_choice_is_one_attempt_and_another_player_can_win(self):
        s = await self.playing()
        correct = self.correct(s)
        wrong = (correct + 1) % 3
        first = await self.click(s, wrong, user(99))
        self.assertTrue(first.response.send_message.call_args.kwargs['ephemeral'])
        self.assertNotIn(QUESTION.answer, first.response.send_message.call_args.args[0])
        second = await self.click(s, correct, user(99))
        self.assertIn('já escolheu', second.response.send_message.call_args.args[0])
        self.assertFalse(s.answer_future.done())
        await self.click(s, correct, user(100))
        await until(lambda: s.correct_count == 1)
        self.assertIn(100, s.session_scores)
        self.assertNotIn(99, s.session_scores)

    async def test_chat_cannot_bypass_a_choice_question(self):
        s = await self.playing()
        self.assertFalse(s.submit(Message(s.channel, content=QUESTION.answer)))
        self.assertFalse(s.had_participation)
        self.assertFalse(s.answer_future.done())

    async def test_buttons_are_neutral_and_shuffled_order_survives_pause_resume(self):
        s = await self.playing()
        order = list(s.choice_order)
        buttons = [i for i in s.control_view.walk_children() if getattr(i, 'custom_id', '').startswith('aa:answer:')]
        self.assertEqual(len(buttons), 3)
        self.assertEqual([b.label for b in buttons], [f'{"ABC"[i]} · {label}' for i, label in enumerate(order)])
        self.assertTrue(all(b.emoji is None for b in buttons))
        self.assertTrue(all(b.style == discord.ButtonStyle.secondary for b in buttons))
        await app.handle_control(interaction(s), 'pause')
        buttons = [i for i in s.control_view.walk_children() if getattr(i, 'custom_id', '').startswith('aa:answer:')]
        self.assertTrue(all(b.disabled for b in buttons))
        delayed = interaction(s, user(99))
        await app.handle_control(delayed, f'answer:{self.correct(s)}')
        self.assertNotIn(99, s.choice_attempts)
        await app.handle_control(interaction(s), 'resume')
        self.assertEqual(s.choice_order, order)
        await app.handle_control(delayed, f'answer:{self.correct(s)}')
        self.assertNotIn(99, s.choice_attempts)
        self.assertIn('antes da retomada', delayed.response.send_message.call_args.args[0])
        await self.click(s, self.correct(s), user(99))
        await until(lambda: s.correct_count == 1)

    async def test_pause_does_not_reset_a_players_wrong_attempt(self):
        s = await self.playing()
        await self.click(s, (self.correct(s) + 1) % 3, user(99))
        await app.handle_control(interaction(s), 'pause')
        await app.handle_control(interaction(s), 'resume')
        event = await self.click(s, self.correct(s), user(99))
        self.assertIn('já escolheu', event.response.send_message.call_args.args[0])

    async def test_stale_message_and_invalid_slot_do_not_consume_attempts(self):
        s = await self.playing()
        event = interaction(s, user(99), self.old_panel)
        await app.handle_control(event, f'answer:{self.correct(s)}')
        for index in (-1, 3, 999):
            await self.click(s, index, user(99))
        self.assertFalse(s.had_participation)
        self.assertFalse(s.choice_attempts)

    async def test_no_attempt_ends_round_and_late_click_cannot_score(self):
        s = await self.playing()
        old = s.control_message
        await s.runner
        self.assertFalse(s.running)
        event = interaction(s, user(99), old)
        await app.handle_control(event, f'answer:{self.correct(s)}')
        app.bot.scores.award.assert_not_called()

    async def test_a_wrong_choice_counts_as_participation_and_next_round_clears_attempts(self):
        s = await self.playing()
        await self.click(s, (self.correct(s) + 1) % 3, user(99))
        self.assertTrue(s.had_participation)
        await until(lambda: s.question_number == 2 and s.question_message is not None)
        self.assertFalse(s.choice_attempts)
        await self.click(s, self.correct(s), user(99))
        await until(lambda: s.correct_count == 1)

    async def test_failed_winner_acknowledgement_cannot_lose_the_point(self):
        s = await self.playing()
        event = interaction(s, user(99))
        event.response.send_message.side_effect = RuntimeError('transport failed')
        with self.assertRaises(RuntimeError):
            await app.handle_control(event, f'answer:{self.correct(s)}')
        await until(lambda: s.correct_count == 1)
        app.bot.scores.award.assert_called_once()
