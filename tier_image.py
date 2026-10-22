"""Deterministic tier art, original portraits and compact native Discord messages."""

from __future__ import annotations
import hashlib
import io
import json
import math
from urllib.parse import urlsplit, parse_qs
from pathlib import Path
import discord
from PIL import Image, ImageDraw, UnidentifiedImageError
from community_domain import ROOT
from community_ui import font, portraits
from tier_domain import safe, moment, place
from tier_store import TIERS
from tier_schedule import poll_progress, progress_text

ROW_COLORS = {
    "META": "#920700",
    "S": "#218900",
    "A": "#588800",
    "B": "#008c91",
    "C": "#777900",
    "D": "#886000",
    "E": "#985000",
}
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
):
    media = portraits() if media is None else media
    columns, tile, label = 10, 96, 138
    groups = [(t, [r for r in ranking if r["tier"] == t]) for t in TIERS]
    width = label + columns * tile
    height = sum(max(1, math.ceil(len(rows) / columns)) * tile for _, rows in groups)
    canvas = Image.new("RGB", (width, height + (60 if footer else 0)), "#111415")
    draw = ImageDraw.Draw(canvas)
    top = 0
    allowed = [(ROOT / "assets").resolve()]
    if media_root:
        allowed.append(Path(media_root).resolve())
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
        for row in publication["ranking"]:
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
            blob = render(
                publication["ranking"],
                media=media,
                media_root=self.media_root,
                updated_at=publication["created_at"],
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
    source = (
        "Fontes em cache"
        if wiki_status in ("cache", "unavailable")
        else "Referências sincronizadas"
    )
    lines = [
        "## Votações e histórico",
        "**A imagem no canal mostra a classificação atual. As enquetes abertas aparecem junto dela; os resultados ficam aqui.**",
        "Propostas com motivos, condições e fontes. Você escolhe **Aprovar**, **Manter** ou **Precisa de mais testes**.",
        "\n**Regras:** 10 minutos · mínimo de 5 participantes · dois terços a favor · um voto por conta na rede. Você pode trocar até o prazo. As escolhas aparecem no resultado final.",
        "No máximo uma proposta por hora; sem evidência suficiente, a classificação é preservada.",
        "\n" + progress_text(progress),
        f"**Wiki:** {source}.",
        f"**Última classificação:** {moment(store.latest()['created_at'])}.",
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
        audit = store.rows(
            "SELECT m.message_id FROM tier_audit_messages m WHERE m.guild_id=? ORDER BY audit_id DESC LIMIT 1",
            (panel["guild_id"],),
        )
        if audit:
            lines.append(
                f"**Última revisão:** [ver registro](https://discord.com/channels/{panel['guild_id']}/{thread['thread_id']}/{audit[0]['message_id']})."
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
        else f"{name} deve ficar no tier {'Meta' if detail['tier'] == 'META' else detail['tier']}?"
    )
    state = POLL_STATES.get(proposal["status"], "Encerrada")
    active = proposal["status"] in ("open", "queued")
    embed = discord.Embed(
        title=safe(question if active else f"{state} · {name}", 250),
        description=safe(detail["reason"], 700),
        color=(
            0x960D16
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
        f"**{safe(name, 100)}:** {place(old, uid)} → {place(proposal['ranking'], uid)}"
    ]
    if before:
        changes.append(
            f"**{safe(catalog.display_name(before), 100)}:** {place(old, before)} → {place(proposal['ranking'], before)}"
        )
    embed.add_field(name="O que muda", value="\n".join(changes), inline=False)
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
    for source in detail["sources"][:2]:
        url = source["url"].replace("(", "%28").replace(")", "%29")
        if len(url) > 500:
            revision = parse_qs(urlsplit(url).query).get("oldid", [""])[0]
            url = (
                (
                    "https://animeadventures.fandom.com/wiki/Special:Redirect/revision/"
                    + revision
                )
                if revision.isdigit() and len(revision) <= 20
                else ""
            )
        embed.add_field(
            name="Referência na wiki",
            value=safe(source["quote"], 350)
            + (
                f"\n[Conferir a revisão]({url})"
                if url
                else "\nReferência preservada no registro da proposta."
            ),
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
    if proposal["status"] == "open":
        embed.add_field(
            name="Prazo",
            value=f"Encerra <t:{int(proposal['closes_at'])}:R> · <t:{int(proposal['closes_at'])}:t>\nMínimo de 5 participantes e dois terços a favor.",
            inline=False,
        )
    elif proposal["status"] == "queued":
        embed.add_field(
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
