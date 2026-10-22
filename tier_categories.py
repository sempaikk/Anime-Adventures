"""One stored assessment per form; Meta is also projected into its primary role."""

ROLES = ("DAMAGE", "SUPPORT", "BUFF", "FARM")
TIERS = ("META", *ROLES)
LABELS = {
    "META": "Meta",
    "DAMAGE": "Damage",
    "SUPPORT": "Support",
    "BUFF": "Buff",
    "FARM": "Farm",
}
COLORS = {
    "META": "#920700",
    "DAMAGE": "#218900",
    "SUPPORT": "#588800",
    "BUFF": "#884500",
    "FARM": "#776000",
}
POLICY = "roles-v1"


def primary_role(row):
    return row.get("role") if row.get("tier") == "META" else row.get("tier")


def valid_ranking(ranking):
    if not isinstance(ranking, list):
        return False
    seen = set()
    for row in ranking:
        if not isinstance(row, dict):
            return False
        uid, tier = row.get("unit_id"), row.get("tier")
        if (
            not isinstance(uid, str)
            or not uid
            or uid in seen
            or not isinstance(tier, str)
            or tier not in TIERS
        ):
            return False
        expected = (
            {"unit_id", "tier", "role"} if tier == "META" else {"unit_id", "tier"}
        )
        if set(row) != expected or primary_role(row) not in ROLES:
            return False
        seen.add(uid)
    return True


def make_row(uid, tier, role):
    row = {"unit_id": uid, "tier": tier}
    if tier == "META":
        row["role"] = role
    if (
        role not in ROLES
        or (tier != "META" and role != tier)
        or not valid_ranking([row])
    ):
        raise ValueError(
            "A função principal precisa corresponder à categoria proposta."
        )
    return row


def rows_for(ranking, category):
    """Meta first in each role, with no duplicate stored records or invented roles."""
    rows = [
        row
        for row in ranking
        if (
            row.get("tier") == "META"
            if category == "META"
            else primary_role(row) == category
        )
    ]
    return sorted(rows, key=lambda row: row.get("tier") != "META")
