"""Bounded match snapshots, review history and privately moderated question reports."""

import json
import sqlite3
import time
import logging

MAX_SNAPSHOT_BYTES = 512 * 1024
RECOVERY_TTL = 86400
HISTORY_TTL = 7 * 86400
MAX_HISTORY_BYTES = 32 * 1024 * 1024
MAX_HISTORY_ROWS = 500
MAX_MESSAGE_CONTEXTS = 20000
log = logging.getLogger('adventures.repository')


class AdventureRepository:
    def __init__(self, connection, *, clock=None):
        self.connection = connection
        self.clock = clock or time.time
        connection.executescript('''
            CREATE TABLE IF NOT EXISTS adventure_sessions (
                id TEXT PRIMARY KEY, channel_id TEXT NOT NULL, guild_id TEXT NOT NULL,
                status TEXT NOT NULL, state TEXT NOT NULL, updated_at REAL NOT NULL);
            CREATE UNIQUE INDEX IF NOT EXISTS one_open_adventure_per_channel ON adventure_sessions(channel_id)
                WHERE status IN ('lobby','active','suspended','recovery');
            CREATE INDEX IF NOT EXISTS adventure_expiry ON adventure_sessions(updated_at);
            CREATE TABLE IF NOT EXISTS adventure_messages (
                message_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                question_id TEXT, resolved INTEGER NOT NULL, created_at REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS adventure_messages_expiry ON adventure_messages(created_at);
            CREATE TABLE IF NOT EXISTS question_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id TEXT NOT NULL, channel_id TEXT NOT NULL,
                user_id TEXT NOT NULL, stage TEXT NOT NULL, question_id TEXT NOT NULL,
                reason TEXT NOT NULL, created_at REAL NOT NULL, reviewed_by TEXT, reviewed_at REAL,
                UNIQUE(user_id,stage,question_id));
            CREATE INDEX IF NOT EXISTS reports_user_time ON question_reports(user_id,created_at);
            CREATE INDEX IF NOT EXISTS reports_guild_queue ON question_reports(guild_id,reviewed_at);
        ''')

    def save(self, state, status):
        raw = json.dumps(state, ensure_ascii=False, separators=(',', ':'))
        if len(raw.encode()) > MAX_SNAPSHOT_BYTES:
            raise ValueError('A partida ultrapassou o limite de armazenamento.')
        with self.connection:
            self.connection.execute('''INSERT INTO adventure_sessions VALUES(?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET status=excluded.status,state=excluded.state,updated_at=excluded.updated_at''',
                (state['id'], str(state['channel_id']), str(state['guild_id']), status, raw, self.clock()))
            if status=='finished':
                self._trim_history()

    def _trim_history(self):
        self.connection.execute('''DELETE FROM adventure_sessions WHERE id IN (
            SELECT id FROM (SELECT id, ROW_NUMBER() OVER(ORDER BY updated_at DESC,rowid DESC) AS position,
                SUM(length(CAST(state AS BLOB))) OVER(ORDER BY updated_at DESC,rowid DESC) AS used_bytes
                FROM adventure_sessions WHERE status IN ('finished','invalid'))
            WHERE position>? OR used_bytes>?)''',(MAX_HISTORY_ROWS,MAX_HISTORY_BYTES))

    def get(self, identifier):
        row = self.connection.execute('SELECT state,status,updated_at FROM adventure_sessions WHERE id=?', (identifier,)).fetchone()
        if not row or row[2] < self.clock() - HISTORY_TTL:
            return None
        try:
            state = json.loads(row[0])
            if not isinstance(state,dict) or state.get('id')!=identifier:
                raise ValueError('Invalid snapshot')
        except (ValueError,TypeError):
            with self.connection:
                self.connection.execute("UPDATE adventure_sessions SET status='invalid' WHERE id=?",(identifier,))
            log.warning('Checkpoint inválido isolado: %s; pontos preservados.',identifier)
            return None
        return {**state, '_status': row[1], '_updated_at': row[2]}

    def open_channel(self, channel_id):
        with self.connection:
            self.connection.execute("UPDATE adventure_sessions SET status='finished' WHERE channel_id=? AND status!='finished' AND updated_at<?",
                                    (str(channel_id),self.clock()-RECOVERY_TTL))
        row = self.connection.execute('''SELECT id FROM adventure_sessions WHERE channel_id=?
            AND status IN ('lobby','active','suspended','recovery')''', (str(channel_id),)).fetchone()
        return self.get(row[0]) if row else None

    def recoverable(self):
        self.cleanup()
        return [self.get(row[0]) for row in self.connection.execute('''SELECT id FROM adventure_sessions
            WHERE status IN ('lobby','active','suspended','recovery') AND updated_at>=?
            ORDER BY updated_at DESC LIMIT 50''', (self.clock() - RECOVERY_TTL,))]

    def context(self, message_id):
        row = self.connection.execute('''SELECT session_id,question_id,resolved FROM adventure_messages
            WHERE message_id=? AND created_at>=?''', (str(message_id), self.clock() - HISTORY_TTL)).fetchone()
        if not row:
            return None
        state = self.get(row[0])
        return {'session': state, 'question_id': row[1], 'resolved': bool(row[2])} if state else None

    def remember_message(self, message_id, session_id, question_id=None, *, resolved=False):
        with self.connection:
            self.connection.execute('INSERT OR REPLACE INTO adventure_messages VALUES(?,?,?,?,?)',
                                    (str(message_id), session_id, question_id, int(resolved), self.clock()))

    def award_for(self, message_id):
        row = self.connection.execute('''SELECT a.user_id,a.credited,COALESCE(s.name,a.user_id),COALESCE(s.points,0)
            FROM awards a LEFT JOIN scores s ON a.user_id=s.user_id WHERE a.question_id=?''', (str(message_id),)).fetchone()
        return {'user_id': int(row[0]), 'credited': bool(row[1]), 'name': row[2], 'total': row[3]} if row else None

    def report(self, message_id, guild_id, channel_id, user_id, reason):
        context = self.context(message_id)
        if (not context or not context['resolved'] or not context['question_id']
                or str(context['session']['guild_id']) != str(guild_id)
                or str(context['session']['channel_id']) != str(channel_id)):
            raise ValueError('Só é possível sinalizar uma pergunta já encerrada neste canal.')
        reason = reason.strip()
        if not 5 <= len(reason) <= 400:
            raise ValueError('Descreva o problema em 5 a 400 caracteres.')
        with self.connection:
            self.connection.execute('BEGIN IMMEDIATE')
            duplicate = self.connection.execute('SELECT 1 FROM question_reports WHERE user_id=? AND stage=? AND question_id=?',
                (str(user_id), context['session']['stage'], context['question_id'])).fetchone()
            if duplicate:
                raise ValueError('Você já sinalizou essa pergunta. Esse aviso já está registrado.')
            count = self.connection.execute('SELECT COUNT(*) FROM question_reports WHERE user_id=? AND created_at>?',
                                           (str(user_id), self.clock() - 86400)).fetchone()[0]
            if count >= 5:
                raise ValueError('Você já enviou cinco avisos nas últimas 24h. Espere para enviar outro.')
            if self.connection.execute('SELECT COUNT(*) FROM question_reports').fetchone()[0] >= 5000:
                raise ValueError('A fila de avisos atingiu o limite. Tente novamente depois da revisão.')
            self.connection.execute('''INSERT INTO question_reports
                (guild_id,channel_id,user_id,stage,question_id,reason,created_at) VALUES(?,?,?,?,?,?,?)''',
                (str(guild_id),str(channel_id),str(user_id),context['session']['stage'],context['question_id'],reason,self.clock()))

    def reports(self, guild_id, page=0):
        total = self.connection.execute('SELECT COUNT(*) FROM question_reports WHERE guild_id=? AND reviewed_at IS NULL', (str(guild_id),)).fetchone()[0]
        page = max(0, min(page, max(0, (total - 1) // 3)))
        rows = self.connection.execute('''SELECT id,question_id,reason FROM question_reports
            WHERE guild_id=? AND reviewed_at IS NULL ORDER BY id LIMIT 3 OFFSET ?''', (str(guild_id), page * 3)).fetchall()
        return {'page': page, 'total': total, 'items': [{'id': r[0], 'question_id': r[1], 'reason': r[2]} for r in rows]}

    def review_report(self, report_id, guild_id, user_id):
        with self.connection:
            return self.connection.execute('''UPDATE question_reports SET reviewed_by=?,reviewed_at=?
                WHERE id=? AND guild_id=? AND reviewed_at IS NULL''',
                (str(user_id),self.clock(),report_id,str(guild_id))).rowcount == 1

    def cleanup(self):
        now = self.clock()
        with self.connection:
            self.connection.execute("UPDATE adventure_sessions SET status='finished' WHERE status!='finished' AND updated_at<?", (now - RECOVERY_TTL,))
            self.connection.execute('DELETE FROM adventure_sessions WHERE id IN (SELECT id FROM adventure_sessions WHERE updated_at<? LIMIT 1000)', (now - HISTORY_TTL,))
            self.connection.execute('DELETE FROM adventure_messages WHERE message_id IN (SELECT message_id FROM adventure_messages WHERE created_at<? LIMIT 1000)', (now - HISTORY_TTL,))
            self.connection.execute('DELETE FROM question_reports WHERE id IN (SELECT id FROM question_reports WHERE created_at<? LIMIT 1000)', (now - 30 * 86400,))
            self._trim_history()
            self.connection.execute('''DELETE FROM adventure_messages WHERE message_id IN (
                SELECT message_id FROM adventure_messages ORDER BY created_at DESC LIMIT -1 OFFSET ?)''',(MAX_MESSAGE_CONTEXTS,))
