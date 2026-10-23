"""Native Discord cards for setup and one account-wide, persistent participation choice."""

import json
import re

import discord

from tier_views import GuardedView, BoundModal, reply
from tier_ui import edit_response
from tier_domain import safe

PANEL_TEXT = """## 🌐 Chat global
Converse com pessoas de outros servidores diretamente neste canal.

**Participe uma vez e escreva normalmente.** Suas mensagens originais ficam aqui; os outros servidores recebem cópias identificadas com seu nome e avatar. Texto, imagens, vídeos e áudios podem ser compartilhados dentro dos limites disponíveis.

**Antes de começar:** abra Participar para entender o compartilhamento e confirmar. Se já participou em outro servidor desta rede, sua confirmação continua valendo.
-# Use os botões para consultar as regras, acompanhar seus envios ou denunciar uma mensagem."""

TERMS = """## 🌐 Antes de participar
**O que você escrever nos canais globais será compartilhado com todos os servidores conectados à rede deste bot — inclusive servidores que entrarem depois.** Essa rede pode crescer para muitos ou milhares de servidores. Participantes desses locais poderão ler suas mensagens e ver seu nome, avatar, anexos e indicação de origem.

**Vale para sua conta em toda a rede.** Você confirma uma vez. Ao entrar em outro servidor participante, não precisa confirmar novamente. A autorização continua salva depois de reiniciar o bot.

**Você escreve normalmente.** A mensagem original fica no servidor onde foi enviada. As cópias são publicadas por webhooks, com a identificação de aplicativo do Discord. Só os canais globais ativados pela administração compartilham mensagens; isso não autoriza compartilhar conversas de outros canais ou mensagens privadas.

**Você tem controle.** Pode interromper novos envios em Parar de participar. Editar ou apagar a original sincroniza as cópias durante a janela de 30 dias, enquanto houver acesso aos canais. Pessoas podem ter visto ou salvo conteúdo antes da remoção. Texto e anexos temporários usados no envio são limpos em até uma hora, com verificações periódicas. IDs de sincronização e denúncias ficam por até 30 dias. Sua confirmação continua salva até você interromper a participação.

Ao escolher **Confirmar e participar**, você concorda com esse compartilhamento. Seus próximos envios nos canais globais conectados serão distribuídos automaticamente."""

HELP = """## Como funciona o chat global
**Uma conversa entre servidores.** Escreva neste canal. A original permanece com você e os demais servidores recebem cópias com seu nome, avatar e origem. A identificação de aplicativo/bot nas cópias faz parte do Discord.

**Participação única.** Confirme uma vez por conta. A escolha vale em todos os servidores desta rede e sobrevive aos reinícios. Parar de participar interrompe novos compartilhamentos. Mensagens anteriores à confirmação não são importadas; se você confirmar pelo aviso de uma primeira mensagem, apenas aquela mensagem ainda disponível poderá ser compartilhada.

**Texto e respostas.** Formatação do Discord é preservada em textos comuns; mensagens longas podem ser divididas. Respostas a mensagens conhecidas pela rede incluem uma citação. Menções retransmitidas não notificam pessoas, cargos ou todos os membros.

**Anexos.** Imagens, GIFs, vídeos, áudios, PDF e TXT podem ser enviados. O limite de upload pode variar por servidor. Um destino que não comporte o arquivo recebe uma indicação, em vez de um anexo incompleto. Figurinhas PNG/APNG/GIF são compartilhadas como arquivo de imagem; outros formatos ficam identificados por nome. Emojis personalizados dependem das permissões e disponibilidade.

**Editar e apagar.** Use a mensagem original no Discord. O bot acompanha as alterações durante 30 dias; exclusões enquanto estiver desconectado são verificadas gradualmente. Em Meus envios também é possível solicitar a remoção das próprias cópias. Uma cópia removida pela moderação local não é recriada. Perda de acesso pode impedir sincronizar um destino.

**O que fica local.** Reações, votos de enquetes nativas, chamadas, transmissão de tela e indicador de digitação não formam uma interação única entre servidores. Não é possível unir canais nativamente.

**Convivência.** Respeite os participantes. Spam, repetição, arquivos não suportados e falta de recursos podem impedir um compartilhamento; a original é preservada. ADMs moderam seu servidor; o responsável pelo bot modera a rede. Denúncias e controles pessoais são privados."""


