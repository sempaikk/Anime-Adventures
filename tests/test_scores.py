import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scores import ScoreStore


class ScoresTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / 'scores.sqlite3'
        self.legacy = self.root / 'scores.json'
        self.store = None

    def tearDown(self):
        if self.store:
            self.store.close()
        self.temp.cleanup()

    def test_award_is_atomic_and_idempotent_after_restart(self):
        self.store = ScoreStore(self.path)
        self.assertEqual(self.store.award('question1', 42, 'Player'), 1)
        self.assertEqual(self.store.award('question1', 42, 'Player'), 1)
        with self.assertRaises(ValueError):
            self.store.award('question1', 43, 'Other')
        self.assertEqual(self.store.award('question2', 42, 'New name'), 2)
        self.store.close()
        self.store = ScoreStore(self.path)
        self.assertEqual(self.store.award('question2', 42, 'New name'), 2)
        self.assertEqual(self.store.award('question3', 42, 'New name'), 3)

    def test_legacy_points_are_migrated_once_without_changing_original_file(self):
        original = json.dumps({'42': {'name': 'Player', 'points': 8, 'correct': 8}})
        self.legacy.write_text(original)
        self.store = ScoreStore(self.path, self.legacy)
        self.assertEqual(self.store.award('q1', 42, 'Player'), 9)
        self.assertEqual(self.legacy.read_text(), original)
        self.store.close()
        self.store = ScoreStore(self.path, self.legacy)
        self.assertEqual(self.store.award('q2', 42, 'Player'), 10)

    def test_bad_legacy_data_is_preserved_and_can_be_repaired(self):
        for bad in ['not json', '[]', '{"42":{"points":-4}}', '{"42":{"points":"8"}}']:
            self.legacy.write_text(bad)
            with self.assertRaises((ValueError, json.JSONDecodeError)):
                ScoreStore(self.path, self.legacy)
            self.assertEqual(self.legacy.read_text(), bad)
        self.legacy.write_text('{"42":{"name":"Player","points":8}}')
        self.store = ScoreStore(self.path, self.legacy)
        self.assertEqual(self.store.award('q1', 42, 'Player'), 9)

    def test_two_connections_do_not_overwrite_points(self):
        self.store = ScoreStore(self.path)
        other = ScoreStore(self.path)
        try:
            self.assertEqual(self.store.award('q1', 42, 'Player'), 1)
            self.assertEqual(other.award('q2', 42, 'Player'), 2)
            self.assertEqual(self.store.award('q3', 42, 'Player'), 3)
        finally:
            other.close()

    def test_failed_award_does_not_leave_partial_record(self):
        self.store = ScoreStore(self.path)
        self.store.connection.execute("CREATE TRIGGER fail_score BEFORE INSERT ON scores BEGIN SELECT RAISE(FAIL, 'disk'); END")
        with self.assertRaises(sqlite3.Error):
            self.store.award('q1', 42, 'Player')
        self.assertEqual(self.store.connection.execute('SELECT COUNT(*) FROM awards').fetchone()[0], 0)
