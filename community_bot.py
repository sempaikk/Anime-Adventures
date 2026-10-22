"""Exactly two commands: a global tier list and an inactive global-chat placeholder."""

from __future__ import annotations
import asyncio
import hashlib
import logging
import os
import signal
import time
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands, tasks
from discord.http import handle_message_parameters
from dotenv import load_dotenv

from community_domain import Catalog
from runtime_health import RuntimeHealth
from storage_maintenance import maintain_storage
from tier_analysis import TierAnalyzer
from tier_image import panel_payload, poll_embed
from tier_store import REQUIRED_TABLES, TierStore

log = logging.getLogger("tierlist")
ANALYSIS_NOTICE = (
    "### Análise da tier list\nA administração ativou este canal como fonte da tier list global. "
    "Só comentários de participantes que confirmarem em **Opções → Participar da análise** entram na análise. "
    "Trechos relevantes sobre o jogo podem ser enviados à IA da Groq, o bot não anexa seu nome, ID do Discord ou nome do servidor. "
    "Não escreva dados pessoais nos relatos. Os comentários ficam no banco por até 7 dias; os registros de votos duram até 30 dias; você pode parar e apagar seus comentários em Opções. "
    "Os resultados são compartilhados na tier list global, com motivos apoiados na wiki; o bot não retransmite a conversa. "
    "Desativar a participação não apaga resultados agregados já publicados. Backups locais são substituídos diariamente."
)


async def reply(i, text=None, **kwargs):
    kwargs.setdefault("ephemeral", True)
    if i.response.is_done():
        return await i.followup.send(text, **kwargs)
    return await i.response.send_message(text, **kwargs)


class GuardedView(discord.ui.View):
    async def on_error(self, i, error, item):
        if isinstance(error, ValueError):
            await reply(i, str(error))
        else:
            log.warning("Falha de interface: %s", type(error).__name__)
            await reply(i, "Não consegui concluir agora. Tente novamente em instantes.")


class TierView(GuardedView):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Opções", custom_id="tier:v2:options")
    async def options(self, i, button):
        state = "ativa" if self.bot.store.consented(i.user.id) else "desativada"
        backend = (
            "configurada" if self.bot.analyzer.backend.enabled else "aguardando conexão"
        )
        text = f"### Tier list global\nSua participação na análise está **{state}**. IA: **{backend}**.\n\n"
        if i.guild_id and i.permissions.manage_guild:
            destination = next(
                (
                    r
                    for r in self.bot.store.update_channels()
                    if r["guild_id"] == str(i.guild_id)
                ),
                None,
            )
            text += f"**Votações e histórico:** {('<#' + destination['channel_id'] + '>') if destination else 'escolha um canal abaixo'}.\nO canal da imagem fica separado.\n\n"
        text += (
            "Os comentários autorizados ajudam a análise automática. Você não precisa preencher notas ou escolher tiers.\n\n"
            + ANALYSIS_NOTICE
        )
        await reply(i, text, view=OptionsView(self.bot, i))


class AnalysisChannel(discord.ui.ChannelSelect):
    def __init__(self, bot, *, disable=False):
        super().__init__(
            placeholder="Desativar análise em um canal"
            if disable
            else "Ativar análise em um canal",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
            row=2 if disable else 1,
        )
        self.bot = bot
        self.disable = disable

    async def callback(self, i):
        self.bot.require_admin(i)
        channel = self.bot.get_channel(self.values[0].id)
        if (
            not isinstance(channel, discord.TextChannel)
            or channel.guild.id != i.guild_id
        ):
            raise ValueError("Escolha um canal deste servidor.")
        await i.response.defer(ephemeral=True, thinking=True)
        if self.disable:
            self.bot.store.disable_channel(i.guild_id, channel.id)
            await reply(
                i,
                f"Análise desativada em {channel.mention}. Os comentários desse canal foram removidos da coleta.",
            )
            return
        if any(p["channel_id"] == str(channel.id) for p in self.bot.store.panels()):
            raise ValueError(
                "O canal da tier list fica só com a imagem. Escolha um canal de conversa para análise."
            )
        perms = channel.permissions_for(i.guild.me)
        if not (
            perms.view_channel and perms.read_message_history and perms.send_messages
        ):
            raise ValueError(
                "O bot precisa de Ver canal, Ler histórico e Enviar mensagens para publicar o aviso de participação."
            )
        await channel.send(ANALYSIS_NOTICE, view=TierView(self.bot))
        self.bot.store.enable_channel(i.guild_id, channel.id)
        await reply(
            i,
            f"Análise ativada em {channel.mention}. Cada participante confirma uma vez em Opções. As conversas não serão retransmitidas.",
        )


