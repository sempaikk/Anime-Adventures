"""A frozen Wiki baseline; never fabricates votes or overwrites community decisions."""

import hashlib
import json

from community_domain import ROOT
from tier_categories import MODES, POLICY, TIERS, valid_ranking

SOURCE = ROOT / "docs/sources/tierlist-46773.wiki"
REFERENCE = ROOT / "data/tier_initial_wiki.json"


def load_reference(path=REFERENCE):
    if path.stat().st_size > 512 * 1024:
        raise ValueError("A referência inicial excede o limite.")
    data = json.loads(path.read_text())
    if (
        data.get("schema") != 1
        or data.get("revision") != 46773
        or data.get("source_url")
        != "https://animeadventures.fandom.com/wiki/Tier_Lists?oldid=46773"
        or data.get("source_sha256") != hashlib.sha256(SOURCE.read_bytes()).hexdigest()
        or not isinstance(data.get("modes"), dict)
        or set(data["modes"]) != set(MODES)
    ):
        raise ValueError("A referência inicial não corresponde à revisão da Wiki.")
    lines = SOURCE.read_text().splitlines()
    for rows in data["modes"].values():
        ranking = [{"unit_id": r["unit_id"], "tier": r["tier"]} for r in rows]
        if not valid_ranking(ranking) or not ranking:
            raise ValueError("A referência inicial tem categorias ou formas inválidas.")
        for row in rows:
            if (
                row["tier"] not in TIERS
                or not isinstance(row.get("line"), int)
                or not 1 <= row["line"] <= len(lines)
                or "{{TierList/Item|" + row["source_name"] not in lines[row["line"] - 1]
            ):
                raise ValueError(
                    "Uma identidade inicial não corresponde à fonte registrada."
                )
    return data


def seed_initial(store, catalog, *, reference=None):
    from tier_balance import revision

    if revision(store):
        return  # A pre-update reference must never be reapplied after a game update.
    data = load_reference() if reference is None else reference
    # Validate both lists completely before making any write.
    for rows in data["modes"].values():
        if not valid_ranking(
            [{"unit_id": r["unit_id"], "tier": r["tier"]} for r in rows]
        ):
            raise ValueError("A referência inicial está inválida.")
    with store.connection:
        store.connection.execute("BEGIN IMMEDIATE")
        for mode in MODES:
            marker = f"wiki_seed:{POLICY}:{mode}"
            current = store.latest(mode)
            pending = store.rows(
                "SELECT 1 FROM tier_proposals WHERE mode=? AND status IN ('open','queued') LIMIT 1",
                (mode,),
            )
            ranking = [
                {"unit_id": r["unit_id"], "tier": r["tier"]}
                for r in data["modes"][mode]
                if r["unit_id"] in catalog.units
            ]
            old_marker = store.get(marker)
            if old_marker:
                # Complete an untouched earlier seed only. An open proposal keeps its
                # exact base; community decisions and owner corrections are never reset.
                previous_ids = {r["unit_id"] for r in current["ranking"]}
                if (
                    pending
                    or old_marker != str(current["id"])
                    or current["model"] != "wiki-baseline"
                    or len(ranking) <= len(current["ranking"])
                    or [r for r in ranking if r["unit_id"] in previous_ids]
                    != current["ranking"]
                ):
                    continue
            preserve = not old_marker and (
                pending or (current["id"] and current["model"] != "category-migration")
            )
            value = "preserved-existing"
            if not preserve:
                if not ranking:
                    continue
                cursor = store.connection.execute(
                    "INSERT INTO tier_publications(created_at,ranking,explanations,source_version,model,mode) VALUES(?,?,?,?,?,?)",
                    (
                        store.clock(),
                        json.dumps(ranking),
                        "{}",
                        f"wiki-tierlist:{data['revision']}:{data['source_sha256']}",
                        "wiki-baseline",
                        mode,
                    ),
                )
                value = str(cursor.lastrowid)
                store.audit(
                    "wiki-baseline",
                    "system",
                    MODES[mode]
                    + f": base inicial com {len(ranking)} formas identificadas na revisão {data['revision']} da Wiki. "
                    "São posições de referência, sem votos da comunidade. A página alerta que pode estar imprecisa; nomes sem correspondência exata ficam pendentes. "
                    + data["source_url"],
                    cursor.lastrowid,
                )
            store.connection.execute(
                "INSERT OR REPLACE INTO tier_meta VALUES(?,?)", (marker, value)
            )
        if not any(
            (store.get(f"wiki_seed:{POLICY}:{mode}") or "").isdigit() for mode in MODES
        ):
            return
        store.connection.execute(
            "INSERT OR REPLACE INTO tier_meta VALUES('wiki_initial_reference',?)",
            (
                json.dumps(
                    {
                        "url": data["source_url"],
                        "revision": data["revision"],
                        "revision_timestamp": data["revision_timestamp"],
                        "unresolved": len(data["unresolved"]),
                        "counts": {m: len(r) for m, r in data["modes"].items()},
                    }
                ),
            ),
        )
