import asyncio
import itertools
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord
import bot as app
import quiz_ui as screen
from scores import ScoreStore

QUESTIONS = {q.id: q for q in app.PACK.questions}
IDS = itertools.count(1000)


def user(id=42, name='Jogador', is_bot=False):
    return SimpleNamespace(id=id, display_name=name, bot=is_bot)


class Message:
    def __init__(self, channel, author=None, content='', *, webhook_id=None, id=None):
        self.channel = channel
        self.author = author or user()
        self.content = content
        self.id = next(IDS) if id is None else id
        self.webhook_id = webhook_id
        self.edits = []
        self.edit_error = None
        self.edit_wait = None

    async def edit(self, **kwargs):
        if self.edit_wait:
            await self.edit_wait.wait()
        if self.edit_error:
            raise self.edit_error
        self.edits.append(kwargs)


class Channel:
    def __init__(self, id=111):
        self.id = id
        self.sent = []
        self.fail_on_send = None

    async def send(self, content=None, **kwargs):
        if self.fail_on_send == len(self.sent) + 1:
            raise discord.Forbidden(SimpleNamespace(status=403, reason='Forbidden'), 'no permission')
        message = Message(self, user(1, 'Bot', True))
        self.sent.append({'message': message, 'content': content, **kwargs})
        return message


class Deck:
    def draw(self):
        return QUESTIONS['summon:cost']


async def until(predicate):
    async with asyncio.timeout(1):
        while not predicate():
            await asyncio.sleep(0.001)


def view_text(view):
    return '\n'.join(item.content for item in view.walk_children() if isinstance(item, discord.ui.TextDisplay))


class SessionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.patches = [patch.object(app, 'QUESTION_TIME', 0.06), patch.object(app, 'COUNTDOWN_INTERVAL', 0.01), patch.object(app, 'BETWEEN_QUESTIONS', 0.002)]
        for p in self.patches:
            p.start()
        self.sessions = []
        self.tasks = []
        self.channel = Channel()
        self.store = Mock(award=Mock(return_value=17))

    async def asyncTearDown(self):
        for session in self.sessions:
            if session.runner:
                session.runner.cancel()
            if session.ticker:
                session.ticker.cancel()
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, *(s.runner for s in self.sessions if s.runner), return_exceptions=True)
        app.active_sessions.clear()
        for p in self.patches:
            p.stop()

    def session(self, **kwargs):
        session = app.QuizSession(self.channel, user(), self.store, deck=Deck(), **kwargs)
        session.running = True
        self.sessions.append(session)
        return session

    async def play(self, session):
        task = asyncio.create_task(session.play_question())
        self.tasks.append(task)
        await until(lambda: session.question_message is not None)
        return task

    async def test_simultaneous_correct_messages_award_only_first_player(self):
        session = self.session()
        task = await self.play(session)
        app.active_sessions[self.channel.id] = session
        messages = [Message(self.channel, user(i, f'Player {i}'), '50') for i in range(50, 90)]
        await asyncio.gather(*(app.on_message(message) for message in messages))
        self.assertTrue(await task)
        self.store.award.assert_called_once_with(str(session.question_message.id), 50, 'Player 50')
        self.assertEqual(session.correct_count, 1)
        self.assertEqual(len(session.session_scores), 1)
        self.assertIn('Player 50', view_text(self.channel.sent[-1]['view']))

    async def test_wrong_attempt_keeps_session_going_without_feedback_spam(self):
        session = self.session()
        task = await self.play(session)
        self.assertFalse(session.submit(Message(self.channel, content='errado')))
        self.assertTrue(await task)
        self.store.award.assert_not_called()
        self.assertEqual(len(self.channel.sent), 2)
        self.assertIn('Tempo esgotado', view_text(self.channel.sent[-1]['view']))
        self.assertIn('Próxima pergunta', view_text(self.channel.sent[-1]['view']))

    async def test_silent_round_stops_and_releases_channel(self):
        session = self.session()
        app.active_sessions[self.channel.id] = session
        session.launch()
        await session.runner
        self.assertFalse(session.running)
        self.assertNotIn(self.channel.id, app.active_sessions)
        self.assertEqual(session.question_number, 1)
        self.assertEqual(len(self.channel.sent), 2)
        self.assertIn('Fim de jogo', view_text(self.channel.sent[-1]['view']))

    async def test_winner_continues_then_silence_ends_next_question(self):
        session = self.session()
        app.active_sessions[self.channel.id] = session
        session.launch()
        await until(lambda: session.question_message is not None)
        self.assertTrue(session.submit(Message(self.channel, content='50 gems')))
        await session.runner
        self.assertEqual(session.question_number, 2)
        self.assertEqual(session.correct_count, 1)
        self.store.award.assert_called_once()
        self.assertFalse(session.running)

    async def test_late_answers_are_rejected_even_before_timeout_task_wakes(self):
        now = [100.0]
        session = self.session(clock=lambda: now[0])
        task = await self.play(session)
        now[0] = session.deadline
        self.assertFalse(session.submit(Message(self.channel, content='50')))
        self.assertFalse(session.had_participation)
        await task
        self.store.award.assert_not_called()

    async def test_slow_publication_does_not_consume_answer_time(self):
        original_send = self.channel.send
        first = True

        async def slow_send(*args, **kwargs):
            nonlocal first
            if first:
                first = False
                await asyncio.sleep(0.04)
            return await original_send(*args, **kwargs)

        self.channel.send = slow_send
        session = self.session()
        task = await self.play(session)
        self.assertGreater(session.deadline - session.clock(), 0.04)
        self.assertFalse(await task)

    async def test_old_bot_and_webhook_messages_do_not_keep_quiz_alive(self):
        session = self.session()
        task = await self.play(session)
        for message in [Message(self.channel, content='50', id=session.question_message.id - 1), Message(self.channel, user(is_bot=True), '50'), Message(self.channel, content='50', webhook_id=2)]:
            self.assertFalse(session.submit(message))
        self.assertFalse(await task)
        self.assertFalse(session.had_participation)

    async def test_slow_result_publication_does_not_consume_reading_interval(self):
        session = self.session()
        session.between_questions = .06
        task = await self.play(session)
        original_send = self.channel.send

        async def slow_send(*args, **kwargs):
            await asyncio.sleep(.08)
            return await original_send(*args, **kwargs)

        self.channel.send = slow_send
        self.assertTrue(session.submit(Message(self.channel, content='50')))
        self.assertTrue(await task)
        self.assertGreater(session.remaining_seconds, .05)

    async def test_delayed_edit_cannot_extend_answer_deadline(self):
        session = self.session()
        task = await self.play(session)
        session.question_message.edit_wait = asyncio.Event()
        # The clock edit blocks; finishing cancels it. Let only the final close edit finish.
        async def unblock_closed():
            await asyncio.sleep(0.085)
            session.question_message.edit_wait.set()
        unblock = asyncio.create_task(unblock_closed())
        self.tasks.append(unblock)
        await asyncio.sleep(0.07)
        self.assertTrue(session.answer_future.done())
        self.assertFalse(session.submit(Message(self.channel, content='50')))
        self.assertFalse(await asyncio.wait_for(task, 0.3))
        self.store.award.assert_not_called()

    async def test_transient_clock_edit_error_does_not_stop_timer(self):
        session = self.session()
        task = await self.play(session)
        session.question_message.edit_error = discord.HTTPException(SimpleNamespace(status=500, reason='error'), 'temporary')
        with self.assertLogs('adventures', level='WARNING'):
            self.assertFalse(await task)
        self.assertIn('Tempo esgotado', view_text(self.channel.sent[-1]['view']))

    async def test_deleted_question_releases_session(self):
        session = self.session()
        app.active_sessions[self.channel.id] = session
        session.launch()
        await until(lambda: session.question_message is not None)
        session.question_message.edit_error = discord.NotFound(SimpleNamespace(status=404, reason='gone'), 'deleted')
        with self.assertRaises(asyncio.CancelledError):
            await session.runner
        self.assertNotIn(self.channel.id, app.active_sessions)
        self.assertFalse(session.running)

    async def test_permission_failure_does_not_leave_ghost_session(self):
        session = self.session()
        self.channel.fail_on_send = 1
        app.active_sessions[self.channel.id] = session
        with self.assertLogs('adventures', level='ERROR'):
            session.launch()
            await session.runner
        self.assertNotIn(self.channel.id, app.active_sessions)
        self.assertFalse(session.running)

    async def test_score_write_failure_is_visible_and_does_not_stall_next_round(self):
        self.store.award.side_effect = sqlite3.OperationalError('read-only')
        session = self.session()
        task = await self.play(session)
        with self.assertLogs('adventures', level='ERROR'):
            session.submit(Message(self.channel, content='50'))
            self.assertTrue(await task)
        self.assertEqual(session.correct_count, 1)
        self.assertIn('não deu para salvar', view_text(self.channel.sent[-1]['view']))

    async def test_cancellation_releases_session_and_clock(self):
        session = self.session()
        app.active_sessions[self.channel.id] = session
        session.launch()
        await until(lambda: session.ticker is not None)
        ticker = session.ticker
        session.runner.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await session.runner
        self.assertTrue(ticker.done())
        self.assertNotIn(self.channel.id, app.active_sessions)

    async def test_session_does_not_remove_another_session_replacement(self):
        session = self.session()
        replacement = object()
        session.launch()
        app.active_sessions[self.channel.id] = replacement
        await session.runner
        self.assertIs(app.active_sessions[self.channel.id], replacement)

    async def test_actual_score_store_and_quiz_work_together(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ScoreStore(Path(directory) / 'scores.sqlite3')
            session = self.session()
            session.store = store
            task = await self.play(session)
            session.submit(Message(self.channel, content='50'))
            await task
            self.assertEqual(store.award(str(session.question_message.id), 42, 'Jogador'), 1)
            store.close()

    async def test_all_cards_fit_discord_limits_and_do_not_reveal_rarity_answer(self):
        session = self.session()
        session.ends_at = datetime.now(timezone.utc)
        session.next_at = session.ends_at
        for q in app.PACK.questions:
            session.current_question = q
            for panel in [screen.question_panel(session, app.handle_control, session.question_time),
                          screen.result_panel(session, None, None, True, app.handle_control),
                          screen.result_panel(session, None, None, False, app.handle_control)]:
                self.assertLessEqual(panel.total_children_count, 40, q.id)
                self.assertLessEqual(panel.content_length(), 4000, q.id)
                payload = discord.http.handle_message_parameters(view=panel).payload
                self.assertEqual(payload['flags'] & 32768, 32768)
                self.assertNotIn('embeds', payload)
                ids = [item.custom_id for item in panel.walk_children() if getattr(item, 'custom_id', None)]
                self.assertEqual(len(ids), len(set(ids)), q.id)
            panel = screen.question_panel(session, app.handle_control, session.question_time)
            if q.category == 'Raridades':
                self.assertEqual(panel.card.to_component_dict()['accent_color'], screen.BRAND_COLOR)
                self.assertNotIn(q.answer, view_text(panel))


class CommandTests(unittest.IsolatedAsyncioTestCase):
    def interaction(self, **permissions):
        return SimpleNamespace(channel=Channel(), guild=object(), user=user(), app_permissions=SimpleNamespace(view_channel=True, send_messages=True, embed_links=True, **permissions), response=SimpleNamespace(send_message=AsyncMock()))

    async def asyncTearDown(self):
        app.active_sessions.clear()

    async def test_one_command_and_duplicate_invocations_do_not_launch_two_sessions(self):
        self.assertEqual([c.name for c in app.bot.tree.get_commands()], ['adventures'])
        self.assertTrue(app.adventures.guild_only)
        interaction = self.interaction()
        with patch.object(app.QuizSession, 'open_lobby', new_callable=AsyncMock) as launch:
            await asyncio.gather(app.adventures.callback(interaction), app.adventures.callback(interaction))
        launch.assert_awaited_once()
        self.assertEqual(len(app.active_sessions), 1)
        self.assertEqual(interaction.response.send_message.await_count, 2)

    async def test_missing_embed_permission_explains_problem_without_starting(self):
        interaction = self.interaction()
        interaction.app_permissions.embed_links = False
        await app.adventures.callback(interaction)
        self.assertEqual(app.active_sessions, {})
        self.assertIn('Inserir links', interaction.response.send_message.call_args.args[0])

    async def test_failed_acknowledgement_releases_channel(self):
        interaction = self.interaction()
        interaction.response.send_message.side_effect = discord.HTTPException(SimpleNamespace(status=500, reason='error'), 'failed')
        with self.assertRaises(discord.HTTPException):
            await app.adventures.callback(interaction)
        self.assertEqual(app.active_sessions, {})

    async def test_shutdown_cancels_active_sessions(self):
        session = app.QuizSession(Channel(), user(), Mock(), deck=Deck())
        app.active_sessions[session.channel.id] = session
        session.launch()
        await until(lambda: session.ticker is not None)
        client = app.AdventuresBot()
        async with client:
            await client.close()
        self.assertFalse(session.running)
        self.assertEqual(app.active_sessions, {})
