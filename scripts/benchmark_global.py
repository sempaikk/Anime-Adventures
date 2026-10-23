"""Offline queue capacity measurement. Temporary SQLite only; no Discord or credentials."""

import argparse
import json
import resource
import statistics
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tier_store import TierStore
from global_store import GlobalStore, fingerprint


def benchmark(guilds=100, messages=40):
    if not 2 <= guilds <= 1000 or not 1 <= messages <= 200:
        raise ValueError("Use 2 a 1000 servidores e 1 a 200 mensagens.")
    with tempfile.TemporaryDirectory(prefix="global-capacity-") as folder:
        base = TierStore(Path(folder) / "tierlist.sqlite3")
        try:
            store = GlobalStore(base)
            for gid in range(1, guilds + 1):
                store.configure(gid, gid * 10, gid * 10 + 1, "synthetic-token", 0)
            store.consent(7)
            latencies = []
            accepted = 0
            limited = 0
            for n in range(messages):
                gid = 1 + n % min(5, guilds)
                message = SimpleNamespace(
                    id=100000 + n,
                    guild=SimpleNamespace(id=gid),
                    channel=SimpleNamespace(id=gid * 10),
                    author=SimpleNamespace(id=7),
                    created_at=datetime.now(timezone.utc),
                )
                data = {
                    "body": f"Artificial message {n}",
                    "files": [],
                    "username": "SIMULATION",
                }
                data["fingerprint"] = fingerprint(data)
                started = time.perf_counter()
                try:
                    row, _ = store.accept(message, data)
                    store.prepared(message.id, data, row["revision"])
                    accepted += 1
                except ValueError:
                    limited += 1
                latencies.append((time.perf_counter() - started) * 1000)
            started = time.perf_counter()
            jobs = store.jobs(limit=8)
            selection = (time.perf_counter() - started) * 1000
            return {
                "guilds": guilds,
                "accepted": accepted,
                "limited": limited,
                "pending_deliveries": store.one(
                    "SELECT COUNT(*) AS n FROM global_deliveries WHERE state='queued'"
                )["n"],
                "ingest_median_ms": round(statistics.median(latencies), 3),
                "ingest_max_ms": round(max(latencies), 3),
                "select_eight_ms": round(selection, 3),
                "distinct_destinations": len({r["channel_id"] for r in jobs}),
                "database_mib": round(base.path.stat().st_size / 1024 / 1024, 2),
                "process_peak_mib": round(
                    resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 2
                ),
                "external_network": False,
                "hosting_capacity_guarantee": False,
            }
        finally:
            base.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--guilds", type=int, default=100)
    p.add_argument("--messages", type=int, default=40)
    a = p.parse_args()
    print(json.dumps(benchmark(a.guilds, a.messages), indent=2))
