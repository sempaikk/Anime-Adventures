"""Tier list, global chat and independently configured image-only banners."""

from __future__ import annotations
import asyncio
import hashlib
import io
import json
import logging
import os
import signal
import shutil
import sqlite3
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
from tier_catalog import TierCatalog
from runtime_health import RuntimeHealth
from tier_analysis import DAILY_CALLS, DAILY_TOKENS, TierAnalyzer
from tier_backup import acquire_lease, maintain_tier_storage
from tier_domain import digest, relevant_units, safe, moment
from tier_image import PanelRenderer, image_file, index_text
from tier_media import MediaLibrary, MAX_UPLOAD
from tier_portraits import PortraitInventory
from tier_schedule import poll_progress
from tier_delivery import sync_polls
from tier_store import TierStore
from tier_views import AdminView, PollView, ThreadView, reply
from tier_wiki import WikiSync
from tier_style import GameTheme
from tier_ui import payload as ui_payload, visible_text

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
    def __init__(self, data_dir=None, *, backend=None, tierlist_enabled=False):
        # Archived implementation remains testable; production keeps it paused.
        self.tierlist_enabled = tierlist_enabled
        intents = discord.Intents.none()
        intents.guilds = intents.guild_messages = intents.message_content = True
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            help_command=None,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        self.directory = Path(data_dir or os.getenv("DATA_DIR", "state"))
        self.catalog = TierCatalog(
            min_mention_length=3,
            extra_aliases={"gyutaro": ["Giltaro", "Gyuutaro", "Gyuutarou"]},
        )
        self.lease = acquire_lease(self.directory)
        try:
            self.store = TierStore(self.directory / "tierlist.sqlite3")
            self.media = MediaLibrary(self.store, self.catalog)
            self.analyzer = TierAnalyzer(
                self.store,
                self.catalog,
                backend=backend,
                source_guard=self.purge_inaccessible_sources,
            )
            self.wiki = WikiSync(self.store, self.catalog, self.analyzer.evidence)
            self.store.bind_catalog(self.catalog)
        except BaseException:
            if hasattr(self, "store"):
                self.store.close()
            self.lease.close()
            raise
        self.portrait_inventory = PortraitInventory(self.catalog, self.media)
        self.index_checks = {}
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
        from global_relay import GlobalRelay

        self.globalchat = GlobalRelay(self)
        self.health.add_probe("global_chat", self.globalchat.ready)
        from banner_relay import BannerRelay

        self.banners = BannerRelay(self)
        self.daily = BannerRelay(self, kind="daily")
        from game_knowledge import GameKnowledge, UnavailableKnowledge

        try:
            if os.getenv('KNOWLEDGE_MODE', 'local').lower() == 'pc':
                from knowledge_remote import RemoteKnowledge
                self.knowledge = RemoteKnowledge(self)
            else:
                self.knowledge = GameKnowledge(self)
        except (sqlite3.DatabaseError, OSError, ValueError):
            log.warning('Knowledge archive unavailable; existing files preserved.')
            self.knowledge = UnavailableKnowledge(self)
        from instance_storage import InstanceStorage

        self.instance_storage=InstanceStorage(Path(__file__).resolve().parent,self.directory,self.health,
                                             limit_mb=os.getenv('INSTANCE_DISK_LIMIT_MB','512'))
        self.globalchat.media.available_space=self.instance_storage.available
        self.owner_ids_set = set()
        self.ui_theme = GameTheme()
        from tier_release import build_info

        self.build = build_info()
        self.register_commands()

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
        from tier_seed import seed_initial

        if self.tierlist_enabled:
            seed_initial(self.store, self.catalog)
        try:
            self.knowledge.ensure_wiki()
        except (sqlite3.DatabaseError, OSError, ValueError):
            self.knowledge.paused=True
            log.warning('Knowledge source indexing unavailable; existing archive preserved.')
        from tier_release import label

        log.info(
            "Versão %s; arquivos %s.",
            label(self.build),
            "conferidos"
            if self.build["verified"]
            else "divergentes; confira o diagnóstico",
        )
        app = await self.application_info()
        await self.ui_theme.refresh(self.http, app.id)
        self.owner_ids_set = {app.team.owner_id if app.team else app.owner.id}
        if self.tierlist_enabled:
            self.add_view(ThreadView(self))
            self.add_view(PollView(self))
        from global_views import GlobalPanelView, GlobalDirectView

        self.add_view(GlobalPanelView(self))
        self.add_view(GlobalDirectView(self))
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
        if self.tierlist_enabled:
            self.add_view(legacy)
        await self.health.start(
            int(os.getenv("PORT") or os.getenv("SERVER_PORT") or 8080),
            routes=getattr(self.knowledge, 'install_routes', None),
        )
        await self.tree.sync()
        for loop in (
            self.history_loop,
            self.analysis_loop,
            self.poll_loop,
            self.panel_loop,
            self.maintenance_loop,
            self.wiki_loop,
            self.global_loop,
            self.operations_loop,
            self.banner_loop,
            self.quota_loop,
        ):
            if not self.tierlist_enabled and loop in (self.history_loop, self.analysis_loop, self.poll_loop, self.panel_loop, self.wiki_loop):
                continue
            loop.start()
        self.banners.start()
        log.info(
            "Comandos sincronizados; tier list %s; IA %s.",
            "ativa" if self.tierlist_enabled else "pausada",
            "chave carregada" if self.analyzer.backend.enabled else "sem chave",
        )

    async def on_ready(self):
        for guild in self.guilds:
            self.store.register_guild(guild.id)
        actual = {str(g.id) for g in self.guilds}
        for row in self.store.rows("SELECT guild_id FROM tier_guilds"):
            if row["guild_id"] not in actual:
                self.store.remove_guild(row["guild_id"])
        for row in self.globalchat.store.channels():
            if row["guild_id"] not in actual:
                self.globalchat.store.remove_guild(row["guild_id"])
        for feed in (self.banners, self.daily):
            for row in feed.query("SELECT guild_id FROM banner_targets").fetchall():
                if row["guild_id"] not in actual:
                    feed.disable(row["guild_id"])
        log.info(
            "Conectado; %s servidores; aguardando relatos do jogo.", len(self.guilds)
        )
        if self.tierlist_enabled:
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
        self.banners.disable(guild.id)
        self.daily.disable(guild.id)
        self.globalchat.store.remove_guild(guild.id)
        self.store.remove_guild(guild.id)
        self.guild_locks.pop(guild.id, None)
        self.index_checks.pop(str(guild.id), None)

    async def on_message(self, message):
        self.collect_message(message)
        await self.globalchat.ingest(message)

    def collect_message(self, message):
        if not self.tierlist_enabled:
            return
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
        self.globalchat.on_delete(event)
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
            self.store.connection.execute(
                "UPDATE tier_threads SET index_hash='' WHERE intro_id=?",
                (str(event.message_id),),
            )
        # Deleted poll copies are respected. Panel repairs require an explicit /tierlist.

    async def on_raw_bulk_message_delete(self, event):
        for ident in event.message_ids:
            await self.on_raw_message_delete(SimpleNamespace(message_id=ident))

    async def on_raw_message_edit(self, event):
        await self.globalchat.on_edit(event)
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
        cfg = self.globalchat.store.source(channel.id)
        if cfg:
            for row in self.globalchat.store.rows(
                "SELECT id FROM global_messages WHERE channel_id=? AND deleted=0",
                (str(channel.id),),
            ):
                self.globalchat.store.erase(row["id"])
            self.globalchat.store.active(channel.guild.id, False)
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
            + (
                "\nHá resultado encerrado aguardando arquivo ou limpeza. Confira o acesso ao canal e ao tópico; o aviso é preservado até confirmar o histórico."
                if self.store.public_results_waiting(i.guild_id)
                else ""
            )
        )

    def diagnostics(self, i):
        from tier_release import label

        self.require_owner(i)
        latest = self.store.board()
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
        text += f"\n**Interface:** Components V2 · {len(self.ui_theme.available)} ícones da wiki disponíveis."
        text += "\n**Listas:** " + " · ".join(
            f"{mode}: {len(p['ranking'])} formas" for mode, p in latest["modes"].items()
        )
        reference = self.store.get("wiki_initial_reference")
        if reference:
            data = json.loads(reference)
            text += f"\n**Base Wiki:** revisão {data['revision']} · {data['unresolved']} entradas sem correspondência exata. Registro inicial interno, sem votos."
        text += "\n" + self.globalchat.operations.description(compact=True)
        text += f"\n**Relatos aguardando análise:** {pending}."
        text += f"\n**Resultados aguardando arquivo/limpeza:** {self.store.public_results_waiting()}."
        text += f"\n**Cota local do dia UTC:** {budget.get('calls', 0)}/{DAILY_CALLS} chamadas · {budget.get('tokens', 0)}/{DAILY_TOKENS} tokens."
        thread = self.store.thread(i.guild_id)
        if thread:
            text += f"\n**Tópico:** {thread['status']}."
        if self.is_owner_id(i.user.id):
            text += (
                "\n**Versão em execução:** "
                + label(self.build)
                + (
                    " · arquivos conferidos na inicialização."
                    if self.build["verified"]
                    else " · confira a atualização dos arquivos."
                )
            )
            import tier_balance

            update = tier_balance.state(self.store)
            if update:
                text += f"\n**Atualização do jogo:** {safe(update['label'], 80)} · " + (
                    "aguardando conferência das fontes."
                    if update["paused"]
                    else "análise retomada após conferência."
                )
            text += f"\n**Catálogo:** {len(self.catalog.units)} formas · {max(0, len(self.catalog.units) - len(latest['ranking']))} sem avaliação.\n**Retratos:** revisão {int(self.store.get('media_revision') or 0)}."
            text += f"\n**Pendências de retrato:** {self.portrait_inventory.get().count}; {len(self.catalog.retired)} formas retiradas do catálogo ativo."
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
        publication = self.store.board()
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
        kwargs = ui_payload(bot=self, **kwargs)
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
        nonce_key = "delivery-nonce:" + key
        generation = int(self.store.get(nonce_key) or 0)
        with handle_message_parameters(
            allowed_mentions=discord.AllowedMentions.none(), **kwargs
        ) as params:
            for attempt in range(2):
                nonce = str(
                    int(
                        hashlib.sha256(
                            f"{self.store.get('salt')}:{key}:{generation}".encode()
                        ).hexdigest()[:15],
                        16,
                    )
                )
                if params.payload is not None:
                    params.payload.update(nonce=nonce, enforce_nonce=True)
                else:
                    for part in params.multipart:
                        if part["name"] == "payload_json":
                            payload = json.loads(part["value"])
                            payload.update(nonce=nonce, enforce_nonce=True)
                            part["value"] = json.dumps(payload)
                try:
                    data = await self.http.send_message(channel.id, params=params)
                    break
                except discord.NotFound as error:
                    if error.code != 10008 or attempt:
                        raise
                    # Discord can retain a nonce after its message was deleted.
                    # Retry once with a new persistent nonce, while files remain open.
                    generation = max(generation + 1, int(self.store.clock()))
                    self.store.set(nonce_key, generation)
                    for file in params.files or []:
                        file.reset()
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
                i.guild_id, channel.id, message.id, self.store.board()["id"]
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
        await self.sync_index(panel, thread, force=True)
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

    async def sync_index(self, panel, thread, *, force=False):
        record = self.store.thread(panel["guild_id"])
        needs = self.portrait_inventory.get()
        text = index_text(
            self.store,
            panel,
            wiki_status=self.wiki.status,
            ai_enabled=self.analyzer.backend.enabled,
            portrait_count=needs.count,
            progress=poll_progress(
                self.store,
                ai_enabled=self.analyzer.backend.enabled,
                analyzing=self.analyzer.running,
                preparing=self.history_import_lock.locked(),
                maintenance=self.health.storage_level == "critical",
            ),
        )
        if self.health.storage_level == "critical":
            text += "\n**Manutenção:** novas análises e imagens temporariamente pausadas. A classificação atual foi preservada."
        previous = self.store.get("previous-thread:" + panel["guild_id"])
        if previous and previous != str(thread.id):
            text += f"\n[Histórico do tópico anterior](https://discord.com/channels/{panel['guild_id']}/{previous})."
        signature = digest(
            (
                text,
                needs.checksum,
                "thread-controls-v5",
                tuple(sorted(self.ui_theme.available)),
            )
        )
        checked = self.index_checks.get(panel["guild_id"])
        if (
            record["intro_id"]
            and record["index_hash"] == signature
            and not force
            and checked is not None
            and self.store.clock() - checked < 900
        ):
            return
        generation_key = f"index-generation:{thread.id}"
        generation = int(self.store.get(generation_key) or 0)
        key = f"index:{thread.id}:{generation}"
        file = (
            discord.File(io.BytesIO(needs.blob), filename="retratos-pendentes.txt")
            if needs.count
            else None
        )
        message = None
        try:
            if record["intro_id"]:
                try:
                    message = await thread.get_partial_message(
                        int(record["intro_id"])
                    ).edit(
                        **ui_payload(
                            bot=self,
                            content=text,
                            attachments=[file] if file else [],
                            view=ThreadView(self),
                        ),
                    )
                except discord.NotFound:
                    if file:
                        file.close()
                        file = discord.File(
                            io.BytesIO(needs.blob), filename="retratos-pendentes.txt"
                        )
                    self.forget_delivery(key)
                    generation += 1
                    self.store.set(generation_key, generation)
                    key = f"index:{thread.id}:{generation}"
                    with self.store.connection:
                        self.store.connection.execute(
                            "UPDATE tier_threads SET intro_id=NULL,index_hash='' WHERE guild_id=?",
                            (panel["guild_id"],),
                        )
            if message is None:
                reconciling = bool(
                    self.store.get("delivery-attempt:" + key)
                    or self.store.rows(
                        "SELECT 1 FROM tier_deliveries WHERE key=?", (key,)
                    )
                )
                message = await self.deliver(
                    thread,
                    key,
                    content=text,
                    files=[file] if file else [],
                    view=ThreadView(self),
                    marker=lambda m: visible_text(m).startswith(
                        "## Votações e histórico"
                    ),
                )
                if reconciling:
                    if file:
                        file.close()
                        file = discord.File(
                            io.BytesIO(needs.blob), filename="retratos-pendentes.txt"
                        )
                    await message.edit(
                        **ui_payload(
                            bot=self,
                            content=text,
                            attachments=[file] if file else [],
                            view=ThreadView(self),
                        ),
                    )
        finally:
            if file:
                file.close()
        self.store.remember_thread(panel["guild_id"], thread.id, message.id)
        with self.store.connection:
            self.store.connection.execute(
                "UPDATE tier_threads SET index_hash=? WHERE guild_id=?",
                (signature, panel["guild_id"]),
            )
        self.index_checks[panel["guild_id"]] = self.store.clock()

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
            await self.ui_theme.refresh(self.http, self.application_id)
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
        await sync_polls(self)

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
                                    self.store.board()["id"],
                                    self.store.clock(),
                                    panel["guild_id"],
                                ),
                            )
                    await self.sync_private_audits(panel, thread)
                    await self.sync_index(panel, thread)
            except discord.NotFound:
                with self.store.connection:
                    self.store.connection.execute(
                        "UPDATE tier_threads SET status='missing' WHERE guild_id=?",
                        (panel["guild_id"],),
                    )
            except Exception as error:
                self.ui_theme.observe_error(error)
                log.warning(
                    "Painel preservado, atualização adiada: %s", type(error).__name__
                )

    @panel_loop.before_loop
    async def panels_ready(self):
        await self.wait_until_ready()

    async def sync_private_audits(self, panel, thread):
        from tier_audit import hide_audit_messages

        await hide_audit_messages(self, panel, thread)

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
                self.store.connection.execute(
                    "DELETE FROM tier_meta WHERE key LIKE 'delivery-nonce:%' AND CAST(value AS REAL)<?",
                    (self.store.clock() - 7 * 86400,),
                )
            report = await asyncio.to_thread(maintain_tier_storage, self.store.path)
            await asyncio.to_thread(self.knowledge.backup)
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

    @operations_loop.before_loop
    async def operations_ready(self):
        await self.wait_until_ready()

    @tasks.loop(seconds=2)
    async def banner_loop(self):
        try:
            await self.banners.cycle()
            await self.daily.cycle()
            self.knowledge.prune()
        except Exception as error:
            log.warning("Entrega de banners adiada: %s", type(error).__name__)

    @banner_loop.before_loop
    async def banner_ready(self):
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

        @self.tree.command(name="ask", description="Ask a question about Anime Adventures in your preferred language.")
        @app_commands.guild_only()
        @app_commands.allowed_installs(guilds=True, users=False)
        async def ask(i: discord.Interaction):
            from game_knowledge import AskModal

            await i.response.send_modal(AskModal(self, i))

        @self.tree.command(
            name="tierlist",
            description="Prepare ou confira o painel da tier list global neste servidor.",
        )
        @app_commands.guild_only()
        @app_commands.allowed_installs(guilds=True, users=False)
        @app_commands.default_permissions(manage_guild=True)
        async def tierlist(i: discord.Interaction):
            self.require_admin(i)
            if self.globalchat.store.source(i.channel_id):
                raise ValueError(
                    "Use um canal diferente do chat global para preparar a tier list."
                )
            await i.response.defer(ephemeral=True, thinking=True)
            async with self.guild_lock(i.guild_id):
                panel, thread = await self.ensure_panel(i)
            url = f"https://discord.com/channels/{i.guild_id}/{thread.id}"
            image_url = f"https://discord.com/channels/{i.guild_id}/{panel['channel_id']}/{panel['message_id']}"
            await i.followup.send(
                **ui_payload(
                    bot=self,
                    content=f"## Painel da tier list\n[Ver tier list]({image_url}) · [Votações e histórico]({url})\n\n**Pronto para participar.** As enquetes aparecem no canal desse painel; os resultados ficam no tópico. Membros participam pelos botões, sem precisar de comandos. Os comentários sobre o jogo são identificados automaticamente nos canais acessíveis ao bot.",
                    view=AdminView(self, i),
                ),
                ephemeral=True,
            )

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

        if not self.tierlist_enabled:
            self.tree.remove_command("tierlist")

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
            self.global_loop,
            self.operations_loop,
            self.banner_loop,
            self.quota_loop,
        ):
            task = loop.get_task()
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        if getattr(self.knowledge, 'remote', False):
            await self.knowledge.aclose()
        await self.health.close()
        await self.banners.close()
        await self.daily.close()
        self.knowledge.close()
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
