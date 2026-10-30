"""Private, scoped report inbox with review history and deliberate moderation actions."""

import json
import discord
from global_views import ScopedView
from global_moderation import REPORT_STATES
from bot_views import BoundModal, reply
from bot_ui import edit_response
from bot_domain import safe


class ReportInbox(ScopedView):
    def __init__(self, bot, i, *, network=False):
        super().__init__(bot, i, moderator=True, owner=network)
        self.scope = None if network else i.guild_id
        self.page = 0
        self.status = "pending"
        self.selected = None
        self.rows = []
        self.total = 0
        self.refresh()

    def refresh(self):
        self.rows, self.total, self.page = self.bot.globalchat.store.report_page(
            self.scope, self.status, self.page
        )
        ids = {r["id"] for r in self.rows}
        if self.selected not in ids:
            self.selected = self.rows[0]["id"] if self.rows else None
        self.previous.disabled = self.page == 0
        self.next.disabled = (self.page + 1) * 5 >= self.total
        self.choose.disabled = not self.rows
        self.review.disabled = not self.rows
        self.choose.options = [
            discord.SelectOption(
                label=f"Report #{r['id']} · {REPORT_STATES[r['status']]}",
                value=str(r["id"]),
                description=r["reason"][:90],
                default=r["id"] == self.selected,
            )
            for r in self.rows
        ] or [discord.SelectOption(label='No reports', value="0")]
        for option in self.filter.options:
            option.default = option.value == self.status

    def description(self):
        self.refresh()
        title = (
            'Network reports' if self.scope is None else 'Server reports'
        )
        text = (
            f'## {title}\n**Page {self.page + 1}/{max(1, (self.total + 4) // 5)} · {self.total} report(s).**\nSelect a report and provide a reason for your decision. Actions in this panel apply '
            + (
                'across the network.'
                if self.scope is None
                else 'only to this server.'
            )
        )
        row = next((r for r in self.rows if r["id"] == self.selected), None)
        if not row:
            return text + '\n\nThere are no reports matching this filter.'
        text += f"\n\n### #{row['id']} · {REPORT_STATES[row['status']]}\n**Submitted reason:** {safe(row['reason'], 500)}"
        source = self.bot.globalchat.store.message(row["source_id"])
        cfg = self.bot.globalchat.store.channel(row["guild_id"])
        if source and cfg:
            channel = self.bot.globalchat.channel(cfg["channel_id"])
            # A guild manager need not have access to every private channel.
            member = channel.guild.get_member(self.actor) if channel else None
            permissions = (
                channel.permissions_for(member) if channel and member else None
            )
            can_read = bool(
                permissions
                and permissions.view_channel
                and permissions.read_message_history
            )
            if can_read:
                body = json.loads(source["payload"]).get("body")
                if body:
                    text += '\n**Excerpt available in cache:** ' + safe(body, 300)
                delivery = self.bot.globalchat.store.delivery(
                    source["id"], cfg["channel_id"]
                )
                ids = json.loads(delivery["receipts"]) if delivery else []
                ident = (
                    source["id"]
                    if source["channel_id"] == cfg["channel_id"]
                    else next((x for x in ids if x), None)
                )
                if ident:
                    text += f"\n[Open the message in this server](https://discord.com/channels/{cfg['guild_id']}/{cfg['channel_id']}/{ident})"
            if self.scope is None:
                text += f"\n**Internal source:** server {source['guild_id']} · user {source['user_id']}."
        text += '\n-# Deleted or expired content may be unavailable; reports do not keep a permanent copy of the conversation.'
        if row["resolution"]:
            text += f"\n**Last review:** {safe(row['resolution'], 500)}\n**Reviewer:** {row['actor']} · <t:{int(row['updated'])}:R>."
        return text

    @discord.ui.button(label='Previous', row=0)
    async def previous(self, i, button):
        self.require(i)
        self.page = max(0, self.page - 1)
        await edit_response(i, content=self.description(), view=self)

    @discord.ui.button(label='Next', row=0)
    async def next(self, i, button):
        self.require(i)
        self.page += 1
        await edit_response(i, content=self.description(), view=self)

    @discord.ui.button(label='Refresh', row=0)
    async def reload(self, i, button):
        self.require(i)
        await edit_response(i, content=self.description(), view=self)

    @discord.ui.select(
        placeholder='Report status',
        options=[
            discord.SelectOption(label=v, value=k)
            for k, v in (*REPORT_STATES.items(), ("all", 'All'))
        ],
        row=1,
    )
    async def filter(self, i, select):
        self.require(i)
        self.status = select.values[0]
        self.page = 0
        await edit_response(i, content=self.description(), view=self)

    @discord.ui.select(
        placeholder='Select a report',
        options=[discord.SelectOption(label='Loading', value="0")],
        row=2,
    )
    async def choose(self, i, select):
        self.require(i)
        selected = int(select.values[0])
        if selected not in {r["id"] for r in self.rows}:
            raise ValueError('Select a report from this page.')
        self.selected = selected
        await edit_response(i, content=self.description(), view=self)

    @discord.ui.button(
        label='Review a report', style=discord.ButtonStyle.primary, row=3
    )
    async def review(self, i, button):
        self.require(i)
        row = self.bot.globalchat.store.report_record(self.selected, self.scope)
        await i.response.send_modal(ReportDecision(self.bot, i, row, self.scope))


class ReportDecision(BoundModal):
    def __init__(self, bot, i, row, scope):
        super().__init__(title=f"Review report #{row['id']}")
        self.bind(bot, i)
        self.ident, self.version, self.scope = row["id"], row["version"], scope
        self.action = discord.ui.Select(
            options=[
                discord.SelectOption(label='Resolve without action', value="resolve"),
                discord.SelectOption(label='Dismiss report', value="dismiss"),
                discord.SelectOption(label='Reopen review', value="reopen"),
                discord.SelectOption(
                    label='Block user for one hour', value="block-hour"
                ),
                discord.SelectOption(label='Restrict user for 15 minutes',value='block-quarter'),
                discord.SelectOption(label='Restrict user for one day',value='block-day'),
                discord.SelectOption(
                    label='Request copy removal', value="remove"
                ),
            ]
        )
        self.reason = discord.ui.TextInput(
            style=discord.TextStyle.paragraph, min_length=5, max_length=500
        )
        self.add_item(
            discord.ui.Label(
                text='Action',
                description='Scope: '
                + ('entire network' if scope is None else 'this server only'),
                component=self.action,
            )
        )
        self.add_item(discord.ui.Label(text='Reason for the decision', component=self.reason))

    async def on_submit(self, i):
        if not await self.interaction_check(i):
            return
        from bot_permissions import require_moderator
        require_moderator(i)
        if self.scope is None:
            self.bot.require_owner(i)
        elif self.scope != i.guild_id:
            raise ValueError('This review belongs to another server.')
        action = self.action.values[0]
        state = self.bot.globalchat.store.review_report(
            self.ident, self.scope, i.user.id, self.version, action, str(self.reason)
        )
        message = f'**Report #{self.ident}: {REPORT_STATES[state]}.** The decision and reviewer were recorded.'
        if action == "remove":
            message += ' Removal of accessible copies was requested; the original remains with its author.'
        if action == "block-hour":
            message += ' The restriction expires in one hour.'
        await reply(i, message + ' Use Refresh in the list to check progress.')
