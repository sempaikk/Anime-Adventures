"""Atomic score updates and one-time migration of the original scores.json."""

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

AWARD_RETENTION = 30 * 86400
DISCORD_EPOCH = 1420070400

@dataclass(frozen=True)
class AwardResult:
    total: int
    credited: bool


class ScoreStore:
    def __init__(self, path: Path, legacy_path: Path | None = None, *, clock=None):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.clock = clock or time.time
        self.last_cleanup = None
        self.connection = sqlite3.connect(path, timeout=1.0)
        try:
            if self.connection.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
                raise sqlite3.DatabaseError('O banco de pontos falhou na verificação de integridade.')
            self.connection.execute("PRAGMA foreign_keys = ON")
            self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS scores (
                user_id TEXT PRIMARY KEY, name TEXT NOT NULL, points INTEGER NOT NULL CHECK(points >= 0)
            );
            CREATE TABLE IF NOT EXISTS awards (
                question_id TEXT PRIMARY KEY, user_id TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)
            with self.connection:
                columns = {row[1] for row in self.connection.execute('PRAGMA table_info(awards)')}
                for name, definition in [('content_id', 'TEXT'), ('awarded_at', 'REAL'),
                                         ('credited', 'INTEGER NOT NULL DEFAULT 1')]:
                    if name not in columns:
                        self.connection.execute(f'ALTER TABLE awards ADD COLUMN {name} {definition}')
                self.connection.execute('''CREATE INDEX IF NOT EXISTS awards_recent_content
                    ON awards(user_id, content_id, awarded_at) WHERE credited=1''')
                self.connection.execute('''CREATE INDEX IF NOT EXISTS awards_expiry
                    ON awards(awarded_at) WHERE content_id IS NOT NULL''')
            self._migrate(legacy_path)
        except Exception:
            self.connection.close()
            raise

    def _migrate(self, legacy_path):
        if self.connection.execute("SELECT 1 FROM metadata WHERE key='legacy_imported'").fetchone():
            return
        records = {}
        if legacy_path is not None and legacy_path.exists():
            records = json.loads(legacy_path.read_text(encoding="utf-8"))
            if not isinstance(records, dict):
                raise ValueError("scores.json inválido; o arquivo original foi preservado.")
        # Validate everything before importing anything; never silently replace damaged scores.
        rows = []
        for user_id, record in records.items():
            if not isinstance(record, dict) or not str(user_id).isdigit():
                raise ValueError("Registro inválido em scores.json.")
            points = record.get("points", 0)
            if type(points) is not int or points < 0:
                raise ValueError("Pontuação inválida em scores.json.")
            rows.append((str(user_id), str(record.get("name", user_id)), points))
        with self.connection:
            self.connection.executemany("INSERT OR IGNORE INTO scores VALUES (?, ?, ?)", rows)
            self.connection.execute("INSERT INTO metadata VALUES ('legacy_imported', '1')")

    def award(self, question_id: str, user_id: int, name: str) -> int:
        """Compatibility helper for trusted imports and existing callers."""
        return self.credit(question_id, user_id, name).total

    def credit(self, question_id: str, user_id: int, name: str, *, content_id: str | None = None) -> AwardResult:
        """Record one winner; a canonical question credits each user once in 24h."""
        uid = str(user_id)
        now = self.clock()
        if content_id is not None:
            if not question_id.isdigit():
                raise ValueError('A rodada precisa ter um identificador de mensagem do Discord.')
            created_at = (int(question_id) >> 22) / 1000 + DISCORD_EPOCH
            if created_at < now - AWARD_RETENTION:
                raise ValueError('Essa rodada já expirou e não pode receber novos créditos.')
        with self.connection:
            # This serializes the eligibility check and write across SQLite connections.
            self.connection.execute('BEGIN IMMEDIATE')
            existing = self.connection.execute(
                "SELECT user_id, credited FROM awards WHERE question_id=?", (question_id,)
            ).fetchone()
            if existing and existing[0] != uid:
                raise ValueError("A pergunta já teve outro vencedor.")
            if existing:
                return AwardResult(self.points(user_id), bool(existing[1]))
            cleanup_due = self.last_cleanup is None or now - self.last_cleanup >= 3600
            if cleanup_due:
                removed = self.connection.execute('''DELETE FROM awards WHERE question_id IN (
                    SELECT question_id FROM awards WHERE content_id IS NOT NULL AND awarded_at<?
                    ORDER BY awarded_at LIMIT 1000)''', (now - AWARD_RETENTION,)).rowcount
            recent = content_id is not None and self.connection.execute('''
                SELECT 1 FROM awards WHERE user_id=? AND content_id=?
                    AND credited=1 AND awarded_at>? LIMIT 1
                ''', (uid, content_id, now - 86400)).fetchone()
            credited = not bool(recent)
            self.connection.execute('''INSERT INTO awards
                (question_id, user_id, content_id, awarded_at, credited) VALUES (?, ?, ?, ?, ?)''',
                (question_id, uid, content_id, now, int(credited)))
            if credited:
                self.connection.execute("""
                    INSERT INTO scores VALUES (?, ?, 1)
                    ON CONFLICT(user_id) DO UPDATE SET name=excluded.name, points=scores.points+1
                """, (uid, name))
            result = AwardResult(self.points(user_id), credited)
        if cleanup_due:
            self.last_cleanup = None if removed == 1000 else now
        return result

    def points(self, user_id: int) -> int:
        row = self.connection.execute("SELECT points FROM scores WHERE user_id=?", (str(user_id),)).fetchone()
        return row[0] if row else 0

    def close(self):
        self.connection.close()
