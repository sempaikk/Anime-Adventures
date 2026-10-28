"""Global chat, image feeds and private community administration."""

from __future__ import annotations
import asyncio
import logging
import os
import signal
import shutil
from pathlib import Path
from types import SimpleNamespace
import discord
from discord import app_commands
from discord.ext import commands,tasks
from dotenv import load_dotenv
from bot_store import BotStore
from bot_storage import acquire_lease,prepare_database,maintain_bot_storage
from bot_style import GameTheme
from bot_views import reply
from bot_release import build_info,label
from runtime_health import RuntimeHealth
from global_relay import GlobalRelay
from banner_relay import BannerRelay
from instance_storage import InstanceStorage
from community_hub import CommunityHub

log=logging.getLogger('adventures.bot')


class CommunityBot(commands.Bot):
    def __init__(self,data_dir=None):
        intents=discord.Intents.none()
        intents.guilds=intents.guild_messages=intents.message_content=True
        super().__init__(command_prefix=commands.when_mentioned,intents=intents,help_command=None,
                         allowed_mentions=discord.AllowedMentions.none())
        self.directory=Path(data_dir or os.getenv('DATA_DIR','state')).resolve()
        self.lease=acquire_lease(self.directory)
        self.health=RuntimeHealth(self.is_ready,lambda:self.store.connection)
        self.instance_storage=InstanceStorage(Path(__file__).resolve().parent,self.directory,self.health,
                                             limit_mb=os.getenv('INSTANCE_DISK_LIMIT_MB','512'))
        try:
            self.store=BotStore(prepare_database(self.directory,available_space=lambda:
                max(0,self.instance_storage.limit-self.instance_storage.measure())))
        except BaseException:
            self.lease.close()
            raise
        self.guild_locks={}
        self.globalchat=GlobalRelay(self)
        self.health.add_probe('global_chat',self.globalchat.ready)
        self.banners=BannerRelay(self)
        self.daily=BannerRelay(self,kind='daily')
        self.globalchat.media.available_space=self.instance_storage.available
        self.owner_ids_set=set()
        self.ui_theme=GameTheme()
        self.community=CommunityHub(self)
        self.build=build_info()
        self.register_commands()

    async def setup_hook(self):
        log.info('Running version %s; files %s.',label(self.build),'verified' if self.build['verified'] else 'changed')
        app=await self.application_info()
        await self.ui_theme.refresh(self.http,app.id)
        self.owner_ids_set={app.team.owner_id if app.team else app.owner.id}
        from global_views import GlobalPanelView,GlobalDirectView
        self.add_view(GlobalPanelView(self))
        self.add_view(GlobalDirectView(self))
        await self.health.start(int(os.getenv('PORT') or os.getenv('SERVER_PORT') or 8080))
        await self.tree.sync()
        for loop in self.service_loops():
            loop.start()
        self.banners.start()
        log.info('Commands synchronized: global chat, banners and daily challenges.')

    def service_loops(self):
        return (self.maintenance_loop,self.global_loop,self.operations_loop,self.banner_loop,
                self.daily_loop,self.banner_votes_loop,self.quota_loop)

    async def on_ready(self):
        actual={str(g.id) for g in self.guilds}
        for row in self.globalchat.store.channels():
            if row['guild_id'] not in actual:
                self.globalchat.store.remove_guild(row['guild_id'])
        for feed in (self.banners,self.daily):
            for row in feed.query('SELECT guild_id FROM banner_targets').fetchall():
                if row['guild_id'] not in actual:
                    feed.disable(row['guild_id'])
        log.info('Connected; %s servers.',len(self.guilds))

    async def on_guild_remove(self,guild):
        self.banners.disable(guild.id)
        self.daily.disable(guild.id)
        self.globalchat.store.remove_guild(guild.id)
        self.guild_locks.pop(guild.id,None)

    async def on_message(self,message):
        await self.globalchat.ingest(message)

    async def on_raw_message_delete(self,event):
        self.globalchat.on_delete(event)

    async def on_raw_bulk_message_delete(self,event):
        for ident in event.message_ids:
            await self.on_raw_message_delete(SimpleNamespace(message_id=ident))

    async def on_raw_message_edit(self,event):
        await self.globalchat.on_edit(event)


    def is_owner_id(self, actor):
        return actor in self.owner_ids_set

    def require_owner(self, i):
        if not self.is_owner_id(i.user.id):
            raise ValueError("Only the bot owner can perform this action.")

    def require_admin(self, i):
        if not i.guild_id or not i.permissions.manage_guild:
            raise ValueError(
                "You need Manage Server to configure this feature."
            )

    def require_human(self, i):
        if (
            not i.guild_id
            or i.user.bot
            or (discord.utils.utcnow() - i.user.created_at).total_seconds() < 7 * 86400
        ):
            raise ValueError(
                "Use a user account that is at least seven days old to participate."
            )

    def guild_lock(self, guild_id):
        return self.guild_locks.setdefault(int(guild_id), asyncio.Lock())

    async def on_guild_channel_delete(self, channel):
        for feed in (self.banners, self.daily):
            target = feed.target(channel.guild.id)
            if target and target["channel_id"] == str(channel.id):
                feed.disable(channel.guild.id)
        cfg = self.globalchat.store.source(channel.id)
        if cfg:
            for row in self.globalchat.store.rows(
                "SELECT id FROM global_messages WHERE channel_id=? AND deleted=0",
                (str(channel.id),),
            ):
                self.globalchat.store.erase(row["id"])
            self.globalchat.store.active(channel.guild.id, False)

    async def on_thread_delete(self, thread):
        await self.on_guild_channel_delete(thread)

    @tasks.loop(minutes=15)
    async def maintenance_loop(self):
        try:
            self.store.cleanup()
            report = await asyncio.to_thread(maintain_bot_storage,self.store.path)
            self.health.update_storage(report)
        except Exception as error:
            self.health.backup_error = True
            usage = shutil.disk_usage(self.directory)
            self.health.update_storage(
                {
                    "backup": "failed",
                    "free_bytes": usage.free,
                    "total_bytes": usage.total,
                    "database_bytes": self.store.path.stat().st_size,
                }
            )
            self.health.backup_error = True
            log.warning(
                "Manutenção adiada, cópia anterior preservada: %s", type(error).__name__
            )

    @maintenance_loop.before_loop
    async def maintenance_ready(self):
        await self.wait_until_ready()

    @tasks.loop(seconds=2)
    async def global_loop(self):
        try:
            await self.globalchat.cycle()
        except Exception as error:
            log.warning("Chat global adiado: %s", type(error).__name__)

    @global_loop.before_loop
    async def global_ready(self):
        await self.wait_until_ready()

    @tasks.loop(seconds=30)
    async def operations_loop(self):
        try:
            await self.globalchat.operations.check_alerts()
        except Exception as error:
            log.warning("Diagnóstico operacional adiado: %s", type(error).__name__)
        try:
            await self.community.publish_update()
        except Exception as error:
            log.warning("Community update deferred: %s", type(error).__name__)

    @operations_loop.before_loop
    async def operations_ready(self):
        await self.wait_until_ready()

    @tasks.loop(seconds=2)
    async def banner_loop(self):
        try:
            await self.banners.cycle()
        except Exception as error:
            log.warning("Entrega de banners adiada: %s", type(error).__name__)

    @banner_loop.before_loop
    async def banner_ready(self):
        await self.wait_until_ready()

    @tasks.loop(seconds=2)
    async def daily_loop(self):
        try:
            await self.daily.cycle()
        except Exception as error:
            log.warning("Daily challenge delivery deferred: %s", type(error).__name__)

    @daily_loop.before_loop
    async def daily_ready(self):
        await self.wait_until_ready()

    @tasks.loop(seconds=10)
    async def banner_votes_loop(self):
        try:
            await self.banners.votes.cycle()
        except Exception as error:
            log.warning('Banner reactions deferred: %s', type(error).__name__)

    @banner_votes_loop.before_loop
    async def banner_votes_ready(self):
        await self.wait_until_ready()

    @tasks.loop(seconds=60)
    async def quota_loop(self):
        try:
            await self.instance_storage.refresh(force=True)
        except OSError:
            log.warning('Instance storage measurement unavailable.')

    @quota_loop.before_loop
    async def quota_ready(self):
        await self.wait_until_ready()

    def register_commands(self):
        async def configure_feed(i, kind):
            from banner_relay import BannerControls, require_banner_admin

            require_banner_admin(i)
            command_name = "dailychallenge" if kind == "daily" else "setbanner"
            if not isinstance(i.channel, discord.TextChannel):
                raise ValueError(f"Use /{command_name} in a server text channel.")
            permissions = i.channel.permissions_for(i.guild.me)
            names = {"view_channel": "View Channel", "send_messages": "Send Messages",
                     "attach_files": "Attach Files", "read_message_history": "Read Message History"}
            missing = [label for name, label in names.items() if not getattr(permissions, name, False)]
            if missing:
                raise ValueError("Grant the bot these permissions in this channel: " + ", ".join(missing) + ".")
            await i.response.defer(ephemeral=True, thinking=True)
            feed = self.daily if kind == "daily" else self.banners
            async with self.guild_lock(i.guild_id):
                feed.configure(i.guild_id, i.channel_id)
            label = "Daily challenges" if kind == "daily" else "Banners"
            await reply(i, f"{label} will be posted in <#{i.channel_id}>. Only static images will be sent, without captions.\n\n{feed.description(i.guild_id)}",
                        view=BannerControls(self, i, kind=kind))

        @self.tree.command(
            name="setbanner",
            description="Receive character banner images in this channel.",
        )
        @app_commands.guild_only()
        @app_commands.allowed_installs(guilds=True, users=False)
        @app_commands.default_permissions(manage_guild=True)
        async def setbanner(i: discord.Interaction):
            await configure_feed(i, "banner")

        @self.tree.command(name="dailychallenge", description="Receive daily challenge images in this channel.")
        @app_commands.guild_only()
        @app_commands.allowed_installs(guilds=True, users=False)
        @app_commands.default_permissions(manage_guild=True)
        async def dailychallenge(i: discord.Interaction):
            await configure_feed(i, "daily")

        @self.tree.command(
            name="globalchat",
            description="Join global chat or manage this server's connection.",
        )
        @app_commands.guild_only()
        @app_commands.allowed_installs(guilds=True, users=False)
        async def chatglobal(i: discord.Interaction):
            from global_views import GlobalAdminView, GlobalMemberView

            if i.permissions.manage_guild:
                view = GlobalAdminView(self, i)
            else:
                self.require_human(i)
                cfg = self.globalchat.store.channel(i.guild_id)
                if not cfg:
                    raise ValueError(
                        "Global chat is not connected in this server yet. Ask an administrator to set up a channel."
                    )
                if cfg["channel_id"] != str(i.channel_id):
                    raise ValueError(
                        f"Open /globalchat in <#{cfg['channel_id']}> to access your private controls."
                    )
                view = GlobalMemberView(self, i)
            await reply(i, view.description(), view=view)

        @self.tree.error
        async def command_error(i, error):
            cause = getattr(error, "original", error)
            self.ui_theme.observe_error(cause)
            if isinstance(cause, (ValueError, app_commands.CheckFailure)):
                await reply(i, str(cause))
            else:
                log.warning("Comando indisponível: %s", type(cause).__name__)
                await reply(
                    i,
                    "The action could not be completed. Check the channel permissions and try again. The previous state was preserved.",
                )

    async def close(self):
        if getattr(self,'_bot_closed',False):
            return
        self._bot_closed=True
        for loop in self.service_loops():
            task=loop.get_task()
            if task and not task.done():
                task.cancel()
                await asyncio.gather(task,return_exceptions=True)
        await self.health.close()
        await self.banners.close()
        await self.daily.close()
        await self.globalchat.close()
        await super().close()
        self.store.close()
        self.lease.close()


def run():
    load_dotenv()
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise SystemExit("Defina DISCORD_TOKEN na hospedagem.")
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    async def main():
        bot = CommunityBot()
        loop = asyncio.get_running_loop()
        for event in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(event, lambda: asyncio.create_task(bot.close()))
            except (NotImplementedError, RuntimeError):
                pass
        try:
            await bot.start(token)
        finally:
            await bot.close()

    asyncio.run(main())
