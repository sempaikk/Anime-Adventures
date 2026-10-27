"""Streaming Discord uploads to bounded disk storage; no arbitrary URL fetches."""

import hashlib
import os
import re
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

import aiohttp
import discord

MEDIA_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".avif",
    ".mp4",
    ".webm",
    ".mov",
    ".m4v",
    ".mp3",
    ".ogg",
    ".oga",
    ".wav",
    ".m4a",
    ".flac",
    ".pdf",
    ".txt",
}


CACHE_LIMIT = 256 * 1024 * 1024


def cdn_url(url):
    try:
        parsed = urlsplit(str(url))
        return (
            parsed.scheme == "https"
            and parsed.hostname
            in ("cdn.discordapp.com", "media.discordapp.net", "cdn.discordapp.net")
            and not parsed.username
            and not parsed.password
            and parsed.port in (None, 443)
            and parsed.path.startswith(
                (
                    "/attachments/",
                    "/ephemeral-attachments/",
                    "/stickers/",
                    "/avatars/",
                    "/embed/avatars/",
                    "/guilds/",
                )
            )
        )
    except ValueError:
        return False


def filename(value):
    value = str(value).replace("\\", "/").rsplit("/", 1)[-1]
    value = re.sub(r"[\x00-\x1f\x7f\u200b-\u200f\u202a-\u202e\u2066-\u2069]", "", value)
    if not value or Path(value).suffix.lower() not in MEDIA_EXTENSIONS:
        raise ValueError(
            'This file type cannot be shared in global chat. Use an image, video, audio, PDF or TXT file.'
        )
    suffix = Path(value).suffix
    stem = (
        value[: -len(suffix)]
        .encode("utf-16-le")[:280]
        .decode("utf-16-le", errors="ignore")
    )
    return (stem or "arquivo") + suffix


class GlobalMedia:
    def __init__(self, directory, session):
        self.root = Path(directory) / "global-media"
        self.root.mkdir(parents=True, exist_ok=True)
        self.session = session
        self.in_use = {}
        self.reserved = 0
        self.downloads = set()
        self.available_space = None

    def usage(self):
        return sum(p.stat().st_size for p in self.root.iterdir() if p.is_file())

    def release(self, assets):
        for asset in assets:
            digest = asset.get("digest")
            if digest in self.in_use:
                self.in_use[digest] -= 1
                if not self.in_use[digest]:
                    del self.in_use[digest]

    async def download(self, asset, limit):
        if not cdn_url(asset["url"]):
            raise ValueError('The file must be an attachment uploaded to Discord.')
        name = filename(asset["filename"])
        expected = int(asset.get("size") or 0)
        if expected > limit:
            return {**asset, "filename": name, "oversize": True}
        if expected < 0:
            raise ValueError('The file size is invalid.')
        reservation = expected or limit
        used = sum(
            p.stat().st_size
            for p in self.root.iterdir()
            if p.is_file() and p.name not in self.downloads
        )
        if used + self.reserved + reservation > CACHE_LIMIT:
            raise ValueError(
                'The temporary cache is full. Wait for cleanup before sharing another large file.'
            )
        free=await self.available_space() if self.available_space else shutil.disk_usage(self.root).free
        if free-self.reserved < max(expected, limit) + 16 * 1024 * 1024:
            raise ValueError(
                'There is not enough storage to share this file right now. The original message was preserved.'
            )
        temporary = None
        self.reserved += reservation
        try:
            session = await self.session()
            with tempfile.NamedTemporaryFile(
                dir=self.root, prefix=".download-", delete=False
            ) as stream:
                temporary = Path(stream.name)
                self.downloads.add(temporary.name)
                digest = hashlib.sha256()
                size = 0
                async with session.get(
                    asset["url"],
                    allow_redirects=False,
                    timeout=aiohttp.ClientTimeout(total=90),
                ) as response:
                    if response.status != 200:
                        raise ValueError(
                            'Discord did not provide the attachment. Please try sending it again.'
                        )
                    if (
                        response.content_length is not None
                        and response.content_length > limit
                    ):
                        return {**asset, "filename": name, "oversize": True}
                    async for chunk in response.content.iter_chunked(65536):
                        size += len(chunk)
                        if size > limit:
                            raise ValueError(
                                'The file exceeds the available sharing limit.'
                            )
                        if size > reservation:
                            raise ValueError(
                                'The file exceeds the available temporary storage.'
                            )
                        stream.write(chunk)
                        digest.update(chunk)
                if not size or (expected and expected != size):
                    raise ValueError(
                        'The attachment download was incomplete. The original was preserved.'
                    )
            target = self.root / digest.hexdigest()
            os.replace(temporary, target)
            self.in_use[digest.hexdigest()] = self.in_use.get(digest.hexdigest(), 0) + 1
            return {
                **asset,
                "filename": name,
                "size": size,
                "digest": digest.hexdigest(),
            }
        finally:
            self.reserved -= reservation
            if temporary and temporary.exists():
                temporary.unlink()
            if temporary:
                self.downloads.discard(temporary.name)

    def path(self, asset):
        digest = asset.get("digest", "")
        if not re.fullmatch("[a-f0-9]{64}", digest):
            raise ValueError('Attachment waiting to be prepared.')
        path = self.root / digest
        if (
            path.is_symlink()
            or not path.is_file()
            or path.stat().st_size != asset["size"]
        ):
            raise ValueError('The attachment needs to be prepared again.')
        return path

    def files(self, assets, limit):
        files = []
        omitted = []
        try:
            for asset in assets:
                if asset.get("oversize") or asset["size"] > limit:
                    omitted.append(asset["filename"])
                    continue
                files.append(
                    discord.File(
                        self.path(asset),
                        filename=asset["filename"],
                        spoiler=asset["filename"].startswith("SPOILER_"),
                    )
                )
            return files, omitted
        except BaseException:
            for file in files:
                file.close()
            raise

    def cleanup(self, active_digests):
        import time

        for path in self.root.iterdir():
            if (
                path.is_file()
                and path.name not in active_digests
                and path.name not in self.in_use
                and path.name not in self.downloads
                and time.time() - path.stat().st_mtime > 60
            ):
                path.unlink()
