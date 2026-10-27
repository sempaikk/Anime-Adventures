"""Native Discord cards for setup and one account-wide, persistent participation choice."""

import json
import re

import discord

from tier_views import GuardedView, BoundModal, reply
from tier_ui import payload
from tier_domain import safe

TERMS = "## Before joining\n**Messages you write in global channels will be shared with every server connected to this bot's network, including servers that join later.** This may grow to many or thousands of servers. People in those servers can read your messages and see your display name, avatar and attachments. The bot does not add your @username or server name to the name on copies.\n\n**Your choice applies across the network.** Confirm once per account. You do not need to confirm again in another participating server. Your choice remains saved after bot restarts.\n\n**Write normally.** Original messages stay in their source server. Copies are published through webhooks with Discord's application label. Only global channels enabled by administrators share messages. This does not authorize sharing other channels or private messages.\n\n**You stay in control.** Choose Leave to stop sharing new messages. Editing or deleting an original synchronizes its copies for up to 30 days while the channels remain accessible. People may have seen or saved content before removal. Temporary message text and files are cleaned up within one hour, with periodic checks. Synchronization IDs and reports are kept for up to 30 days. Your confirmation stays saved until you leave.\n\nBy choosing **Confirm and join**, you agree to this sharing. New messages you write in connected global channels will be distributed automatically."

HELP = "## How global chat works\n**One conversation across servers.** Write in this channel. Your original stays in its server; other servers receive copies with your display name and avatar, without an added @username or server name. Owner and Tester labels are reserved for authorized accounts. Discord adds its application/bot label to webhook copies.\n\n**Confirm once.** Your choice applies throughout this network and survives restarts. Leave stops new sharing. The first invitation arrives by DM, without repeated public notices. Messages written before confirmation are not shared. If your DMs are closed, open `/globalchat` in the global channel to confirm privately.\n\n**Text and replies.** Normal Discord formatting is preserved; long messages may be split. Replies to known network messages include a quote. Forwarded mentions do not notify users, roles or everyone.\n\n**Attachments.** Global chat supports images, GIFs, videos, audio, PDF and TXT. Upload limits vary by server. A destination that cannot accept a file receives a size notice instead of an incomplete attachment. Compatible stickers become image files; other formats are identified by name. Custom emoji rendering depends on Discord permissions and availability. These global chat attachment rules are separate from the static-image-only banner and daily challenge feeds.\n\n**Edit and delete.** Use the original Discord message. The bot follows changes for up to 30 days and gradually checks deletions made during disconnections. My messages also lets you request removal of your network copies. Copies removed by local moderation are not recreated. Missing access can prevent synchronization to a destination.\n\n**Local features.** Reactions, native poll votes, calls, screen sharing and typing indicators remain local. Discord channels cannot be merged natively.\n\n**Community rules.** Do not share scams, harassment, threats, sexual content, other people's personal information or mass advertising. Occasional links are allowed; disguised destinations and coordinated bursts may be restricted temporarily. Spam, unsupported files and insufficient resources can prevent sharing; the original is preserved. Administrators moderate their server; the bot owner moderates the network. Reports and personal controls are private."


POLICY_LINKS = (
    '\n\n[Terms of Service](https://www.adventureswiki.workers.dev/bot/termos/) · [Privacy Policy](https://www.adventureswiki.workers.dev/bot/privacidade/)\nSupport and data requests: estrmozica@gmail.com.'
)
TERMS += POLICY_LINKS
HELP += POLICY_LINKS


class ScopedView(GuardedView):
    def __init__(self, bot, i, *, admin=False, owner=False):
        super().__init__(timeout=600)
        self.bot, self.actor, self.guild, self.channel = (
            bot,
            i.user.id,
            i.guild_id,
            i.channel_id,
        )
        self.admin, self.owner = admin, owner

    def require(self, i):
        if (i.user.id, i.guild_id, i.channel_id) != (
            self.actor,
            self.guild,
            self.channel,
        ):
            raise ValueError('Open your own global chat controls.')
        if self.admin:
            self.bot.require_admin(i)
        if self.owner:
            self.bot.require_owner(i)

    async def interaction_check(self, i):
        try:
            self.require(i)
        except ValueError as error:
            await reply(i, str(error))
            return False
        return True


