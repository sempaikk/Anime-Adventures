"""One image and one persistent discussion thread; exactly two slash commands."""

from __future__ import annotations
import asyncio
import hashlib
import json
import logging
import os
import signal
import shutil
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks
from discord.http import handle_message_parameters
from dotenv import load_dotenv
from community_domain import Catalog
from runtime_health import RuntimeHealth
from tier_analysis import DAILY_CALLS, DAILY_TOKENS, TierAnalyzer
from tier_backup import acquire_lease, maintain_tier_storage
from tier_domain import digest, relevant_units, safe, moment
from tier_image import PanelRenderer, image_file, index_text, poll_embed
from tier_media import MediaLibrary, MAX_UPLOAD
from tier_store import TierStore
from tier_views import AdminView, PollView, ThreadView, reply
from tier_wiki import WikiSync

log = logging.getLogger("tierlist")
PERMISSIONS = {
    "view_channel": "Ver canal",
    "send_messages": "Enviar mensagens",
    "embed_links": "Inserir links",
    "attach_files": "Anexar arquivos",
    "read_message_history": "Ler histórico",
    "create_public_threads": "Criar tópicos públicos",
    "send_messages_in_threads": "Enviar mensagens em tópicos",
}


class CommunityBot(commands.Bot):
    def __init__(self, data_dir=None, *, backend=None):
        intents = discord.Intents.none()
        intents.guilds = intents.guild_messages = intents.message_content = True
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            help_command=None,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        self.directory = Path(data_dir or os.getenv("DATA_DIR", "state"))
        self.lease = acquire_lease(self.directory)
        try:
            self.store = TierStore(self.directory / "tierlist.sqlite3")
        except BaseException:
            self.lease.close()
            raise
        self.catalog = Catalog(
            min_mention_length=3,
            extra_aliases={"gyutaro": ["Giltaro", "Gyuutaro", "Gyuutarou"]},
        )
        self.media = MediaLibrary(self.store, self.catalog)
        self.analyzer = TierAnalyzer(
            self.store,
            self.catalog,
            backend=backend,
            source_guard=self.purge_inaccessible_sources,
        )
        self.wiki = WikiSync(self.store, self.catalog, self.analyzer.evidence)
        self.renderer = PanelRenderer(self.media.root)
        self.render_lock = asyncio.Lock()
        self.analysis_lock = asyncio.Lock()
        self.verification_lock = asyncio.Lock()
        self.verification_tasks = set()
        self.history_import_lock = asyncio.Lock()
        self.active_history_import = None
        self.image_slots = asyncio.Semaphore(1)
        self.upload_slots = self.image_slots
        self.guild_locks = {}
        self.health = RuntimeHealth(self.is_ready, lambda: self.store.connection)
        self.owner_ids_set = set()
        self.store.connection.execute(
            "CREATE TABLE IF NOT EXISTS tier_deliveries(key TEXT PRIMARY KEY,channel_id TEXT NOT NULL,message_id TEXT NOT NULL,created_at REAL NOT NULL)"
        )
        self.store.connection.commit()
        self.register_commands()

    def is_owner_id(self, actor):
        return actor in self.owner_ids_set

    def require_owner(self, i):
        if not self.is_owner_id(i.user.id):
            raise ValueError("Esta revisão global é exclusiva do responsável pelo bot.")

    def require_admin(self, i):
        if not i.guild_id or not i.permissions.manage_guild:
            raise ValueError(
                "Você precisa de Gerenciar servidor para publicar o painel."
            )

    def require_human(self, i):
        if (
            not i.guild_id
            or i.user.bot
            or (discord.utils.utcnow() - i.user.created_at).total_seconds() < 7 * 86400
        ):
            raise ValueError(
                "Use uma conta de pessoa com pelo menos sete dias para participar."
            )

    def require_thread(self, i, *, index_only=False):
        thread = self.store.thread(i.guild_id)
        if (
            not thread
            or str(i.channel_id) != thread["thread_id"]
            or thread["status"] != "ok"
            or (index_only and str(i.message.id) != thread["intro_id"])
        ):
            raise ValueError("Abra esse recurso no tópico oficial ligado à tier list.")

    def media_available(self):
        if self.health.storage_level == "critical":
            raise ValueError(
                "O armazenamento precisa de atenção. Os envios foram pausados para preservar o estado."
            )

    def guild_lock(self, guild_id):
        return self.guild_locks.setdefault(int(guild_id), asyncio.Lock())

    async def setup_hook(self):
        app = await self.application_info()
        self.owner_ids_set = {app.team.owner_id if app.team else app.owner.id}
        self.add_view(ThreadView(self))
        self.add_view(PollView(self))
        legacy = PollView(self)
        old_ids = {
            "tier:v3:approve": "tier:v2:vote:approve",
            "tier:v3:keep": "tier:v2:vote:keep",
            "tier:v3:test": "tier:v2:vote:test",
        }
        for item in list(legacy.children):
            if item.custom_id in old_ids:
                item.custom_id = old_ids[item.custom_id]
            else:
                legacy.remove_item(item)
        self.add_view(legacy)
        await self.health.start(
            int(os.getenv("PORT") or os.getenv("SERVER_PORT") or 8080)
        )
        await self.tree.sync()
        for loop in (
            self.history_loop,
            self.analysis_loop,
            self.poll_loop,
            self.panel_loop,
            self.maintenance_loop,
            self.wiki_loop,
        ):
            loop.start()
        log.info(
            "Sincronizados somente /tierlist e /chatglobal; imagem e tópico; IA %s.",
            "chave carregada" if self.analyzer.backend.enabled else "sem chave",
        )

    async def on_ready(self):
        for guild in self.guilds:
            self.store.register_guild(guild.id)
        actual = {str(g.id) for g in self.guilds}
        for row in self.store.rows("SELECT guild_id FROM tier_guilds"):
            if row["guild_id"] not in actual:
                self.store.remove_guild(row["guild_id"])
        log.info(
            "Conectado; %s servidores; aguardando relatos do jogo.", len(self.guilds)
        )
        await self.cleanup_old_notices()

    async def cleanup_old_notices(self):
        if self.store.get("legacy-notices-cleaned") == "1":
            return
        complete = True
        for row in self.store.channels():
            channel = self.get_channel(int(row["channel_id"]))
            if not channel:
                continue
            try:
                async for message in channel.history(limit=50):
                    if (
                        self.user
                        and message.author.id == self.user.id
                        and message.content.startswith(
                            "### Análise da tier list\nA administração ativou este canal como fonte"
                        )
                    ):
                        await message.delete()
            except discord.HTTPException:
                complete = False
        if complete:
            self.store.set("legacy-notices-cleaned", "1")

    async def on_guild_join(self, guild):
        self.store.register_guild(guild.id)

    async def on_guild_remove(self, guild):
        self.store.remove_guild(guild.id)
        self.guild_locks.pop(guild.id, None)

    async def on_message(self, message):
        self.collect_message(message)

    def collect_message(self, message):
        if (
            not message.guild
            or message.author.bot
            or message.webhook_id
            or not message.content
        ):
            return
        if getattr(
            message, "message_snapshots", None
        ) or message.content.lstrip().startswith((">", "```")):
            return
        if (
            discord.utils.utcnow() - message.author.created_at
        ).total_seconds() < 7 * 86400:
            return
        if self.health.storage_level == "critical":
            return
        channel = message.channel
        permissions = channel.permissions_for(message.guild.me)
        if not permissions.view_channel:
            return
        thread = self.store.thread(message.guild.id)
        if thread and str(channel.id) == thread["thread_id"]:
            return
        panel = next(
            (p for p in self.store.panels() if p["guild_id"] == str(message.guild.id)),
            None,
        )
        if panel and str(channel.id) == panel["channel_id"]:
            return
        units = relevant_units(self.catalog, message.content)
        if not units:
            return
        self.store.register_guild(message.guild.id)
        created_at = getattr(message, "created_at", None)
        return self.store.ingest(
            message.id,
            message.author.id,
            message.guild.id,
            channel.id,
            message.content,
            units,
            sent_at=created_at.timestamp() if created_at is not None else None,
        )

    async def on_raw_message_delete(self, event):
        if self.active_history_import:
            self.active_history_import.invalidate(event)
        with self.store.connection:
            self.store.connection.execute(
                "DELETE FROM tier_comments WHERE message_id=?", (str(event.message_id),)
            )
            self.store.connection.execute(
                "UPDATE tier_poll_messages SET status='removed' WHERE message_id=?",
                (str(event.message_id),),
            )
        # Deleted poll copies are respected. Panel repairs require an explicit /tierlist.

    async def on_raw_bulk_message_delete(self, event):
        for ident in event.message_ids:
            await self.on_raw_message_delete(SimpleNamespace(message_id=ident))

    async def on_raw_message_edit(self, event):
        if "content" in event.data:
            if self.active_history_import:
                self.active_history_import.invalidate(event)
            with self.store.connection:
                self.store.connection.execute(
                    "DELETE FROM tier_comments WHERE message_id=?",
                    (str(event.message_id),),
                )

    async def on_guild_channel_update(self, before, after):
        if not after.permissions_for(after.guild.me).view_channel:
            with self.store.connection:
                self.store.connection.execute(
                    "DELETE FROM tier_comments WHERE channel_id=?", (str(after.id),)
                )

    async def on_guild_channel_delete(self, channel):
        with self.store.connection:
            self.store.connection.execute(
                "DELETE FROM tier_comments WHERE channel_id=?", (str(channel.id),)
            )
            self.store.connection.execute(
                "UPDATE tier_threads SET status='missing' WHERE thread_id=?",
                (str(channel.id),),
            )

    async def on_thread_delete(self, thread):
        await self.on_guild_channel_delete(thread)

    def server_status(self, i):
        self.require_admin(i)
        panel = next(
            (p for p in self.store.panels() if p["guild_id"] == str(i.guild_id)), None
        )
        thread = self.store.thread(i.guild_id)
        if not panel or not thread:
            return "**Painel ainda não preparado.** Use /tierlist em um canal de texto e confira as permissões informadas."
        channel = self.get_channel(int(panel["channel_id"]))
        if not channel:
            return "**Painel indisponível.** Confira Ver canal e use /tierlist para preparar novamente o painel."
        if thread["status"] == "missing":
            return "**O tópico precisa de reparo.** Use /tierlist e siga a orientação para preparar novamente o painel."
        missing = [
            label
            for flag, label in PERMISSIONS.items()
            if channel
            and not getattr(channel.permissions_for(channel.guild.me), flag, False)
        ]
        from tier_history import history_status

        return (
            "**Painel deste servidor**\n"
            + f"[Ver imagem](https://discord.com/channels/{i.guild_id}/{panel['channel_id']}/{panel['message_id']}) · [Votações e histórico](https://discord.com/channels/{i.guild_id}/{thread['thread_id']})\n"
            + (
                "Confira estas permissões: " + ", ".join(missing) + "."
                if missing
                else "Painel preparado. Se o tópico estiver trancado, destranque para continuar as votações."
            )
            + "\n**Histórico do jogo:** "
            + history_status(self.store, i.guild_id)
        )

    def diagnostics(self, i):
        self.require_owner(i)
        latest = self.store.latest()
        key = "carregada" if self.analyzer.backend.enabled else "ausente"
        checked = self.store.get("last_connection_success")
        analysis = self.store.get("last_success")
        text = f"### Diagnóstico\n**Classificação:** versão {latest['id']} · {len(latest['ranking'])} unidades.\n**IA:** chave {key}.\n**Último teste de conexão válido:** {moment(float(checked)) if checked else 'ainda não realizado'}.\n**Última análise válida:** {moment(float(analysis)) if analysis else 'ainda não realizada'}.\n**Wiki:** {self.wiki.status}; {len(self.analyzer.evidence.sources)} referências.\n**Imagens para revisão:** {len(self.media.pending())}.\n**Banco:** {self.store.path.stat().st_size // 1024} KB.\n**Armazenamento:** {self.health.storage_level}."
        from tier_history import history_status

        text += "\n**Histórico do jogo:** " + history_status(self.store, i.guild_id)
        pending = self.store.rows(
            "SELECT COUNT(*) AS total FROM tier_comments WHERE processed=0 AND attempts<3 AND created_at>=?",
            (self.store.clock() - 7 * 86400,),
        )[0]["total"]
        budget = json.loads(self.store.get("budget") or "{}")
        day = datetime.fromtimestamp(self.store.clock(), timezone.utc).strftime(
            "%Y-%m-%d"
        )
        if budget.get("day") != day:
            budget = {}
        text += f"\n**Relatos aguardando análise:** {pending}."
        text += f"\n**Cota local do dia UTC:** {budget.get('calls', 0)}/{DAILY_CALLS} chamadas · {budget.get('tokens', 0)}/{DAILY_TOKENS} tokens."
        thread = self.store.thread(i.guild_id)
        if thread:
            text += f"\n**Tópico:** {thread['status']}."
        if self.is_owner_id(i.user.id):
            text += f"\n**Catálogo:** {len(self.catalog.units)} formas · {max(0, len(self.catalog.units) - len(latest['ranking']))} sem avaliação.\n**Retratos:** revisão {int(self.store.get('media_revision') or 0)}."
            text += f"\n**Backup:** {'falha na última tentativa; confira o armazenamento e exporte a cópia anterior' if self.health.backup_error else 'sem falha registrada'}."
            error = self.store.get("analysis_error")
            if error:
                text += f"\n**Última falha de análise:** {safe(error, 80)}."
            text += "\nUse Testar conexão da IA para validar a resposta real, sem mexer na classificação."
        return text

    async def read_upload(self, attachment):
        self.media_available()
        if not 0 < attachment.size <= MAX_UPLOAD:
            raise ValueError("Cada imagem deve ter no máximo 4 MB.")
        url = attachment.url
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname
            not in ("cdn.discordapp.com", "media.discordapp.net", "cdn.discordapp.net")
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
        ):
            raise ValueError("Envie o arquivo pelo formulário do Discord.")
        blob = bytearray()
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=20)
        ) as session:
            async with session.get(url, allow_redirects=False) as response:
                if response.status != 200:
                    raise ValueError(
                        "O anexo expirou. Abra o formulário e envie novamente."
                    )
                while chunk := await response.content.read(16384):
                    blob.extend(chunk)
                    if len(blob) > MAX_UPLOAD:
                        raise ValueError("A imagem excedeu 4 MB.")
        return bytes(blob)

    async def picture(self):
        publication = self.store.latest()
        overrides = self.media.approved()
        revision = int(self.store.get("media_revision") or 0)
        async with self.render_lock:
            async with self.image_slots:
                return await asyncio.to_thread(
                    self.renderer.get,
                    publication,
                    overrides,
                    revision,
                    len(self.catalog.units),
                )

    async def channel(self, channel_id):
        channel = self.get_channel(int(channel_id))
        return channel or await self.fetch_channel(int(channel_id))

    async def active_thread(self, panel):
        record = self.store.thread(panel["guild_id"])
        if not record:
            raise ValueError("Use /tierlist para preparar o tópico deste painel.")
        try:
            thread = await self.channel(record["thread_id"])
        except discord.NotFound:
            with self.store.connection:
                self.store.connection.execute(
                    "UPDATE tier_threads SET status='missing' WHERE guild_id=?",
                    (panel["guild_id"],),
                )
            raise ValueError(
                "O tópico foi removido. Use /tierlist para reparar o painel."
            )
        if not isinstance(thread, discord.Thread):
            raise ValueError("O destino não é o tópico oficial.")
        if thread.locked:
            raise ValueError(
                "O tópico está trancado. A administração precisa destrancá-lo para o bot continuar."
            )
        if thread.archived:
            await thread.edit(archived=False, reason="Continuar votações da tier list")
        permissions = thread.permissions_for(thread.guild.me)
        if not (
            permissions.view_channel
            and permissions.send_messages_in_threads
            and permissions.embed_links
            and permissions.attach_files
        ):
            raise ValueError(
                "Confira Ver canal, Inserir links, Anexar arquivos e Enviar mensagens em tópicos."
            )
        return thread

    async def deliver(self, channel, key, *, marker=None, **kwargs):
        receipt = self.store.rows(
            "SELECT message_id FROM tier_deliveries WHERE key=? AND channel_id=?",
            (key, str(channel.id)),
        )
        if receipt:
            return channel.get_partial_message(int(receipt[0]["message_id"]))
        # Nonces cover recent lost acknowledgments. A visible marker also reconciles delayed retries.
        attempted = self.store.get("delivery-attempt:" + key)
        if attempted and marker:
            async for message in channel.history(limit=100):
                if self.user and message.author.id == self.user.id and marker(message):
                    self.remember_delivery(key, channel.id, message.id)
                    return channel.get_partial_message(message.id)
        self.store.set("delivery-attempt:" + key, self.store.clock())
        nonce = str(int(hashlib.sha256(key.encode()).hexdigest()[:15], 16))
        with handle_message_parameters(
            nonce=nonce, allowed_mentions=discord.AllowedMentions.none(), **kwargs
        ) as params:
            if params.payload is not None:
                params.payload["enforce_nonce"] = True
            else:
                for part in params.multipart:
                    if part["name"] == "payload_json":
                        payload = json.loads(part["value"])
                        payload["enforce_nonce"] = True
                        part["value"] = json.dumps(payload)
            data = await self.http.send_message(channel.id, params=params)
        self.remember_delivery(key, channel.id, data["id"])
        return channel.get_partial_message(int(data["id"]))

    def remember_delivery(self, key, channel_id, message_id):
        with self.store.connection:
            self.store.connection.execute(
                "INSERT OR REPLACE INTO tier_deliveries VALUES(?,?,?,?)",
                (key, str(channel_id), str(message_id), self.store.clock()),
            )
            self.store.connection.execute(
                "DELETE FROM tier_meta WHERE key=?", ("delivery-attempt:" + key,)
            )

    def forget_delivery(self, key):
        with self.store.connection:
            self.store.connection.execute(
                "DELETE FROM tier_deliveries WHERE key=?", (key,)
            )

    async def ensure_panel(self, i):
        request_channel = (
            i.channel.parent if isinstance(i.channel, discord.Thread) else i.channel
        )
        if not isinstance(request_channel, discord.TextChannel):
            raise ValueError(
                "Use /tierlist em um canal de texto normal para criar a imagem e seu tópico."
            )
        panel = next(
            (p for p in self.store.panels() if p["guild_id"] == str(i.guild_id)), None
        )
        channel = request_channel
        message = None
        if panel:
            try:
                channel = await self.channel(panel["channel_id"])
                message = await channel.fetch_message(int(panel["message_id"]))
            except discord.NotFound:
                self.store.forget_panel(panel["channel_id"])
                old = self.store.thread(i.guild_id)
                if old:
                    self.store.set(
                        "previous-thread:" + str(i.guild_id), old["thread_id"]
                    )
                with self.store.connection:
                    self.store.connection.execute(
                        "DELETE FROM tier_threads WHERE guild_id=?", (str(i.guild_id),)
                    )
                panel = None
                channel = request_channel
        permissions = channel.permissions_for(i.guild.me)
        missing = [
            label
            for flag, label in PERMISSIONS.items()
            if not getattr(permissions, flag, False)
        ]
        if missing:
            raise ValueError(
                "Faltam estas permissões para o bot no canal do painel: "
                + ", ".join(missing)
                + "."
            )
        if not panel and len(self.store.panels()) >= 100:
            raise ValueError(
                "A capacidade desta instância está cheia. Os painéis existentes continuam disponíveis."
            )
        blob, checksum = await self.picture()
        if not message:
            generation = int(self.store.get("panel-generation:" + str(i.guild_id)) or 0)
            key = f"panel:{i.guild_id}:{generation}"
            file = image_file(blob)
            file.filename = (
                "tierlist-" + hashlib.sha256(key.encode()).hexdigest()[:12] + ".png"
            )
            try:
                message = await self.deliver(
                    channel,
                    key,
                    file=file,
                    marker=lambda m: any(
                        a.filename == file.filename for a in m.attachments
                    ),
                )
                try:
                    await message.fetch()
                except discord.NotFound:
                    self.forget_delivery(key)
                    self.store.set(
                        "panel-generation:" + str(i.guild_id), generation + 1
                    )
                    raise ValueError(
                        "A mensagem anterior foi apagada. Use /tierlist novamente para publicar uma nova."
                    )
            finally:
                file.close()
            self.store.remember_panel(
                i.guild_id, channel.id, message.id, self.store.latest()["id"]
            )
        record = self.store.thread(i.guild_id)
        thread = None
        if record and record["thread_id"] == str(message.id):
            try:
                thread = await self.channel(record["thread_id"])
            except discord.NotFound:
                pass
        if not thread:
            thread = channel.get_thread(message.id)
        if not thread:
            try:
                thread = await self.fetch_channel(message.id)
            except discord.NotFound:
                pass
        if not thread:
            try:
                thread = await message.create_thread(
                    name="Votações e histórico",
                    auto_archive_duration=1440,
                    reason="Histórico da tier list global",
                )
            except discord.HTTPException as error:
                if error.code == 160004:
                    raise ValueError(
                        "O tópico original foi removido. Apague a imagem antiga do bot e execute /tierlist novamente para recriar o conjunto."
                    ) from error
                raise
        if not isinstance(thread, discord.Thread):
            raise ValueError("Não consegui confirmar o tópico do painel.")
        self.store.remember_thread(i.guild_id, thread.id)
        panel = next(p for p in self.store.panels() if p["guild_id"] == str(i.guild_id))
        thread = await self.active_thread(panel)
        await self.sync_index(panel, thread)
        # Update old images on demand as well as through the background loop.
        record = self.store.thread(i.guild_id)
        if record["panel_hash"] != checksum:
            file = image_file(blob)
            try:
                await message.edit(
                    content=None, embeds=[], attachments=[file], view=None
                )
            finally:
                file.close()
            with self.store.connection:
                self.store.connection.execute(
                    "UPDATE tier_threads SET panel_hash=? WHERE guild_id=?",
                    (checksum, str(i.guild_id)),
                )
        return panel, thread

    async def sync_index(self, panel, thread):
        record = self.store.thread(panel["guild_id"])
        text = index_text(
            self.store,
            panel,
            wiki_status=self.wiki.status,
            ai_enabled=self.analyzer.backend.enabled,
        )
        if self.health.storage_level == "critical":
            text += "\n**Manutenção:** novas análises e imagens temporariamente pausadas. A classificação atual foi preservada."
        previous = self.store.get("previous-thread:" + panel["guild_id"])
        if previous and previous != str(thread.id):
            text += f"\n[Histórico do tópico anterior](https://discord.com/channels/{panel['guild_id']}/{previous})."
        signature = digest(text)
        if record["intro_id"] and record["index_hash"] == signature:
            return
        key = f"index:{thread.id}"
        message = None
        if record["intro_id"]:
            try:
                message = await thread.get_partial_message(
                    int(record["intro_id"])
                ).edit(
                    content=text,
                    embeds=[],
                    attachments=[],
                    view=ThreadView(self),
                )
            except discord.NotFound:
                self.forget_delivery(key)
        if message is None:
            message = await self.deliver(
                thread,
                key,
                content=text,
                view=ThreadView(self),
                marker=lambda m: m.content.startswith("## Votações e histórico"),
            )
        self.store.remember_thread(panel["guild_id"], thread.id, message.id)
        with self.store.connection:
            self.store.connection.execute(
                "UPDATE tier_threads SET index_hash=? WHERE guild_id=?",
                (signature, panel["guild_id"]),
            )

    def purge_inaccessible_sources(self):
        for row in self.store.rows(
            "SELECT DISTINCT channel_id,guild_id FROM tier_comments"
        ):
            channel = self.get_channel(int(row["channel_id"]))
            if (
                not channel
                or not channel.permissions_for(channel.guild.me).view_channel
            ):
                with self.store.connection:
                    self.store.connection.execute(
                        "DELETE FROM tier_comments WHERE channel_id=?",
                        (row["channel_id"],),
                    )

    @tasks.loop(seconds=20)
    async def analysis_loop(self):
        if (
            self.health.storage_level == "critical"
            or not self.store.thread_targets()
            or self.analysis_lock.locked()
            or self.history_import_lock.locked()
        ):
            return
        try:
            async with self.analysis_lock:
                self.purge_inaccessible_sources()
                await self.analyzer.run()
        except Exception as error:
            log.warning("Análise adiada: %s", type(error).__name__)

    @analysis_loop.before_loop
    async def analysis_ready(self):
        await self.wait_until_ready()

    @tasks.loop(seconds=30)
    async def history_loop(self):
        from tier_history import scan_next

        try:
            await scan_next(self)
        except Exception as error:
            log.warning("Leitura inicial adiada: %s", type(error).__name__)

    @history_loop.before_loop
    async def history_ready(self):
        await self.wait_until_ready()

    @tasks.loop(minutes=15)
    async def wiki_loop(self):
        if (
            self.health.storage_level == "critical"
            or self.analysis_lock.locked()
            or not self.store.thread_targets()
        ):
            return
        try:
            async with self.analysis_lock:
                units = [
                    u for c in self.store.pending(8) for u in json.loads(c["units"])
                ]
                await self.wiki.refresh(units)
        except Exception as error:
            log.warning("Fontes em cache preservadas: %s", type(error).__name__)

    @wiki_loop.before_loop
    async def wiki_ready(self):
        await self.wait_until_ready()

    async def _poll_cycle(self):
        self.store.resolve_due(source_version=self.analyzer.evidence.version)
        proposal = self.store.active_proposal()
        if proposal:
            for panel in self.store.thread_targets():
                if self.store.rows(
                    "SELECT 1 FROM tier_poll_messages WHERE proposal_id=? AND channel_id=?",
                    (proposal["id"], panel["thread_id"]),
                ):
                    continue
                try:
                    async with self.guild_lock(panel["guild_id"]):
                        proposal = self.store.proposal(proposal["id"])
                        if proposal["status"] not in ("queued", "open") or (
                            proposal["status"] == "open"
                            and self.store.clock() >= proposal["closes_at"]
                        ):
                            continue
                        if (
                            proposal["status"] == "open"
                            and proposal["closes_at"] - self.store.clock() < 60
                        ):
                            continue
                        thread = await self.active_thread(panel)
                        number = proposal["id"]
                        message = await self.deliver(
                            thread,
                            f"poll:{number}:{thread.id}",
                            embed=poll_embed(self.store, self.catalog, proposal),
                            view=PollView(self),
                            marker=lambda m: any(
                                e.footer.text
                                and e.footer.text.startswith(f"Proposta #{number} ·")
                                for e in m.embeds
                            ),
                        )
                        published = None
                        if message.id > 10**15:
                            published = discord.utils.snowflake_time(
                                message.id
                            ).timestamp()
                        self.store.remember_poll(
                            number,
                            panel["guild_id"],
                            thread.id,
                            message.id,
                            published_at=published,
                        )
                except (discord.HTTPException, ValueError, TimeoutError) as error:
                    log.warning("Enquete adiada: %s", type(error).__name__)
        self.store.resolve_due(source_version=self.analyzer.evidence.version)
        now = self.store.clock()
        for receipt in self.store.poll_messages():
            if receipt["status"] == "removed":
                continue
            proposal = self.store.proposal(receipt["proposal_id"])
            if not proposal:
                continue
            if receipt["status"] == proposal["status"] and (
                proposal["status"] not in ("open", "queued")
                or now - receipt["updated_at"] < 60
            ):
                continue
            panel = next(
                (
                    p
                    for p in self.store.panels()
                    if p["guild_id"] == receipt["guild_id"]
                ),
                None,
            )
            if not panel:
                continue
            try:
                async with self.guild_lock(panel["guild_id"]):
                    record = self.store.thread(panel["guild_id"])
                    if record and record["thread_id"] == receipt["channel_id"]:
                        thread = await self.active_thread(panel)
                    else:
                        # Finish pre-migration polls where they were originally published.
                        thread = await self.channel(receipt["channel_id"])
                        if str(thread.guild.id) != receipt["guild_id"]:
                            continue
                    await thread.get_partial_message(int(receipt["message_id"])).edit(
                        embed=poll_embed(self.store, self.catalog, proposal),
                        view=PollView(
                            self, closed=proposal["status"] not in ("open", "queued")
                        ),
                    )
                    self.store.remember_poll(
                        proposal["id"],
                        receipt["guild_id"],
                        receipt["channel_id"],
                        receipt["message_id"],
                        proposal["status"],
                    )
            except discord.NotFound:
                with self.store.connection:
                    self.store.connection.execute(
                        "UPDATE tier_poll_messages SET status='removed' WHERE proposal_id=? AND channel_id=?",
                        (proposal["id"], receipt["channel_id"]),
                    )
            except (discord.HTTPException, ValueError, TimeoutError) as error:
                log.warning("Resultado adiado: %s", type(error).__name__)

    @tasks.loop(seconds=15)
    async def poll_loop(self):
        try:
            await self._poll_cycle()
        except Exception as error:
            log.warning("Ciclo de votação adiado: %s", type(error).__name__)

    @poll_loop.before_loop
    async def poll_ready(self):
        await self.wait_until_ready()

    @tasks.loop(seconds=30)
    async def panel_loop(self):
        for panel in self.store.panels():
            try:
                async with self.guild_lock(panel["guild_id"]):
                    thread = await self.active_thread(panel)
                    blob, checksum = await self.picture()
                    record = self.store.thread(panel["guild_id"])
                    if record["panel_hash"] != checksum:
                        channel = await self.channel(panel["channel_id"])
                        file = image_file(blob)
                        try:
                            await channel.get_partial_message(
                                int(panel["message_id"])
                            ).edit(
                                content=None, embeds=[], attachments=[file], view=None
                            )
                        finally:
                            file.close()
                        with self.store.connection:
                            self.store.connection.execute(
                                "UPDATE tier_threads SET panel_hash=? WHERE guild_id=?",
                                (checksum, panel["guild_id"]),
                            )
                            self.store.connection.execute(
                                "UPDATE tier_panels SET publication_id=?,last_sent=? WHERE guild_id=?",
                                (
                                    self.store.latest()["id"],
                                    self.store.clock(),
                                    panel["guild_id"],
                                ),
                            )
                    await self.publish_audits(panel, thread)
                    await self.sync_index(panel, thread)
            except discord.NotFound:
                with self.store.connection:
                    self.store.connection.execute(
                        "UPDATE tier_threads SET status='missing' WHERE guild_id=?",
                        (panel["guild_id"],),
                    )
            except Exception as error:
                log.warning(
                    "Painel preservado, atualização adiada: %s", type(error).__name__
                )

    @panel_loop.before_loop
    async def panels_ready(self):
        await self.wait_until_ready()

    async def publish_audits(self, panel, thread):
        rows = self.store.rows(
            "SELECT a.* FROM tier_audit a WHERE a.created_at>=? AND NOT EXISTS(SELECT 1 FROM tier_audit_messages m WHERE m.audit_id=a.id AND m.guild_id=?) ORDER BY a.id LIMIT 10",
            (self.store.clock() - 7 * 86400, panel["guild_id"]),
        )
        for row in rows:
            if self.store.clock() - row["created_at"] > 7 * 86400:
                continue
            embed = discord.Embed(
                title="Revisão da comunidade",
                description=safe(row["reason"], 900),
                color=0x960D16,
            )
            embed.set_footer(text=f"Revisão #{row['id']} · {moment(row['created_at'])}")
            ident = row["id"]
            message = await self.deliver(
                thread,
                f"audit:{ident}:{thread.id}",
                embed=embed,
                marker=lambda m: any(
                    e.footer.text and e.footer.text.startswith(f"Revisão #{ident} ·")
                    for e in m.embeds
                ),
            )
            with self.store.connection:
                self.store.connection.execute(
                    "INSERT OR IGNORE INTO tier_audit_messages VALUES(?,?,?)",
                    (ident, panel["guild_id"], str(message.id)),
                )

    @tasks.loop(minutes=15)
    async def maintenance_loop(self):
        try:
            self.store.cleanup()
            self.media.cleanup()
            with self.store.connection:
                self.store.connection.execute(
                    "DELETE FROM tier_deliveries WHERE created_at<? AND key NOT LIKE 'panel:%' AND key NOT LIKE 'index:%'",
                    (self.store.clock() - 30 * 86400,),
                )
                self.store.connection.execute(
                    "DELETE FROM tier_meta WHERE key LIKE 'delivery-attempt:%' AND CAST(value AS REAL)<?",
                    (self.store.clock() - 7 * 86400,),
                )
            report = await asyncio.to_thread(maintain_tier_storage, self.store.path)
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

    def register_commands(self):
        @self.tree.command(
            name="tierlist",
            description="Prepare ou confira o painel da tier list global neste servidor.",
        )
        @app_commands.guild_only()
        @app_commands.allowed_installs(guilds=True, users=False)
        @app_commands.default_permissions(manage_guild=True)
        async def tierlist(i: discord.Interaction):
            self.require_admin(i)
            await i.response.defer(ephemeral=True, thinking=True)
            async with self.guild_lock(i.guild_id):
                panel, thread = await self.ensure_panel(i)
            url = f"https://discord.com/channels/{i.guild_id}/{thread.id}"
            await i.followup.send(
                f"**Painel pronto.** A imagem fica no canal; propostas, votos e resultados ficam no [tópico]({url}). Membros participam pelos botões, sem precisar de comandos. Os comentários sobre o jogo são identificados automaticamente nos canais acessíveis ao bot.",
                view=AdminView(self, i),
                ephemeral=True,
            )

        @self.tree.command(name="chatglobal", description="Em breve.")
        @app_commands.guild_only()
        async def chatglobal(i: discord.Interaction):
            await reply(i, "Em breve.")

        @self.tree.error
        async def command_error(i, error):
            cause = getattr(error, "original", error)
            if isinstance(cause, (ValueError, app_commands.CheckFailure)):
                await reply(i, str(cause))
            else:
                log.warning("Comando indisponível: %s", type(cause).__name__)
                await reply(
                    i,
                    "Não consegui concluir agora. Confira as permissões do canal e tente novamente. O estado anterior foi preservado.",
                )

    async def close(self):
        if getattr(self, "_tier_closed", False):
            return
        self._tier_closed = True
        checks = [
            task
            for task in self.verification_tasks
            if task is not asyncio.current_task() and not task.done()
        ]
        for task in checks:
            task.cancel()
        if checks:
            await asyncio.gather(*checks, return_exceptions=True)
        for loop in (
            self.history_loop,
            self.analysis_loop,
            self.poll_loop,
            self.panel_loop,
            self.maintenance_loop,
            self.wiki_loop,
        ):
            task = loop.get_task()
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        await self.health.close()
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
