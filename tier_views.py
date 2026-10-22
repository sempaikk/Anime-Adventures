"""Small public controls and owner-bound private review; no extra slash commands."""

from __future__ import annotations
import asyncio
import io
import logging
import discord
from PIL import Image, ImageDraw
from community_ui import portraits, font
from community_domain import ROOT
from tier_domain import safe
from tier_style import decorate_controls
from tier_ui import payload, edit, edit_response

log = logging.getLogger("tierlist.ui")

PLAYER_GUIDE = """## Como funciona a tier list
**Leia a imagem:** Meta destaca os melhores. Damage é dano; Support é controle/debuff; Buff melhora aliados; Farm gera recursos. Cada forma tem uma função principal. Os Meta aparecem também nessa função, à frente dos demais. Dentro de cada linha, a ordem é da esquerda para a direita. No celular, toque para ampliar.

**Sem avaliação não significa ruim.** Uma forma só aparece na grade depois de uma decisão aprovada. As formas ainda sem avaliação ficam fora da imagem.

**Antes de votar:** leia o motivo, as condições, a ressalva e as referências. Considere a forma exata, o custo e as situações de uso. A wiki é comunitária e pode estar desatualizada.

**Escolha:** Aprovar aceita a mudança; Manter preserva as posições; Mais testes pede evidências melhores. Sua conta tem um voto na rede inteira e pode trocar até o prazo. Contas precisam ter pelo menos sete dias para votar.

**Quando muda:** são dez minutos de votação, cinco participantes e dois terços a favor. A imagem muda depois da aprovação. Sem aprovação, continua igual. Há no máximo uma proposta por hora; sem evidência suficiente, não há proposta.

**Próxima enquete:** o tópico mostra quando uma nova análise ficará disponível e se já existe proposta pronta. O contador não garante uma votação: a análise pode concluir que as posições devem continuar iguais.

**Onde votar:** a enquete aparece no canal da imagem. Após encerrar, o resultado fica no tópico; o aviso do canal sai depois de dois minutos e somente com o histórico confirmado. Os votos ficam ocultos até o fim. Sinalizar problema pede revisão, sem acrescentar votos.

**Retratos:** quando houver fotos pendentes, o tópico terá retratos-pendentes.txt com as formas exatas. Sugerir imagem envia a contribuição para revisão do responsável. Trocar retrato não muda posições. Acompanhe em Meus envios.

**Glossário opcional:** ||DPS: dano por segundo. SPA: intervalo entre ataques. Esses valores dependem da forma e das condições de uso.||"""


async def reply(i, text=None, **kwargs):
    kwargs.setdefault("ephemeral", True)
    kwargs = payload(bot=getattr(i, "client", None), content=text, **kwargs)
    if i.response.is_done():
        return await i.followup.send(**kwargs)
    return await i.response.send_message(**kwargs)


class GuardedView(discord.ui.View):
    async def on_error(self, i, error, item):
        if isinstance(error, ValueError):
            await reply(i, str(error))
        else:
            log.warning("Interface indisponível: %s", type(error).__name__)
            await reply(i, "Não consegui concluir agora. Tente novamente em instantes.")


class BoundModal(discord.ui.Modal):
    def bind(self, bot, i):
        self.bot, self.actor, self.guild, self.channel = (
            bot,
            i.user.id,
            i.guild_id,
            i.channel_id,
        )

    async def interaction_check(self, i):
        if (i.user.id, i.guild_id, i.channel_id) != (
            self.actor,
            self.guild,
            self.channel,
        ):
            await reply(i, "Abra o formulário pelo seu próprio botão.")
            return False
        return True

    async def on_error(self, i, error):
        if isinstance(error, ValueError):
            await reply(i, str(error))
        else:
            log.warning("Formulário indisponível: %s", type(error).__name__)
            await reply(
                i, "Não consegui concluir agora. Nenhuma alteração foi aplicada."
            )


