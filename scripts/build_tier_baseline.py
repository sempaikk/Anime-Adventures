"""Rebuild the attributed initial lists from committed Wiki snapshots and exact identities."""

import hashlib, json, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from community_domain import Catalog, normalize
from tier_catalog import TierCatalog
from tier_categories import LABELS
from tier_names import parse_names

root = Path(__file__).resolve().parents[1]
source = root / "docs/sources/tierlist-46773.wiki"
text = source.read_text()
all_units = Catalog()
active = TierCatalog()
names = {}
proof = {}
for revision, path in (
    (46960, root / "docs/sources/46960.wiki"),
    (33578, root / "docs/sources/tier-names-33578.wiki"),
    (43960, root / "docs/sources/tier-names-43960.wiki"),
):
    for name, uid in parse_names(path.read_text()):
        if uid not in all_units.units:
            continue
        key = normalize(name)
        names.setdefault(key, set()).add(uid)
        proof[(key, uid)] = (
            f"https://animeadventures.fandom.com/wiki/Module:UnitData/Data/Names?oldid={revision}"
        )
for sid, item in json.loads((root / "data/tier_evidence.json").read_text())[
    "sources"
].items():
    uid = item["unit_id"]
    if uid not in all_units.units:
        continue
    values = [item["title"].removeprefix("UnitData · ")]
    if sid.endswith(":data"):
        match = re.search(r"""\bname\s*=\s*(["'])([^\n]+?)\1""", item["text"])
        if match:
            values.append(match[2])
    for name in values:
        key = normalize(name)
        names.setdefault(key, set()).add(uid)
        proof[(key, uid)] = item["url"]
redirects = {
    normalize(x["title"]): x["target"]
    for x in json.loads((root / "docs/sources/tier-initial-redirects.json").read_text())
}
lookup = {label.replace("\n", " "): tier for tier, label in LABELS.items()}
result = {
    "schema": 1,
    "source_url": "https://animeadventures.fandom.com/wiki/Tier_Lists?oldid=46773",
    "revision": 46773,
    "revision_timestamp": "2025-04-18T10:45:03Z",
    "source_file": "docs/sources/tierlist-46773.wiki",
    "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    "warning": "This page is not completely updated and may be inaccurate.",
    "order": "Source order within each category; not a newly verified damage ranking.",
    "modes": {"infinite": [], "casual": []},
    "unresolved": [],
    "retired": [],
}
mode = tier = None
for number, line in enumerate(text.splitlines(), 1):
    match = re.search(r"TierList/Item Container\|[^\n]*id=([^|]+)\|name=([^|]+)", line)
    if match:
        mode = (
            "infinite"
            if match[1] == "infiniti"
            else "casual"
            if match[1] == "Story_Mode"
            else None
        )
        tier = lookup.get(match[2].strip())
    match = re.match(r"\s*{{TierList/Item\|([^|\n]+)", line)
    if not match or not mode or not tier:
        continue
    name = match[1].strip()
    key = normalize(name)
    ids = names.get(key, set())
    if not ids and key in redirects:
        key = normalize(redirects[key])
        ids = names.get(key, set())
    entry = {"source_name": name, "tier": tier, "line": number}
    if len(ids) != 1:
        result["unresolved"].append(dict(entry, mode=mode))
        continue
    uid = next(iter(ids))
    entry.update(unit_id=uid, identity_source=proof[(key, uid)])
    if uid not in active.units:
        result["retired"].append(dict(entry, mode=mode))
        continue
    result["modes"][mode].append(entry)
for mode, rows in result["modes"].items():
    assert len({r["unit_id"] for r in rows}) == len(rows), mode
(root / "data/tier_initial_wiki.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=2) + "\n"
)
print(
    {m: len(r) for m, r in result["modes"].items()},
    "unresolved",
    len(result["unresolved"]),
    "retired",
    len(result["retired"]),
)
