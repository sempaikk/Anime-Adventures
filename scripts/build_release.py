"""Freeze a private deploy fingerprint after changing runtime, data and tests."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bot_release import manifest

if __name__ == "__main__":
    data = manifest(sys.argv[1])
    (ROOT / "data/build.json").write_text(json.dumps(data, indent=2) + "\n")
    print(data["version"], data["fingerprint"][:12], len(data["files"]), "arquivos")
