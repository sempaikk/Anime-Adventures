"""Owner-only server inventory and release notices for the designated community."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path

import aiohttp
import discord
from discord.http import handle_message_parameters

CENTRAL_GUILD_ID = 1554953245204422807
CENTRAL_UPDATE_CHANNEL_ID = 1564498826423959652
# One fixed editorial correction; never use new release notes to rewrite history.
NOTICE_CORRECTION_VERSION = "2026.10.27.6"
UPDATES_PATH = Path(__file__).with_name("data") / "community_updates.json"
CORRECTION_PATH = Path(__file__).with_name("data") / "community_notice_correction.json"
REPORT_PERMISSIONS = (
    "view_channel", "send_messages", "read_message_history", "attach_files",
    "embed_links", "manage_webhooks", "manage_roles", "manage_channels",
    "administrator", "add_reactions",
)


class CommunityHub:
    def __init__(self, bot):
        self.bot = bot
        self.lock = asyncio.Lock()
        self.status = "Waiting for the community server."
        self.next_attempt = 0

    def guild(self):
        guild = self.bot.get_guild(CENTRAL_GUILD_ID)
        if not guild or guild.unavailable or not guild.me:
            return None
        return guild

    def update_channel(self, guild):
        # Confirmed from the owner's private server report. Names may change;
        # never redirect announcements to a different channel with a similar name.
        channel = guild.get_channel(CENTRAL_UPDATE_CHANNEL_ID)
        if not isinstance(channel, discord.TextChannel):
            self.status = "The configured updates channel is unavailable to the bot."
            return None
        # A changelog must not change or mix with a configured relay destination.
        configured = self.bot.globalchat.store.channel(guild.id)
        if ((configured and configured['channel_id'] == str(channel.id))
                or any(feed.target(guild.id) and feed.target(guild.id)['channel_id'] == str(channel.id)
                       for feed in (self.bot.banners, self.bot.daily))):
            self.status = "Choose an update-log channel separate from the feeds and global chat."
            return None
        permissions = channel.permissions_for(guild.me)
        if not all(getattr(permissions, key) for key in
                   ("view_channel", "send_messages", "read_message_history")):
            self.status = "The bot needs View Channel, Send Messages and Read Message History in update-log."
            return None
        return channel

    def release_note(self):
        build = self.bot.build
        if not build.get('verified'):
            self.status = "Release files must pass verification before an update is published."
            return None
        data = json.loads(UPDATES_PATH.read_text(encoding="utf-8"))
        if data.get('schema') != 1 or data.get('version') != build['version']:
            self.status = "No user-facing notes for the running version."
            return None
        if data.get('requires_banner_reactions') and not self.bot.banners.votes.emojis:
            self.status = 'Update announcement waiting: the banner reaction setup must finish.'
            return None
        if not self.update_complete():
            return None
        return self.note_text(data)

    def update_complete(self):
        # Every new notice uses this gate, including releases without a W/M/L flag.
        # Future asynchronous migrations must expose confirmed completion here too.
        pending = (self.bot.banners.votes.release_pending()
                   or self.bot.feed_publications.release_pending())
        if pending:
            self.status = 'Update announcement waiting: ' + pending
            return False
        return True

    @staticmethod
    def note_text(data):
        changes = data.get('changes')
        if not isinstance(changes, list) or not changes or not all(
                isinstance(change, str) and change.strip() for change in changes):
            raise ValueError("Invalid community release notes")
        text = '\n'.join('- ' + change for change in changes)
        if len(text.encode('utf-16-le')) // 2 > 1900:
            raise ValueError("Community release notes exceed the message limit")
        return text

    async def correct_legacy_notice(self, guild):
        """Carry the one approved correction across skipped deploys, independently of new notes."""
        key = f'community-update:{CENTRAL_GUILD_ID}:{NOTICE_CORRECTION_VERSION}'
        completed = json.loads(self.bot.store.get(key) or '{}')
        if completed.get('state') == 'sent':
            return True
        data = json.loads(CORRECTION_PATH.read_text(encoding='utf-8'))
        if data.get('schema') != 1 or data.get('version') != NOTICE_CORRECTION_VERSION:
            raise ValueError('Invalid fixed notice correction')
        text = self.note_text(data)
        saved = None
        for previous in (data.get('replaces'), data.get('replaces_fallback')):
            if previous:
                saved = self.bot.store.get(f'community-update:{CENTRAL_GUILD_ID}:{previous}')
                if saved:
                    break
        if saved is None:
            return False
        receipt = json.loads(saved)
        if receipt.get('state') != 'sent' or not receipt.get('message_id'):
            self.status = 'The previous update is awaiting confirmation; its correction will wait.'
            return True
        channel = self.update_channel(guild)
        if channel is None:
            return True
        if receipt.get('channel_id') != str(channel.id):
            self.status = 'The previous update belongs to a different channel. Check its receipt.'
            return True
        try:
            message = await channel.fetch_message(int(receipt['message_id']))
            old_header = f'Anime Adventures · Update {previous}\n\n'
            known_body = hashlib.sha256(message.content.encode('utf-8')).hexdigest() in data.get('replaces_content_sha256', [])
            if (message.author.id != self.bot.user.id or message.webhook_id
                    or not (message.content.startswith(old_header) or known_body or message.content == text)):
                self.status = 'The previous message could not be verified as the bot update.'
                return True
            if message.content != text:
                await message.edit(content=text, allowed_mentions=discord.AllowedMentions.none())
            self.bot.store.set(key, json.dumps(receipt))
            self.status = f"Current update corrected in <#{channel.id}>."
        except (discord.HTTPException, aiohttp.ClientError, TimeoutError, OSError):
            self.status = 'The previous update could not be corrected yet. Its original message was preserved.'
        return True

    async def publish_update(self):
        """Called only after Gateway readiness; never run by an offline diagnostic."""
        if self.lock.locked() or self.bot.store.clock() < self.next_attempt:
            return
        async with self.lock:
            self.next_attempt = self.bot.store.clock() + 300
            guild = self.guild()
            if guild is None:
                self.status = "The community server is unavailable to the bot."
                return
            text = self.release_note()
            if not text:
                return
            corrected = await self.correct_legacy_notice(guild)
            if corrected and self.bot.build['version'] == NOTICE_CORRECTION_VERSION:
                return
            key = f"community-update:{CENTRAL_GUILD_ID}:{self.bot.build['version']}"
            receipt = json.loads(self.bot.store.get(key) or '{}')
            if receipt.get('state') == 'sent':
                self.status = f"Current update published in <#{receipt['channel_id']}>."
                return
            if receipt.get('state') in {'sending', 'uncertain'}:
                # Always reconcile the original channel, even after a rename/move.
                channel = guild.get_channel(int(receipt['channel_id']))
                if not isinstance(channel, discord.TextChannel):
                    self.status = "An update is awaiting confirmation; its original channel is unavailable."
                    return
                try:
                    async for message in channel.history(limit=100):
                        if (message.author.id == self.bot.user.id and not message.webhook_id
                                and (str(message.nonce) == receipt['nonce']
                                     or (message.content == text
                                         and message.created_at.timestamp() >= receipt['attempted_at'] - 5))):
                            receipt.update(state='sent', message_id=str(message.id))
                            self.bot.store.set(key, json.dumps(receipt))
                            self.status = f"Current update published in <#{channel.id}>."
                            return
                except (discord.HTTPException, aiohttp.ClientError, TimeoutError, OSError):
                    pass
                self.status = "An update is awaiting confirmation; it will not be posted twice."
                return
            channel = self.update_channel(guild)
            if channel is None or not self.update_complete():
                return
            receipt = {
                'state': 'sending', 'channel_id': str(channel.id),
                'attempted_at': self.bot.store.clock(),
                'nonce': str(int(hashlib.sha256(key.encode()).hexdigest()[:15], 16)),
            }
            # Persist before awaiting Discord so a restart cannot blindly repost.
            self.bot.store.set(key, json.dumps(receipt))
            try:
                with handle_message_parameters(
                        content=text, nonce=receipt['nonce'],
                        allowed_mentions=discord.AllowedMentions.none()) as params:
                    params.payload['enforce_nonce'] = True
                    message = await self.bot.http.send_message(channel.id, params=params)
                receipt.update(state='sent', message_id=str(message['id']))
                self.status = f"Current update published in <#{channel.id}>."
            except (discord.Forbidden, discord.NotFound):
                receipt['state'] = 'blocked'
                self.status = "Discord denied the update-log publication. Check channel permissions."
            except (discord.HTTPException, aiohttp.ClientError, TimeoutError, OSError):
                receipt['state'] = 'uncertain'
                self.status = "An update is awaiting confirmation; it will not be posted twice."
            finally:
                self.bot.store.set(key, json.dumps(receipt))

    def report(self, interaction):
        self.bot.require_owner(interaction)
        self.bot.require_admin(interaction)
        if interaction.guild_id != CENTRAL_GUILD_ID:
            raise ValueError("Open this private report in the community server.")
        guild = self.guild()
        if guild is None:
            raise ValueError("The community server is temporarily unavailable. Try again after reconnection.")
        channels = []
        for channel in sorted(guild.channels, key=lambda item: (item.position, item.id)):
            permissions = channel.permissions_for(guild.me)
            everyone = channel.permissions_for(guild.default_role)
            role_overrides = []
            member_override_count = 0
            for subject, overwrite in channel.overwrites.items():
                if isinstance(subject, discord.Role):
                    allow, deny = overwrite.pair()
                    role_overrides.append({'role_id': str(subject.id), 'allow': allow.value, 'deny': deny.value})
                else:
                    member_override_count += 1
            channels.append({
                'id': str(channel.id), 'name': channel.name, 'type': str(channel.type),
                'category_id': str(channel.category_id) if channel.category_id else None,
                'position': channel.position, 'topic': getattr(channel, 'topic', None),
                'bot_permissions': {name: getattr(permissions, name) for name in REPORT_PERMISSIONS},
                'everyone_can_view': everyone.view_channel,
                'role_overrides': role_overrides,
                'member_override_count': member_override_count,
            })
        feeds = {}
        for feed in (self.bot.banners, self.bot.daily):
            target = feed.target(guild.id)
            feeds[feed.kind] = {
                'destination_id': target['channel_id'] if target else None,
                'source_status': feed.status,
                'summary': feed.private_status(guild.id),
            }
        cfg = self.bot.globalchat.store.channel(guild.id)
        report = {
            'schema': 1, 'generated_at': datetime.now(timezone.utc).isoformat(),
            'scope': 'Gateway metadata only. No message history, member list, tokens or webhooks are exported.',
            'server': {'id': str(guild.id), 'name': guild.name, 'member_count': guild.member_count,
                       'preferred_locale': str(guild.preferred_locale),
                       'rules_channel_id': str(guild.rules_channel.id) if guild.rules_channel else None},
            'bot': {'id': str(self.bot.user.id), 'version': self.bot.build['version'],
                    'files_verified': self.bot.build['verified'],
                    'permissions': guild.me.guild_permissions.value,
                    'top_role_position': guild.me.top_role.position},
            'channels': channels,
            'roles': [{'id': str(role.id), 'name': role.name, 'position': role.position,
                       'permissions': role.permissions.value, 'managed': role.managed,
                       'bot_can_assign': role < guild.me.top_role and not role.managed and not role.is_default()
                                         and guild.me.guild_permissions.manage_roles}
                      for role in guild.roles],
            'image_feeds': feeds,
            'global_chat': {'destination_id': cfg['channel_id'] if cfg else None,
                            'active': bool(cfg and cfg['active'])},
            'update_log': self.status,
        }
        blob = json.dumps(report, ensure_ascii=False, indent=2).encode('utf-8')
        return discord.File(io.BytesIO(blob), filename='community-server-report.json')
