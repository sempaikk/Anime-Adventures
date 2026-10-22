"""Bounded community evidence, durable voting and atomic global publications."""

from __future__ import annotations

import hashlib
import math
import hmac
import json
import secrets
import sqlite3
import time
import re
import shutil
from pathlib import Path
from contextlib import nullcontext
from urllib.parse import urlsplit

from tier_categories import TIERS as TIERS, POLICY, LABELS, valid_ranking

REQUIRED_TABLES = {
    "tier_meta",
    "tier_channels",
    "tier_comments",
    "tier_publications",
    "tier_proposals",
    "tier_votes",
    "tier_poll_messages",
    "tier_destinations",
    "tier_guilds",
    "tier_threads",
    "tier_reports",
    "tier_audit",
}


def source_signature(sources):
    from community_domain import normalize

    return sorted(
        (
            urlsplit(s["url"])._replace(query="", fragment="").geturl(),
            normalize(s["quote"]),
        )
        for s in sources
    )


class TierStore:
    def __init__(self, path, *, clock=time.time):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self.catalog = None
        self.connection = sqlite3.connect(self.path, timeout=1)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA busy_timeout=1000")
        if self.connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            self.connection.close()
            raise sqlite3.DatabaseError("Falha de integridade; o banco foi preservado.")
        self.connection.executescript("""
          CREATE TABLE IF NOT EXISTS tier_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS tier_proposals(
            id INTEGER PRIMARY KEY AUTOINCREMENT,created_at REAL NOT NULL,closes_at REAL NOT NULL,
            base_publication INTEGER NOT NULL,ranking TEXT NOT NULL,explanations TEXT NOT NULL,
            details TEXT NOT NULL,source_version TEXT NOT NULL,model TEXT NOT NULL,
            status TEXT NOT NULL,outcome TEXT NOT NULL DEFAULT '{}');
          CREATE TABLE IF NOT EXISTS tier_votes(
            proposal_id INTEGER NOT NULL,user_id TEXT NOT NULL,guild_id TEXT NOT NULL,
            choice TEXT NOT NULL,created_at REAL NOT NULL,PRIMARY KEY(proposal_id,user_id));
          CREATE TABLE IF NOT EXISTS tier_poll_messages(
            proposal_id INTEGER NOT NULL,guild_id TEXT NOT NULL,channel_id TEXT NOT NULL,
            message_id TEXT NOT NULL UNIQUE,updated_at REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'open',PRIMARY KEY(proposal_id,channel_id));
          CREATE TABLE IF NOT EXISTS tier_channels(channel_id TEXT PRIMARY KEY,guild_id TEXT NOT NULL,enabled_at REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS tier_consents(user_id TEXT PRIMARY KEY,accepted_at REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS tier_comments(
            message_id TEXT PRIMARY KEY,user_id TEXT NOT NULL,actor_key TEXT NOT NULL,
            guild_id TEXT NOT NULL,channel_id TEXT NOT NULL,body TEXT NOT NULL,units TEXT NOT NULL,
            created_at REAL NOT NULL,processed INTEGER NOT NULL DEFAULT 0);
          CREATE INDEX IF NOT EXISTS tier_pending ON tier_comments(processed,created_at);
          CREATE TABLE IF NOT EXISTS tier_publications(
            id INTEGER PRIMARY KEY AUTOINCREMENT,created_at REAL NOT NULL,ranking TEXT NOT NULL,
            explanations TEXT NOT NULL,source_version TEXT NOT NULL,model TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS tier_panels(
            channel_id TEXT PRIMARY KEY,guild_id TEXT NOT NULL,message_id TEXT NOT NULL,
            publication_id INTEGER NOT NULL DEFAULT 0,last_sent REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS tier_destinations(
            guild_id TEXT PRIMARY KEY,channel_id TEXT NOT NULL,enabled_at REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS tier_history(
            id INTEGER PRIMARY KEY AUTOINCREMENT,publication_id INTEGER NOT NULL,
            unit_id TEXT NOT NULL,from_position INTEGER,to_position INTEGER,reason TEXT NOT NULL,
            sources TEXT NOT NULL,created_at REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS tier_guilds(guild_id TEXT PRIMARY KEY,joined_at REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS tier_threads(
            guild_id TEXT PRIMARY KEY,thread_id TEXT NOT NULL UNIQUE,intro_id TEXT,
            index_hash TEXT NOT NULL DEFAULT '',panel_hash TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'ok');
          CREATE TABLE IF NOT EXISTS tier_fingerprints(
            fingerprint TEXT PRIMARY KEY,message_id TEXT NOT NULL,created_at REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS tier_reports(
            id INTEGER PRIMARY KEY AUTOINCREMENT,proposal_id INTEGER NOT NULL,user_id TEXT NOT NULL,
            guild_id TEXT NOT NULL,reason TEXT NOT NULL,created_at REAL NOT NULL,status TEXT NOT NULL DEFAULT 'pending',
            UNIQUE(proposal_id,user_id));
          CREATE TABLE IF NOT EXISTS tier_audit(
            id INTEGER PRIMARY KEY AUTOINCREMENT,kind TEXT NOT NULL,actor_id TEXT NOT NULL,
            reason TEXT NOT NULL,publication_id INTEGER,created_at REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS tier_audit_messages(
            audit_id INTEGER NOT NULL,guild_id TEXT NOT NULL,message_id TEXT NOT NULL,
            PRIMARY KEY(audit_id,guild_id));
          CREATE TABLE IF NOT EXISTS tier_deliveries(
            key TEXT PRIMARY KEY,channel_id TEXT NOT NULL,message_id TEXT NOT NULL,created_at REAL NOT NULL);
        """)
        self._column("tier_proposals", "opened_at", "REAL")
        self._column("tier_comments", "attempts", "INTEGER NOT NULL DEFAULT 0")
        self._column("tier_comments", "sent_at", "REAL")
        # Opening times of pre-migration polls are already running; never reset their clock.
        self.connection.execute(
            "UPDATE tier_proposals SET opened_at=created_at WHERE status='open' AND opened_at IS NULL"
        )
        with self.connection:
            for k, v in (
                ("interval", "60"),
                ("salt", secrets.token_hex(32)),
                ("schema", "1"),
                ("last_analysis", "0"),
                ("last_attempt", "0"),
                ("analysis_status", "not-connected"),
            ):
                self.connection.execute(
                    "INSERT OR IGNORE INTO tier_meta VALUES(?,?)", (k, v)
                )
            self.connection.execute("UPDATE tier_meta SET value='3' WHERE key='schema'")
        self._migrate_categories()

    def _migrate_categories(self):
        """Grades never imply roles. Keep old snapshots/votes, publish an audited boundary."""
        if self.get("category_policy") == POLICY:
            return
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            latest = self.latest()
            incompatible = not valid_ranking(latest["ranking"])
            if incompatible:
                cursor = self.connection.execute(
                    "INSERT INTO tier_publications(created_at,ranking,explanations,source_version,model) VALUES(?,?,?,?,?)",
                    (
                        self.clock(),
                        "[]",
                        "{}",
                        latest["source_version"],
                        "category-migration",
                    ),
                )
                self.audit(
                    "category-migration",
                    "system",
                    "A imagem agora separa Meta, Damage, Support, Buff e Farm. Meta também aparece na função principal. "
                    "As classificações por letras foram preservadas no histórico; não equivalem a funções. "
                    "As novas posições precisam de propostas e votos, sem atribuições automáticas.",
                    cursor.lastrowid,
                )
                self.connection.execute("UPDATE tier_comments SET processed=0")
            for row in self.rows(
                "SELECT id FROM tier_proposals WHERE status IN ('open','queued')"
            ):
                proposal = self.proposal(row["id"])
                if incompatible or not valid_ranking(proposal["ranking"]):
                    self.connection.execute(
                        "UPDATE tier_proposals SET status='outdated',outcome=? WHERE id=?",
                        (json.dumps(self.poll_counts(row["id"])), row["id"]),
                    )
            self.connection.execute(
                "INSERT OR REPLACE INTO tier_meta VALUES('category_policy',?)",
                (POLICY,),
            )

    def _column(self, table, column, declaration):
        if column not in {
            r[1] for r in self.connection.execute(f"PRAGMA table_info({table})")
        }:
            self.connection.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {declaration}"
            )

    def bind_catalog(self, catalog):
        """Apply explicit retirements once, preserving snapshots, votes and audit history."""
        self.catalog = catalog
        retired = set(getattr(catalog, "retired", {}))
        signature = hashlib.sha256(json.dumps(sorted(retired)).encode()).hexdigest()
        if self.get("catalog_policy") == signature:
            return
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            latest = self.latest()
            ranking = [r for r in latest["ranking"] if r["unit_id"] not in retired]
            if ranking != latest["ranking"]:
                removed = [
                    r["unit_id"] for r in latest["ranking"] if r["unit_id"] in retired
                ]
                explanations = {
                    u: d for u, d in latest["explanations"].items() if u not in retired
                }
                cursor = self.connection.execute(
                    "INSERT INTO tier_publications(created_at,ranking,explanations,source_version,model) VALUES(?,?,?,?,?)",
                    (
                        self.clock(),
                        json.dumps(ranking),
                        json.dumps(explanations),
                        latest["source_version"],
                        "catalog-maintenance",
                    ),
                )
                self.audit(
                    "catalog-retired",
                    "system",
                    "Formas retiradas do catálogo ativo: "
                    + ", ".join(catalog.display_name(u) for u in removed)
                    + ". A ordem relativa das demais formas foi preservada.",
                    cursor.lastrowid,
                )
            for row in self.rows(
                "SELECT id FROM tier_proposals WHERE status IN ('open','queued')"
            ):
                proposal = self.proposal(row["id"])
                if proposal["base_publication"] != self.latest()[
                    "id"
                ] or self._inactive(proposal["ranking"], proposal["details"]):
                    self.connection.execute(
                        "UPDATE tier_proposals SET status='outdated',outcome=? WHERE id=?",
                        (json.dumps(self.poll_counts(row["id"])), row["id"]),
                    )
                    self.connection.execute(
                        "UPDATE tier_meta SET value='outdated' WHERE key='analysis_status'"
                    )
            for row in self.rows("SELECT message_id,units FROM tier_comments"):
                units = set(json.loads(row["units"])) - retired
                if units:
                    self.connection.execute(
                        "UPDATE tier_comments SET units=? WHERE message_id=?",
                        (json.dumps(sorted(units)), row["message_id"]),
                    )
                else:
                    self.connection.execute(
                        "DELETE FROM tier_comments WHERE message_id=?",
                        (row["message_id"],),
                    )
            tables = {
                r[0]
                for r in self.connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if "tier_media_active" in tables:
                for uid in retired:
                    deleted = self.connection.execute(
                        "DELETE FROM tier_media_active WHERE unit_id=?", (uid,)
                    ).rowcount
                    self.connection.execute(
                        "UPDATE tier_media_suggestions SET status='unavailable' WHERE unit_id=? AND status='pending'",
                        (uid,),
                    )
                    if deleted:
                        self.connection.execute(
                            "INSERT INTO tier_meta VALUES('media_revision','1') ON CONFLICT(key) DO UPDATE SET value=CAST(value AS INTEGER)+1"
                        )
            self.connection.execute(
                "INSERT OR REPLACE INTO tier_meta VALUES('catalog_policy',?)",
                (signature,),
            )

    def _inactive(self, ranking, details=None):
        if self.catalog is None:
            return False
        ids = {r["unit_id"] for r in ranking} | set(details or {})
        ids.update(d["before"] for d in (details or {}).values() if d.get("before"))
        return not ids <= self.catalog.units.keys()

    def _require_active(self, ranking, details=None):
        if not valid_ranking(ranking):
            raise ValueError(
                "A classificação precisa usar funções válidas, sem formas repetidas; Meta exige função principal."
            )
        if self._inactive(ranking, details):
            raise ValueError(
                "A proposta contém uma forma fora do catálogo ativo do jogo."
            )

    def register_guild(self, guild_id):
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO tier_guilds VALUES(?,?)",
                (str(guild_id), self.clock()),
            )

    def guild_registered(self, guild_id):
        return bool(
            self.connection.execute(
                "SELECT 1 FROM tier_guilds WHERE guild_id=?", (str(guild_id),)
            ).fetchone()
        )

    def remove_guild(self, guild_id):
        with self.connection:
            self.connection.execute(
                "DELETE FROM tier_meta WHERE key=?", (f"history-import:{guild_id}",)
            )
            for table in (
                "tier_guilds",
                "tier_threads",
                "tier_panels",
                "tier_channels",
                "tier_destinations",
                "tier_comments",
            ):
                self.connection.execute(
                    f"DELETE FROM {table} WHERE guild_id=?", (str(guild_id),)
                )
            self.connection.execute(
                "UPDATE tier_poll_messages SET status='removed' WHERE guild_id=? AND status='open'",
                (str(guild_id),),
            )

    def thread(self, guild_id):
        rows = self.rows(
            "SELECT * FROM tier_threads WHERE guild_id=?", (str(guild_id),)
        )
        return rows[0] if rows else None

    def remember_thread(self, guild_id, thread_id, intro_id=None):
        with self.connection:
            self.connection.execute(
                "INSERT INTO tier_threads(guild_id,thread_id,intro_id) VALUES(?,?,?) ON CONFLICT(guild_id) DO UPDATE SET intro_id=CASE WHEN tier_threads.thread_id=excluded.thread_id THEN COALESCE(excluded.intro_id,tier_threads.intro_id) ELSE excluded.intro_id END,index_hash=CASE WHEN tier_threads.thread_id=excluded.thread_id THEN tier_threads.index_hash ELSE '' END,panel_hash=CASE WHEN tier_threads.thread_id=excluded.thread_id THEN tier_threads.panel_hash ELSE '' END,thread_id=excluded.thread_id,status='ok'",
                (str(guild_id), str(thread_id), str(intro_id) if intro_id else None),
            )

    def thread_targets(self):
        return self.rows(
            "SELECT t.*,p.channel_id,p.message_id FROM tier_threads t JOIN tier_panels p USING(guild_id) WHERE t.status='ok'"
        )

    def close(self):
        self.connection.close()

    def rows(self, sql, args=()):
        return [dict(r) for r in self.connection.execute(sql, args)]

    def get(self, key):
        row = self.connection.execute(
            "SELECT value FROM tier_meta WHERE key=?", (key,)
        ).fetchone()
        return row[0] if row else None

    def set(self, key, value):
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO tier_meta VALUES(?,?)", (key, str(value))
            )

    def interval(self):
        return int(self.get("interval") or 60) * 60

    def set_interval(self, minutes):
        if minutes not in (30, 60):
            raise ValueError("Escolha 30 minutos ou 1 hora.")
        self.set("interval", minutes)

    def channels(self, guild_id=None):
        return self.rows(
            "SELECT * FROM tier_channels"
            + (" WHERE guild_id=?" if guild_id is not None else ""),
            (str(guild_id),) if guild_id is not None else (),
        )

    def update_channels(self):
        return self.rows(
            "SELECT d.* FROM tier_destinations d "
            "JOIN tier_panels p ON p.guild_id=d.guild_id "
            "WHERE d.channel_id!=p.channel_id"
        )

    def set_update_channel(self, guild_id, channel_id):
        panel = self.connection.execute(
            "SELECT channel_id FROM tier_panels WHERE guild_id=?", (str(guild_id),)
        ).fetchone()
        if not panel:
            raise ValueError("Publique primeiro o painel com /tierlist.")
        if panel[0] == str(channel_id):
            raise ValueError(
                "Escolha outro canal para manter a tier list separada das votações."
            )
        active = self.active_proposal()
        if (
            active
            and self.connection.execute(
                "SELECT 1 FROM tier_poll_messages WHERE proposal_id=? AND guild_id=? AND status='open'",
                (active["id"], str(guild_id)),
            ).fetchone()
        ):
            raise ValueError(
                "Aguarde a votação deste servidor terminar antes de trocar o canal."
            )
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO tier_destinations VALUES(?,?,?)",
                (str(guild_id), str(channel_id), self.clock()),
            )

    def is_update_channel(self, guild_id, channel_id):
        return bool(
            self.connection.execute(
                "SELECT 1 FROM tier_destinations WHERE guild_id=? AND channel_id=?",
                (str(guild_id), str(channel_id)),
            ).fetchone()
        )

    def channel_enabled(self, guild_id, channel_id):
        return bool(
            self.connection.execute(
                "SELECT 1 FROM tier_channels WHERE guild_id=? AND channel_id=?",
                (str(guild_id), str(channel_id)),
            ).fetchone()
        )

    def enable_channel(self, guild_id, channel_id):
        # Compatibility for archived tests/tools. The active runtime has no channel opt-in.
        self.register_guild(guild_id)
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO tier_channels VALUES(?,?,?)",
                (str(channel_id), str(guild_id), self.clock()),
            )

    def disable_channel(self, guild_id, channel_id):
        with self.connection:
            self.connection.execute(
                "DELETE FROM tier_channels WHERE guild_id=? AND channel_id=?",
                (str(guild_id), str(channel_id)),
            )
            self.connection.execute(
                "DELETE FROM tier_comments WHERE guild_id=? AND channel_id=?",
                (str(guild_id), str(channel_id)),
            )

    def consented(self, user_id):
        return bool(
            self.connection.execute(
                "SELECT 1 FROM tier_consents WHERE user_id=?", (str(user_id),)
            ).fetchone()
        )

    def consent(self, user_id):
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO tier_consents VALUES(?,?)",
                (str(user_id), self.clock()),
            )

    def withdraw(self, user_id):
        with self.connection:
            self.connection.execute(
                "DELETE FROM tier_consents WHERE user_id=?", (str(user_id),)
            )
            self.connection.execute(
                "DELETE FROM tier_votes WHERE user_id=?", (str(user_id),)
            )
            self.connection.execute(
                "DELETE FROM tier_comments WHERE user_id=?", (str(user_id),)
            )

    def ingest(
        self, message_id, user_id, guild_id, channel_id, body, units, *, sent_at=None
    ):
        if self.catalog is not None:
            units = set(units) & self.catalog.units.keys()
        if not self.guild_registered(guild_id) or not units:
            return False
        if not 12 <= len(body) <= 4000:
            return False
        if self.path.stat().st_size >= 64 * 1024 * 1024:
            return False
        if shutil.disk_usage(self.path.parent).free < 16 * 1024 * 1024:
            return False
        now = self.clock()
        sent_at = now if sent_at is None else sent_at
        if (
            type(sent_at) not in (int, float)
            or not math.isfinite(sent_at)
            or not 0 <= sent_at <= now
        ):
            return False
        if (
            self.connection.execute("SELECT COUNT(*) FROM tier_comments").fetchone()[0]
            >= 10000
        ):
            return False
        recent = self.connection.execute(
            "SELECT COUNT(*) FROM tier_comments WHERE user_id=? AND created_at>?",
            (str(user_id), now - 3600),
        ).fetchone()[0]
        if recent >= 10:
            return False
        if (
            self.connection.execute(
                "SELECT COUNT(*) FROM tier_comments WHERE guild_id=? AND created_at>?",
                (str(guild_id), now - 3600),
            ).fetchone()[0]
            >= 60
        ):
            return False
        from community_domain import normalize

        canonical = normalize(re.sub(r"https?://\S+|<[@#][!&]?\d+>", "", body))
        fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
        if self.connection.execute(
            "SELECT 1 FROM tier_fingerprints WHERE fingerprint=? AND created_at>?",
            (fingerprint, now - 7 * 86400),
        ).fetchone():
            return False
        words = set(canonical.split())
        for previous in self.rows(
            "SELECT body FROM tier_comments WHERE created_at>? ORDER BY created_at DESC LIMIT 100",
            (now - 86400,),
        ):
            other = set(normalize(previous["body"]).split())
            if (
                len(words) >= 7
                and len(other) >= 7
                and len(words & other) / max(1, len(words | other)) >= 0.9
            ):
                return False
        actor = hmac.new(
            bytes.fromhex(self.get("salt")), str(user_id).encode(), hashlib.sha256
        ).hexdigest()[:24]
        with self.connection:
            cursor = self.connection.execute(
                "INSERT OR IGNORE INTO tier_comments(message_id,user_id,actor_key,guild_id,channel_id,body,units,created_at,sent_at,processed) VALUES(?,?,?,?,?,?,?,?,?,0)",
                (
                    str(message_id),
                    str(user_id),
                    actor,
                    str(guild_id),
                    str(channel_id),
                    body,
                    json.dumps(sorted(units)),
                    now,
                    sent_at,
                ),
            )
            if cursor.rowcount:
                self.connection.execute(
                    "INSERT OR REPLACE INTO tier_fingerprints VALUES(?,?,?)",
                    (fingerprint, str(message_id), now),
                )
        return bool(cursor.rowcount)

    def pending(self, limit=16):
        rows = self.rows(
            "SELECT * FROM (SELECT c.*,ROW_NUMBER() OVER(PARTITION BY c.guild_id ORDER BY c.attempts,c.created_at,c.message_id) AS guild_order FROM tier_comments c JOIN tier_guilds g USING(guild_id) WHERE c.processed=0 AND c.attempts<3 AND c.created_at>=?) WHERE guild_order<=? ORDER BY guild_order,guild_id LIMIT 1000",
            (self.clock() - 7 * 86400, max(4, limit)),
        )
        grouped = {}
        for row in rows:
            grouped.setdefault(row["guild_id"], []).append(row)
        guilds = sorted(grouped)
        cursor = self.get("fair_cursor")
        if cursor in guilds:
            i = guilds.index(cursor) + 1
            guilds = guilds[i:] + guilds[:i]
        result = []
        while guilds and len(result) < limit:
            for guild in list(guilds):
                if len(result) >= limit:
                    break
                result.append(grouped[guild].pop(0))
                if not grouped[guild]:
                    guilds.remove(guild)
        return result

    def attempted(self, comments):
        with self.connection:
            for comment in comments:
                self.connection.execute(
                    "UPDATE tier_comments SET attempts=attempts+1 WHERE message_id=?",
                    (comment["message_id"],),
                )
        if comments:
            self.set("fair_cursor", comments[0]["guild_id"])

    def recent(self):
        return self.rows(
            "SELECT * FROM tier_comments WHERE created_at>=? ORDER BY created_at DESC LIMIT 200",
            (self.clock() - 7 * 86400,),
        )

    def still_allowed(self, comments):
        return all(
            self.guild_registered(c["guild_id"])
            and self.connection.execute(
                "SELECT 1 FROM tier_comments WHERE message_id=?", (c["message_id"],)
            ).fetchone()
            for c in comments
        )

    def latest(self):
        rows = self.rows("SELECT * FROM tier_publications ORDER BY id DESC LIMIT 1")
        if not rows:
            return {
                "id": 0,
                "created_at": None,
                "ranking": [],
                "explanations": {},
                "source_version": "",
                "model": "",
            }
        row = rows[0]
        row["ranking"] = json.loads(row["ranking"])
        row["explanations"] = json.loads(row["explanations"])
        return row

    def publish(
        self,
        ranking,
        explanations,
        *,
        source_version,
        model,
        comments,
        change_details=None,
        transactional=True,
    ):
        self._require_active(ranking, change_details)
        if not self.still_allowed(comments):
            raise ValueError(
                "A participação ou o canal mudou durante a análise. O lote foi descartado."
            )
        old = self.latest()
        now = self.clock()
        old_positions = {
            r["unit_id"]: (i, r["tier"]) for i, r in enumerate(old["ranking"])
        }
        with self.connection if transactional else nullcontext():
            same = old["ranking"] == ranking and old["explanations"] == explanations
            if not same:
                cursor = self.connection.execute(
                    "INSERT INTO tier_publications(created_at,ranking,explanations,source_version,model) VALUES(?,?,?,?,?)",
                    (
                        now,
                        json.dumps(ranking),
                        json.dumps(explanations),
                        source_version,
                        model,
                    ),
                )
                publication = cursor.lastrowid
                # Reasons are shown only for META units, including changes within META.
                for pos, row in enumerate(ranking):
                    uid = row["unit_id"]
                    previous = old_positions.get(uid)
                    was_meta = previous is not None and previous[1] == "META"
                    if (row["tier"] == "META" or was_meta) and (
                        previous != (pos, row["tier"])
                        or old["explanations"].get(uid) != explanations.get(uid)
                    ):
                        detail = explanations.get(uid) or (change_details or {}).get(
                            uid
                        )
                        if not detail:
                            continue
                        reason = (
                            detail["reason"]
                            if row["tier"] == "META"
                            else f"Saiu do Meta para {LABELS[row['tier']]}. "
                            + detail["reason"]
                        )
                        self.connection.execute(
                            "INSERT INTO tier_history(publication_id,unit_id,from_position,to_position,reason,sources,created_at) VALUES(?,?,?,?,?,?,?)",
                            (
                                publication,
                                uid,
                                previous[0] + 1 if previous else None,
                                pos + 1,
                                reason,
                                json.dumps(detail["sources"]),
                                now,
                            ),
                        )
            for c in comments:
                self.connection.execute(
                    "UPDATE tier_comments SET processed=1 WHERE message_id=?",
                    (c["message_id"],),
                )
            self.connection.execute(
                "UPDATE tier_meta SET value=? WHERE key='last_analysis'", (str(now),)
            )
            self.connection.execute(
                "UPDATE tier_meta SET value='ok' WHERE key='analysis_status'"
            )
        return not same

    def history(self, page=1):
        return self.rows(
            "SELECT * FROM tier_history ORDER BY id DESC LIMIT 3 OFFSET ?",
            ((max(1, page) - 1) * 3,),
        )

    def remember_panel(self, guild_id, channel_id, message_id, publication):
        self.register_guild(guild_id)
        with self.connection:
            # One official board per server; older messages remain as historical copies.
            self.connection.execute(
                "DELETE FROM tier_panels WHERE guild_id=? AND channel_id!=?",
                (str(guild_id), str(channel_id)),
            )
            if (
                not self.connection.execute(
                    "SELECT 1 FROM tier_panels WHERE channel_id=?", (str(channel_id),)
                ).fetchone()
                and self.connection.execute(
                    "SELECT COUNT(*) FROM tier_panels"
                ).fetchone()[0]
                >= 100
            ):
                raise ValueError(
                    "A capacidade de painéis está cheia. A consulta foi publicada sem atualização automática."
                )
            self.connection.execute(
                "INSERT OR REPLACE INTO tier_panels(channel_id,guild_id,message_id,publication_id,last_sent) VALUES(?,?,?,?,?)",
                (
                    str(channel_id),
                    str(guild_id),
                    str(message_id),
                    publication,
                    self.clock(),
                ),
            )

    def panels(self):
        return self.rows("SELECT * FROM tier_panels")

    def forget_panel(self, channel_id):
        with self.connection:
            self.connection.execute(
                "DELETE FROM tier_panels WHERE channel_id=?", (str(channel_id),)
            )

    def cleanup(self):
        with self.connection:
            self.connection.execute(
                "DELETE FROM tier_proposals WHERE status NOT IN ('open','queued') AND id NOT IN (SELECT id FROM tier_proposals ORDER BY id DESC LIMIT 50)"
            )
            self.connection.execute(
                "DELETE FROM tier_votes WHERE proposal_id NOT IN (SELECT id FROM tier_proposals)"
            )
            self.connection.execute(
                "DELETE FROM tier_poll_messages WHERE proposal_id NOT IN (SELECT id FROM tier_proposals)"
            )
            self.connection.execute(
                "DELETE FROM tier_votes WHERE created_at<?",
                (self.clock() - 30 * 86400,),
            )
            self.connection.execute(
                "DELETE FROM tier_poll_messages WHERE proposal_id IN (SELECT id FROM tier_proposals WHERE status!='open' AND created_at<?)",
                (self.clock() - 30 * 86400,),
            )
            self.connection.execute(
                "DELETE FROM tier_proposals WHERE status!='open' AND created_at<?",
                (self.clock() - 30 * 86400,),
            )
            self.connection.execute(
                "DELETE FROM tier_comments WHERE created_at<?",
                (self.clock() - 7 * 86400,),
            )
            self.connection.execute(
                "DELETE FROM tier_fingerprints WHERE created_at<?",
                (self.clock() - 7 * 86400,),
            )
            self.connection.execute(
                "DELETE FROM tier_reports WHERE created_at<?",
                (self.clock() - 30 * 86400,),
            )
            self.connection.execute(
                "DELETE FROM tier_audit WHERE id NOT IN (SELECT id FROM tier_audit ORDER BY id DESC LIMIT 1000)"
            )
            self.connection.execute(
                "DELETE FROM tier_audit_messages WHERE audit_id NOT IN (SELECT id FROM tier_audit)"
            )
            expired = self.connection.execute(
                "UPDATE tier_proposals SET status='unavailable' WHERE status='queued' AND created_at<?",
                (self.clock() - 3600,),
            ).rowcount
            if expired:
                self.connection.execute(
                    "UPDATE tier_meta SET value='retry' WHERE key='analysis_status'"
                )
            # Keep recent snapshots, and the detailed META history separately.
            self.connection.execute(
                "DELETE FROM tier_publications WHERE id NOT IN (SELECT id FROM tier_publications ORDER BY id DESC LIMIT 20)"
            )
            self.connection.execute(
                "DELETE FROM tier_history WHERE id NOT IN (SELECT id FROM tier_history ORDER BY id DESC LIMIT 2000)"
            )

    def proposal(self, proposal_id):
        rows = self.rows("SELECT * FROM tier_proposals WHERE id=?", (proposal_id,))
        if not rows:
            return None
        row = rows[0]
        for key in ("ranking", "explanations", "details", "outcome"):
            row[key] = json.loads(row[key])
        return row

    def active_proposal(self):
        rows = self.rows(
            "SELECT id FROM tier_proposals WHERE status IN ('open','queued') ORDER BY id DESC LIMIT 1"
        )
        return self.proposal(rows[0]["id"]) if rows else None

    def may_propose(self):
        if self.active_proposal():
            return False
        return self.clock() >= self.next_proposal_at()

    def next_proposal_at(self):
        row = self.connection.execute(
            "SELECT MAX(COALESCE(opened_at,created_at)) FROM tier_proposals"
        ).fetchone()[0]
        return 0 if row is None else row + 3600

    def next_analysis_at(self):
        return max(
            float(self.get("last_attempt") or 0) + self.interval(),
            self.next_proposal_at(),
        )

    def has_pending_comments(self):
        return (
            self.connection.execute(
                "SELECT 1 FROM tier_comments c JOIN tier_guilds g USING(guild_id) WHERE c.processed=0 AND c.attempts<3 AND c.created_at>=? LIMIT 1",
                (self.clock() - 7 * 86400,),
            ).fetchone()
            is not None
        )

    def create_proposal(
        self, ranking, explanations, *, details, source_version, model, comments
    ):
        self._require_active(ranking, details)
        if not self.still_allowed(comments):
            raise ValueError("As fontes de participação mudaram durante a análise.")
        if (
            sum(
                len(json.dumps(part).encode())
                for part in (ranking, explanations, details)
            )
            > 256 * 1024
        ):
            raise ValueError(
                "A proposta excede o limite de armazenamento e foi preservada sem publicação."
            )
        latest = self.latest()
        now = self.clock()
        if latest["ranking"] == ranking:
            with self.connection:
                for c in comments:
                    self.connection.execute(
                        "UPDATE tier_comments SET processed=1 WHERE message_id=?",
                        (c["message_id"],),
                    )
            return False
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            if not self.may_propose():
                return False
            for uid, detail in details.items():
                last = self.rows(
                    "SELECT * FROM tier_proposals WHERE status='approved' AND created_at>? ORDER BY id DESC LIMIT 24",
                    (now - 86400,),
                )
                for row in last:
                    old_detail = json.loads(row["details"]).get(uid)
                    if old_detail and source_signature(
                        old_detail["sources"]
                    ) == source_signature(detail["sources"]):
                        for c in comments:
                            self.connection.execute(
                                "UPDATE tier_comments SET processed=1 WHERE message_id=?",
                                (c["message_id"],),
                            )
                        return False
            # Do not repeat the same unresolved comparison every hour without a new outcome.
            for previous in self.rows(
                "SELECT ranking,status,details FROM tier_proposals WHERE created_at>?",
                (now - 86400,),
            ):
                if (
                    json.loads(previous["ranking"]) == ranking
                    and previous["status"]
                    in ("maintained", "needs-tests", "not-enough-votes", "suspended")
                    and {
                        u: source_signature(d["sources"])
                        for u, d in json.loads(previous["details"]).items()
                    }
                    == {u: source_signature(d["sources"]) for u, d in details.items()}
                ):
                    for c in comments:
                        self.connection.execute(
                            "UPDATE tier_comments SET processed=1 WHERE message_id=?",
                            (c["message_id"],),
                        )
                    return False
            self.connection.execute(
                """INSERT INTO tier_proposals
              (created_at,closes_at,base_publication,ranking,explanations,details,source_version,model,status)
              VALUES(?,?,?,?,?,?,?,?,'queued')""",
                (
                    now,
                    0,
                    latest["id"],
                    json.dumps(ranking),
                    json.dumps(explanations),
                    json.dumps(details),
                    source_version,
                    model,
                ),
            )
            for c in comments:
                self.connection.execute(
                    "UPDATE tier_comments SET processed=1 WHERE message_id=?",
                    (c["message_id"],),
                )
            self.connection.execute(
                "UPDATE tier_meta SET value='poll-queued' WHERE key='analysis_status'"
            )
        return True

    def poll_counts(self, proposal_id):
        counts = {"approve": 0, "keep": 0, "test": 0}
        for row in self.rows(
            "SELECT choice,COUNT(*) AS n FROM tier_votes WHERE proposal_id=? GROUP BY choice",
            (proposal_id,),
        ):
            counts[row["choice"]] = row["n"]
        return counts

    def remember_poll(
        self,
        proposal_id,
        guild_id,
        channel_id,
        message_id,
        status="open",
        *,
        published_at=None,
    ):
        with self.connection:
            proposal = self.proposal(proposal_id)
            if status == "open" and proposal and proposal["status"] == "queued":
                opened = max(
                    proposal["created_at"],
                    min(
                        self.clock(),
                        published_at if published_at is not None else self.clock(),
                    ),
                )
                self.connection.execute(
                    "UPDATE tier_proposals SET status='open',opened_at=?,closes_at=? WHERE id=? AND status='queued'",
                    (opened, opened + 600, proposal_id),
                )
                self.connection.execute(
                    "UPDATE tier_meta SET value='poll-open' WHERE key='analysis_status'"
                )
            self.connection.execute(
                "INSERT OR REPLACE INTO tier_poll_messages VALUES(?,?,?,?,?,?)",
                (
                    proposal_id,
                    str(guild_id),
                    str(channel_id),
                    str(message_id),
                    self.clock(),
                    status,
                ),
            )

    def poll_at(self, guild_id, channel_id, message_id):
        rows = self.rows(
            "SELECT * FROM tier_poll_messages WHERE guild_id=? AND channel_id=? AND message_id=?",
            (str(guild_id), str(channel_id), str(message_id)),
        )
        return rows[0] if rows else None

    def vote(self, proposal_id, user_id, guild_id, channel_id, message_id, choice):
        if choice not in ("approve", "keep", "test"):
            raise ValueError("Escolha uma das opções da votação.")
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            proposal = self.proposal(proposal_id)
            if (
                not proposal
                or proposal["status"] != "open"
                or self.clock() >= proposal["closes_at"]
            ):
                raise ValueError("Essa votação já terminou.")
            receipt = self.poll_at(guild_id, channel_id, message_id)
            if (
                not receipt
                or receipt["proposal_id"] != proposal_id
                or receipt["status"] != "open"
            ):
                raise ValueError("Esta mensagem não pertence à votação.")
            existing_vote = self.connection.execute(
                "SELECT 1 FROM tier_votes WHERE proposal_id=? AND user_id=?",
                (proposal_id, str(user_id)),
            ).fetchone()
            if (
                self.connection.execute("SELECT COUNT(*) FROM tier_votes").fetchone()[0]
                >= 50000
            ) and not existing_vote:
                raise ValueError("O registro de votos precisa de manutenção.")
            self.connection.execute(
                "INSERT INTO tier_votes VALUES(?,?,?,?,?) ON CONFLICT(proposal_id,user_id) DO UPDATE SET guild_id=excluded.guild_id,choice=excluded.choice,created_at=excluded.created_at",
                (proposal_id, str(user_id), str(guild_id), choice, self.clock()),
            )

    def resolve_due(self, *, source_version, proposal_ids=None):
        changed = False
        eligible = None if proposal_ids is None else set(proposal_ids)
        for item in self.rows(
            "SELECT id FROM tier_proposals WHERE status='open' AND closes_at<=?",
            (self.clock(),),
        ):
            if eligible is not None and item["id"] not in eligible:
                continue
            with self.connection:
                self.connection.execute("BEGIN IMMEDIATE")
                proposal = self.proposal(item["id"])
                if proposal["status"] != "open":
                    continue
                counts = self.poll_counts(proposal["id"])
                total = sum(counts.values())
                if (
                    proposal["base_publication"] != self.latest()["id"]
                    or proposal["source_version"] != source_version
                    or self._inactive(proposal["ranking"], proposal["details"])
                ):
                    status = "outdated"
                elif not self.connection.execute(
                    "SELECT 1 FROM tier_poll_messages WHERE proposal_id=? AND status!='removed'",
                    (proposal["id"],),
                ).fetchone():
                    status = "unavailable"
                elif total < 5:
                    status = "not-enough-votes"
                elif counts["test"] >= max(counts["approve"], counts["keep"]):
                    status = "needs-tests"
                elif (
                    counts["approve"] * 3 >= total * 2
                    and counts["approve"] > counts["keep"]
                ):
                    status = "approved"
                else:
                    status = "maintained"
                if status == "approved":
                    changed = (
                        self.publish(
                            proposal["ranking"],
                            proposal["explanations"],
                            change_details=proposal["details"],
                            source_version=proposal["source_version"],
                            model=proposal["model"],
                            comments=[],
                            transactional=False,
                        )
                        or changed
                    )
                self.connection.execute(
                    "UPDATE tier_proposals SET status=?,outcome=? WHERE id=? AND status=?",
                    (status, json.dumps(counts), proposal["id"], "open"),
                )
                self.connection.execute(
                    "UPDATE tier_meta SET value=? WHERE key='analysis_status'",
                    (status,),
                )
        return changed

    def decisions(self):
        rows = self.rows(
            "SELECT id,status,outcome,details FROM tier_proposals WHERE status NOT IN ('open','queued') ORDER BY id DESC LIMIT 2"
        )
        return [
            {
                "status": r["status"],
                "votes": json.loads(r["outcome"]),
                "units": list(json.loads(r["details"])),
            }
            for r in rows
        ]

    def poll_messages(self):
        return self.rows("SELECT * FROM tier_poll_messages")

    def public_results_waiting(self, guild_id=None):
        sql = "SELECT COUNT(*) AS total FROM tier_poll_messages m JOIN tier_proposals v ON v.id=m.proposal_id JOIN tier_panels p ON p.guild_id=m.guild_id AND p.channel_id=m.channel_id WHERE m.status!='removed' AND v.status NOT IN ('open','queued') AND m.updated_at<?"
        args = [self.clock() - 180]
        if guild_id is not None:
            sql += " AND m.guild_id=?"
            args.append(str(guild_id))
        return self.rows(sql, args)[0]["total"]

    def report(self, proposal_id, user_id, guild_id, reason):
        if not self.proposal(proposal_id) or not 15 <= len(reason.strip()) <= 800:
            raise ValueError(
                "Informe o problema em 15 a 800 caracteres numa proposta recente."
            )
        if (
            self.connection.execute(
                "SELECT COUNT(*) FROM tier_reports WHERE status='pending'"
            ).fetchone()[0]
            >= 1000
        ):
            raise ValueError("A fila de revisão está cheia. Tente mais tarde.")
        if (
            self.connection.execute(
                "SELECT COUNT(*) FROM tier_reports WHERE user_id=? AND created_at>?",
                (str(user_id), self.clock() - 86400),
            ).fetchone()[0]
            >= 5
        ):
            raise ValueError("Você já enviou cinco relatos hoje. Aguarde a revisão.")
        with self.connection:
            self.connection.execute(
                "INSERT INTO tier_reports(proposal_id,user_id,guild_id,reason,created_at) VALUES(?,?,?,?,?) ON CONFLICT(proposal_id,user_id) DO UPDATE SET reason=excluded.reason",
                (
                    proposal_id,
                    str(user_id),
                    str(guild_id),
                    reason.strip(),
                    self.clock(),
                ),
            )

    def audit(self, kind, actor_id, reason, publication_id=None):
        cursor = self.connection.execute(
            "INSERT INTO tier_audit(kind,actor_id,reason,publication_id,created_at) VALUES(?,?,?,?,?)",
            (kind, str(actor_id), reason, publication_id, self.clock()),
        )
        return cursor.lastrowid

    def rollback(self, expected_publication, actor_id, reason):
        if not 20 <= len(reason.strip()) <= 700:
            raise ValueError("Explique a correção em 20 a 700 caracteres.")
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            current = self.latest()
            if current["id"] != expected_publication:
                raise ValueError("A classificação mudou. Abra a revisão novamente.")
            rows = self.rows(
                "SELECT * FROM tier_publications WHERE id<? ORDER BY id DESC LIMIT 1",
                (current["id"],),
            )
            previous = (
                rows[0]
                if rows
                else {
                    "ranking": "[]",
                    "explanations": "{}",
                    "source_version": current["source_version"],
                }
            )
            previous_ranking = json.loads(previous["ranking"])
            previous_explanations = json.loads(previous["explanations"])
            if not valid_ranking(previous_ranking):
                raise ValueError(
                    "Essa versão usa as antigas notas por letras. O histórico foi preservado, mas não pode substituir a classificação por função."
                )
            if self.catalog is not None:
                retired = set(getattr(self.catalog, "retired", {}))
                previous_ranking = [
                    r for r in previous_ranking if r["unit_id"] not in retired
                ]
                previous_explanations = {
                    u: d for u, d in previous_explanations.items() if u not in retired
                }
            if not current["id"] or (current["ranking"] == previous_ranking):
                raise ValueError("Não há uma alteração disponível para reverter.")
            self.publish(
                previous_ranking,
                previous_explanations,
                source_version=previous["source_version"],
                model="human-correction",
                comments=[],
                transactional=False,
            )
            for proposal in self.rows(
                "SELECT id FROM tier_proposals WHERE status IN ('open','queued')"
            ):
                self.connection.execute(
                    "UPDATE tier_proposals SET status='outdated',outcome=? WHERE id=?",
                    (json.dumps(self.poll_counts(proposal["id"])), proposal["id"]),
                )
            self.audit("rollback", actor_id, reason.strip(), self.latest()["id"])
        return self.latest()

    def cancel_proposal(self, proposal_id, actor_id, reason):
        if not 20 <= len(reason.strip()) <= 700:
            raise ValueError("Explique a suspensão em 20 a 700 caracteres.")
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            proposal = self.proposal(proposal_id)
            if not proposal or proposal["status"] not in ("open", "queued"):
                raise ValueError("Essa proposta já foi encerrada.")
            self.connection.execute(
                "UPDATE tier_proposals SET status='suspended',outcome=? WHERE id=?",
                (json.dumps(self.poll_counts(proposal_id)), proposal_id),
            )
            self.audit(
                "proposal-suspended",
                actor_id,
                f"Proposta #{proposal_id} suspensa. " + reason.strip(),
            )
