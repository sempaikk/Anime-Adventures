"""Private, persistent invitations and bounded removal of legacy public notices."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import discord
import aiohttp

from tier_ui import payload, component_dicts, visible_text


class GlobalOnboarding:
    def __init__(self, relay):
        self.relay, self.bot, self.store = relay, relay.bot, relay.store

    async def notice(self, message, text, *, join=False):
        if join:
            cfg = self.store.source(message.channel.id)
            if not cfg or not self.store.claim_invitation(message.author.id, cfg):
                return
            from global_views import GlobalDirectView, TERMS

            task = asyncio.current_task()
            self.relay.tasks.add(task)
            try:
                sent = await message.author.send(
                    **payload(
                        bot=self.bot,
                        content=TERMS
                        + "\n\n**A mensagem que você já escreveu ficou apenas no servidor de origem.** Depois de confirmar, escreva novamente no canal para conversar com a rede. Se preferir, seus controles pessoais também estão em `/chatglobal` dentro do servidor.",
                        view=GlobalDirectView(self.bot),
                    )
                )
                with self.store.db:
                    self.store.db.execute(
                        "UPDATE global_invitations SET dm_channel_id=?,message_id=?,status=CASE WHEN status='sending' THEN 'pending' ELSE status END WHERE user_id=?",
                        (str(sent.channel.id), str(sent.id), str(message.author.id)),
                    )
                if self.store.consented(message.author.id):
                    await self.finish(message.author.id, "accepted", message=sent)
                elif self.store.invitation(message.author.id)["status"] in (
                    "accepted",
                    "declined",
                ):
                    await self.finish(
                        message.author.id,
                        self.store.invitation(message.author.id)["status"],
                        message=sent,
                    )
            except (discord.HTTPException, aiohttp.ClientError, TimeoutError, OSError):
                with self.store.db:
                    self.store.db.execute(
                        "UPDATE global_invitations SET status='unavailable' WHERE user_id=? AND status='sending'",
                        (str(message.author.id),),
                    )
            finally:
                self.relay.tasks.discard(task)
        elif self.store.limit("private-notice:" + str(message.author.id), 1, 300):
            try:
                await message.author.send(
                    **payload(
                        bot=self.bot,
                        content="## Seu envio no chat global\n"
                        + text
                        + "\n\nConsulte `/chatglobal` no servidor para acompanhar seus envios.",
                    )
                )
            except (discord.HTTPException, aiohttp.ClientError, TimeoutError, OSError):
                pass

    def direct_record(self, i):
        row = self.store.invitation(i.user.id)
        if (
            i.guild_id
            or not row
            or row["status"] != "pending"
            or (str(i.channel_id), str(i.message.id))
            != (row["dm_channel_id"], row["message_id"])
        ):
            raise ValueError(
                "Esta confirmação não está mais disponível. Abra /chatglobal no servidor para participar."
            )
        return row

    async def context(self, i):
        row = self.direct_record(i)
        cfg = self.store.channel(row["guild_id"])
        if (
            not cfg
            or not cfg["active"]
            or (cfg["channel_id"], cfg["generation"])
            != (row["channel_id"], row["generation"])
        ):
            raise ValueError(
                "A conexão do servidor mudou. Abra /chatglobal no canal global atual para participar."
            )
        self.bot.require_human(
            SimpleNamespace(user=i.user, guild_id=int(cfg["guild_id"]))
        )
        if self.store.blocked(i.user.id, cfg["guild_id"]):
            raise ValueError("Sua participação está bloqueada neste chat.")
        channel = self.relay.channel(cfg["channel_id"])
        if not self.relay.readable(channel):
            raise ValueError(
                "O canal global está indisponível. Abra /chatglobal no servidor para conferir."
            )
        member = channel.guild.get_member(i.user.id)
        if member is None:
            try:
                member = await channel.guild.fetch_member(i.user.id)
            except discord.HTTPException:
                raise ValueError(
                    "Não consegui confirmar seu acesso ao servidor. Abra /chatglobal por lá."
                ) from None
        permissions = channel.permissions_for(member)
        if not permissions.view_channel or not permissions.send_messages:
            raise ValueError(
                "Você precisa ter acesso para conversar no canal global desse servidor."
            )
        fresh = self.store.source(row["channel_id"])
        if (
            not fresh
            or fresh["generation"] != row["generation"]
            or not self.relay.readable(channel)
            or self.store.blocked(i.user.id, row["guild_id"])
        ):
            raise ValueError(
                "A conexão ou seu acesso mudou. Abra /chatglobal no canal global atual."
            )
        self.direct_record(i)  # Another click may have resolved the DM while fetching.
        return cfg

    async def finish(self, user, status, *, message=None):
        row = self.store.invitation(user)
        if not row:
            return
        with self.store.db:
            self.store.db.execute(
                "UPDATE global_invitations SET status=? WHERE user_id=?",
                (status, str(user)),
            )
        if not row["message_id"]:
            return
        try:
            if message is None:
                channel = self.bot.get_channel(int(row["dm_channel_id"]))
                if channel is None:
                    channel = await self.bot.fetch_channel(int(row["dm_channel_id"]))
                if (
                    getattr(channel, "guild", None)
                    or not getattr(channel, "recipient", None)
                    or channel.recipient.id != int(user)
                ):
                    return
                message = await channel.fetch_message(int(row["message_id"]))
            if (
                str(message.id) != row["message_id"]
                or str(message.channel.id) != row["dm_channel_id"]
                or message.author.id != self.bot.user.id
                or message.webhook_id
            ):
                return
            await message.delete()
        except discord.NotFound:
            pass
        except (discord.HTTPException, aiohttp.ClientError, TimeoutError, OSError):
            return  # Retain the ID for a bounded retry; never post a public fallback.
        with self.store.db:
            self.store.db.execute(
                "UPDATE global_invitations SET message_id='',dm_channel_id='' WHERE user_id=? AND message_id=?",
                (str(user), row["message_id"]),
            )

    async def cleanup_private(self):
        with self.store.db:
            self.store.db.execute(
                "UPDATE global_invitations SET status='expired' WHERE status='pending' AND attempted<?",
                (self.store.clock() - 30 * 86400,),
            )
        for row in self.store.rows(
            "SELECT * FROM global_invitations WHERE status IN ('accepted','declined','expired') AND message_id<>'' LIMIT 5"
        ):
            await self.finish(row["user_id"], row["status"])

    def legacy_owned(self, message):
        if (
            not self.bot.user
            or message.author.id != self.bot.user.id
            or message.webhook_id
        ):
            return False
        components = getattr(message, "components", [])
        controls = any(
            str(item.get("custom_id", "")).startswith("global:v1:")
            for item in component_dicts(components)
        )
        text = visible_text(components) or message.content or ""
        return controls and (
            "Chat global" in text or "chat global" in text or "Conexão pausada" in text
        )

    async def cleanup_public(self, cfg):
        """Only delete positively identified bot notices, never conversation copies."""
        channel = self.relay.channel(cfg["channel_id"])
        if not self.relay.readable(channel):
            return
        known = []
        if cfg["panel_id"]:
            known.append(cfg["panel_id"])
        known.extend(
            row["notice_id"]
            for row in self.store.rows(
                "SELECT notice_id FROM global_prompts WHERE guild_id=? AND channel_id=? LIMIT 20",
                (cfg["guild_id"], cfg["channel_id"]),
            )
        )
        for ident in known:
            try:
                message = await channel.fetch_message(int(ident))
                if self.legacy_owned(message):
                    await message.delete()
            except discord.NotFound:
                pass
            except discord.HTTPException:
                return
            with self.store.db:
                self.store.db.execute(
                    "UPDATE global_channels SET panel_id=NULL WHERE panel_id=?",
                    (str(ident),),
                )
                self.store.db.execute(
                    "DELETE FROM global_prompts WHERE notice_id=?", (str(ident),)
                )
        key = "global-private-ui-migration:" + cfg["channel_id"]
        cursor = self.bot.store.get(key)
        if cursor == "done":
            return
        cutoff = max(cfg["enabled_at"], self.store.clock() - 7 * 86400)
        kwargs = {
            "limit": 50,
            "oldest_first": False,
            "after": datetime.fromtimestamp(cutoff, timezone.utc),
        }
        if cursor:
            kwargs["before"] = discord.Object(id=int(cursor))
        count, last = 0, None
        try:
            async for message in channel.history(**kwargs):
                if self.legacy_owned(message):
                    await message.delete()
                count += 1
                last = message.id
        except discord.HTTPException:
            return
        self.bot.store.set(key, str(last) if count == 50 else "done")