class UpdatesChannel(discord.ui.ChannelSelect):
    def __init__(self, bot):
        super().__init__(
            placeholder="Canal de votações e atualizações",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
            row=3,
        )
        self.bot = bot

    async def callback(self, i):
        self.bot.require_admin(i)
        channel = self.bot.get_channel(self.values[0].id)
        if (
            not isinstance(channel, discord.TextChannel)
            or channel.guild.id != i.guild_id
        ):
            raise ValueError("Escolha um canal deste servidor.")
        perms = channel.permissions_for(i.guild.me)
        if not (perms.view_channel and perms.send_messages and perms.embed_links):
            raise ValueError(
                "O bot precisa de Ver canal, Enviar mensagens e Inserir links nesse canal."
            )
        self.bot.store.set_update_channel(i.guild_id, channel.id)
        await reply(
            i,
            f"Votações e resultados serão publicados em {channel.mention}. O painel da tier list continua no canal separado.",
        )


class OptionsView(GuardedView):
    def __init__(self, bot, i):
        super().__init__(timeout=600)
        self.bot = bot
        self.actor = i.user.id
        self.guild = i.guild_id
        if i.guild_id and i.permissions.manage_guild:
            self.add_item(AnalysisChannel(bot))
            self.add_item(AnalysisChannel(bot, disable=True))
            self.add_item(UpdatesChannel(bot))

    async def interaction_check(self, i):
        if i.user.id != self.actor or i.guild_id != self.guild:
            await reply(i, "Abra suas próprias opções no painel.")
            return False
        return True

    @discord.ui.button(
        label="Participar da análise", style=discord.ButtonStyle.success, row=0
    )
    async def participate(self, i, button):
        if (discord.utils.utcnow() - i.user.created_at).total_seconds() < 7 * 86400:
            raise ValueError("Sua conta precisa ter pelo menos 7 dias para participar.")
        self.bot.store.consent(i.user.id)
        await reply(
            i,
            "Participação confirmada. Comentários futuros nos canais ativados podem entrar na análise global. Nenhuma conversa antiga será importada.",
        )

    @discord.ui.button(label="Parar e apagar meus comentários", row=0)
    async def stop(self, i, button):
        self.bot.store.withdraw(i.user.id)
        await reply(
            i,
            "Participação desativada e comentários removidos da coleta. Os resultados agregados já publicados continuam; a cópia de segurança anterior é substituída no próximo ciclo diário.",
        )


class PollView(GuardedView):
    def __init__(self, bot, *, closed=False):
        super().__init__(timeout=None)
        self.bot = bot
        for item in self.children:
            item.disabled = closed

    async def cast(self, i, choice):
        if (
            i.user.bot
            or (discord.utils.utcnow() - i.user.created_at).total_seconds() < 7 * 86400
        ):
            raise ValueError(
                "Para votar, use uma conta de pessoa com pelo menos 7 dias."
            )
        receipt = self.bot.store.poll_at(i.guild_id, i.channel_id, i.message.id)
        if not receipt:
            raise ValueError("Esta votação não está mais disponível.")
        self.bot.store.vote(
            receipt["proposal_id"],
            i.user.id,
            i.guild_id,
            i.channel_id,
            i.message.id,
            choice,
        )
        labels = {
            "approve": "Aprovar",
            "keep": "Manter como está",
            "test": "Precisa de mais testes",
        }
        await reply(
            i,
            f"Seu voto: **{labels[choice]}**. Você pode trocar até o encerramento; ele conta uma vez na rede inteira.",
        )

    @discord.ui.button(
        label="Aprovar",
        custom_id="tier:v2:vote:approve",
        style=discord.ButtonStyle.success,
    )
    async def approve(self, i, button):
        await self.cast(i, "approve")

    @discord.ui.button(label="Manter como está", custom_id="tier:v2:vote:keep")
    async def keep(self, i, button):
        await self.cast(i, "keep")

    @discord.ui.button(label="Precisa de mais testes", custom_id="tier:v2:vote:test")
    async def more(self, i, button):
        await self.cast(i, "test")


