"""Isolated, read-only source listener. Secrets arrive over stdin, never argv/logs."""

from __future__ import annotations
import asyncio
from datetime import datetime, timezone
import importlib.metadata
import hashlib
import json
import logging
import os
import re
from pathlib import Path
import subprocess
import sys
import time
import venv
from collections import OrderedDict
from urllib.parse import urlsplit

READER_VERSION = "2.1.0"


def dependencies_match():
    try:
        for line in Path(__file__).with_name('requirements-reader.txt').read_text().splitlines():
            if line.strip() and not line.startswith('#'):
                name,version=line.strip().split('==')
                if importlib.metadata.version(name)!=version:
                    return False
        return importlib.metadata.version('discord.py-self')==READER_VERSION
    except (OSError,ValueError,importlib.metadata.PackageNotFoundError):
        return False


def image_identity(payload):
    """Stable source identity, excluding expiring CDN signatures."""
    paths = tuple((urlsplit(url).hostname, urlsplit(url).path) for url in payload['images'])
    return str(payload['channel_id']), str(payload['message_id']), float(payload['created_at']), paths


class ImageTracker:
    """Suppress bursts, but retry reception until the parent has persisted it."""
    def __init__(self):
        self.seen = OrderedDict()
        self.clock = time.monotonic

    def new(self, payload):
        key, now = image_identity(payload), self.clock()
        if key in self.seen and now - self.seen[key] < 60:
            self.seen.move_to_end(key)
            return False
        self.seen[key] = now
        self.seen.move_to_end(key)
        while len(self.seen)>256:self.seen.popitem(last=False)
        return True


def emit(event, **values):
    print(json.dumps({"event": event, **values}, separators=(",", ":")), flush=True)


def image_message(message, sources):
    """Do not serialize message text, authors, mentions, DMs or other channels."""
    if message.channel.id not in sources:
        return None
    images = []
    # Discord puts forwarded attachments/embeds inside MessageSnapshot objects,
    # in both pinned SDKs. Inspect only the inline snapshots, never fetch the
    # referenced channel/message or serialize its text and author information.
    parts = [message, *(getattr(message, "message_snapshots", None) or ())[:10]]
    for part in parts:
        for item in part.attachments:
            mime = getattr(item, "content_type", "") or ""
            if mime != "image/gif" and (mime.startswith("image/") or str(item.filename).lower().endswith((".png", ".jpg", ".jpeg", ".webp"))):
                images.append(str(item.url))
        for embed in part.embeds:
            if getattr(embed.image, "url", None):
                images.append(str(getattr(embed.image, "proxy_url", None) or embed.image.url))
    images = list(dict.fromkeys(images))[:10]
    if not images:
        return None
    # Identity and age belong to the post in the configured source channel,
    # rather than the original message preserved in a forward's snapshot.
    return {"event": "image", "channel_id": str(message.channel.id),
            "message_id": str(message.id), "created_at": (getattr(message, "edited_at", None) or message.created_at).timestamp(),
            "published_at": message.created_at.timestamp(),
            "images": images}


