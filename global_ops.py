"""Owner-only operational view and quiet, persistent alerts for sustained failures."""

import json
import discord
import aiohttp
from global_views import ScopedView
from tier_views import BoundModal, reply
from tier_ui import edit_response, payload
from tier_release import label


class GlobalOperations:
    def __init__(self, relay):
        self.relay, self.bot, self.store = relay, relay.bot, relay.store

    def snapshot(self):
        now = self.store.clock()
        pending = self.store.one(
            "SELECT COUNT(*) AS n,MIN(m.updated) AS oldest FROM global_deliveries d JOIN global_messages m ON m.id=d.source_id WHERE d.state IN ('queued','preparing','uncertain','sending')"
        )
        failures = self.store.one(
            "SELECT COUNT(*) AS n FROM global_deliveries d JOIN global_messages m ON m.id=d.source_id WHERE d.state='failed' AND m.updated>?",
            (now - 900,),
        )["n"]
        blocked = self.store.one(
            "SELECT COUNT(*) AS n FROM global_restrictions WHERE until>? AND kind='guild'",
            (now,),
        )["n"]
        return {
            "pending": pending["n"],
            "age": max(0, int(now - pending["oldest"])) if pending["oldest"] else 0,
            "failures": failures,
            "contained": blocked,
            "paused": self.store.network_paused(),
            "heartbeat": max(0, int(now - self.relay.last_cycle)),
            "storage": getattr(self.bot.health, "storage_level", "unknown"),
            "archive_paused": bool(getattr(getattr(self.bot,'knowledge',None),'paused',False)) and (not getattr(self.bot.knowledge,'remote',False) or self.bot.knowledge.online),
        }

    def description(self, *, compact=False):
        s = self.snapshot()
        text = f"**Global chat:** {('network paused' if s['paused'] else 'network active')} · {s['pending']} pending delivery attempt(s); oldest: {s['age']} s.\n**Last 15 minutes:** {s['failures']} unconfirmed delivery attempt(s).\n**Temporary restrictions:** {s['contained']} restricted server(s).\n**Last queue cycle:** {s['heartbeat']} s."
        if compact:
            return text
        text = '## Private bot status\n' + text
        quota=getattr(self.bot.health,'quota',None)
        if quota:
            text+=f"\n**Instance files:** {quota['used']/1048576:.1f}/{quota['total']/1048576:.0f} MiB (measured locally)."
        text += f"\n**Storage:** {s['storage']} · database {self.bot.store.path.stat().st_size / 1024 / 1024:.1f} MiB · cache {self.relay.media.usage() / 1024 / 1024:.1f} MiB."
        build = getattr(self.bot, "build", None)
        if build:
            text += '\n**Running version:** ' + label(build)
        for key, title in (() if getattr(getattr(self.bot,'knowledge',None),'disabled',False) else (
            ("last_connection_success", 'Last successful AI connection'),
            ("ask_last_success", 'Last successful answer'),
        )):
            value = self.bot.store.get(key)
            text += f"\n**{title}:** " + (
                f"<t:{int(float(value))}:R>" if value else 'not recorded yet'
            )
        alerts = self.bot.store.get("global-owner-alerts") != "0"
        text += f"\n**Private alerts:** {('enabled' if alerts else 'disabled')}. Failures must persist for two minutes; each alert type has a one-hour cooldown."
        held = self.store.rows(
            "SELECT target,until,reason FROM global_restrictions WHERE scope='*' AND kind='guild' AND until>? ORDER BY until LIMIT 5",
            (self.store.clock(),),
        )
        for row in held:
            text += f"\n**Server {row['target']}:** restricted until <t:{int(row['until'])}:t>."
        text += '\n-# Use Network moderation to release a server early. Pausing the network stops new sharing; deletions continue to be processed.'
        knowledge=getattr(self.bot,'knowledge',None)
        if knowledge and not getattr(knowledge,'disabled',False):
            info=knowledge.statistics()
            if info.get('remote'):
                text+=f"\n**PC question service:** {'online' if info['online'] else 'offline'} · {info['messages']} saved messages · {info['bytes']/1048576:.1f} MiB on the PC (last received status)."
                if info.get('last_answer'):
                    text+=f"\n**Last PC answer:** <t:{int(info['last_answer'])}:R>."
                if not info['online']:
                    text+='\nQuestions are unavailable until the PC program reconnects. Image feeds and global chat remain independent.'
            else:
                today=info['days'][0]['messages'] if info['days'] else 0
                text+=f"\n**Game knowledge:** {info['messages']} saved messages · {info['bytes']/1048576:.1f}/{info['limit']/1048576:.0f} MiB · latest observed day: {today} messages."
            if info['paused'] and (not info.get('remote') or info['online']):
                text+='\n**Q&A capture paused.** Saved history is preserved. Check storage and backups before restarting collection.'
        return text

    async def notify(self, text):
        delivered = False
        for ident in sorted(getattr(self.bot, "owner_ids_set", set())):
            try:
                user = self.bot.get_user(ident)
                if user is None:
                    user = await self.bot.fetch_user(ident)
                if user.id == ident and self.bot.is_owner_id(ident):
                    await user.send(**payload(bot=self.bot, content=text))
                    delivered = True
            except (discord.HTTPException, aiohttp.ClientError, TimeoutError, OSError):
                pass
        return delivered

    async def check_alerts(self):
        if self.bot.store.get("global-owner-alerts") == "0":
            return
        s = self.snapshot()
        now = self.store.clock()
        conditions = {
            "knowledge": (
                s['archive_paused'],
                'Q&A capture is paused because its archive is full or unavailable. Saved messages have not been erased. Check storage and download the knowledge backup before making changes.',
            ),
            "storage": (
                s["storage"] == "critical",
                'Storage is critically low. Open the private diagnostics before sharing more files.',
            ),
            "queue": (
                s["pending"] > 0 and s["age"] > 180 and not s["paused"],
                'Some deliveries have been waiting for more than three minutes. Open Bot status to check the queue and permissions.',
            ),
            "worker": (
                s["heartbeat"] > 240 and not s["paused"],
                'Global chat processing is not progressing. Check the logs and the running version.',
            ),
            "containment": (
                s["contained"] > 0,
                'One or more servers were temporarily restricted after a burst. Check Bot status to review.',
            ),
        }
        if getattr(getattr(self.bot,'knowledge',None),'disabled',False):
            conditions.pop('knowledge',None)
        for key, (active, text) in conditions.items():
            meta = "global-alert:" + key
            previous = json.loads(self.bot.store.get(meta) or "{}")
            if not active:
                if previous.get("sent"):
                    self.bot.store.set(meta, "{}")
                    await self.notify(
                        '## Service recovered\n'
                        + {
                            "storage": 'Storage is no longer critically low.',
                            "queue": 'The queue no longer shows the previous delay.',
                            "worker": 'Global chat processing is progressing again.',
                            "containment": 'No servers are currently under temporary restrictions.',
                            "knowledge": 'The knowledge archive is accepting Q&A messages again.',
                        }[key]
                    )
                elif previous:
                    self.bot.store.set(meta, "{}")
                continue
            if not previous:
                self.bot.store.set(
                    meta, json.dumps({"first": now, "attempted": 0, "sent": False})
                )
                continue
            if (
                now - previous["first"] < 120
                or now - previous.get("attempted", 0) < 3600
            ):
                continue
            previous.update(attempted=now)
            self.bot.store.set(meta, json.dumps(previous))
            delivered = await self.notify(
                '## Bot status alert\n'
                + text
                + '\n-# This alert is private and is not repeated for every message.'
            )
            previous["sent"] = previous.get("sent", False) or delivered
            self.bot.store.set(meta, json.dumps(previous))


