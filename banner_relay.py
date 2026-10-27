"""Image-only banner destinations, durable receipts and an isolated account reader."""

from __future__ import annotations
import asyncio
import hashlib
import io
import json
import inspect
import logging
import math
import os
from pathlib import Path
import sys
import warnings
from urllib.parse import urlsplit

import aiohttp
import discord
from discord.http import handle_message_parameters
from PIL import Image
from game_sources import BANNER_CHANNEL_ID, DAILY_CHANNEL_ID, QUESTIONS_CHANNEL_ID, SOURCE_CHANNELS, IMAGE_SOURCE_CHANNELS, reader_token

SOURCE_CHANNEL_IDS = (BANNER_CHANNEL_ID,)
MAX_IMAGE = 8 * 1024 * 1024
MAX_BATCH = 16 * 1024 * 1024
MAX_CACHE = 32 * 1024 * 1024
MAX_AGE = 3900
log = logging.getLogger("adventures.banners")


def image_url(value):
    if not isinstance(value, str) or len(value) > 4096:
        return False
    try:
        url = urlsplit(value)
        return (url.scheme == "https" and not url.username and not url.password
                and url.port in (None, 443)
                and ((url.hostname in {"cdn.discordapp.com", "media.discordapp.net"}
                      and url.path.startswith("/attachments/"))
                     or (url.hostname in {"images-ext-1.discordapp.net", "images-ext-2.discordapp.net"}
                         and url.path.startswith("/external/"))))
    except ValueError:
        return False


