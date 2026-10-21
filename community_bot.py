"""Opt-in community tier lists and durable cross-server conversation relay."""

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

from community_domain import Catalog, MODES, ROLES, TIERS
from community_store import COMMUNITY_TABLES, CommunityStore
from community_ui import (
    PAGE_SIZE,
    changes_embed,
    relay_embed,
    safe,
    tier_payload,
    unit_embed,
)
from runtime_health import RuntimeHealth
from storage_maintenance import maintain_storage

log = logging.getLogger("community")
ROLE_CHOICES = [app_commands.Choice(name=v, value=k) for k, v in ROLES.items()]
MODE_CHOICES = [app_commands.Choice(name=v, value=k) for k, v in MODES.items()]
SCOPES = [
    app_commands.Choice(name="Global", value="global"),
    app_commands.Choice(name="Do servidor", value="server"),
]
CONSENT_TEXT = (
    "**Sua mensagem será compartilhada entre servidores.**\n"
    "O bot publica seu nome, o servidor de origem e o texto nos canais globais conectados. "
    "Depois de confirmar uma vez, as próximas mensagens neste canal são enviadas automaticamente. "
    "A original só é apagada após o bot publicar uma cópia neste servidor. "
    "Use `/global sair` para parar os próximos envios e `/global apagar` para remover uma mensagem sua. "
    "As cópias podem ter sido vistas ou salvas por outras pessoas. Evite dados pessoais. "
    "Texto de envio é guardado por até 7 dias; IDs de autoria e cópias ficam para moderação e remoção. "
    "Anexos e convites não são enviados nesta versão."
)


def context_scope(guild_id, value):
    if value not in ("global", "server"):
        raise ValueError("Escolha Global ou Do servidor.")
    return "global" if value == "global" else "guild:" + str(guild_id)


async def reply(interaction, text=None, **kwargs):
    kwargs.setdefault("ephemeral", True)
    if interaction.response.is_done():
        return await interaction.followup.send(text, **kwargs)
    return await interaction.response.send_message(text, **kwargs)


class GuardedView(discord.ui.View):
    async def on_error(self, interaction, error, item):
        if isinstance(error, ValueError):
            await reply(interaction, str(error))
        else:
            log.error("Falha de interface: %s", type(error).__name__)
            await reply(
                interaction,
                "Não consegui concluir essa ação. Tente novamente em instantes.",
            )


class DraftView(GuardedView):
    def __init__(self, bot, draft):
        super().__init__(timeout=600)
        self.bot = bot
        self.draft = draft

    async def interaction_check(self, i):
        if str(i.user.id) != self.draft["user_id"]:
            await reply(
                i,
                "Esta confirmação é de outra pessoa. Envie sua própria mensagem para participar.",
            )
            return False
        return True

    @discord.ui.button(label="Confirmar e enviar", style=discord.ButtonStyle.success)
    async def accept(self, i, button):
        row = self.bot.store.accept_draft(self.draft["id"], i.user.id)
        await i.response.edit_message(
            content=f"Participação confirmada. Sua primeira mensagem entrou na fila.\nCódigo: `{row['id']}` · acompanhe com `/global status`.",
            view=None,
        )
        self.stop()

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, i, button):
        self.bot.store.cancel_draft(self.draft["id"], i.user.id)
        await i.response.edit_message(
            content="Envio cancelado. Sua mensagem não foi compartilhada.", view=None
        )
        self.stop()


class ConsentView(GuardedView):
    def __init__(self, bot, actor):
        super().__init__(timeout=600)
        self.bot = bot
        self.actor = actor

    @discord.ui.button(
        label="Participar do chat global", style=discord.ButtonStyle.success
    )
    async def accept(self, i, button):
        if i.user.id != self.actor:
            raise ValueError("Abra sua própria confirmação com /global participar.")
        self.bot.store._check_source(i.guild_id, i.channel_id)
        if self.bot.store.blocked(i.user.id):
            raise ValueError("Sua participação está bloqueada.")
        self.bot.store.consent(i.user.id)
        await i.response.edit_message(
            content="Participação confirmada. Você pode escrever neste canal ou usar `/global enviar`.",
            view=None,
        )


class ChatModal(discord.ui.Modal, title="Enviar ao chat global"):
    body = discord.ui.TextInput(
        label="Mensagem para todos os servidores",
        style=discord.TextStyle.paragraph,
        max_length=1000,
    )

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, i):
        try:
            row = self.bot.accept_message(
                i.user, i.guild, i.channel_id, "form:" + str(i.id), str(self.body)
            )
            await reply(
                i,
                f"Mensagem na fila do chat global.\nCódigo: `{row['id']}` · acompanhe com `/global status`.",
            )
        except ValueError as exc:
            await reply(i, str(exc))

    async def on_error(self, i, error):
        await reply(i, "Não consegui enviar agora. Sua mensagem não foi publicada.")


