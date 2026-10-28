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
from bot_release import build_info


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
    database = folder / "bot.sqlite3"
    legacy=False
    if not database.exists() and folder.exists():
        candidates=[]
        try:
            for candidate in folder.glob('*.sqlite3'):
                if candidate.is_symlink():
                    continue
                with closing(sqlite3.connect(candidate.resolve().as_uri()+'?mode=ro',uri=True,timeout=1)) as connection:
                    tables={row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    if tables & {'global_channels','banner_targets','daily_targets'}:
                        candidates.append(candidate)
            if len(candidates)>1:
                result.update(state='ambiguous',database_checked=True)
            elif candidates:
                database,legacy=candidates[0],True
        except sqlite3.Error:
            result.update(state='unavailable',database_checked=True)
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
                healthy = healthy and (legacy or {"bot_meta", "bot_audit"}.issubset(tables))
            result.update(state=('migration_required' if legacy else 'ok') if healthy else 'invalid', database_checked=True)
            if legacy:
                required=2*sum(p.stat().st_size for p in (database,Path(str(database)+'-wal')) if p.exists())+16*1024*1024
                result['storage_margin']=space.free>=required
        except sqlite3.Error:
            result.update(state="unavailable", database_checked=True)
    result["passed"] = (
        result["program_verified"]
        and result["storage_margin"]
        and result["state"] in ('new','ok','migration_required')
    )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args()
    report = check_release(data_dir=args.data_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["passed"] else 1)
