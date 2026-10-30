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
from banner_reader import image_identity
from game_sources import BANNER_CHANNEL_ID, DAILY_CHANNEL_ID, SOURCE_CHANNELS, IMAGE_SOURCE_CHANNELS, reader_token

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
            with Image.open(io.BytesIO(blob)) as image:
                image.load()
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
        self.receiver = None
        self.status = "not_configured"
        self.native = False
        self.require_source_confirmation=False
        self.last_prune=float('-inf')
        self.accept_lock = asyncio.Lock()
        self.cycle_lock = asyncio.Lock()
        self.channel_locks = {}
        self.deliveries = {}
        self.delivery_slots = asyncio.Semaphore(2)
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
          CREATE TABLE IF NOT EXISTS banner_source_receipts(
            fingerprint TEXT PRIMARY KEY, expires_at REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS banner_config_versions(
            guild_id TEXT PRIMARY KEY, generation INTEGER NOT NULL);
        """.replace("banner_", self.kind + "_"))
        from feed_state import FeedState
        self.diagnostics = FeedState(self)
        columns = {row[1] for row in self.query('PRAGMA table_info(banner_jobs)')}
        for name in ('first_attempt', 'next_try'):
            if name not in columns:
                self.query('ALTER TABLE banner_jobs ADD COLUMN '+name+' REAL NOT NULL DEFAULT 0')
        self.db.commit()
        if kind == 'banner':
            from banner_images import BannerImages
            from banner_votes import BannerVotes

            self.images = BannerImages(self)
            self.votes = BannerVotes(self)
        else:
            from daily_current import DailyCurrent

            self.current_daily = DailyCurrent(self)

    def query(self, statement, parameters=()):
        return self.db.execute(statement.replace("banner_", self.kind + "_"), parameters)

    def target(self, guild_id):
        return self.query("SELECT * FROM banner_targets WHERE guild_id=?", (str(guild_id),)).fetchone()

    def configure(self, guild_id, channel_id):
        guild_id, channel_id = str(guild_id), str(channel_id)
        if int(channel_id) in SOURCE_CHANNELS:
            raise ValueError("Choose a destination channel different from the source channel.")
        with self.db:
            self.query('INSERT INTO banner_config_versions VALUES(?,1) ON CONFLICT(guild_id) DO UPDATE SET generation=generation+1', (guild_id,))
            self.query("DELETE FROM banner_jobs WHERE guild_id=? AND channel_id<>? AND state NOT IN ('sent','sending','uncertain')", (guild_id, channel_id))
            self.query("INSERT INTO banner_targets VALUES(?,?,?) ON CONFLICT(guild_id) DO UPDATE SET channel_id=excluded.channel_id,enabled_at=excluded.enabled_at",
                            (guild_id, channel_id, self.clock()))
            latest = self.query("SELECT id FROM banner_events WHERE created_at>?"
                + (" AND id=(SELECT c.event_id FROM daily_current c JOIN daily_source_head h ON h.singleton=c.singleton AND h.source_message=c.source_message)" if self.kind == 'daily' else '')
                + " ORDER BY created_at DESC,rowid DESC LIMIT 1", (self.clock() - self.max_age,)).fetchone()
            if latest:
                self.query("INSERT OR IGNORE INTO banner_jobs(event_id,guild_id,channel_id) VALUES(?,?,?)", (latest[0], guild_id, channel_id))
                self.query("UPDATE banner_jobs SET state='pending' WHERE event_id=? AND channel_id=? AND state='unavailable'", (latest[0], channel_id))
        if self.kind == 'banner':
            self.images.resume(guild_id, channel_id)

    def disable(self, guild_id):
        with self.db:
            self.query('INSERT INTO banner_config_versions VALUES(?,1) ON CONFLICT(guild_id) DO UPDATE SET generation=generation+1', (str(guild_id),))
            self.query("DELETE FROM banner_targets WHERE guild_id=?", (str(guild_id),))
            self.query("DELETE FROM banner_jobs WHERE guild_id=? AND state NOT IN ('sent','sending','uncertain')", (str(guild_id),))

    def generation(self, guild_id):
        row = self.query('SELECT generation FROM banner_config_versions WHERE guild_id=?', (str(guild_id),)).fetchone()
        return row[0] if row else 0

    def channel_lock(self, channel_id):
        return self.channel_locks.setdefault(str(channel_id), asyncio.Lock())

    def current_job(self, job):
        target = self.target(job['guild_id'])
        event = self.query('SELECT source_message FROM banner_events WHERE id=?', (job['event_id'],)).fetchone()
        current = self.query('SELECT state FROM banner_jobs WHERE event_id=? AND channel_id=?', (job['event_id'],job['channel_id'])).fetchone()
        return bool(target and target['channel_id'] == job['channel_id']
            and event and not self.diagnostics.obsolete(event['source_message'])
            and current and current['state'] != 'superseded'
            and ('generation' not in job or job['generation'] == self.generation(job['guild_id']))
            and (self.kind != 'daily' or self.current_daily.known(job['event_id'])))

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
                    "unavailable": "\nA server administrator needs to restore channel access and permissions. The latest eligible image will resume automatically.",
                    "oversize": "\nAn image exceeded this server's attachment size limit.",
                    "uncertain": "\nA delivery is awaiting confirmation from Discord. The bot is checking the result to avoid duplicates.",
                }.get(job[0], "")
            if self.kind == 'banner' and self.target(guild_id):
                status += '\n**W/M/L reactions:** ' + self.votes.description(guild_id)
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
            summary=self.diagnostics.snapshot(guild_id).get('delivery')
            text += (f"\nLast confirmed delivery: <t:{int(summary['confirmed'])}:R>." if summary
                     else "\nNo confirmed delivery remains in the recent receipt window.")
        state=self.diagnostics.snapshot(guild_id)
        for key,label in (('polled','Source checked'),('observed','Source image published/updated'),('received','Bytes verified')):
            text+='\n'+label+(': <t:'+str(int(state[key]))+':R>.' if state[key] else ': not confirmed yet.')
        text+=f"\nPending deliveries: {state['pending']}."
        if state['error']:
            text+=' Last issue: '+state['error'].replace('_',' ')+'.'
        return text

    def ready(self):
        if self.paused():
            return True
        if not self.query('SELECT 1 FROM banner_targets LIMIT 1').fetchone():
            return True
        state=self.diagnostics.snapshot()
        waiting = (state['source_message'] and (state['source_message'] != state['received_source']
                   or state['observed'] > state['received_version']) and self.clock()-state['observed_at']>120)
        return self.status=='ready' and state['polled']>0 and self.clock()-state['polled']<120 and not waiting

    def paused(self):
        until=float(self.bot.store.get('feed-maintenance-until:'+self.kind) or 0)
        return self.bot.store.get('feed-maintenance:'+self.kind) == '1' and (not until or until>self.clock())

    def pause(self, paused, actor, *, seconds=3600):
        with self.db:
            for key,value in (('feed-maintenance:', '1' if paused else '0'),
                    ('feed-maintenance-until:', str(self.clock()+seconds if paused else 0)),
                    ('feed-maintenance-version:', str(self.maintenance_version()+1))):
                self.db.execute('INSERT OR REPLACE INTO bot_meta VALUES(?,?)',(key+self.kind,value))
            self.bot.store.audit('feed-maintenance', actor, self.kind+(' paused' if paused else ' resumed'))

    def maintenance_version(self):
        return int(self.bot.store.get('feed-maintenance-version:'+self.kind) or 0)

    def alert_conditions(self):
        if self.paused():
            return {}
        if not self.query('SELECT 1 FROM banner_targets LIMIT 1').fetchone():
            return {}
        state=self.diagnostics.snapshot()
        failures=self.query("SELECT count(*) FROM banner_jobs j JOIN banner_targets t ON t.channel_id=j.channel_id WHERE state IN ('unavailable','oversize','rejected')").fetchone()[0]
        return {
            self.kind+'_source':(not self.ready(),f'The {self.kind} source has not confirmed a recent successful check. Open private feed diagnostics.'),
            self.kind+'_delivery':(bool((state['pending'] and state['oldest'] and self.clock()-state['oldest']>180) or failures),
                f'The {self.kind} feed has delayed or blocked destinations. Check private status and channel permissions.'),
            self.kind+'_receive':(bool(state['source_message'] and (state['source_message']!=state['received_source'] or state['observed']>state['received_version']) and self.clock()-state['observed_at']>120),
                f'A new {self.kind} source image has not completed reception. Check private source and download diagnostics.'),
        }

    def start(self):
        if reader_token() and not self.task:
            self.task = asyncio.create_task(self.supervise(), name="banner-reader")

    async def supervise(self):
        await self.bot.wait_until_ready()
        delay = 5
        while True:
            for feed in (self,self.bot.daily):
                if not feed.native:
                    feed.status='connecting'
            try:
                from feed_receiver import FeedReceiver
                setup_reservation=None
                executable=self.bot.directory/'.banner-reader-venv'/'bin'/'python'
                marker=self.bot.directory/'.banner-reader-venv'/'.dependencies.sha256'
                expected=hashlib.sha256(Path(__file__).with_name('requirements-reader.txt').read_bytes()).hexdigest()
                current=marker.read_text().strip() if marker.is_file() else ''
                if (not executable.exists() or current!=expected) and getattr(self.bot,'instance_storage',None):
                    reservation=self.bot.instance_storage.reserve(96*1024*1024,memory=48*1024*1024)
                    await reservation.__aenter__()
                    setup_reservation=reservation
                self.receiver = FeedReceiver(self.bot)
                self.receiver.start()
                environment = {key: value for key, value in os.environ.items()
                               if key in {"PATH", "SYSTEMROOT", "TMPDIR", "TMP", "TEMP", "LANG", "LC_ALL", "SSL_CERT_FILE", "SSL_CERT_DIR", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"}}
                self.process = await asyncio.create_subprocess_exec(
                    sys.executable, "-I", str(Path(__file__).with_name("banner_reader.py")),
                    "--bootstrap", str((self.bot.directory / ".banner-reader-venv").resolve()),
                    env=environment, stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                    limit=65536,
                )
                config = {"token": reader_token(), "source_channel_ids": IMAGE_SOURCE_CHANNELS,
                          "daily_channel_id": DAILY_CHANNEL_ID}
                self.process.stdin.write(json.dumps(config).encode() + b"\n")
                await self.process.stdin.drain()
                self.process.stdin.close()
                count=0
                stream = self.process.stdout.__aiter__()
                while True:
                    try:
                        installing=any(feed.status=='installing' for feed in (self,self.bot.daily) if not feed.native)
                        line = await asyncio.wait_for(anext(stream), 300 if installing else 90)
                    except StopAsyncIteration:
                        break
                    try:
                        event = json.loads(line)
                        if setup_reservation is not None and event.get('event') in {'connecting','ready'}:
                            await setup_reservation.__aexit__(None,None,None)
                            setup_reservation=None
                        self.receiver.handle(event)
                        if event.get('event') == 'ready':
                            delay = 5
                    except (ValueError, TypeError, KeyError, aiohttp.ClientError, asyncio.TimeoutError) as error:
                        log.warning("Image source event deferred (%s); reception can retry automatically.",
                                    type(error).__name__)
                    count+=1
                    if count%25==0:
                        await asyncio.sleep(0)
                await self.process.wait()
                if any(feed.status in {'login_failed','account_action_required'} for feed in (self,self.bot.daily) if not feed.native):
                    return
            except asyncio.CancelledError:
                raise
            except Exception as error:
                log.warning("Leitor de banners indisponível: %s", type(error).__name__)
            finally:
                if setup_reservation is not None:
                    await setup_reservation.__aexit__(None,None,None)
                if self.receiver:
                    await self.receiver.close()
                    self.receiver = None
                await self.stop_process()
            for feed in (self,self.bot.daily):
                if not feed.native:
                    feed.status='reader_failed'
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

    async def stop_reader(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task,return_exceptions=True)
            self.task=None
        await self.stop_process()

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
        if self.kind=='daily' and not all(image_url(url) for url in urls):
            return False
        skipped_urls = sum(not image_url(url) for url in urls)
        urls = [url for url in urls if image_url(url)]
        if not urls:
            self.diagnostics.error('unsupported_source_urls')
            return False
        published=float(payload.get('published_at',created))
        if not math.isfinite(published):
            return False
        if published<=self.clock()-self.max_age:
            known_source=self.query('SELECT 1 FROM banner_seen WHERE source_message=? LIMIT 1',(message_id,)).fetchone()
            current=self.current_daily.current() if self.kind=='daily' else None
            if not known_source and not (current and current['source_message']==message_id):
                return False
        if self.bot.health.storage_level == "critical":
            return False
        async with self.accept_lock:
            self.prune()
            if self.diagnostics.obsolete(message_id):
                return False
            if self.kind == 'daily' and self.current_daily.older(message_id, created):
                return False
            if self.kind == 'daily':
                self.current_daily.observe(message_id,created)
            self.diagnostics.observe(message_id,created)
            fingerprint = hashlib.sha256(json.dumps(image_identity(payload), separators=(',', ':')).encode()).hexdigest()
            if self.query('SELECT 1 FROM banner_source_receipts WHERE fingerprint=?', (fingerprint,)).fetchone():
                return False
            images, blobs, size, skipped, partial = [], {}, 0, skipped_urls, False
            last_error=None
            for url in dict.fromkeys(urls):
                try:
                    blob = await self.download(url, min(MAX_IMAGE, MAX_BATCH - size))
                    size += len(blob)
                    from media_validation import decode_budget
                    async with decode_budget(getattr(self.bot,'instance_storage',None), blob):
                        extension = await asyncio.to_thread(image_extension, blob)
                except (ValueError,aiohttp.ClientError,TimeoutError,OSError) as error:
                    if isinstance(error,ValueError) and str(error)=='Unsupported image':
                        skipped+=1
                        continue
                    if self.kind=='daily':
                        raise
                    partial,last_error=True,error
                    continue
                digest = hashlib.sha256(blob).hexdigest()
                if digest not in blobs:
                    images.append(digest)
                    blobs[digest] = (extension, blob)
            if not images:
                if last_error:
                    raise last_error
                self.diagnostics.error('unsupported_images')
                return False
            ident = hashlib.sha256((message_id + ":" + ":".join(images)).encode()).hexdigest()
            if (self.query("SELECT 1 FROM banner_events WHERE id=?", (ident,)).fetchone()
                    or self.diagnostics.known(message_id, images)
                    or (self.kind == 'daily' and self.current_daily.current() is not None
                        and self.current_daily.current()['event_id']==ident)):
                with self.db:
                    if self.kind == 'daily':
                        self.current_daily.remember(ident, message_id, created)
                    if not partial:
                        self.query('INSERT OR REPLACE INTO banner_source_receipts VALUES(?,?)',
                                   (fingerprint, created + self.max_age))
                        self.diagnostics.received(skipped,message_id=message_id,created=created)
                return False
            used = self.query("SELECT COALESCE(SUM(length(data)),0) FROM banner_assets").fetchone()[0]
            new = sum(len(blob) for digest, (_, blob) in blobs.items() if not self.query("SELECT 1 FROM banner_assets WHERE digest=?", (digest,)).fetchone())
            if used + new > MAX_CACHE or self.query("SELECT COUNT(*) FROM banner_events").fetchone()[0] >= 64:
                raise ValueError("Banner cache full")
            with self.db:
                for digest, (extension, blob) in blobs.items():
                    self.query("INSERT OR IGNORE INTO banner_assets VALUES(?,?,?)", (digest, extension, blob))
                self.query("INSERT INTO banner_events VALUES(?,?,?,?)", (ident, message_id, created, json.dumps(images)))
                self.diagnostics.remember(message_id, images, created)
                if not partial:
                    self.diagnostics.received(skipped,message_id=message_id,created=created)
                else:
                    self.query("UPDATE banner_diagnostics SET error='partial_reception' WHERE singleton=1")
                self.query("UPDATE banner_jobs SET state='superseded' WHERE state='pending' AND event_id IN (SELECT id FROM banner_events WHERE source_message=? AND id<>?)", (message_id, ident))
                self.query("INSERT OR IGNORE INTO banner_jobs(event_id,guild_id,channel_id) SELECT ?,guild_id,channel_id FROM banner_targets", (ident,))
                if self.kind == 'daily':
                    self.current_daily.remember(ident, message_id, created)
                # Confirm only after all bytes, validation and jobs are saved.
                # A receive retry then needs neither a download nor a new upload.
                if not partial:
                    self.query('INSERT OR REPLACE INTO banner_source_receipts VALUES(?,?)',
                               (fingerprint, created + self.max_age))
            return True

    def prune(self, *, force=True):
        if not force and self.clock()-self.last_prune<30:
            return
        self.last_prune=self.clock()
        with self.db:
            self.query('DELETE FROM banner_source_receipts WHERE expires_at<=?', (self.clock(),))
            self.diagnostics.prune()
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
            self.query("UPDATE banner_jobs SET state=CASE WHEN state='superseded' THEN state ELSE ? END,attempted_at=?,message_id=? WHERE event_id=? AND channel_id=?",
                            (state, self.clock(), str(message_id) if message_id else None, job["event_id"], job["channel_id"]))
            if state == 'sent':
                self.diagnostics.confirmed(job)
            self.query('UPDATE banner_jobs SET first_attempt=CASE WHEN first_attempt=0 AND ?=\'sending\' THEN ? ELSE first_attempt END,next_try=? WHERE event_id=? AND channel_id=?',
                (state,self.clock(),self.clock()+(60 if state=='unavailable' else 30) if state in {'uncertain','unavailable'} else 0,job['event_id'],job['channel_id']))

    def recover_permissions(self):
        # Only the latest unexpired job for a configured target is eligible.
        # Never recreate a sent image or revive an obsolete daily/source version.
        rows = self.query('''SELECT j.* FROM banner_jobs j JOIN banner_events e ON e.id=j.event_id
            JOIN banner_targets t ON t.guild_id=j.guild_id AND t.channel_id=j.channel_id
            WHERE j.state='unavailable' AND j.next_try<=? AND e.created_at>?
            AND NOT EXISTS(SELECT 1 FROM banner_jobs n JOIN banner_events x ON x.id=n.event_id
                WHERE n.channel_id=j.channel_id AND (x.created_at>e.created_at OR (x.created_at=e.created_at AND x.rowid>e.rowid)))
            ORDER BY j.next_try LIMIT 16''', (self.clock(),self.clock()-self.max_age)).fetchall()
        from feed_views import feed_permissions
        for row in rows:
            channel = self.bot.get_channel(int(row['channel_id']))
            self.query('UPDATE banner_jobs SET next_try=? WHERE event_id=? AND channel_id=?',
                       (self.clock()+60,row['event_id'],row['channel_id']))
            if (not isinstance(channel,discord.TextChannel) or str(channel.guild.id)!=row['guild_id']
                    or not self.current_job(dict(row)) or feed_permissions(channel,channel.guild.me)):
                continue
            self.query("UPDATE banner_jobs SET state='pending',next_try=0 WHERE event_id=? AND channel_id=? AND state='unavailable'",(row['event_id'],row['channel_id']))
            if self.kind=='banner':
                event=self.query('SELECT source_message,images FROM banner_events WHERE id=?',(row['event_id'],)).fetchone()
                for digest in json.loads(event['images']):
                    self.db.execute("UPDATE banner_image_receipts SET state='pending' WHERE source_message=? AND digest=? AND channel_id=? AND state='unavailable'",(event['source_message'],digest,row['channel_id']))
        self.db.commit()

    @staticmethod
    def nonce(job):
        return str(int(hashlib.sha256((job["event_id"] + job["channel_id"]).encode()).hexdigest()[:15], 16))

    async def deliver(self, job):
        async with self.channel_lock(job['channel_id']):
            job = dict(job)
            job['generation'] = self.generation(job['guild_id'])
            if self.paused() or not self.current_job(job):
                return
            target = self.target(job["guild_id"])
            if not target or target["channel_id"] != job["channel_id"]:
                return
            if self.kind == 'daily' and not self.current_daily.known(job['event_id']):
                return
            channel = self.bot.get_channel(int(job["channel_id"]))
            if not isinstance(channel, discord.TextChannel):
                self.state(job, "unavailable")
                return
            permissions = channel.permissions_for(channel.guild.me)
            if not all(getattr(permissions, name, False) for name in ("view_channel", "send_messages", "attach_files", "read_message_history")):
                self.state(job, "unavailable")
                return
            from contextlib import AsyncExitStack
            async with AsyncExitStack() as reservations:
                budget=getattr(self.bot,'instance_storage',None)
                sizes=self.query('SELECT length(data) FROM banner_assets WHERE digest IN (SELECT value FROM banner_events,json_each(images) WHERE banner_events.id=?)',(job['event_id'],)).fetchall()
                if budget:
                    await reservations.enter_async_context(budget.reserve(0,memory=3*sum(r[0] for r in sizes)))
                await self.deliver_reserved(job, channel)

    async def deliver_reserved(self, job, channel):
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
            from feed_history import recent_attempts
            async for message in recent_attempts(channel, job['first_attempt'] or job['attempted_at']):
                if message.author.id == self.bot.user.id and (str(message.nonce) == self.nonce(job) or [a.filename for a in message.attachments] == names):
                    self.state(job, "sent", message.id)
                    return
            self.state(job, "uncertain")
            return
        limit = min(MAX_IMAGE, channel.guild.filesize_limit)
        if any(len(asset["data"]) > limit for asset in assets):
            self.state(job, "oversize")
            return
        if self.paused() or not self.current_job(job):
            return
        files = [discord.File(io.BytesIO(asset["data"]), filename=name) for asset, name in zip(assets, names)]
        self.state(job, "sending")
        try:
            with handle_message_parameters(files=files, allowed_mentions=discord.AllowedMentions.none()) as params:
                from feed_tools import silence_payload
                silence_payload(self.bot, job['guild_id'], params)
                for part in params.multipart:
                    if part["name"] == "payload_json":
                        payload = json.loads(part["value"])
                        payload.update(nonce=self.nonce(job), enforce_nonce=True)
                        part["value"] = json.dumps(payload)
                response = await self.bot.http.send_message(channel.id, params=params)
            self.state(job, "sent", response["id"])
        except (discord.Forbidden, discord.NotFound):
            self.state(job, "unavailable")
        except Exception as error:
            from delivery_errors import feed_failure,retry_delay
            self.state(job, feed_failure(error))
            delay=retry_delay(error)
            if delay:
                with self.db:
                    self.query('UPDATE banner_jobs SET next_try=? WHERE event_id=? AND channel_id=?',
                               (self.clock()+delay,job['event_id'],job['channel_id']))
            log.warning("Confirmação de envio de banner pendente; sem reenvio automático.")
        finally:
            for file in files:
                file.close()

    async def cycle(self):
        if self.cycle_lock.locked():
            return
        async with self.cycle_lock:
            await self._cycle()

    async def _cycle(self):
        self.prune(force=False)
        if self.paused():
            return
        if self.bot.health.storage_level == "critical" or getattr(self.bot.health,'memory_level','ok') == 'critical':
            return
        if self.require_source_confirmation and self.status!='ready':
            return
        if self.kind == 'daily' and self.status != 'ready':
            return  # Confirm the current source before replaying any cached job.
        self.recover_permissions()
        self.deliveries = {key: task for key,task in self.deliveries.items() if not task.done()}
        jobs = self.query("SELECT j.* FROM banner_jobs j JOIN banner_targets t ON t.guild_id=j.guild_id AND t.channel_id=j.channel_id WHERE j.state IN ('pending','sending','uncertain') AND j.next_try<=?"
            + (" AND j.event_id=(SELECT c.event_id FROM daily_current c JOIN daily_source_head h ON h.singleton=c.singleton AND h.source_message=c.source_message)" if self.kind == 'daily' else '')
            + " ORDER BY j.attempted_at,j.rowid LIMIT 64", (self.clock(),)).fetchall()

        async def run(job):
            async with self.delivery_slots:
                try:
                    await asyncio.wait_for(self.deliver(job), 40)
                except asyncio.CancelledError:
                    raise
                except (discord.HTTPException, aiohttp.ClientError, asyncio.TimeoutError, OSError):
                    self.diagnostics.error('delivery_deferred')
                    self.query('UPDATE banner_jobs SET next_try=? WHERE event_id=? AND channel_id=?',
                               (self.clock()+30,job['event_id'],job['channel_id']))
                    self.db.commit()
                except Exception as error:
                    self.diagnostics.error('delivery_failed')
                    log.warning('Delivery deferred: feed=%s stage=send error=%s status=%s',self.kind,type(error).__name__,getattr(error,'status',0))
        for job in jobs:
            if len(self.deliveries)>=16:
                break
            if job['channel_id'] not in self.deliveries:
                self.deliveries[job['channel_id']] = asyncio.create_task(run(job),name='deliver-'+self.kind)
        if self.deliveries:
            await asyncio.wait(self.deliveries.values(), timeout=.05)

    async def close(self):
        if self.kind == 'banner':
            await self.votes.close()
        tasks = list(self.deliveries.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks,return_exceptions=True)
        self.deliveries.clear()
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
        self.generation = self.feed.generation(self.guild)

    async def interaction_check(self, interaction):
        from bot_views import reply
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
        from bot_views import reply
        require_banner_admin(interaction)
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.bot.guild_lock(self.guild):
            target = self.feed.target(self.guild)
            if not target or target["channel_id"] != str(self.channel) or self.feed.generation(self.guild) != self.generation:
                await reply(interaction, "The configuration changed. Open the setup command in the desired channel to check it.")
                return
            self.feed.disable(self.guild)
        await reply(interaction, "This image feed has been disabled in this server.")
        self.stop()

    async def on_error(self, interaction, error, item):
        from bot_views import reply
        await reply(interaction, "The change could not be confirmed. Open the setup command to check it.")
