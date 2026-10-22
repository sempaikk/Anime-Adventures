"""Stable Wiki-style categories, independent contexts, one row per form and mode."""

TIERS = (
    "META_HILL",
    "META_GROUND",
    "META_SUPPORT",
    "GOOD_HILL",
    "GOOD_GROUND",
    "GOOD_SUPPORT",
)
LABELS = {
    "META_HILL": "META\nHill/Hybrid",
    "META_GROUND": "META\nGround",
    "META_SUPPORT": "META\nSupport",
    "GOOD_HILL": "Good\nHill/Hybrid",
    "GOOD_GROUND": "Good\nGround",
    "GOOD_SUPPORT": "Good\nSupport",
}
COLORS = {
    "META_HILL": "#920700",
    "META_GROUND": "#5d4600",
    "META_SUPPORT": "#884500",
    "GOOD_HILL": "#246a00",
    "GOOD_GROUND": "#008080",
    "GOOD_SUPPORT": "#083e74",
}
MODES = {"infinite": "Infinite", "casual": "Casual · Story / Raids / Portals / Stages"}
POLICY = "placements-v1"


def is_meta(tier):
    return isinstance(tier, str) and tier.startswith("META_")


def label(tier):
    return LABELS.get(tier, tier).replace("\n", " ")


def valid_ranking(ranking):
    if not isinstance(ranking, list):
        return False
    seen = set()
    for row in ranking:
        if not isinstance(row, dict) or set(row) != {"unit_id", "tier"}:
            return False
        uid, tier = row["unit_id"], row["tier"]
        if (
            not isinstance(uid, str)
            or not uid
            or uid in seen
            or not isinstance(tier, str)
            or tier not in TIERS
        ):
            return False
        seen.add(uid)
    return True


def make_row(uid, tier):
    row = {"unit_id": uid, "tier": tier}
    if not valid_ranking([row]):
        raise ValueError("Escolha uma das seis categorias válidas da classificação.")
    return row


def rows_for(ranking, category):
    return [row for row in ranking if row.get("tier") == category]


def comment_context(text):
    import re
    from community_domain import normalize

    text = normalize(text)
    infinite = bool(re.search(r"\b(?:infinite|infinito|infinita)\b", text))
    casual = bool(
        re.search(
            r"\b(?:casual|story|historia|raids?|portals?|portais|legend|stages?|estagios?)\b",
            text,
        )
    )
    return (
        "both"
        if infinite and casual
        else "infinite"
        if infinite
        else "casual"
        if casual
        else "general"
    )
