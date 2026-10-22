"""Bounded MediaWiki refresh with immutable revision references and safe fallback."""

from __future__ import annotations
import hashlib
import json
import re
import shutil
from urllib.parse import quote, urlparse, parse_qs
import aiohttp

API = "https://animeadventures.fandom.com/api.php"
WIKI = "https://animeadventures.fandom.com/wiki/"
NAMES = "Module:UnitData/Data/Names"
DATA = "Module:UnitData/Data"
MAX_RESPONSE = 6 * 1024 * 1024


class WikiSync:
    def __init__(self, store, catalog, evidence, session_factory=aiohttp.ClientSession):
        self.store, self.catalog, self.evidence = store, catalog, evidence
        self.session_factory = session_factory
        self.cache = store.path.parent / "wiki-cache.json"
        self.status = "cache"
        self.checked = {}
        self.cursor = 0
        if self.cache.is_file() and self.cache.stat().st_size < 8 * 1024 * 1024:
            try:
                data = json.loads(self.cache.read_text())
                self.catalog.merge_units(data.get("units", []))
                sources = dict(self.evidence.sources)
                for sid, item in data["sources"].items():
                    if self.valid_source(sid, item):
                        old = sources.get(sid)
                        if not old or item["revision"] >= old.get("revision", 0):
                            sources[sid] = item
                self.evidence.replace(sources)
                self.checked = data.get("checked", {})
            except (ValueError, KeyError, TypeError, OSError):
                self.status = "unavailable"

    def valid_source(self, sid, item):
        try:
            uri = urlparse(item["url"])
            return (
                sid in (item["unit_id"] + ":article", item["unit_id"] + ":data")
                and item["unit_id"] in self.catalog.units
                and uri.scheme == "https"
                and uri.hostname == "animeadventures.fandom.com"
                and not uri.username
                and not uri.password
                and uri.port in (None, 443)
                and uri.path.startswith("/wiki/")
                and type(item["revision"]) is int
                and item["revision"] > 0
                and parse_qs(uri.query).get("oldid") == [str(item["revision"])]
                and isinstance(item["text"], str)
                and 20 <= len(item["text"]) <= 300000
                and item["sha256"] == hashlib.sha256(item["text"].encode()).hexdigest()
            )
        except (KeyError, TypeError, ValueError):
            return False

    def save(self):
        data = {
            "schema": 1,
            "checked": self.checked,
            "sources": self.evidence.sources,
            "units": [
                {"id": u.id, "name": u.name, "aliases": list(u.aliases)}
                for u in self.catalog.units.values()
            ],
        }
        blob = json.dumps(data, ensure_ascii=False).encode()
        if len(blob) > 8 * 1024 * 1024:
            raise ValueError("Wiki cache exceeds local bound")
        if shutil.disk_usage(self.cache.parent).free < len(blob) + 16 * 1024 * 1024:
            raise OSError("Insufficient space for wiki cache")
        temporary = self.cache.with_suffix(".tmp")
        temporary.write_bytes(blob)
        temporary.replace(self.cache)

    async def refresh(self, unit_ids=()):
        if self.store.active_proposal():
            return False
        now = self.store.clock()
        if now - float(self.store.get("wiki_last_attempt") or 0) < 900:
            return False
        titles = []
        if now - float(self.checked.get(NAMES, 0)) >= 86400:
            titles.extend([NAMES, DATA])
        candidates = [u for u in unit_ids if u in self.catalog.units]
        if not candidates:
            units = sorted(self.catalog.units)
            candidates = units[self.cursor : self.cursor + 4]
            self.cursor = (self.cursor + 4) % max(1, len(units))
        for uid in list(dict.fromkeys(candidates))[:4]:
            unit = self.catalog.units[uid]
            # Wikitext module grammar separators are not accepted as article titles.
            if (
                "|" in unit.name
                or "#" in unit.name
                or any(ord(c) < 32 for c in unit.name)
            ):
                continue
            if now - float(self.checked.get(unit.name, 0)) >= 3600:
                titles.append(unit.name)
        if not titles:
            return False
        self.store.set("wiki_last_attempt", now)
        try:
            async with self.session_factory(
                timeout=aiohttp.ClientTimeout(total=25)
            ) as session:
                async with session.get(
                    API,
                    params={
                        "action": "query",
                        "prop": "revisions",
                        "rvprop": "ids|timestamp|content",
                        "rvslots": "main",
                        "format": "json",
                        "formatversion": "2",
                        "titles": "|".join(titles),
                    },
                    headers={
                        "User-Agent": "AnimeAdventuresCommunityBot/1.0 (revision-cached tier list)"
                    },
                    allow_redirects=False,
                ) as response:
                    if response.status != 200:
                        raise ValueError("Wiki unavailable")
                    blob = bytearray()
                    while chunk := await response.content.read(16384):
                        blob.extend(chunk)
                        if len(blob) > MAX_RESPONSE:
                            raise ValueError("Wiki response exceeds bound")
                    pages = json.loads(blob)["query"]["pages"]
            if not isinstance(pages, list) or len(pages) > 6:
                raise ValueError("Invalid wiki response")
            pages = sorted(pages, key=lambda p: p.get("title") != NAMES)
            sources = dict(self.evidence.sources)
            changed = False
            accepted = 0
            for page in pages:
                title = page.get("title")
                if (
                    title not in titles
                    or page.get("missing")
                    or not page.get("revisions")
                ):
                    continue
                revision = page["revisions"][0]
                rid = revision.get("revid")
                text = revision.get("slots", {}).get("main", {}).get("content")
                if (
                    type(rid) is not int
                    or rid <= 0
                    or not isinstance(text, str)
                    or not 20 <= len(text) <= 3_000_000
                ):
                    continue
                accepted += 1
                if title == NAMES:
                    entries = {}
                    for name, uid in re.findall(
                        r'^\s*\["([^"\n]+)"\]\s*=\s*\{\s*name\s*=\s*"([^"\n]+)"',
                        text,
                        re.M,
                    ):
                        entry = entries.setdefault(
                            uid, {"id": uid, "name": name, "aliases": []}
                        )
                        if name != entry["name"]:
                            entry["aliases"].append(name)
                    if not entries:
                        raise ValueError("Wiki identity module changed format")
                    self.catalog.merge_units(list(entries.values()))
                elif title == DATA:
                    starts = list(
                        re.finditer(r"^\t([A-Za-z0-9_]+)\s*=\s*\{", text, re.M)
                    )
                    if not starts:
                        raise ValueError("Wiki data module changed format")
                    for i, m in enumerate(starts):
                        uid = m.group(1)
                        if uid in self.catalog.units:
                            body = text[
                                m.start() : starts[i + 1].start()
                                if i + 1 < len(starts)
                                else len(text)
                            ].strip()
                            changed = (
                                self._source(sources, uid, "data", title, rid, body)
                                or changed
                            )
                else:
                    for uid, unit in self.catalog.units.items():
                        if unit.name == title:
                            changed = (
                                self._source(sources, uid, "article", title, rid, text)
                                or changed
                            )
                self.checked[title] = now
            if not accepted:
                raise ValueError("No wiki revision returned")
            if changed:
                self.evidence.replace(sources)
            self.status = "synced"
            self.store.set("wiki_last_success", now)
            self.save()
            return changed
        except (
            aiohttp.ClientError,
            TimeoutError,
            ValueError,
            KeyError,
            TypeError,
            OSError,
        ):
            self.status = "unavailable"
            return False

    def _source(self, sources, uid, suffix, title, revision, text):
        item = {
            "unit_id": uid,
            "title": title,
            "revision": revision,
            "url": WIKI + quote(title, safe=":()") + "?oldid=" + str(revision),
            "text": text,
            "sha256": hashlib.sha256(text.encode()).hexdigest(),
        }
        sid = uid + ":" + suffix
        if not self.valid_source(sid, item):
            return False
        old = sources.get(sid)
        if old and revision < old.get("revision", 0):
            return False
        if old == item:
            return False
        sources[sid] = item
        return True
