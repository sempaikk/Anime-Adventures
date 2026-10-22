"""Render a normal tier list from the original character artwork, without generative art."""

from __future__ import annotations
import hashlib
import io
import json
import math
import discord
from PIL import Image, ImageDraw
from community_domain import ROOT
from community_ui import font, safe, portraits
from tier_store import TIERS

ROW_COLORS = {
    "META": "#920700",
    "S": "#218900",
    "A": "#588800",
    "B": "#008c91",
    "C": "#777900",
    "D": "#886000",
    "E": "#985000",
}


def render(ranking, *, media=None):
    media = portraits() if media is None else media
    columns, tile, label = 10, 96, 138
    groups = [(t, [r for r in ranking if r["tier"] == t]) for t in TIERS]
    width = label + columns * tile
    height = sum(max(1, math.ceil(len(rows) / columns)) * tile for _, rows in groups)
    canvas = Image.new("RGB", (width, height), "#111415")
    draw = ImageDraw.Draw(canvas)
    top = 0
    for tier, rows in groups:
        band = max(1, math.ceil(len(rows) / columns)) * tile
        draw.rectangle((0, top, label, top + band), fill=ROW_COLORS[tier])
        title = "Meta" if tier == "META" else tier
        box = draw.textbbox((0, 0), title, font=font(25))
        draw.text(
            ((label - box[2]) / 2, top + (band - 30) / 2),
            title,
            font=font(25),
            fill="#eeeeee",
        )
        draw.line((0, top, width, top), fill="#626569", width=1)
        draw.line((label, top, label, top + band), fill="#626569", width=1)
        for index, row in enumerate(rows):
            item = media.get(row["unit_id"])
            x = label + (index % columns) * tile
            y = top + (index // columns) * tile
            path = (ROOT / item["path"]).resolve() if item else None
            if path and path.is_relative_to(ROOT / "assets") and path.is_file():
                with Image.open(path) as original:
                    icon = original.convert("RGBA")
                    icon.thumbnail((88, 88), Image.Resampling.LANCZOS)
                    canvas.paste(
                        icon,
                        (x + (tile - icon.width) // 2, y + (tile - icon.height) // 2),
                        icon,
                    )
            else:
                draw.text((x + 8, y + 27), "Imagem", font=font(15), fill="#90969c")
                draw.text((x + 8, y + 47), "pendente", font=font(15), fill="#90969c")
        top += band
    draw.rectangle((0, 0, width - 1, height - 1), outline="#626569", width=1)
    output = io.BytesIO()
    canvas.save(output, format="PNG", optimize=True)
    return output.getvalue()


def panel_payload(store):
    publication = store.latest()
    blob = render(publication["ranking"])
    when = (
        f"<t:{int(publication['created_at'])}:R>"
        if publication["created_at"]
        else "Aguardando a primeira análise"
    )
    description = (
        f"**Atualizada:** {when}\nOs mais bem colocados ficam à esquerda em cada tier."
    )
    if not publication["ranking"]:
        description += "\n\nA lista começa sem posições inventadas. Os personagens entram após a análise das fontes e dos comentários."
    embed = discord.Embed(title="Tier list", description=description, color=0x960D16)
    embed.set_image(url="attachment://tierlist.png")
    embed.set_footer(text="Enquetes de 10 min · no máximo uma proposta por hora")
    file = discord.File(io.BytesIO(blob), filename="tierlist.png", description=".")
    return embed, file, hashlib.sha256(blob).hexdigest()


def log_embed(store, catalog, page=1):
    logs = store.history(page)
    embed = discord.Embed(title="Atualizações · Meta", color=0x960D16)
    if not logs:
        embed.description = "Ainda não há mudanças confirmadas no Meta."
    else:
        for row in logs:
            unit = catalog.units.get(row["unit_id"])
            detail = json.loads(row["sources"])
            links = []
            for source in detail[:2]:
                links.append(f"[Conferir na wiki]({source['url']})")
            embed.add_field(
                name=f"{unit.name if unit else row['unit_id']} · posição {row['to_position']}",
                value=f"{safe(row['reason'], 700)}\n"
                + " · ".join(links)
                + f"\n<t:{int(row['created_at'])}:R>",
                inline=False,
            )
    embed.set_footer(text=f"Página {page} · motivos detalhados dos personagens do Meta")
    return embed


POLL_STATES = {
    "open": "Votação aberta",
    "approved": "Aprovada · tier list atualizada",
    "maintained": "Encerrada · posição mantida",
    "needs-tests": "Encerrada · precisa de mais testes",
    "not-enough-votes": "Encerrada · participação insuficiente",
    "outdated": "Encerrada · fontes ou lista mudaram",
}


def poll_embed(store, catalog, proposal):
    uid = next(iter(proposal["details"]))
    detail = proposal["details"][uid]
    name = catalog.units[uid].name
    before = detail.get("before")
    question = (
        f"{name} deve passar {catalog.units[before].name}?"
        if before
        else f"{name} deve ficar no tier {detail['tier']}?"
    )
    embed = discord.Embed(
        title=question[:250], description=safe(detail["reason"], 800), color=0x960D16
    )
    for source in detail["sources"][:2]:
        embed.add_field(
            name="Referência na wiki",
            value=safe(source["quote"], 350) + f"\n[Conferir fonte]({source['url']})",
            inline=False,
        )
    counts = (
        store.poll_counts(proposal["id"])
        if proposal["status"] == "open"
        else proposal["outcome"]
    )
    embed.add_field(
        name=POLL_STATES[proposal["status"]],
        value=f"**Aprovar:** {counts.get('approve', 0)} · **Manter:** {counts.get('keep', 0)} · **Mais testes:** {counts.get('test', 0)}",
        inline=False,
    )
    if proposal["status"] == "open":
        embed.add_field(
            name="Prazo",
            value=f"Encerra <t:{int(proposal['closes_at'])}:R> · <t:{int(proposal['closes_at'])}:t>\nMínimo de 5 pessoas e dois terços a favor. Um voto por pessoa em toda a rede.",
            inline=False,
        )
    embed.set_footer(
        text="A IA propõe; a comunidade decide · uma proposta por hora · votos não treinam o modelo"
    )
    return embed