class ScopedView(GuardedView):
    def __init__(self, bot, i, *, admin=False, owner=False):
        super().__init__(timeout=600)
        self.bot, self.actor, self.guild, self.channel = (
            bot,
            i.user.id,
            i.guild_id,
            i.channel_id,
        )
        self.admin, self.owner = admin, owner

    def require(self, i):
        if (i.user.id, i.guild_id, i.channel_id) != (
            self.actor,
            self.guild,
            self.channel,
        ):
            raise ValueError("Abra seus próprios controles no chat global.")
        if self.admin:
            self.bot.require_admin(i)
        if self.owner:
            self.bot.require_owner(i)

    async def interaction_check(self, i):
        try:
            self.require(i)
        except ValueError as error:
            await reply(i, str(error))
            return False
        return True


class GlobalPanelView(GuardedView):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(
        label="Participar",
        style=discord.ButtonStyle.success,
        custom_id="global:v1:join",
        row=0,
    )
    async def join(self, i, button):
        cfg, prompt = self.bot.globalchat.public_context(i)
        self.bot.require_human(i)
        store = self.bot.globalchat.store
        if not cfg["active"]:
            raise ValueError(
                "A conexão deste servidor está pausada. Aguarde a administração ou participe em outro servidor conectado."
            )
        if store.blocked(i.user.id, i.guild_id):
            raise ValueError("Sua participação está bloqueada neste chat.")
        if store.consented(i.user.id):
            await reply(
                i,
                "**Você já participa da rede.** Escreva normalmente neste canal; sua confirmação vale em todos os servidores conectados.",
            )
            return
        await reply(i, TERMS, view=ConsentView(self.bot, i, cfg, prompt))

    @discord.ui.button(label="Meus envios", custom_id="global:v1:mine", row=0)
    async def mine(self, i, button):
        self.bot.globalchat.public_context(i)
        self.bot.require_human(i)
        view = MyMessagesView(self.bot, i)
        await reply(i, view.description(), view=view)

    @discord.ui.button(label="Como funciona", custom_id="global:v1:help", row=0)
    async def help(self, i, button):
        self.bot.globalchat.public_context(i)
        await reply(i, HELP)

    @discord.ui.button(label="Denunciar", custom_id="global:v1:report", row=1)
    async def report(self, i, button):
        self.bot.globalchat.public_context(i)
        self.bot.require_human(i)
        await i.response.send_modal(MessageAction(self.bot, i, "report"))

    @discord.ui.button(label="Parar de participar", custom_id="global:v1:leave", row=1)
    async def leave(self, i, button):
        self.bot.globalchat.public_context(i)
        self.bot.require_human(i)
        self.bot.globalchat.store.consent(i.user.id, False)
        await reply(
            i,
            "**Novos envios interrompidos em toda a rede.** Suas próximas mensagens ficam apenas no servidor onde você escrever. As cópias já publicadas continuam disponíveis; use a original ou Meus envios para solicitar remoção. Para voltar, abra Participar.",
        )


class JoinPromptView(GlobalPanelView):
    def __init__(self, bot):
        super().__init__(bot)
        for item in list(self.children):
            if item.custom_id != "global:v1:join":
                self.remove_item(item)


