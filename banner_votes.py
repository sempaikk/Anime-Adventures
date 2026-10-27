"""Original application emojis, independent reactions and resumable banner backfill."""

import asyncio
import hashlib
import io
import json
import logging
from pathlib import Path
import re

import aiohttp
import discord
from PIL import Image

from banner_vote_order import BannerVoteOrder

ROOT = Path(__file__).resolve().parent
ASSET_FILE = ROOT / 'data/banner_votes.json'
KEYS = ('win', 'mid', 'lose')
BANNER_FILE = re.compile(r'^banner-[0-9a-f]{16}(?:-\d{1,2})?\.(?:png|jpg|webp)$')
log = logging.getLogger('adventures.banner-votes')


def load_assets():
    data = json.loads(ASSET_FILE.read_text(encoding='utf-8'))
    if data.get('schema') != 1 or [item['key'] for item in data['images']] != list(KEYS):
        raise ValueError('Invalid banner reaction manifest')
    result = []
    for item in data['images']:
        path = (ROOT / item['path']).resolve()
        if not path.is_relative_to(ROOT / 'assets/banner-votes') or path.stat().st_size > 262144:
            raise ValueError('Invalid banner reaction asset')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != item['sha256']:
            raise ValueError('Banner reaction image differs from original')
        with Image.open(io.BytesIO(raw)) as image:
            if image.format != 'PNG' or image.mode != 'RGBA' or max(image.size) > 128 or getattr(image, 'is_animated', False):
                raise ValueError('Unsupported banner reaction image')
            image.verify()
        result.append((item['key'], item['sha256'], raw))
    return result


