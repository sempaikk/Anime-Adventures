"""Import exact-name wiki portraits from an audited allimages inventory.

No fuzzy filename matching, generated pictures, placeholders or live-runtime downloads.
Use --inventory /path/to/all_wiki_images.json to rebuild the source manifest.
"""

import argparse
import hashlib
import io
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def key(s):
    return re.sub(r"[\s_]+", "", s.casefold())


def sync(inventory=None):
    catalog = json.loads((ROOT / "data/community_catalog.json").read_text())
    target = ROOT / "data/community_portraits.json"
    if inventory:
        images = json.loads(Path(inventory).read_text())["images"]
        by_name = {}
        for im in images:
            if (
                im.get("mime") in ("image/png", "image/webp", "image/gif")
                and min(im.get("width", 0), im.get("height", 0)) >= 90
            ):
                by_name.setdefault(key(Path(im["name"]).stem), []).append(im)
        assets = {}
        for unit in catalog["units"]:
            matches = []
            # Only the exact current in-game form; anime aliases may refer to a different form.
            for name in [unit["name"], unit["name"] + " (Pose)"]:
                candidates = by_name.get(key(name), [])
                if candidates:
                    # Several encodings of the same exact title: PNG first, then WebP/GIF.
                    matches = sorted(
                        candidates,
                        key=lambda r: (
                            {"image/png": 0, "image/webp": 1, "image/gif": 2}[
                                r["mime"]
                            ],
                            r["name"],
                        ),
                    )[:1]
                    break
            if len(matches) == 1:
                im = matches[0]
                assets[unit["id"]] = {
                    "name": unit["name"],
                    "source_url": im["url"],
                    "source_page": im["descriptionurl"],
                    "path": "assets/community/"
                    + hashlib.sha256(unit["id"].encode()).hexdigest()[:20]
                    + ".png",
                }
        manifest = {
            "schema": 1,
            "source": "Anime Adventures wiki allimages inventory",
            "assets": assets,
            "missing": [u["id"] for u in catalog["units"] if u["id"] not in assets],
        }
    else:
        manifest = json.loads(target.read_text())

    def download(pair):
        uid, item = pair
        path = ROOT / item["path"]
        parsed = urlparse(item["source_url"])
        if (
            parsed.scheme != "https"
            or parsed.hostname != "static.wikia.nocookie.net"
            or not parsed.path.startswith("/animeadventures/")
        ):
            return uid, "invalid-source"
        if path.exists():
            return uid, None
        try:
            req = Request(
                item["source_url"],
                headers={"User-Agent": "AnimeAdventuresCommunityBot/1.0"},
            )
            with urlopen(req, timeout=25) as response:
                blob = response.read(8 * 1024 * 1024 + 1)
            if len(blob) > 8 * 1024 * 1024:
                raise ValueError("Image exceeds bound")
            with Image.open(io.BytesIO(blob)) as im:
                if min(im.size) < 90 or max(im.size) > 4096:
                    raise ValueError("Image dimensions outside bounds")
                # Technical thumbnail of the original art, retaining color and transparency.
                im = im.convert("RGBA")
                im.thumbnail((144, 144), Image.Resampling.LANCZOS)
                im.save(path, optimize=True)
            return uid, None
        except Exception as exc:
            return uid, type(exc).__name__

    with ThreadPoolExecutor(max_workers=4) as pool:
        failures = dict(
            (u, error)
            for u, error in pool.map(download, manifest["assets"].items())
            if error
        )
    # These source files were visually checked: they show the wiki's generic cyan dummy.
    rejected_prefixes = (
        "Blaze Frost",
        "Explosion Hero",
        "Falcon",
        "Flame Hero",
        "Gravity Hero",
        "Joykid (Bounce)",
        "Joykid (Mode IV)",
        "Lunar Hare",
        "Nightmare Joykid",
        "Prime Force",
        "Restructure",
        "Scorch",
        "Verdant Hero",
        "Windspire",
    )
    rejected = {
        **manifest.get("rejected_placeholders", {}),
        **{
            uid: item
            for uid, item in manifest["assets"].items()
            if item["name"].startswith(rejected_prefixes)
            and item["path"].startswith("assets/community/")
        },
    }
    manifest["rejected_placeholders"] = rejected
    for uid, item in rejected.items():
        current = manifest["assets"].get(uid)
        if current and current["source_url"] == item["source_url"]:
            manifest["assets"].pop(uid)
            (ROOT / item["path"]).unlink(missing_ok=True)
            if uid not in manifest["missing"]:
                manifest["missing"].append(uid)
    # Reuse only portraits already reviewed against the exact unit ID; never a different form.
    approved = json.loads((ROOT / "data/media.json").read_text())
    for uid, asset_id in approved["units"].items():
        item = approved["assets"][asset_id]
        if (
            uid not in manifest["assets"]
            and item.get("width", 0) >= 90
            and item.get("height", 0) >= 90
        ):
            manifest["assets"][uid] = {
                "name": next(u["name"] for u in catalog["units"] if u["id"] == uid),
                "source_url": item["source_url"],
                "source_page": item["source_page"],
                "path": item["path"],
            }
            if uid in manifest["missing"]:
                manifest["missing"].remove(uid)
    manifest["failures"] = failures
    for uid in failures:
        manifest["assets"].pop(uid, None)
        if uid not in manifest["missing"]:
            manifest["missing"].append(uid)
    used = {str((ROOT / a["path"]).resolve()) for a in manifest["assets"].values()}
    for unused in (ROOT / "assets/community").glob("*.png"):
        if str(unused.resolve()) not in used:
            unused.unlink()
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "portraits": len(manifest["assets"]),
                "missing": len(manifest["missing"]),
                "download_failures": failures,
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory")
    args = parser.parse_args()
    sync(args.inventory)