async def listen(config):
    # This import runs exclusively in the dedicated virtual environment.
    import discord as account_discord

    sources = {int(value) for value in config["source_channel_ids"]}
    daily = int(config.get("daily_channel_id", 0))
    if not 1 <= len(sources) <= 2 or not config.get("token"):
        raise ValueError("Invalid reader configuration")

    class Reader(account_discord.Client):
        def publish_image(self, message):
            payload=image_message(message,sources)
            if payload and self.image_tracker.new(payload):
                emit(**payload)
            return bool(payload)

        async def scan_image(self, channel):
            recent = []
            async for message in channel.history(limit=50):
                age=time.time()-(getattr(message,'edited_at',None) or message.created_at).timestamp()
                if age>(26*3600 if channel.id==daily else 3900):continue
                recent.append(message)
            # A newer image may already be seen while earlier images missed a
            # Gateway event or failed reception. Check the entire bounded page.
            if channel.id == daily:
                # The 26-hour cache window can contain both yesterday and today.
                # Only the newest daily image is a recovery candidate.
                for message in recent:
                    if self.publish_image(message):
                        break
            else:
                for message in reversed(recent):
                    self.publish_image(message)
            emit('ready',channel_id=str(channel.id))

        async def poll_images(self):
            while True:
                await asyncio.sleep(30)
                emit('heartbeat')
                # History uses authenticated HTTP and can still work while the
                # Gateway reconnects. DISCONNECT may be followed by RESUMED,
                # without another READY; it must not latch polling off forever.
                await asyncio.gather(*(self.poll_source(ident) for ident in sources))

        async def poll_source(self, ident):
            try:
                async def poll():
                    channel=self.image_channels.get(ident)
                    if channel is None:
                        channel=self.get_channel(ident) or await self.fetch_channel(ident)
                        if not isinstance(channel,account_discord.TextChannel):raise ValueError('Unsupported source channel')
                        await channel.guild.subscribe(typing=True,threads=False,activities=False,member_updates=False)
                        self.image_channels[ident]=channel
                    await self.scan_image(channel)
                await asyncio.wait_for(poll(),25)
            except account_discord.CaptchaRequired:
                emit('account_action_required');await self.close()
            except Exception as error:
                emit('source_unavailable',channel_id=str(ident),reason=type(error).__name__)

        async def on_ready(self):
            await asyncio.gather(*(self.poll_source(ident) for ident in config['source_channel_ids']))
            if self.image_poll is None or self.image_poll.done():
                self.image_poll=asyncio.create_task(self.poll_images())

        async def on_resumed(self):
            # Recover messages missed during the disconnect immediately, using
            # the same tracker and existing poller to avoid duplicate delivery.
            await self.on_ready()

        async def on_disconnect(self):
            emit("connecting")

        async def on_message(self, message):
            self.publish_image(message)

        async def on_raw_message_edit(self, event):
            if event.channel_id not in sources:
                return
            try:
                channel = self.get_channel(event.channel_id) or await self.fetch_channel(event.channel_id)
                message = await channel.fetch_message(event.message_id)
                self.publish_image(message)
            except Exception as error:
                emit('source_unavailable',channel_id=str(event.channel_id),reason=type(error).__name__)

        async def on_raw_message_delete(self, event):
            if event.channel_id in sources:
                emit('source_retracted', channel_id=str(event.channel_id), message_id=str(event.message_id))

    client = Reader(guild_subscriptions=False, chunk_guilds_at_startup=False, max_messages=None)
    client.image_tracker=ImageTracker()
    client.image_channels={}
    client.image_poll=None
    try:
        emit("connecting")
        await client.start(config["token"])
    except account_discord.CaptchaRequired:
        emit("account_action_required")
        return 2
    except account_discord.LoginFailure:
        emit("login_failed")
        return 2
    finally:
        if client.image_poll:
            client.image_poll.cancel()
            await asyncio.gather(client.image_poll,return_exceptions=True)
        await client.close()
    return 0


def bootstrap(directory):
    directory = Path(directory).resolve()
    executable = directory / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    installed = executable.exists() and subprocess.run(
        [str(executable), "-I", __file__, "--check"], stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode == 0
    if not installed:
        emit("installing")
        venv.EnvBuilder(with_pip=True).create(directory)
        subprocess.run(
            [str(executable), "-m", "pip", "install", "--disable-pip-version-check",
             "--no-input", "--no-cache-dir", "--timeout", "30", "--retries", "1",
             '-r', str(Path(__file__).with_name('requirements-reader.txt'))],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=240, check=True,
        )
    (directory/'.dependencies.sha256').write_text(hashlib.sha256(Path(__file__).with_name('requirements-reader.txt').read_bytes()).hexdigest())
    os.execv(str(executable), [str(executable), "-I", str(Path(__file__).resolve()), "--reader"])


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    try:
        if sys.argv[1:] == ["--check"]:
            raise SystemExit(0 if dependencies_match() else 1)
        if len(sys.argv) == 3 and sys.argv[1] == "--bootstrap":
            bootstrap(sys.argv[2])
        elif sys.argv[1:] == ["--reader"]:
            config = json.loads(sys.stdin.buffer.readline(8192))
            raise SystemExit(asyncio.run(listen(config)))
        else:
            raise SystemExit(1)
    except Exception:
        emit("reader_failed")
        raise SystemExit(1)