class ConsentView(ScopedView):
    def __init__(self, bot, i, cfg, prompt=None):
        super().__init__(bot, i)
        self.generation = cfg["generation"]
        self.source = prompt["source_id"] if prompt else None
        self.completed = False

    @discord.ui.button(
        label="Confirmar e participar", style=discord.ButtonStyle.success
    )
    async def accept(self, i, button):
        self.require(i)
        self.bot.require_human(i)
        cfg = self.bot.globalchat.store.source(i.channel_id)
        if not cfg or cfg["generation"] != self.generation:
            raise ValueError("A conexão do canal mudou. Abra Participar novamente.")
        if self.bot.globalchat.store.blocked(i.user.id, i.guild_id):
            raise ValueError("Sua participação está bloqueada neste chat.")
        if self.completed:
            return
        self.completed = True
        self.bot.globalchat.store.consent(i.user.id)
        await edit_response(
            i,
            content="## Participação confirmada\n**Sua escolha foi salva para toda a rede.** Você já pode escrever nos canais globais conectados. Não vamos pedir novamente em outro servidor ou após reiniciar o bot.\n\nPara interromper próximos envios, use Parar de participar.",
            view=None,
        )
        if self.source:
            try:
                original = await i.channel.fetch_message(int(self.source))
                if original.author.id == i.user.id:
                    await self.bot.globalchat.ingest(original, confirmed_first=True)
            except discord.HTTPException:
                pass
        self.stop()

    @discord.ui.button(label="Agora não")
    async def cancel(self, i, button):
        self.require(i)
        if self.completed:
            return
        self.completed = True
        await edit_response(
            i,
            content="Participação não ativada. Suas mensagens continuam apenas no servidor onde foram escritas.",
            view=None,
        )
        self.stop()