class GlobalPanelView(GuardedView):
    """Retire old public buttons safely until their notices have been removed."""

    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot
        for name, label in (
            ("join", 'Join'),
            ("mine", 'My messages'),
            ("help", 'How it works'),
            ("report", 'Report'),
            ("leave", 'Leave'),
        ):
            button = discord.ui.Button(label=label, custom_id="global:v1:" + name)
            button.callback = self.redirect
            self.add_item(button)

    async def redirect(self, i):
        await reply(
            i,
            'Controls are now private. Open `/globalchat` in this channel to join or check your messages.',
        )


class GlobalMemberView(ScopedView):
    def current(self, i):
        self.require(i)
        cfg = self.bot.globalchat.store.channel(i.guild_id)
        if not cfg or cfg["channel_id"] != str(i.channel_id):
            raise ValueError("Open /globalchat in the server's current global channel.")
        self.bot.require_human(i)
        return cfg

    def description(self):
        participating = self.bot.globalchat.store.consented(self.actor)
        cfg = self.bot.globalchat.store.channel(self.guild)
        held = self.bot.globalchat.store.restriction(self.actor, self.guild)
        paused = self.bot.globalchat.store.network_paused() or (
            cfg and not cfg["active"]
        )
        state = (
            '**You have joined the network.** Write normally in the global channel.'
            if participating
            else '**You have not joined yet.** Choose Join to confirm sharing. Your messages stay in this server until you accept.'
        )
        if paused:
            state = (
                '**Connection paused.** New messages stay local until the connection resumes. '
                + (
                    'Your confirmation is still saved.'
                    if participating
                    else 'You have not confirmed participation yet.'
                )
            )
        elif held:
            state = f"**Sharing is temporarily restricted until <t:{int(held['until'])}:t>.** You can check your messages or contact an administrator."
        elif self.bot.globalchat.store.blocked(self.actor, self.guild):
            state = '**Your participation in this chat is blocked.** Contact a server administrator or the bot owner.'
        return (
            '## Global chat · my controls\n'
            + state
            + '\n\nYour confirmation applies to every connected server. Use the buttons below to check your messages, read the rules or stop sharing.\n-# This panel is private. Only administrators can configure the server connection.'
        )

    @discord.ui.button(label='Join', style=discord.ButtonStyle.success, row=0)
    async def join(self, i, button):
        cfg = self.current(i)
        if not cfg["active"]:
            raise ValueError(
                "This server's connection is paused. Please wait for its administrators."
            )
        if self.bot.globalchat.store.blocked(i.user.id, i.guild_id):
            raise ValueError('Your participation in this chat is blocked.')
        if self.bot.globalchat.store.consented(i.user.id):
            await reply(
                i,
                '**You have already joined the network.** Your confirmation remains saved across all servers.',
            )
            return
        await reply(i, TERMS, view=ConsentView(self.bot, i, cfg))

    @discord.ui.button(label='My messages', row=0)
    async def mine(self, i, button):
        self.current(i)
        view = MyMessagesView(self.bot, i)
        await reply(i, view.description(), view=view)

    @discord.ui.button(label='How it works', row=0)
    async def help(self, i, button):
        self.current(i)
        await reply(i, HELP)

    @discord.ui.button(label='Report', row=1)
    async def report(self, i, button):
        self.current(i)
        await i.response.send_modal(MessageAction(self.bot, i, "report"))

    @discord.ui.button(label='Leave', row=1)
    async def leave(self, i, button):
        self.current(i)
        self.bot.globalchat.store.consent(i.user.id, False)
        await reply(
            i,
            '**New sharing has stopped across the network.** Existing copies remain available; use the original message or My messages to request removal. Choose Join in this panel to return. Another automatic invitation will not be sent.',
        )


async def close_confirmation(i, text):
    await i.response.defer()
    try:
        await i.delete_original_response()
    except discord.NotFound:
        pass
    except discord.HTTPException:
        await i.edit_original_response(**payload(bot=i.client, content=text, view=None))


