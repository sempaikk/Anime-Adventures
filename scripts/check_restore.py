"""Offline restore drill for a private snapshot. Does not print rows or credentials."""

import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backup_check import check_restore

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot',type=Path)
    args=parser.parse_args()
    print(json.dumps(check_restore(args.snapshot)))
