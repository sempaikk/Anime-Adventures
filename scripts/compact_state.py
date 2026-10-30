"""Offline, opt-in SQLite compaction after a fresh private snapshot and size checks."""

import argparse
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
from contextlib import closing

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from bot_storage import acquire_lease
from storage_maintenance import snapshot_database,verify_database
from instance_storage import InstanceStorage


def compact_state(directory):
    directory=Path(directory).resolve()
    path=directory/'bot.sqlite3'
    with acquire_lease(directory):
        verify_database(path)
        before=path.stat().st_size
        with closing(sqlite3.connect(path)) as db:
            free=db.execute('PRAGMA freelist_count').fetchone()[0]*db.execute('PRAGMA page_size').fetchone()[0]
            if free < 8*1024*1024 or free < before*.25:
                return {'compacted':False,'reason':'insufficient_reusable_space','bytes':before}
            quota=InstanceStorage(ROOT,directory,None,limit_mb=os.getenv('INSTANCE_DISK_LIMIT_MB','512'))
            available=min(shutil.disk_usage(directory).free,max(0,quota.limit-quota.measure()))
            if available < 3*before+32*1024*1024:
                raise OSError('Not enough space for a verified backup and safe offline compaction.')
            snapshot=directory/'backups'/'before-compaction.sqlite3'
            snapshot_database(path,snapshot)
            db.execute('VACUUM')
        verify_database(path)
        return {'compacted':True,'before':before,'after':path.stat().st_size,'snapshot_verified':True}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('data_dir',type=Path)
    args=parser.parse_args()
    print(json.dumps(compact_state(args.data_dir)))
