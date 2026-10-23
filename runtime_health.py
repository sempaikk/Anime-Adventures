"""Minimal readiness endpoints and bounded operational status; no player data."""

import logging
import time

from aiohttp import web

log = logging.getLogger("adventures.health")


class RuntimeHealth:
    def __init__(self, ready, database):
        self.ready = ready
        self.database = database
        self.started = time.monotonic()
        self.storage = None
        self.last_backup = None
        self.backup_error = False
        self.runner = None
        self.port = None
        self.storage_level = "unknown"
        self.probes = {}

    def add_probe(self, name, probe):
        self.probes[name] = probe

    def services_ready(self):
        try:
            return all(probe() for probe in self.probes.values())
        except Exception:
            return False

    def database_ready(self):
        try:
            connection = self.database()
            row = (
                connection.execute("SELECT 1").fetchone()
                if connection is not None
                else None
            )
            return row is not None and row[0] == 1
        except Exception:
            return False

    def update_storage(self, report):
        self.storage = report
        self.backup_error = False
        if report["backup"] == "created":
            self.last_backup = time.time()
        elif report.get("backup_modified"):
            self.last_backup = report["backup_modified"]
        total, free = report.get("total_bytes", 0), report["free_bytes"]
        ratio = 1 - free / total if total else 0
        level = (
            "critical"
            if ratio >= 0.9 or free < 16 * 1024 * 1024
            else "warning"
            if ratio >= 0.7
            else "ok"
        )
        if level != self.storage_level and level in ("warning", "critical"):
            log.warning("Alerta de armazenamento: %s; %s bytes livres.", level, free)
        self.storage_level = level

    def status(self):
        return {
            "gateway": bool(self.ready()),
            "database": self.database_ready(),
            "uptime": max(0, int(time.monotonic() - self.started)),
            "storage": self.storage_level,
            "last_backup": self.last_backup,
            "backup_error": self.backup_error,
        }

    async def start(self, port):
        async def live(request):
            return web.json_response(
                {"status": "alive"}, headers={"Cache-Control": "no-store"}
            )

        async def ready(request):
            healthy = (
                bool(self.ready())
                and self.database_ready()
                and self.storage_level != "critical"
                and self.services_ready()
            )
            return web.json_response(
                {"status": "ready" if healthy else "unavailable"},
                status=200 if healthy else 503,
                headers={"Cache-Control": "no-store"},
            )

        app = web.Application(client_max_size=1024)
        app.router.add_get("/health", live)
        app.router.add_get("/ready", ready)
        self.runner = web.AppRunner(app, access_log=None)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "0.0.0.0", port)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]

    async def close(self):
        if self.runner:
            await self.runner.cleanup()
            self.runner = None
