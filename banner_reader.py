"""Isolated, read-only source listener. Secrets arrive over stdin, never argv/logs."""

from __future__ import annotations
import asyncio
from datetime import datetime, timezone
import importlib.metadata
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
    for item in message.attachments:
        mime = getattr(item, "content_type", "") or ""
        if mime != "image/gif" and (mime.startswith("image/") or str(item.filename).lower().endswith((".png", ".jpg", ".jpeg", ".webp"))):
            images.append(str(item.url))
    for embed in message.embeds:
        if getattr(embed.image, "url", None):
            images.append(str(getattr(embed.image, "proxy_url", None) or embed.image.url))
    images = list(dict.fromkeys(images))[:10]
    if not images:
        return None
    return {"event": "image", "channel_id": str(message.channel.id),
            "message_id": str(message.id), "created_at": (getattr(message, "edited_at", None) or message.created_at).timestamp(),
            "images": images}


def question_message(message, channel_id):
    if message.channel.id != channel_id:
        return None
    body = str(message.content or "")[:4000]
    body = re.sub(r"<[@#][!&]?\d+>|https?://\S+|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[removed]", body)
    body = re.sub(r"\+\d[\d ()-]{7,}\d|(?i:phone|telefone|whatsapp)\s*:?\s*\d[\d ()-]{7,}\d", "[removed]", body)
    body = re.sub(r"\b(?:gsk_[A-Za-z0-9_-]{16,}|mfa\.[A-Za-z0-9_-]{20,})", "[removed]", body)
    body = "".join(c for c in body if c == "\n" or (c.isprintable() and c not in "\u202e\u202d"))[:4000].strip()
    if not body:
        return None
    reference = getattr(message, "reference", None)
    reply_to = getattr(reference, "message_id", None) if getattr(reference, "channel_id", None) == channel_id else None
    return {"event": "question", "channel_id": str(channel_id), "message_id": str(message.id),
            "reply_to": str(reply_to) if reply_to else None, "body": body,
            "created_at": message.created_at.timestamp()}


