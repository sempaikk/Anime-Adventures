"""Scoped private answers, appeals and short-lived screenshots for existing cases."""

import io
import re
import warnings

import discord
from PIL import Image

from bot_domain import safe
from bot_views import BoundModal, reply
from community_hub import CENTRAL_GUILD_ID

MAX_SCREENSHOT = 2 * 1024 * 1024


def case(bot, i, kind, ident, *, staff=False):
    if kind not in ('report', 'feedback') or not str(ident).isdigit():
        raise ValueError('Choose Report or Feedback and enter its numeric reference.')
    if kind == 'feedback':
        if i.guild_id != CENTRAL_GUILD_ID:
            raise ValueError('Feedback is available only in the official community.')
        if staff:
            bot.require_owner(i)
        row = bot.store.rows('SELECT id,user_id AS user,created FROM bot_feedback WHERE id=?', (int(ident),))
    else:
        if staff:
            from bot_permissions import require_moderator
            require_moderator(i)
        row = bot.store.rows('SELECT id,reporter AS user,created FROM global_reports WHERE id=? AND guild_id=?', (int(ident), str(i.guild_id)))
    if not row or row[0]['created'] < bot.store.clock() - 30 * 86400 or not staff and row[0]['user'] != str(i.user.id):
        raise ValueError('This recent case is not available to you in this server.')
    return row[0]


def followup(bot, guild, kind, ident):
    return bot.adventures.state.one('SELECT * FROM bot_case_followup WHERE kind=? AND case_id=? AND guild=?', (kind, int(ident), str(guild)))


