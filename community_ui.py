"""Discord text hierarchy and a bounded PNG grid made from original wiki portraits."""

from __future__ import annotations

import hashlib
import io
import json
import math
import unicodedata
from pathlib import Path

import discord
from PIL import Image, ImageDraw, ImageFont

from community_domain import MODES, ROLES, ROOT, TIERS

COLORS = {
    "S": "#e75c70",
    "A": "#ef9d60",
    "B": "#e5ca6a",
    "C": "#80bf86",
    "D": "#77a8db",
    None: "#8b91a1",
}
PAGE_SIZE = 24


def safe(text, limit=1000):
    text = "".join(
        c
        for c in str(text)[:2000]
        if unicodedata.category(c) not in ("Cc", "Cf") or c == "\n"
    )
    text = discord.utils.escape_mentions(discord.utils.escape_markdown(text))
    return text.encode("utf-16-le")[: limit * 2].decode("utf-16-le", errors="ignore")


def font(size):
    for name in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ):
        if Path(name).exists():
            return ImageFont.truetype(name, size)
    return ImageFont.load_default(size=size)


def portraits():
    path = ROOT / "data/community_portraits.json"
    return json.loads(path.read_text())["assets"] if path.exists() else {}


def ranked_rows(store, catalog, role, mode, scope):
    ranked = store.tier_rows(role, mode, scope=scope)
    present = {r["unit_id"] for r in ranked}
    ranked.extend(
        {"unit_id": u.id, "tier": None, "basis": "community", "metrics": {}}
        for u in sorted(catalog.units.values(), key=lambda u: u.name)
        if u.id not in present
    )
    # Classified units precede all pending units. A tie uses the exact form's ID.
    return sorted(
        ranked,
        key=lambda r: (
            -(TIERS.index(r["tier"]) if r["tier"] else -1),
            -(r["metrics"].get("rating") or 0),
            r["unit_id"],
        ),
    )


