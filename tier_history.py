"""Automatic, bounded first read of recent public game discussions."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

import discord

log = logging.getLogger("tierlist.history")
# Update Log, revision 46886: Update 20 explicitly says 9 March 2025.
# The later 20.4.1 heading has no release date; do not substitute its wiki edit date.
# This is a conservative lower bound, not a claim to date the latest patch.
SINCE = datetime(2025, 3, 9, tzinfo=timezone.utc).timestamp()
MAX_CHANNELS = 10
PER_CHANNEL = 100
MAX_READ = 1000
MAX_ACCEPTED = 20
MAX_ATTEMPTS = 3
RETRY = 3600
TIMEOUT = 60


def eligible(bot, guild, channel):
    if not isinstance(channel, discord.TextChannel) or channel.guild.id != guild.id:
        return False
    access = channel.permissions_for(guild.me)
    if not (access.view_channel and access.read_message_history):
        return False
    if (
        not channel.permissions_for(guild.default_role).view_channel
        or channel.is_nsfw()
    ):
        return False
    return not any(
        p["guild_id"] == str(guild.id) and p["channel_id"] == str(channel.id)
        for p in bot.store.panels()
    )


def channels_for(bot, guild):
    return sorted(
        (c for c in guild.text_channels if eligible(bot, guild, c)),
        key=lambda c: int(c.last_message_id or c.id),
        reverse=True,
    )[:MAX_CHANNELS]


def history_status(store, guild_id):
    state = json.loads(store.get(f"history-import:{guild_id}") or "{}")
    status = state.get("status")
    if status == "completed":
        suffix = (
            " O limite da leitura inicial foi atingido." if state.get("limited") else ""
        )
        return f"leitura inicial concluída; {state['accepted']} relatos aproveitados.{suffix}"
    if status == "running":
        return "leitura inicial em andamento."
    if status == "waiting-permissions":
        return "aguardando um canal público com Ver canal e Ler histórico. Mensagens novas seguem o fluxo normal."
    if status == "interrupted":
        return (
            "a leitura inicial ficou incompleta; haverá nova tentativa automática."
            if state.get("attempts", 0) < MAX_ATTEMPTS
            else "a leitura inicial ficou incompleta após as tentativas. Confira as permissões; mensagens novas seguem o fluxo normal."
        )
    return "aguardando a leitura inicial automática."


class HistoryReader:
    def __init__(self, bot, guild, channels, report):
        self.bot, self.guild, self.channels, self.report = bot, guild, channels, report
        self.channel_ids = tuple(c.id for c in channels)
        self.invalidated = set()
        self.stop_requested = False

    def invalidate(self, event):
        if getattr(event, "channel_id", None) not in (None, *self.channel_ids):
            return
        if len(self.invalidated) >= MAX_READ:
            self.stop_requested = True
        else:
            self.invalidated.add(str(event.message_id))

    def current_channel(self, channel_id):
        if (
            not self.bot.get_guild(self.guild.id)
            or self.bot.health.storage_level == "critical"
            or self.stop_requested
        ):
            raise ValueError("A leitura foi interrompida para preservar o estado.")
        channel = self.bot.get_channel(channel_id)
        return (
            channel
            if channel is not None and eligible(self.bot, self.guild, channel)
            else None
        )

    async def scan(self):
        report = self.report
        start = report["started_at"]
        before = datetime.fromtimestamp(start, timezone.utc)
        after = datetime.fromtimestamp(SINCE, timezone.utc)
        for channel in self.channels:
            current = self.current_channel(channel.id)
            if current is None:
                report["unavailable"] += 1
                continue
            report["channels"] += 1
            count = 0
            try:
                async for message in current.history(
                    limit=PER_CHANNEL, after=after, before=before, oldest_first=False
                ):
                    report["read"] += 1
                    count += 1
                    if self.current_channel(channel.id) is None:
                        raise ValueError("O acesso mudou durante a leitura.")
                    sent = message.created_at.timestamp()
                    if (
                        str(message.id) not in self.invalidated
                        and message.guild
                        and message.guild.id == self.guild.id
                        and message.channel.id == channel.id
                        and after.timestamp() <= sent < start
                        and self.bot.collect_message(message)
                    ):
                        report["accepted"] += 1
                    if report["accepted"] >= MAX_ACCEPTED or report["read"] >= MAX_READ:
                        report["limited"] = True
                        return
                    if count >= PER_CHANNEL:
                        report["limited"] = True
                        break
            except (discord.Forbidden, discord.NotFound):
                report["unavailable"] += 1


async def scan_next(bot):
    """Read one server per cycle; never redo a completed pass after restart."""
    if bot.history_import_lock.locked() or bot.health.storage_level == "critical":
        return False
    now = bot.store.clock()
    for guild in bot.guilds:
        key = f"history-import:{guild.id}"
        previous = json.loads(bot.store.get(key) or "{}")
        if (
            previous.get("status") == "completed"
            or previous.get("attempts", 0) >= MAX_ATTEMPTS
        ):
            continue
        if now < previous.get("retry_after", 0):
            continue
        channels = channels_for(bot, guild)
        if not channels:
            bot.store.set(
                key,
                json.dumps(dict(status="waiting-permissions", retry_after=now + 300)),
            )
            continue
        async with bot.history_import_lock:
            bot.store.register_guild(guild.id)
            report = dict(
                started_at=now,
                retry_after=now + RETRY,
                attempts=previous.get("attempts", 0) + 1,
                status="running",
                read=0,
                accepted=0,
                channels=0,
                unavailable=0,
                limited=False,
            )
            bot.store.set(key, json.dumps(report))
            reader = HistoryReader(bot, guild, channels, report)
            bot.active_history_import = reader
            try:
                async with asyncio.timeout(TIMEOUT):
                    await reader.scan()
                report["status"] = (
                    "interrupted" if report["unavailable"] else "completed"
                )
            except asyncio.CancelledError:
                report["status"] = "interrupted"
                raise
            except Exception as error:
                report["status"] = "interrupted"
                log.warning("Leitura inicial interrompida: %s", type(error).__name__)
            finally:
                bot.active_history_import = None
                if bot.store.guild_registered(guild.id):
                    bot.store.set(key, json.dumps(report))
            return True
    return False
