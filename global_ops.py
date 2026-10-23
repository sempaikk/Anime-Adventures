"""Owner-only operational view and quiet, persistent alerts for sustained failures."""

import json
import discord
import aiohttp
from global_views import ScopedView
from tier_views import BoundModal, reply
from tier_ui import edit_response, payload
from tier_release import label


class GlobalOperations:
    def __init__(self, relay):
        self.relay, self.bot, self.store = relay, relay.bot, relay.store

    def snapshot(self):
        now = self.store.clock()
        pending = self.store.one(
            "SELECT COUNT(*) AS n,MIN(m.updated) AS oldest FROM global_deliveries d JOIN global_messages m ON m.id=d.source_id WHERE d.state IN ('queued','preparing','uncertain','sending')"
        )
        failures = self.store.one(
            "SELECT COUNT(*) AS n FROM global_deliveries d JOIN global_messages m ON m.id=d.source_id WHERE d.state='failed' AND m.updated>?",
            (now - 900,),
        )["n"]
        blocked = self.store.one(
            "SELECT COUNT(*) AS n FROM global_restrictions WHERE until>? AND kind='guild'",
            (now,),
        )["n"]
        return {
            "pending": pending["n"],
            "age": max(0, int(now - pending["oldest"])) if pending["oldest"] else 0,
            "failures": failures,
            "contained": blocked,
            "paused": self.store.network_paused(),
            "heartbeat": max(0, int(now - self.relay.last_cycle)),
            "storage": getattr(self.bot.health, "storage_level", "unknown"),
        }

    def description(self, *, compact=False):
        s = self.snapshot()
        text = f"**Chat global:** {'rede pausada' if s['paused'] else 'rede ativa'} · {s['pending']} entrega(s) pendente(s), mais antiga há {s['age']} s.\n**Últimos 15 minutos:** {s['failures']} entrega(s) não confirmada(s).\n**Proteção temporária:** {s['contained']} servidor(es) contido(s).\n**Última passagem da fila:** há {s['heartbeat']} s."
        if compact:
            return text
        text = "## Estado privado do bot\n" + text
        text += f"\n**Armazenamento:** {s['storage']} · banco {self.bot.store.path.stat().st_size / 1024 / 1024:.1f} MiB · cache {self.relay.media.usage() / 1024 / 1024:.1f} MiB."
        build = getattr(self.bot, "build", None)
        if build:
            text += "\n**Versão em execução:** " + label(build)
        for key, title in (
            ("last_connection_success", "Última conexão válida da IA"),
            ("last_success", "Última análise válida"),
        ):
            value = self.bot.store.get(key)
            text += f"\n**{title}:** " + (
                f"<t:{int(float(value))}:R>" if value else "ainda não registrada"
            )
        alerts = self.bot.store.get("global-owner-alerts") != "0"
        text += f"\n**Alertas privados:** {'ativados' if alerts else 'desativados'}. Falhas precisam persistir por dois minutos; cada tipo de alerta tem intervalo de uma hora."
        held = self.store.rows(
            "SELECT target,until,reason FROM global_restrictions WHERE scope='*' AND kind='guild' AND until>? ORDER BY until LIMIT 5",
            (self.store.clock(),),
        )
        for row in held:
            text += f"\n**Servidor {row['target']}:** contido até <t:{int(row['until'])}:t>."
        text += "\n-# Use Moderação da rede para liberar um servidor antes do prazo. Pausar a rede interrompe novos compartilhamentos; exclusões continuam sendo processadas."
        return text

    async def notify(self, text):
        delivered = False
        for ident in sorted(getattr(self.bot, "owner_ids_set", set())):
            try:
                user = self.bot.get_user(ident)
                if user is None:
                    user = await self.bot.fetch_user(ident)
                if user.id == ident and self.bot.is_owner_id(ident):
                    await user.send(**payload(bot=self.bot, content=text))
                    delivered = True
            except (discord.HTTPException, aiohttp.ClientError, TimeoutError, OSError):
                pass
        return delivered

    async def check_alerts(self):
        if self.bot.store.get("global-owner-alerts") == "0":
            return
        s = self.snapshot()
        now = self.store.clock()
        conditions = {
            "storage": (
                s["storage"] == "critical",
                "O armazenamento está crítico. Abra o diagnóstico privado antes de compartilhar mais arquivos.",
            ),
            "queue": (
                s["pending"] > 0 and s["age"] > 180 and not s["paused"],
                "Há entregas esperando há mais de três minutos. Abra Estado do bot para conferir a fila e as permissões.",
            ),
            "worker": (
                s["heartbeat"] > 240 and not s["paused"],
                "A rotina do chat global não registra avanço. Confira os logs e a versão em execução.",
            ),
            "containment": (
                s["contained"] > 0,
                "A proteção conteve temporariamente um ou mais servidores após uma rajada. Confira Estado do bot para revisar.",
            ),
        }
        for key, (active, text) in conditions.items():
            meta = "global-alert:" + key
            previous = json.loads(self.bot.store.get(meta) or "{}")
            if not active:
                if previous.get("sent"):
                    self.bot.store.set(meta, "{}")
                    await self.notify(
                        "## Situação normalizada\n"
                        + {
                            "storage": "O armazenamento deixou de estar crítico.",
                            "queue": "A fila deixou de apresentar o atraso observado.",
                            "worker": "A rotina do chat global voltou a registrar avanço.",
                            "containment": "Não há mais servidores sob contenção temporária.",
                        }[key]
                    )
                elif previous:
                    self.bot.store.set(meta, "{}")
                continue
            if not previous:
                self.bot.store.set(
                    meta, json.dumps({"first": now, "attempted": 0, "sent": False})
                )
                continue
            if (
                now - previous["first"] < 120
                or now - previous.get("attempted", 0) < 3600
            ):
                continue
            previous.update(attempted=now)
            self.bot.store.set(meta, json.dumps(previous))
            delivered = await self.notify(
                "## Atenção · estado do bot\n"
                + text
                + "\n-# Este aviso é privado e não se repete a cada mensagem."
            )
            previous["sent"] = previous.get("sent", False) or delivered
            self.bot.store.set(meta, json.dumps(previous))


