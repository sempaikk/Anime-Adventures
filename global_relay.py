"""Human originals plus webhook copies, with durable receipts and bounded recovery."""

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from types import SimpleNamespace

import aiohttp
import discord

from global_store import GlobalStore, fingerprint
from global_media import GlobalMedia, cdn_url, filename

log = logging.getLogger("globalchat")
HOOK_NAME = "Anime Adventures · Global"
TESTER_IDS = frozenset({1401953040004550858})
REQUIRED = {
    "view_channel": "Ver canal",
    "send_messages": "Enviar mensagens",
    "read_message_history": "Ler histórico",
    "manage_webhooks": "Gerenciar webhooks",
    "attach_files": "Anexar arquivos",
}


def clean_name(value, limit):
    text = re.sub(
        r"[\x00-\x1f\x7f\u200b-\u200f\u202a-\u202e\u2066-\u2069]", "", str(value)
    )
    value = re.sub(
        "discord|clyde",
        lambda m: m.group().casefold().replace("i", "1").replace("y", "1"),
        text,
        flags=re.I,
    )
    return value.encode("utf-16-le")[: limit * 2].decode("utf-16-le", errors="ignore")


def relay_name(bot, author):
    """Reserved account labels are computed from IDs, never from a nickname/role."""
    label = (
        "Owner"
        if bot.is_owner_id(author.id)
        else "Tester"
        if author.id in TESTER_IDS
        else ""
    )

    def identity(value, size):
        value = re.sub(
            r"\[\s*(?:owner|tester)\s*\]", "", str(value), flags=re.I
        ).strip()
        return clean_name(value, size) or "usuário"

    display = identity(author.display_name, 70 if label else 80)
    return display + (f" [{label}]" if label else "")


def text_content(message):
    text = message.content or ""
    users = {
        str(u.id): clean_name(u.display_name, 40)
        for u in getattr(message, "mentions", [])
    }
    roles = {
        str(r.id): clean_name(r.name, 40) for r in getattr(message, "role_mentions", [])
    }
    text = re.sub(r"<@!?(\d+)>", lambda m: "@" + users.get(m[1], "usuário"), text)
    text = re.sub(r"<@&(\d+)>", lambda m: "@" + roles.get(m[1], "cargo"), text)

    def channel(match):
        found = message.guild.get_channel(int(match[1]))
        return "#" + clean_name(found.name, 60) if found else "#canal"

    return re.sub(r"<#(\d+)>", channel, text)


def chunks(text, limit=1900):
    # Discord's webhook limit is 2,000 characters, including reply context.
    # Nitro-length originals are delivered as consecutive parts.
    result = []
    while len(text.encode("utf-16-le")) // 2 > limit:
        units = 0
        boundary = 0
        for character in text:
            cost = 2 if ord(character) > 0xFFFF else 1
            if units + cost > limit:
                break
            units += cost
            boundary += 1
        end = max(text.rfind("\n", 0, boundary), text.rfind(" ", 0, boundary))
        if end < boundary // 2:
            end = boundary
        result.append(text[:end])
        text = text[end:]
    result.append(text)
    return result