def image_extension(blob):
    if not blob or len(blob) > MAX_IMAGE:
        raise ValueError("Image size outside limits")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(blob)) as image:
                extension = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp"}.get(image.format)
                if not extension or getattr(image, "is_animated", False) or image.width * image.height > 20_000_000 or max(image.size) > 8192:
                    raise ValueError("Unsupported image")
                image.verify()
                return extension
    except (OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise ValueError("Invalid image") from error


def require_banner_admin(interaction):
    permissions = interaction.permissions
    if not interaction.guild_id or not (permissions.manage_guild or getattr(permissions, "administrator", False)):
        raise ValueError("You need Manage Server or Administrator to configure image feeds.")


class BannerRelay:
    def __init__(self, bot, *, kind="banner"):
        if kind not in {"banner", "daily"}:
            raise ValueError("Unknown image feed")
        self.bot = bot
        self.kind = kind
        self.source_ids = (DAILY_CHANNEL_ID,) if kind == "daily" else SOURCE_CHANNEL_IDS
        self.max_age = 26 * 3600 if kind == "daily" else MAX_AGE
        self.db = bot.store.connection
        self.clock = bot.store.clock
        self.task = None
        self.process = None
        self.session = None
        self.status = "not_configured"
        self.accept_lock = asyncio.Lock()
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS banner_targets(
            guild_id TEXT PRIMARY KEY, channel_id TEXT NOT NULL, enabled_at REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS banner_assets(
            digest TEXT PRIMARY KEY, extension TEXT NOT NULL, data BLOB NOT NULL);
          CREATE TABLE IF NOT EXISTS banner_events(
            id TEXT PRIMARY KEY, source_message TEXT NOT NULL, created_at REAL NOT NULL,
            images TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS banner_jobs(
            event_id TEXT NOT NULL, guild_id TEXT NOT NULL, channel_id TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'pending', attempted_at REAL NOT NULL DEFAULT 0,
            message_id TEXT, PRIMARY KEY(event_id,channel_id));
          CREATE INDEX IF NOT EXISTS banner_pending ON banner_jobs(state,attempted_at);
        """.replace("banner_", self.kind + "_"))
        if kind == 'banner':
            from banner_images import BannerImages
            from banner_votes import BannerVotes

            self.images = BannerImages(self)
            self.votes = BannerVotes(self)

    def query(self, statement, parameters=()):
        return self.db.execute(statement.replace("banner_", self.kind + "_"), parameters)

    def target(self, guild_id):
        return self.query("SELECT * FROM banner_targets WHERE guild_id=?", (str(guild_id),)).fetchone()

    def configure(self, guild_id, channel_id):
        guild_id, channel_id = str(guild_id), str(channel_id)
        if int(channel_id) in SOURCE_CHANNELS:
            raise ValueError("Choose a destination channel different from the source channel.")
        with self.db:
            self.query("DELETE FROM banner_jobs WHERE guild_id=? AND channel_id<>? AND state NOT IN ('sent','sending','uncertain')", (guild_id, channel_id))
            self.query("INSERT INTO banner_targets VALUES(?,?,?) ON CONFLICT(guild_id) DO UPDATE SET channel_id=excluded.channel_id,enabled_at=excluded.enabled_at",
                            (guild_id, channel_id, self.clock()))
            latest = self.query("SELECT id FROM banner_events WHERE created_at>? ORDER BY created_at DESC,rowid DESC LIMIT 1", (self.clock() - self.max_age,)).fetchone()
            if latest:
                self.query("INSERT OR IGNORE INTO banner_jobs(event_id,guild_id,channel_id) VALUES(?,?,?)", (latest[0], guild_id, channel_id))
                self.query("UPDATE banner_jobs SET state='pending' WHERE event_id=? AND channel_id=? AND state='unavailable'", (latest[0], channel_id))
        if self.kind == 'banner':
            self.images.resume(guild_id, channel_id)

    def disable(self, guild_id):
        with self.db:
            self.query("DELETE FROM banner_targets WHERE guild_id=?", (str(guild_id),))
            self.query("DELETE FROM banner_jobs WHERE guild_id=? AND state NOT IN ('sent','sending','uncertain')", (str(guild_id),))

    def description(self, guild_id=None):
        current = self.status
        status = {
            "not_configured": "The bot owner has not configured the source reader yet.",
            "installing": "The source reader is completing its initial setup.",
            "connecting": "The reader is connecting to the source.",
            "ready": "Reader connected. New static images will be forwarded automatically.",
            "source_unavailable": "The reader could not confirm source access. The bot owner needs to check the configured account.",
            "login_failed": "Reader authentication failed. The bot owner needs to check the hosting secret.",
            "account_action_required": "Discord requested account verification. Reading has stopped; the owner needs to check the account in the official app.",
            "reader_failed": "The reader is unavailable. The bot owner needs to check the installation and restart the bot.",
        }.get(current, "The reader is reconnecting to the source.")
        if current=='ready' and not self.query('SELECT 1 FROM banner_events WHERE created_at>? LIMIT 1',(self.clock()-self.max_age,)).fetchone():
            status+='\nNo recent image is cached yet. The source is checked automatically every 30 seconds.'
        if guild_id is not None:
            job = self.query("SELECT j.state FROM banner_jobs j JOIN banner_targets t ON t.guild_id=j.guild_id AND t.channel_id=j.channel_id WHERE j.guild_id=? ORDER BY j.rowid DESC LIMIT 1", (str(guild_id),)).fetchone()
            if job:
                status += {
                    "unavailable": "\nCheck the bot's channel access and permissions, then run the setup command again.",
                    "oversize": "\nAn image exceeded this server's attachment size limit.",
                    "uncertain": "\nA delivery is awaiting confirmation from Discord. The bot is checking the result to avoid duplicates.",
                }.get(job[0], "")
            if self.kind == 'banner' and self.target(guild_id):
                status += '\n**W/M/L reactions:** ' + self.votes.description(guild_id)
            if publishing := self.bot.feed_publications.description(self.kind, guild_id):
                status += '\n**Announcement publishing:** ' + publishing
        return status

    def private_status(self, guild_id):
        title = "Daily challenges" if self.kind == "daily" else "Banners"
        target = self.target(guild_id)
        if not target:
            return f"**{title}:** no destination configured in this server."
        text = f"**{title}:** <#{target['channel_id']}>. {self.description(guild_id)}"
        confirmed = self.query(
            "SELECT attempted_at FROM banner_jobs WHERE guild_id=? AND channel_id=? AND state='sent' ORDER BY attempted_at DESC LIMIT 1",
            (str(guild_id), target['channel_id']),
        ).fetchone()
        if confirmed:
            text += f"\nLast confirmed delivery: <t:{int(confirmed[0])}:R>."
        else:
            text += "\nNo confirmed delivery remains in the recent receipt window."
        return text

    def start(self):
        if reader_token() and not self.task:
            self.task = asyncio.create_task(self.supervise(), name="banner-reader")

    async def supervise(self):
        await self.bot.wait_until_ready()
        delay = 5
        while True:
            self.status = "connecting"
            self.bot.daily.status = "connecting"
            try:
                environment = {key: value for key, value in os.environ.items()
                               if key in {"PATH", "SYSTEMROOT", "TMPDIR", "TMP", "TEMP", "LANG", "LC_ALL", "SSL_CERT_FILE", "SSL_CERT_DIR", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"}}
                self.process = await asyncio.create_subprocess_exec(
                    sys.executable, "-I", str(Path(__file__).with_name("banner_reader.py")),
                    "--bootstrap", str((self.bot.directory / ".banner-reader-venv").resolve()),
                    env=environment, stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                    limit=65536,
                )
                config = {"token": reader_token(), "source_channel_ids": SOURCE_CHANNELS,
                          "questions_channel_id": QUESTIONS_CHANNEL_ID, "daily_channel_id": DAILY_CHANNEL_ID,
                          "question_after": self.bot.knowledge.get_meta('source-cursor'),
                          "questions_enabled": not self.bot.knowledge.paused}
                if getattr(self.bot.knowledge,'disabled',False):
                    config.update(source_channel_ids=IMAGE_SOURCE_CHANNELS,questions_channel_id=0,
                                  question_after=None,questions_enabled=False)
                self.process.stdin.write(json.dumps(config).encode() + b"\n")
                await self.process.stdin.drain()
                self.process.stdin.close()
                count=0
                async for line in self.process.stdout:
                    try:
                        event = json.loads(line)
                        if event.get("event") == "image":
                            channel_id = str(event.get("channel_id"))
                            if channel_id == str(BANNER_CHANNEL_ID):
                                await self.accept(event)
                            elif channel_id == str(DAILY_CHANNEL_ID):
                                await self.bot.daily.accept(event)
                        elif event.get("event") in {"question", "question_delete"}:
                            result = self.bot.knowledge.ingest(event)
                            if inspect.isawaitable(result):
                                await result
                        elif event.get('event')=='question_checkpoint':
                            result = self.bot.knowledge.checkpoint(event)
                            if inspect.isawaitable(result):
                                await result
                        elif event.get("event") in {"installing", "connecting", "ready", "source_unavailable", "login_failed", "account_action_required", "reader_failed"}:
                            source = str(event.get('channel_id',''))
                            feed = self if source == str(BANNER_CHANNEL_ID) else self.bot.daily if source == str(DAILY_CHANNEL_ID) else None
                            if feed:
                                changed=feed.status!=event['event']
                                feed.status=event['event']
                                if changed:log.info('Image source %s: %s (%s).',feed.kind,event['event'],event.get('reason','confirmed'))
                            elif not source:
                                self.status = event["event"]
                                self.bot.daily.status = self.status
                            self.bot.knowledge.reader_status = event['event']
                            if event['event'] == 'ready':
                                delay = 5
                    except (ValueError, TypeError, KeyError, aiohttp.ClientError, asyncio.TimeoutError):
                        log.warning("Uma imagem de banner não pôde ser recebida; detalhes privados omitidos.")
                    count+=1
                    if count%25==0:
                        await asyncio.sleep(0)
                await self.process.wait()
                if self.status in {"login_failed", "account_action_required"}:
                    return
            except asyncio.CancelledError:
                raise
            except Exception as error:
                log.warning("Leitor de banners indisponível: %s", type(error).__name__)
            finally:
                await self.stop_process()
            self.status = "reader_failed"
            self.bot.daily.status = "reader_failed"
            await asyncio.sleep(delay)
            delay = min(delay * 2, 300)

    async def stop_process(self):
        process, self.process = self.process, None
        if process and process.returncode is None:
            try:
                process.terminate()
                await asyncio.wait_for(process.wait(), 5)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
            except ProcessLookupError:
                pass

    async def download(self, url, limit):
        if not image_url(url):
            raise ValueError("Only Discord image attachments/proxies are accepted")
        if self.session is None:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        async with self.session.get(url, allow_redirects=False) as response:
            if response.status != 200 or (response.content_length is not None and response.content_length > limit):
                raise ValueError("Image unavailable")
            blob = bytearray()
            async for chunk in response.content.iter_chunked(65536):
                blob.extend(chunk)
                if len(blob) > limit:
                    raise ValueError("Image outside limits")
        return bytes(blob)

    async def accept(self, payload):
        # Check scope, age and bounded shape before any download or storage.
        if str(payload.get("channel_id")) not in {str(value) for value in self.source_ids}:
            return False
        created = float(payload["created_at"])
        if not math.isfinite(created) or not self.clock() - self.max_age < created <= self.clock() + 300:
            return False
        message_id = str(payload["message_id"])
        urls = payload["images"]
        if not message_id.isdecimal() or len(message_id) > 22 or not isinstance(urls, list) or not 1 <= len(urls) <= 10:
            return False
        if not all(image_url(url) for url in urls):
            return False
        if self.bot.health.storage_level == "critical":
            return False
        async with self.accept_lock:
            self.prune()
            images, blobs, size = [], {}, 0
            for url in dict.fromkeys(urls):
                blob = await self.download(url, min(MAX_IMAGE, MAX_BATCH - size))
                size += len(blob)
                extension = await asyncio.to_thread(image_extension, blob)
                digest = hashlib.sha256(blob).hexdigest()
                if digest not in blobs:
                    images.append(digest)
                    blobs[digest] = (extension, blob)
            ident = hashlib.sha256((message_id + ":" + ":".join(images)).encode()).hexdigest()
            if self.query("SELECT 1 FROM banner_events WHERE id=?", (ident,)).fetchone():
                return False
            used = self.query("SELECT COALESCE(SUM(length(data)),0) FROM banner_assets").fetchone()[0]
            new = sum(len(blob) for digest, (_, blob) in blobs.items() if not self.query("SELECT 1 FROM banner_assets WHERE digest=?", (digest,)).fetchone())
            if used + new > MAX_CACHE or self.query("SELECT COUNT(*) FROM banner_events").fetchone()[0] >= 64:
                raise ValueError("Banner cache full")
            with self.db:
                for digest, (extension, blob) in blobs.items():
                    self.query("INSERT OR IGNORE INTO banner_assets VALUES(?,?,?)", (digest, extension, blob))
                self.query("INSERT INTO banner_events VALUES(?,?,?,?)", (ident, message_id, created, json.dumps(images)))
                self.query("UPDATE banner_jobs SET state='superseded' WHERE state='pending' AND event_id IN (SELECT id FROM banner_events WHERE source_message=? AND id<>?)", (message_id, ident))
                self.query("INSERT OR IGNORE INTO banner_jobs(event_id,guild_id,channel_id) SELECT ?,guild_id,channel_id FROM banner_targets", (ident,))
            return True

    def prune(self):
        with self.db:
            self.query("DELETE FROM banner_jobs WHERE event_id IN (SELECT id FROM banner_events WHERE created_at<=?)", (self.clock() - self.max_age,))
            self.query("DELETE FROM banner_events WHERE created_at<=?", (self.clock() - self.max_age,))
            used = {digest for row in self.query("SELECT images FROM banner_events") for digest in json.loads(row[0])}
            for row in self.query("SELECT digest FROM banner_assets").fetchall():
                if row[0] not in used:
                    self.query("DELETE FROM banner_assets WHERE digest=?", (row[0],))
        if self.kind == 'banner':
            self.images.prune()

    def assets(self, event_id):
        event = self.query("SELECT * FROM banner_events WHERE id=?", (event_id,)).fetchone()
        if not event or event["created_at"] <= self.clock() - self.max_age:
            return []
        return [self.query("SELECT * FROM banner_assets WHERE digest=?", (digest,)).fetchone() for digest in json.loads(event["images"])]

    def state(self, job, state, message_id=None):
        with self.db:
            self.query("UPDATE banner_jobs SET state=?,attempted_at=?,message_id=? WHERE event_id=? AND channel_id=?",
                            (state, self.clock(), str(message_id) if message_id else None, job["event_id"], job["channel_id"]))

    @staticmethod
    def nonce(job):
        return str(int(hashlib.sha256((job["event_id"] + job["channel_id"]).encode()).hexdigest()[:15], 16))

    async def deliver(self, job):
        async with self.bot.guild_lock(int(job["guild_id"])):
            target = self.target(job["guild_id"])
            if not target or target["channel_id"] != job["channel_id"]:
                return
            channel = self.bot.get_channel(int(job["channel_id"]))
            if not isinstance(channel, discord.TextChannel):
                self.state(job, "unavailable")
                return
            permissions = channel.permissions_for(channel.guild.me)
            if not all(getattr(permissions, name, False) for name in ("view_channel", "send_messages", "attach_files", "read_message_history")):
                self.state(job, "unavailable")
                return
            assets = self.assets(job["event_id"])
            if not assets or any(asset is None for asset in assets):
                return
            if self.kind == 'banner' and (job['layout'] == 'images' or job['state'] == 'pending'):
                await self.images.deliver(job, channel, assets)
                return
            names = [f"banner-{job['event_id'][:16]}-{index}.{asset['extension']}" for index, asset in enumerate(assets)]
            if job["state"] in {"sending", "uncertain"}:
                if self.clock() - job["attempted_at"] < 30:
                    return
                # Uncertain sends are reconciled, never blindly sent again.
                async for message in channel.history(limit=50):
                    if message.author.id == self.bot.user.id and (str(message.nonce) == self.nonce(job) or [a.filename for a in message.attachments] == names):
                        self.state(job, "sent", message.id)
                        return
                self.state(job, "uncertain")
                return
            limit = min(MAX_IMAGE, channel.guild.filesize_limit)
            if any(len(asset["data"]) > limit for asset in assets):
                self.state(job, "oversize")
                return
            files = [discord.File(io.BytesIO(asset["data"]), filename=name) for asset, name in zip(assets, names)]
            self.state(job, "sending")
            try:
                with handle_message_parameters(files=files, allowed_mentions=discord.AllowedMentions.none()) as params:
                    for part in params.multipart:
                        if part["name"] == "payload_json":
                            payload = json.loads(part["value"])
                            payload.update(nonce=self.nonce(job), enforce_nonce=True)
                            part["value"] = json.dumps(payload)
                    response = await self.bot.http.send_message(channel.id, params=params)
                self.state(job, "sent", response["id"])
            except (discord.Forbidden, discord.NotFound):
                self.state(job, "unavailable")
            except Exception:
                self.state(job, "uncertain")
                log.warning("Confirmação de envio de banner pendente; sem reenvio automático.")
            finally:
                for file in files:
                    file.close()

    async def cycle(self):
        self.prune()
        if self.bot.health.storage_level == "critical":
            return
        jobs = self.query("SELECT j.* FROM banner_jobs j JOIN banner_targets t ON t.guild_id=j.guild_id AND t.channel_id=j.channel_id WHERE j.state IN ('pending','sending','uncertain') ORDER BY j.attempted_at LIMIT 8").fetchall()
        for job in jobs:
            try:
                await self.deliver(job)
            except (discord.HTTPException, aiohttp.ClientError, asyncio.TimeoutError):
                log.warning("Conferência de um destino de banners adiada.")

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None
        await self.stop_process()
        if self.session:
            await self.session.close()
            self.session = None


class BannerControls(discord.ui.View):
    def __init__(self, bot, interaction, *, kind="banner"):
        super().__init__(timeout=180)
        self.bot, self.actor, self.guild, self.channel = bot, interaction.user.id, interaction.guild_id, interaction.channel_id
        self.feed = bot.daily if kind == "daily" else bot.banners

    async def interaction_check(self, interaction):
        from tier_views import reply
        if (interaction.user.id, interaction.guild_id) != (self.actor, self.guild):
            await reply(interaction, "Open the setup command to manage your own server's image feed.")
            return False
        try:
            require_banner_admin(interaction)
        except ValueError as error:
            await reply(interaction, str(error))
            return False
        return True

    @discord.ui.button(label="Stop receiving", style=discord.ButtonStyle.danger)
    async def disable(self, interaction, _button):
        from tier_views import reply
        require_banner_admin(interaction)
        async with self.bot.guild_lock(self.guild):
            target = self.feed.target(self.guild)
            if not target or target["channel_id"] != str(self.channel):
                await reply(interaction, "The configuration changed. Open the setup command in the desired channel to check it.")
                return
            self.feed.disable(self.guild)
        await reply(interaction, "This image feed has been disabled in this server.")
        self.stop()

    async def on_error(self, interaction, error, item):
        from tier_views import reply
        await reply(interaction, "The change could not be confirmed. Open the setup command to check it.")
