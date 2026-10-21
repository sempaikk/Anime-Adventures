import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from adventure_repository import AdventureRepository, MAX_SNAPSHOT_BYTES
from scores import ScoreStore
from storage_maintenance import snapshot_database


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'scores.sqlite3'
        self.store = ScoreStore(self.path)
        self.addCleanup(self.store.close)
        self.now = [1800000000.0]
        self.repo = AdventureRepository(self.store.connection,clock=lambda:self.now[0])
        self.state = {'id':'a'*32,'channel_id':20,'guild_id':10,'stage':'release','performance':{},'reviews':[]}
        self.repo.save(self.state,'active')

    def context(self,index):
        self.repo.remember_message(str(index),'a'*32,'question:'+str(index),resolved=True)

    def test_only_one_open_game_per_channel_and_finished_history_does_not_block_new_game(self):
        other = {**self.state,'id':'b'*32}
        with self.assertRaises(sqlite3.IntegrityError):
            self.repo.save(other,'active')
        self.repo.save(self.state,'finished')
        self.repo.save(other,'lobby')
        self.assertEqual(self.repo.open_channel(20)['id'],'b'*32)
        self.assertIsNotNone(self.repo.get('a'*32))

    def test_restart_preserves_context_reports_and_private_review_state(self):
        self.context(1)
        self.repo.report(1,10,20,42,'A resposta precisa de revisão.')
        another = ScoreStore(self.path)
        try:
            repo = AdventureRepository(another.connection,clock=lambda:self.now[0])
            self.assertEqual(repo.context(1)['question_id'],'question:1')
            self.assertEqual(repo.reports(10)['total'],1)
            self.assertEqual(repo.get('a'*32)['stage'],'release')
        finally:
            another.close()

    def test_reporting_before_reveal_or_from_another_scope_is_rejected(self):
        self.repo.remember_message(1,'a'*32,'q:one',resolved=False)
        with self.assertRaises(ValueError):
            self.repo.report(1,10,20,42,'Ainda não acabou.')
        self.context(2)
        for guild,channel in [(99,20),(10,99)]:
            with self.assertRaises(ValueError):
                self.repo.report(2,guild,channel,42,'Essa pergunta tem problema.')
        self.assertEqual(self.repo.reports(10)['total'],0)

    def test_duplicate_and_daily_report_limits_do_not_extend_the_window(self):
        for i in range(1,7):
            self.context(i)
        self.repo.report(1,10,20,42,'Primeiro aviso válido.')
        with self.assertRaises(ValueError):
            self.repo.report(1,10,20,42,'Não pode duplicar.')
        for i in range(2,6):
            self.repo.report(i,10,20,42,'Outro aviso válido.')
        with self.assertRaises(ValueError):
            self.repo.report(6,10,20,42,'Sexto aviso no mesmo dia.')
        self.now[0] += 86400
        self.repo.report(6,10,20,42,'Agora passou a janela.')
        self.assertEqual(self.repo.reports(10)['total'],6)

    def test_moderation_is_scoped_and_reviewing_never_changes_global_scores(self):
        self.context(1)
        self.store.award('original',42,'Player')
        self.repo.report(1,10,20,42,'Revisar a fonte desta resposta.')
        identifier = self.repo.reports(10)['items'][0]['id']
        self.assertFalse(self.repo.review_report(identifier,99,78))
        self.assertTrue(self.repo.review_report(identifier,10,78))
        self.assertFalse(self.repo.review_report(identifier,10,78))
        self.assertEqual(self.repo.reports(10)['total'],0)
        self.assertEqual(self.store.points(42),1)

    def test_expired_recovery_releases_channel_and_cleanup_preserves_total_scores(self):
        self.store.award('original',42,'Player')
        self.context(1)
        self.repo.report(1,10,20,42,'Um aviso para revisar depois.')
        self.now[0] += 86401
        self.assertIsNone(self.repo.open_channel(20))
        self.assertFalse(self.repo.recoverable())
        self.assertIsNotNone(self.repo.get('a'*32))
        self.now[0] += 31*86400
        self.repo.cleanup()
        self.assertIsNone(self.repo.get('a'*32))
        self.assertIsNone(self.repo.context(1))
        self.assertEqual(self.repo.reports(10)['total'],0)
        self.assertEqual(self.store.points(42),1)

    def test_invalid_report_lengths_and_oversized_state_cannot_replace_saved_state(self):
        self.context(1)
        for reason in ('','four','x'*401):
            with self.assertRaises(ValueError):
                self.repo.report(1,10,20,42,reason)
        with self.assertRaises(ValueError):
            self.repo.save({**self.state,'bad':'x'*MAX_SNAPSHOT_BYTES},'active')
        self.assertNotIn('bad',self.repo.get('a'*32))

    def test_corrupt_checkpoint_is_isolated_without_stopping_other_recovery_or_points(self):
        self.store.award('original',42,'Player')
        self.repo.save({**self.state,'id':'b'*32,'channel_id':21},'active')
        with self.store.connection:
            self.store.connection.execute('UPDATE adventure_sessions SET state=? WHERE id=?',('not json','a'*32))
        with self.assertLogs('adventures.repository',level='WARNING'):
            recovered=self.repo.recoverable()
        self.assertEqual([s['id'] for s in recovered if s],['b'*32])
        self.assertIsNone(self.repo.open_channel(20))
        self.assertEqual(self.store.points(42),1)

    def test_database_snapshot_recovers_matches_reports_and_points_together(self):
        self.context(1);self.store.award('original',42,'Player')
        self.repo.report(1,10,20,42,'Conferir esta resposta histórica.')
        destination=Path(self.temp.name)/'backup.sqlite3'
        snapshot_database(self.path,destination)
        restored=ScoreStore(destination)
        try:
            repo=AdventureRepository(restored.connection,clock=lambda:self.now[0])
            self.assertEqual(restored.points(42),1)
            self.assertEqual(repo.get('a'*32)['channel_id'],20)
            self.assertEqual(repo.reports(10)['total'],1)
            self.assertEqual(repo.context(1)['question_id'],'question:1')
        finally:
            restored.close()

    def test_history_budget_prunes_old_finished_games_without_touching_active_game_or_points(self):
        self.store.award('original',42,'Player')
        with patch('adventure_repository.MAX_HISTORY_BYTES',2500):
            for i in range(4):
                self.now[0]+=1
                self.repo.save({**self.state,'id':str(i)*32,'channel_id':100+i,'notes':'x'*1000},'finished')
        self.assertIsNone(self.repo.get('0'*32))
        self.assertIsNotNone(self.repo.get('3'*32))
        self.assertIsNotNone(self.repo.get('a'*32))
        self.assertEqual(self.store.points(42),1)

    def test_expired_report_identifiers_are_never_reused_by_new_reports(self):
        self.context(1);self.repo.report(1,10,20,42,'Primeiro aviso nesta pergunta.')
        original=self.repo.reports(10)['items'][0]['id']
        self.now[0]+=31*86400;self.repo.cleanup()
        self.repo.save(self.state,'active');self.context(2)
        self.repo.report(2,10,20,42,'Novo aviso depois da limpeza.')
        self.assertGreater(self.repo.reports(10)['items'][0]['id'],original)
