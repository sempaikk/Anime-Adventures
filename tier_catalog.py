"""Active game identities; explicit retirements survive wiki/cache refreshes."""

from __future__ import annotations

import json
from pathlib import Path

from community_domain import Catalog, ROOT


class TierCatalog(Catalog):
    def __init__(
        self, *args, availability=ROOT / "data/tier_availability.json", **kwargs
    ):
        policy = json.loads(Path(availability).read_text())
        if policy.get("schema") != 1 or not isinstance(policy.get("retired"), dict):
            raise ValueError("A lista de formas retiradas está inválida.")
        self.retired = policy["retired"]
        super().__init__(*args, **kwargs)
        if not set(self.retired) <= self.units.keys():
            raise ValueError(
                "A lista de formas retiradas contém uma identidade desconhecida."
            )
        self._exclude_retired()

    def _exclude_retired(self):
        for uid in self.retired:
            self.units.pop(uid, None)
        self._index()

    def merge_units(self, rows):
        super().merge_units(rows)
        self._exclude_retired()

    def resolve(self, value):
        from community_domain import normalize

        if isinstance(value, str) and any(
            normalize(value) in (normalize(uid), normalize(info["name"]))
            for uid, info in self.retired.items()
        ):
            raise ValueError("Essa forma foi retirada do catálogo ativo do jogo.")
        return super().resolve(value)

    def display_name(self, uid):
        if uid in self.retired:
            return self.retired[uid]["name"]
        return super().display_name(uid)
