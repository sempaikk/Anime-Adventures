"""Bounded tool workers; all notifications require an explicit user action."""

import asyncio
from datetime import datetime, timedelta, timezone as UTC
import hashlib
import io
import json
import logging
import weakref
from collections import OrderedDict

import aiohttp
import discord
from discord.http import handle_message_parameters

from adventure_store import AdventureStore, timezone
from bot_domain import safe
from bot_ui import payload

log = logging.getLogger('adventures.tools')


def quiet(settings, timestamp):
    start, end = settings.get('quiet_start'), settings.get('quiet_end')
    if start is None or end is None or start == end:
        return False
    hour = datetime.fromtimestamp(timestamp, timezone(settings.get('timezone', 'UTC'))).hour
    return start <= hour < end if start < end else hour >= start or hour < end


def parse_time(value, zone, now):
    value = value.strip()
    if value.isdecimal():
        return now + int(value) * 60
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError('Enter minutes from now, or YYYY-MM-DD HH:MM with an optional UTC offset.') from None
    if dt.tzinfo is None:
        z = timezone(zone)
        possible = [dt.replace(tzinfo=z, fold=f) for f in (0, 1)]
        valid = [v for v in possible if datetime.fromtimestamp(v.timestamp(), z).replace(tzinfo=None) == dt]
        if not valid or len({v.utcoffset() for v in valid}) > 1:
            raise ValueError('This local time is missing or ambiguous due to a clock change. Include a UTC offset, for example -03:00.')
        dt = valid[0]
    return dt.timestamp()


