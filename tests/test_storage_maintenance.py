import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scores import ScoreStore
from storage_maintenance import maintain_storage, snapshot_database, verify_database


class StorageMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'scores.sqlite3'
        self.backup = self.root / 'backups' / 'scores-latest.sqlite3'
        self.store = ScoreStore(self.path)
        self.addCleanup(self.store.close)
        self.store.award('original', 42, 'Player')

    def test_snapshot_restores_totals_and_duplicate_receipts_independently(self):
        snapshot_database(self.path, self.backup)
        restored_path = self.root / 'restored.sqlite3'
        shutil.copy2(self.backup, restored_path)
        restored = ScoreStore(restored_path)
        try:
            self.assertEqual(restored.points(42), 1)
            self.assertEqual(restored.award('original', 42, 'Player'), 1)
            self.assertEqual(restored.award('next', 42, 'Player'), 2)
            self.assertEqual(self.store.points(42), 1)
        finally:
            restored.close()

    def test_snapshot_reads_committed_data_without_committing_live_transaction(self):
        self.store.connection.execute("UPDATE scores SET points=99 WHERE user_id='42'")
        snapshot_database(self.path, self.backup)
        with sqlite3.connect(self.backup) as copied:
            self.assertEqual(copied.execute('SELECT points FROM scores').fetchone()[0], 1)
        self.store.connection.rollback()
        self.assertEqual(self.store.points(42), 1)

    def test_low_space_keeps_both_live_database_and_previous_snapshot(self):
        snapshot_database(self.path, self.backup)
        original = self.backup.read_bytes()
        with patch('storage_maintenance.shutil.disk_usage', return_value=SimpleNamespace(free=1)):
            with self.assertRaises(OSError):
                snapshot_database(self.path, self.backup)
        self.assertEqual(self.backup.read_bytes(), original)
        self.assertEqual(self.store.points(42), 1)
        self.assertEqual(list(self.backup.parent.glob('.scores-backup-*')), [])

    def test_corrupt_source_and_timeout_cannot_replace_a_good_snapshot(self):
        snapshot_database(self.path, self.backup)
        original = self.backup.read_bytes()
        corrupt = self.root / 'corrupt.sqlite3'
        corrupt.write_bytes(b'not a database')
        with self.assertRaises(sqlite3.DatabaseError):
            snapshot_database(corrupt, self.backup)
        with self.assertRaises(TimeoutError):
            snapshot_database(self.path, self.backup, timeout=0)
        self.assertEqual(self.backup.read_bytes(), original)
        self.assertEqual(list(self.backup.parent.glob('.scores-backup-*')), [])

    def test_read_only_verification_does_not_create_a_missing_database(self):
        missing = self.root / 'missing.sqlite3'
        with self.assertRaises(sqlite3.Error):
            verify_database(missing)
        self.assertFalse(missing.exists())
        with self.assertRaises(ValueError):
            snapshot_database(self.path, self.path)
        self.assertEqual(self.store.points(42), 1)

    def test_daily_maintenance_keeps_one_snapshot_and_refreshes_after_24h(self):
        first = maintain_storage(self.path)
        timestamp = self.backup.stat().st_mtime
        self.assertEqual(first['backup'], 'created')
        self.store.award('next', 42, 'Player')
        self.assertEqual(maintain_storage(self.path, now=timestamp + 86399)['backup'], 'fresh')
        self.assertEqual(self.backup.stat().st_mtime, timestamp)
        self.assertEqual(maintain_storage(self.path, now=timestamp + 86400)['backup'], 'created')
        with sqlite3.connect(self.backup) as copied:
            self.assertEqual(copied.execute('SELECT points FROM scores').fetchone()[0], 2)
        self.assertEqual(list(self.backup.parent.iterdir()), [self.backup])

    def test_invalid_live_database_is_preserved_and_startup_fails_clearly(self):
        broken = self.root / 'broken.sqlite3'
        broken.write_bytes(b'broken database bytes')
        before = broken.read_bytes()
        with self.assertRaises(sqlite3.DatabaseError):
            ScoreStore(broken)
        self.assertEqual(broken.read_bytes(), before)
