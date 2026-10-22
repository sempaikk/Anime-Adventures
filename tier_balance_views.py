"""Owner-only update workflow with a concrete preview before the global change."""

from datetime import datetime, timedelta, timezone

import discord

import tier_balance
from tier_domain import safe
from tier_ui import edit_response
from tier_views import BoundModal, PrivateView, reply


BRT = timezone(timedelta(hours=-3))


class BalancePanel(PrivateView):
    def __init__(self, bot, i):
        super().__init__(bot, i, owner=True)
        self.resume.disabled = not tier_balance.paused(bot.store)

    def text(self):
        update = tier_balance.state(self.bot.store)
        status = (
            f"**Atualização registrada:** {safe(update['label'], 80)} · <t:{int(update['effective_at'])}:f>.\n"
            + (
                "**Análises pausadas:** confira as fontes antes de retomar."
                if update["paused"]
                else "**Análises liberadas** após a conferência das fontes."
            )
            if update
            else "Nenhum novo balanceamento registrado por estes controles."
        )
        return (
            "## Atualizações do jogo\n"
            + status
            + "\n\nUse apenas quando houver uma atualização ou balanceamento real no jogo. Registrar pausa novas propostas, cancela enquetes em andamento e deixa de usar relatos anteriores à data informada. As imagens, decisões encerradas e votos anteriores são preservados.\n\nDepois de conferir as fontes para essa atualização, use **Retomar análise**. Apenas você controla este processo global; os ADMs dos servidores não precisam configurar nada."
        )

    @discord.ui.button(label="Registrar atualização", style=discord.ButtonStyle.primary)
    async def register(self, i, button):
        self.bot.require_owner(i)
        await i.response.send_modal(UpdateModal(self.bot, i))

    @discord.ui.button(label="Retomar análise")
    async def resume(self, i, button):
        self.bot.require_owner(i)
        if not tier_balance.paused(self.bot.store):
            raise ValueError("Não há uma pausa por atualização para encerrar.")
        await i.response.send_modal(ResumeModal(self.bot, i))


class UpdateModal(BoundModal):
    def __init__(self, bot, i):
        super().__init__(title="Registrar atualização do jogo", timeout=300)
        self.bind(bot, i)
        self.expected = tier_balance.revision(bot.store)
        self.name = discord.ui.TextInput(
            min_length=2, max_length=80, placeholder="Ex.: Update 21 · balanceamento"
        )
        self.date = discord.ui.TextInput(
            min_length=16, max_length=16, placeholder="22/10/2026 18:00"
        )
        self.reason = discord.ui.TextInput(
            min_length=20, max_length=500, style=discord.TextStyle.paragraph
        )
        for title, description, field in (
            (
                "Nome da atualização",
                "Informe o nome ou número confirmado dentro do jogo.",
                self.name,
            ),
            (
                "Quando entrou no jogo · horário de Brasília",
                "Formato: dia/mês/ano hora:minuto. Não use a data de uma mudança na Wiki.",
                self.date,
            ),
            (
                "O que mudou?",
                "Registro interno. Descreva o balanceamento e o que precisa ser conferido.",
                self.reason,
            ),
        ):
            self.add_item(
                discord.ui.Label(text=title, description=description, component=field)
            )

    async def on_submit(self, i):
        if not await self.interaction_check(i):
            return
        self.bot.require_owner(i)
        try:
            when = (
                datetime.strptime(str(self.date), "%d/%m/%Y %H:%M")
                .replace(tzinfo=BRT)
                .timestamp()
            )
        except ValueError:
            raise ValueError(
                "Use dia/mês/ano hora:minuto no horário de Brasília, como 22/10/2026 18:00."
            ) from None
        if not 0 < when <= self.bot.store.clock() or when < tier_balance.cutoff(
            self.bot.store
        ):
            raise ValueError(
                "A data precisa estar no passado e não pode ser anterior à atualização já registrada."
            )
        pending = len(
            self.bot.store.rows(
                "SELECT id FROM tier_proposals WHERE status IN ('open','queued')"
            )
        )
        impact = (
            "A enquete em andamento será cancelada."
            if pending == 1
            else f"As {pending} enquetes em andamento serão canceladas."
            if pending
            else "Não há enquete em andamento para cancelar."
        )
        await reply(
            i,
            f"## Confirmar atualização global\n**{safe(str(self.name), 80)}** · <t:{int(when)}:f>\n\n**{impact}**\nAo confirmar, novas propostas ficarão pausadas e relatos anteriores a essa data deixarão de sustentar análises.\n\nAs imagens e os resultados encerrados serão preservados. Depois será necessário conferir as fontes e retomar a análise nestes controles. Nada foi alterado ainda.",
            view=ConfirmUpdate(
                self.bot, i, self.expected, str(self.name), when, str(self.reason)
            ),
        )


class ConfirmUpdate(PrivateView):
    def __init__(self, bot, i, expected, name, when, reason):
        super().__init__(bot, i, owner=True)
        self.expected, self.name, self.when, self.reason = expected, name, when, reason
        self.completed = False

    @discord.ui.button(
        label="Confirmar atualização e pausar", style=discord.ButtonStyle.danger
    )
    async def confirm(self, i, button):
        self.bot.require_owner(i)
        if self.completed:
            raise ValueError(
                "Esta confirmação já foi encerrada. Reabra os controles para conferir o estado atual."
            )
        tier_balance.register(
            self.bot.store,
            expected=self.expected,
            label=self.name,
            effective_at=self.when,
            reason=self.reason,
            actor=i.user.id,
        )
        self.completed = True
        for item in self.children:
            item.disabled = True
        await edit_response(
            i,
            content="Atualização registrada. Novas propostas estão pausadas; as enquetes em andamento foram canceladas. As imagens e os votos foram preservados. Confira as fontes e reabra **Atualizações do jogo → Retomar análise** quando estiverem prontas.",
            view=self,
        )

    @discord.ui.button(label="Cancelar")
    async def cancel(self, i, button):
        self.bot.require_owner(i)
        if self.completed:
            raise ValueError(
                "Esta confirmação já foi encerrada. Reabra os controles para conferir o estado atual."
            )
        self.completed = True
        for item in self.children:
            item.disabled = True
        await edit_response(
            i,
            content="Registro cancelado. O funcionamento da tier list foi preservado.",
            view=self,
        )


class ResumeModal(BoundModal):
    def __init__(self, bot, i):
        super().__init__(title="Retomar análise da tier list", timeout=300)
        self.bind(bot, i)
        self.expected = tier_balance.revision(bot.store)
        self.source_version = bot.analyzer.evidence.version
        self.reason = discord.ui.TextInput(
            min_length=20, max_length=500, style=discord.TextStyle.paragraph
        )
        self.add_item(
            discord.ui.Label(
                text="Quais fontes e mudanças você conferiu?",
                description="Enviar confirma que as referências disponíveis correspondem à atualização do jogo.",
                component=self.reason,
            )
        )

    async def on_submit(self, i):
        if not await self.interaction_check(i):
            return
        self.bot.require_owner(i)
        if self.source_version != self.bot.analyzer.evidence.version:
            raise ValueError(
                "As fontes mudaram enquanto o formulário estava aberto. Reabra e confira antes de retomar."
            )
        tier_balance.resume(
            self.bot.store,
            expected=self.expected,
            source_version=self.source_version,
            reason=str(self.reason),
            actor=i.user.id,
        )
        await reply(
            i,
            "Análise retomada após sua conferência. Relatos anteriores à atualização continuam excluídos das análises; novas mudanças passam pelas regras normais de votação.",
        )
