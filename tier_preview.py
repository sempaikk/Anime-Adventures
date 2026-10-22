"""Owner-only visual scenarios; all positions and media changes are temporary."""

from __future__ import annotations

import asyncio
import hashlib
import io
import tempfile
from pathlib import Path
from types import SimpleNamespace

import discord
from tier_ui import edit, payload, message_files
from PIL import Image, ImageDraw

from community_domain import ROOT
from community_ui import font, portraits
from tier_image import PanelRenderer, image_file
from tier_media import MediaLibrary
from tier_portraits import PortraitInventory
from tier_store import TierStore
from tier_categories import make_row
from tier_views import GuardedView, reply


class VisualScenario:
    def __init__(self, catalog):
        self.catalog = SimpleNamespace(units=dict(catalog.units))
        self.media = portraits()
        preferred = ["daki", "gyutaro", "speedwagon"]
        available = [
            u
            for u in [*preferred, *sorted(self.catalog.units)]
            if u in self.catalog.units
            and u in self.media
            and (ROOT / self.media[u]["path"]).is_file()
        ]
        self.units = list(dict.fromkeys(available))[:12]
        if len(self.units) < 12:
            raise ValueError("Faltam retratos locais para a demonstração completa.")
        a, b, *others = self.units
        row = make_row
        expanded = [
            row(b, "META_HILL"),
            *[row(u, "META_HILL") for u in others],
            row(a, "GOOD_GROUND"),
        ]
        expanded += [
            row(u, tier)
            for u, tier in zip(
                others[:4], ("META_GROUND", "META_SUPPORT", "GOOD_HILL", "GOOD_SUPPORT")
            )
        ]
        # Keep one assessment per form, even in the technical preview.
        used = {r["unit_id"] for r in expanded[-4:]}
        expanded = [r for r in expanded[:-4] if r["unit_id"] not in used] + expanded[
            -4:
        ]
        # More identities exercise a wrapping row while all six labels remain visible.
        extras = [u for u in available if u not in {r["unit_id"] for r in expanded}]
        expanded += [row(u, "META_HILL") for u in list(dict.fromkeys(extras))[:4]]
        self.steps = [
            ("Grade vazia", [], 0, 0),
            ("Adicionar personagem ao Meta", [row(a, "META_HILL")], 1, 0),
            (
                "Inserir outro à esquerda",
                [row(b, "META_HILL"), row(a, "META_HILL")],
                2,
                0,
            ),
            (
                "Trocar a ordem no mesmo tier",
                [row(a, "META_HILL"), row(b, "META_HILL")],
                3,
                0,
            ),
            (
                "Mover de META Hill/Hybrid para Good Ground",
                [row(b, "META_HILL"), row(a, "GOOD_GROUND")],
                4,
                0,
            ),
            ("Expandir Meta e conferir as seis categorias", expanded, 5, 0),
            ("Substituir um retrato sem mudar posições", expanded, 5, 1),
            ("Restaurar o retrato anterior", expanded, 5, 2),
            (
                "Remover um personagem e reduzir a linha",
                [r for r in expanded if r["unit_id"] != b],
                6,
                2,
            ),
            ("Retornar à grade vazia", [], 7, 2),
        ]
        self.renderer = PanelRenderer(None)

    def render(self, index):
        title, ranking, publication, revision = self.steps[index]
        # Exercise the same approval/undo and renderer used in production,
        # with a new database and media directory for each isolated frame.
        with tempfile.TemporaryDirectory(prefix="tier-visual-") as folder:
            store = TierStore(Path(folder) / "tierlist.sqlite3")
            try:
                library = MediaLibrary(store, self.catalog)
                if revision:
                    target = self.units[1]
                    with Image.open(ROOT / self.media[target]["path"]) as source:
                        icon = source.convert("RGBA")
                        icon.thumbnail((112, 96))
                    candidate = Image.new("RGBA", (128, 128), "#111415")
                    candidate.paste(icon, ((128 - icon.width) // 2, 4), icon)
                    draw = ImageDraw.Draw(candidate)
                    draw.rectangle((0, 0, 127, 127), outline="#f1c65b", width=4)
                    draw.text((31, 105), "TESTE", font=font(16), fill="#f1c65b")
                    stream = io.BytesIO()
                    candidate.save(stream, format="PNG")
                    ident = library.submit(
                        target,
                        0,
                        0,
                        "simulação",
                        "Retrato artificial exclusivo da demonstração de testes.",
                        stream.getvalue(),
                    )
                    library.decide(ident, 0, approve=True)
                    if revision == 2:
                        library.undo(target, ident, 0)
                self.renderer.media_root = library.root
                body, _ = self.renderer.get(
                    {"id": publication, "ranking": ranking, "created_at": None},
                    library.approved(),
                    revision,
                    len(self.catalog.units),
                )
            finally:
                store.close()
        with Image.open(io.BytesIO(body)) as image:
            canvas = Image.new("RGB", (image.width, image.height + 58), "#202735")
            canvas.paste(image, (0, 58))
            draw = ImageDraw.Draw(canvas)
            draw.text(
                (14, 8),
                "SIMULAÇÃO · NÃO É A CLASSIFICAÇÃO GLOBAL",
                font=font(18),
                fill="#f1c65b",
            )
            draw.text(
                (14, 32),
                f"{index + 1}/{len(self.steps)} · {title}",
                font=font(16),
                fill="#f1f3f5",
            )
            output = io.BytesIO()
            canvas.save(output, format="PNG")
        return {
            "png": output.getvalue(),
            "body_digest": hashlib.sha256(body).hexdigest(),
            "title": title,
            "ranking": [dict(r) for r in ranking],
        }


class VisualDemoView(GuardedView):
    def __init__(self, bot, i):
        super().__init__(timeout=600)
        self.bot, self.actor, self.guild = bot, i.user.id, i.guild_id
        self.scenario = VisualScenario(bot.catalog)
        self.index = 0
        self.running = False
        self.navigation_lock = asyncio.Lock()

    async def interaction_check(self, i):
        if (
            i.user.id != self.actor
            or i.guild_id != self.guild
            or not self.bot.is_owner_id(i.user.id)
        ):
            await reply(i, "Esta demonstração é privada do responsável pelo bot.")
            return False
        if self.running:
            await reply(
                i,
                "A demonstração automática está em andamento. Aguarde o fim para navegar.",
            )
            return False
        return True

    async def show(self, i):
        async with self.bot.image_slots:
            frame = await asyncio.to_thread(self.scenario.render, self.index)
        file = image_file(frame["png"])
        self.previous.disabled = self.index == 0
        self.next.disabled = self.index == len(self.scenario.steps) - 1
        try:
            await edit(
                i,
                content=f"**Teste visual privado · {self.index + 1}/{len(self.scenario.steps)}**\n{frame['title']}. As posições são artificiais; o ranking e os retratos oficiais continuam preservados.",
                attachments=[file],
                view=self,
            )
        finally:
            file.close()

    @discord.ui.button(label="Anterior")
    async def previous(self, i, button):
        await i.response.defer()
        async with self.navigation_lock:
            self.index = max(0, self.index - 1)
            await self.show(i)

    @discord.ui.button(label="Próxima etapa")
    async def next(self, i, button):
        await i.response.defer()
        async with self.navigation_lock:
            self.index = min(len(self.scenario.steps) - 1, self.index + 1)
            await self.show(i)

    @discord.ui.button(label="Executar todas", style=discord.ButtonStyle.primary)
    async def autoplay(self, i, button):
        self.running = True
        task = asyncio.current_task()
        self.bot.verification_tasks.add(task)
        try:
            await i.response.defer()
            async with self.navigation_lock:
                for index in range(len(self.scenario.steps)):
                    self.index = index
                    await self.show(i)
                    if index < len(self.scenario.steps) - 1:
                        await asyncio.sleep(2)
        finally:
            self.running = False
            self.bot.verification_tasks.discard(task)


async def open_demo(bot, i):
    bot.require_owner(i)
    await i.response.defer(ephemeral=True, thinking=True)
    await VisualDemoView(bot, i).show(i)


async def check_visual_sequence(bot, message):
    scenario = VisualScenario(bot.catalog)
    frames = []
    for index in range(len(scenario.steps)):
        async with bot.image_slots:
            frame = await asyncio.to_thread(scenario.render, index)
        file = image_file(frame["png"])
        try:
            await message.edit(
                **payload(
                    bot=bot,
                    content=f"**SIMULAÇÃO · {index + 1}/{len(scenario.steps)}**\n{frame['title']}. Nenhuma posição global foi alterada.",
                    attachments=[file],
                )
            )
        finally:
            file.close()
        received = await message.channel.fetch_message(message.id)
        if received.id != message.id or len(message_files(received)) != 1:
            raise ValueError(
                f"A imagem da etapa {index + 1} não foi confirmada pelo Discord."
            )
        received_bytes = await message_files(received)[0].read()
        checksum = hashlib.sha256(frame["png"]).hexdigest()
        if hashlib.sha256(received_bytes).hexdigest() != checksum:
            raise ValueError(
                f"O arquivo recebido na etapa {index + 1} difere da imagem enviada."
            )
        frames.append(
            {
                "step": index + 1,
                "title": frame["title"],
                "body_digest": frame["body_digest"],
                "received_sha256": checksum,
            }
        )
    hashes = [f["body_digest"] for f in frames]
    if len(set(hashes)) < 8 or hashes[0] != hashes[-1] or hashes[5] != hashes[7]:
        raise ValueError(
            "As mudanças visuais ou a restauração não produziram as imagens esperadas."
        )
    return frames


async def check_portrait_sequence(bot, message):
    """Exercise contribution states and actual TXT add/remove on the same Discord message."""
    uid = "daki" if "daki" in bot.catalog.units else next(iter(bot.catalog.units))
    catalog = SimpleNamespace(units={uid: bot.catalog.units[uid]})
    steps = []
    with tempfile.TemporaryDirectory(prefix="tier-portraits-") as folder:
        store = TierStore(Path(folder) / "tierlist.sqlite3")
        try:
            library = MediaLibrary(store, catalog)
            # An explicitly isolated, single-form fixture does not depend on whether
            # all bundled game portraits have already been supplied in the future.
            inventory = PortraitInventory(catalog, library, bundled={})
            blob = io.BytesIO()
            Image.new("RGBA", (128, 128), "#963021").save(blob, format="PNG")

            async def check(title, expected):
                needs = inventory.get()
                if needs.count != expected:
                    raise ValueError("A lista de retratos não acompanhou a revisão.")
                file = (
                    discord.File(
                        io.BytesIO(needs.blob), filename="retratos-pendentes.txt"
                    )
                    if needs.count
                    else None
                )
                try:
                    await message.edit(
                        **payload(
                            bot=bot,
                            content=f"**SIMULAÇÃO · retratos**\n{title}. Estado temporário, sem alterar imagens ou posições oficiais.",
                            attachments=[file] if file else [],
                        )
                    )
                finally:
                    if file:
                        file.close()
                received = await message.channel.fetch_message(message.id)
                if received.id != message.id or len(message_files(received)) != bool(
                    expected
                ):
                    raise ValueError(
                        "A atualização do anexo de retratos não foi confirmada."
                    )
                if expected:
                    attachment = message_files(received)[0]
                    if (
                        attachment.filename != "retratos-pendentes.txt"
                        or hashlib.sha256(await attachment.read()).hexdigest()
                        != needs.checksum
                    ):
                        raise ValueError(
                            "A lista recebida do Discord difere da lista enviada."
                        )
                steps.append(
                    {"title": title, "pending": needs.count, "sha256": needs.checksum}
                )

            await check("Uma forma aguarda retrato", 1)
            suggestion = library.submit(
                uid,
                0,
                0,
                "simulação",
                "Imagem artificial exclusiva da verificação, sem correspondência visual com o jogo.",
                blob.getvalue(),
            )
            await check("Envio pendente não remove a solicitação", 1)
            library.decide(suggestion, 0, approve=True)
            await check("Aprovação remove o último anexo pendente", 0)
            library.undo(uid, suggestion, 0)
            await check("Restauração recoloca a solicitação", 1)
            rejected = library.submit(
                uid,
                0,
                0,
                "simulação",
                "Sugestão artificial exclusiva do teste de rejeição.",
                blob.getvalue(),
            )
            library.decide(rejected, 0, approve=False)
            await check("Rejeição mantém a solicitação", 1)
        finally:
            store.close()
    return steps