class GlobalAdminView(ScopedView):
    def __init__(self, bot, i):
        super().__init__(bot, i, admin=True)
        cfg = bot.globalchat.store.channel(i.guild_id)
        self.generation = cfg["generation"] if cfg else 0
        self.activate.label = (
            "Ativar neste canal"
            if not cfg or cfg["channel_id"] != str(i.channel_id)
            else "Conferir conexão"
        )
        if not bot.is_owner_id(i.user.id):
            self.remove_item(self.network)
            self.remove_item(self.network_reports)

    def current(self, i):
        self.require(i)
        cfg = self.bot.globalchat.store.channel(i.guild_id)
        if (cfg["generation"] if cfg else 0) != self.generation:
            raise ValueError("As configurações mudaram. Abra /chatglobal novamente.")
        return cfg

    def description(self):
        cfg = self.bot.globalchat.store.channel(self.guild)
        state = (
            "Ainda não conectado."
            if not cfg
            else ("**Conectado:** " if cfg["active"] else "**Pausado:** ")
            + f"<#{cfg['channel_id']}>."
        )
        text = (
            "## 🌐 Chat global · administração\n"
            + state
            + "\n\n**Um canal por servidor.** Ative neste canal para conectar as próximas conversas à rede. Mensagens originais são mantidas; só participantes que confirmarem entram no compartilhamento.\n\nO bot precisa de **Ver canal, Enviar mensagens, Ler histórico, Anexar arquivos e Gerenciar webhooks**. Use um canal diferente da tier list e sem restrição de idade.\n\nADMs cuidam deste servidor. Bloqueios e remoções da rede inteira são exclusivos do responsável pelo aplicativo."
        )
        if self.bot.is_owner_id(self.actor):
            from global_media import CACHE_LIMIT

            usage = self.bot.globalchat.media.usage()
            queued = self.bot.globalchat.store.one(
                "SELECT COUNT(*) AS n FROM global_deliveries WHERE state IN ('queued','preparing','uncertain','sending')"
            )["n"]
            text += f"\n\n**Somente para você:** cache temporário {usage / 1024 / 1024:.1f}/{CACHE_LIMIT // 1024 // 1024} MiB · banco {self.bot.store.path.stat().st_size / 1024 / 1024:.1f} MiB · {queued} entregas pendentes."
        return text

    @discord.ui.button(
        label="Ativar neste canal", style=discord.ButtonStyle.success, row=0
    )
    async def activate(self, i, button):
        cfg = self.current(i)
        if cfg and cfg["channel_id"] != str(i.channel_id):
            await reply(
                i,
                f"**Trocar o canal global?**\nAtual: <#{cfg['channel_id']}> → novo: <#{i.channel_id}>.\nAs próximas mensagens serão compartilhadas pelo novo canal. O histórico anterior permanece onde foi publicado.",
                view=MoveConfirm(self.bot, i, self.generation),
            )
            return
        await i.response.defer(ephemeral=True, thinking=True)
        async with self.bot.guild_lock(i.guild_id):
            self.current(i)
            await self.bot.globalchat.activate(i.channel)
        fresh = GlobalAdminView(self.bot, i)
        await reply(
            i,
            "**Conexão preparada.** O painel de participação está no canal.\n\n"
            + fresh.description(),
            view=fresh,
        )

    @discord.ui.button(label="Pausar / retomar", row=0)
    async def toggle(self, i, button):
        cfg = self.current(i)
        if not cfg:
            raise ValueError("Ative um canal primeiro.")
        await i.response.defer(ephemeral=True)
        if cfg["active"]:
            self.bot.globalchat.store.active(i.guild_id, False)
            await self.bot.globalchat.sync_panel(
                self.bot.globalchat.store.channel(i.guild_id), force=True
            )
            await reply(
                i,
                "**Conexão pausada neste servidor.** Novas mensagens não entram nem saem da rede. O histórico permanece disponível. Use /chatglobal para retomar.",
            )
        else:
            channel = self.bot.globalchat.channel(cfg["channel_id"])
            await self.bot.globalchat.activate(channel)
            await reply(
                i,
                "**Conexão retomada.** Só mensagens novas serão compartilhadas; a conversa ocorrida durante a pausa não é importada.",
            )

    @discord.ui.button(label="Bloqueios locais", row=1)
    async def blocks(self, i, button):
        self.current(i)
        await i.response.send_modal(ModerationModal(self.bot, i, network=False))

    @discord.ui.button(label="Denúncias deste servidor", row=1)
    async def reports(self, i, button):
        self.current(i)
        rows = self.bot.globalchat.store.rows(
            "SELECT * FROM global_reports WHERE guild_id=? AND reviewed=0 ORDER BY id DESC LIMIT 5",
            (str(i.guild_id),),
        )
        text = "## Denúncias deste servidor\n"
        for row in rows:
            text += f"\n**#{row['id']} · mensagem {row['source_id']}**\n{safe(row['reason'], 500)}\n"
        await reply(i, text if rows else text + "Nenhuma denúncia pendente.")

    @discord.ui.button(label="Moderação da rede", row=2)
    async def network(self, i, button):
        self.current(i)
        self.bot.require_owner(i)
        await i.response.send_modal(ModerationModal(self.bot, i, network=True))

    @discord.ui.button(label="Denúncias da rede", row=2)
    async def network_reports(self, i, button):
        self.current(i)
        self.bot.require_owner(i)
        rows = self.bot.globalchat.store.rows(
            "SELECT * FROM global_reports ORDER BY id DESC LIMIT 5"
        )
        text = "## Denúncias da rede\n"
        for row in rows:
            text += f"\n**#{row['id']} · mensagem {row['source_id']} · servidor {row['guild_id']}**\n{safe(row['reason'], 500)}\n"
        await reply(i, text if rows else text + "Nenhuma denúncia recente.")