class ConsentView(ScopedView):
    def __init__(self, bot, i, cfg):
        super().__init__(bot, i)
        self.generation = cfg["generation"]
        self.completed = False

    @discord.ui.button(
        label='Confirm and join', style=discord.ButtonStyle.success
    )
    async def accept(self, i, button):
        self.require(i)
        self.bot.require_human(i)
        cfg = self.bot.globalchat.store.source(i.channel_id)
        if not cfg or cfg["generation"] != self.generation:
            raise ValueError('The channel connection changed. Open /globalchat again.')
        if self.bot.globalchat.store.blocked(i.user.id, i.guild_id):
            raise ValueError('Your participation in this chat is blocked.')
        if self.completed:
            return
        self.completed = True
        self.bot.globalchat.store.consent(i.user.id)
        await close_confirmation(
            i,
            '**Participation confirmed across the network.** Your new messages in global channels will be shared.',
        )
        await self.bot.globalchat.onboarding.finish(i.user.id, "accepted")
        self.stop()

    @discord.ui.button(label='Not now')
    async def cancel(self, i, button):
        self.require(i)
        if self.completed:
            return
        self.completed = True
        await close_confirmation(
            i,
            'You have not joined. Your messages stay in the server where you wrote them.',
        )
        await self.bot.globalchat.onboarding.finish(i.user.id, "declined")
        self.stop()


class GlobalDirectView(GuardedView):
    """Persistent buttons bound to the recorded DM recipient and message IDs."""

    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(
        label='Confirm and join',
        style=discord.ButtonStyle.success,
        custom_id="global:v2:dm:accept",
    )
    async def accept(self, i, button):
        service = self.bot.globalchat.onboarding
        service.direct_record(i)
        await i.response.defer()
        await service.context(i)
        self.bot.globalchat.store.consent(i.user.id)
        await service.finish(i.user.id, "accepted", message=i.message)

    @discord.ui.button(label='Not now', custom_id="global:v2:dm:cancel")
    async def cancel(self, i, button):
        service = self.bot.globalchat.onboarding
        service.direct_record(i)
        await i.response.defer()
        await service.finish(i.user.id, "declined", message=i.message)


