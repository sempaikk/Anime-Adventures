"""Build identity aliases from the archived wiki names module, without importing tiers."""

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tier_names import parse_names


def build():
    source = ROOT / "docs/sources/46960.wiki"
    code = source.read_text()
    units = {}
    for name, uid in parse_names(code):
        entry = units.setdefault(uid, {"id": uid, "name": name, "aliases": []})
        if name != entry["name"]:
            entry["aliases"].append(name)
    history = []
    for revision in (33578, 43960):
        path = ROOT / f"docs/sources/tier-names-{revision}.wiki"
        history.append(
            {
                "url": f"https://animeadventures.fandom.com/wiki/Module:UnitData/Data/Names?oldid={revision}",
                "snapshot": str(path.relative_to(ROOT)),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
        for name, uid in parse_names(path.read_text()):
            if uid in units and name != units[uid]["name"]:
                units[uid]["aliases"].append(name)
    release = json.loads((ROOT / "data/release.json").read_text())
    for historical in release["units"]:
        if historical["id"] in units:
            entry = units[historical["id"]]
            entry["aliases"] += [
                historical["character"],
                historical["game_name"],
                historical.get("historical_name"),
                *historical.get("aliases", []),
            ]
    for entry in units.values():
        entry["aliases"] = sorted(
            {name for name in entry["aliases"] if name and name != entry["name"]}
        )
    result = {
        "schema": 1,
        "policy": "Identity catalog only. Availability, roles, strength and current balance are not inferred from this snapshot.",
        "source": "https://animeadventures.fandom.com/wiki/Module:UnitData/Data/Names?oldid=46960",
        "source_snapshot": "docs/sources/46960.wiki",
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "historical_identity_sources": history,
        "units": sorted(units.values(), key=lambda row: row["name"]),
    }
    (ROOT / "data/community_catalog.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    return result


if __name__ == "__main__":
    print(
        f"{len(build()['units'])} identidades; nenhuma classificação de força importada."
    )