class OperationsView(ScopedView):
    def __init__(self, bot, i):
        super().__init__(bot, i, owner=True)

    @discord.ui.button(label="Atualizar estado", row=0)
    async def refresh(self, i, button):
        self.require(i)
        await edit_response(
            i, content=self.bot.globalchat.operations.description(), view=self
        )

    @discord.ui.button(label="Pausar / retomar rede", row=0)
    async def pause(self, i, button):
        self.require(i)
        await i.response.send_modal(NetworkPause(self.bot, i))

    @discord.ui.button(label="Ativar / desativar alertas", row=1)
    async def alerts(self, i, button):
        self.require(i)
        enabled = self.bot.store.get("global-owner-alerts") != "0"
        self.bot.store.set("global-owner-alerts", "0" if enabled else "1")
        await edit_response(
            i, content=self.bot.globalchat.operations.description(), view=self
        )


class NetworkPause(BoundModal):
    def __init__(self, bot, i):
        super().__init__(title="Pausar ou retomar a rede")
        self.bind(bot, i)
        self.was_paused = bot.globalchat.store.network_paused()
        self.reason = discord.ui.TextInput(
            style=discord.TextStyle.paragraph, min_length=5, max_length=500
        )
        self.add_item(
            discord.ui.Label(
                text="Motivo para "
                + ("retomar" if self.was_paused else "pausar")
                + " a rede",
                description="Vale para todos os servidores. A conversa local e exclusões continuam disponíveis.",
                component=self.reason,
            )
        )

    async def on_submit(self, i):
        if not await self.interaction_check(i):
            return
        self.bot.require_owner(i)
        if self.bot.globalchat.store.network_paused() != self.was_paused:
            raise ValueError(
                "O estado da rede mudou. Atualize os controles antes de confirmar."
            )
        self.bot.globalchat.store.pause_network(
            not self.was_paused, i.user.id, str(self.reason)
        )
        await reply(
            i,
            "**Rede "
            + ("retomada" if self.was_paused else "pausada")
            + ".** "
            + (
                "Somente novas mensagens entram no compartilhamento."
                if self.was_paused
                else "Novos compartilhamentos foram interrompidos; remoções continuam sendo processadas."
            ),
        )