class GlobalAdminView(ScopedView):
    def __init__(self, bot, i):
        super().__init__(bot, i, admin=True)
        cfg = bot.globalchat.store.channel(i.guild_id)
        self.generation = cfg["generation"] if cfg else 0
        self.activate.label = (
            'Enable in this channel'
            if not cfg or cfg["channel_id"] != str(i.channel_id)
            else 'Check connection'
        )
        if not bot.is_owner_id(i.user.id):
            self.remove_item(self.network)
            self.remove_item(self.network_reports)
            self.remove_item(self.operations)

    def current(self, i):
        self.require(i)
        cfg = self.bot.globalchat.store.channel(i.guild_id)
        if (cfg["generation"] if cfg else 0) != self.generation:
            raise ValueError('The settings changed. Open /globalchat again.')
        return cfg

    def description(self):
        cfg = self.bot.globalchat.store.channel(self.guild)
        state = (
            'Not connected yet.'
            if not cfg
            else ('**Connected:** ' if cfg["active"] else '**Paused:** ')
            + f"<#{cfg['channel_id']}>."
        )
        text = (
            '## Global chat · administration\n'
            + state
            + '\n\n**One channel per server.** Enable this channel to connect new conversations to the network. Original messages stay in place; only people who confirm participation have their messages shared.\n\nThe bot needs **View Channel, Send Messages, Read Message History, Attach Files and Manage Webhooks**. Choose a channel without an age restriction.\n\nAdministrators moderate this server. Network-wide restrictions and removals are reserved for the bot owner.'
        )
        held = self.bot.globalchat.store.restriction(0, self.guild)
        if held:
            text += f"\n\n**Sharing is temporarily restricted until <t:{int(held['until'])}:t>.** Local conversation continues; the bot owner can review the restriction."
        if self.bot.globalchat.store.network_paused():
            text += "\n\n**The bot owner has paused the network.** This server's configuration has been preserved."
        if self.bot.is_owner_id(self.actor):
            from global_media import CACHE_LIMIT

            usage = self.bot.globalchat.media.usage()
            queued = self.bot.globalchat.store.one(
                "SELECT COUNT(*) AS n FROM global_deliveries WHERE state IN ('queued','preparing','uncertain','sending')"
            )["n"]
            text += f'\n\n**Only visible to you:** temporary cache {usage / 1024 / 1024:.1f}/{CACHE_LIMIT // 1024 // 1024} MiB · database {self.bot.store.path.stat().st_size / 1024 / 1024:.1f} MiB · {queued} pending deliveries.'
        return text

    @discord.ui.button(
        label='Enable in this channel', style=discord.ButtonStyle.success, row=0
    )
    async def activate(self, i, button):
        cfg = self.current(i)
        if cfg and cfg["channel_id"] != str(i.channel_id):
            await reply(
                i,
                f"**Change the global channel?**\nCurrent: <#{cfg['channel_id']}> → new: <#{i.channel_id}>.\nNew messages will be shared through the new channel. Existing history stays where it was published.",
                view=MoveConfirm(self.bot, i, self.generation),
            )
            return
        await i.response.defer(ephemeral=True, thinking=True)
        async with self.bot.guild_lock(i.guild_id):
            self.current(i)
            await self.bot.globalchat.activate(i.channel)
        fresh = GlobalAdminView(self.bot, i)
        await reply(
            i,
            '**Connection ready.** Controls are private. The first invitation arrives by DM, without repeated public notices.\n\n'
            + fresh.description(),
            view=fresh,
        )

    @discord.ui.button(label='Pause / resume', row=0)
    async def toggle(self, i, button):
        cfg = self.current(i)
        if not cfg:
            raise ValueError('Enable a channel first.')
        await i.response.defer(ephemeral=True)
        if cfg["active"]:
            self.bot.globalchat.store.active(i.guild_id, False)
            await self.bot.globalchat.onboarding.cleanup_public(
                self.bot.globalchat.store.channel(i.guild_id)
            )
            await reply(
                i,
                '**Connection paused in this server.** New messages are not shared in either direction. Existing history remains available. Use /globalchat to resume.',
            )
        else:
            channel = self.bot.globalchat.channel(cfg["channel_id"])
            await self.bot.globalchat.activate(channel)
            await reply(
                i,
                '**Connection resumed.** Only new messages will be shared; conversations from the pause are not imported.',
            )

    @discord.ui.button(label='Local restrictions', row=1)
    async def blocks(self, i, button):
        self.current(i)
        await i.response.send_modal(ModerationModal(self.bot, i, network=False))

    @discord.ui.button(label='Server reports', row=1)
    async def reports(self, i, button):
        self.current(i)
        from global_reports import ReportInbox

        view = ReportInbox(self.bot, i)
        await reply(i, view.description(), view=view)

    @discord.ui.button(label='Bot status', row=4)
    async def operations(self, i, button):
        self.current(i)
        self.bot.require_owner(i)
        from global_ops import OperationsView

        await reply(
            i,
            self.bot.globalchat.operations.description(),
            view=OperationsView(self.bot, i),
        )

    @discord.ui.button(label='My participation', row=2)
    async def personal(self, i, button):
        cfg = self.current(i)
        if not cfg or cfg["channel_id"] != str(i.channel_id):
            raise ValueError(
                'Open /globalchat in the configured global channel to manage your participation.'
            )
        self.bot.require_human(i)
        view = GlobalMemberView(self.bot, i)
        await reply(i, view.description(), view=view)

    @discord.ui.button(label='Network moderation', row=3)
    async def network(self, i, button):
        self.current(i)
        self.bot.require_owner(i)
        await i.response.send_modal(ModerationModal(self.bot, i, network=True))

    @discord.ui.button(label='Network reports', row=3)
    async def network_reports(self, i, button):
        self.current(i)
        self.bot.require_owner(i)
        from global_reports import ReportInbox

        view = ReportInbox(self.bot, i, network=True)
        await reply(i, view.description(), view=view)


