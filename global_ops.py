"""Owner-only operational view and quiet, persistent alerts for sustained failures."""

import json
import discord
import aiohttp
from global_views import ScopedView
from bot_views import BoundModal, reply
from bot_ui import edit_response, payload
from bot_release import label


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
        memory=getattr(self.bot.health,'memory',None)
        if memory:
            text+=f"\n**Process memory:** {memory['used']/1048576:.1f}/{memory['total']/1048576:.0f} MiB, including reader children."
        else:
            text+='\n**Process memory:** measurement unavailable on this host.'
        text += f"\n**Storage:** {s['storage']} · database {self.bot.store.path.stat().st_size / 1024 / 1024:.1f} MiB · cache {self.relay.media.usage() / 1024 / 1024:.1f} MiB."
        from storage_metrics import storage_metrics
        capacity=storage_metrics(self.store)
        text+=f"\n**History:** {capacity['stored_copies']} stored copy records · {capacity['reusable']/1048576:.1f} MiB reusable inside SQLite · {capacity['expired_sources']} expired sources awaiting bounded cleanup."
        text+=f"\n**Growth estimate:** {capacity['daily_sources']} source messages in 24 h × up to {max(0,capacity['active_servers']-1)} other active servers = {capacity['estimated_daily_copies']} copies/day at the current audience (before restrictions)."
        build = getattr(self.bot, "build", None)
        if build:
            text += '\n**Running version:** ' + label(build)
        for feed in (getattr(self.bot,'banners',None),getattr(self.bot,'daily',None)):
            if feed:
                summary=feed.diagnostics.network_summary()
                text+=f"\n**{feed.kind.title()} network:** {summary['targets']} destinations · {summary['pending']} pending · {summary['blocked']} blocked attempts."
                if summary['p95'] is not None:
                    text+=f" Latest per-destination delivery p95: {summary['p95']:.0f} s."
        alerts = self.bot.store.get("global-owner-alerts") != "0"
        backup=getattr(self.bot.health,'last_backup',None)
        text+='\n**Verified local backup:** '+(f'<t:{int(backup)}:R>.' if backup else 'not confirmed yet.')
        text+=' External copy: not configured; local copies share the hosting failure risk.'
        text+='\n**Command sync:** '+getattr(self.bot,'command_sync_status','not confirmed in this process')+'.'
        text += f"\n**Private alerts:** {('enabled' if alerts else 'disabled')}. Failures and recoveries must persist for two minutes; each incident type has a one-hour cooldown."
        held = self.store.rows(
            "SELECT target,until,reason FROM global_restrictions WHERE scope='*' AND kind='guild' AND until>? ORDER BY until LIMIT 5",
            (self.store.clock(),),
        )
        for row in held:
            text += f"\n**Server {row['target']}:** restricted until <t:{int(row['until'])}:t>."
        text += '\n-# Use Network moderation to release a server early. Pausing the network stops new sharing; deletions continue to be processed.'
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
        conditions['memory']=(getattr(self.bot.health,'memory_level','unknown')=='critical',
                              'Memory usage is critically high. Large image preparation is paused; check private status.')
        conditions['backup']=(bool(getattr(self.bot.health,'backup_error',False)),
                              'The latest backup attempt failed. The previous verified snapshot remains available.')
        for feed in (getattr(self.bot,'banners',None),getattr(self.bot,'daily',None)):
            if feed:
                conditions.update(feed.alert_conditions())
        source_keys=[k for k in conditions if k.endswith(('_source','_receive'))]
        source_issues=[key for key in source_keys if conditions.pop(key)[0]]
        issue_text = 'The latest source image has not completed reception. Open private feed diagnostics.'
        if any(key.endswith('_source') for key in source_issues):
            issue_text = 'Image source checks are delayed. Open private source diagnostics.'
        else:
            issues = {feed.diagnostics.snapshot()['error'] for feed in
                      (getattr(self.bot,'banners',None),getattr(self.bot,'daily',None))
                      if feed and feed.kind+'_receive' in source_issues}
            if 'receive_memory_budget' in issues:
                issue_text = 'Source checks succeeded, but image reception is waiting for available memory. Open private feed diagnostics.'
            elif 'receive_disk_budget' in issues:
                issue_text = 'Source checks succeeded, but image reception is waiting for available storage. Open private feed diagnostics.'
        conditions['image_sources']=(bool(source_issues), issue_text)
        for key, (active, text) in conditions.items():
            meta = "global-alert:" + key
            previous = json.loads(self.bot.store.get(meta) or "{}")
            if not active:
                if not previous.get('first'):
                    continue
                if not previous.get('cleared'):
                    previous['cleared']=now
                if now-previous['cleared']<120:
                    self.bot.store.set(meta,json.dumps(previous))
                    continue
                if previous.get("sent"):
                    delivered=await self.notify(
                        '## Service recovered\n'
                        + {
                            "storage": 'Storage is no longer critically low.',
                            "queue": 'The queue no longer shows the previous delay.',
                            "worker": 'Global chat processing is progressing again.',
                            "containment": 'No servers are currently under temporary restrictions.',
                        }.get(key,'The '+key.replace('_',' ')+' condition has recovered.')
                    )
                    if not delivered:
                        self.bot.store.set(meta,json.dumps(previous))
                        continue
                previous.update(first=0,sent=False,cleared=0)
                self.bot.store.set(meta,json.dumps(previous))
                continue
            if not previous.get('first'):
                previous.update(first=now,sent=False,cleared=0)
                self.bot.store.set(
                    meta, json.dumps(previous)
                )
                continue
            previous['cleared']=0
            self.bot.store.set(meta,json.dumps(previous))
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
        from community_hub import CENTRAL_GUILD_ID

        if i.guild_id != CENTRAL_GUILD_ID:
            self.remove_item(self.server_report)
            self.remove_item(self.access_review)

    def description(self):
        text = self.bot.globalchat.operations.description()
        for feed in (getattr(self.bot, 'banners', None), getattr(self.bot, 'daily', None)):
            if feed:
                text += '\n\n' + feed.private_status(self.guild)
        from community_hub import CENTRAL_GUILD_ID

        if self.guild == CENTRAL_GUILD_ID:
            text += '\n\n**Community update log:** ' + self.bot.community.status
        text += '\n\n**Feed recovery notice:** ' + self.bot.feed_notices.description()
        text += '\n\n**Banner forwarding notice:** ' + self.bot.banner_forward_notices.description()
        text += '\n\n**Banner reception notice:** ' + self.bot.banner_reception_notices.description()
        return text

    @discord.ui.button(label='Refresh status', row=0)
    async def refresh(self, i, button):
        self.require(i)
        await edit_response(
            i, content=self.description(), view=self
        )

    @discord.ui.button(label='Destinations',row=3)
    async def destinations(self,i,button):
        self.require(i)
        from operations_views import DestinationView
        view=DestinationView(self.bot,i)
        await reply(i,view.description(),view=view)

    @discord.ui.button(label='Copy diagnostics',row=3)
    async def diagnostics(self,i,button):
        self.require(i)
        from operations_views import diagnostic_text
        await reply(i,diagnostic_text(self.bot,self.guild))

    @discord.ui.button(label='Feed maintenance',row=3)
    async def maintenance(self,i,button):
        self.require(i)
        from operations_views import FeedMaintenance
        await i.response.send_modal(FeedMaintenance(self.bot,i))

    @discord.ui.button(label='Server report', row=1)
    async def server_report(self, i, button):
        self.require(i)
        await i.response.defer(ephemeral=True, thinking=True)
        report = self.bot.community.report(i)
        try:
            await reply(i, 'Private server structure and bot permissions. Review this file before sharing it. No messages or credentials are included.', file=report)
        finally:
            report.close()

    @discord.ui.button(label='Review role permissions',row=2)
    async def access_review(self,i,button):
        self.require(i)
        from community_access import AccessReview
        view=AccessReview(self.bot,i)
        await reply(i,view.description(),view=view)

    @discord.ui.button(label='Check backup restore',row=2)
    async def backup_check(self,i,button):
        self.require(i)
        await i.response.defer(ephemeral=True,thinking=True)
        from backup_check import check_restore
        from bot_storage import make_snapshot
        import asyncio
        size=self.bot.store.path.stat().st_size
        async with self.bot.backup_lock,self.bot.instance_storage.reserve(max(1,size)*4):
            if getattr(self.bot,'backup_task',None) and not self.bot.backup_task.done():
                await asyncio.shield(self.bot.backup_task)
            snapshot,_=await asyncio.to_thread(make_snapshot,self.bot.store.path)
            report=await asyncio.to_thread(check_restore,snapshot,temporary_parent=self.bot.directory)
        await reply(i,f'Private restore check passed: {report["tables_checked"]} tables verified in a disposable copy. Live data was not replaced; no snapshot or credentials were uploaded.')

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
            i, content=self.description(), view=self
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