class MoveConfirm(ScopedView):
    def __init__(self, bot, i, generation):
        super().__init__(bot, i, admin=True)
        self.generation = generation
        self.done = False

    @discord.ui.button(label="Confirmar troca", style=discord.ButtonStyle.success)
    async def confirm(self, i, button):
        self.require(i)
        cfg = self.bot.globalchat.store.channel(i.guild_id)
        if not cfg or cfg["generation"] != self.generation:
            raise ValueError("O canal mudou. Abra /chatglobal novamente.")
        if self.done:
            return
        self.done = True
        await i.response.defer(ephemeral=True)
        async with self.bot.guild_lock(i.guild_id):
            current = self.bot.globalchat.store.channel(i.guild_id)
            if not current or current["generation"] != self.generation:
                raise ValueError("O canal mudou. Abra /chatglobal novamente.")
            await self.bot.globalchat.activate(i.channel)
        await reply(
            i,
            "**Canal global alterado.** O novo painel de participação já está disponível.",
        )
        self.stop()


class MyMessagesView(ScopedView):
    def description(self):
        rows = self.bot.globalchat.store.rows(
            "SELECT * FROM global_messages WHERE user_id=? AND deleted=0 AND expires>? ORDER BY created DESC LIMIT 5",
            (str(self.actor), self.bot.globalchat.store.clock()),
        )
        text = "## Meus envios\nEdite ou apague a mensagem original pelo Discord. Para solicitar somente a remoção das cópias da rede, use Remover cópias.\n"
        for row in rows:
            data = json.loads(row["payload"])
            counts = self.bot.globalchat.store.rows(
                "SELECT state,COUNT(*) AS n FROM global_deliveries WHERE source_id=? GROUP BY state",
                (row["id"],),
            )
            states = {x["state"]: x["n"] for x in counts}
            status = f"Compartilhada em {states.get('sent', 0) + states.get('partial', 0)} destino(s)."
            if states.get("partial"):
                status += " Alguns anexos ultrapassaram o limite do destino."
            if any(
                states.get(k) for k in ("queued", "preparing", "uncertain", "sending")
            ):
                status += " Há entregas pendentes."
            if states.get("failed") or row["error"]:
                status += " Alguns envios não puderam ser confirmados."
            text += f"\n**[Mensagem {row['id']}](https://discord.com/channels/{row['guild_id']}/{row['channel_id']}/{row['id']})**\n{safe(data.get('body') or 'Anexo ou conteúdo já removido do cache.', 100)}\n{status}\n"
        return (
            text
            if rows
            else text + "\nNenhuma mensagem recente compartilhada pela sua conta."
        )

    @discord.ui.button(label="Remover cópias", style=discord.ButtonStyle.danger)
    async def erase(self, i, button):
        self.require(i)
        await i.response.send_modal(MessageAction(self.bot, i, "erase"))


class MessageAction(BoundModal):
    def __init__(self, bot, i, action):
        super().__init__(
            title="Denunciar mensagem"
            if action == "report"
            else "Remover minhas cópias"
        )
        self.bind(bot, i)
        self.action = action
        self.link = discord.ui.TextInput(
            placeholder="Cole o link ou o ID da mensagem", max_length=250
        )
        self.add_item(
            discord.ui.Label(text="Mensagem do chat global", component=self.link)
        )
        self.reason = None
        if action == "report":
            self.reason = discord.ui.TextInput(
                style=discord.TextStyle.paragraph, min_length=10, max_length=500
            )
            self.add_item(
                discord.ui.Label(text="O que aconteceu?", component=self.reason)
            )

    async def on_submit(self, i):
        if not await self.interaction_check(i):
            return
        self.bot.require_human(i)
        row = find_message(self.bot, i, str(self.link), own=self.action == "erase")
        if self.action == "report":
            self.bot.globalchat.store.report(
                row["id"], i.user.id, i.guild_id, str(self.reason)
            )
            await reply(
                i,
                "**Denúncia registrada.** A administração deste servidor e o responsável pela rede podem revisar. Sua denúncia não é publicada no chat.",
            )
        else:
            if row["user_id"] != str(i.user.id):
                raise ValueError(
                    "Você só pode remover as cópias das próprias mensagens."
                )
            self.bot.globalchat.store.erase(row["id"])
            await reply(
                i,
                "**Remoção solicitada.** As cópias acessíveis serão apagadas. A original continua sob seu controle no Discord.",
            )


