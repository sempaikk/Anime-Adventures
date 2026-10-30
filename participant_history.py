"""Scoped follow-up and small-screen selections within the existing commands."""

import json
import discord

from bot_domain import safe
from bot_views import reply
from bot_ui import edit_response
from global_views import ScopedView, MessageAction
from community_hub import CENTRAL_GUILD_ID


class RequestHistory(ScopedView):
    def __init__(self, bot, i):
        super().__init__(bot, i)
        self.page = 0

    def description(self):
        now = self.bot.globalchat.store.clock()
        query='''SELECT r.created AS created,'Report' AS kind,r.id AS id,
            COALESCE(a.status,CASE WHEN r.reviewed=1 THEN 'resolved' ELSE 'pending' END) AS status
            FROM global_reports r LEFT JOIN global_report_actions a ON a.report_id=r.id
            WHERE r.reporter=? AND r.guild_id=? AND r.created>?'''
        args=(str(self.actor),str(self.guild),now-30*86400)
        if self.guild == CENTRAL_GUILD_ID:
            query+=" UNION ALL SELECT created,'Feedback',id,status FROM bot_feedback WHERE user_id=? AND created>?"
            args+=(str(self.actor),now-30*86400)
        count=self.bot.globalchat.store.one('SELECT count(*) n FROM ('+query+')',args)['n']
        self.page = max(0, min(self.page, max(0, (count-1)//5)))
        rows=self.bot.globalchat.store.rows(query+' ORDER BY created DESC,id DESC LIMIT 5 OFFSET ?',(*args,self.page*5))
        self.previous.disabled = not self.page
        self.next.disabled = (self.page+1)*5 >= count
        return (f'## My requests · page {self.page+1}\nYour reports from this server; community feedback appears only in the official community. Retained for up to 30 days.\n'
            + ('\n'.join(f'\n**{r["kind"]} #{r["id"]}: {r["status"]}** · <t:{int(r["created"])}:R>' for r in rows) or '\nNo recent requests.'))

    @discord.ui.button(label='Previous', row=0)
    async def previous(self, i, button):
        self.require(i)
        self.page -= 1
        await edit_response(i, content=self.description(), view=self)

    @discord.ui.button(label='Next', row=0)
    async def next(self, i, button):
        self.require(i)
        self.page += 1
        await edit_response(i, content=self.description(), view=self)

    @discord.ui.button(label='Refresh', row=0)
    async def refresh(self, i, button):
        self.require(i)
        await edit_response(i, content=self.description(), view=self)


class RecentReport(ScopedView):
    def __init__(self, bot, i):
        super().__init__(bot, i)
        self.check_channel(i)
        self.options = {}
        rows = bot.globalchat.store.rows('''SELECT m.* FROM global_messages m WHERE m.deleted=0 AND m.expires>?
            AND (m.channel_id=? OR EXISTS(SELECT 1 FROM global_receipts r WHERE r.source_id=m.id AND r.channel_id=?))
            ORDER BY m.created DESC LIMIT 10''', (bot.store.clock(), str(self.channel), str(self.channel)))
        options = []
        for row in rows:
            receipt = bot.globalchat.store.one('SELECT message_id FROM global_receipts WHERE source_id=? AND channel_id=? LIMIT 1', (row['id'], str(self.channel)))
            ident = row['id'] if row['channel_id'] == str(self.channel) else receipt['message_id']
            self.options[ident] = row['id']
            excerpt = json.loads(row['payload']).get('body') or 'Attachment / content no longer cached'
            options.append(discord.SelectOption(label='Message '+ident, value=ident, description=safe(excerpt, 80)))
        self.choose.options = options or [discord.SelectOption(label='No recent messages', value='0')]
        self.choose.disabled = not options

    def check_channel(self, i):
        cfg = self.bot.globalchat.store.channel(i.guild_id)
        p = i.channel.permissions_for(i.user)
        if not cfg or cfg['channel_id'] != str(i.channel_id) or not p.view_channel or not p.read_message_history:
            raise ValueError('Open this selection in the configured global channel with access to its history.')

    def description(self):
        return '## Choose a message to report\nSelect one of the latest shared messages in this channel, then describe the issue privately. You can also use Report to paste a link.'

    @discord.ui.select(placeholder='Recent shared messages', options=[discord.SelectOption(label='Loading', value='0')])
    async def choose(self, i, select):
        self.require(i)
        self.check_channel(i)
        value = select.values[0]
        if value not in self.options:
            raise ValueError('Reopen the recent-message selection.')
        form = MessageAction(self.bot, i, 'report')
        form.link.default = value
        await i.response.send_modal(form)


class RestrictionView(ScopedView):
    def __init__(self, bot, i, *, network):
        super().__init__(bot, i, moderator=True, owner=network)
        self.scope = '*' if network else str(i.guild_id)
        self.page = 0
        self.selected = None
        self.records = []

    def description(self):
        store = self.bot.globalchat.store
        rows = store.rows('''SELECT kind,target,until FROM global_restrictions WHERE scope=? AND until>?
            UNION ALL SELECT kind,target,0 AS until FROM global_blocks WHERE scope=? ORDER BY kind,target''', (self.scope, store.clock(), self.scope))
        # Permanent and temporary restrictions on the same target are released together.
        unique = {(r['kind'], r['target']): r for r in rows}
        rows = list(unique.values())
        self.page = max(0, min(self.page, max(0, (len(rows)-1)//5)))
        self.records = rows[self.page*5:self.page*5+5]
        self.previous.disabled = not self.page
        self.next.disabled = (self.page+1)*5 >= len(rows)
        self.choose.options = [discord.SelectOption(label=r['kind'].title()+' '+r['target'], value=r['kind']+':'+r['target']) for r in self.records] or [discord.SelectOption(label='No restrictions', value='0')]
        self.choose.disabled = not self.records
        text = f'## Restrictions · page {self.page+1}\nScope: '+('entire network' if self.scope == '*' else 'this server only')+'. Select a target to review a release.\n'
        for r in self.records:
            text += '\n**'+r['kind'].title()+' '+r['target']+'** · '+(f'until <t:{int(r["until"])}:R>' if r['until'] else 'until manually released')
        return text if rows else text+'\nNo active restrictions.'

    @discord.ui.button(label='Previous', row=0)
    async def previous(self, i, button):
        self.require(i)
        self.page -= 1
        await edit_response(i, content=self.description(), view=self)

    @discord.ui.button(label='Next', row=0)
    async def next(self, i, button):
        self.require(i)
        self.page += 1
        await edit_response(i, content=self.description(), view=self)

    @discord.ui.select(placeholder='Choose a restriction', options=[discord.SelectOption(label='Loading', value='0')], row=1)
    async def choose(self, i, select):
        self.require(i)
        value = select.values[0]
        if value not in {r['kind']+':'+r['target'] for r in self.records}:
            raise ValueError('Refresh the restriction list.')
        from global_views import ModerationModal
        form = ModerationModal(self.bot, i, network=self.scope == '*')
        kind, target = value.split(':')
        for option in form.action.options:
            option.default = option.value == 'unblock-'+kind
        form.target.default = target
        store=self.bot.globalchat.store
        form.expected_restriction=store.rows('SELECT * FROM global_restrictions WHERE scope=? AND kind=? AND target=? AND until>?',
            (self.scope,kind,target,store.clock()))+store.rows('SELECT * FROM global_blocks WHERE scope=? AND kind=? AND target=?',(self.scope,kind,target))
        await i.response.send_modal(form)