class OperationsView(ScopedView):
    def __init__(self, bot, i):
        super().__init__(bot, i, owner=True)

    @discord.ui.button(label='Refresh status', row=0)
    async def refresh(self, i, button):
        self.require(i)
        await edit_response(
            i, content=self.bot.globalchat.operations.description(), view=self
        )

    @discord.ui.button(label='Pause / resume network', row=0)
    async def pause(self, i, button):
        self.require(i)
        await i.response.send_modal(NetworkPause(self.bot, i))

    @discord.ui.button(label='Enable / disable alerts', row=1)
    async def alerts(self, i, button):
        self.require(i)
        enabled = self.bot.store.get("global-owner-alerts") != "0"
        self.bot.store.set("global-owner-alerts", "0" if enabled else "1")
        await edit_response(
            i, content=self.bot.globalchat.operations.description(), view=self
        )


class NetworkPause(BoundModal):
    def __init__(self, bot, i):
        super().__init__(title='Pause or resume the network')
        self.bind(bot, i)
        self.was_paused = bot.globalchat.store.network_paused()
        self.reason = discord.ui.TextInput(
            style=discord.TextStyle.paragraph, min_length=5, max_length=500
        )
        self.add_item(
            discord.ui.Label(
                text='Reason to '
                + ('resume' if self.was_paused else 'pause')
                + ' the network',
                description='Applies to all servers. Local conversation and deletions remain available.',
                component=self.reason,
            )
        )

    async def on_submit(self, i):
        if not await self.interaction_check(i):
            return
        self.bot.require_owner(i)
        if self.bot.globalchat.store.network_paused() != self.was_paused:
            raise ValueError(
                'The network status changed. Refresh the controls before confirming.'
            )
        self.bot.globalchat.store.pause_network(
            not self.was_paused, i.user.id, str(self.reason)
        )
        await reply(
            i,
            '**Network '
            + ('resumed' if self.was_paused else 'paused')
            + ".** "
            + (
                'Only new messages are shared.'
                if self.was_paused
                else 'New sharing has stopped; deletions continue to be processed.'
            ),
        )