class CommunityBot(commands.Bot):
    def __init__(self, data_dir=None, *, backend=None):
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True
        intents.message_content = True
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            help_command=None,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        self.catalog = Catalog(
            min_mention_length=3,
            extra_aliases={"gyutaro": ["Giltaro", "Gyuutaro", "Gyuutarou"]},
        )
        self.store = TierStore(
            Path(data_dir or os.getenv("DATA_DIR", "state")) / "tierlist.sqlite3"
        )
        self.analyzer = TierAnalyzer(self.store, self.catalog, backend=backend)
        self.health = RuntimeHealth(self.is_ready, lambda: self.store.connection)
        self.owner_ids_set = set()
        self.command_cooldowns = {}
        self.command_clock = time.monotonic
        self.register_commands()

    def is_owner_id(self, actor):
        return actor in self.owner_ids_set

    def require_admin(self, i):
        if not i.guild_id or not i.permissions.manage_guild:
            raise ValueError(
                "Você precisa de Gerenciar servidor para configurar os canais."
            )

    async def setup_hook(self):
        app = await self.application_info()
        self.owner_ids_set = (
            {m.id for m in app.team.members} if app.team else {app.owner.id}
        )
        self.add_view(TierView(self))
        self.add_view(PollView(self))
        await self.health.start(
            int(os.getenv("PORT") or os.getenv("SERVER_PORT") or 8080)
        )
        await self.tree.sync()
        self.analysis_loop.start()
        self.poll_loop.start()
        self.panel_loop.start()
        self.maintenance_loop.start()
        log.info(
            "Sincronizados somente /tierlist e /chatglobal; chat global inativo; IA %s.",
            "configurada" if self.analyzer.backend.enabled else "sem chave",
        )

    async def on_ready(self):
        log.info("Conectado; %s servidores.", len(self.guilds))

    async def on_message(self, message):
        if message.author.bot or message.webhook_id or not message.guild:
            return
        if not self.store.channel_enabled(message.guild.id, message.channel.id):
            return
        if not self.store.consented(message.author.id):
            return
        if not message.content or message.attachments or message.stickers:
            return
        if self.health.storage_level == "critical":
            return
        self.store.ingest(
            message.id,
            message.author.id,
            message.guild.id,
            message.channel.id,
            message.content,
            self.catalog.mentions(message.content),
        )

    async def on_raw_message_delete(self, event):
        with self.store.connection:
            self.store.connection.execute(
                "DELETE FROM tier_comments WHERE message_id=?", (str(event.message_id),)
            )

    async def on_raw_message_edit(self, event):
        # Edited source text is removed from pending evidence; it is not silently reinterpreted.
        if "content" in event.data:
            with self.store.connection:
                self.store.connection.execute(
                    "DELETE FROM tier_comments WHERE message_id=?",
                    (str(event.message_id),),
                )

    async def on_guild_remove(self, guild):
        for channel in self.store.channels(guild.id):
            self.store.disable_channel(guild.id, channel["channel_id"])
        with self.store.connection:
            self.store.connection.execute(
                "DELETE FROM tier_panels WHERE guild_id=?", (str(guild.id),)
            )
            self.store.connection.execute(
                "DELETE FROM tier_destinations WHERE guild_id=?", (str(guild.id),)
            )

    @tasks.loop(seconds=15)
    async def analysis_loop(self):
        try:
            if self.health.storage_level != "critical" and self.store.update_channels():
                await self.analyzer.run()
        except Exception as exc:
            log.warning("Análise adiada: %s", type(exc).__name__)

    @analysis_loop.before_loop
    async def analysis_ready(self):
        await self.wait_until_ready()

    @tasks.loop(seconds=15)
    async def poll_loop(self):
        try:
            self.store.resolve_due(source_version=self.analyzer.evidence.version)
            proposal = self.store.active_proposal()
            if proposal:
                for panel in self.store.update_channels():
                    existing = self.store.rows(
                        "SELECT 1 FROM tier_poll_messages WHERE proposal_id=? AND channel_id=?",
                        (proposal["id"], panel["channel_id"]),
                    )
                    if existing:
                        continue
                    channel = self.get_channel(int(panel["channel_id"]))
                    if not channel:
                        continue
                    try:
                        nonce = str(
                            int(
                                hashlib.sha256(
                                    f"poll:{proposal['id']}:{channel.id}".encode()
                                ).hexdigest()[:15],
                                16,
                            )
                        )
                        with handle_message_parameters(
                            embed=poll_embed(self.store, self.catalog, proposal),
                            view=PollView(self),
                            nonce=nonce,
                            allowed_mentions=discord.AllowedMentions.none(),
                        ) as params:
                            params.payload["enforce_nonce"] = True
                            message = await self.http.send_message(
                                channel.id, params=params
                            )
                        self.store.remember_poll(
                            proposal["id"],
                            panel["guild_id"],
                            panel["channel_id"],
                            message["id"],
                        )
                    except discord.HTTPException:
                        log.warning(
                            "Publicação da enquete adiada por falha no Discord."
                        )
            now = self.store.clock()
            for receipt in self.store.poll_messages():
                if receipt["status"] == "removed":
                    continue
                p = self.store.proposal(receipt["proposal_id"])
                if not p:
                    continue
                if receipt["status"] == p["status"] and (
                    p["status"] != "open" or now - receipt["updated_at"] < 60
                ):
                    continue
                channel = self.get_channel(int(receipt["channel_id"]))
                if not channel:
                    continue
                try:
                    await channel.get_partial_message(int(receipt["message_id"])).edit(
                        embed=poll_embed(self.store, self.catalog, p),
                        view=PollView(self, closed=p["status"] != "open"),
                    )
                    self.store.remember_poll(
                        p["id"],
                        receipt["guild_id"],
                        receipt["channel_id"],
                        receipt["message_id"],
                        p["status"],
                    )
                except discord.NotFound:
                    with self.store.connection:
                        self.store.connection.execute(
                            "UPDATE tier_poll_messages SET status='removed' WHERE proposal_id=? AND channel_id=?",
                            (p["id"], receipt["channel_id"]),
                        )
                except discord.HTTPException:
                    log.warning("Resultado da enquete adiado por falha no Discord.")
        except Exception as exc:
            log.warning("Votação adiada: %s", type(exc).__name__)

    @poll_loop.before_loop
    async def poll_ready(self):
        await self.wait_until_ready()

    @tasks.loop(seconds=15)
    async def panel_loop(self):
        latest = self.store.latest()
        for panel in self.store.panels():
            if panel["publication_id"] == latest["id"]:
                continue
            channel = self.get_channel(int(panel["channel_id"]))
            if not channel:
                continue
            _, file, _ = panel_payload(self.store)
            try:
                await channel.get_partial_message(int(panel["message_id"])).edit(
                    content=None, embeds=[], attachments=[file], view=None
                )
                self.store.remember_panel(
                    panel["guild_id"],
                    panel["channel_id"],
                    panel["message_id"],
                    latest["id"],
                )
            except discord.NotFound:
                self.store.forget_panel(panel["channel_id"])
            except discord.HTTPException:
                log.warning("Painel adiado por falha no Discord.")
            finally:
                file.close()

    @panel_loop.before_loop
    async def panels_ready(self):
        await self.wait_until_ready()

    @tasks.loop(minutes=15)
    async def maintenance_loop(self):
        try:
            self.store.cleanup()
            report = await asyncio.to_thread(
                maintain_storage, self.store.path, required_tables=REQUIRED_TABLES
            )
            self.health.update_storage(report)
        except Exception as exc:
            self.health.backup_error = True
            log.warning("Manutenção: %s", type(exc).__name__)

    def register_commands(self):
        @self.tree.command(
            name="tierlist",
            description="Veja a tier list global ou configure o painel do servidor.",
        )
        @app_commands.guild_only()
        async def tierlist(i: discord.Interaction):
            # No options, scopes, forms, tiers or modes in the slash command.
            perms = i.app_permissions
            if not (perms.send_messages and perms.embed_links and perms.attach_files):
                raise ValueError(
                    "O bot precisa de Enviar mensagens, Inserir links e Anexar arquivos neste canal."
                )
            last = self.command_cooldowns.get(i.channel_id)
            if last is not None and self.command_clock() - last < 10:
                await reply(
                    i,
                    "Aguarde alguns segundos antes de publicar outra tier list neste canal.",
                )
                return
            self.command_cooldowns[i.channel_id] = self.command_clock()
            if len(self.command_cooldowns) > 1000:
                self.command_cooldowns.clear()
            public = bool(i.permissions.manage_guild)
            if public and self.store.is_update_channel(i.guild_id, i.channel_id):
                raise ValueError(
                    "Publique a imagem em outro canal. Este está reservado para votações e atualizações."
                )
            if public and self.store.channel_enabled(i.guild_id, i.channel_id):
                raise ValueError(
                    "Escolha um canal separado das conversas analisadas para publicar a imagem."
                )
            await i.response.defer(thinking=True, ephemeral=True)
            _, file, _ = panel_payload(self.store)
            if not public:
                try:
                    await i.followup.send(
                        file=file, view=TierView(self), ephemeral=True
                    )
                finally:
                    file.close()
                return
            existing = next(
                (
                    p
                    for p in self.store.panels()
                    if p["channel_id"] == str(i.channel_id)
                ),
                None,
            )
            try:
                sent = None
                if existing:
                    try:
                        sent = await i.channel.get_partial_message(
                            int(existing["message_id"])
                        ).edit(content=None, embeds=[], attachments=[file], view=None)
                    except discord.NotFound:
                        file.reset()
                if sent is None:
                    sent = await i.channel.send(file=file)
                self.store.remember_panel(
                    i.guild_id, i.channel_id, sent.id, self.store.latest()["id"]
                )
            finally:
                file.close()
            await i.followup.send(
                "Painel da tier list pronto. Só a imagem aparece neste canal. Em **Opções**, escolha outro canal para votações, resultados e histórico.",
                view=TierView(self),
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
                log.warning("Comando não concluído: %s", type(cause).__name__)
                await reply(
                    i, "Não consegui concluir agora. Tente novamente em instantes."
                )

    async def close(self):
        if getattr(self, "_tier_closed", False):
            return
        self._tier_closed = True
        for loop in (
            self.analysis_loop,
            self.poll_loop,
            self.panel_loop,
            self.maintenance_loop,
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
