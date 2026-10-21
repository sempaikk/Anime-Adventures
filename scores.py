"""Atomic score updates and one-time migration of the original scores.json."""

import json
import sqlite3
from pathlib import Path


class ScoreStore:
    def __init__(self, path: Path, legacy_path: Path | None = None):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
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
        try:
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
        uid = str(user_id)
        with self.connection:
            existing = self.connection.execute(
                "SELECT user_id FROM awards WHERE question_id=?", (question_id,)
            ).fetchone()
            if existing and existing[0] != uid:
                raise ValueError("A pergunta já teve outro vencedor.")
            if not existing:
                self.connection.execute("INSERT INTO awards VALUES (?, ?)", (question_id, uid))
                self.connection.execute("""
                    INSERT INTO scores VALUES (?, ?, 1)
                    ON CONFLICT(user_id) DO UPDATE SET name=excluded.name, points=scores.points+1
                """, (uid, name))
            return self.connection.execute("SELECT points FROM scores WHERE user_id=?", (uid,)).fetchone()[0]

    def close(self):
        self.connection.close()