class ThreadView(GuardedView):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot
        decorate_controls(self, bot)

    @discord.ui.button(label="Sugerir imagem", custom_id="tier:v3:suggest-image")
    async def suggest(self, i, button):
        self.bot.require_thread(i, index_only=True)
        self.bot.require_human(i)
        await i.response.send_modal(ImageModal(self.bot, i))

    @discord.ui.button(label="Meus envios", custom_id="tier:v3:submissions")
    async def submissions(self, i, button):
        self.bot.require_thread(i, index_only=True)
        self.bot.require_human(i)
        view = SubmissionView(self.bot, i)
        await view.status.callback(i)

    @discord.ui.button(label="Como funciona", custom_id="tier:v3:help")
    async def help(self, i, button):
        self.bot.require_thread(i, index_only=True)
        await reply(i, PLAYER_GUIDE)


class ImageModal(BoundModal):
    def __init__(self, bot, i):
        super().__init__(title="Sugerir retrato", timeout=300)
        self.bind(bot, i)
        self.unit = discord.ui.TextInput(
            placeholder="Use o nome completo da evolução",
            max_length=150,
        )
        self.appearance = discord.ui.TextInput(required=False, max_length=150)
        self.note = discord.ui.TextInput(
            style=discord.TextStyle.paragraph,
            min_length=15,
            max_length=700,
        )
        self.portrait = discord.ui.FileUpload(min_values=1, max_values=1)
        self.proof = discord.ui.FileUpload(required=False, min_values=0, max_values=1)
        self.add_item(
            discord.ui.Label(
                text="Personagem e forma exatos",
                description="Vai para revisão no bot. Acompanhe em Meus envios; somente o responsável aprova.",
                component=self.unit,
            )
        )
        self.add_item(
            discord.ui.Label(
                text="Skin ou aparência (opcional)",
                description="Informe se é uma skin ou uma aparência diferente da forma padrão.",
                component=self.appearance,
            )
        )
        self.add_item(
            discord.ui.Label(
                text="O que esta imagem corrige?",
                description="Explique a diferença: forma incorreta, skin nova, enquadramento ou qualidade.",
                component=self.note,
            )
        )
        self.add_item(
            discord.ui.Label(
                text="Retrato PNG, JPG ou WebP · até 4 MB",
                description="Uma imagem estática do personagem exato, de preferência com fundo transparente.",
                component=self.portrait,
            )
        )
        self.add_item(
            discord.ui.Label(
                text="Print do personagem no jogo (opcional)",
                description="Ajuda o responsável a conferir a forma e a aparência. Até 4 MB.",
                component=self.proof,
            )
        )

    async def on_submit(self, i):
        if not await self.interaction_check(i):
            return
        self.bot.require_thread(i)
        self.bot.require_human(i)
        self.bot.media_available()
        try:
            unit = self.bot.catalog.resolve(str(self.unit))
        except ValueError:
            choices = self.bot.catalog.search(str(self.unit), limit=5)
            text = "Informe o nome completo, incluindo a forma."
            if choices:
                text += (
                    " Exemplos encontrados: " + ", ".join(u.name for u in choices) + "."
                )
            raise ValueError(text)
        if len(self.portrait.values) != 1 or len(self.proof.values) > 1:
            raise ValueError("Envie um retrato e, se quiser, um print de comprovação.")
        self.bot.media.check_submission(
            unit.id, i.user.id, i.guild_id, str(self.appearance), str(self.note)
        )
        await i.response.defer(ephemeral=True, thinking=True)
        if self.bot.upload_slots.locked():
            raise ValueError(
                "Outras imagens estão sendo preparadas. Tente novamente em instantes."
            )
        async with self.bot.upload_slots:
            self.bot.media.begin_upload(i.user.id, i.guild_id)
            portrait = await self.bot.read_upload(self.portrait.values[0])
            proof = (
                await self.bot.read_upload(self.proof.values[0])
                if self.proof.values
                else None
            )
            from tier_media import prepare

            portrait = await asyncio.to_thread(prepare, portrait)
            if proof:
                proof = await asyncio.to_thread(prepare, proof, proof=True)
            self.bot.require_thread(i)
            self.bot.media_available()
            ident = self.bot.media.submit(
                unit.id,
                i.user.id,
                i.guild_id,
                str(self.appearance),
                str(self.note),
                portrait,
                proof,
                _prepared=True,
            )
        await reply(
            i,
            f"Sugestão **#{ident}** recebida para **{safe(unit.name, 150)}**. Ela vai passar por revisão antes de substituir o retrato. As posições continuam iguais.",
            view=SubmissionView(self.bot, i),
        )