class MoveConfirm(ScopedView):
    def __init__(self, bot, i, generation):
        super().__init__(bot, i, admin=True)
        self.generation = generation
        self.done = False

    @discord.ui.button(label='Confirm change', style=discord.ButtonStyle.success)
    async def confirm(self, i, button):
        self.require(i)
        cfg = self.bot.globalchat.store.channel(i.guild_id)
        if not cfg or cfg["generation"] != self.generation:
            raise ValueError('The channel changed. Open /globalchat again.')
        if self.done:
            return
        self.done = True
        await i.response.defer(ephemeral=True)
        async with self.bot.guild_lock(i.guild_id):
            current = self.bot.globalchat.store.channel(i.guild_id)
            if not current or current["generation"] != self.generation:
                raise ValueError('The channel changed. Open /globalchat again.')
            await self.bot.globalchat.activate(i.channel)
        await reply(
            i,
            '**Global channel changed.** Controls remain private; new participants receive their invitation by DM.',
        )
        self.stop()


class MyMessagesView(ScopedView):
    def __init__(self, bot, i):
        super().__init__(bot, i)
        self.page = 0

    def description(self):
        rows = self.bot.globalchat.store.rows(
            "SELECT * FROM global_messages WHERE user_id=? AND deleted=0 AND expires>? ORDER BY created DESC,id DESC LIMIT 6 OFFSET ?",
            (str(self.actor), self.bot.globalchat.store.clock(), self.page * 5),
        )
        self.previous.disabled = self.page == 0
        self.next.disabled = len(rows) <= 5
        rows = rows[:5]
        text = f'## My messages · page {self.page + 1}\nEdit or delete the original message in Discord. To request removal of network copies only, choose Remove copies.\n'
        for row in rows:
            data = json.loads(row["payload"])
            counts = self.bot.globalchat.store.rows(
                "SELECT state,COUNT(*) AS n FROM global_deliveries WHERE source_id=? GROUP BY state",
                (row["id"],),
            )
            states = {x["state"]: x["n"] for x in counts}
            status = f"Shared with {states.get('sent', 0) + states.get('partial', 0)} destination(s)."
            if states.get("partial"):
                status += " Some attachments exceeded the destination's limit."
            if any(
                states.get(k) for k in ("queued", "preparing", "uncertain", "sending")
            ):
                status += ' There are pending deliveries.'
            if states.get("failed") or row["error"]:
                status += ' Some deliveries could not be confirmed.'
            text += f"\n**[Message {row['id']}](https://discord.com/channels/{row['guild_id']}/{row['channel_id']}/{row['id']})**\n{safe(data.get('body') or 'The attachment or content has already been removed from the cache.', 100)}\n{status}\n"
        return (
            text
            if rows
            else text + '\nYour account has not shared any recent messages.'
        )

    @discord.ui.button(label='Previous', row=0)
    async def previous(self, i, button):
        self.require(i)
        self.page = max(0, self.page - 1)
        from tier_ui import edit_response

        await edit_response(i, content=self.description(), view=self)

    @discord.ui.button(label='Next', row=0)
    async def next(self, i, button):
        self.require(i)
        self.page += 1
        from tier_ui import edit_response

        await edit_response(i, content=self.description(), view=self)

    @discord.ui.button(label='Refresh', row=0)
    async def reload(self, i, button):
        self.require(i)
        from tier_ui import edit_response

        await edit_response(i, content=self.description(), view=self)

    @discord.ui.button(label='Remove copies', style=discord.ButtonStyle.danger, row=1)
    async def erase(self, i, button):
        self.require(i)
        await i.response.send_modal(MessageAction(self.bot, i, "erase"))


class MessageAction(BoundModal):
    def __init__(self, bot, i, action):
        super().__init__(
            title='Report a message'
            if action == "report"
            else 'Remove my copies'
        )
        self.bind(bot, i)
        self.action = action
        self.link = discord.ui.TextInput(
            placeholder='Paste a message link or ID', max_length=250
        )
        self.add_item(
            discord.ui.Label(text='Global chat message', component=self.link)
        )
        self.reason = None
        if action == "report":
            self.reason = discord.ui.TextInput(
                style=discord.TextStyle.paragraph, min_length=10, max_length=500
            )
            self.add_item(
                discord.ui.Label(text='What happened?', component=self.reason)
            )

    async def on_submit(self, i):
        if not await self.interaction_check(i):
            return
        self.bot.require_human(i)
        row = find_message(self.bot, i, str(self.link), own=self.action == "erase")
        if self.action == "report":
            self.bot.globalchat.store.report(
                row["id"], i.user.id, i.guild_id, str(self.reason)
            )
            await reply(
                i,
                "**Report submitted.** This server's administrators and the network owner can review it. Your report is not published in chat.",
            )
        else:
            if row["user_id"] != str(i.user.id):
                raise ValueError(
                    'You can only remove copies of your own messages.'
                )
            self.bot.globalchat.store.erase(row["id"])
            await reply(
                i,
                '**Removal requested.** Accessible copies will be deleted. You remain in control of the original message in Discord.',
            )