def find_message(bot, i, value, *, own=False, network=False):
    store = bot.globalchat.store
    value = value.strip()
    match = re.fullmatch(
        r"https://(?:canary\.|ptb\.)?discord(?:app)?\.com/channels/(\d+)/(\d+)/(\d+)",
        value,
    )
    if match:
        guild, channel, ident = match.groups()
        if (
            not own
            and not network
            and (guild, channel) != (str(i.guild_id), str(i.channel_id))
        ):
            raise ValueError("Use o link de uma mensagem deste chat global.")
        row = store.resolve(guild, channel, ident)
    elif value.isdecimal():
        row = store.resolve(i.guild_id, i.channel_id, value)
        if not row and (own or network):
            row = store.message(value)
            if not row:
                receipt = store.one(
                    "SELECT source_id FROM global_receipts WHERE message_id=?", (value,)
                )
                row = store.message(receipt["source_id"]) if receipt else None
    else:
        raise ValueError("Cole o link da mensagem do Discord ou somente seu ID.")
    if not row:
        raise ValueError(
            "A mensagem não foi encontrada na janela de sincronização de 30 dias."
        )
    return row


class ModerationModal(BoundModal):
    def __init__(self, bot, i, *, network):
        super().__init__(
            title="Moderação da rede" if network else "Moderação deste servidor"
        )
        self.bind(bot, i)
        self.network = network
        options = [
            discord.SelectOption(label="Bloquear pessoa", value="block-user"),
            discord.SelectOption(label="Desbloquear pessoa", value="unblock-user"),
        ]
        if network:
            options.extend(
                [
                    discord.SelectOption(
                        label="Bloquear servidor", value="block-guild"
                    ),
                    discord.SelectOption(
                        label="Desbloquear servidor", value="unblock-guild"
                    ),
                    discord.SelectOption(
                        label="Remover cópias de uma mensagem", value="erase"
                    ),
                ]
            )
        self.action = discord.ui.Select(options=options)
        self.target = discord.ui.TextInput(
            max_length=250, placeholder="ID da pessoa/servidor ou link da mensagem"
        )
        self.reason = discord.ui.TextInput(
            style=discord.TextStyle.paragraph, min_length=5, max_length=500
        )
        self.add_item(discord.ui.Label(text="Ação", component=self.action))
        self.add_item(discord.ui.Label(text="Alvo", component=self.target))
        self.add_item(discord.ui.Label(text="Motivo", component=self.reason))

    async def on_submit(self, i):
        if not await self.interaction_check(i):
            return
        self.bot.require_admin(i)
        if self.network:
            self.bot.require_owner(i)
        reason = str(self.reason).strip()
        if not 5 <= len(reason) <= 500:
            raise ValueError("Explique o motivo em 5 a 500 caracteres.")
        value = self.action.values[0]
        if value == "erase":
            if not self.network:
                raise ValueError("Esta ação é exclusiva da moderação da rede.")
            row = find_message(self.bot, i, str(self.target), network=True)
            self.bot.globalchat.store.erase(row["id"])
            with self.bot.store.connection:
                self.bot.store.audit("global-removal", i.user.id, str(self.reason))
        else:
            enabled, kind = value.split("-", 1)
            if kind == "guild" and not self.network:
                raise ValueError("ADMs só podem bloquear pessoas no próprio servidor.")
            target = str(self.target).strip()
            if target.startswith("https://"):
                row = find_message(self.bot, i, target, network=self.network)
                target = row["user_id"] if kind == "user" else row["guild_id"]
            self.bot.globalchat.store.block(
                "*" if self.network else i.guild_id,
                kind,
                target,
                i.user.id,
                str(self.reason),
                enabled=enabled == "block",
            )
        await reply(
            i,
            "**Moderação aplicada.** "
            + (
                "A ação vale para toda a rede."
                if self.network
                else "A ação vale somente para este servidor."
            ),
        )