class GlobalRelay:
    def __init__(self, bot):
        self.bot = bot
        self.store = GlobalStore(bot.store)
        from global_onboarding import GlobalOnboarding

        self.onboarding = GlobalOnboarding(self)
        self.session = None
        self.media = GlobalMedia(bot.directory, self.http_session)
        self.upload_slots = asyncio.Semaphore(2)
        self.cycle_lock = asyncio.Lock()
        self.source_locks = {}
        self.tasks = set()
        self.round = 0
        self.recovery_index = 0
        self.last_recovery = 0
        self.last_maintenance = 0
        self.closed = False

    async def http_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=90), trust_env=True
            )
        return self.session

    def channel(self, ident):
        return self.bot.get_channel(int(ident))

    def readable(self, channel):
        if (
            channel is None
            or not getattr(channel, "guild", None)
            or not channel.guild.me
        ):
            return False
        p = channel.permissions_for(channel.guild.me)
        return bool(p.view_channel and p.read_message_history)

    def webhook(self, ident):
        record = self.store.hook(ident)
        if not record:
            raise ValueError(
                "A conexão deste canal precisa ser reparada pela administração."
            )
        hook = discord.Webhook.partial(
            int(record["hook_id"]), record["token"], client=self.bot
        )
        # discord.py's partial constructor does not inherit the client's proxy.
        # Keep webhook requests on the same transport as the connected bot.
        hook.proxy = self.bot.http.proxy
        hook.proxy_auth = self.bot.http.proxy_auth
        return hook

    async def activate(self, channel):
        if not isinstance(channel, discord.TextChannel):
            raise ValueError("Escolha um canal de texto do servidor.")
        if channel.is_nsfw():
            raise ValueError(
                "O chat global desta rede é para canais sem restrição de idade."
            )
        missing = [
            name
            for attr, name in REQUIRED.items()
            if not getattr(channel.permissions_for(channel.guild.me), attr, False)
        ]
        if missing:
            raise ValueError(
                "Permissões necessárias neste canal: " + ", ".join(missing) + "."
            )
        if self.store.blocked(0, channel.guild.id):
            raise ValueError(
                "Este servidor está bloqueado na rede. Fale com o responsável pelo bot."
            )
        panel = next(
            (
                p
                for p in self.bot.store.panels()
                if str(p["channel_id"]) == str(channel.id)
            ),
            None,
        )
        if panel or any(
            str(t["thread_id"]) == str(channel.id)
            for t in self.bot.store.thread_targets()
        ):
            raise ValueError(
                "Use um canal diferente do painel e do histórico da tier list."
            )
        hooks = await channel.webhooks()
        hook = next(
            (
                h
                for h in hooks
                if h.name == HOOK_NAME
                and h.user
                and self.bot.user
                and h.user.id == self.bot.user.id
                and h.token
            ),
            None,
        )
        if hook is None:
            hook = await channel.create_webhook(
                name=HOOK_NAME,
                reason="Chat global ativado pela administração do servidor",
            )
        if not hook.token:
            raise ValueError(
                "O Discord não forneceu acesso ao webhook. Tente novamente."
            )
        previous = self.store.channel(channel.guild.id)
        if previous:
            await self.onboarding.cleanup_public(previous)
        cursor = discord.utils.time_snowflake(discord.utils.utcnow())
        self.store.configure(channel.guild.id, channel.id, hook.id, hook.token, cursor)
        await self.onboarding.cleanup_public(self.store.channel(channel.guild.id))

    async def notice(self, message, text, *, join=False):
        await self.onboarding.notice(message, text, join=join)

    def serialize(self, message):
        body = text_content(message)
        assets = []
        warnings = []
        for item in message.attachments:
            assets.append(
                {
                    "id": str(item.id),
                    "url": item.url,
                    "filename": filename(item.filename),
                    "size": item.size,
                }
            )
        for sticker in getattr(message, "stickers", []):
            if sticker.format == discord.StickerFormatType.lottie:
                warnings.append(
                    "Figurinha "
                    + clean_name(sticker.name, 60)
                    + " (formato nativo indisponível nos outros servidores)"
                )
            else:
                extension = (
                    "gif" if sticker.format == discord.StickerFormatType.gif else "png"
                )
                assets.append(
                    {
                        "id": str(sticker.id),
                        "url": str(sticker.url),
                        "filename": f"figurinha-{sticker.id}.{extension}",
                        "size": 0,
                    }
                )
        if warnings:
            body += "\n" + "\n".join(warnings)
        if not body.strip() and not assets:
            raise ValueError(
                "Envie texto ou anexos. Enquetes e encaminhamentos nativos não são copiados pelo chat global."
            )
        reference = getattr(message, "reference", None)
        replied = (
            self.store.resolve(
                message.guild.id, message.channel.id, reference.message_id
            )
            if reference and reference.message_id
            else None
        )
        username = relay_name(self.bot, message.author)
        avatar = str(message.author.display_avatar.url)
        if not cdn_url(avatar):
            avatar = None
        data = {
            "body": body,
            "files": assets,
            "username": username,
            "avatar": avatar,
            "reply": replied["id"] if replied else None,
        }
        data["fingerprint"] = fingerprint(
            {
                "body": body,
                "files": [{k: v for k, v in a.items() if k != "url"} for a in assets],
                "reply": data["reply"],
            }
        )
        return data

    async def ingest(self, message, *, recovery=False, confirmed_first=False):
        if self.closed or not message.guild or message.author.bot or message.webhook_id:
            return
        cfg = self.store.source(message.channel.id)
        if (
            not cfg
            or cfg["guild_id"] != str(message.guild.id)
            or not self.readable(message.channel)
        ):
            return
        if not self.store.message(message.id) and (
            message.created_at.timestamp() < cfg["enabled_at"]
            or self.store.clock() - message.created_at.timestamp() > 3600
        ):
            return
        if self.store.blocked(message.author.id, message.guild.id):
            return
        if not self.store.consented(message.author.id):
            if not recovery:
                try:
                    self.bot.require_human(
                        SimpleNamespace(user=message.author, guild_id=message.guild.id)
                    )
                except ValueError:
                    return
                await self.notice(
                    message,
                    "## Participe do chat global\nSuas mensagens ficam neste servidor até você confirmar. Ao participar, o que escrever neste canal será compartilhado com toda a rede de servidores. Abra a confirmação abaixo.",
                    join=True,
                )
            return
        if not self.store.message(message.id) and not confirmed_first:
            accepted = self.store.one(
                "SELECT accepted FROM global_consents WHERE user_id=?",
                (str(message.author.id),),
            )
            if not accepted or message.created_at.timestamp() < accepted["accepted"]:
                return
        task = asyncio.current_task()
        self.tasks.add(task)
        entry = self.source_locks.setdefault(
            str(message.id), SimpleNamespace(lock=asyncio.Lock(), users=0)
        )
        entry.users += 1
        prepared_assets = []
        try:
            async with entry.lock:
                self.bot.require_human(
                    SimpleNamespace(user=message.author, guild_id=message.guild.id)
                )
                data = self.serialize(message)
                old = self.store.message(message.id)
                if not old:
                    if not self.store.limit("send:" + str(message.author.id), 6, 10):
                        raise ValueError(
                            "Você enviou mensagens muito rápido. Aguarde alguns segundos; a original continua neste canal."
                        )
                    if not self.store.limit(
                        "duplicate:" + str(message.author.id),
                        20,
                        60,
                        data["fingerprint"],
                    ):
                        raise ValueError(
                            "Essa mensagem já foi enviada recentemente. Evite repetir o mesmo conteúdo."
                        )
                row, changed = self.store.accept(
                    message, data, confirmed_first=confirmed_first
                )
                preparing = self.store.one(
                    "SELECT 1 FROM global_deliveries WHERE source_id=? AND state='preparing'",
                    (str(message.id),),
                )
                if not changed and not preparing:
                    return
                if self.bot.health.storage_level == "critical":
                    raise ValueError(
                        "O compartilhamento de anexos está temporariamente indisponível. A original foi preservada."
                    )
                targets = [
                    self.channel(d["channel_id"])
                    for d in self.store.rows(
                        "SELECT channel_id FROM global_deliveries WHERE source_id=?",
                        (row["id"],),
                    )
                ]
                limit = max(
                    [
                        getattr(c.guild, "filesize_limit", 10 * 1024 * 1024)
                        for c in targets
                        if c and c.guild
                    ]
                    + [getattr(message.guild, "filesize_limit", 10 * 1024 * 1024)]
                )
                async with self.upload_slots:
                    for asset in data["files"]:
                        prepared_assets.append(await self.media.download(asset, limit))
                    data["files"] = prepared_assets
                if (
                    not self.readable(message.channel)
                    or not self.store.source(message.channel.id)
                    or not self.store.consented(message.author.id)
                ):
                    raise ValueError(
                        "O compartilhamento foi interrompido. A original permanece no servidor."
                    )
                # A deleted/edited source while downloading must not publish stale bytes.
                fresh = await message.channel.fetch_message(message.id)
                if self.serialize(fresh)["fingerprint"] != data["fingerprint"]:
                    return
                self.store.prepared(row["id"], data, row["revision"])
        except discord.NotFound:
            self.store.erase(message.id)
        except (
            ValueError,
            discord.HTTPException,
            aiohttp.ClientError,
            TimeoutError,
            OSError,
        ) as error:
            reason = (
                str(error)
                if isinstance(error, ValueError)
                else "Não foi possível preparar o compartilhamento. A mensagem original foi preservada."
            )
            self.store.failed(message.id, reason)
            if not recovery:
                await self.notice(message, reason)
        finally:
            self.media.release(prepared_assets)
            self.tasks.discard(task)
            entry.users -= 1
            if not entry.users:
                self.source_locks.pop(str(message.id), None)

    async def original(self, row):
        channel = self.channel(row["channel_id"])
        cfg = self.store.source(row["channel_id"])
        if not cfg or cfg["guild_id"] != row["guild_id"] or not self.readable(channel):
            raise ValueError("A origem deixou de estar disponível para a rede.")
        message = await channel.fetch_message(int(row["id"]))
        if (
            str(message.author.id) != row["user_id"]
            or message.author.bot
            or message.webhook_id
        ):
            raise ValueError("A autoria da mensagem original não foi confirmada.")
        return message

    def parts(self, row, target):
        data = json.loads(row["payload"])
        body = data.get("body", "")
        replied = self.store.message(data.get("reply")) if data.get("reply") else None
        if (
            replied
            and not replied["deleted"]
            and not self.store.blocked(
                replied["user_id"], target.guild.id, replied["guild_id"]
            )
        ):
            prior = json.loads(replied["payload"])
            quote = discord.utils.escape_markdown(
                prior.get("body", "").replace("\n", " ")[:140]
            )
            if quote:
                body = "> " + quote + "\n" + body
            else:
                receipt = self.store.delivery(replied["id"], target.id)
                ids = json.loads(receipt["receipts"]) if receipt else []
                ident = (
                    replied["id"]
                    if replied["channel_id"] == str(target.id)
                    else next((x for x in ids if x), None)
                )
                if ident:
                    body = (
                        f"> [Resposta a uma mensagem](https://discord.com/channels/{target.guild.id}/{target.id}/{ident})\n"
                        + body
                    )
        assets = data.get("files", [])
        oversized = [
            a["filename"]
            for a in assets
            if a.get("oversize") or a["size"] > target.guild.filesize_limit
        ]
        if oversized:
            body += (
                "\n-# Anexo acima do limite deste servidor: "
                + ", ".join(oversized)[:300]
            )
        usable = [
            a
            for a in assets
            if not a.get("oversize") and a["size"] <= target.guild.filesize_limit
        ]
        texts = chunks(body)
        count = max(len(texts), (len(usable) + 9) // 10)
        return [
            {
                "content": texts[n] if n < len(texts) else "",
                "files": usable[n * 10 : (n + 1) * 10],
            }
            for n in range(count)
        ]

    async def reconcile_uncertain(self, job, row, target):
        part = job["uncertain"]
        expected = json.loads(job["attempt_payload"])
        if part < 0 or not expected:
            self.store.retry(
                job,
                "A tentativa anterior não pôde ser identificada; conferência necessária.",
                terminal=True,
            )
            return False
        after = datetime.fromtimestamp(max(0, job["attempted"] - 5), timezone.utc)
        matches = []
        async for message in target.history(limit=100, after=after):
            if str(message.webhook_id) != job["hook_id"]:
                continue
            actual = {
                "content": message.content,
                "username": message.author.name,
                "files": [
                    {"filename": a.filename, "size": a.size}
                    for a in message.attachments
                ],
            }
            if fingerprint(actual) == expected["fingerprint"]:
                matches.append(message)
        if len(matches) == 1:
            self.store.save_receipt(job, part, matches[0].id)
            with self.store.db:
                self.store.db.execute(
                    "UPDATE global_deliveries SET state='queued',next_try=0 WHERE source_id=? AND channel_id=?",
                    (job["source_id"], job["channel_id"]),
                )
            return True
        # No blind retry: execute-webhook has no idempotency key. Avoid duplication
        # when the remote server might have accepted a request with a lost ACK.
        self.store.retry(
            job,
            "Entrega não confirmada; preservada para conferência, sem reenviar às cegas.",
            uncertain=part,
            terminal=job["attempts"] >= 6,
        )
        return False

    async def deliver(self, job):
        row = self.store.message(job["source_id"])
        if not row:
            return
        if not row["deleted"] and self.store.clock() - row["updated"] > 3600:
            self.store.retry(
                job, "A fila expirou após uma hora; original preservada.", terminal=True
            )
            return
        receipts = json.loads(job["receipts"])
        try:
            hook = self.webhook(job["hook_id"])
            if row["deleted"] and job["uncertain"] >= 0:
                target = self.channel(job["channel_id"])
                if not self.readable(target):
                    raise ValueError(
                        "Sem acesso ao destino para localizar a cópia pendente de remoção."
                    )
                await self.reconcile_uncertain(job, row, target)
                return
            if row["deleted"] or job["suppressed"]:
                for ident in receipts:
                    if ident:
                        try:
                            await hook.delete_message(int(ident))
                        except discord.NotFound:
                            pass
                self.store.finish(job, row["revision"], [], state="deleted")
                return
            cfg = self.store.source(job["channel_id"])
            target = self.channel(job["channel_id"])
            if (
                not cfg
                or cfg["hook_id"] != job["hook_id"]
                or not self.readable(target)
                or self.store.blocked(row["user_id"], job["guild_id"], row["guild_id"])
                or not self.store.consented(row["user_id"])
            ):
                self.store.finish(job, row["revision"], receipts, state="cancelled")
                return
            original = await self.original(row)
            live = self.serialize(original)
            if live["fingerprint"] != row["fingerprint"]:
                await self.ingest(original, recovery=True)
                return
            if job["state"] == "uncertain":
                await self.reconcile_uncertain(job, row, target)
                return
            data = json.loads(row["payload"])
            if data:
                data["username"] = live["username"]
            if not data:
                with self.store.db:
                    self.store.db.execute(
                        "UPDATE global_deliveries SET state='preparing' WHERE source_id=? AND state='queued'",
                        (row["id"],),
                    )
                await self.ingest(original, recovery=True)
                return
            parts = self.parts(row, target)
            try:
                for asset in data.get("files", []):
                    if not asset.get("oversize"):
                        self.media.path(asset)
            except ValueError:
                with self.store.db:
                    self.store.db.execute(
                        "UPDATE global_deliveries SET state='preparing' WHERE source_id=? AND state='queued'",
                        (row["id"],),
                    )
                await self.ingest(original, recovery=True)
                return
            for index, part in enumerate(parts):
                current = self.store.message(row["id"])
                if current["deleted"] or current["revision"] != row["revision"]:
                    return
                active = self.store.source(job["channel_id"])
                delivery = self.store.delivery(job["source_id"], job["channel_id"])
                if (
                    not active
                    or active["hook_id"] != job["hook_id"]
                    or delivery["state"] == "cancelled"
                    or delivery["suppressed"]
                    or not self.store.source(row["channel_id"])
                    or not self.readable(original.channel)
                    or not self.store.consented(row["user_id"])
                    or self.store.blocked(
                        row["user_id"], job["guild_id"], row["guild_id"]
                    )
                ):
                    return
                if not all(
                    getattr(target.permissions_for(target.guild.me), flag, False)
                    for flag in REQUIRED
                ):
                    raise ValueError(
                        "A administração precisa conferir as permissões do bot neste canal."
                    )
                files, _ = self.media.files(part["files"], target.guild.filesize_limit)
                existing = receipts[index] if index < len(receipts) else None
                try:
                    if existing:
                        try:
                            await hook.edit_message(
                                int(existing),
                                content=part["content"],
                                attachments=files,
                                allowed_mentions=discord.AllowedMentions.none(),
                            )
                        except discord.NotFound:
                            # A removed copy is a moderation decision, never resurrect it.
                            self.store.suppress(
                                job["guild_id"], job["channel_id"], existing
                            )
                            return
                    else:
                        attempt = {
                            "fingerprint": fingerprint(
                                {
                                    "content": part["content"],
                                    "username": data["username"],
                                    "files": [
                                        {"filename": a["filename"], "size": a["size"]}
                                        for a in part["files"]
                                    ],
                                }
                            )
                        }
                        with self.store.db:
                            self.store.db.execute(
                                "UPDATE global_deliveries SET state='sending',uncertain=?,attempted=?,attempt_payload=? WHERE source_id=? AND channel_id=?",
                                (
                                    index,
                                    self.store.clock(),
                                    json.dumps(attempt),
                                    row["id"],
                                    job["channel_id"],
                                ),
                            )
                        try:
                            sent = await hook.send(
                                part["content"] or None,
                                username=data["username"],
                                **(
                                    {"avatar_url": data["avatar"]}
                                    if data.get("avatar")
                                    else {}
                                ),
                                files=files,
                                allowed_mentions=discord.AllowedMentions.none(),
                                wait=True,
                            )
                        except (
                            TimeoutError,
                            aiohttp.ClientError,
                            discord.DiscordServerError,
                        ):
                            self.store.retry(
                                job,
                                "O Discord não confirmou a publicação.",
                                uncertain=index,
                            )
                            return
                        if not sent or not getattr(sent, "id", None):
                            self.store.retry(
                                job,
                                "O Discord não confirmou a publicação.",
                                uncertain=index,
                            )
                            return
                        self.store.save_receipt(job, index, sent.id)
                        while len(receipts) <= index:
                            receipts.append(None)
                        receipts[index] = str(sent.id)
                finally:
                    for file in files:
                        file.close()
            for ident in receipts[len(parts) :]:
                if ident:
                    with self.store.db:
                        self.store.db.execute(
                            "DELETE FROM global_receipts WHERE message_id=?",
                            (str(ident),),
                        )
                    try:
                        await hook.delete_message(int(ident))
                    except discord.NotFound:
                        pass
            partial = any(
                a.get("oversize") or a["size"] > target.guild.filesize_limit
                for a in data.get("files", [])
            )
            self.store.finish(
                job,
                row["revision"],
                receipts[: len(parts)],
                state="partial" if partial else "sent",
            )
        except discord.NotFound:
            # An absent original cancels every destination, an absent webhook
            # is a local connection problem. Distinguish using the stored source.
            try:
                await self.original(row)
            except discord.NotFound:
                self.store.erase(row["id"])
            except ValueError:
                self.store.retry(job, "A origem ficou indisponível.", terminal=True)
            else:
                self.store.retry(
                    job,
                    "O webhook precisa ser reparado pela administração.",
                    terminal=True,
                )
        except (
            discord.HTTPException,
            aiohttp.ClientError,
            TimeoutError,
            ValueError,
            OSError,
        ) as error:
            status = getattr(error, "status", 0)
            reason = (
                str(error)
                if isinstance(error, ValueError)
                else f"Falha de entrega (HTTP {status}). A original foi preservada."
            )
            self.store.retry(
                job,
                reason,
                terminal=status in (400, 401, 403, 404, 413) or job["attempts"] >= 5,
            )

    async def on_edit(self, event):
        row = self.store.message(event.message_id)
        if not row or row["deleted"]:
            return
        if not any(
            k in event.data for k in ("content", "attachments", "sticker_items")
        ):
            return
        try:
            await self.ingest(await self.original(row), recovery=True)
        except discord.NotFound:
            self.store.erase(row["id"])
        except (discord.HTTPException, ValueError):
            pass

    def on_delete(self, event):
        with self.store.db:
            self.store.db.execute(
                "UPDATE global_channels SET panel_id=NULL WHERE panel_id=?",
                (str(event.message_id),),
            )
        row = self.store.message(event.message_id)
        if row:
            self.store.erase(row["id"])
        else:
            copied = self.store.one(
                "SELECT * FROM global_receipts WHERE message_id=?",
                (str(event.message_id),),
            )
            if copied:
                original = self.store.message(copied["source_id"])
                if original and not original["deleted"]:
                    self.store.suppress(
                        copied["guild_id"], copied["channel_id"], event.message_id
                    )

    async def recover(self):
        await self.onboarding.cleanup_private()
        configs = self.store.channels()
        for _ in range(min(5, len(configs))):
            cfg = configs[self.recovery_index % len(configs)]
            self.recovery_index += 1
            channel = self.channel(cfg["channel_id"])
            if self.readable(channel):
                try:
                    await self.onboarding.cleanup_public(cfg)
                    if not cfg["active"]:
                        continue
                    async for message in channel.history(
                        limit=30,
                        after=discord.Object(
                            id=max(
                                int(cfg["cursor"]),
                                discord.utils.time_snowflake(
                                    datetime.fromtimestamp(
                                        self.store.clock() - 3600, timezone.utc
                                    )
                                ),
                            )
                        ),
                        oldest_first=True,
                    ):
                        await self.ingest(message, recovery=True)
                        with self.store.db:
                            self.store.db.execute(
                                "UPDATE global_channels SET cursor=? WHERE guild_id=?",
                                (str(message.id), cfg["guild_id"]),
                            )
                except (discord.HTTPException, ValueError):
                    pass
        for row in self.store.rows(
            "SELECT m.* FROM global_messages m WHERE m.deleted=0 AND m.expires>? AND (m.checked<? OR EXISTS(SELECT 1 FROM global_deliveries d WHERE d.source_id=m.id AND d.state='preparing')) ORDER BY m.checked LIMIT 5",
            (self.store.clock(), self.store.clock() - 300),
        ):
            try:
                message = await self.original(row)
                await self.ingest(message, recovery=True)
            except discord.NotFound:
                self.store.erase(row["id"])
            except (discord.HTTPException, ValueError):
                pass
            with self.store.db:
                self.store.db.execute(
                    "UPDATE global_messages SET checked=? WHERE id=?",
                    (self.store.clock(), row["id"]),
                )

    async def cycle(self):
        if self.cycle_lock.locked():
            return
        async with self.cycle_lock:
            if self.store.clock() - self.last_maintenance >= 60:
                self.maintenance()
                self.last_maintenance = self.store.clock()
            for job in self.store.jobs(limit=8):
                try:
                    await asyncio.wait_for(self.deliver(job), 90)
                except TimeoutError:
                    current = self.store.delivery(job["source_id"], job["channel_id"])
                    self.store.retry(
                        current,
                        "Tempo de entrega excedido; original preservada.",
                        uncertain=current["uncertain"],
                    )
                except Exception as error:
                    log.warning("Entrega global adiada: %s", type(error).__name__)
            self.round += 1
            if self.store.clock() - self.last_recovery >= 10:
                await self.recover()
                self.last_recovery = self.store.clock()

    def maintenance(self):
        self.store.cleanup()
        active = set()
        for row in self.store.rows(
            "SELECT DISTINCT m.payload FROM global_messages m JOIN global_deliveries d ON d.source_id=m.id WHERE d.state IN ('queued','preparing','uncertain','sending')"
        ):
            active.update(
                a["digest"]
                for a in json.loads(row["payload"]).get("files", [])
                if a.get("digest")
            )
        self.media.cleanup(active)

    async def close(self):
        self.closed = True
        tasks = [
            t for t in self.tasks if t is not asyncio.current_task() and not t.done()
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self.session:
            await self.session.close()
