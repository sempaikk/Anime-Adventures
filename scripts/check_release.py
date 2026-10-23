"""Read-only deployment preflight: code fingerprint, state integrity and disk margin."""

import argparse
from contextlib import closing
import json
import shutil
import sqlite3
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tier_release import build_info


def check_release(root=ROOT, data_dir=None):
    build = build_info(root)
    folder = Path(data_dir) if data_dir else root / "state"
    existing = folder
    while not existing.exists() and existing.parent != existing:
        existing = existing.parent
    space = shutil.disk_usage(existing)
    result = {
        "version": build["version"],
        "fingerprint": build.get("fingerprint", "")[:12],
        "program_verified": build["verified"],
        "files_checked": build["files_checked"],
        "storage_margin": space.free >= 16 * 1024 * 1024,
        "state": "new",
        "database_checked": False,
        "credentials_read": False,
        "network_used": False,
    }
    database = folder / "tierlist.sqlite3"
    if database.exists():
        try:
            with closing(
                sqlite3.connect(
                    "file:" + quote(str(database.resolve())) + "?mode=ro",
                    uri=True,
                    timeout=1,
                )
            ) as connection:
                healthy = connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                healthy = healthy and {"tier_meta", "tier_publications"}.issubset(
                    tables
                )
            result.update(state="ok" if healthy else "invalid", database_checked=True)
        except sqlite3.Error:
            result.update(state="unavailable", database_checked=True)
    result["passed"] = (
        result["program_verified"]
        and result["storage_margin"]
        and result["state"] in ("new", "ok")
    )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args()
    report = check_release(data_dir=args.data_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["passed"] else 1)
