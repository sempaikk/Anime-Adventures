"""Private, scoped report inbox with review history and deliberate moderation actions."""

import json
import discord
from global_views import ScopedView
from global_moderation import REPORT_STATES
from tier_views import BoundModal, reply
from tier_ui import edit_response
from tier_domain import safe


class ReportInbox(ScopedView):
    def __init__(self, bot, i, *, network=False):
        super().__init__(bot, i, admin=True, owner=network)
        self.scope = None if network else i.guild_id
        self.page = 0
        self.status = "pending"
        self.selected = None
        self.rows = []
        self.total = 0
        self.refresh()

    def refresh(self):
        self.rows, self.total, self.page = self.bot.globalchat.store.report_page(
            self.scope, self.status, self.page
        )
        ids = {r["id"] for r in self.rows}
        if self.selected not in ids:
            self.selected = self.rows[0]["id"] if self.rows else None
        self.previous.disabled = self.page == 0
        self.next.disabled = (self.page + 1) * 5 >= self.total
        self.choose.disabled = not self.rows
        self.review.disabled = not self.rows
        self.choose.options = [
            discord.SelectOption(
                label=f"Denúncia #{r['id']} · {REPORT_STATES[r['status']]}",
                value=str(r["id"]),
                description=r["reason"][:90],
                default=r["id"] == self.selected,
            )
            for r in self.rows
        ] or [discord.SelectOption(label="Nenhuma denúncia", value="0")]
        for option in self.filter.options:
            option.default = option.value == self.status

    def description(self):
        self.refresh()
        title = (
            "Denúncias da rede" if self.scope is None else "Denúncias deste servidor"
        )
        text = (
            f"## {title}\n**Página {self.page + 1}/{max(1, (self.total + 4) // 5)} · {self.total} registro(s).**\nSelecione uma denúncia e revise com um motivo. As ações deste painel valem "
            + (
                "para toda a rede."
                if self.scope is None
                else "somente para este servidor."
            )
        )
        row = next((r for r in self.rows if r["id"] == self.selected), None)
        if not row:
            return text + "\n\nNenhuma denúncia neste filtro."
        text += f"\n\n### #{row['id']} · {REPORT_STATES[row['status']]}\n**Motivo enviado:** {safe(row['reason'], 500)}"
        source = self.bot.globalchat.store.message(row["source_id"])
        cfg = self.bot.globalchat.store.channel(row["guild_id"])
        if source and cfg:
            channel = self.bot.globalchat.channel(cfg["channel_id"])
            # A guild manager need not have access to every private channel.
            member = channel.guild.get_member(self.actor) if channel else None
            permissions = (
                channel.permissions_for(member) if channel and member else None
            )
            can_read = bool(
                permissions
                and permissions.view_channel
                and permissions.read_message_history
            )
            if can_read:
                body = json.loads(source["payload"]).get("body")
                if body:
                    text += "\n**Trecho disponível no cache:** " + safe(body, 300)
                delivery = self.bot.globalchat.store.delivery(
                    source["id"], cfg["channel_id"]
                )
                ids = json.loads(delivery["receipts"]) if delivery else []
                ident = (
                    source["id"]
                    if source["channel_id"] == cfg["channel_id"]
                    else next((x for x in ids if x), None)
                )
                if ident:
                    text += f"\n[Abrir mensagem neste servidor](https://discord.com/channels/{cfg['guild_id']}/{cfg['channel_id']}/{ident})"
            if self.scope is None:
                text += f"\n**Origem interna:** servidor {source['guild_id']} · pessoa {source['user_id']}."
        text += "\n-# Conteúdo apagado ou fora do cache pode estar indisponível; a denúncia não guarda uma cópia permanente da conversa."
        if row["resolution"]:
            text += f"\n**Última revisão:** {safe(row['resolution'], 500)}\n**Responsável:** {row['actor']} · <t:{int(row['updated'])}:R>."
        return text

    @discord.ui.button(label="Anterior", row=0)
    async def previous(self, i, button):
        self.require(i)
        self.page = max(0, self.page - 1)
        await edit_response(i, content=self.description(), view=self)

    @discord.ui.button(label="Próxima", row=0)
    async def next(self, i, button):
        self.require(i)
        self.page += 1
        await edit_response(i, content=self.description(), view=self)

    @discord.ui.button(label="Atualizar", row=0)
    async def reload(self, i, button):
        self.require(i)
        await edit_response(i, content=self.description(), view=self)

    @discord.ui.select(
        placeholder="Estado das denúncias",
        options=[
            discord.SelectOption(label=v, value=k)
            for k, v in (*REPORT_STATES.items(), ("all", "Todas"))
        ],
        row=1,
    )
    async def filter(self, i, select):
        self.require(i)
        self.status = select.values[0]
        self.page = 0
        await edit_response(i, content=self.description(), view=self)

    @discord.ui.select(
        placeholder="Selecionar denúncia",
        options=[discord.SelectOption(label="Carregando", value="0")],
        row=2,
    )
    async def choose(self, i, select):
        self.require(i)
        selected = int(select.values[0])
        if selected not in {r["id"] for r in self.rows}:
            raise ValueError("Selecione uma denúncia desta página.")
        self.selected = selected
        await edit_response(i, content=self.description(), view=self)

    @discord.ui.button(
        label="Revisar denúncia", style=discord.ButtonStyle.primary, row=3
    )
    async def review(self, i, button):
        self.require(i)
        row = self.bot.globalchat.store.report_record(self.selected, self.scope)
        await i.response.send_modal(ReportDecision(self.bot, i, row, self.scope))


class ReportDecision(BoundModal):
    def __init__(self, bot, i, row, scope):
        super().__init__(title=f"Revisar denúncia #{row['id']}")
        self.bind(bot, i)
        self.ident, self.version, self.scope = row["id"], row["version"], scope
        self.action = discord.ui.Select(
            options=[
                discord.SelectOption(label="Resolver sem punição", value="resolve"),
                discord.SelectOption(label="Descartar denúncia", value="dismiss"),
                discord.SelectOption(label="Reabrir revisão", value="reopen"),
                discord.SelectOption(
                    label="Bloquear pessoa por uma hora", value="block-hour"
                ),
                discord.SelectOption(
                    label="Solicitar remoção das cópias", value="remove"
                ),
            ]
        )
        self.reason = discord.ui.TextInput(
            style=discord.TextStyle.paragraph, min_length=5, max_length=500
        )
        self.add_item(
            discord.ui.Label(
                text="Ação",
                description="Escopo: "
                + ("rede inteira" if scope is None else "somente este servidor"),
                component=self.action,
            )
        )
        self.add_item(discord.ui.Label(text="Motivo da decisão", component=self.reason))

    async def on_submit(self, i):
        if not await self.interaction_check(i):
            return
        self.bot.require_admin(i)
        if self.scope is None:
            self.bot.require_owner(i)
        elif self.scope != i.guild_id:
            raise ValueError("Esta revisão pertence a outro servidor.")
        action = self.action.values[0]
        state = self.bot.globalchat.store.review_report(
            self.ident, self.scope, i.user.id, self.version, action, str(self.reason)
        )
        message = f"**Denúncia #{self.ident}: {REPORT_STATES[state]}.** A decisão e o responsável foram registrados."
        if action == "remove":
            message += " A remoção das cópias acessíveis foi solicitada; a original permanece com o autor."
        if action == "block-hour":
            message += " O bloqueio expira em uma hora."
        await reply(i, message + " Use Atualizar na lista para acompanhar.")
