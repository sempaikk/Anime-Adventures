"""A single global ranking, opt-in analysis sources and atomic publications."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from pathlib import Path
from contextlib import nullcontext

TIERS = ("META", "S", "A", "B", "C", "D", "E")
REQUIRED_TABLES = {
    "tier_meta",
    "tier_channels",
    "tier_comments",
    "tier_publications",
    "tier_proposals",
    "tier_votes",
    "tier_poll_messages",
    "tier_destinations",
}


class TierStore:
    def __init__(self, path, *, clock=time.time):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self.connection = sqlite3.connect(self.path, timeout=1)
        self.connection.row_factory = sqlite3.Row
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
        """)
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

    def ingest(self, message_id, user_id, guild_id, channel_id, body, units):
        if (
            not self.consented(user_id)
            or not self.channel_enabled(guild_id, channel_id)
            or not units
        ):
            return False
        if not 12 <= len(body) <= 1500:
            return False
        if self.path.stat().st_size >= 64 * 1024 * 1024:
            return False
        now = self.clock()
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
        actor = hmac.new(
            bytes.fromhex(self.get("salt")), str(user_id).encode(), hashlib.sha256
        ).hexdigest()[:24]
        with self.connection:
            cursor = self.connection.execute(
                "INSERT OR IGNORE INTO tier_comments VALUES(?,?,?,?,?,?,?,?,0)",
                (
                    str(message_id),
                    str(user_id),
                    actor,
                    str(guild_id),
                    str(channel_id),
                    body,
                    json.dumps(sorted(units)),
                    now,
                ),
            )
        return bool(cursor.rowcount)

    def pending(self, limit=16):
        return self.rows(
            """SELECT c.* FROM tier_comments c JOIN tier_channels t ON t.channel_id=c.channel_id AND t.guild_id=c.guild_id
           JOIN tier_consents u ON u.user_id=c.user_id WHERE c.processed=0 AND c.created_at>=? ORDER BY c.created_at,c.message_id LIMIT ?""",
            (self.clock() - 7 * 86400, limit),
        )

    def recent(self):
        return self.rows(
            "SELECT * FROM tier_comments WHERE created_at>=? ORDER BY created_at DESC LIMIT 200",
            (self.clock() - 7 * 86400,),
        )

    def still_allowed(self, comments):
        return all(
            self.consented(c["user_id"])
            and self.channel_enabled(c["guild_id"], c["channel_id"])
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
                            else f"Saiu do Meta para {row['tier']}. " + detail["reason"]
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
                "INSERT OR REPLACE INTO tier_panels VALUES(?,?,?,?,?)",
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
                "DELETE FROM tier_proposals WHERE status!='open' AND id NOT IN (SELECT id FROM tier_proposals ORDER BY id DESC LIMIT 50)"
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
            "SELECT id FROM tier_proposals WHERE status='open' ORDER BY id DESC LIMIT 1"
        )
        return self.proposal(rows[0]["id"]) if rows else None

    def may_propose(self):
        if self.active_proposal():
            return False
        row = self.connection.execute(
            "SELECT MAX(created_at) FROM tier_proposals"
        ).fetchone()[0]
        return row is None or self.clock() - row >= 3600

    def create_proposal(
        self, ranking, explanations, *, details, source_version, model, comments
    ):
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
            # Do not repeat the same unresolved comparison every hour without a new outcome.
            for previous in self.rows(
                "SELECT ranking,status,details FROM tier_proposals WHERE created_at>?",
                (now - 86400,),
            ):
                if (
                    json.loads(previous["ranking"]) == ranking
                    and previous["status"] != "approved"
                    and {
                        u: sorted((s["url"], s["quote"]) for s in d["sources"])
                        for u, d in json.loads(previous["details"]).items()
                    }
                    == {
                        u: sorted((s["url"], s["quote"]) for s in d["sources"])
                        for u, d in details.items()
                    }
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
              VALUES(?,?,?,?,?,?,?,?,'open')""",
                (
                    now,
                    now + 600,
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
                "UPDATE tier_meta SET value='poll-open' WHERE key='analysis_status'"
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
        self, proposal_id, guild_id, channel_id, message_id, status="open"
    ):
        with self.connection:
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
            if (
                self.connection.execute("SELECT COUNT(*) FROM tier_votes").fetchone()[0]
                >= 50000
            ):
                raise ValueError("O registro de votos precisa de manutenção.")
            self.connection.execute(
                "INSERT INTO tier_votes VALUES(?,?,?,?,?) ON CONFLICT(proposal_id,user_id) DO UPDATE SET guild_id=excluded.guild_id,choice=excluded.choice,created_at=excluded.created_at",
                (proposal_id, str(user_id), str(guild_id), choice, self.clock()),
            )

    def resolve_due(self, *, source_version):
        changed = False
        for item in self.rows(
            "SELECT id FROM tier_proposals WHERE status='open' AND closes_at<=?",
            (self.clock(),),
        ):
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
                ):
                    status = "outdated"
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
            "SELECT id,status,outcome,details FROM tier_proposals WHERE status!='open' ORDER BY id DESC LIMIT 2"
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
