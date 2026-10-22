"""Bundle attributed wiki text for inference. Lua source is read as text, never executed."""

import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build(corpus):
    corpus = Path(corpus)
    pages = json.loads((corpus / "page_catalogue.json").read_text())
    by_title = {p["title"]: p for p in pages if not p.get("redirect_target")}
    module = by_title["Module:UnitData/Data"]
    lua = (corpus / module["content_file"]).read_text()
    starts = list(re.finditer(r"^\t([A-Za-z0-9_]+)\s*=\s*\{", lua, re.M))
    blocks = {
        m.group(1): lua[
            m.start() : starts[i + 1].start() if i + 1 < len(starts) else len(lua)
        ].strip()
        for i, m in enumerate(starts)
    }
    units = json.loads((ROOT / "data/community_catalog.json").read_text())["units"]
    sources = {}
    for unit in units:
        uid = unit["id"]
        page = by_title.get(unit["name"])
        if page:
            body = (corpus / page["content_file"]).read_text()
            sources[uid + ":article"] = {
                "unit_id": uid,
                "title": page["title"],
                "url": page["source_url"] + "?oldid=" + str(page["revision_id"]),
                "revision": page["revision_id"],
                "text": body,
                "sha256": hashlib.sha256(body.encode()).hexdigest(),
            }
        if uid in blocks:
            body = blocks[uid]
            sources[uid + ":data"] = {
                "unit_id": uid,
                "title": "UnitData · " + unit["name"],
                "url": module["source_url"] + "?oldid=" + str(module["revision_id"]),
                "revision": module["revision_id"],
                "text": body,
                "sha256": hashlib.sha256(body.encode()).hexdigest(),
            }
    digest = hashlib.sha256(
        json.dumps(sources, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    result = {
        "schema": 1,
        "version": digest,
        "policy": "Wiki snapshot, not live game telemetry. Quotes must match the supplied excerpt and unit form. Conflicting or missing evidence does not establish superiority.",
        "sources": sources,
    }
    (ROOT / "data/tier_evidence.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                "sources": len(sources),
                "units_with_sources": len({s["unit_id"] for s in sources.values()}),
                "version": digest,
            }
        )
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--corpus", required=True)
    build(p.parse_args().corpus)
