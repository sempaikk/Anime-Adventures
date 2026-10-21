"""Contextual quiz media, without rarity frames or names that reveal answers."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
MEDIA_FILE = ROOT / "data" / "media.json"
PUBLIC_ASSETS = "https://raw.githubusercontent.com/sempaikk/Anime-Adventures/main/"


def load_media(path=MEDIA_FILE):
    data = json.loads(path.read_text(encoding="utf-8"))
    for asset in data["assets"].values():
        if asset["kind"] not in ("wiki", "user_provided"):
            raise ValueError("A mídia deve vir do usuário ou da wiki de Anime Adventures.")
        for value in (asset["path"], asset.get("quiz_path")):
            if value:
                local = (ROOT / value).resolve()
                if not local.is_relative_to(ROOT / "assets") or not local.is_file():
                    raise ValueError("Arquivo de mídia inválido.")
        if asset["kind"] == "wiki":
            url = urlparse(asset["source_page"])
            if url.scheme != "https" or url.hostname != "animeadventures.fandom.com":
                raise ValueError("Origem de mídia inválida.")
            image_url = urlparse(asset["source_url"])
            if image_url.hostname != "static.wikia.nocookie.net" or not image_url.path.startswith("/animeadventures/"):
                raise ValueError("A imagem precisa pertencer à wiki de Anime Adventures.")
        elif not asset.get("approval"):
            raise ValueError("Banner sem referência à imagem fornecida pelo usuário.")
    return data


MEDIA = load_media()


def get_asset(key):
    item = MEDIA["assets"].get(key)
    return {**item, "url": PUBLIC_ASSETS + item["path"]} if item else None


def banner(index=0):
    banners = MEDIA["banners"]
    return get_asset(banners[index % len(banners)]) if banners else None


def for_question(question, *, revealed=False):
    prefix = question.id.split(":", 1)[0]
    units = MEDIA["units"]
    if prefix == "unit":
        asset = get_asset(units.get(question.subject))
        if revealed or not asset:
            return asset
        if not asset.get("quiz_path"):
            return None
        # ALT text and the public filename must not contain the character's name.
        return {**asset, "url": PUBLIC_ASSETS + asset["quiz_path"],
                "alt": "Personagem de Anime Adventures. Use a imagem e a dica para responder."}
    if prefix == "rarity":
        asset = get_asset(units.get(question.subject))
        return asset if revealed or (asset and asset.get("rarity_safe") is True) else None
    if prefix == "stats":
        return get_asset(units.get(question.subject))
    if prefix == "evolution":
        target = question.id.split(":", 1)[1] if revealed else question.subject
        # Never substitute the base portrait when the answer calls for an evolved form.
        return get_asset(units.get(target))
    if prefix in ("world", "act", "boss"):
        parts = question.id.split(":")
        world = parts[1]
        if prefix == "world" and parts[-1] == "order" and not revealed:
            return None
        return get_asset(MEDIA["maps"].get(world))
    if prefix == "food":
        _, name, kind = question.id.split(":", 2)
        if kind == "name" and not revealed:
            return None
        return get_asset(MEDIA["foods"].get(name))
    return None