class ReportModal(discord.ui.Modal, title="Sinalizar mensagem global"):
    reason = discord.ui.TextInput(
        label="O que aconteceu?",
        style=discord.TextStyle.paragraph,
        min_length=5,
        max_length=400,
    )

    def __init__(self, bot, job):
        super().__init__()
        self.bot = bot
        self.job = job

    async def on_submit(self, i):
        try:
            self.bot.store.report(
                self.job["relay_id"],
                i.user.id,
                i.guild_id,
                self.job["message_id"],
                str(self.reason),
            )
            await reply(
                i,
                "Denúncia registrada para a moderação da rede. Em caso de urgência, avise a moderação do servidor também.",
            )
        except ValueError as exc:
            await reply(i, str(exc))


class RelayView(GuardedView):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(
        label="Sinalizar",
        custom_id="community:report:v1",
        style=discord.ButtonStyle.secondary,
    )
    async def report(self, i, button):
        job = self.bot.store._one(
            "SELECT * FROM community_deliveries WHERE message_id=? AND guild_id=? AND state='sent'",
            (str(i.message.id), str(i.guild_id)),
        )
        if not job:
            raise ValueError("Não encontrei esta mensagem no registro do chat global.")
        await i.response.send_modal(ReportModal(self.bot, job))


class ReviewModal(discord.ui.Modal, title="Avaliar uma unidade"):
    reason = discord.ui.TextInput(
        label="Por que merece esse tier?",
        style=discord.TextStyle.paragraph,
        min_length=25,
        max_length=700,
    )
    conditions = discord.ui.TextInput(
        label="Trait, equipe, relíquia e situação de uso",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=300,
    )
    evidence = discord.ui.TextInput(
        label="Link HTTPS de referência (opcional)", required=False, max_length=400
    )

    def __init__(self, bot, actor, unit, role, mode, tier, share, period):
        super().__init__()
        self.bot = bot
        self.actor = actor
        self.unit = unit
        self.role = role
        self.mode = mode
        self.tier = tier
        self.share = share
        self.period = period

    async def on_submit(self, i):
        try:
            if i.user.id != self.actor or self.period != self.bot.store.get("period"):
                raise ValueError("O período mudou. Abra uma nova avaliação.")
            self.bot.require_player(i)
            self.bot.store.submit_review(
                i.user.id,
                i.guild_id,
                self.unit.id,
                self.role,
                self.mode,
                self.tier,
                str(self.reason),
                conditions=str(self.conditions),
                evidence=str(self.evidence),
                share_global=self.share,
            )
            await reply(
                i,
                "Avaliação salva. Ela entra no próximo cálculo; a imagem do canal segue o intervalo configurado. Obrigado por explicar sua experiência.",
            )
        except ValueError as exc:
            await reply(i, str(exc))

    async def on_error(self, i, error):
        log.error("Falha ao salvar avaliação: %s", type(error).__name__)
        await reply(i, "Não consegui salvar agora. Tente novamente em instantes.")


class ReviewView(GuardedView):
    def __init__(self, bot, i, unit, role, mode, tier, share):
        super().__init__(timeout=600)
        self.args = (
            bot,
            i.user.id,
            unit,
            role,
            mode,
            tier,
            share,
            bot.store.get("period"),
        )

    @discord.ui.button(label="Escrever avaliação", style=discord.ButtonStyle.primary)
    async def write(self, i, button):
        if i.user.id != self.args[1]:
            raise ValueError("Abra sua própria avaliação com /avaliar.")
        await i.response.send_modal(ReviewModal(*self.args))


class PanelView(GuardedView):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Atualizações", custom_id="community:changes:v1")
    async def changes(self, i, button):
        config = self.bot.store.channel(i.guild_id, "tier")
        scope = context_scope(i.guild_id, config["scope"] if config else "global")
        await reply(i, embed=changes_embed(self.bot.store, self.bot.catalog, scope))

    @discord.ui.button(label="Como participar", custom_id="community:how:v1")
    async def how(self, i, button):
        await reply(
            i,
            "### Sua experiência conta\nUse `/avaliar` e escolha a **forma exata**, função, modo e tier. Explique suas condições de uso.\n\n"
            "**Servidor:** pelo menos 5 pessoas. **Global:** 3 servidores, com 3 pessoas cada, sem dar mais peso a servidores grandes. "
            "Cada pessoa tem uma avaliação atual por contexto. Só avaliações compartilhadas entram no global.\n\n"
            "Notas usam relatos dos últimos 30 dias no período atual. Menções no chat não mudam tiers. Empates mantêm ordem estável. "
            "A imagem é revisada no intervalo escolhido pela administração. Use `/tierlist` para detalhes e páginas.",
        )

    @discord.ui.button(label="Navegar pela lista", custom_id="community:browse:v1")
    async def browse(self, i, button):
        config = self.bot.store.channel(i.guild_id, "tier")
        if not config:
            raise ValueError("Use /tierlist para escolher uma função e um modo.")
        await i.response.defer(ephemeral=True, thinking=True)
        scope = context_scope(i.guild_id, config["scope"])
        embed, file, _ = tier_payload(
            self.bot.store, self.bot.catalog, config["role"], config["mode"], scope
        )
        await reply(
            i,
            embed=embed,
            file=file,
            view=TierPages(self.bot, i.user.id, config["role"], config["mode"], scope),
        )


