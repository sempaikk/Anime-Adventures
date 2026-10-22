"""Visible polls, durable results, and safe cleanup of the bot's own notices."""

from __future__ import annotations

import logging

import discord

from tier_image import poll_embed
from tier_views import PollView
from tier_ui import payload, visible_text
from tier_style import theme_for

log = logging.getLogger("tierlist.delivery")
PUBLIC_RESULT_SECONDS = 120
ACTIVE = ("open", "queued")


def poll_marker(number, message):
    marker = f"Proposta #{number} · decisão da comunidade"
    return any(
        line.strip().removeprefix("-# ") == marker
        for line in visible_text(message).splitlines()
    )


def removed(store, receipt):
    with store.connection:
        store.connection.execute(
            "UPDATE tier_poll_messages SET status='removed' WHERE proposal_id=? AND channel_id=?",
            (receipt["proposal_id"], receipt["channel_id"]),
        )


async def archive_and_clean(bot, panel, receipt, proposal):
    """Never remove the visible notice without a confirmed, readable result."""
    store = bot.store
    thread = await bot.active_thread(panel)
    archives = store.rows(
        "SELECT * FROM tier_poll_messages WHERE proposal_id=? AND channel_id=?",
        (proposal["id"], str(thread.id)),
    )
    if archives:
        archive = archives[0]
        if archive["status"] == "removed":
            return  # Respect a moderator removing the saved result.
        if archive["status"] != proposal["status"]:
            return  # A pre-migration copy still needs its final result edit.
    else:
        message = await bot.deliver(
            thread,
            f"poll-history:{proposal['id']}:{thread.id}",
            embed=poll_embed(store, bot.catalog, proposal),
            view=PollView(bot, closed=True, panel=panel, thread_id=thread.id),
            marker=lambda m: poll_marker(proposal["id"], m),
        )
        store.remember_poll(
            proposal["id"], panel["guild_id"], thread.id, message.id, proposal["status"]
        )
        archive = store.poll_at(panel["guild_id"], thread.id, message.id)
    if (
        receipt["status"] == "removed"
        or store.clock() - receipt["updated_at"] < PUBLIC_RESULT_SECONDS
    ):
        return
    try:
        saved = await thread.fetch_message(int(archive["message_id"]))
    except discord.NotFound:
        removed(store, archive)
        return
    if saved.author.id != bot.user.id or not poll_marker(proposal["id"], saved):
        raise ValueError("O resultado salvo não pôde ser confirmado; aviso preservado.")
    channel = await bot.channel(receipt["channel_id"])
    if str(channel.guild.id) != panel["guild_id"]:
        raise ValueError("O aviso não pertence ao servidor do painel.")
    try:
        notice = await channel.fetch_message(int(receipt["message_id"]))
        if notice.author.id != bot.user.id or not poll_marker(proposal["id"], notice):
            raise ValueError(
                "O aviso não pôde ser confirmado; nenhuma mensagem removida."
            )
        await notice.delete()
    except discord.NotFound:
        pass
    removed(store, receipt)


async def publish_pending(bot):
    store = bot.store
    proposal = store.active_proposal()
    if not proposal:
        return
    for panel in store.thread_targets():
        try:
            async with bot.guild_lock(panel["guild_id"]):
                proposal = store.proposal(proposal["id"])
                if proposal["status"] not in ACTIVE or (
                    proposal["status"] == "open"
                    and proposal["closes_at"] - store.clock() < 60
                ):
                    continue
                # A legacy poll finishes in its original thread. Removed copies
                # are not reposted, and concurrent ticks cannot create another.
                if store.rows(
                    "SELECT 1 FROM tier_poll_messages WHERE proposal_id=? AND guild_id=?",
                    (proposal["id"], panel["guild_id"]),
                ):
                    continue
                thread = await bot.active_thread(panel)
                channel = await bot.channel(panel["channel_id"])
                if str(channel.guild.id) != panel["guild_id"]:
                    raise ValueError("O canal não pertence ao servidor do painel.")
                message = await bot.deliver(
                    channel,
                    f"poll:{proposal['id']}:{channel.id}",
                    embed=poll_embed(store, bot.catalog, proposal),
                    view=PollView(bot, panel=panel, thread_id=thread.id),
                    marker=lambda m: poll_marker(proposal["id"], m),
                )
                published = (
                    discord.utils.snowflake_time(message.id).timestamp()
                    if message.id > 10**15
                    else None
                )
                store.remember_poll(
                    proposal["id"],
                    panel["guild_id"],
                    channel.id,
                    message.id,
                    published_at=published,
                )
        except (discord.HTTPException, ValueError, TimeoutError) as error:
            theme_for(bot).observe_error(error)
            log.warning("Enquete adiada: %s", type(error).__name__)


