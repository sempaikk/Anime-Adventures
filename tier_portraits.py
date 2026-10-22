"""A small, live contribution list; never exports ranking or player information."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from community_domain import ROOT
from community_ui import portraits


@dataclass(frozen=True)
class PortraitNeeds:
    names: tuple[str, ...]
    blob: bytes
    checksum: str

    @property
    def count(self):
        return len(self.names)


class PortraitInventory:
    def __init__(self, catalog, library, *, bundled=None):
        self.catalog, self.library = catalog, library
        self.bundled = bundled
        self._key = None
        self._value = None

    def get(self):
        # Immutable files are verified by MediaLibrary; name changes and wiki additions
        # also invalidate this cache. Recheck bundled files at least every five minutes.
        approved = self.library.approved()
        key = (
            tuple(sorted((u.id, u.name) for u in self.catalog.units.values())),
            tuple(sorted((u, a["suggestion_id"]) for u, a in approved.items())),
            int(self.library.store.clock() // 300),
        )
        if key == self._key:
            return self._value
        present = set(approved)
        allowed = (ROOT / "assets").resolve()
        bundled = portraits() if self.bundled is None else self.bundled
        for uid, item in bundled.items():
            path = Path(item["path"])
            path = (ROOT / path).resolve()
            try:
                if (
                    not path.is_relative_to(allowed)
                    or not path.is_file()
                    or not 0 < path.stat().st_size <= 4 * 1024 * 1024
                ):
                    continue
                with Image.open(path) as source:
                    if (
                        source.format not in ("PNG", "JPEG", "WEBP")
                        or source.width * source.height > 4_000_000
                        or getattr(source, "n_frames", 1) != 1
                    ):
                        continue
                    source.verify()
                present.add(uid)
            except (
                OSError,
                ValueError,
                UnidentifiedImageError,
                Image.DecompressionBombError,
            ):
                continue
        names = tuple(
            sorted(
                (u.name for u in self.catalog.units.values() if u.id not in present),
                key=str.casefold,
            )
        )
        blob = b""
        if names:
            lines = [
                "ANIME ADVENTURES — RETRATOS PENDENTES",
                "1 forma aguarda um retrato validado."
                if len(names) == 1
                else f"{len(names)} formas aguardam um retrato validado.",
                "",
                "Use Sugerir imagem no tópico do bot e informe a forma exata da lista.",
                "Envie PNG, JPG ou WebP estático, com até 4 MB. Uma sugestão basta;",
                "o retrato só entra na tier list depois da revisão do responsável.",
                "Acompanhe seu envio em Meus envios. Esta lista se atualiza após aprovações.",
                "",
                "Cada evolução conta separadamente. Estar nesta lista não indica tier ou força.",
                "As formas retiradas do catálogo ativo não são solicitadas aqui.",
                "",
                *[f"{i}. {' '.join(name.split())}" for i, name in enumerate(names, 1)],
                "",
            ]
            blob = "\n".join(lines).encode("utf-8")
        self._key = key
        self._value = PortraitNeeds(names, blob, hashlib.sha256(blob).hexdigest())
        return self._value
