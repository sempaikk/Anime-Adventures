"""Run only with the bot stopped. A verified snapshot includes its media directory."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tier_backup import restore_snapshot

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    print(restore_snapshot(args.snapshot, args.data_dir, replace=args.replace))
