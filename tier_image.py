"""Deterministic tier art, original portraits and compact native Discord messages."""

from __future__ import annotations
import hashlib
import io
import json
import math
from pathlib import Path
import discord
from PIL import Image, ImageDraw, UnidentifiedImageError
from community_domain import ROOT
from community_ui import font, portraits
from tier_domain import safe, moment, place
from tier_store import TIERS
from tier_categories import COLORS, LABELS, MODES, rows_for, label
from tier_schedule import poll_progress, progress_text

ROW_COLORS = COLORS
POLL_STATES = {
    "queued": "Preparando votação",
    "open": "Votação aberta",
    "approved": "Aprovada · classificação publicada",
    "maintained": "Encerrada · posição mantida",
    "needs-tests": "Encerrada · precisa de mais testes",
    "not-enough-votes": "Encerrada · participação insuficiente",
    "outdated": "Cancelada · a referência mudou",
    "unavailable": "Cancelada · publicação indisponível",
    "suspended": "Suspensa pelo responsável · posição preservada",
    "game-updated": "Cancelada · atualização do jogo",
}


def render(
    ranking,
    *,
    media=None,
    media_root=None,
    updated_at=None,
    media_revision=0,
    total_units=None,
    footer=False,
    row_heights=None,
):
    media = portraits() if media is None else media
    columns, tile, label = 10, 96, 138
    groups = [(t, rows_for(ranking, t)) for t in TIERS]
    width = label + columns * tile
    bands = {
        t: max(
            max(1, math.ceil(len(rows) / columns)) * tile, (row_heights or {}).get(t, 0)
        )
        for t, rows in groups
    }
    height = sum(bands.values())
    canvas = Image.new("RGB", (width, height + (60 if footer else 0)), "#111415")
    draw = ImageDraw.Draw(canvas)
    top = 0
    allowed = [(ROOT / "assets").resolve()]
    if media_root:
        allowed.append(Path(media_root).resolve())
    for tier, rows in groups:
        band = bands[tier]
        draw.rectangle((0, top, label, top + band), fill=ROW_COLORS[tier])
        title = LABELS[tier]
        face = font(22)
        box = draw.multiline_textbbox(
            (0, 0), title, font=face, spacing=4, align="center"
        )
        draw.multiline_text(
            (
                (label - (box[2] - box[0])) / 2 - box[0],
                top + (band - (box[3] - box[1])) / 2 - box[1],
            ),
            title,
            font=face,
            fill="#eeeeee",
            spacing=4,
            align="center",
        )
        draw.line((0, top, width, top), fill="#626569", width=1)
        draw.line((label, top, label, top + band), fill="#626569", width=1)
        for index, row in enumerate(rows):
            item = media.get(row["unit_id"])
            x = label + (index % columns) * tile
            y = top + (index // columns) * tile
            path = (
                Path(item.get("absolute_path") or ROOT / item["path"]).resolve()
                if item
                else None
            )
            drawn = False
            if path and any(path.is_relative_to(p) for p in allowed) and path.is_file():
                try:
                    with Image.open(path) as original:
                        if original.width * original.height > 4_000_000:
                            raise ValueError("oversized portrait")
                        icon = original.convert("RGBA")
                        icon.thumbnail((88, 88), Image.Resampling.LANCZOS)
                        canvas.paste(
                            icon,
                            (
                                x + (tile - icon.width) // 2,
                                y + (tile - icon.height) // 2,
                            ),
                            icon,
                        )
                        drawn = True
                except (UnidentifiedImageError, OSError, ValueError):
                    pass
            if not drawn:
                draw.text((x + 8, y + 27), "Imagem", font=font(15), fill="#b7bdc3")
                draw.text((x + 8, y + 47), "pendente", font=font(15), fill="#b7bdc3")
        top += band
    if footer:
        draw.line((0, height, width, height), fill="#626569")
        draw.text(
            (16, height + 8),
            "Classificação: " + moment(updated_at),
            font=font(16),
            fill="#d4d8dd",
        )
        count = f"{len(ranking)} classificados"
        if total_units is not None:
            count += f" · {max(0, total_units - len(ranking))} sem avaliação"
        count += f" · Retratos: revisão {media_revision}"
        draw.text((16, height + 32), count, font=font(15), fill="#aab1b8")
    draw.rectangle((0, 0, width - 1, canvas.height - 1), outline="#626569", width=1)
    output = io.BytesIO()
    canvas.save(output, format="PNG", optimize=True)
    return output.getvalue()


def render_modes(publications, **kwargs):
    """One persistent PNG with independently ranked, clearly labelled game modes."""
    frames = []
    row_heights = {
        tier: max(
            max(1, math.ceil(len(rows_for(publications[mode]["ranking"], tier)) / 10))
            * 96
            for mode in MODES
        )
        for tier in TIERS
    }
    for mode in ("casual", "infinite"):
        title = MODES[mode]
        blob = render(publications[mode]["ranking"], row_heights=row_heights, **kwargs)
        with Image.open(io.BytesIO(blob)) as image:
            frame = Image.new("RGB", (image.width, image.height + 54), "#202735")
            frame.paste(image, (0, 54))
        ImageDraw.Draw(frame).text((16, 14), title, font=font(23), fill="#f1f3f5")
        frames.append(frame)
    canvas = Image.new(
        "RGB",
        (sum(f.width for f in frames) + 16, max(f.height for f in frames)),
        "#111415",
    )
    left = 0
    for frame in frames:
        canvas.paste(frame, (left, 0))
        left += frame.width + 16
        frame.close()
    output = io.BytesIO()
    canvas.save(output, format="PNG", optimize=True)
    canvas.close()
    return output.getvalue()


class PanelRenderer:
    def __init__(self, media_root):
        self.media_root = media_root
        self.key = None
        self.blob = None

    def get(self, publication, overrides, media_revision, total_units):
        media = dict(portraits())
        media.update(overrides)
        files = []
        roots = [(ROOT / "assets").resolve()]
        if self.media_root:
            roots.append(Path(self.media_root).resolve())
        all_rows = (
            [r for p in publication["modes"].values() for r in p["ranking"]]
            if "modes" in publication
            else publication["ranking"]
        )
        for row in all_rows:
            item = media.get(row["unit_id"])
            stamp = None
            if item:
                path = Path(item.get("absolute_path") or ROOT / item["path"]).resolve()
                if any(path.is_relative_to(root) for root in roots):
                    try:
                        stat = path.stat()
                        stamp = (
                            stat.st_ino,
                            stat.st_size,
                            stat.st_mtime_ns,
                            stat.st_ctime_ns,
                        )
                    except OSError:
                        pass
            files.append((row["unit_id"], stamp))
        key = (
            publication["id"],
            media_revision,
            total_units,
            tuple(files),
            tuple(
                sorted(
                    (
                        uid,
                        item.get("suggestion_id"),
                        item.get("absolute_path") or item.get("path"),
                    )
                    for uid, item in overrides.items()
                )
            ),
        )
        if key != self.key:
            renderer = render_modes if "modes" in publication else render
            blob = renderer(
                publication.get("modes", publication["ranking"]),
                media=media,
                media_root=self.media_root,
                updated_at=publication.get("created_at"),
                media_revision=media_revision,
                total_units=total_units,
                footer=False,
            )
            if len(blob) > 8 * 1024 * 1024:
                raise ValueError(
                    "A imagem excedeu o limite; a versão anterior foi preservada."
                )
            self.blob, self.key = blob, key
        return self.blob, hashlib.sha256(self.blob).hexdigest()


def image_file(blob):
    return discord.File(io.BytesIO(blob), filename="tierlist.png")


def index_text(
    store,
    panel,
    *,
    wiki_status="cache",
    media_pending=0,
    ai_enabled=None,
    portrait_count=0,
    progress=None,
):
    thread = store.thread(panel["guild_id"])
    progress = progress or poll_progress(store, ai_enabled=ai_enabled)
    lines = [
        "## Votações e histórico",
        "**A imagem no canal mostra a classificação atual. As enquetes abertas aparecem junto dela; os resultados ficam aqui.**",
        "Propostas com motivos, mudanças e condições de uso. Você escolhe **Aprovar**, **Manter** ou **Precisa de mais testes**.",
        "**Leitura:** Casual fica à esquerda e Infinite à direita, com posições independentes. Em cada modo, META e Good se dividem em Hill/Hybrid, Ground e Support. A ordem da linha vai da esquerda para a direita. Abra a imagem para ampliar.",
        "\n**Regras:** 10 minutos · mínimo de 5 participantes · dois terços a favor · um voto por conta na rede. Você pode trocar até o prazo. As escolhas aparecem no resultado final.",
        "No máximo uma proposta por hora; sem evidência suficiente, a classificação é preservada.",
        "\n" + progress_text(progress),
    ]
    proposal = store.active_proposal()
    if proposal and thread:
        receipt = store.connection.execute(
            "SELECT message_id,channel_id FROM tier_poll_messages WHERE proposal_id=? AND guild_id=? AND status!='removed' ORDER BY channel_id=? DESC LIMIT 1",
            (proposal["id"], panel["guild_id"], panel["channel_id"]),
        ).fetchone()
        if receipt:
            lines.append(
                f"**Proposta atual:** [abrir votação](https://discord.com/channels/{panel['guild_id']}/{receipt[1]}/{receipt[0]})."
            )
    if thread:
        approved = store.rows(
            "SELECT m.message_id,m.proposal_id FROM tier_poll_messages m JOIN tier_proposals p ON p.id=m.proposal_id WHERE m.channel_id=? AND p.status='approved' ORDER BY p.id DESC LIMIT 1",
            (thread["thread_id"],),
        )
        if approved:
            lines.append(
                f"**Última votação aprovada:** [ver resultado](https://discord.com/channels/{panel['guild_id']}/{thread['thread_id']}/{approved[0]['message_id']})."
            )
    lines += [
        "\nTem um retrato melhor ou uma skin atualizada? Use **Sugerir imagem** e acompanhe em **Meus envios**. A substituição passa por revisão.",
    ]
    if portrait_count:
        pending_text = (
            "1 forma aguarda"
            if portrait_count == 1
            else f"{portrait_count} formas aguardam"
        )
        lines.append(
            f"**Quer ajudar?** {pending_text} retrato. Consulte **retratos-pendentes.txt** e envie a imagem da forma exata pelo botão."
        )
    return "\n".join(lines)


def poll_embed(store, catalog, proposal):
    uid = next(iter(proposal["details"]))
    detail = proposal["details"][uid]
    name = catalog.display_name(uid)
    before = detail.get("before")
    question = (
        f"{name} deve passar {catalog.display_name(before)}?"
        if before
        else f"{name} deve ficar em {label(detail['tier'])}?"
    )
    state = POLL_STATES.get(proposal["status"], "Encerrada")
    active = proposal["status"] in ("open", "queued")
    embed = discord.Embed(
        title=safe(question if active else f"{state} · {name}", 250),
        description=f"**Modo: {MODES.get(proposal.get('mode', 'infinite'), 'Infinite')}**\n"
        + safe(detail["reason"], 700),
        color=(
            0xA283E8
            if active
            else 0x27864A
            if proposal["status"] == "approved"
            else 0x68727E
        ),
    )
    base = store.rows(
        "SELECT ranking FROM tier_publications WHERE id=?",
        (proposal["base_publication"],),
    )
    old = json.loads(base[0]["ranking"]) if base else []
    changes = [
        f"**{safe(name, 100)}:** ~~{place(old, uid)}~~ → **{place(proposal['ranking'], uid)}**"
    ]
    if before:
        changes.append(
            f"**{safe(catalog.display_name(before), 100)}:** ~~{place(old, before)}~~ → **{place(proposal['ranking'], before)}**"
        )
    proposal_label = (
        "**Se aprovada:**"
        if active
        else "**Mudança aprovada:**"
        if proposal["status"] == "approved"
        else "**Proposta avaliada; não aplicada:**"
    )
    embed.add_field(
        name="O que muda",
        value=proposal_label + "\n" + "\n".join(changes),
        inline=False,
    )
    portrait = portraits().get(uid) if uid in catalog.units else None
    if portrait and portrait.get("url"):
        embed.set_thumbnail(url=portrait["url"])
    if detail.get("conditions"):
        embed.add_field(
            name="Quando essa vantagem se aplica",
            value=safe(detail["conditions"], 300),
            inline=False,
        )
    if detail.get("caveat"):
        embed.add_field(
            name="O que precisa ser considerado",
            value=safe(detail["caveat"], 300),
            inline=False,
        )
    counts = (
        store.poll_counts(proposal["id"])
        if proposal["status"] in ("open", "queued")
        else proposal["outcome"]
    )
    if proposal["status"] in ("open", "queued"):
        total = sum(counts.values())
        remaining = max(0, 5 - total)
        participation = (
            f"Faltam {remaining} para o mínimo."
            if remaining
            else "Mínimo de participantes atingido."
        )
        value = f"**{total} participantes.** {participation} Escolhas reveladas ao encerrar."
    else:
        value = f"**Aprovar:** {counts.get('approve', 0)} · **Manter:** {counts.get('keep', 0)} · **Mais testes:** {counts.get('test', 0)}"
    embed.add_field(name=state, value=value, inline=False)
    result_text = {
        "approved": "A proposta atingiu o mínimo de participantes e dois terços a favor. A mudança foi aplicada à imagem.",
        "maintained": "A proposta não atingiu dois terços a favor. A classificação foi mantida.",
        "needs-tests": "O resultado pede mais testes. A mudança não foi aplicada à imagem.",
        "not-enough-votes": f"Participaram {sum(counts.values())} de pelo menos 5 pessoas necessárias. A classificação foi mantida.",
        "outdated": "A classificação ou as fontes mudaram antes da conclusão. Esta proposta não foi aplicada.",
        "unavailable": "A publicação da enquete deixou de estar disponível. Esta proposta não foi aplicada.",
        "suspended": "O responsável suspendeu esta proposta. A classificação foi mantida.",
        "game-updated": "O jogo recebeu uma atualização. Esta proposta foi cancelada para evitar uma decisão com dados anteriores. A classificação foi preservada.",
    }.get(proposal["status"])
    if result_text:
        embed.add_field(name="Resultado", value=result_text, inline=False)
    if proposal["status"] == "open":
        embed.insert_field_at(
            0,
            name="Prazo",
            value=f"Encerra <t:{int(proposal['closes_at'])}:R> · <t:{int(proposal['closes_at'])}:t>\nMínimo de 5 participantes e dois terços a favor.",
            inline=False,
        )
    elif proposal["status"] == "queued":
        embed.insert_field_at(
            0,
            name="Prazo",
            value="10 minutos a partir da publicação confirmada.",
            inline=False,
        )
    embed.set_footer(text=f"Proposta #{proposal['id']} · decisão da comunidade")
    return embed


# Kept for offline compatibility; the public runtime sends only image_file().
def panel_payload(store):
    publication = store.latest()
    blob = render(publication["ranking"])
    embed = discord.Embed(
        title="Tier list", description=moment(publication["created_at"])
    )
    embed.set_image(url="attachment://tierlist.png")
    return embed, image_file(blob), hashlib.sha256(blob).hexdigest()


def log_embed(store, catalog, page=1):
    embed = discord.Embed(title="Atualizações · Meta", color=0x960D16)
    for row in store.history(page):
        embed.add_field(
            name=safe(catalog.display_name(row["unit_id"]), 150),
            value=safe(row["reason"], 700)
            + "\n"
            + " · ".join(f"[Wiki]({s['url']})" for s in json.loads(row["sources"])[:2]),
            inline=False,
        )
    if not embed.fields:
        embed.description = "Ainda não há mudanças confirmadas no Meta."
    return embed