class TierPages(GuardedView):
    def __init__(self, bot, actor, role, mode, scope, page=1):
        super().__init__(timeout=600)
        self.bot, self.actor, self.role, self.mode, self.scope, self.page = (
            bot,
            actor,
            role,
            mode,
            scope,
            page,
        )

    async def interaction_check(self, i):
        if i.user.id != self.actor:
            await reply(i, "Abra sua própria lista com /tierlist.")
            return False
        return True

    async def turn(self, i, delta):
        await i.response.defer()
        pages = (len(self.bot.catalog.units) + PAGE_SIZE - 1) // PAGE_SIZE
        self.page = max(1, min(self.page + delta, pages))
        embed, file, _ = tier_payload(
            self.bot.store,
            self.bot.catalog,
            self.role,
            self.mode,
            self.scope,
            page=self.page,
        )
        await i.edit_original_response(embed=embed, attachments=[file], view=self)

    @discord.ui.button(label="Anterior")
    async def previous(self, i, button):
        await self.turn(i, -1)

    @discord.ui.button(label="Próxima")
    async def next_page(self, i, button):
        await self.turn(i, 1)

    @discord.ui.button(label="Atualizações")
    async def changes(self, i, button):
        await reply(
            i, embed=changes_embed(self.bot.store, self.bot.catalog, self.scope)
        )