class SubmissionView(GuardedView):
    def __init__(self, bot, i):
        super().__init__(timeout=600)
        self.bot, self.actor, self.guild = bot, i.user.id, i.guild_id

    async def interaction_check(self, i):
        if i.user.id != self.actor or i.guild_id != self.guild:
            await reply(
                i,
                "Abra Meus envios no tópico oficial para consultar seus próprios envios.",
            )
            return False
        return True

    @discord.ui.button(label="Meus envios")
    async def status(self, i, button):
        rows = self.bot.store.rows(
            "SELECT id,unit_id,status FROM tier_media_suggestions WHERE user_id=? ORDER BY id DESC LIMIT 5",
            (str(i.user.id),),
        )
        labels = {
            "pending": "aguardando revisão",
            "approved": "aprovado",
            "rejected": "não aprovado",
            "reverted": "versão anterior restaurada",
            "expired": "prazo de revisão encerrado",
            "unavailable": "forma retirada do catálogo ativo",
        }
        text = "### Seus envios\n"
        for row in rows:
            text += f"**#{row['id']} · {safe(self.bot.catalog.display_name(row['unit_id']), 150)}:** {labels.get(row['status'], 'revisado')}.\n"
        reports = self.bot.store.rows(
            "SELECT id,status FROM tier_reports WHERE user_id=? ORDER BY id DESC LIMIT 5",
            (str(i.user.id),),
        )
        for row in reports:
            text += f"**Relato #{row['id']}:** {'aguardando revisão' if row['status'] == 'pending' else 'revisado'}.\n"
        if not rows and not reports:
            text += "Você ainda não tem sugestões ou relatos recentes."
        await reply(i, text)


class ReportModal(BoundModal):
    def __init__(self, bot, i, proposal_id):
        super().__init__(title="Sinalizar problema", timeout=300)
        self.bind(bot, i)
        self.proposal_id = proposal_id
        self.reason = discord.ui.TextInput(
            style=discord.TextStyle.paragraph,
            min_length=15,
            max_length=800,
            placeholder="Forma errada, fonte antiga, comparação incompleta…",
        )
        self.add_item(
            discord.ui.Label(
                text="Qual é o problema?",
                description="Seu relato vai para revisão privada. Enviar não altera votos nem posições.",
                component=self.reason,
            )
        )

    async def on_submit(self, i):
        if not await self.interaction_check(i):
            return
        self.bot.require_human(i)
        receipt = self.bot.store.rows(
            "SELECT 1 FROM tier_poll_messages WHERE proposal_id=? AND guild_id=? AND channel_id=? AND status!=?",
            (self.proposal_id, str(i.guild_id), str(i.channel_id), "removed"),
        )
        if not receipt:
            raise ValueError("Essa proposta não está disponível para revisão.")
        self.bot.store.report(self.proposal_id, i.user.id, i.guild_id, str(self.reason))
        await reply(
            i,
            "Problema encaminhado para revisão. Sinalizar não altera a classificação nem acrescenta votos.",
        )


class PollView(GuardedView):
    def __init__(self, bot, *, closed=False, panel=None, thread_id=None):
        super().__init__(timeout=None)
        self.bot = bot
        for item in self.children:
            if item.custom_id != "tier:v3:report":
                item.disabled = closed
        if panel:
            self.add_item(
                discord.ui.Button(
                    label="Ver tier list",
                    url=f"https://discord.com/channels/{panel['guild_id']}/{panel['channel_id']}/{panel['message_id']}",
                    row=1,
                )
            )
            if thread_id:
                self.add_item(
                    discord.ui.Button(
                        label="Histórico",
                        url=f"https://discord.com/channels/{panel['guild_id']}/{thread_id}",
                        row=1,
                    )
                )

        decorate_controls(self, bot)

    async def cast(self, i, choice):
        self.bot.require_human(i)
        receipt = self.bot.store.poll_at(i.guild_id, i.channel_id, i.message.id)
        if not receipt:
            raise ValueError("Esta mensagem não pertence à votação.")
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
        proposal = self.bot.store.proposal(receipt["proposal_id"])
        await reply(
            i,
            f"Voto registrado: **{labels[choice]}**. Encerra <t:{int(proposal['closes_at'])}:R>. Você pode trocar pelos mesmos botões até o prazo. Sua conta conta uma vez em toda a rede.",
        )

    @discord.ui.button(
        label="Aprovar",
        custom_id="tier:v3:approve",
        style=discord.ButtonStyle.success,
        row=0,
    )
    async def approve(self, i, button):
        await self.cast(i, "approve")

    @discord.ui.button(label="Manter", custom_id="tier:v3:keep", row=0)
    async def keep(self, i, button):
        await self.cast(i, "keep")

    @discord.ui.button(label="Mais testes", custom_id="tier:v3:test", row=0)
    async def tests(self, i, button):
        await self.cast(i, "test")

    @discord.ui.button(label="Sinalizar problema", custom_id="tier:v3:report", row=1)
    async def report(self, i, button):
        self.bot.require_human(i)
        receipt = self.bot.store.poll_at(i.guild_id, i.channel_id, i.message.id)
        if not receipt or receipt["status"] == "removed":
            raise ValueError("Esta proposta não está disponível.")
        await i.response.send_modal(ReportModal(self.bot, i, receipt["proposal_id"]))


