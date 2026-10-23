"""Scoped report decisions and expiring containment; never erase human originals."""

REPORT_STATES = {
    "pending": "Pendente",
    "resolved": "Resolvida",
    "dismissed": "Descartada",
}


class ModerationStore:
    def init_moderation(self):
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS global_report_actions(
          report_id INTEGER PRIMARY KEY,status TEXT NOT NULL,version INTEGER NOT NULL,
          actor TEXT NOT NULL,reason TEXT NOT NULL,action TEXT NOT NULL,updated REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS global_restrictions(
          scope TEXT NOT NULL,kind TEXT NOT NULL,target TEXT NOT NULL,until REAL NOT NULL,
          reason TEXT NOT NULL,actor TEXT NOT NULL,created REAL NOT NULL,
          PRIMARY KEY(scope,kind,target));
        CREATE INDEX IF NOT EXISTS global_restrictions_expiry ON global_restrictions(until);
        CREATE TABLE IF NOT EXISTS global_traffic(
          id TEXT PRIMARY KEY,guild_id TEXT NOT NULL,user_id TEXT NOT NULL,hash TEXT NOT NULL,
          invite INTEGER NOT NULL,created REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS global_traffic_origin ON global_traffic(guild_id,created);
        CREATE INDEX IF NOT EXISTS global_traffic_hash ON global_traffic(guild_id,hash,created);
        CREATE INDEX IF NOT EXISTS global_delivery_target ON global_deliveries(channel_id,state);
        CREATE INDEX IF NOT EXISTS global_delivery_origin ON global_messages(guild_id,updated);
        CREATE INDEX IF NOT EXISTS global_invitation_status ON global_invitations(status,attempted);
        """)

    def restriction(self, user, guild, source_guild=None):
        return self.one(
            """SELECT * FROM global_restrictions WHERE until>? AND
          ((kind='user' AND target=? AND scope IN ('*',?)) OR
           (kind='guild' AND scope='*' AND target IN (?,?))) ORDER BY until DESC LIMIT 1""",
            (
                self.clock(),
                str(user),
                str(guild),
                str(guild),
                str(source_guild or guild),
            ),
        )

    def restrict(self, scope, kind, target, seconds, actor, reason):
        if (
            kind not in ("user", "guild")
            or (kind == "guild" and str(scope) != "*")
            or not str(target).isdecimal()
            or not 0 < int(target) < 2**64
        ):
            raise ValueError("Escolha uma pessoa ou servidor válido.")
        if not 5 <= len(reason.strip()) <= 500 or not 0 < seconds <= 86400:
            raise ValueError(
                "Informe um motivo e uma duração entre um segundo e um dia."
            )
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO global_restrictions VALUES(?,?,?,?,?,?,?)",
                (
                    str(scope),
                    kind,
                    str(target),
                    self.clock() + seconds,
                    reason.strip(),
                    str(actor),
                    self.clock(),
                ),
            )

    def network_paused(self):
        return self.base.get("global-network-paused") == "1"

    def pause_network(self, enabled, actor, reason):
        if not 5 <= len(reason.strip()) <= 500:
            raise ValueError("Explique o motivo em 5 a 500 caracteres.")
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO tier_meta VALUES(?,?)",
                ("global-network-paused", str(int(enabled))),
            )
            if enabled:
                self.db.execute(
                    "UPDATE global_deliveries SET state='cancelled' WHERE state IN ('queued','preparing','uncertain','sending') AND source_id IN (SELECT id FROM global_messages WHERE deleted=0) AND suppressed=0"
                )
            else:
                self.db.execute(
                    "INSERT OR REPLACE INTO tier_meta VALUES(?,?)",
                    ("global-network-resumed-at", str(self.clock())),
                )
            self.base.audit(
                "global-network-pause" if enabled else "global-network-resume",
                actor,
                reason.strip(),
            )

    def report_page(self, scope, status="pending", page=0):
        if status not in (*REPORT_STATES, "all"):
            raise ValueError("Escolha um estado de denúncia válido.")
        where, args = ["r.created>?"], [self.clock() - 30 * 86400]
        if scope is not None:
            where.append("r.guild_id=?")
            args.append(str(scope))
        if status != "all":
            where.append(
                "COALESCE(a.status,CASE WHEN r.reviewed=1 THEN 'resolved' ELSE 'pending' END)=?"
            )
            args.append(status)
        sql = (
            " FROM global_reports r LEFT JOIN global_report_actions a ON a.report_id=r.id WHERE "
            + " AND ".join(where)
        )
        count = self.one("SELECT COUNT(*) AS n" + sql, args)["n"]
        page = max(0, min(page, max(0, (count - 1) // 5)))
        rows = self.rows(
            "SELECT r.*,COALESCE(a.status,CASE WHEN r.reviewed=1 THEN 'resolved' ELSE 'pending' END) AS status,COALESCE(a.version,0) AS version,COALESCE(a.actor,'') AS actor,COALESCE(a.reason,'') AS resolution,COALESCE(a.action,'') AS action,COALESCE(a.updated,0) AS updated"
            + sql
            + " ORDER BY r.id DESC LIMIT 5 OFFSET ?",
            (*args, page * 5),
        )
        return rows, count, page

    def report_record(self, ident, scope):
        row = self.one(
            "SELECT r.*,COALESCE(a.status,CASE WHEN r.reviewed=1 THEN 'resolved' ELSE 'pending' END) AS status,COALESCE(a.version,0) AS version FROM global_reports r LEFT JOIN global_report_actions a ON a.report_id=r.id WHERE r.id=? AND r.created>?",
            (ident, self.clock() - 30 * 86400),
        )
        if not row or (scope is not None and row["guild_id"] != str(scope)):
            raise ValueError("Esta denúncia não está disponível neste servidor.")
        return row

    def review_report(self, ident, scope, actor, expected, action, reason):
        if (
            action not in ("resolve", "dismiss", "reopen", "block-hour", "remove")
            or not 5 <= len(reason.strip()) <= 500
        ):
            raise ValueError(
                "Escolha uma ação e explique o motivo em 5 a 500 caracteres."
            )
        report = self.report_record(ident, scope)
        if report["version"] != expected:
            raise ValueError("A denúncia já mudou. Atualize a lista antes de decidir.")
        source = self.message(report["source_id"])
        if action in ("block-hour", "remove") and source is None:
            raise ValueError(
                "A mensagem saiu da janela de sincronização. Você ainda pode resolver ou descartar a denúncia."
            )
        if (
            action == "remove"
            and scope is not None
            and source["guild_id"] == str(scope)
        ):
            raise ValueError(
                "Esta é a mensagem original do servidor. Use a moderação do Discord para removê-la; o bot só solicita remoção das próprias cópias."
            )
        status = (
            "pending"
            if action == "reopen"
            else "dismissed"
            if action == "dismiss"
            else "resolved"
        )
        with self.db:
            result = self.db.execute(
                """INSERT INTO global_report_actions VALUES(?,?,?,?,?,?,?)
             ON CONFLICT(report_id) DO UPDATE SET status=excluded.status,version=excluded.version,
             actor=excluded.actor,reason=excluded.reason,action=excluded.action,updated=excluded.updated
             WHERE global_report_actions.version=?""",
                (
                    ident,
                    status,
                    expected + 1,
                    str(actor),
                    reason.strip(),
                    action,
                    self.clock(),
                    expected,
                ),
            )
            if result.rowcount != 1:
                raise ValueError("A denúncia já foi revisada. Atualize a lista.")
            self.db.execute(
                "UPDATE global_reports SET reviewed=? WHERE id=?",
                (int(status != "pending"), ident),
            )
            if action == "block-hour":
                self.db.execute(
                    "INSERT OR REPLACE INTO global_restrictions VALUES(?,?,?,?,?,?,?)",
                    (
                        "*" if scope is None else str(scope),
                        "user",
                        source["user_id"],
                        self.clock() + 3600,
                        reason.strip(),
                        str(actor),
                        self.clock(),
                    ),
                )
            if action == "remove":
                if scope is None:
                    self.db.execute(
                        "UPDATE global_messages SET deleted=1,payload='{}',revision=revision+1,updated=? WHERE id=? AND deleted=0",
                        (self.clock(), source["id"]),
                    )
                    self.db.execute(
                        "UPDATE global_deliveries SET state=CASE WHEN uncertain>=0 THEN 'uncertain' WHEN receipts='[]' THEN 'cancelled' ELSE 'queued' END,attempts=0,next_try=0 WHERE source_id=?",
                        (source["id"],),
                    )
                else:
                    self.db.execute(
                        "UPDATE global_deliveries SET suppressed=1,state=CASE WHEN uncertain>=0 THEN 'uncertain' WHEN receipts='[]' THEN 'cancelled' ELSE 'queued' END,next_try=0,attempts=0 WHERE source_id=? AND guild_id=?",
                        (source["id"], str(scope)),
                    )
            self.base.audit(
                "global-report-review",
                actor,
                f"Denúncia {ident}: {action}. {reason.strip()}",
            )
        return status