class CommunityBot(commands.Bot):
    def __init__(self, data_dir=None):
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True
        intents.message_content = True
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        self.catalog = Catalog()
        self.store = CommunityStore(
            Path(data_dir or os.getenv("DATA_DIR", "state")) / "community.sqlite3"
        )
        self.health = RuntimeHealth(self.is_ready, lambda: self.store.connection)
        self.network_mods = {
            int(s)
            for s in os.getenv("COMMUNITY_MODERATOR_IDS", "").split(",")
            if s.strip().isdigit()
        }
        self.owner_ids_set = set()
        self.panel_hashes = {}
        self.last_panels = {}
        self.warned = {}
        self.maintenance_at = 0
        self.register_commands()

    async def setup_hook(self):
        app = await self.application_info()
        self.owner_ids_set = (
            {m.id for m in app.team.members} if app.team else {app.owner.id}
        )
        self.add_view(RelayView(self))
        self.add_view(PanelView(self))
        await self.health.start(
            int(os.getenv("PORT") or os.getenv("SERVER_PORT") or 8080)
        )
        await self.tree.sync()
        self.delivery_loop.start()
        self.panel_loop.start()
        self.maintenance_loop.start()
        log.info(
            "Comandos da comunidade sincronizados; %s identidades, sem API de IA.",
            len(self.catalog.units),
        )

    async def on_ready(self):
        log.info("Bot da comunidade conectado; %s servidores.", len(self.guilds))

    def is_network_mod(self, user_id):
        return user_id in self.owner_ids_set or user_id in self.network_mods

    def require_mod(self, i):
        if not self.is_network_mod(i.user.id):
            raise ValueError("Esta ação é da moderação da rede.")

    def require_admin(self, i):
        if not i.guild_id or not i.permissions.manage_guild:
            raise ValueError(
                "Você precisa de Gerenciar servidor para configurar este recurso."
            )

    def require_player(self, i):
        if not i.guild_id:
            raise ValueError("Use este comando em um servidor.")
        if self.store.blocked(i.user.id):
            raise ValueError("Sua participação está bloqueada. Procure a moderação.")
        if (discord.utils.utcnow() - i.user.created_at).total_seconds() < 7 * 86400:
            raise ValueError(
                "Para participar, sua conta precisa ter pelo menos 7 dias."
            )
        if self.health.storage_level == "critical":
            raise ValueError("O armazenamento precisa de manutenção. Tente mais tarde.")

    def check_channel(self, i, channel, *, manage=False):
        self.require_admin(i)
        if channel.guild.id != i.guild_id:
            raise ValueError("Escolha um canal deste servidor.")
        perms = channel.permissions_for(i.guild.me)
        if not (perms.view_channel and perms.send_messages and perms.embed_links):
            raise ValueError(
                "O bot precisa de Ver canal, Enviar mensagens e Inserir links nesse canal."
            )
        if manage and not perms.manage_messages:
            raise ValueError(
                "Para substituir as mensagens originais, conceda Gerenciar mensagens ao bot neste canal."
            )

    def accept_message(self, user, guild, channel_id, event, body, original=None):
        if (discord.utils.utcnow() - user.created_at).total_seconds() < 7 * 86400:
            raise ValueError("Sua conta precisa ter pelo menos 7 dias para participar.")
        if self.health.storage_level == "critical":
            raise ValueError(
                "A rede está temporariamente indisponível por armazenamento."
            )
        return self.store.enqueue(
            user.id,
            guild.id,
            channel_id,
            event,
            user.display_name,
            guild.name,
            body,
            original_id=original,
        )

    async def on_message(self, message):
        if message.author.bot or message.webhook_id or not message.guild:
            return
        config = self.store.channel_at(message.channel.id)
        if not config:
            return
        if config["kind"] == "observe":
            self.store.record_mentions(
                message.author.id,
                message.guild.id,
                self.catalog.mentions(message.content),
            )
            return
        if config["kind"] != "global" or config["input_mode"] != "messages":
            return
        try:
            if message.attachments or message.stickers:
                raise ValueError(
                    "Por enquanto, o chat global envia só texto. Seu anexo ficou neste servidor."
                )
            if not message.content:
                return
            if not self.store.consented(message.author.id):
                if (
                    discord.utils.utcnow() - message.author.created_at
                ).total_seconds() < 7 * 86400:
                    raise ValueError(
                        "Sua conta precisa ter pelo menos 7 dias para participar."
                    )
                draft = self.store.draft(
                    message.author.id,
                    message.guild.id,
                    message.channel.id,
                    str(message.id),
                    message.author.display_name,
                    message.guild.name,
                    message.content,
                )
                preview = discord.Embed(
                    title="Prévia da mensagem que será enviada",
                    description=safe(draft["body"]),
                    color=0x9265E8,
                )
                await message.reply(
                    CONSENT_TEXT,
                    embed=preview,
                    view=DraftView(self, draft),
                    mention_author=False,
                )
                return
            self.accept_message(
                message.author,
                message.guild,
                message.channel.id,
                str(message.id),
                message.content,
                message.id,
            )
        except ValueError as exc:
            if time.monotonic() - self.warned.get(message.author.id, 0) >= 10:
                self.warned[message.author.id] = time.monotonic()
                if len(self.warned) > 1000:
                    self.warned.clear()
                await message.reply(str(exc), mention_author=False, delete_after=30)
        except discord.HTTPException:
            log.warning("Não foi possível mostrar um aviso local.")
        except Exception as exc:
            log.error("Falha ao receber mensagem: %s", type(exc).__name__)

    async def deliver(self, job):
        if self.store.get("global_paused") == "1":
            return
        if not self.store.delivery_valid(job):
            self.store.cancel_job(job["id"])
            return
        row = self.store.relay(job["relay_id"])
        channel = self.get_channel(int(job["channel_id"]))
        if channel is None:
            # Guild loss / removed configuration cannot trigger cross-guild API access.
            self.store.fail_job(job, permanent=True)
            return
        try:
            # Official recent-message nonce deduplication limits retries after lost acknowledgements.
            nonce = str(
                int(
                    hashlib.sha256(
                        (row["id"] + ":" + job["channel_id"]).encode()
                    ).hexdigest()[:15],
                    16,
                )
            )
            view = RelayView(self)
            with handle_message_parameters(
                embed=relay_embed(row),
                view=view,
                nonce=nonce,
                allowed_mentions=discord.AllowedMentions.none(),
            ) as params:
                params.payload["enforce_nonce"] = True
                data = await self.http.send_message(channel.id, params=params)
            self.store.mark_sent(
                job["id"], data["id"], revoked=not self.store.delivery_valid(job)
            )
        except (discord.Forbidden, discord.NotFound):
            self.store.fail_job(job, permanent=True)
        except (discord.HTTPException, OSError, asyncio.TimeoutError):
            self.store.fail_job(job)

    async def remove_originals(self):
        for row in self.store.originals_to_delete():
            channel = self.get_channel(int(row["channel_id"]))
            if not channel:
                self.store.mark_original(row["id"], "unavailable")
                continue
            try:
                await channel.get_partial_message(int(row["original_id"])).delete()
                self.store.mark_original(row["id"], "deleted")
            except discord.NotFound:
                self.store.mark_original(row["id"], "deleted")
            except discord.Forbidden:
                self.store.mark_original(row["id"], "permission-denied")
                log.warning(
                    "Cópia local publicada; original preservada por falta de permissão."
                )
            except discord.HTTPException:
                pass

    @tasks.loop(seconds=2)
    async def delivery_loop(self):
        try:
            await self.remove_originals()
            for job in self.store.jobs():
                await self.deliver(job)
            for job in self.store.deletions():
                channel = self.get_channel(int(job["channel_id"]))
                if not channel:
                    continue
                try:
                    await channel.get_partial_message(int(job["message_id"])).delete()
                    self.store.deleted(job["id"])
                except discord.NotFound:
                    self.store.deleted(job["id"])
                except (discord.Forbidden, discord.HTTPException):
                    with self.store.connection:
                        self.store.connection.execute(
                            "UPDATE community_deliveries SET next_try=? WHERE id=?",
                            (time.time() + 300, job["id"]),
                        )
        except Exception as exc:
            log.error("Fila preservada após falha: %s", type(exc).__name__)

    @delivery_loop.before_loop
    async def wait_for_gateway(self):
        await self.wait_until_ready()

    @tasks.loop(seconds=60)
    async def panel_loop(self):
        try:
            self.store.refresh_tiers()
            now = time.time()
            for config in self.store.channels("tier"):
                cid = config["channel_id"]
                interval = (
                    int(self.store.get("panel_minutes:" + config["guild_id"]) or 30)
                    * 60
                )
                if now - self.last_panels.get(cid, 0) < interval:
                    continue
                channel = self.get_channel(int(cid))
                if not channel:
                    continue
                scope = context_scope(config["guild_id"], config["scope"])
                embed, file, digest = tier_payload(
                    self.store,
                    self.catalog,
                    config["role"],
                    config["mode"],
                    scope,
                    published_at=now,
                    interval_minutes=interval // 60,
                )
                self.last_panels[cid] = now
                if self.panel_hashes.get(cid) == digest:
                    file.close()
                    continue
                try:
                    if config["panel_id"]:
                        try:
                            await channel.get_partial_message(
                                int(config["panel_id"])
                            ).edit(
                                embed=embed, attachments=[file], view=PanelView(self)
                            )
                        except discord.NotFound:
                            file.reset()
                            sent = await channel.send(
                                embed=embed, file=file, view=PanelView(self)
                            )
                            self.store.set_panel(config["guild_id"], "tier", sent.id)
                    else:
                        sent = await channel.send(
                            embed=embed, file=file, view=PanelView(self)
                        )
                        self.store.set_panel(config["guild_id"], "tier", sent.id)
                    self.panel_hashes[cid] = digest
                except discord.HTTPException:
                    log.warning(
                        "Painel não atualizado; tentativa no próximo intervalo."
                    )
                finally:
                    file.close()
        except Exception as exc:
            log.error("Falha no cálculo dos painéis: %s", type(exc).__name__)

    @panel_loop.before_loop
    async def panels_ready(self):
        await self.wait_until_ready()

    @tasks.loop(minutes=15)
    async def maintenance_loop(self):
        try:
            self.store.cleanup()
            report = await asyncio.to_thread(
                maintain_storage, self.store.path, required_tables=COMMUNITY_TABLES
            )
            self.health.update_storage(report)
        except Exception as exc:
            self.health.backup_error = True
            log.error("Manutenção de armazenamento: %s", type(exc).__name__)

    async def on_guild_remove(self, guild):
        for kind in ("global", "observe", "tier"):
            self.store.disable(guild.id, kind)

    async def close(self):
        if getattr(self, "_community_closed", False):
            return
        self._community_closed = True
        for loop in (self.delivery_loop, self.panel_loop, self.maintenance_loop):
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

    def register_commands(self):
        async def unit_complete(i, current):
            return [
                app_commands.Choice(name=u.name[:100], value=u.id)
                for u in self.catalog.search(current)
            ]

        @self.tree.command(
            name="tierlist",
            description="Veja a classificação da comunidade por função, modo e forma.",
        )
        @app_commands.guild_only()
        @app_commands.choices(alcance=SCOPES, funcao=ROLE_CHOICES, modo=MODE_CHOICES)
        @app_commands.autocomplete(unidade=unit_complete)
        async def tierlist(
            i: discord.Interaction,
            alcance: str = "global",
            funcao: str = "damage",
            modo: str = "general",
            pagina: app_commands.Range[int, 1, 50] = 1,
            unidade: str | None = None,
        ):
            await i.response.defer(ephemeral=True, thinking=True)
            scope = context_scope(i.guild_id, alcance)
            if unidade:
                await reply(
                    i,
                    embed=unit_embed(
                        self.store,
                        self.catalog,
                        self.catalog.resolve(unidade),
                        funcao,
                        modo,
                        scope,
                    ),
                )
                return
            self.store.refresh_tiers()
            embed, file, _ = tier_payload(
                self.store, self.catalog, funcao, modo, scope, page=pagina
            )
            await reply(
                i,
                embed=embed,
                file=file,
                view=TierPages(self, i.user.id, funcao, modo, scope, pagina),
            )

        @self.tree.command(
            name="avaliar",
            description="Conte como uma unidade se sai nas suas condições de jogo.",
        )
        @app_commands.guild_only()
        @app_commands.choices(
            funcao=ROLE_CHOICES,
            modo=MODE_CHOICES,
            tier=[app_commands.Choice(name=t, value=t) for t in reversed(TIERS)],
        )
        @app_commands.autocomplete(unidade=unit_complete)
        async def avaliar(
            i: discord.Interaction,
            unidade: str,
            funcao: str,
            modo: str,
            tier: str,
            compartilhar_global: bool = True,
        ):
            self.require_player(i)
            unit = self.catalog.resolve(unidade)
            await reply(
                i,
                f"### {safe(unit.name)}\n**{ROLES[funcao]} · {MODES[modo]} · tier {tier}**\n"
                f"Visibilidade: **{'servidor e global' if compartilhar_global else 'somente este servidor'}**. "
                "Seu relato será mostrado nos detalhes da unidade. Não inclua dados pessoais. "
                "Uma avaliação por pessoa, unidade, forma, modo e função; sua atualização substitui a anterior. "
                "Relatos não são estatísticas oficiais. Você pode removê-los com `/privacidade`.",
                view=ReviewView(self, i, unit, funcao, modo, tier, compartilhar_global),
            )

        @self.tree.command(
            name="atualizacoes",
            description="Confira por que uma unidade mudou de tier neste período.",
        )
        @app_commands.guild_only()
        @app_commands.choices(alcance=SCOPES)
        async def updates(i: discord.Interaction, alcance: str = "global"):
            await reply(
                i,
                embed=changes_embed(
                    self.store, self.catalog, context_scope(i.guild_id, alcance)
                ),
            )

        global_group = app_commands.Group(
            name="global",
            description="Converse com a comunidade dos servidores conectados.",
            guild_only=True,
        )

        @global_group.command(
            name="participar",
            description="Entenda o compartilhamento e confirme sua participação uma vez.",
        )
        async def participate(i: discord.Interaction):
            self.require_player(i)
            self.store._check_source(i.guild_id, i.channel_id)
            await reply(i, CONSENT_TEXT, view=ConsentView(self, i.user.id))

        @global_group.command(
            name="enviar", description="Escreva uma mensagem global por formulário."
        )
        async def send(i: discord.Interaction):
            self.require_player(i)
            self.store._check_source(i.guild_id, i.channel_id)
            if not self.store.consented(i.user.id):
                await reply(i, CONSENT_TEXT, view=ConsentView(self, i.user.id))
                return
            await i.response.send_modal(ChatModal(self))

        @global_group.command(
            name="sair",
            description="Pare o envio automático das suas próximas mensagens.",
        )
        async def leave(i: discord.Interaction):
            self.store.withdraw(i.user.id)
            await reply(
                i,
                "Participação desativada. Novas mensagens não serão compartilhadas até você confirmar novamente. O histórico já publicado continua; use `/global apagar` para remover mensagens suas.",
            )

        @global_group.command(
            name="apagar",
            description="Remova uma mensagem sua dos canais globais conectados.",
        )
        async def delete(i: discord.Interaction, codigo: str):
            self.store.delete_relay(
                codigo.strip(), i.user.id, moderator=self.is_network_mod(i.user.id)
            )
            await reply(
                i,
                "Remoção solicitada para todas as cópias registradas. O bot tentará novamente onde houver falha de conexão.",
            )

        @global_group.command(
            name="status",
            description="Acompanhe o envio ou a remoção de uma mensagem sua.",
        )
        async def message_status(i: discord.Interaction, codigo: str):
            row = self.store.relay(codigo.strip())
            if not row or (
                row["user_id"] != str(i.user.id) and not self.is_network_mod(i.user.id)
            ):
                raise ValueError("Esse registro não é de uma mensagem sua.")
            jobs = self.store._all(
                "SELECT state,COUNT(*) AS n FROM community_deliveries WHERE relay_id=? GROUP BY state",
                (row["id"],),
            )
            labels = {
                "sent": "Enviadas",
                "queued": "Na fila",
                "failed": "Falharam",
                "cancelled": "Canceladas",
                "delete": "Remoção pendente",
                "deleted": "Removidas",
            }
            await reply(
                i,
                "### Estado da mensagem\n"
                + "\n".join(
                    f"**{labels.get(r['state'], r['state'])}:** {r['n']}" for r in jobs
                )
                + "\n\nFalhas de envio não significam remoção de cópias já publicadas. Se a cópia local falhar, a original fica preservada.",
            )

        self.tree.add_command(global_group)

        config_group = app_commands.Group(
            name="configurar",
            description="Ative os canais da comunidade neste servidor.",
            guild_only=True,
            default_permissions=discord.Permissions(manage_guild=True),
        )

        @config_group.command(
            name="global",
            description="Conecte um canal ao chat global com participação confirmada.",
        )
        @app_commands.choices(
            entrada=[
                app_commands.Choice(name="Escrever no canal", value="messages"),
                app_commands.Choice(name="Formulário /global enviar", value="form"),
            ]
        )
        async def setup_global(
            i: discord.Interaction,
            canal: discord.TextChannel,
            entrada: str = "messages",
        ):
            self.check_channel(i, canal, manage=entrada == "messages")
            await i.response.defer(ephemeral=True, thinking=True)
            await canal.send(
                "## Chat global\n"
                + CONSENT_TEXT
                + "\n\nA moderação deste servidor ativou a conexão. Para começar, use `/global participar`."
            )
            self.store.configure(
                i.guild_id, i.guild.name, "global", canal.id, input_mode=entrada
            )
            await reply(
                i,
                f"Chat global ativado em {canal.mention}. "
                + (
                    "Os participantes precisam poder escrever neste canal; o bot precisa de Gerenciar mensagens."
                    if entrada == "messages"
                    else "Os participantes usam `/global enviar`; você pode deixar o canal sem envio de mensagens para membros."
                ),
            )

        @config_group.command(
            name="tierlist",
            description="Publique um painel de tier list que o bot atualiza sem novas mensagens.",
        )
        @app_commands.choices(
            alcance=SCOPES,
            funcao=ROLE_CHOICES,
            modo=MODE_CHOICES,
            intervalo=[
                app_commands.Choice(name="30 minutos", value=30),
                app_commands.Choice(name="1 hora", value=60),
            ],
        )
        async def setup_tier(
            i: discord.Interaction,
            canal: discord.TextChannel,
            alcance: str = "global",
            funcao: str = "damage",
            modo: str = "general",
            intervalo: int = 30,
        ):
            self.check_channel(i, canal)
            if not canal.permissions_for(i.guild.me).attach_files:
                raise ValueError(
                    "Conceda Anexar arquivos ao bot nesse canal para publicar a imagem."
                )
            self.store.configure(
                i.guild_id,
                i.guild.name,
                "tier",
                canal.id,
                role=funcao,
                mode=modo,
                scope=alcance,
            )
            self.store.set("panel_minutes:" + str(i.guild_id), intervalo)
            self.last_panels.pop(str(canal.id), None)
            self.panel_hashes.pop(str(canal.id), None)
            await reply(
                i,
                f"Painel configurado em {canal.mention}; a primeira imagem aparece em até um minuto. Atualizações a cada {intervalo} minutos quando houver mudança. Deixe o canal sem permissão de envio para membros se quiser usar só o painel.",
            )

        @config_group.command(
            name="observacao",
            description="Conte menções a unidades neste canal, sem armazenar conversas.",
        )
        async def observe(i: discord.Interaction, canal: discord.TextChannel):
            self.check_channel(i, canal)
            await canal.send(
                "## Unidades em debate\nA administração ativou a contagem de menções a unidades neste canal. O bot não salva o texto das conversas para isso e não transforma menções em notas. Para contribuir com a classificação, use `/avaliar`. Contagens duram 7 dias e são limitadas por participante."
            )
            self.store.configure(i.guild_id, i.guild.name, "observe", canal.id)
            await reply(
                i,
                "Observação ativada. As menções medem interesse; avaliações estruturadas definem os tiers.",
            )

        @config_group.command(
            name="desativar",
            description="Desconecte um recurso deste servidor e cancele envios pendentes.",
        )
        @app_commands.choices(
            recurso=[
                app_commands.Choice(name=n, value=v)
                for n, v in [
                    ("Chat global", "global"),
                    ("Tier list", "tier"),
                    ("Observação", "observe"),
                ]
            ]
        )
        async def disable(i: discord.Interaction, recurso: str):
            self.require_admin(i)
            self.store.disable(i.guild_id, recurso)
            await reply(
                i,
                "Recurso desativado neste servidor. O histórico publicado não foi apagado.",
            )

        self.tree.add_command(config_group)

        mod_group = app_commands.Group(
            name="moderacao",
            description="Gerencie a segurança da rede e a curadoria das classificações.",
            guild_only=True,
        )

        @mod_group.command(
            name="denuncias", description="Consulte as denúncias pendentes da rede."
        )
        async def reports(i: discord.Interaction):
            self.require_mod(i)
            rows = self.store.reports()
            await reply(
                i,
                "### Denúncias pendentes\n"
                + (
                    "\n\n".join(
                        f"**#{r['id']}** · código `{r['relay_id']}`\n{safe(r['reason'], 300)}"
                        for r in rows
                    )
                    or "Nenhuma denúncia pendente."
                ),
            )

        @mod_group.command(
            name="resolver",
            description="Marque uma denúncia como revisada após a moderação.",
        )
        async def resolve_report(i: discord.Interaction, numero: int):
            self.require_mod(i)
            with self.store.connection:
                self.store.connection.execute(
                    "UPDATE community_reports SET reviewed_at=? WHERE id=?",
                    (time.time(), numero),
                )
            await reply(i, "Denúncia marcada como revisada.")

        @mod_group.command(
            name="bloquear", description="Bloqueie a participação de uma conta na rede."
        )
        async def block(i: discord.Interaction, usuario: discord.User, motivo: str):
            self.require_mod(i)
            self.store.block(usuario.id, motivo)
            await reply(
                i,
                "Participação bloqueada. Novos envios são cancelados e suas avaliações deixam de contar.",
            )

        @mod_group.command(
            name="desbloquear",
            description="Libere a participação de uma conta na rede.",
        )
        async def unblock(i: discord.Interaction, usuario: discord.User):
            self.require_mod(i)
            self.store.unblock(usuario.id)
            await reply(
                i, "Participação liberada. O chat global exige uma nova confirmação."
            )

        @mod_group.command(
            name="pausar_global",
            description="Pause ou retome os envios do chat global da rede.",
        )
        async def pause(i: discord.Interaction, pausado: bool):
            self.require_mod(i)
            self.store.set("global_paused", int(pausado))
            await reply(
                i, "Chat global pausado." if pausado else "Chat global retomado."
            )

        @mod_group.command(
            name="periodo",
            description="Abra um novo período de avaliação após uma atualização confirmada.",
        )
        async def period(i: discord.Interaction, nome: str):
            self.require_mod(i)
            self.store.set_period(nome)
            await reply(
                i,
                "Novo período aberto. O histórico anterior foi preservado; suas notas não foram copiadas para o novo balanceamento.",
            )

        @mod_group.command(
            name="definir",
            description="Adicione uma classificação de curadoria com justificativa explícita.",
        )
        @app_commands.choices(
            alcance=SCOPES,
            funcao=ROLE_CHOICES,
            modo=MODE_CHOICES,
            tier=[app_commands.Choice(name=t, value=t) for t in reversed(TIERS)],
        )
        @app_commands.autocomplete(unidade=unit_complete)
        async def editorial(
            i: discord.Interaction,
            unidade: str,
            funcao: str,
            modo: str,
            tier: str,
            motivo: str,
            alcance: str = "server",
        ):
            if alcance == "global":
                self.require_mod(i)
            else:
                self.require_admin(i)
            unit = self.catalog.resolve(unidade)
            self.store.editorial(
                context_scope(i.guild_id, alcance), unit.id, funcao, modo, tier, motivo
            )
            await reply(
                i,
                "Classificação salva como **Curadoria**, com motivo no histórico. Ela será revisada quando houver consenso estável da comunidade.",
            )

        self.tree.add_command(mod_group)

        @self.tree.command(
            name="privacidade",
            description="Veja os dados usados pelo bot ou remova suas avaliações.",
        )
        @app_commands.guild_only()
        async def privacy(i: discord.Interaction, remover_avaliacoes: bool = False):
            if remover_avaliacoes:
                self.store.erase_reviews(i.user.id)
                await reply(
                    i,
                    "Suas avaliações foram removidas. Os próximos cálculos deixam de usá-las. O histórico agregado de mudanças continua sem autoria.",
                )
                return
            await reply(
                i,
                "### Seus dados\n**Avaliações:** nota, justificativa, condições, link opcional, IDs de usuário e servidor, período e datas. Você escolhe compartilhar no global. Use `remover_avaliacoes: Sim` para apagar.\n\n"
                "**Chat global:** envio só após confirmação. Texto fica até 7 dias no banco; IDs de autoria e cópias são mantidos para remoção e moderação. `/global sair` cancela futuros envios; `/global apagar` remove uma mensagem. As cópias do Discord ficam até remoção.\n\n"
                "**Observação:** só contagem de menções por unidade por 7 dias, sem texto da conversa, com identificador pseudônimo para limitar repetição. Não usamos API externa de IA. Backups locais são substituídos diariamente; uma exclusão pode permanecer na cópia anterior até a próxima substituição.",
            )

        @self.tree.error
        async def command_error(i, error):
            cause = getattr(error, "original", error)
            if isinstance(cause, (ValueError, app_commands.CheckFailure)):
                await reply(i, str(cause))
            else:
                log.error("Comando falhou: %s", type(cause).__name__)
                await reply(
                    i, "Não consegui concluir agora. Tente novamente em instantes."
                )


def run():
    load_dotenv()
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise SystemExit("Defina DISCORD_TOKEN no ambiente da hospedagem.")
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