def render_grid(rows, *, title, subtitle, page=1, media=None):
    media = portraits() if media is None else media
    pages = max(1, math.ceil(len(rows) / PAGE_SIZE))
    page = max(1, min(page, pages))
    selected = rows[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]
    bands = [
        (tier, [r for r in selected if r["tier"] == tier]) for tier in reversed(TIERS)
    ]
    bands.append((None, [r for r in selected if r["tier"] is None]))
    columns, tile, label = 6, 112, 130
    width = label + columns * tile + 24
    height = (
        142
        + sum(
            (math.ceil(len(items) / columns) * tile if items else 56) + 12
            for _, items in bands
        )
        + 38
    )
    canvas = Image.new("RGB", (width, height), "#11131e")
    draw = ImageDraw.Draw(canvas)
    draw.text((24, 18), title, fill="white", font=font(27))
    draw.text((24, 58), subtitle, fill="#b6bed3", font=font(17))
    draw.text(
        (24, 91),
        f"Página {page}/{pages} · ordem por avaliação · empates mantêm ordem estável",
        fill="#9ca6bf",
        font=font(15),
    )
    y = 130
    for tier, items in bands:
        band_height = math.ceil(len(items) / columns) * tile if items else 56
        draw.rounded_rectangle(
            (12, y, width - 12, y + band_height), radius=8, fill="#1b1f2e"
        )
        draw.rounded_rectangle(
            (12, y, label - 4, y + band_height), radius=8, fill=COLORS[tier]
        )
        if tier:
            draw.text(
                (48, y + band_height // 2 - 25), tier, fill="#11131e", font=font(42)
            )
        else:
            draw.text(
                (22, y + band_height // 2 - 20), "Em", fill="#11131e", font=font(17)
            )
            draw.text(
                (22, y + band_height // 2 + 2),
                "avaliação",
                fill="#11131e",
                font=font(17),
            )
        if not items:
            draw.text(
                (label + 18, y + 18),
                "Sem unidades nesta página",
                fill="#737e98",
                font=font(16),
            )
        for i, row in enumerate(items):
            x = label + (i % columns) * tile + 4
            top = y + (i // columns) * tile + 4
            item = media.get(row["unit_id"])
            path = (ROOT / item["path"]).resolve() if item else None
            if path and path.is_relative_to(ROOT / "assets") and path.is_file():
                with Image.open(path) as portrait:
                    portrait = portrait.convert("RGBA")
                    portrait.thumbnail((96, 96), Image.Resampling.LANCZOS)
                    canvas.paste(
                        portrait,
                        (
                            x + (96 - portrait.width) // 2,
                            top + (96 - portrait.height) // 2,
                        ),
                        portrait,
                    )
            else:
                # Explicit absence, never a different form or generated character substitute.
                draw.text((x + 4, top + 29), "Imagem", fill="#8b95ad", font=font(15))
                draw.text((x + 4, top + 49), "pendente", fill="#8b95ad", font=font(15))
        y += band_height + 12
    draw.text(
        (24, height - 32),
        "Opinião da comunidade · não é uma classificação oficial do jogo",
        fill="#9ca6bf",
        font=font(15),
    )
    output = io.BytesIO()
    canvas.save(output, format="PNG", optimize=True)
    return output.getvalue(), page, pages


def tier_payload(
    store, catalog, role, mode, scope, *, page=1, published_at=None, interval_minutes=30
):
    rows = ranked_rows(store, catalog, role, mode, scope)
    label = "Global" if scope == "global" else "Do servidor"
    subtitle = f"{ROLES[role]} · {MODES[mode]} · {store.get('period_label')}"
    blob, page, pages = render_grid(
        rows, title=f"Tier list · {label}", subtitle=subtitle, page=page
    )
    count = sum(r["tier"] is not None for r in rows)
    embed = discord.Embed(
        title=f"Tier list · {label}",
        description=f"**{ROLES[role]} · {MODES[mode]}**\n{safe(store.get('period_label'), 70)}\n\n"
        f"**{count}** unidades classificadas · **{len(rows) - count}** em avaliação\n"
        "Cada forma tem sua própria avaliação. Use `/tierlist` para navegar e `/avaliar` para participar.",
        color=0x9265E8,
    )
    if published_at:
        embed.add_field(
            name="Imagem atualizada",
            value=f"<t:{int(published_at)}:R> · revisão a cada {interval_minutes} min",
            inline=False,
        )
    embed.set_image(url="attachment://tierlist.png")
    embed.set_footer(
        text=f"Página {page}/{pages} · S → D · mais à esquerda = maior nota no mesmo tier"
    )
    return (
        embed,
        discord.File(io.BytesIO(blob), filename="tierlist.png", description="."),
        hashlib.sha256(blob).hexdigest(),
    )


def unit_embed(store, catalog, unit, role, mode, scope):
    reviews = store.reviews(unit.id, role, mode, scope=scope)
    state = next(
        (
            r
            for r in store.tier_rows(role, mode, scope=scope)
            if r["unit_id"] == unit.id
        ),
        None,
    )
    tier = state["tier"] if state else None
    metrics = state["metrics"] if state else {}
    embed = discord.Embed(
        title=unit.name,
        description=f"**{ROLES[role]} · {MODES[mode]}**\n"
        f"Classificação: **{tier or 'Em avaliação'}**\nBase: **{'Curadoria' if state and state['basis'] == 'editorial' else 'Comunidade'}**\n"
        f"Confiança: **{metrics.get('confidence', 'Em avaliação')}**\n"
        f"Participação: **{len(reviews)}** pessoas · **{len({r['guild_id'] for r in reviews})}** servidores",
        color=0x9265E8,
    )
    for r in reviews[:2]:
        text = safe(r["reason"], 650)
        if r["conditions"]:
            text += "\n**Condições:** " + safe(r["conditions"], 250)
        if r["evidence"]:
            text += "\n**Referência informada:** " + safe(r["evidence"], 300)
        text = text.encode("utf-16-le")[: 1000 * 2].decode("utf-16-le", errors="ignore")
        embed.add_field(
            name=f"Relato de jogador · tier {TIERS[r['score']]}",
            value=text,
            inline=False,
        )
    embed.add_field(
        name="Como entra na lista",
        value="Servidor: 5 pessoas e concordância mínima. Global: 3 servidores com pelo menos 3 pessoas cada. Relatos dos últimos 30 dias; mudanças de tier passam por estabilidade.",
        inline=False,
    )
    mentions = store.mentions(
        unit.id, guild_id=scope.removeprefix("guild:") if scope != "global" else None
    )
    embed.add_field(
        name="Em debate",
        value=f"{mentions} menções contabilizadas nos últimos 7 dias, com limite por participante. Não afeta a nota.",
        inline=False,
    )
    embed.set_footer(text="Menções no chat medem interesse e não mudam a nota.")
    return embed


def changes_embed(store, catalog, scope):
    embed = discord.Embed(
        title="Atualizações da tier list",
        description="Mudanças nas avaliações da comunidade neste período.",
        color=0x9265E8,
    )
    changes = store.changes(scope=scope)
    for row in changes:
        unit = catalog.units.get(row["unit_id"])
        embed.add_field(
            name=f"{unit.name if unit else row['unit_id']} · {row['old_tier'] or 'Em avaliação'} → {row['new_tier'] or 'Em avaliação'}",
            value=f"**{ROLES[row['role']]} · {MODES[row['mode']]}** · <t:{int(row['created_at'])}:R>\n{safe(row['reason'], 400)}",
            inline=False,
        )
    if not changes:
        embed.add_field(
            name="Ainda sem mudanças",
            value="As primeiras classificações aparecem quando houver participação suficiente.",
        )
    return embed


def relay_embed(row):
    embed = discord.Embed(description=safe(row["body"]), color=0x9265E8)
    embed.set_author(name=f"{row['author_name']} · {row['guild_name']}"[:250])
    embed.set_footer(text=f"Chat global · enviado pelo bot · código {row['id']}")
    return embed