class CaseForm(BoundModal):
    def __init__(self, bot, i):
        super().__init__(title='My case')
        self.bind(bot, i)
        self.kind = discord.ui.Select(options=[discord.SelectOption(label='Report', value='report')] + ([discord.SelectOption(label='Feedback', value='feedback')] if i.guild_id == CENTRAL_GUILD_ID else []))
        self.reference = discord.ui.TextInput(max_length=20)
        self.action = discord.ui.Select(options=[discord.SelectOption(label='Read response', value='read'), discord.SelectOption(label='Request review', value='appeal'), discord.SelectOption(label='Attach screenshot', value='image')])
        self.body = discord.ui.TextInput(style=discord.TextStyle.paragraph, required=False, max_length=500)
        self.image = discord.ui.FileUpload(required=False, min_values=0, max_values=1)
        self.add_item(discord.ui.Label(text='Case type', component=self.kind))
        self.add_item(discord.ui.Label(text='Numeric case reference', component=self.reference))
        self.add_item(discord.ui.Label(text='Action', component=self.action))
        self.add_item(discord.ui.Label(text='Review reason, when requested', component=self.body))
        self.add_item(discord.ui.Label(text='Optional screenshot', description='PNG/JPEG/WebP, up to 2 MiB and 4 megapixels. Private to authorized reviewers; deleted within 24 hours. Do not include secrets.', component=self.image))

    async def on_submit(self, i):
        if not await self.interaction_check(i):
            return
        kind, ident = self.kind.values[0], str(self.reference).strip()
        case(self.bot, i, kind, ident)
        state = self.bot.adventures.state
        old = followup(self.bot, i.guild_id, kind, ident)
        action = self.action.values[0]
        if action == 'read':
            text = old['answer'] if old else ''
            await reply(i, '## Private case response\n' + (safe(text, 1500) if text else 'No written response yet. Your case status remains available in My requests.'))
            return
        if action == 'appeal':
            body = str(self.body).strip()
            if not 10 <= len(body) <= 500:
                raise ValueError('Explain the request for review in 10 to 500 characters.')
            if old and old['appeal']:
                raise ValueError('A review request is already recorded for this case.')
            with state.db:
                state.budget()
                state.db.execute('INSERT INTO bot_case_followup(kind,case_id,guild,appeal,updated) VALUES(?,?,?,?,?) ON CONFLICT(kind,case_id,guild) DO UPDATE SET appeal=excluded.appeal,version=version+1,updated=excluded.updated WHERE appeal=\'\'', (kind, int(ident), str(i.guild_id), body, state.clock()))
            await reply(i, 'Your request for review was attached privately to this case. It does not change the moderation decision automatically.')
            return
        if action != 'image' or not self.image.values:
            raise ValueError('Choose a screenshot to attach.')
        attachment = self.image.values[0]
        from global_media import cdn_url
        if attachment.size > MAX_SCREENSHOT or not cdn_url(attachment.url):
            raise ValueError('Use a Discord-uploaded screenshot up to 2 MiB.')
        await i.response.defer(ephemeral=True, thinking=True)
        async with self.bot.instance_storage.reserve(MAX_SCREENSHOT, memory=20*1024*1024, feature='global'):
            if state.one('SELECT COALESCE(sum(length(image)),0) n FROM bot_case_followup')['n'] + attachment.size > 8 * 1024 * 1024:
                raise ValueError('Private screenshot storage is full. Try again after older attachments expire.')
            session = await self.bot.globalchat.http_session()
            async with session.get(attachment.url, allow_redirects=False) as response:
                if response.status != 200:
                    raise ValueError('The screenshot could not be downloaded.')
                data = bytearray()
                async for part in response.content.iter_chunked(65536):
                    data.extend(part)
                    if len(data) > MAX_SCREENSHOT:
                        raise ValueError('The screenshot exceeds the 2 MiB limit.')
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter('error', Image.DecompressionBombWarning)
                    with Image.open(io.BytesIO(data)) as image:
                        if image.format not in ('PNG', 'JPEG', 'WEBP') or getattr(image, 'is_animated', False) or image.width * image.height > 4_000_000:
                            raise ValueError('Use a static PNG/JPEG/WebP screenshot up to 4 megapixels.')
                        extension = {'PNG': 'png', 'JPEG': 'jpg', 'WEBP': 'webp'}[image.format]
                        image.verify()
            except (OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
                raise ValueError('The image could not be validated as a screenshot.') from None
            case(self.bot, i, kind, ident)  # Access may have changed during download.
            with state.db:
                state.budget()
                current_image = followup(self.bot, i.guild_id, kind, ident)
                previous_bytes = len(current_image['image']) if current_image and current_image['image'] else 0
                if state.one('SELECT COALESCE(sum(length(image)),0) n FROM bot_case_followup')['n'] - previous_bytes + len(data) > 8*1024*1024:
                    raise ValueError('Private screenshot storage is full. Older screenshots must expire first.')
                state.db.execute('INSERT INTO bot_case_followup(kind,case_id,guild,image,image_type,image_expires,updated) VALUES(?,?,?,?,?,?,?) ON CONFLICT(kind,case_id,guild) DO UPDATE SET image=excluded.image,image_type=excluded.image_type,image_expires=excluded.image_expires,updated=excluded.updated,version=version+1', (kind, int(ident), str(i.guild_id), bytes(data), extension, state.clock()+86400, state.clock()))
        await reply(i, 'The screenshot was attached privately for up to 24 hours. Nothing was posted in a public channel.')


class CaseReview(BoundModal):
    def __init__(self, bot, i, kind, ident):
        super().__init__(title='Case follow-up')
        self.bind(bot, i)
        case(bot, i, kind, ident, staff=True)
        self.kind, self.ident = kind, ident
        old = followup(bot, i.guild_id, kind, ident)
        self.version = old['version'] if old else 0
        self.action = discord.ui.Select(options=[discord.SelectOption(label='Assign to me', value='claim'), discord.SelectOption(label='Answer requester', value='answer'), discord.SelectOption(label='View review request', value='appeal'), discord.SelectOption(label='View screenshot', value='image')])
        self.body = discord.ui.TextInput(style=discord.TextStyle.paragraph, required=False, max_length=1200)
        self.add_item(discord.ui.Label(text='Action', component=self.action))
        self.add_item(discord.ui.Label(text='Response visible to the requester', description='Do not include internal reviewer notes or other people\'s data.', component=self.body))

    async def on_submit(self, i):
        if not await self.interaction_check(i):
            return
        case(self.bot, i, self.kind, self.ident, staff=True)
        state = self.bot.adventures.state
        old = followup(self.bot, i.guild_id, self.kind, self.ident)
        action = self.action.values[0]
        if action == 'appeal':
            await reply(i, '## Request for review\n' + safe(old['appeal'] if old and old['appeal'] else 'None recorded.', 600)); return
        if action == 'image':
            if not old or not old['image'] or old['image_expires'] <= state.clock():
                raise ValueError('No current screenshot is available.')
            file = discord.File(io.BytesIO(old['image']), filename='case-screenshot.' + old['image_type'])
            try:
                await reply(i, 'Private case screenshot; do not redistribute unrelated personal data.', file=file)
            finally:
                file.close()
            return
        if action not in ('claim', 'answer'):
            raise ValueError('Choose a case action.')
        if (old['version'] if old else 0) != self.version:
            raise ValueError('This case changed. Reopen its follow-up before deciding.')
        if old and old['assigned'] and old['assigned'] != str(i.user.id):
            raise ValueError('Another reviewer has already assumed this case.')
        body = str(self.body).strip()
        if action == 'answer' and not 5 <= len(body) <= 1200:
            raise ValueError('Write a response in 5 to 1200 characters.')
        with state.db:
            state.budget()
            state.db.execute('INSERT INTO bot_case_followup(kind,case_id,guild,assigned,answer,updated) VALUES(?,?,?,?,?,?) ON CONFLICT(kind,case_id,guild) DO UPDATE SET assigned=excluded.assigned,answer=CASE WHEN ? THEN excluded.answer ELSE answer END,updated=excluded.updated,version=version+1', (self.kind, self.ident, str(i.guild_id), str(i.user.id), body if action == 'answer' else '', state.clock(), int(action == 'answer')))
        await reply(i, 'Case assigned to you.' if action == 'claim' else 'Your response is available privately in the requester\'s My requests. No DM was sent.')