def find_message(bot, i, value, *, own=False, network=False):
    store = bot.globalchat.store
    value = value.strip()
    match = re.fullmatch(
        r"https://(?:canary\.|ptb\.)?discord(?:app)?\.com/channels/(\d+)/(\d+)/(\d+)",
        value,
    )
    if match:
        guild, channel, ident = match.groups()
        if (
            not own
            and not network
            and (guild, channel) != (str(i.guild_id), str(i.channel_id))
        ):
            raise ValueError('Use a message link from this global chat.')
        row = store.resolve(guild, channel, ident)
    elif value.isdecimal():
        row = store.resolve(i.guild_id, i.channel_id, value)
        if not row and (own or network):
            row = store.message(value)
            if not row:
                receipt = store.one(
                    "SELECT source_id FROM global_receipts WHERE message_id=?", (value,)
                )
                row = store.message(receipt["source_id"]) if receipt else None
    else:
        raise ValueError('Paste the Discord message link or its ID.')
    if not row:
        raise ValueError(
            'The message was not found within the 30-day synchronization window.'
        )
    return row


class ModerationModal(BoundModal):
    def __init__(self, bot, i, *, network):
        super().__init__(
            title='Network moderation' if network else 'Server moderation'
        )
        self.bind(bot, i)
        self.network = network
        options = [
            discord.SelectOption(label='Block user', value="block-user"),
            discord.SelectOption(label='Unblock user', value="unblock-user"),
        ]
        if network:
            options.extend(
                [
                    discord.SelectOption(
                        label='Block server', value="block-guild"
                    ),
                    discord.SelectOption(
                        label='Unblock server', value="unblock-guild"
                    ),
                    discord.SelectOption(
                        label='Remove message copies', value="erase"
                    ),
                ]
            )
        self.action = discord.ui.Select(options=options)
        self.target = discord.ui.TextInput(
            max_length=250, placeholder='User/server ID or message link'
        )
        self.reason = discord.ui.TextInput(
            style=discord.TextStyle.paragraph, min_length=5, max_length=500
        )
        self.add_item(discord.ui.Label(text='Action', component=self.action))
        self.add_item(discord.ui.Label(text="Alvo", component=self.target))
        self.add_item(discord.ui.Label(text="Motivo", component=self.reason))

    async def on_submit(self, i):
        if not await self.interaction_check(i):
            return
        self.bot.require_admin(i)
        if self.network:
            self.bot.require_owner(i)
        reason = str(self.reason).strip()
        if not 5 <= len(reason) <= 500:
            raise ValueError('Explain the reason in 5 to 500 characters.')
        value = self.action.values[0]
        if value == "erase":
            if not self.network:
                raise ValueError('This action is restricted to network moderation.')
            row = find_message(self.bot, i, str(self.target), network=True)
            self.bot.globalchat.store.erase(row["id"])
            with self.bot.store.connection:
                self.bot.store.audit("global-removal", i.user.id, str(self.reason))
        else:
            enabled, kind = value.split("-", 1)
            if kind == "guild" and not self.network:
                raise ValueError('Server administrators can only block users in their own server.')
            target = str(self.target).strip()
            if target.startswith("https://"):
                row = find_message(self.bot, i, target, network=self.network)
                target = row["user_id"] if kind == "user" else row["guild_id"]
            self.bot.globalchat.store.block(
                "*" if self.network else i.guild_id,
                kind,
                target,
                i.user.id,
                str(self.reason),
                enabled=enabled == "block",
            )
        await reply(
            i,
            '**Moderation applied.** '
            + (
                'This action applies across the network.'
                if self.network
                else 'This action applies only to this server.'
            ),
        )
