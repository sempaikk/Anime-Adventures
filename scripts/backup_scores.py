"""Operator tool: verify or snapshot a score database; does not connect to Discord."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from storage_maintenance import snapshot_database, verify_database


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', type=Path)
    parser.add_argument('--output', type=Path, help='Create a verified snapshot at this path.')
    args = parser.parse_args()
    if args.output:
        snapshot_database(args.database, args.output)
        print('Verified snapshot:', args.output)
    else:
        verify_database(args.database)
        print('Database integrity: OK')
