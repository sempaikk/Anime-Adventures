"""Community opinions are evidence of player experience, not verified game statistics."""

from __future__ import annotations

import json
import re
import statistics
import unicodedata
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ROLES = {
    "damage": "Dano",
    "support": "Suporte",
    "control": "Controle",
    "economy": "Economia",
}
MODES = {
    "general": "Geral",
    "story": "História",
    "infinite": "Infinito",
    "raid": "Raids",
    "challenge": "Desafios",
}
TIERS = ("D", "C", "B", "A", "S")
MIN_SERVERS = 3
MIN_PER_SERVER = 3
REVIEW_WINDOW = 30 * 86400
CONSENT_VERSION = 1


def normalize(value):
    value = unicodedata.normalize("NFKD", str(value).casefold())
    return " ".join(
        re.sub(
            r"[\W_]+", " ", "".join(c for c in value if not unicodedata.combining(c))
        ).split()
    )


def clean_text(value, limit=1000):
    value = str(value)
    value = "".join(
        c
        for c in value
        if c not in "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
        and (unicodedata.category(c) != "Cc" or c == "\n")
    )
    value = value.strip()
    if not value or len(value) > limit:
        raise ValueError(f"Escreva entre 1 e {limit} caracteres.")
    return value


def validate_chat(value):
    value = clean_text(value)
    if re.search(r"(?:discord\.gg/|discord(?:app)?\.com/invite/)", value, re.I):
        raise ValueError("Convites de servidores não são enviados pelo chat global.")
    return value


@dataclass(frozen=True)
class Unit:
    id: str
    name: str
    aliases: tuple[str, ...]


class Catalog:
    def __init__(
        self,
        path=ROOT / "data/community_catalog.json",
        *,
        min_mention_length=4,
        extra_aliases=None,
    ):
        self.metadata = json.loads(Path(path).read_text())
        self.units = {
            row["id"]: Unit(row["id"], row["name"], tuple(row["aliases"]))
            for row in self.metadata["units"]
        }
        self.min_mention_length = min_mention_length
        self.extra_aliases = extra_aliases or {}
        self._index()

    def _index(self):
        self.aliases = {}
        for unit in self.units.values():
            for alias in (unit.id, unit.name, *unit.aliases):
                self.aliases.setdefault(normalize(alias), set()).add(unit.id)
        for unit_id, aliases in self.extra_aliases.items():
            if unit_id not in self.units:
                raise ValueError("Alias de unidade desconhecida.")
            for alias in aliases:
                self.aliases.setdefault(normalize(alias), set()).add(unit_id)
        # Only unambiguous names count as passive mentions.
        usable = [
            alias
            for alias, ids in self.aliases.items()
            if len(alias) >= self.min_mention_length and len(ids) == 1
        ]
        self.mention_pattern = re.compile(
            r"(?<!\w)(?:"
            + "|".join(re.escape(a) for a in sorted(usable, key=len, reverse=True))
            + r")(?!\w)"
        )

    def merge_units(self, rows):
        if not isinstance(rows, list) or len(rows) > 3000:
            raise ValueError("Catálogo fora dos limites.")
        updated = dict(self.units)
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("id"), str):
                raise ValueError("Identidade inválida no catálogo.")
            uid, name = row["id"], row["name"]
            aliases = row.get("aliases", [])
            if (
                not re.fullmatch(r"[a-zA-Z0-9_]{1,100}", uid)
                or not isinstance(name, str)
                or not 1 <= len(name) <= 150
                or not isinstance(aliases, list)
                or len(aliases) > 50
                or any(not isinstance(a, str) or len(a) > 150 for a in aliases)
            ):
                raise ValueError("Identidade inválida no catálogo.")
            old = updated.get(uid)
            names = {name, *aliases}
            if old:
                names.update((old.name, *old.aliases))
            updated[uid] = Unit(uid, name, tuple(sorted(names - {name}))[:50])
        if len(updated) > 3000:
            raise ValueError("Catálogo fora dos limites.")
        self.units = updated
        self._index()

    def resolve(self, value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Informe o personagem e a forma exatos.")
        if value in self.units:
            return self.units[value]
        if not normalize(value):
            exact = [u for u in self.units.values() if u.name == value.strip()]
            if len(exact) == 1:
                return exact[0]
            raise ValueError("Informe o personagem e a forma exatos.")
        matches = self.aliases.get(normalize(value), set())
        if len(matches) != 1:
            raise ValueError("Informe o nome completo da unidade e da forma.")
        return self.units[next(iter(matches))]

    def search(self, value, limit=25):
        query = normalize(value)
        found = [
            unit
            for unit in self.units.values()
            if not query
            or any(query in normalize(a) for a in (unit.name, unit.id, *unit.aliases))
        ]
        return sorted(
            found, key=lambda u: (not normalize(u.name).startswith(query), u.name)
        )[:limit]

    def mentions(self, text):
        normalized = normalize(str(text)[:4000])
        return set(
            next(iter(self.aliases[m.group()]))
            for m in self.mention_pattern.finditer(normalized)
        )


def consensus(reviews, *, local=False):
    """Each qualifying server contributes one median; large servers cannot buy weight."""
    grouped = {}
    for review in reviews:
        grouped.setdefault(str(review["guild_id"]), []).append(int(review["score"]))
    eligible = {
        guild: scores
        for guild, scores in grouped.items()
        if len(scores) >= MIN_PER_SERVER
    }
    voters = sum(map(len, eligible.values()))
    result = {
        "tier": None,
        "players": len(reviews),
        "servers": len(grouped),
        "eligible_players": voters,
        "eligible_servers": len(eligible),
        "agreement": 0.0,
        "confidence": "Em avaliação",
        "rating": None,
    }
    if local:
        if len(reviews) < 5:
            return result
        score = int(statistics.median(r["score"] for r in reviews))
        agreement = sum(abs(int(r["score"]) - score) <= 1 for r in reviews) / len(
            reviews
        )
        result.update(
            agreement=agreement,
            eligible_players=len(reviews),
            eligible_servers=len(grouped),
            rating=round(statistics.mean(r["score"] for r in reviews), 4),
        )
        if agreement >= 0.7:
            result.update(
                tier=TIERS[score],
                confidence="Alta" if len(reviews) >= 20 else "Moderada",
            )
        else:
            result["confidence"] = "Relatos divididos"
        return result
    if len(eligible) < MIN_SERVERS:
        return result
    medians = [statistics.median(scores) for scores in eligible.values()]
    # Ties between adjacent tiers resolve towards the lower one.
    score = int(statistics.median(medians))
    agreement = sum(abs(value - score) <= 0.5 for value in medians) / len(medians)
    result.update(
        agreement=agreement,
        rating=round(statistics.mean(statistics.mean(s) for s in eligible.values()), 4),
    )
    if agreement < 2 / 3:
        result["confidence"] = "Relatos divididos"
        return result
    result.update(
        tier=TIERS[score],
        confidence="Alta"
        if voters >= 30 and len(eligible) >= 5 and agreement >= 0.8
        else "Moderada",
    )
    return result
