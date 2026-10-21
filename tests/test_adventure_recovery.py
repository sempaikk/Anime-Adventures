import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import quiz_legacy as app
from adventure_repository import AdventureRepository
from quiz_content import QuestionDeck
from scores import ScoreStore
from test_controls import interaction
from test_session import Channel, Message, until, user, view_text


class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'scores.sqlite3'
        self.store=ScoreStore(self.path)
        self.repo=AdventureRepository(self.store.connection)
        self.patches=[patch.object(app.bot,'scores',self.store),patch.object(app.bot,'adventures',self.repo),
                      patch.object(app,'QUESTION_TIME',30),patch.object(app,'BETWEEN_QUESTIONS',20),
                      patch.object(app.bot,'connection_lost',False)]
        for p in self.patches:p.start()
        self.sessions=[]
        app.click_limits.clear()
        self.guild=SimpleNamespace(id=10)
        async def fetch(uid):return SimpleNamespace(id=uid,display_name='Player '+str(uid),bot=False,guild=self.guild)
        self.guild.fetch_member=AsyncMock(side_effect=fetch)
        self.channel=Channel(7777);self.channel.guild=self.guild
        async def fetch_message(mid):
            return next(row['message'] for row in self.channel.sent if row['message'].id==mid)
        self.channel.fetch_message=AsyncMock(side_effect=fetch_message)
        self.question=next(q for q in app.PACK.questions if q.id=='summon:cost')

    async def asyncTearDown(self):
        tasks=set()
        for s in self.sessions+list(app.active_sessions.values()):
            s.suspending=True
            for t in (s.runner,s.ticker,s.lobby_timer,s.pause_expiry):
                if t:t.cancel();tasks.add(t)
            if s.control_view:s.control_view.stop()
        await asyncio.gather(*tasks,return_exceptions=True)
        app.active_sessions.clear();app.click_limits.clear()
        for p in self.patches:p.stop()
        self.store.close();self.temp.cleanup()

    def event(self,s,actor=None,message=None):
        e=interaction(s,actor,message)
        e.guild=self.guild;e.guild_id=self.guild.id
        e.followup=SimpleNamespace(send=AsyncMock())
        return e

    async def playing(self):
        s=app.QuizSession(self.channel,user(),self.store)
        self.sessions.append(s);app.active_sessions[self.channel.id]=s
        await s.open_lobby()
        # A deterministic single question from the real pack still exports the real deck protocol.
        s.deck=QuestionDeck((self.question,))
        s.launch();await until(lambda:s.question_message is not None)
        return s

    async def crash(self,s):
        s.suspending=True
        s.runner.cancel();await asyncio.gather(s.runner,return_exceptions=True)
        if s.control_view:s.control_view.stop()
        app.active_sessions.clear()
        self.store.close()
        self.store=ScoreStore(self.path)
        self.repo=AdventureRepository(self.store.connection)
        app.bot.scores=self.store;app.bot.adventures=self.repo

    def reconstruct(self,state):
        s=app.QuizSession(self.channel,user(),self.store)
        s.load_saved(state,app.screen.GROUPS)
        self.sessions.append(s)
        return s

    async def test_unanswered_interrupted_round_is_void_and_old_question_does_not_repeat(self):
        s=await self.playing()
        self.assertFalse(s.submit(Message(self.channel,content='wrong')))
        s.checkpoint()
        state=self.repo.get(s.session_id)
        interrupted_id=s.current_question.id
        await self.crash(s)
        restored=self.reconstruct(state)
        self.assertEqual(restored.question_number,0)
        self.assertEqual(restored.correct_count,0)
        self.assertEqual(restored.performance[42]['attempts'],0)
        self.assertEqual(restored.phase,'recovery')
        self.assertEqual(self.store.points(42),0)
        # More than one question exists in the real filtered pack after restore.
        self.assertNotEqual(restored.deck.draw().id,interrupted_id)

    async def test_winner_saved_before_shutdown_is_restored_once_with_review(self):
        s=await self.playing()
        self.assertTrue(s.submit(Message(self.channel,content='50')))
        state=self.repo.get(s.session_id)
        self.assertFalse(state['round']['complete'])
        await self.crash(s)
        restored=self.reconstruct(state)
        self.assertEqual(restored.question_number,1)
        self.assertEqual(restored.correct_count,1)
        self.assertEqual(restored.session_scores[42]['points'],1)
        self.assertEqual(restored.performance[42]['played'],1)
        self.assertEqual(len(restored.review_history),1)
        self.assertEqual(self.store.points(42),1)

    async def test_crash_between_point_commit_and_match_checkpoint_reconciles_the_receipt(self):
        s=await self.playing()
        state=self.repo.get(s.session_id)
        self.store.credit(str(s.question_message.id),78,'Winner',content_id='release:summon:cost')
        await self.crash(s)
        restored=self.reconstruct(state)
        self.assertEqual(restored.correct_count,1)
        self.assertEqual(restored.session_scores[78]['points'],1)
        self.assertEqual(restored.performance[78]['won'],1)
        self.assertEqual(self.store.points(78),1)
        self.assertEqual(self.store.connection.execute('SELECT COUNT(*) FROM awards').fetchone()[0],1)
        second=self.reconstruct(self.repo.get(restored.session_id))
        self.assertEqual(second.correct_count,1)
        self.assertEqual(second.performance[78]['played'],1)

    async def test_recovery_restores_one_panel_and_only_current_host_or_mod_can_continue(self):
        s=await self.playing()
        state=self.repo.get(s.session_id)
        await self.crash(s)
        first,second=await asyncio.gather(app.restore_one_session(self.channel,state),app.restore_one_session(self.channel,state))
        self.assertIs(first,second)
        self.sessions.append(first)
        self.assertEqual(first.phase,'recovery')
        self.assertEqual(self.channel.fetch_message.await_count,1)
        await app.handle_control(self.event(first,user(99)),'resume_saved')
        self.assertEqual(first.phase,'recovery')
        await app.handle_control(self.event(first),'resume_saved')
        await until(lambda:first.phase=='question' and first.question_message is not None)
        self.assertEqual(first.question_number,1)
        self.assertNotEqual(first.current_question.id,self.question.id)

    async def test_invalid_fingerprint_ends_saved_game_without_touching_totals(self):
        s=await self.playing()
        state=self.repo.get(s.session_id)
        state['fingerprint']='invalid'
        self.store.award('trusted',42,'Player')
        await self.crash(s)
        with self.assertLogs('adventures',level='WARNING'):
            restored=await app.restore_one_session(self.channel,state)
        self.assertIsNone(restored)
        self.assertEqual(self.repo.get(s.session_id)['_status'],'finished')
        self.assertEqual(self.store.points(42),1)

    async def test_graceful_shutdown_keeps_recoverable_snapshot_instead_of_finished_state(self):
        s=await self.playing()
        client=app.AdventuresBot();client.scores=self.store;client.adventures=self.repo
        async with client:
            await client.close()
        self.store=ScoreStore(self.path);self.repo=AdventureRepository(self.store.connection)
        app.bot.scores=self.store;app.bot.adventures=self.repo
        state=self.repo.get(s.session_id)
        self.assertEqual(state['_status'],'suspended')
        self.assertEqual(state['phase'],'question')
        self.assertEqual(len(self.repo.recoverable()),1)
        self.assertIn('partida foi salva',view_text(s.control_message.edits[-1]['view']))

    async def test_empty_lobby_filter_remains_editable_after_restart(self):
        s=app.QuizSession(self.channel,user(),self.store)
        self.sessions.append(s)
        await s.open_lobby()
        s.difficulty='hard';s.answer_mode='image';s.checkpoint()
        state=self.repo.get(s.session_id)
        restored=self.reconstruct(state)
        self.assertEqual(restored.phase,'lobby')
        self.assertFalse(restored.selected_questions())
        restored.answer_mode='mixed'
        self.assertTrue(restored.selected_questions())

    async def test_recovered_last_winner_finishes_without_starting_an_eleventh_question(self):
        s=await self.playing();s.question_number=10
        self.assertTrue(s.submit(Message(self.channel,content='50')))
        state=self.repo.get(s.session_id)
        await self.crash(s)
        recovered=await app.restore_one_session(self.channel,state)
        self.sessions.append(recovered)
        await app.handle_control(self.event(recovered),'resume_saved')
        self.assertFalse(recovered.running)
        self.assertIsNone(recovered.runner)
        self.assertEqual(recovered.question_number,10)
        self.assertEqual(self.store.points(42),1)

    async def test_old_answer_button_on_recovery_panel_cannot_claim_a_new_point(self):
        s=await self.playing();old_message=s.question_message
        state=self.repo.get(s.session_id)
        await self.crash(s)
        recovered=await app.restore_one_session(self.channel,state)
        self.sessions.append(recovered)
        event=self.event(recovered,message=old_message)
        await app.handle_control(event,'answer:0')
        self.assertEqual(self.store.points(42),0)
        self.assertEqual(recovered.correct_count,0)
        self.assertEqual(recovered.phase,'recovery')

    async def test_restart_does_not_resurrect_a_game_that_the_host_already_stopped(self):
        s=await self.playing()
        self.assertTrue(s.submit(Message(self.channel,content='50')))
        s.stop_requested=True
        client=app.AdventuresBot();client.scores=self.store;client.adventures=self.repo
        async with client:
            await client.close()
        self.store=ScoreStore(self.path);self.repo=AdventureRepository(self.store.connection)
        app.bot.scores=self.store;app.bot.adventures=self.repo
        state=self.repo.get(s.session_id)
        self.assertEqual(state['_status'],'finished')
        self.assertEqual(state['correct_count'],1)
        self.assertEqual(len(state['reviews']),1)
        self.assertFalse(self.repo.recoverable())
        self.assertEqual(self.store.points(42),1)