class PrivateView(GuardedView):
    def __init__(self, bot, i, *, owner=False):
        super().__init__(timeout=600)
        self.bot, self.actor, self.guild, self.owner = bot, i.user.id, i.guild_id, owner

    async def interaction_check(self, i):
        if i.user.id != self.actor or i.guild_id != self.guild:
            await reply(i, "Abra seus próprios controles com /tierlist.")
            return False
        try:
            if self.owner:
                self.bot.require_owner(i)
            else:
                self.bot.require_admin(i)
        except ValueError as error:
            await reply(i, str(error))
            return False
        return True


class AdminView(PrivateView):
    def __init__(self, bot, i):
        super().__init__(bot, i, owner=bot.is_owner_id(i.user.id))
        if not bot.is_owner_id(i.user.id):
            for item in list(self.children):
                if item.custom_id in (
                    "review-images",
                    "review-reports",
                    "rollback",
                    "undo-image",
                    "connection-test",
                    "full-verification",
                    "visual-test",
                ):
                    self.remove_item(item)
            self.diagnosis.label = "Conferir painel"
        decorate_controls(self, bot)

    @discord.ui.button(label="Diagnóstico", row=0)
    async def diagnosis(self, i, button):
        await reply(
            i,
            self.bot.diagnostics(i)
            if self.bot.is_owner_id(i.user.id)
            else self.bot.server_status(i),
        )

    @discord.ui.button(label="Revisar imagens", custom_id="review-images", row=0)
    async def images(self, i, button):
        self.bot.require_owner(i)
        await i.response.defer(ephemeral=True)
        await MediaReview(self.bot, i).show(i)

    @discord.ui.button(label="Revisar relatos", custom_id="review-reports", row=0)
    async def reports(self, i, button):
        self.bot.require_owner(i)
        await i.response.defer(ephemeral=True)
        await ReportReview(self.bot, i).show(i)

    @discord.ui.button(label="Reverter classificação", custom_id="rollback", row=1)
    async def rollback(self, i, button):
        self.bot.require_owner(i)
        await i.response.send_modal(CorrectionModal(self.bot, i))

    @discord.ui.button(
        label="Restaurar retrato anterior", custom_id="undo-image", row=1
    )
    async def undo_image(self, i, button):
        self.bot.require_owner(i)
        rows = self.bot.store.rows(
            "SELECT a.unit_id,a.suggestion_id FROM tier_media_active a ORDER BY suggestion_id DESC LIMIT 1"
        )
        if not rows:
            raise ValueError("Não há uma substituição de retrato para desfazer.")
        row = rows[0]
        await reply(
            i,
            f"Restaurar o retrato anterior de **{safe(self.bot.catalog.units[row['unit_id']].name, 150)}**? As posições serão preservadas.",
            view=UndoImage(self.bot, i, row),
        )

    @discord.ui.button(label="Testar conexão da IA", custom_id="connection-test", row=2)
    async def connection(self, i, button):
        self.bot.require_owner(i)
        await i.response.defer(ephemeral=True, thinking=True)
        async with self.bot.analysis_lock:
            result = await self.bot.analyzer.check_connection()
        await reply(i, result)

    @discord.ui.button(
        label="Verificação completa", custom_id="full-verification", row=2
    )
    async def verification(self, i, button):
        self.bot.require_owner(i)
        await i.response.defer(ephemeral=True, thinking=True)
        from tier_verify import verify

        await verify(self.bot, i)

    @discord.ui.button(
        label="Testar personagens na imagem", custom_id="visual-test", row=2
    )
    async def visual(self, i, button):
        from tier_preview import open_demo

        await open_demo(self.bot, i)


