from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

import discord

from scores import AwardResult, ScoreStore


class AntifarmTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'scores.sqlite3'
        self.now = [1800000000.0]
        self.sequence = 0
        self.store = ScoreStore(self.path, clock=lambda: self.now[0])

    def tearDown(self):
        self.store.close()

    def message_id(self):
        self.sequence += 1
        return str(discord.utils.time_snowflake(datetime.fromtimestamp(self.now[0], timezone.utc)) + self.sequence)

    def credit(self, content='summon:cost', actor=42):
        return self.store.credit(self.message_id(), actor, 'Player', content_id=content)

    def test_same_question_in_another_channel_or_session_does_not_credit_twice(self):
        self.assertEqual(self.credit(), AwardResult(1, True))
        self.assertEqual(self.credit(), AwardResult(1, False))
        self.assertEqual(self.store.points(42), 1)
        self.assertEqual(self.store.connection.execute('SELECT COUNT(*) FROM awards').fetchone()[0], 2)

    def test_other_questions_and_other_players_remain_eligible(self):
        self.credit()
        self.assertEqual(self.credit('trait:item'), AwardResult(2, True))
        self.assertEqual(self.credit(actor=99), AwardResult(1, True))

    def test_window_is_24_hours_and_rejected_repeats_do_not_extend_it(self):
        self.credit()
        self.now[0] += 86399
        self.assertEqual(self.credit(), AwardResult(1, False))
        self.now[0] += 1
        self.assertEqual(self.credit(), AwardResult(2, True))

    def test_antifarm_survives_restart(self):
        self.credit()
        self.store.close()
        self.store = ScoreStore(self.path, clock=lambda: self.now[0])
        self.assertEqual(self.credit(), AwardResult(1, False))

    def test_receipt_retry_does_not_duplicate_points_or_change_the_winner(self):
        identifier = self.message_id()
        for _ in range(3):
            self.assertEqual(self.store.credit(identifier, 42, 'Player', content_id='summon:cost'), AwardResult(1, True))
        with self.assertRaises(ValueError):
            self.store.credit(identifier, 99, 'Other', content_id='summon:cost')
        self.assertEqual(self.store.points(42), 1)
        self.assertEqual(self.store.points(99), 0)

    def test_two_connections_racing_for_same_player_and_question_credit_once(self):
        self.store.close()
        gate = threading.Barrier(2)
        identifiers = [self.message_id(), self.message_id()]

        def attempt(index):
            store = ScoreStore(self.path, clock=lambda: self.now[0])
            try:
                gate.wait(timeout=5)
                return store.credit(identifiers[index], 42, 'Player', content_id='summon:cost')
            finally:
                store.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, range(2)))
        self.store = ScoreStore(self.path, clock=lambda: self.now[0])
        self.assertEqual(sum(r.credited for r in results), 1)
        self.assertTrue(all(r.total == 1 for r in results))
        self.assertEqual(self.store.points(42), 1)

    def test_legacy_sqlite_schema_and_points_are_preserved(self):
        self.store.close()
        self.path.unlink()
        with sqlite3.connect(self.path) as db:
            db.executescript('''CREATE TABLE scores(user_id TEXT PRIMARY KEY, name TEXT, points INTEGER);
                CREATE TABLE awards(question_id TEXT PRIMARY KEY, user_id TEXT);
                CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);
                INSERT INTO scores VALUES ('42','Player',8);
                INSERT INTO awards VALUES ('old-message','42');
                INSERT INTO metadata VALUES ('legacy_imported','1');''')
        self.store = ScoreStore(self.path, clock=lambda: self.now[0])
        self.assertEqual(self.store.points(42), 8)
        self.assertEqual(self.store.award('old-message', 42, 'Player'), 8)
        self.assertEqual(self.credit(), AwardResult(9, True))

    def test_expired_receipts_are_pruned_without_removing_totals(self):
        old_id = self.message_id()
        self.store.credit(old_id, 42, 'Player', content_id='summon:cost')
        self.now[0] += 31 * 86400
        self.assertEqual(self.credit('trait:item'), AwardResult(2, True))
        self.assertIsNone(self.store.connection.execute('SELECT 1 FROM awards WHERE question_id=?', (old_id,)).fetchone())
        self.assertEqual(self.store.points(42), 2)
        with self.assertRaises(ValueError):
            self.store.credit(old_id, 42, 'Player', content_id='summon:cost')
        self.assertEqual(self.store.points(42), 2)

    def test_cleanup_still_runs_after_an_hour_of_regular_activity(self):
        old_id = self.message_id()
        self.store.credit(old_id, 42, 'Player', content_id='old')
        with self.store.connection:
            self.store.connection.execute('UPDATE awards SET awarded_at=?', (self.now[0] - 31 * 86400,))
        self.now[0] += 3599
        self.credit('recent-one')
        self.assertIsNotNone(self.store.connection.execute('SELECT 1 FROM awards WHERE question_id=?', (old_id,)).fetchone())
        self.now[0] += 2
        self.credit('recent-two')
        self.assertIsNone(self.store.connection.execute('SELECT 1 FROM awards WHERE question_id=?', (old_id,)).fetchone())
        self.assertEqual(self.store.points(42), 3)

    def test_large_cleanup_is_batched_without_deleting_any_player_points(self):
        self.credit('first')
        with self.store.connection:
            self.store.connection.executemany('''INSERT INTO awards
                (question_id,user_id,content_id,awarded_at,credited) VALUES (?,?,?,?,?)''',
                [(str(i), '42', 'expired', self.now[0] - 31 * 86400, 0) for i in range(1005)])
        self.now[0] += 3601
        self.credit('second')
        self.assertEqual(self.store.connection.execute("SELECT COUNT(*) FROM awards WHERE content_id='expired'").fetchone()[0], 5)
        self.credit('third')
        self.assertEqual(self.store.connection.execute("SELECT COUNT(*) FROM awards WHERE content_id='expired'").fetchone()[0], 0)
        self.assertEqual(self.store.points(42), 3)