async def listen(config):
    # This import runs exclusively in the dedicated virtual environment.
    import discord as account_discord

    sources = {int(value) for value in config["source_channel_ids"]}
    questions = int(config.get("questions_channel_id", 0))
    daily = int(config.get("daily_channel_id", 0))
    questions_enabled=config.get('questions_enabled',True)
    if not 1 <= len(sources) <= 3 or not config.get("token"):
        raise ValueError("Invalid reader configuration")

    class Reader(account_discord.Client):
        def publish_image(self, message):
            payload=image_message(message,sources-{questions})
            if payload and self.image_tracker.new(payload):
                emit(**payload)
            return bool(payload)

        async def scan_image(self, channel):
            recent = []
            async for message in channel.history(limit=50):
                age=time.time()-(getattr(message,'edited_at',None) or message.created_at).timestamp()
                if age>(26*3600 if channel.id==daily else 3900):break
                recent.append(message)
            # A newer image may already be seen while earlier images missed a
            # Gateway event or failed reception. Check the entire bounded page.
            for message in reversed(recent):
                self.publish_image(message)
            emit('ready',channel_id=str(channel.id))

        async def poll_images(self):
            while True:
                await asyncio.sleep(30)
                if not self.image_ready:continue
                for ident in sources-{questions}:
                    try:
                        channel=self.image_channels.get(ident)
                        if channel is None:
                            channel=self.get_channel(ident) or await self.fetch_channel(ident)
                            if not isinstance(channel,account_discord.TextChannel):raise ValueError('Unsupported source channel')
                            await channel.guild.subscribe(typing=True,threads=False,activities=False,member_updates=False)
                            self.image_channels[ident]=channel
                        await self.scan_image(channel)
                    except account_discord.CaptchaRequired:
                        emit('account_action_required');await self.close();return
                    except Exception as error:
                        emit('source_unavailable',channel_id=str(ident),reason=type(error).__name__)

        def publish_question(self,message,*,checkpoint=True):
            reference=getattr(message,'reference',None)
            original=getattr(reference,'resolved',None)
            if isinstance(original,account_discord.Message) and original.channel.id==questions:
                original_payload=question_message(original,questions)
                if original_payload:
                    emit(**original_payload)
            payload=question_message(message,questions)
            if payload:
                emit(**payload)
            if checkpoint:
                self.qa_cursor=max(self.qa_cursor,int(message.id))
                emit('question_checkpoint',channel_id=str(questions),message_id=str(self.qa_cursor))

        async def on_ready(self):
            unavailable=False
            self.qa_loading=True
            for ident in config['source_channel_ids']:
                if ident==questions and not questions_enabled:
                    continue
                try:
                    channel = self.get_channel(ident) or await self.fetch_channel(ident)
                    if not isinstance(channel, account_discord.TextChannel):
                        raise ValueError("Source must be a guild text channel")
                    # Large official guilds require an explicit subscription.
                    await channel.guild.subscribe(typing=True, threads=False,
                                                  activities=False, member_updates=False)
                    if ident == questions:
                        if self.qa_cursor:
                            upper=account_discord.Object(id=account_discord.utils.time_snowflake(datetime.now(timezone.utc),high=True))
                            async for message in channel.history(limit=None,after=account_discord.Object(id=self.qa_cursor),before=upper,oldest_first=True):
                                self.publish_question(message)
                        else:
                            messages=[message async for message in channel.history(limit=100)]
                            for message in reversed(messages):
                                self.publish_question(message)
                        pending,self.qa_pending=self.qa_pending,[]
                        for message in sorted(pending,key=lambda item:item.id):
                            self.publish_question(message)
                        self.qa_loading=False
                        continue
                    self.image_channels[ident]=channel
                    await self.scan_image(channel)
                except Exception as error:
                    unavailable=True
                    emit('source_unavailable',channel_id=str(ident),reason=type(error).__name__)
            self.image_ready=True
            if self.image_poll is None or self.image_poll.done():
                self.image_poll=asyncio.create_task(self.poll_images())
            # Preserve archived Q&A test protocol; production has image sources only.
            if questions in sources and questions_enabled:
                emit("source_unavailable" if unavailable else "ready")

        async def on_disconnect(self):
            self.qa_loading=True
            self.image_ready=False
            emit("connecting")

        async def on_message(self, message):
            if message.channel.id == questions:
                if not questions_enabled:
                    return
                if self.qa_loading:
                    if len(self.qa_pending)>=2000:
                        emit('source_unavailable')
                        await self.close()
                    else:
                        self.qa_pending.append(message)
                else:
                    self.publish_question(message)
                return
            self.publish_image(message)

        async def on_raw_message_edit(self, event):
            if event.channel_id not in sources:
                return
            if event.channel_id == questions and not questions_enabled:
                return
            try:
                channel = self.get_channel(event.channel_id) or await self.fetch_channel(event.channel_id)
                message = await channel.fetch_message(event.message_id)
                if event.channel_id==questions:
                    payload=question_message(message,questions)
                    if payload:emit(**payload)
                else:self.publish_image(message)
            except Exception as error:
                emit('source_unavailable',channel_id=str(event.channel_id),reason=type(error).__name__)

        async def on_raw_message_delete(self, event):
            if event.channel_id == questions:
                emit("question_delete", channel_id=str(questions), message_id=str(event.message_id))

        async def on_raw_bulk_message_delete(self, event):
            if event.channel_id == questions:
                for ident in event.message_ids:
                    emit("question_delete", channel_id=str(questions), message_id=str(ident))

    client = Reader(guild_subscriptions=False, chunk_guilds_at_startup=False, max_messages=None)
    client.qa_loading=True
    client.qa_pending=[]
    client.qa_cursor=int(config.get('question_after') or 0)
    client.image_tracker=ImageTracker()
    client.image_channels={}
    client.image_ready=False
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
             f"discord.py-self=={READER_VERSION}"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=240, check=True,
        )
    os.execv(str(executable), [str(executable), "-I", str(Path(__file__).resolve()), "--reader"])


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    try:
        if sys.argv[1:] == ["--check"]:
            raise SystemExit(0 if importlib.metadata.version("discord.py-self") == READER_VERSION else 1)
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