class AdventureService:
    def __init__(self, bot):
        self.bot = bot
        self.state = AdventureStore(bot.store)
        self.lock = asyncio.Lock()
        self.tasks = set()
        self.last_cleanup = 0
        self.last_sample = 0
        self.party_locks = weakref.WeakValueDictionary()
        self.notification_slots = asyncio.Semaphore(2)
        self.recent = OrderedDict()

    def remember(self,user,guild,kind,ident):
        key=(str(user),str(guild))
        current=self.recent.pop(key,[])
        current=[x for x in current if x['kind']!=kind or x['id']!=ident]
        self.recent[key]=[{'kind':kind,'id':ident,'time':self.state.clock()},*current][:10]
        while len(self.recent)>500:self.recent.popitem(last=False)

    def recent_for(self,user,guild):
        return [x for x in self.recent.get((str(user),str(guild)),[]) if x['time']>self.state.clock()-1800]

    def clear_recent(self,user):
        for key in list(self.recent):
            if key[0]==str(user):self.recent.pop(key,None)

    def knowledge(self):
        from game_knowledge import Knowledge
        return Knowledge()

    def normal_channel(self, channel, user=None, *, party=False):
        if not isinstance(channel, discord.TextChannel) or channel.is_nsfw() or channel.type == discord.ChannelType.news:
            raise ValueError('Choose an accessible server text channel that is not age-restricted.')
        from community_hub import CENTRAL_UPDATE_CHANNEL_ID
        forbidden = {str(CENTRAL_UPDATE_CHANNEL_ID)}
        cfg = self.bot.globalchat.store.channel(channel.guild.id)
        if cfg:
            forbidden.add(cfg['channel_id'])
        for feed in (self.bot.banners, self.bot.daily):
            target = feed.target(channel.guild.id)
            if target:
                forbidden.add(target['channel_id'])
        if str(channel.id) in forbidden:
            raise ValueError('Use a normal conversation channel, separate from feeds, global chat and official updates.')
        for member in (channel.guild.me, user):
            if member is None:
                raise ValueError('Server membership could not be confirmed.')
            p = channel.permissions_for(member)
            if not (p.view_channel and p.send_messages and p.read_message_history):
                raise ValueError('View Channel, Send Messages and Read Message History are required in this channel.')
        if party:
            settings = self.state.settings(channel.guild.id)[0]
            if str(settings.get('party_channel')) != str(channel.id):
                raise ValueError('An administrator must first select this group channel in /adventures → Server setup.')

    def party_text(self, row):
        members = self.state.members(row['id'])
        seats, waiting = members[:row['capacity']], members[row['capacity']:]
        lines = [f"## {safe(row['mode'], 60)} · group", f"Organizer: <@{row['owner']}> · starts <t:{int(row['starts'])}:F>", f"Places: {len(seats)}/{row['capacity']} · {row['state']}"]
        if row['requirements']:
            lines.append('Requirements: ' + safe(row['requirements'], 300))
        lines.append('\n'.join(f"<@{m['user']}> · {'ready' if m['ready'] else 'not ready'}" for m in seats))
        if waiting:
            lines.append('Waiting list: ' + ', '.join(f"<@{m['user']}>" for m in waiting))
        lines.append(f"Expires <t:{int(row['expires'])}:R>. Join and readiness are for this group; they do not grant Discord roles.\nGroup {row['id']}")
        return '\n\n'.join(lines)

    async def publish_party(self, ident, i):
        row = self.state.party_record(ident, i.guild_id)
        if row['owner'] != str(i.user.id):
            raise ValueError('Only the organizer can publish this group.')
        self.state.require(i.guild_id, 'parties')
        channel = self.bot.get_channel(int(row['channel']))
        self.normal_channel(channel, i.user, party=True)
        if row['state'] == 'open':
            return row
        if row['state'] != 'draft' or row['expires'] <= self.state.clock():
            raise ValueError('Publication is closed or awaiting confirmation. Refresh instead of publishing again.')
        from adventure_views import PartyView
        with self.state.db:
            claim = self.state.db.execute("UPDATE bot_tool_parties SET state='publishing',attempted=? WHERE id=? AND state='draft'", (self.state.clock(), ident))
        if claim.rowcount != 1:
            raise ValueError('Another publication is already being confirmed.')
        row = self.state.party_record(ident, i.guild_id)
        nonce = str(int(hashlib.sha256(('party:' + ident).encode()).hexdigest()[:15], 16))
        try:
            with handle_message_parameters(content=self.party_text({**row, 'state': 'open'}), view=PartyView(ident,events=self.state.enabled(i.guild_id,'events')), nonce=nonce, allowed_mentions=discord.AllowedMentions.none()) as params:
                params.payload['enforce_nonce'] = True
                result = await asyncio.wait_for(self.bot.http.send_message(channel.id, params=params), 25)
            with self.state.db:
                self.state.db.execute("UPDATE bot_tool_parties SET state=CASE WHEN state='publishing' THEN 'open' ELSE state END,message=? WHERE id=?", (str(result['id']), ident))
        except (discord.Forbidden, discord.NotFound):
            with self.state.db:
                self.state.db.execute("UPDATE bot_tool_parties SET state='draft' WHERE id=? AND state='publishing'", (ident,))
            raise ValueError('Publication was denied. Ask an administrator to check access before trying again.') from None
        except (discord.HTTPException, aiohttp.ClientError, TimeoutError, OSError):
            with self.state.db:
                self.state.db.execute("UPDATE bot_tool_parties SET state='uncertain' WHERE id=? AND state='publishing'", (ident,))
            raise ValueError('Publication confirmation is pending. The bot will check the original attempt without posting again.') from None
        return self.state.party_record(ident, i.guild_id)

    async def refresh_party(self, row):
        lock = self.party_locks.setdefault(row['id'], asyncio.Lock())
        async with lock:
            await self._refresh_party(row)

    async def _refresh_party(self, row):
        channel = self.bot.get_channel(int(row['channel']))
        if channel is None or not row['message']:
            return
        from adventure_views import PartyView
        message = await channel.fetch_message(int(row['message']))
        if message.author.id != self.bot.user.id or message.webhook_id:
            return
        current = self.state.party_record(row['id'], row['guild'])
        await message.edit(content=self.party_text(current), view=PartyView(row['id'], closed=current['state'] != 'open',events=self.state.enabled(row['guild'],'events')), allowed_mentions=discord.AllowedMentions.none())
        with self.state.db:
            self.state.db.execute('UPDATE bot_tool_parties SET rendered=?,render_after=? WHERE id=?', (current['version'], self.state.clock()+10, row['id']))

    def removed(self, *, guild=None, channel=None, message=None):
        with self.state.db:
            if guild is not None:
                self.state.db.execute("UPDATE bot_tool_parties SET state='closed',message=NULL,rendered=version+1,version=version+1 WHERE guild=?",(str(guild),))
                self.state.db.execute("UPDATE bot_tool_reminders SET state='cancelled',generation=generation+1 WHERE guild=? AND state IN ('pending','sending','uncertain')",(str(guild),))
            elif message is not None:
                self.state.db.execute("UPDATE bot_tool_parties SET state='closed',message=NULL,rendered=version+1,version=version+1 WHERE message=?",(str(message),))
            elif channel is not None:
                self.state.db.execute("UPDATE bot_tool_parties SET state='closed',message=NULL,rendered=version+1,version=version+1 WHERE channel=?",(str(channel),))

    async def reconcile_party(self, row):
        channel = self.bot.get_channel(int(row['channel']))
        if channel is None:
            return
        nonce = str(int(hashlib.sha256(('party:' + row['id']).encode()).hexdigest()[:15], 16))
        after = datetime.fromtimestamp(max(0, row['attempted'] - 5), UTC.utc)
        async for message in channel.history(limit=100, after=after, oldest_first=True):
            if message.author.id == self.bot.user.id and not message.webhook_id and (str(getattr(message, 'nonce', '')) == nonce or message.content.endswith('Group '+row['id'])):
                with self.state.db:
                    self.state.db.execute("UPDATE bot_tool_parties SET state=CASE WHEN state IN ('uncertain','publishing') THEN 'open' ELSE state END,message=? WHERE id=?", (str(message.id), row['id']))
                return

    def source_current(self,row):
        if row['purpose']!='feed' or not row['source_ref']:
            return True
        kind,_,occurrence=row['source_ref'].partition(':')
        feed=self.bot.banners if kind=='banner' else self.bot.daily
        snap=feed.diagnostics.snapshot()
        return bool(snap['received_source']) and occurrence==f"{snap['received_source']}:{snap['received_version']}" and not feed.diagnostics.obsolete(snap['received_source']) and feed.clock()-snap['received_version']<=feed.max_age

    async def deliver_reminder(self, row):
        current = self.state.one('SELECT * FROM bot_tool_reminders WHERE id=?', (row['id'],))
        if not current or current['state'] not in ('pending', 'uncertain'):
            return
        row = current
        with self.state.db:
            self.state.db.execute('UPDATE bot_tool_reminders SET next_try=? WHERE id=?', (self.state.clock()+60,row['id']))
        pref = self.state.preferences(row['user'])
        if row['state']=='pending' and not self.source_current(row):
            self.state.cancel(row['user'],row['id']);return
        if not self.state.enabled(row['guild'], 'reminders') or row['purpose'] == 'feed' and not pref['feed_alerts']:
            with self.state.db:
                self.state.db.execute("UPDATE bot_tool_reminders SET state='cancelled',error='Notifications disabled.' WHERE id=?", (row['id'],))
            return
        if quiet(pref, self.state.clock()) and row['state'] == 'pending':
            following = datetime.fromtimestamp(self.state.clock(), timezone(pref['timezone']))
            for _ in range(26):
                following += timedelta(hours=1)
                if not quiet(pref, following.timestamp()):
                    break
            with self.state.db:
                self.state.db.execute('UPDATE bot_tool_reminders SET due=? WHERE id=? AND state=\'pending\'', (following.replace(minute=0, second=0).timestamp(), row['id']))
            return
        guild = self.bot.get_guild(int(row['guild']))
        if guild is None:
            self.state.cancel(row['user'], row['id']); return
        member = guild.get_member(int(row['user']))
        if member is None:
            try:
                member = await asyncio.wait_for(guild.fetch_member(int(row['user'])), 15)
            except discord.NotFound:
                self.state.cancel(row['user'], row['id']); return
        user = self.bot.get_user(int(row['user'])) or await asyncio.wait_for(self.bot.fetch_user(int(row['user'])), 15)
        dm = user.dm_channel or await asyncio.wait_for(user.create_dm(), 15)
        if row['state'] == 'uncertain':
            after = datetime.fromtimestamp(max(0, row['attempted'] - 5), UTC.utc)
            async for message in dm.history(limit=100, after=after, oldest_first=True):
                if message.author.id == self.bot.user.id and not getattr(message,'webhook_id',None) and (str(getattr(message, 'nonce', '')) == row['nonce'] or getattr(message,'content','').endswith('Reference '+row['id']+'.')):
                    with self.state.db:
                        finished=self.state.db.execute("UPDATE bot_tool_reminders SET state='sent',message=?,error='' WHERE id=? AND state='uncertain' AND generation=?", (str(message.id), row['id'], row['generation']))
                        if finished.rowcount:
                            self.state.db.execute("UPDATE bot_tool_reminders SET state='sent',message=?,error='' WHERE bundle=? AND state='pending'",(str(message.id),row['id']))
                    return
            return  # No evidence is not permission to repeat a private notification.
        fresh = self.state.one('SELECT * FROM bot_tool_reminders WHERE id=?', (row['id'],))
        pref = self.state.preferences(row['user'])
        if fresh['state'] != 'pending' or fresh['generation'] != row['generation'] or not self.state.enabled(row['guild'],'reminders') or not self.source_current(fresh) or row['purpose'] == 'feed' and not pref['feed_alerts']:
            return
        with self.state.db:
            claimed = self.state.db.execute("UPDATE bot_tool_reminders SET state='sending',attempted=?,dm=? WHERE id=? AND state='pending' AND generation=?", (self.state.clock(), str(dm.id), row['id'], row['generation']))
        if claimed.rowcount != 1:
            return
        delay = 'This reminder was delayed while the bot was unavailable.\n' if self.state.clock() - row['due'] > 300 else ''
        children=self.state.rows("SELECT * FROM bot_tool_reminders WHERE bundle=? AND user=? AND state='pending' ORDER BY due LIMIT 6",(row['id'],row['user']))
        for child in children:
            if not self.source_current(child):self.state.cancel(child['user'],child['id'])
        children=[child for child in children if self.source_current(child)]
        details=safe(row['body'],300)+''.join('\n• '+safe(r['body'],200) for r in children)
        text = f"{delay}**Your Adventures {'reminder digest' if children else 'reminder'}**\n{details}\nScheduled <t:{int(row['due'])}:F>.\nManage reminders with /adventures in your server. Reference {row['id']}."
        try:
            with handle_message_parameters(content=text, nonce=row['nonce'], allowed_mentions=discord.AllowedMentions.none()) as params:
                params.payload['enforce_nonce'] = True
                result = await asyncio.wait_for(self.bot.http.send_message(dm.id, params=params), 20)
            with self.state.db:
                finished=self.state.db.execute("UPDATE bot_tool_reminders SET state='sent',message=?,error='' WHERE id=? AND state='sending' AND generation=?", (str(result['id']), row['id'], row['generation']))
                if finished.rowcount:
                    self.state.db.execute("UPDATE bot_tool_reminders SET state='sent',message=?,error='' WHERE bundle=? AND state='pending'",(str(result['id']),row['id']))
        except (discord.Forbidden, discord.NotFound):
            with self.state.db:
                failed=self.state.db.execute("UPDATE bot_tool_reminders SET state='blocked',error='Direct messages are unavailable. No public fallback was sent.' WHERE id=? AND state='sending'", (row['id'],))
                if failed.rowcount:
                    self.state.db.execute("UPDATE bot_tool_reminders SET state='blocked',error='Direct messages are unavailable.' WHERE bundle=? AND state='pending'",(row['id'],))
        except (discord.HTTPException, aiohttp.ClientError, TimeoutError, OSError):
            with self.state.db:
                self.state.db.execute("UPDATE bot_tool_reminders SET state='uncertain',error='Checking Discord confirmation; no blind retry.' WHERE id=? AND state='sending'", (row['id'],))

    def feed_notifications(self):
        remaining=20000-self.state.one('SELECT count(*) n FROM bot_tool_reminders')['n']
        if remaining<=0:
            return
        try:self.state.budget()
        except ValueError:return
        for feed in (self.bot.banners, self.bot.daily):
            snap = feed.diagnostics.snapshot()
            if feed.status != 'ready' or not snap['received_source'] or not snap['polled'] or feed.clock()-snap['polled']>180 or feed.clock()-snap['received_version']>feed.max_age or feed.diagnostics.obsolete(snap['received_source']) or snap['observed'] > snap['received_version'] or snap['source_message'] != snap['received_source']:
                continue
            occurrence = f"{snap['received_source']}:{snap['received_version']}"
            key = 'tool-feed-head:' + feed.kind
            previous = self.bot.store.get(key)
            if previous == occurrence:
                continue
            # First observation seeds the marker; restarting never advertises an
            # old cached image. New subscriptions also start from future events.
            with self.state.db:
                if previous:
                    for pref in self.state.rows('SELECT * FROM bot_tool_preferences WHERE feed_alerts=1 AND alert_guild IS NOT NULL LIMIT 2000'):
                        if remaining<=0:break
                        if not feed.target(pref['alert_guild']) or not self.state.enabled(pref['alert_guild'], 'reminders'):
                            continue
                        ident = hashlib.sha256(f"feed:{feed.kind}:{occurrence}:{pref['user']}".encode()).hexdigest()[:12]
                        if self.state.one('SELECT count(*) n FROM bot_tool_reminders WHERE user=? AND purpose=\'feed\' AND state IN (\'pending\',\'sending\',\'uncertain\')', (pref['user'],))['n'] >= 2:
                            continue
                        body = f"A new {feed.kind} source update was confirmed. Open /{'setbanner' if feed.kind == 'banner' else 'dailychallenge'} to check this server's delivery."
                        inserted=self.state.db.execute("INSERT OR IGNORE INTO bot_tool_reminders(id,user,guild,body,due,nonce,created,purpose,source_ref) VALUES(?,?,?,?,?,?,?,'feed',?)", (ident, pref['user'], pref['alert_guild'], body, self.state.clock(), str(int(ident, 16)), self.state.clock(),feed.kind+':'+occurrence))
                        remaining-=inserted.rowcount
                self.state.db.execute('INSERT OR REPLACE INTO bot_meta VALUES(?,?)', (key, occurrence))

    async def cycle(self):
        if self.lock.locked():
            return
        async with self.lock:
            if self.state.clock() - self.last_cleanup > 300:
                self.state.cleanup(); self.last_cleanup = self.state.clock()
            self.feed_notifications()
            self.state.bundle_due()
            rows = self.state.rows("SELECT * FROM bot_tool_reminders WHERE state IN ('pending','uncertain') AND bundle IS NULL AND due<=? AND next_try<=? ORDER BY due LIMIT 4", (self.state.clock(),self.state.clock()))
            async def notify(row):
                try:
                    async with self.notification_slots:
                        await self.deliver_reminder(row)
                except (discord.HTTPException, aiohttp.ClientError, TimeoutError, OSError):
                    with self.state.db:
                        self.state.db.execute('UPDATE bot_tool_reminders SET next_try=? WHERE id=? AND state IN (\'pending\',\'uncertain\')', (self.state.clock()+300, row['id']))
            # Tiny persistent batches and two workers, independent of the feeds.
            await asyncio.gather(*(notify(row) for row in rows))
            for row in self.state.rows("SELECT * FROM bot_tool_parties WHERE state IN ('publishing','uncertain') OR (state='closed' AND attempted>0 AND message IS NULL) ORDER BY attempted LIMIT 2"):
                try:
                    await asyncio.wait_for(self.reconcile_party(row), 15)
                except (discord.HTTPException, aiohttp.ClientError, TimeoutError, OSError):
                    pass
            for row in self.state.rows('SELECT * FROM bot_tool_parties WHERE message IS NOT NULL AND version>rendered AND render_after<=? ORDER BY render_after LIMIT 2', (self.state.clock(),)):
                try:
                    await asyncio.wait_for(self.refresh_party(row), 15)
                except discord.NotFound:
                    with self.state.db:
                        self.state.db.execute("UPDATE bot_tool_parties SET state='closed',message=NULL WHERE id=?", (row['id'],))
                except (discord.HTTPException, aiohttp.ClientError, TimeoutError, OSError):
                    with self.state.db:
                        self.state.db.execute('UPDATE bot_tool_parties SET render_after=? WHERE id=?', (self.state.clock()+300,row['id']))
            for row in self.state.rows("SELECT * FROM bot_tool_parties WHERE state IN ('closed','expired') AND event IS NOT NULL AND event_done=0 AND event_retry<=? ORDER BY event_retry LIMIT 2",(self.state.clock(),)):
                guild=self.bot.get_guild(int(row['guild']))
                if guild is None:continue
                try:
                    events=list(getattr(guild,'scheduled_events',[]))
                    event=next((e for e in events if str(e.id)==row['event']),None)
                    if event is None and str(row['event']).isdigit():
                        event=await asyncio.wait_for(guild.fetch_scheduled_event(int(row['event'])),15)
                    if event is None and row['event']=='pending':
                        event=next((e for e in events if e.creator_id==self.bot.user.id and ('Group '+row['id']) in (e.description or '')),None)
                    if event and event.creator_id==self.bot.user.id:
                        if event.status==discord.EventStatus.scheduled:
                            await asyncio.wait_for(event.edit(status=discord.EventStatus.cancelled,reason='The organizer closed this Adventures group or it expired'),15)
                        elif event.status==discord.EventStatus.active:
                            await asyncio.wait_for(event.edit(status=discord.EventStatus.completed,reason='The Adventures group closed'),15)
                        with self.state.db:self.state.db.execute('UPDATE bot_tool_parties SET event_done=1 WHERE id=?',(row['id'],))
                except discord.NotFound:
                    with self.state.db:self.state.db.execute('UPDATE bot_tool_parties SET event_done=1 WHERE id=?',(row['id'],))
                except (discord.HTTPException,aiohttp.ClientError,TimeoutError,OSError):
                    pass
                finally:
                    with self.state.db:self.state.db.execute('UPDATE bot_tool_parties SET event_retry=? WHERE id=?',(self.state.clock()+300,row['id']))
            if self.state.clock() - self.last_sample > 300:
                self.state.record('health', {'global': self.bot.globalchat.operations.snapshot(), 'banner': self.bot.banners.diagnostics.network_summary(), 'daily': self.bot.daily.diagnostics.network_summary()})
                self.last_sample = self.state.clock()

    def operations(self):
        rows = self.state.rows('SELECT kind,detail,created FROM bot_tool_events ORDER BY id DESC LIMIT 6')
        text = '## Optional tools · private operations\n'
        text += '\n'.join(f"<t:{int(r['created'])}:R> · {safe(r['kind'])}\n{safe(r['detail'], 350)}" for r in rows) or 'No recent samples.'
        text += '\n\nPending external prerequisites: current official code verification; trusted character metadata for banner alerts; actual game integration for AA inventory; external backup destination; public monitor URL; App Directory eligibility. None is assumed configured.'
        return text