class UndoImage(PrivateView):
    def __init__(self, bot, i, row):
        super().__init__(bot, i, owner=True)
        self.row = row

    @discord.ui.button(label="Confirmar restauração", style=discord.ButtonStyle.danger)
    async def confirm(self, i, button):
        self.bot.require_owner(i)
        self.bot.media.undo(self.row["unit_id"], self.row["suggestion_id"], i.user.id)
        for item in self.children:
            item.disabled = True
        await edit_response(
            i,
            content="Retrato anterior restaurado. A revisão será registrada no tópico; as posições foram preservadas.",
            view=self,
        )


class CorrectionModal(BoundModal):
    def __init__(self, bot, i, *, proposal_id=None):
        super().__init__(title="Justificar correção", timeout=300)
        self.bind(bot, i)
        self.proposal_id = proposal_id
        self.publication = bot.store.latest()["id"]
        self.reason = discord.ui.TextInput(
            style=discord.TextStyle.paragraph,
            min_length=20,
            max_length=700,
        )
        self.add_item(
            discord.ui.Label(
                text="Motivo que ficará no histórico",
                description="Este motivo será público. Enviar confirma a correção, após validar a classificação atual.",
                component=self.reason,
            )
        )

    async def on_submit(self, i):
        if not await self.interaction_check(i):
            return
        self.bot.require_owner(i)
        if self.proposal_id is None:
            self.bot.store.rollback(self.publication, i.user.id, str(self.reason))
            text = "Classificação anterior restaurada em uma nova revisão. O motivo ficará no tópico."
        else:
            self.bot.store.cancel_proposal(
                self.proposal_id, i.user.id, str(self.reason)
            )
            text = "Proposta suspensa com justificativa. As posições foram preservadas."
        await reply(i, text)