class BannerVotes:
    def __init__(self, relay):
        self.relay, self.bot, self.db = relay, relay.bot, relay.db
        self.emojis = ()
        self.next_setup = 0
        self.lock = asyncio.Lock()
        self.status = 'Preparing the original W/M/L emojis.'
        self.db.execute('''CREATE TABLE IF NOT EXISTS banner_vote_backfill(
            guild_id TEXT NOT NULL, channel_id TEXT PRIMARY KEY, before_id TEXT,
            done INTEGER NOT NULL DEFAULT 0, scanned INTEGER NOT NULL DEFAULT 0,
            rated INTEGER NOT NULL DEFAULT 0, skipped INTEGER NOT NULL DEFAULT 0,
            next_scan REAL NOT NULL DEFAULT 0)''')
        self.db.commit()
        self.order = BannerVoteOrder(self)

    async def ensure_emojis(self):
        if self.emojis:
            return True
        if self.relay.clock() < self.next_setup:
            return False
        self.next_setup = self.relay.clock() + 60
        try:
            assets = load_assets()
            known = {str(emoji.id): emoji for emoji in await self.bot.fetch_application_emojis()}
            selected = []
            for name, digest, raw in assets:
                key = 'banner-vote-emoji:' + digest
                emoji = known.get(self.bot.store.get(key))
                legacy_name = name + '_' + digest[:12]
                if emoji is None:
                    emoji = next((item for item in known.values() if item.name == legacy_name), None)
                if emoji is None:
                    # Recover a lost create acknowledgment before assigning the public name.
                    emoji = await self.bot.create_application_emoji(name=legacy_name, image=raw)
                # Save the ID before renaming: a lost edit acknowledgment must not
                # replace an existing emoji or disconnect votes from its identity.
                self.bot.store.set(key, emoji.id)
                if emoji.name != name:
                    emoji = await emoji.edit(name=name)
                selected.append(emoji)
            # PATCH acknowledgments and existing reaction payloads can carry
            # different names. Confirm the application registry independently.
            current = {emoji.id: emoji for emoji in await self.bot.fetch_application_emojis()}
            selected = [current.get(emoji.id) for emoji in selected]
            reported = tuple(emoji.name if emoji else 'missing' for emoji in selected)
            if reported != KEYS:
                self.status = ('Short emoji names are awaiting Discord confirmation. Reported names: '
                               + ', '.join(reported) + '. Banner images continue to be delivered.')
                return False
            # One bounded pass also refreshes names on reactions created before
            # the rename. Preserve the regular historical cursor on later restarts.
            if not self.bot.store.get('banner-vote-name-refresh:1'):
                with self.db:
                    self.db.execute('''UPDATE banner_vote_backfill SET before_id=NULL,done=0,
                        scanned=0,rated=0,skipped=0,next_scan=0''')
                    self.bot.store.set('banner-vote-name-refresh:1', '1')
            self.emojis = tuple(selected)
            self.status = 'W/M/L ready. Discord-confirmed names: win, mid, lose.'
            return True
        except (discord.DiscordException, aiohttp.ClientError, TimeoutError, OSError, ValueError, KeyError, TypeError) as error:
            self.status = 'Emoji setup is waiting. Banner images continue to be delivered.'
            log.warning('Banner emoji setup deferred: %s', type(error).__name__)
            return False

    def description(self, guild_id):
        target = self.relay.target(guild_id)
        channel = self.bot.get_channel(int(target['channel_id'])) if target else None
        if channel and not channel.permissions_for(channel.guild.me).add_reactions:
            return 'Grant Add Reactions in this channel. Banner images remain enabled.'
        row = self.db.execute('SELECT * FROM banner_vote_backfill WHERE channel_id=?',
                              (target['channel_id'],)).fetchone() if target else None
        text = self.status
        if row:
            text += f" Historical scan {'completed' if row['done'] else 'in progress'}: {row['rated']} banner message(s) checked."
            if row['skipped']:
                text += f" {row['skipped']} message(s) already reached Discord's reaction limit."
        return text

    def target_channel(self, guild_id, channel_id):
        target = self.relay.target(guild_id)
        if not target or target['channel_id'] != str(channel_id):
            return None
        channel = self.bot.get_channel(int(channel_id))
        if not isinstance(channel, discord.TextChannel):
            return None
        permissions = channel.permissions_for(channel.guild.me)
        if not all(getattr(permissions, name) for name in ('view_channel', 'read_message_history', 'add_reactions')):
            return None
        return channel

    async def rate(self, message, mask=0, progress=None, *, refresh_names=False):
        present = {getattr(reaction.emoji, 'id', None): reaction
                   for reaction in getattr(message, 'reactions', ()) if reaction.me}
        for index, emoji in enumerate(self.emojis):
            bit = 1 << index
            if mask & bit:
                continue
            reaction = present.get(emoji.id)
            if refresh_names and reaction and getattr(reaction.emoji, 'name', None) != emoji.name:
                # Remove only our own seed, then restore it with the current name.
                # Never clear an emoji's reactions or remove another member's vote.
                await message.remove_reaction(reaction.emoji, self.bot.user)
                await message.add_reaction(emoji)
            elif reaction is None:
                await message.add_reaction(emoji)
            mask |= bit
            if progress:
                progress(mask)
        return mask

    def observe_error(self, error):
        if isinstance(error, discord.HTTPException) and error.code == 10014:
            self.emojis = ()
            self.next_setup = self.relay.clock() + 30
        self.status = 'Some W/M/L reactions are waiting for Discord or channel permissions.'

    async def live_reactions(self):
        rows = self.db.execute('''SELECT r.* FROM banner_image_receipts r JOIN banner_targets t
            ON t.guild_id=r.guild_id AND t.channel_id=r.channel_id
            WHERE r.state='sent' AND r.reactions<>7 AND r.reaction_after<=? AND r.expires_at>?
            ORDER BY r.reaction_after LIMIT 8''', (self.relay.clock(), self.relay.clock())).fetchall()
        for row in rows:
            async with self.bot.guild_lock(int(row['guild_id'])):
                channel = self.target_channel(row['guild_id'], row['channel_id'])
                def save(mask):
                    with self.db:
                        self.db.execute('''UPDATE banner_image_receipts SET reactions=?,reaction_after=?
                            WHERE source_message=? AND digest=? AND channel_id=?''',
                            (mask, self.relay.clock() + 30, row['source_message'], row['digest'], row['channel_id']))
                save(row['reactions'])
                if channel is None:
                    continue
                try:
                    await self.rate(channel.get_partial_message(int(row['message_id'])), row['reactions'], save)
                except discord.NotFound as error:
                    if error.code == 10008:
                        save(7)  # The owner deleted the image; never recreate it.
                    else:
                        self.observe_error(error)
                except (discord.HTTPException, aiohttp.ClientError, TimeoutError, OSError) as error:
                    self.observe_error(error)

    async def backfill(self):
        row = self.db.execute('''SELECT b.* FROM banner_vote_backfill b JOIN banner_targets t
            ON t.guild_id=b.guild_id AND t.channel_id=b.channel_id
            WHERE b.done=0 AND b.next_scan<=? ORDER BY b.next_scan LIMIT 1''', (self.relay.clock(),)).fetchone()
        if row is None:
            return
        with self.db:
            self.db.execute('UPDATE banner_vote_backfill SET next_scan=? WHERE channel_id=?',
                            (self.relay.clock() + 30, row['channel_id']))
        channel = self.target_channel(row['guild_id'], row['channel_id'])
        if channel is None:
            return
        # Old daily and banner batches shared filenames. Do not guess in mixed channels.
        daily = self.bot.daily.target(row['guild_id'])
        mixed = bool(daily and daily['channel_id'] == row['channel_id'])
        try:
            before = discord.Object(id=int(row['before_id'])) if row['before_id'] else None
            page = [message async for message in channel.history(limit=20, before=before, oldest_first=False)]
            rated = 0
            for message in page:
                skipped = 0
                files = message.attachments
                banner = (message.author.id == self.bot.user.id and not getattr(message, 'webhook_id', None)
                          and bool(files) and all(BANNER_FILE.fullmatch(file.filename) for file in files))
                if mixed and any(re.search(r'-\d+\.', file.filename) for file in files):
                    banner = False
                if banner:
                    async with self.bot.guild_lock(int(row['guild_id'])):
                        if self.target_channel(row['guild_id'], row['channel_id']) is None:
                            return
                        try:
                            repaired = await self.order.repair(message, channel)
                            if repaired is None:
                                return
                            if not repaired:
                                await self.rate(message, refresh_names=True)
                        except discord.HTTPException as error:
                            if error.code not in (10008, 30010):
                                raise
                            skipped = int(error.code == 30010)
                            banner = False
                    rated += 1
                with self.db:
                    self.db.execute('''UPDATE banner_vote_backfill SET before_id=?,scanned=scanned+1,
                        rated=rated+?,skipped=skipped+? WHERE channel_id=?''', (str(message.id), int(banner), skipped, row['channel_id']))
                if rated >= 3:
                    return  # Next cycle resumes at this message; live deliveries have priority.
            if len(page) < 20:
                with self.db:
                    self.db.execute('UPDATE banner_vote_backfill SET done=1 WHERE channel_id=?', (row['channel_id'],))
        except (discord.HTTPException, aiohttp.ClientError, TimeoutError, OSError) as error:
            self.observe_error(error)

    async def cycle(self):
        if self.lock.locked() or self.bot.health.storage_level == 'critical':
            return
        async with self.lock:
            with self.db:
                self.db.execute('''INSERT OR IGNORE INTO banner_vote_backfill(guild_id,channel_id)
                    SELECT guild_id,channel_id FROM banner_targets''')
                self.db.execute('DELETE FROM banner_vote_backfill WHERE channel_id NOT IN (SELECT channel_id FROM banner_targets)')
            if not self.db.execute('SELECT 1 FROM banner_targets LIMIT 1').fetchone() or not await self.ensure_emojis():
                return
            self.order.prepare_scan()
            await self.live_reactions()
            if self.emojis:
                await self.backfill()
