"""Private release identification and bounded verification of shipped program files."""

import hashlib
import json
from pathlib import Path

from community_domain import ROOT


def shipped_files(root=ROOT):
    paths = {root / "requirements.txt", root / "requirements-pc.txt"}
    for pattern in ("*.py", "*.cmd", "data/*.json", "scripts/*.py", "scripts/*.ps1", "tests/*.py", "assets/banner-votes/*.png"):
        paths.update(root.glob(pattern))
    paths.discard(root / "data/tier_build.json")
    return sorted(path for path in paths if path.is_file())


def manifest(version, root=ROOT):
    files = {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in shipped_files(root)
    }
    fingerprint = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    return {"schema": 1, "version": version, "fingerprint": fingerprint, "files": files}


def build_info(root=ROOT):
    """Return only file names/counts, never file contents or environment values."""
    try:
        path = root / "data/tier_build.json"
        if path.stat().st_size > 256 * 1024:
            raise ValueError("oversized manifest")
        expected = json.loads(path.read_text())
        files = expected["files"]
        if (
            expected.get("schema") != 1
            or not isinstance(files, dict)
            or not 1 <= len(files) <= 1000
            or not isinstance(expected.get("version"), str)
            or not 1 <= len(expected["version"]) <= 40
        ):
            raise ValueError("invalid manifest")
        actual = {}
        for name in files:
            if (
                not isinstance(name, str)
                or Path(name).is_absolute()
                or not (root / name).resolve().is_relative_to(root.resolve())
            ):
                raise ValueError("invalid manifest path")
            path = root / name
            if path.is_file():
                if path.stat().st_size > 16 * 1024 * 1024:
                    raise ValueError("oversized program file")
                actual[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        fingerprint = hashlib.sha256(
            json.dumps(actual, sort_keys=True).encode()
        ).hexdigest()
        changed = sorted(name for name in files if files[name] != actual.get(name))
        return {
            "version": expected["version"],
            "fingerprint": fingerprint,
            "verified": not changed and fingerprint == expected["fingerprint"],
            "files_checked": len(actual),
            "changed_files": changed[:20],
        }
    except (OSError, ValueError, KeyError, TypeError):
        return {
            "version": "não identificada",
            "verified": False,
            "files_checked": 0,
            "changed_files": [],
        }


def label(info):
    return info["version"] + (
        " · " + info["fingerprint"][:12] if info.get("fingerprint") else ""
    )