def comparison(current_path, candidate_path):
    canvas = Image.new("RGB", (900, 470), "#16191e")
    draw = ImageDraw.Draw(canvas)
    paths = [current_path, candidate_path]
    for i, (label, path) in enumerate(zip(("Atual", "Sugestão"), paths)):
        x = 20 + i * 450
        draw.text((x, 16), label, font=font(24), fill="#e9edf1")
        if path:
            try:
                with Image.open(path) as source:
                    if source.width * source.height > 4_000_000:
                        raise ValueError("oversized")
                    icon = source.convert("RGBA")
                    icon.thumbnail((390, 370), Image.Resampling.LANCZOS)
                    canvas.paste(
                        icon,
                        (x + (410 - icon.width) // 2, 70 + (370 - icon.height) // 2),
                        icon,
                    )
            except (OSError, ValueError):
                draw.text(
                    (x, 150), "Imagem indisponível", font=font(20), fill="#adb3bc"
                )
        else:
            draw.text((x, 150), "Imagem pendente", font=font(20), fill="#adb3bc")
    output = io.BytesIO()
    canvas.save(output, format="PNG")
    return output.getvalue()


class MediaReview(PrivateView):
    def __init__(self, bot, i):
        super().__init__(bot, i, owner=True)
        self.selected = None
        self.offset = 0

    async def show(self, i):
        rows = self.bot.media.pending()
        self.offset = min(self.offset, max(0, len(rows) - 1))
        self.selected = rows[self.offset]["id"] if rows else None
        if not rows:
            await edit(
                i,
                content="Nenhuma imagem aguardando revisão.",
                embeds=[],
                attachments=[],
                view=None,
            )
            return
        row = rows[self.offset]
        embed = discord.Embed(
            title=f"Imagem #{row['id']} · {self.offset + 1}/{len(rows)}",
            description=f"**{safe(self.bot.catalog.units[row['unit_id']].name, 150)}**\nSkin: {safe(row['appearance'] or 'padrão', 150)}\n\n{safe(row['note'], 700)}",
            color=0x960D16,
        )
        current = self.bot.media.approved().get(row["unit_id"]) or portraits().get(
            row["unit_id"]
        )
        current_path = (
            (current.get("absolute_path") or ROOT / current["path"])
            if current
            else None
        )
        async with self.bot.image_slots:
            blob = await asyncio.to_thread(
                comparison, current_path, self.bot.media.path(row["preview_hash"])
            )
        files = [discord.File(io.BytesIO(blob), filename="comparacao.png")]
        embed.set_image(url="attachment://comparacao.png")
        if row["proof_hash"]:
            path = self.bot.media.path(row["proof_hash"])
            if path.is_file():
                files.append(discord.File(path, filename="comprovacao.png"))
        try:
            await edit(
                i,
                content="Confira a forma e a skin antes de aprovar. O arquivo de comprovação, quando enviado, acompanha a comparação.",
                embed=embed,
                attachments=files,
                view=self,
            )
        finally:
            for file in files:
                file.close()

    @discord.ui.button(label="Anterior", row=0)
    async def previous(self, i, button):
        await i.response.defer()
        self.offset = max(0, self.offset - 1)
        await self.show(i)

    @discord.ui.button(label="Próxima", row=0)
    async def next(self, i, button):
        await i.response.defer()
        self.offset += 1
        await self.show(i)

    @discord.ui.button(
        label="Aprovar retrato", style=discord.ButtonStyle.success, row=1
    )
    async def approve(self, i, button):
        self.bot.require_owner(i)
        self.bot.media.decide(self.selected, i.user.id, approve=True)
        await i.response.defer()
        await self.show(i)

    @discord.ui.button(label="Rejeitar", style=discord.ButtonStyle.danger, row=1)
    async def reject(self, i, button):
        self.bot.require_owner(i)
        self.bot.media.decide(self.selected, i.user.id, approve=False)
        await i.response.defer()
        await self.show(i)

    @discord.ui.button(label="Alternar recorte de fundo uniforme", row=2)
    async def background(self, i, button):
        self.bot.require_owner(i)
        ident = self.selected
        await i.response.defer()
        async with self.bot.image_slots:
            from tier_media import prepare

            row = self.bot.media.suggestion(ident)
            if not row or row["status"] != "pending":
                raise ValueError("Essa sugestão já foi revisada.")
            prepared = None
            if row["preview_hash"] == row["original_hash"]:
                original = self.bot.media.path(row["original_hash"]).read_bytes()
                prepared = await asyncio.to_thread(
                    prepare, original, remove_background=True
                )
            self.bot.media.crop_background(ident, _prepared=prepared)
        await self.show(i)


class ReportReview(PrivateView):
    def __init__(self, bot, i):
        super().__init__(bot, i, owner=True)
        self.selected = None
        self.proposal = None

    async def show(self, i):
        rows = self.bot.store.rows(
            "SELECT * FROM tier_reports WHERE status='pending' ORDER BY id LIMIT 1"
        )
        if not rows:
            await edit(
                i,
                content="Nenhum relato aguardando revisão.",
                embeds=[],
                attachments=[],
                view=None,
            )
            return
        row = rows[0]
        self.selected, self.proposal = row["id"], row["proposal_id"]
        await edit(
            i,
            content=f"### Relato #{row['id']} · proposta #{row['proposal_id']}\n{safe(row['reason'], 800)}\n\nMarcar como revisado não modifica posições. Suspender exige uma justificativa pública.",
            view=self,
            embeds=[],
            attachments=[],
        )

    @discord.ui.button(label="Marcar como revisado")
    async def reviewed(self, i, button):
        self.bot.require_owner(i)
        with self.bot.store.connection:
            self.bot.store.connection.execute(
                "UPDATE tier_reports SET status='reviewed' WHERE id=?", (self.selected,)
            )
        await i.response.defer()
        await self.show(i)

    @discord.ui.button(label="Suspender proposta", style=discord.ButtonStyle.danger)
    async def suspend(self, i, button):
        self.bot.require_owner(i)
        await i.response.send_modal(
            CorrectionModal(self.bot, i, proposal_id=self.proposal)
        )
