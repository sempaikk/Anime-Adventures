import asyncio
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord
from discord import app_commands

import bot as app
import quiz_ui as screen
from interaction_errors import respond_to_error
from scores import AwardResult, ScoreStore
from test_controls import interaction
from test_session import Channel, Deck, Message, until, user, view_text


class ResilienceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        app.click_limits.clear()
        self.patches = [patch.object(app, 'QUESTION_TIME', .5), patch.object(app, 'BETWEEN_QUESTIONS', .2),
                        patch.object(app, 'COUNTDOWN_INTERVAL', .1), patch.object(app.bot, 'connection_lost', False),
                        patch.object(app.bot, 'scores', Mock(credit=Mock(return_value=AwardResult(1, True))))]
        for item in self.patches:
            item.start()
        self.sessions = []

    async def asyncTearDown(self):
        tasks = set()
        for session in self.sessions + list(app.active_sessions.values()):
            for task in (session.runner, session.lobby_timer, session.ticker, session.pause_expiry):
                if task:
                    task.cancel()
                    tasks.add(task)
            if session.control_view:
                session.control_view.stop()
        await asyncio.gather(*tasks, return_exceptions=True)
        app.active_sessions.clear()
        app.click_limits.clear()
        for item in self.patches:
            item.stop()

    async def playing(self, channel=None):
        session = app.QuizSession(channel or Channel(1000 + len(self.sessions)), user(), app.bot.scores, deck=Deck())
        self.sessions.append(session)
        app.active_sessions[session.channel.id] = session
        await session.open_lobby()
        session.launch()
        await until(lambda: session.question_message is not None)
        return session

    async def test_disconnect_freezes_budget_and_reconnect_rejects_the_old_backlog(self):
        session = await self.playing()
        await app.on_disconnect()
        remaining = session.remaining_seconds
        self.assertTrue(session.connection_paused)
        old = Message(session.channel, content='50')
        await asyncio.sleep(.025)
        self.assertEqual(session.remaining_seconds, remaining)
        self.assertFalse(session.submit(old))
        await app.on_resumed()
        self.assertFalse(session.is_paused)
        self.assertFalse(session.connection_paused)
        self.assertAlmostEqual(session.remaining_seconds, remaining, delta=.03)
        self.assertFalse(session.submit(old))
        fresh = Message(session.channel, content='50', id=session.answer_min_id + 1)
        self.assertTrue(session.submit(fresh))
        self.assertEqual(session.correct_count, 1)

    async def test_manual_pause_stays_paused_and_duplicate_disconnect_does_not_extend_expiry(self):
        manual = await self.playing()
        await app.handle_control(interaction(manual), 'pause')
        automatic = await self.playing()
        await app.on_disconnect()
        expiry = automatic.pause_expiry
        await app.on_disconnect()
        self.assertIs(automatic.pause_expiry, expiry)
        await app.on_resumed()
        self.assertTrue(manual.is_paused)
        self.assertFalse(automatic.is_paused)

    async def test_explicit_pause_during_recovery_is_not_resumed_automatically(self):
        session = await self.playing()
        await app.on_disconnect()
        await app.handle_control(interaction(session), 'pause')
        await app.on_resumed()
        self.assertTrue(session.is_paused)

    async def test_disconnect_during_question_publication_cannot_reset_the_paused_timer(self):
        channel = Channel()
        original = channel.send
        async def delayed(*args, **kwargs):
            if len(channel.sent) == 1:
                await app.on_disconnect()
            return await original(*args, **kwargs)
        channel.send = delayed
        session = await self.playing(channel)
        self.assertTrue(session.is_paused)
        self.assertEqual(session.phase, 'paused_question')
        await app.on_resumed()
        self.assertEqual(session.phase, 'question')
        self.assertFalse(session.is_paused)

    async def test_disconnect_during_result_publication_pauses_the_full_reading_interval(self):
        session = await self.playing()
        original = session.channel.send
        async def delayed(*args, **kwargs):
            await app.on_disconnect()
            return await original(*args, **kwargs)
        session.channel.send = delayed
        self.assertTrue(session.submit(Message(session.channel, content='50')))
        await until(lambda: session.phase == 'paused_intermission')
        remaining = session.remaining_seconds
        await asyncio.sleep(.025)
        self.assertEqual(session.remaining_seconds, remaining)
        await app.on_resumed()
        self.assertEqual(session.phase, 'intermission')

    async def test_thread_deletion_and_guild_removal_release_only_their_sessions(self):
        deleted = await self.playing()
        removed = await self.playing()
        kept = await self.playing()
        removed.guild_id, kept.guild_id = 9, 10
        await app.handle_control(interaction(deleted), 'pause')
        await app.on_thread_delete(deleted.channel)
        await app.on_guild_remove(SimpleNamespace(id=9))
        self.assertFalse(deleted.running)
        self.assertFalse(removed.running)
        self.assertTrue(kept.running)
        self.assertEqual(set(app.active_sessions), {kept.channel.id})

    async def test_session_capacity_is_claimed_before_await_without_blocking_other_guilds(self):
        async def open_one(index, guild):
            seed = app.QuizSession(Channel(4000 + index), user(100 + index), app.bot.scores)
            event = interaction(seed)
            event.guild = SimpleNamespace(id=guild)
            await app.begin_lobby(event)
            return event
        with patch.object(app, 'MAX_SESSIONS', 5), patch.object(app, 'MAX_GUILD_SESSIONS', 3):
            first = await asyncio.gather(*(open_one(i, 1) for i in range(15)))
            self.assertEqual(len(app.active_sessions), 3)
            self.assertEqual(sum(len(e.channel.sent) for e in first), 3)
            await asyncio.gather(*(open_one(20 + i, 2 + i) for i in range(10)))
            self.assertEqual(len(app.active_sessions), 5)

    async def test_reconnect_does_not_undo_an_already_awarded_point(self):
        session = await self.playing()
        self.assertTrue(session.submit(Message(session.channel, content='50')))
        await app.on_disconnect()
        await app.on_resumed()
        self.assertEqual(session.correct_count, 1)
        self.assertEqual(session.session_scores[42]['points'], 1)
        app.bot.scores.credit.assert_called_once()

    async def test_new_lobby_and_manual_resume_wait_until_gateway_recovers(self):
        session = await self.playing()
        await app.on_disconnect()
        event = interaction(session)
        await app.handle_control(event, 'resume')
        self.assertTrue(session.is_paused)
        seed = app.QuizSession(Channel(5555), user(99), app.bot.scores)
        await app.begin_lobby(interaction(seed))
        self.assertNotIn(seed.channel.id, app.active_sessions)

    async def test_long_connection_outage_expires_without_resurrecting_the_game(self):
        session = await self.playing()
        session.pause_timeout = .01
        await app.on_disconnect()
        await session.pause_expiry
        await app.on_resumed()
        self.assertFalse(session.running)
        self.assertNotIn(session.channel.id, app.active_sessions)

    async def test_fifty_rooms_and_two_thousand_racing_answers_keep_one_winner_per_room(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ScoreStore(Path(directory) / 'scores.sqlite3')
            try:
                with patch.object(app.bot, 'scores', store), patch.object(app, 'QUESTION_TIME', 5):
                    sessions = []
                    for _ in range(50):
                        session = await self.playing()
                        session.round_limit = 1
                        sessions.append(session)
                    async def answer(session, actor):
                        return session.submit(Message(session.channel, user(actor), '50'))
                    results = await asyncio.gather(*(answer(session, 1000 + i * 40 + j)
                                                    for i, session in enumerate(sessions) for j in range(40)))
                    await asyncio.gather(*(s.runner for s in sessions))
                    self.assertEqual(sum(results), 50)
                    self.assertEqual(store.connection.execute('SELECT SUM(points) FROM scores').fetchone()[0], 50)
                    self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM awards').fetchone()[0], 50)
                    self.assertTrue(all(s.correct_count == 1 and s.question_number == 1 for s in sessions))
                    self.assertFalse(app.active_sessions)
            finally:
                store.close()


class InteractionErrorTests(unittest.IsolatedAsyncioTestCase):
    def event(self, done=False):
        return SimpleNamespace(response=SimpleNamespace(is_done=lambda: done, send_message=AsyncMock()),
                               followup=SimpleNamespace(send=AsyncMock()))

    async def test_failed_slash_reports_permission_problem_after_releasing_the_channel(self):
        seed = app.QuizSession(Channel(9999), user(78), Mock())
        seed.channel.fail_on_send = 1
        event = interaction(seed)
        event.response.is_done = lambda: True
        event.followup = SimpleNamespace(send=AsyncMock())
        with self.assertRaises(discord.Forbidden) as caught:
            await app.adventures.callback(event)
        with self.assertLogs('adventures.interactions', level='ERROR'):
            await app.on_command_error(event, app_commands.CommandInvokeError(app.adventures, caught.exception))
        self.assertNotIn(seed.channel.id, app.active_sessions)
        self.assertIn('permissões', event.followup.send.call_args.args[0])
        self.assertTrue(event.followup.send.call_args.kwargs['ephemeral'])
        app.click_limits.clear()

    async def test_ui_failure_is_private_and_does_not_expose_internal_error_details(self):
        event = self.event()
        with self.assertLogs('adventures.interactions', level='ERROR'):
            await screen.help_panel().on_error(event, RuntimeError('internal-secret-path'), None)
        response = event.response.send_message.call_args
        self.assertNotIn('internal-secret-path', response.args[0])
        self.assertTrue(response.kwargs['ephemeral'])

    async def test_expired_interaction_does_not_trigger_another_error_reply(self):
        event = self.event()
        event.response.send_message.side_effect = discord.NotFound(SimpleNamespace(status=404, reason='expired'), 'gone')
        with self.assertLogs('adventures.interactions', level='WARNING'):
            await respond_to_error(event, RuntimeError('failed'))
        event.followup.send.assert_not_awaited()


class StorageRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_backup_io_runs_outside_the_event_loop_and_stops_with_the_bot(self):
        client = app.AdventuresBot()
        client.scores = Mock(path=Path('/unused/scores.sqlite3'))
        entered, release = threading.Event(), threading.Event()
        def slow_backup(path):
            entered.set()
            release.wait(timeout=2)
            return {'database_bytes': 10, 'free_bytes': 100, 'backup': 'created', 'backup_bytes': 10}
        try:
            with patch.object(app, 'maintain_storage', slow_backup):
                client.storage_task = asyncio.create_task(client.monitor_storage())
                await until(entered.is_set)
                # A backup in progress must not block interaction/timer work.
                await asyncio.wait_for(asyncio.sleep(0), timeout=.1)
                release.set()
                async with client:
                    await client.close()
                self.assertIsNone(client.storage_task)
        finally:
            release.set()
            if client.storage_task:
                client.storage_task.cancel()
                await asyncio.gather(client.storage_task, return_exceptions=True)

    async def test_backup_failure_is_logged_without_closing_the_score_database(self):
        client = app.AdventuresBot()
        store = Mock(path=Path('/unused/scores.sqlite3'))
        client.scores = store
        failed = threading.Event()
        def fail(path):
            failed.set()
            raise OSError('disk full')
        with patch.object(app, 'maintain_storage', fail), self.assertLogs('adventures', level='ERROR'):
            client.storage_task = asyncio.create_task(client.monitor_storage())
            await until(failed.is_set)
            await asyncio.sleep(.01)
            store.close.assert_not_called()
            self.assertIs(client.scores, store)
            async with client:
                await client.close()


class ShutdownTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        app.active_sessions.clear()

    async def test_repeated_termination_requests_close_once_and_explain_restart_on_the_panel(self):
        client = app.AdventuresBot()
        store = Mock()
        client.scores = store
        session = app.QuizSession(Channel(4545), user(), store, deck=Deck())
        await session.open_lobby()
        app.active_sessions[session.channel.id] = session
        message = session.control_message
        async with client:
            client.request_shutdown()
            first = client.shutdown_task
            client.request_shutdown()
            self.assertIs(client.shutdown_task, first)
            await first
            self.assertFalse(session.running)
            self.assertFalse(app.active_sessions)
            store.close.assert_called_once()
            self.assertIn('O bot está reiniciando', view_text(message.edits[-1]['view']))

    async def test_unreachable_panel_does_not_prevent_shutdown_and_score_database_close(self):
        client = app.AdventuresBot()
        store = Mock()
        client.scores = store
        session = app.QuizSession(Channel(4646), user(), store, deck=Deck())
        await session.open_lobby()
        session.control_message.edit_wait = asyncio.Event()
        app.active_sessions[session.channel.id] = session
        with patch.object(app, 'SHUTDOWN_PANEL_TIMEOUT', .01), self.assertLogs('adventures', level='WARNING'):
            async with client:
                await asyncio.wait_for(client.close(), timeout=.5)
        store.close.assert_called_once()
        self.assertFalse(session.running)
        self.assertFalse(app.active_sessions)