async def resolve_confirmed(bot):
    """A missing gateway delete event must not turn a removed poll into approval."""
    store = bot.store
    eligible = []
    for proposal in store.rows(
        "SELECT id FROM tier_proposals WHERE status='open' AND closes_at<=?",
        (store.clock(),),
    ):
        unknown = False
        for receipt in store.rows(
            "SELECT * FROM tier_poll_messages WHERE proposal_id=? AND status!='removed'",
            (proposal["id"],),
        ):
            try:
                channel = await bot.channel(receipt["channel_id"])
                message = await channel.fetch_message(int(receipt["message_id"]))
            except discord.NotFound:
                removed(store, receipt)
                continue
            except (discord.HTTPException, TimeoutError):
                unknown = True
                continue
            if (
                str(channel.guild.id) == receipt["guild_id"]
                and message.author.id == bot.user.id
                and poll_marker(proposal["id"], message)
            ):
                eligible.append(proposal["id"])
                break
            removed(store, receipt)
        else:
            if not unknown:
                eligible.append(proposal["id"])
    store.resolve_due(
        source_version=bot.analyzer.evidence.version, proposal_ids=eligible
    )


async def sync_polls(bot):
    store = bot.store
    await resolve_confirmed(bot)
    await publish_pending(bot)
    await resolve_confirmed(bot)
    panels = {p["guild_id"]: p for p in store.panels()}
    for stale in store.poll_messages():
        panel = panels.get(stale["guild_id"])
        if not panel:
            continue
        try:
            async with bot.guild_lock(panel["guild_id"]):
                receipt = store.poll_at(
                    stale["guild_id"], stale["channel_id"], stale["message_id"]
                )
                proposal = store.proposal(stale["proposal_id"])
                if not receipt or not proposal:
                    continue
                closed = proposal["status"] not in ACTIVE
                public_result = closed and receipt["channel_id"] == panel["channel_id"]
                needs_edit = receipt["status"] != "removed" and (
                    receipt["status"] != proposal["status"]
                    or (not closed and store.clock() - receipt["updated_at"] >= 60)
                )
                if needs_edit:
                    record = store.thread(panel["guild_id"])
                    if record and record["thread_id"] == receipt["channel_id"]:
                        channel = await bot.active_thread(panel)
                    else:
                        channel = await bot.channel(receipt["channel_id"])
                    if str(channel.guild.id) != receipt["guild_id"]:
                        continue
                    try:
                        await channel.get_partial_message(
                            int(receipt["message_id"])
                        ).edit(
                            **payload(
                                bot=bot,
                                embed=poll_embed(store, bot.catalog, proposal),
                                view=PollView(
                                    bot,
                                    closed=closed,
                                    panel=panel,
                                    thread_id=record["thread_id"] if record else None,
                                ),
                            ),
                        )
                    except discord.NotFound:
                        removed(store, receipt)
                    else:
                        store.remember_poll(
                            proposal["id"],
                            receipt["guild_id"],
                            receipt["channel_id"],
                            receipt["message_id"],
                            proposal["status"],
                        )
                    receipt = store.poll_at(
                        receipt["guild_id"],
                        receipt["channel_id"],
                        receipt["message_id"],
                    )
                if public_result:
                    await archive_and_clean(bot, panel, receipt, proposal)
        except (discord.HTTPException, ValueError, TimeoutError) as error:
            theme_for(bot).observe_error(error)
            log.warning(
                "Resultado preservado, entrega adiada: %s", type(error).__name__
            )
