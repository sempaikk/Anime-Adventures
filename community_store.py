"""Bounded community state. The archived quiz database is never migrated or erased."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import shutil
import sqlite3
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

from community_domain import (
    CONSENT_VERSION,
    MODES,
    ROLES,
    REVIEW_WINDOW,
    TIERS,
    clean_text,
    consensus,
    validate_chat,
)


COMMUNITY_TABLES = {
    "community_meta",
    "community_channels",
    "community_reviews",
    "community_relays",
}
STABLE_SECONDS = 15 * 60
MOVE_INTERVAL = 60 * 60
MAX_RELAYS = 100_000
MAX_PENDING = 1000
MAX_DATABASE_BYTES = 128 * 1024 * 1024


class CommunityStore:
    def __init__(self, path, *, clock=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock or time.time
        self.connection = sqlite3.connect(self.path, timeout=1)
        self.connection.row_factory = sqlite3.Row
        if self.connection.execute("PRAGMA quick_check").fetchall()[0][0] != "ok":
            self.connection.close()
            raise sqlite3.DatabaseError(
                "O banco da comunidade falhou na verificação de integridade."
            )
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS community_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS community_channels(
          guild_id TEXT NOT NULL,kind TEXT NOT NULL,channel_id TEXT UNIQUE NOT NULL,guild_name TEXT NOT NULL,
          role TEXT NOT NULL DEFAULT 'damage',mode TEXT NOT NULL DEFAULT 'general',
          scope TEXT NOT NULL DEFAULT 'global',panel_id TEXT,input_mode TEXT NOT NULL DEFAULT 'messages',
          PRIMARY KEY(guild_id,kind));
        CREATE TABLE IF NOT EXISTS community_consents(
          user_id TEXT PRIMARY KEY,version INTEGER NOT NULL,accepted_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS community_blocks(
          user_id TEXT PRIMARY KEY,reason TEXT NOT NULL,created_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS community_reviews(
          id INTEGER PRIMARY KEY AUTOINCREMENT,user_id TEXT NOT NULL,guild_id TEXT NOT NULL,
          unit_id TEXT NOT NULL,period TEXT NOT NULL,role TEXT NOT NULL,mode TEXT NOT NULL,
          score INTEGER NOT NULL CHECK(score BETWEEN 0 AND 4),reason TEXT NOT NULL,conditions TEXT NOT NULL,
          evidence TEXT NOT NULL,share_global INTEGER NOT NULL,created_at REAL NOT NULL,updated_at REAL NOT NULL,
          UNIQUE(user_id,guild_id,unit_id,period,role,mode));
        CREATE INDEX IF NOT EXISTS community_reviews_context
          ON community_reviews(period,role,mode,unit_id,updated_at);
        CREATE TABLE IF NOT EXISTS community_mentions(
          actor_hash TEXT NOT NULL,guild_id TEXT NOT NULL,unit_id TEXT NOT NULL,period TEXT NOT NULL,
          day INTEGER NOT NULL,created_at REAL NOT NULL,PRIMARY KEY(actor_hash,unit_id,period,day));
        CREATE TABLE IF NOT EXISTS community_tiers(
          scope TEXT NOT NULL,period TEXT NOT NULL,unit_id TEXT NOT NULL,role TEXT NOT NULL,mode TEXT NOT NULL,
          tier TEXT,candidate TEXT,candidate_since REAL,changed_at REAL NOT NULL DEFAULT 0,
          metrics TEXT NOT NULL,basis TEXT NOT NULL DEFAULT 'community',
          PRIMARY KEY(scope,period,unit_id,role,mode));
        CREATE TABLE IF NOT EXISTS community_changes(
          id INTEGER PRIMARY KEY AUTOINCREMENT,scope TEXT NOT NULL,period TEXT NOT NULL,unit_id TEXT NOT NULL,
          role TEXT NOT NULL,mode TEXT NOT NULL,old_tier TEXT,new_tier TEXT,reason TEXT NOT NULL,
          created_at REAL NOT NULL,basis TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS community_pending(
          id TEXT PRIMARY KEY,user_id TEXT NOT NULL,guild_id TEXT NOT NULL,channel_id TEXT NOT NULL,
          source_event TEXT UNIQUE NOT NULL,author_name TEXT NOT NULL,guild_name TEXT NOT NULL,
          body TEXT NOT NULL,created_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS community_relays(
          id TEXT PRIMARY KEY,source_event TEXT UNIQUE NOT NULL,user_id TEXT NOT NULL,guild_id TEXT NOT NULL,
          channel_id TEXT NOT NULL,author_name TEXT NOT NULL,guild_name TEXT NOT NULL,body TEXT NOT NULL,
          created_at REAL NOT NULL,status TEXT NOT NULL,original_id TEXT,original_state TEXT NOT NULL DEFAULT 'pending',
          reply_id TEXT);
        CREATE TABLE IF NOT EXISTS community_deliveries(
          id INTEGER PRIMARY KEY AUTOINCREMENT,relay_id TEXT NOT NULL REFERENCES community_relays(id) ON DELETE CASCADE,
          guild_id TEXT NOT NULL,channel_id TEXT NOT NULL,message_id TEXT,state TEXT NOT NULL,
          attempts INTEGER NOT NULL DEFAULT 0,next_try REAL NOT NULL DEFAULT 0,last_error TEXT,
          is_source INTEGER NOT NULL,UNIQUE(relay_id,channel_id));
        CREATE INDEX IF NOT EXISTS community_delivery_queue ON community_deliveries(state,next_try);
        CREATE TABLE IF NOT EXISTS community_reports(
          id INTEGER PRIMARY KEY AUTOINCREMENT,relay_id TEXT NOT NULL,user_id TEXT NOT NULL,guild_id TEXT NOT NULL,
          reason TEXT NOT NULL,created_at REAL NOT NULL,reviewed_at REAL,UNIQUE(relay_id,user_id));
        """)
        with self.connection:
            for key, value in (
                ("schema", "1"),
                ("period", "initial"),
                ("period_label", "Período inicial"),
                ("salt", secrets.token_hex(32)),
                ("revision", "0"),
                ("global_paused", "0"),
            ):
                self.connection.execute(
                    "INSERT OR IGNORE INTO community_meta VALUES(?,?)", (key, value)
                )
        self.dirty = True

    def close(self):
        self.connection.close()

    def _one(self, sql, args=()):
        row = self.connection.execute(sql, args).fetchone()
        return dict(row) if row else None

    def _all(self, sql, args=()):
        return [dict(row) for row in self.connection.execute(sql, args)]

    def get(self, key):
        row = self._one("SELECT value FROM community_meta WHERE key=?", (key,))
        return row["value"] if row else None

    def set(self, key, value):
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO community_meta VALUES(?,?)", (key, str(value))
            )

    def touch(self):
        self.connection.execute(
            "UPDATE community_meta SET value=CAST(value AS INTEGER)+1 WHERE key='revision'"
        )
        self.dirty = True

    def require_capacity(self):
        if (
            self.path.stat().st_size >= MAX_DATABASE_BYTES
            or shutil.disk_usage(self.path.parent).free < 16 * 1024 * 1024
        ):
            raise ValueError(
                "O armazenamento precisa de manutenção. O conteúdo existente foi preservado."
            )

    def configure(
        self,
        guild_id,
        guild_name,
        kind,
        channel_id,
        *,
        role="damage",
        mode="general",
        scope="global",
        input_mode="messages",
    ):
        if (
            kind not in ("global", "observe", "tier")
            or role not in ROLES
            or mode not in MODES
            or scope not in ("global", "server")
        ):
            raise ValueError("Escolha um tipo de canal e contexto válidos.")
        if input_mode not in ("messages", "form"):
            raise ValueError("Escolha mensagens ou formulário.")
        gid, cid = str(guild_id), str(channel_id)
        previous = self.channel(gid, kind)
        with self.connection:
            try:
                self.connection.execute(
                    """INSERT INTO community_channels(guild_id,kind,channel_id,guild_name,role,mode,scope,input_mode)
                  VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(guild_id,kind) DO UPDATE SET
                  channel_id=excluded.channel_id,guild_name=excluded.guild_name,role=excluded.role,mode=excluded.mode,
                  scope=excluded.scope,panel_id=NULL,input_mode=excluded.input_mode""",
                    (
                        gid,
                        kind,
                        cid,
                        clean_text(guild_name, 100),
                        role,
                        mode,
                        scope,
                        input_mode,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(
                    "Use canais diferentes para chat global, observação e tier list."
                ) from exc
            if previous and previous["channel_id"] != cid:
                self.connection.execute(
                    "UPDATE community_deliveries SET state='cancelled' WHERE channel_id=? AND state='queued'",
                    (previous["channel_id"],),
                )
                if kind == "global":
                    self.connection.execute(
                        "UPDATE community_deliveries SET state='cancelled' WHERE state='queued' AND relay_id IN (SELECT id FROM community_relays WHERE guild_id=?)",
                        (gid,),
                    )
            self.touch()

    def channel(self, guild_id, kind):
        return self._one(
            "SELECT * FROM community_channels WHERE guild_id=? AND kind=?",
            (str(guild_id), kind),
        )

    def channel_at(self, channel_id):
        return self._one(
            "SELECT * FROM community_channels WHERE channel_id=?", (str(channel_id),)
        )

    def channels(self, kind):
        return self._all(
            "SELECT * FROM community_channels WHERE kind=? ORDER BY guild_id", (kind,)
        )

    def disable(self, guild_id, kind):
        old = self.channel(guild_id, kind)
        with self.connection:
            self.connection.execute(
                "DELETE FROM community_channels WHERE guild_id=? AND kind=?",
                (str(guild_id), kind),
            )
            if old:
                self.connection.execute(
                    "UPDATE community_deliveries SET state='cancelled' WHERE channel_id=? AND state='queued'",
                    (old["channel_id"],),
                )
                if kind == "global":
                    self.connection.execute(
                        "UPDATE community_deliveries SET state='cancelled' WHERE state='queued' AND relay_id IN (SELECT id FROM community_relays WHERE guild_id=?)",
                        (str(guild_id),),
                    )
            self.touch()

    def set_panel(self, guild_id, kind, message_id):
        with self.connection:
            self.connection.execute(
                "UPDATE community_channels SET panel_id=? WHERE guild_id=? AND kind=?",
                (str(message_id), str(guild_id), kind),
            )

    def set_period(self, label):
        label = clean_text(label, 70)
        new_id = uuid.uuid4().hex[:16]
        with self.connection:
            self.connection.execute(
                "UPDATE community_meta SET value=? WHERE key='period'", (new_id,)
            )
            self.connection.execute(
                "UPDATE community_meta SET value=? WHERE key='period_label'", (label,)
            )
            self.touch()
        return new_id

    def consented(self, user_id):
        return bool(
            self._one(
                "SELECT 1 FROM community_consents WHERE user_id=? AND version=?",
                (str(user_id), CONSENT_VERSION),
            )
        )

    def consent(self, user_id):
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO community_consents VALUES(?,?,?)",
                (str(user_id), CONSENT_VERSION, self.clock()),
            )

    def withdraw(self, user_id):
        with self.connection:
            self.connection.execute(
                "DELETE FROM community_consents WHERE user_id=?", (str(user_id),)
            )
            self.connection.execute(
                "DELETE FROM community_pending WHERE user_id=?", (str(user_id),)
            )
            self.connection.execute(
                "UPDATE community_deliveries SET state='cancelled' WHERE state='queued' AND relay_id IN (SELECT id FROM community_relays WHERE user_id=?)",
                (str(user_id),),
            )

    def blocked(self, user_id):
        return bool(
            self._one("SELECT 1 FROM community_blocks WHERE user_id=?", (str(user_id),))
        )

    def block(self, user_id, reason):
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO community_blocks VALUES(?,?,?)",
                (str(user_id), clean_text(reason, 400), self.clock()),
            )
            self.connection.execute(
                "DELETE FROM community_consents WHERE user_id=?", (str(user_id),)
            )
            self.connection.execute(
                "DELETE FROM community_pending WHERE user_id=?", (str(user_id),)
            )
            self.connection.execute(
                "UPDATE community_deliveries SET state='cancelled' WHERE state='queued' AND relay_id IN (SELECT id FROM community_relays WHERE user_id=?)",
                (str(user_id),),
            )
            self.touch()

    def unblock(self, user_id):
        with self.connection:
            self.connection.execute(
                "DELETE FROM community_blocks WHERE user_id=?", (str(user_id),)
            )
            self.touch()

    def submit_review(
        self,
        user_id,
        guild_id,
        unit_id,
        role,
        mode,
        tier,
        reason,
        conditions="",
        evidence="",
        *,
        share_global=True,
    ):
        self.require_capacity()
        if self.blocked(user_id):
            raise ValueError(
                "Sua participação na rede está suspensa. Procure a moderação do bot."
            )
        if role not in ROLES or mode not in MODES or tier not in TIERS:
            raise ValueError("Escolha função, modo e tier válidos.")
        if not (self.channel(guild_id, "tier") or self.channel(guild_id, "observe")):
            raise ValueError(
                "Um administrador precisa ativar a tier list ou um canal de relatos neste servidor."
            )
        reason, conditions = clean_text(reason, 700), str(conditions).strip()
        if len(reason) < 25 or len(conditions) > 300:
            raise ValueError(
                "Explique o motivo em pelo menos 25 caracteres; as condições aceitam até 300."
            )
        evidence = str(evidence).strip()
        if evidence:
            parsed = urlparse(evidence)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or len(evidence) > 400
            ):
                raise ValueError(
                    "A demonstração precisa ser um link HTTPS público, sem credenciais."
                )
        uid, gid, period, now = (
            str(user_id),
            str(guild_id),
            self.get("period"),
            self.clock(),
        )
        args = (uid, gid, unit_id, period, role, mode)
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            previous = self._one(
                """SELECT updated_at FROM community_reviews
                WHERE user_id=? AND guild_id=? AND unit_id=? AND period=? AND role=? AND mode=?""",
                args,
            )
            latest = self._one(
                "SELECT MAX(updated_at) AS value FROM community_reviews WHERE user_id=?",
                (uid,),
            )
            if latest and latest["value"] is not None and now - latest["value"] < 60:
                raise ValueError("Espere um minuto entre avaliações.")
            if previous and now - previous["updated_at"] < 600:
                raise ValueError(
                    "Essa avaliação pode ser atualizada depois de dez minutos."
                )
            if (
                self.connection.execute(
                    "SELECT COUNT(*) FROM community_reviews WHERE user_id=? AND updated_at>?",
                    (uid, now - 86400),
                ).fetchone()[0]
                >= 40
            ):
                raise ValueError(
                    "Você chegou ao limite de 40 avaliações nas últimas 24 horas."
                )
            if (
                not previous
                and self.connection.execute(
                    "SELECT COUNT(*) FROM community_reviews"
                ).fetchone()[0]
                >= 50000
            ):
                raise ValueError("A coleta está em manutenção. Tente mais tarde.")
            self.connection.execute(
                """INSERT INTO community_reviews
                (user_id,guild_id,unit_id,period,role,mode,score,reason,conditions,evidence,share_global,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id,guild_id,unit_id,period,role,mode)
                DO UPDATE SET score=excluded.score,reason=excluded.reason,conditions=excluded.conditions,
                evidence=excluded.evidence,share_global=excluded.share_global,updated_at=excluded.updated_at""",
                (
                    *args,
                    TIERS.index(tier),
                    reason,
                    conditions,
                    evidence,
                    int(share_global),
                    now,
                    now,
                ),
            )
            self.touch()

    def reviews(self, unit_id, role, mode, *, scope="global", period=None):
        period = period or self.get("period")
        where = "r.share_global=1" if scope == "global" else "r.guild_id=?"
        args = [period, unit_id, role, mode, self.clock() - REVIEW_WINDOW]
        if scope != "global":
            args.append(scope.removeprefix("guild:"))
        # One person has one global vote, even after rating in several servers.
        return self._all(
            f"""SELECT * FROM (
            SELECT r.*,ROW_NUMBER() OVER(PARTITION BY r.user_id ORDER BY r.updated_at DESC,r.id DESC) AS position
            FROM community_reviews r WHERE period=? AND unit_id=? AND role=? AND mode=? AND updated_at>=?
            AND NOT EXISTS(SELECT 1 FROM community_blocks b WHERE b.user_id=r.user_id) AND {where})
            WHERE position=1 ORDER BY updated_at DESC""",
            args,
        )

    def record_mentions(self, user_id, guild_id, units):
        if self.blocked(user_id):
            return
        try:
            self.require_capacity()
        except ValueError:
            return
        salt = bytes.fromhex(self.get("salt"))
        actor = hmac.new(salt, str(user_id).encode(), hashlib.sha256).hexdigest()
        now, period = self.clock(), self.get("period")
        if (
            self.connection.execute(
                "SELECT COUNT(*) FROM community_mentions"
            ).fetchone()[0]
            >= 20000
        ):
            return
        with self.connection:
            for unit_id in sorted(units)[:5]:
                self.connection.execute(
                    "INSERT OR IGNORE INTO community_mentions VALUES(?,?,?,?,?,?)",
                    (actor, str(guild_id), unit_id, period, int(now // 86400), now),
                )

    def mentions(self, unit_id, *, guild_id=None):
        sql = "SELECT COUNT(*) FROM community_mentions WHERE unit_id=? AND period=? AND created_at>=?"
        args = [unit_id, self.get("period"), self.clock() - 7 * 86400]
        if guild_id is not None:
            sql += " AND guild_id=?"
            args.append(str(guild_id))
        return self.connection.execute(sql, args).fetchone()[0]

    def refresh_tiers(self):
        now, period = self.clock(), self.get("period")
        contexts = set()
        for row in self._all(
            "SELECT DISTINCT unit_id,role,mode,guild_id,share_global FROM community_reviews WHERE period=?",
            (period,),
        ):
            contexts.add(
                ("guild:" + row["guild_id"], row["unit_id"], row["role"], row["mode"])
            )
            if row["share_global"]:
                contexts.add(("global", row["unit_id"], row["role"], row["mode"]))
        contexts.update(
            (r["scope"], r["unit_id"], r["role"], r["mode"])
            for r in self._all(
                "SELECT * FROM community_tiers WHERE period=?", (period,)
            )
        )
        changes = []
        with self.connection:
            for scope, unit, role, mode in sorted(contexts):
                key = (scope, period, unit, role, mode)
                old = self._one(
                    "SELECT * FROM community_tiers WHERE scope=? AND period=? AND unit_id=? AND role=? AND mode=?",
                    key,
                )
                data = consensus(
                    self.reviews(unit, role, mode, scope=scope), local=scope != "global"
                )
                candidate, current = data["tier"], old["tier"] if old else None
                since = (
                    old["candidate_since"]
                    if old and old["candidate"] == candidate
                    else now
                ) or now
                changed_at = old["changed_at"] if old else 0
                basis = old["basis"] if old else "community"
                publish = candidate != current and (
                    (current is None and candidate is not None)
                    or (basis != "editorial" and candidate is None)
                    or (
                        candidate is not None
                        and now - since >= STABLE_SECONDS
                        and now - changed_at >= MOVE_INTERVAL
                    )
                )
                if publish:
                    reason = (
                        f"{data['eligible_players']} avaliações elegíveis; {data['eligible_servers']} servidores; "
                        f"{round(data['agreement'] * 100)}% de concordância entre as referências usadas."
                        if candidate
                        else "Os relatos atuais não atingem o mínimo de participação ou concordância."
                    )
                    self.connection.execute(
                        """INSERT INTO community_changes
                        (scope,period,unit_id,role,mode,old_tier,new_tier,reason,created_at,basis)
                        VALUES(?,?,?,?,?,?,?,?,?,?)""",
                        (*key, current, candidate, reason, now, "community"),
                    )
                    changes.append((scope, unit))
                    current, changed_at, basis = candidate, now, "community"
                    self.connection.execute(
                        "UPDATE community_meta SET value=CAST(value AS INTEGER)+1 WHERE key='revision'"
                    )
                self.connection.execute(
                    """INSERT OR REPLACE INTO community_tiers
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        *key,
                        current,
                        candidate,
                        since,
                        changed_at,
                        json.dumps(data),
                        basis,
                    ),
                )
        self.dirty = False
        return changes

    def tier_rows(self, role, mode, *, scope="global"):
        rows = self._all(
            "SELECT * FROM community_tiers WHERE scope=? AND period=? AND role=? AND mode=?",
            (scope, self.get("period"), role, mode),
        )
        for row in rows:
            row["metrics"] = json.loads(row["metrics"])
        return sorted(
            rows,
            key=lambda row: (
                -(TIERS.index(row["tier"]) if row["tier"] else -1),
                -(row["metrics"].get("rating") or 0),
                row["unit_id"],
            ),
        )

    def changes(self, *, scope="global", limit=8):
        return self._all(
            "SELECT * FROM community_changes WHERE scope=? AND period=? ORDER BY id DESC LIMIT ?",
            (scope, self.get("period"), limit),
        )

    def editorial(self, scope, unit_id, role, mode, tier, reason):
        if tier not in TIERS or role not in ROLES or mode not in MODES:
            raise ValueError("Escolha um contexto válido.")
        reason = clean_text(reason, 500)
        if len(reason) < 25:
            raise ValueError("Explique a classificação em pelo menos 25 caracteres.")
        key = (scope, self.get("period"), unit_id, role, mode)
        old = self._one(
            "SELECT tier FROM community_tiers WHERE scope=? AND period=? AND unit_id=? AND role=? AND mode=?",
            key,
        )
        now = self.clock()
        metrics = consensus(
            self.reviews(unit_id, role, mode, scope=scope), local=scope != "global"
        )
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO community_tiers VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (*key, tier, None, now, now, json.dumps(metrics), "editorial"),
            )
            self.connection.execute(
                """INSERT INTO community_changes
                (scope,period,unit_id,role,mode,old_tier,new_tier,reason,created_at,basis)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (*key, old["tier"] if old else None, tier, reason, now, "editorial"),
            )
            self.touch()

    def draft(
        self, user_id, guild_id, channel_id, source_event, author_name, guild_name, body
    ):
        self.require_capacity()
        self._check_source(guild_id, channel_id)
        body = validate_chat(body)
        if self.blocked(user_id):
            raise ValueError("Sua participação está bloqueada. Procure a moderação.")
        existing = self._one(
            "SELECT * FROM community_pending WHERE source_event=?", (str(source_event),)
        )
        if existing:
            return existing
        if self._one(
            "SELECT 1 FROM community_pending WHERE user_id=? AND created_at>?",
            (str(user_id), self.clock() - 600),
        ):
            raise ValueError(
                "Confirme ou cancele sua primeira mensagem antes de enviar outra."
            )
        if (
            self.connection.execute(
                "SELECT COUNT(*) FROM community_pending"
            ).fetchone()[0]
            >= MAX_PENDING
        ):
            raise ValueError("Há muitas solicitações pendentes. Tente mais tarde.")
        uid = uuid.uuid4().hex
        with self.connection:
            self.connection.execute(
                "INSERT INTO community_pending VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    uid,
                    str(user_id),
                    str(guild_id),
                    str(channel_id),
                    str(source_event),
                    clean_text(author_name, 100),
                    clean_text(guild_name, 100),
                    body,
                    self.clock(),
                ),
            )
        return self._one("SELECT * FROM community_pending WHERE id=?", (uid,))

    def cancel_draft(self, draft_id, user_id):
        with self.connection:
            self.connection.execute(
                "DELETE FROM community_pending WHERE id=? AND user_id=?",
                (draft_id, str(user_id)),
            )

    def accept_draft(self, draft_id, user_id):
        row = self._one(
            "SELECT * FROM community_pending WHERE id=? AND user_id=?",
            (draft_id, str(user_id)),
        )
        if not row or self.clock() - row["created_at"] > 600:
            raise ValueError("Essa confirmação expirou. Envie a mensagem novamente.")
        self._check_source(row["guild_id"], row["channel_id"])
        self.consent(user_id)
        relay = self.enqueue(
            user_id,
            row["guild_id"],
            row["channel_id"],
            row["source_event"],
            row["author_name"],
            row["guild_name"],
            row["body"],
            original_id=row["source_event"] if row["source_event"].isdigit() else None,
        )
        self.cancel_draft(draft_id, user_id)
        return relay

    def _check_source(self, guild_id, channel_id):
        config = self.channel(guild_id, "global")
        if not config or config["channel_id"] != str(channel_id):
            raise ValueError("O chat global não está ativo neste canal.")
        if self.get("global_paused") == "1":
            raise ValueError("O chat global está pausado pela moderação.")
        return config

    def enqueue(
        self,
        user_id,
        guild_id,
        channel_id,
        source_event,
        author_name,
        guild_name,
        body,
        *,
        original_id=None,
    ):
        self.require_capacity()
        self._check_source(guild_id, channel_id)
        if self.blocked(user_id) or not self.consented(user_id):
            raise ValueError(
                "Confirme sua participação no chat global antes de enviar."
            )
        existing = self._one(
            "SELECT * FROM community_relays WHERE source_event=?", (str(source_event),)
        )
        if existing:
            return existing
        body, now = validate_chat(body), self.clock()
        uid = uuid.uuid4().hex
        with self.connection:
            if self._one(
                "SELECT 1 FROM community_relays WHERE user_id=? AND created_at>?",
                (str(user_id), now - 10),
            ):
                raise ValueError("Espere 10 segundos entre mensagens globais.")
            count = self.connection.execute(
                "SELECT COUNT(*) FROM community_relays WHERE guild_id=? AND created_at>?",
                (str(guild_id), now - 60),
            ).fetchone()[0]
            if count >= 30:
                raise ValueError(
                    "O chat deste servidor está movimentado. Tente em um minuto."
                )
            targets = self.channels("global")
            if (
                len(targets) > 100
                or self.connection.execute(
                    "SELECT COUNT(*) FROM community_relays"
                ).fetchone()[0]
                >= MAX_RELAYS
                or self.connection.execute(
                    "SELECT COUNT(*) FROM community_deliveries WHERE state='queued'"
                ).fetchone()[0]
                + len(targets)
                > 10000
            ):
                raise ValueError(
                    "A fila global está cheia. Sua mensagem original foi preservada."
                )
            self.connection.execute(
                """INSERT INTO community_relays
              (id,source_event,user_id,guild_id,channel_id,author_name,guild_name,body,created_at,status,original_id)
              VALUES(?,?,?,?,?,?,?,?,?,'active',?)""",
                (
                    uid,
                    str(source_event),
                    str(user_id),
                    str(guild_id),
                    str(channel_id),
                    clean_text(author_name, 100),
                    clean_text(guild_name, 100),
                    body,
                    now,
                    str(original_id) if original_id else None,
                ),
            )
            for target in targets:
                self.connection.execute(
                    """INSERT INTO community_deliveries(relay_id,guild_id,channel_id,state,is_source)
                  VALUES(?,?,?,'queued',?)""",
                    (
                        uid,
                        target["guild_id"],
                        target["channel_id"],
                        int(target["channel_id"] == str(channel_id)),
                    ),
                )
        return self.relay(uid)

    def relay(self, relay_id):
        return self._one("SELECT * FROM community_relays WHERE id=?", (relay_id,))

    def delivery_valid(self, job):
        relay = self.relay(job["relay_id"])
        config = self.channel(job["guild_id"], "global")
        source = self.channel(relay["guild_id"], "global") if relay else None
        return bool(
            relay
            and relay["status"] == "active"
            and self.get("global_paused") != "1"
            and self.consented(relay["user_id"])
            and not self.blocked(relay["user_id"])
            and config
            and config["channel_id"] == job["channel_id"]
            and source
            and source["channel_id"] == relay["channel_id"]
        )

    def jobs(self, limit=10):
        # A destination only becomes eligible after the local copy is acknowledged.
        return self._all(
            """SELECT d.* FROM community_deliveries d JOIN community_relays r ON r.id=d.relay_id
          WHERE d.state='queued' AND d.next_try<=? AND r.status='active' AND
          (d.is_source=1 OR EXISTS(SELECT 1 FROM community_deliveries s WHERE s.relay_id=d.relay_id AND s.is_source=1 AND s.state='sent'))
          ORDER BY d.id LIMIT ?""",
            (self.clock(), limit),
        )

    def mark_sent(self, job_id, message_id, *, revoked=False):
        with self.connection:
            # A withdrawal/deletion may arrive while the HTTP request is in flight.
            # Retain the receipt even then, so a late copy can be removed.
            self.connection.execute(
                """UPDATE community_deliveries SET
                state=CASE WHEN state='queued' AND ?=0 THEN 'sent' ELSE 'delete' END,
                message_id=?,last_error=NULL,next_try=0 WHERE id=?""",
                (int(revoked), str(message_id), job_id),
            )

    def cancel_job(self, job_id):
        with self.connection:
            self.connection.execute(
                "UPDATE community_deliveries SET state='cancelled' WHERE id=? AND state='queued'",
                (job_id,),
            )

    def fail_job(self, job, *, permanent=False):
        attempts = job["attempts"] + 1
        state = "failed" if permanent or attempts >= 5 else "queued"
        with self.connection:
            self.connection.execute(
                "UPDATE community_deliveries SET state=?,attempts=?,next_try=?,last_error=? WHERE id=?",
                (
                    state,
                    attempts,
                    self.clock() + min(300, 2**attempts * 5),
                    "delivery-failed",
                    job["id"],
                ),
            )
            if state == "failed" and job["is_source"]:
                self.connection.execute(
                    "UPDATE community_deliveries SET state='cancelled' WHERE relay_id=? AND state='queued'",
                    (job["relay_id"],),
                )

    def originals_to_delete(self):
        return self._all("""SELECT r.* FROM community_relays r WHERE r.original_id IS NOT NULL AND r.original_state='pending'
          AND EXISTS(SELECT 1 FROM community_deliveries d WHERE d.relay_id=r.id AND d.is_source=1 AND d.state='sent') LIMIT 20""")

    def mark_original(self, relay_id, state):
        with self.connection:
            self.connection.execute(
                "UPDATE community_relays SET original_state=? WHERE id=?",
                (state, relay_id),
            )

    def report(self, relay_id, user_id, guild_id, message_id, reason):
        if not self._one(
            "SELECT 1 FROM community_deliveries WHERE relay_id=? AND guild_id=? AND message_id=? AND state='sent'",
            (relay_id, str(guild_id), str(message_id)),
        ):
            raise ValueError("Esta mensagem não pertence a este chat global.")
        if (
            self.connection.execute(
                "SELECT COUNT(*) FROM community_reports WHERE user_id=? AND created_at>?",
                (str(user_id), self.clock() - 3600),
            ).fetchone()[0]
            >= 5
        ):
            raise ValueError(
                "Limite de cinco denúncias por hora. Procure a moderação em caso de urgência."
            )
        with self.connection:
            self.connection.execute(
                """INSERT INTO community_reports(relay_id,user_id,guild_id,reason,created_at) VALUES(?,?,?,?,?)
              ON CONFLICT(relay_id,user_id) DO NOTHING""",
                (
                    relay_id,
                    str(user_id),
                    str(guild_id),
                    clean_text(reason, 400),
                    self.clock(),
                ),
            )

    def reports(self, limit=15):
        return self._all(
            "SELECT * FROM community_reports WHERE reviewed_at IS NULL ORDER BY id DESC LIMIT ?",
            (limit,),
        )

    def delete_relay(self, relay_id, user_id, *, moderator=False):
        relay = self.relay(relay_id)
        if not relay or (not moderator and relay["user_id"] != str(user_id)):
            raise ValueError("Você só pode remover suas próprias mensagens.")
        with self.connection:
            self.connection.execute(
                "UPDATE community_relays SET status='deleted',body='' WHERE id=?",
                (relay_id,),
            )
            self.connection.execute(
                "UPDATE community_deliveries SET state=CASE WHEN message_id IS NOT NULL THEN 'delete' ELSE 'cancelled' END WHERE relay_id=?",
                (relay_id,),
            )
        return relay

    def deletions(self):
        return self._all(
            "SELECT * FROM community_deliveries WHERE state='delete' AND next_try<=? LIMIT 20",
            (self.clock(),),
        )

    def deleted(self, job_id):
        with self.connection:
            self.connection.execute(
                "UPDATE community_deliveries SET state='deleted' WHERE id=?", (job_id,)
            )

    def erase_reviews(self, user_id):
        with self.connection:
            self.connection.execute(
                "DELETE FROM community_reviews WHERE user_id=?", (str(user_id),)
            )
            self.touch()

    def cleanup(self):
        now = self.clock()
        with self.connection:
            self.connection.execute(
                "DELETE FROM community_pending WHERE created_at<?", (now - 600,)
            )
            self.connection.execute(
                "DELETE FROM community_mentions WHERE created_at<?", (now - 7 * 86400,)
            )
            self.connection.execute(
                "UPDATE community_deliveries SET state='cancelled',last_error='expired' WHERE state='queued' AND relay_id IN (SELECT id FROM community_relays WHERE created_at<?)",
                (now - 86400,),
            )
            # Copies remain in Discord. Mapping IDs are retained for removal; old bodies are minimized.
            self.connection.execute(
                "UPDATE community_relays SET body='' WHERE created_at<? AND body!='' AND NOT EXISTS(SELECT 1 FROM community_deliveries d WHERE d.relay_id=community_relays.id AND d.state='queued')",
                (now - 7 * 86400,),
            )
