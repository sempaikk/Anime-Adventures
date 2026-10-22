"""Administrative audit stays private; remove only its verified, bot-owned copies."""

import logging

import discord
import aiohttp

from tier_ui import visible_text

log = logging.getLogger("tierlist.audit")


def audit_marker(ident, message):
    return any(
        line.strip().removeprefix("-# ").startswith(f"Revisão #{ident} ·")
        for line in visible_text(message).splitlines()
    )


async def hide_audit_messages(bot, panel, thread):
    """Bounded cleanup of recorded notices, including copies in previous topics."""
    store = bot.store
    rows = store.rows(
        "SELECT m.audit_id,m.message_id,COALESCE(d.channel_id,?) AS channel_id,d.key "
        "FROM tier_audit_messages m LEFT JOIN tier_deliveries d "
        "ON d.message_id=m.message_id AND d.key='audit:'||m.audit_id||':'||d.channel_id "
        "WHERE m.guild_id=? ORDER BY m.audit_id LIMIT 10",
        (str(thread.id), panel["guild_id"]),
    )
    known = {str(thread.id)}
    previous = store.get("previous-thread:" + panel["guild_id"])
    if previous:
        known.add(previous)
    # A process can stop after recording delivery but before recording its audit receipt.
    for channel_id in sorted(known):
        for item in store.rows(
            "SELECT * FROM tier_deliveries WHERE channel_id=? AND key LIKE 'audit:%' LIMIT 10",
            (channel_id,),
        ):
            parts = item["key"].split(":")
            if len(parts) == 3 and parts[1].isdigit() and parts[2] == channel_id:
                rows.append(dict(item, audit_id=int(parts[1])))
    candidates = {(r["channel_id"], r["message_id"]): r for r in rows}
    for row in list(candidates.values())[:10]:
        try:
            channel = (
                thread
                if str(thread.id) == row["channel_id"]
                else await bot.channel(row["channel_id"])
            )
            if str(channel.guild.id) != panel["guild_id"]:
                log.warning("Aviso administrativo preservado: servidor divergente.")
                continue
            try:
                message = await channel.fetch_message(int(row["message_id"]))
                if message.author.id != bot.user.id or not audit_marker(
                    row["audit_id"], message
                ):
                    log.warning(
                        "Aviso administrativo preservado: identidade divergente."
                    )
                    continue
                await message.delete()
            except discord.NotFound:
                pass
            with store.connection:
                store.connection.execute(
                    "DELETE FROM tier_audit_messages WHERE audit_id=? AND guild_id=? AND message_id=?",
                    (row["audit_id"], panel["guild_id"], row["message_id"]),
                )
                store.connection.execute(
                    "DELETE FROM tier_deliveries WHERE key=? AND message_id=?",
                    (
                        row["key"] or f"audit:{row['audit_id']}:{row['channel_id']}",
                        row["message_id"],
                    ),
                )
        except (discord.HTTPException, aiohttp.ClientError, TimeoutError):
            log.warning("Limpeza de aviso administrativo adiada; registro preservado.")
