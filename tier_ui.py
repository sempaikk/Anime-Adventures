"""Components V2 presentation shared by public and private tier-list messages."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

import discord

from tier_style import theme_for, decorate_controls

log = logging.getLogger("tierlist.ui")


@dataclass
class ComponentFile:
    filename: str
    media: discord.UnfurledMediaItem
    size: int | None = None
    state: object | None = None

    async def read(self):
        if self.state is not None:
            return await self.state.http.get_from_cdn(self.media.url)
        return await self.media.read()


def message_files(message):
    """V2 moves uploaded files into File/MediaGallery components, outside attachments."""
    files = list(getattr(message, "attachments", []))
    known = {getattr(item, "id", None) for item in files}

    def visit(components):
        for component in components:
            media = []
            if isinstance(component, discord.components.FileComponent):
                media.append((component.media, component.name))
            elif isinstance(component, discord.components.MediaGalleryComponent):
                media.extend((item.media, None) for item in component.items)
            for item, name in media:
                if item.attachment_id is not None and item.attachment_id not in known:
                    filename = name or unquote(
                        urlsplit(item.url).path.rsplit("/", 1)[-1]
                    )
                    files.append(
                        ComponentFile(
                            filename, item, state=getattr(message, "_state", None)
                        )
                    )
                    known.add(item.attachment_id)
            visit(getattr(component, "children", []))

    visit(getattr(message, "components", []))
    return files


def component_dicts(value):
    if isinstance(value, (list, tuple)):
        for item in value:
            yield from component_dicts(item)
    elif isinstance(value, dict):
        yield value
        yield from component_dicts(value.get("components", []))
        if value.get("accessory"):
            yield from component_dicts(value["accessory"])
    elif isinstance(value, (discord.ui.View, discord.ui.LayoutView)):
        yield from component_dicts(value.to_components())
    elif hasattr(value, "to_dict"):
        yield from component_dicts(value.to_dict())
    else:
        yield from component_dicts(getattr(value, "components", []))


def visible_text(value):
    """Read legacy text, embeds and nested native components, including test payloads."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return "\n".join(filter(None, (visible_text(item) for item in value)))
    if isinstance(value, dict):
        parts = [
            value.get("content") or "",
            value.get("title") or "",
            value.get("description") or "",
        ]
        for field in value.get("fields", []):
            parts.extend((field.get("name", ""), field.get("value", "")))
        parts.append(value.get("footer", {}).get("text", ""))
        parts.extend(
            visible_text(value.get(key, [])) for key in ("components", "embeds")
        )
        return "\n".join(filter(None, parts))
    if isinstance(value, discord.Embed):
        return visible_text(value.to_dict())
    parts = []
    text = getattr(value, "content", None)
    if isinstance(text, str):
        parts.append(text)
    for name in ("embeds", "components", "children"):
        children = getattr(value, name, None)
        if isinstance(children, (list, tuple)):
            parts.append(visible_text(children))
    return "\n".join(filter(None, parts))


class Card(discord.ui.LayoutView):
    def __init__(self, *, text=None, embeds=(), controller=None, files=(), bot=None):
        super().__init__(timeout=controller.timeout if controller else 600)
        self.controller = controller
        self.theme = theme_for(bot or getattr(controller, "bot", None))
        if controller:
            decorate_controls(controller, bot or getattr(controller, "bot", None))
        used_images = set()
        if text:
            paragraphs = str(text).split("\n\n")
            box = discord.ui.Container(accent_colour=0xA283E8)
            context = controller.__class__.__name__ if controller else ""
            hero_key = {
                "ThreadView": "units",
                "AdminView": "units",
                "GlobalAdminView": "units",
                "GlobalMemberView": "units",
                "ConsentView": "units",
                "GlobalDirectView": "units",
                "MyMessagesView": "items",
                "OperationsView": "clock",
            }.get(context)
            for index, paragraph in enumerate(paragraphs):
                if index:
                    box.add_item(
                        discord.ui.Separator(spacing=discord.SeparatorSpacing.small)
                    )
                image = self.theme.image(hero_key)
                if index == 0 and image:
                    box.add_item(
                        discord.ui.Section(
                            discord.ui.TextDisplay(paragraph),
                            accessory=discord.ui.Thumbnail(image),
                        )
                    )
                else:
                    box.add_item(discord.ui.TextDisplay(paragraph))
            self.add_item(box)
        for embed in embeds:
            box = discord.ui.Container(accent_colour=embed.colour or 0xA283E8)
            is_poll = bool(
                embed.footer.text and embed.footer.text.startswith("Proposta #")
            )
            header = "\n".join(
                filter(
                    None,
                    (
                        "## " + embed.title if embed.title else "",
                        embed.description,
                    ),
                )
            )
            thumbnail = embed.thumbnail.url or (
                self.theme.image("rank") if is_poll else None
            )
            if thumbnail and header:
                box.add_item(
                    discord.ui.Section(
                        discord.ui.TextDisplay(header),
                        accessory=discord.ui.Thumbnail(thumbnail),
                    )
                )
            elif header:
                box.add_item(discord.ui.TextDisplay(header))
            for field in embed.fields:
                box.add_item(
                    discord.ui.Separator(spacing=discord.SeparatorSpacing.small)
                )
                icon = (
                    "clock"
                    if field.name == "Prazo"
                    else "rank"
                    if field.name == "O que muda"
                    else None
                )
                box.add_item(
                    discord.ui.TextDisplay(
                        f"### {self.theme.mark(icon)}{field.name}\n{field.value}"
                    )
                )
            if embed.image.url:
                used_images.add(embed.image.url.removeprefix("attachment://"))
                box.add_item(
                    discord.ui.MediaGallery(discord.MediaGalleryItem(embed.image.url))
                )
            if embed.footer.text:
                box.add_item(discord.ui.TextDisplay("-# " + embed.footer.text))
            self.add_item(box)
        attachments = []
        for file in files:
            filename = getattr(file, "filename", "")
            if not filename or filename in used_images:
                continue
            if filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                attachments.append(
                    discord.ui.MediaGallery(
                        discord.MediaGalleryItem("attachment://" + filename)
                    )
                )
            else:
                attachments.append(discord.ui.File("attachment://" + filename))
        for item in attachments:
            self.add_item(item)
        if controller:
            rows = {}
            for item in controller.children:
                rows.setdefault(item.row or 0, []).append(item)
            controls = discord.ui.Container(accent_colour=0xA283E8)
            for row in sorted(rows):
                titles = {}
                if controller.__class__.__name__ == "AdminView":
                    titles = {
                        0: "Revisão e acompanhamento"
                        if controller.owner
                        else "Administração deste servidor",
                        1: "Correções",
                        2: "Testes",
                        3: "Atualizações do jogo",
                    }
                elif controller.__class__.__name__ == "GlobalAdminView":
                    titles = {
                        0: "Conexão deste servidor",
                        1: "Moderação deste servidor",
                        2: "Sua participação",
                        3: "Moderação da rede · dono do bot",
                        4: "Operação · dono do bot",
                    }
                if titles:
                    controls.add_item(
                        discord.ui.TextDisplay("### " + titles.get(row, "Outras ações"))
                    )
                controls.add_item(discord.ui.ActionRow(*rows[row]))
            if rows:
                self.add_item(controls)

    async def interaction_check(self, i):
        if not self.controller:
            return True
        if self.controller.is_finished():
            from tier_views import reply

            await reply(
                i, "Estes controles expiraram. Abra novamente pelo painel do bot."
            )
            return False
        return await self.controller.interaction_check(i)

    async def on_error(self, i, error, item):
        self.theme.observe_error(error)
        if self.controller:
            return await self.controller.on_error(i, error, item)
        from tier_views import reply

        log.warning("Cartão indisponível: %s", type(error).__name__)
        await reply(i, "Não consegui concluir agora. Tente novamente em instantes.")


def payload(*, bot=None, **kwargs):
    """Preserve standalone PNGs; migrate user-facing messages and controls to V2."""
    original = dict(kwargs)
    text = kwargs.pop("content", None)
    embeds = kwargs.pop("embeds", [])
    embed = kwargs.pop("embed", None)
    if embed:
        embeds = [embed]
    controller = kwargs.pop("view", None)
    if isinstance(controller, discord.ui.LayoutView):
        kwargs.update(content=None, embeds=[], view=controller)
        return kwargs
    if not text and not embeds and not controller:
        return original
    files = list(kwargs.get("files") or kwargs.get("attachments") or [])
    if kwargs.get("file"):
        files.append(kwargs["file"])
    card = Card(text=text, embeds=embeds, controller=controller, files=files, bot=bot)
    if (
        card.total_children_count > 40
        or len(visible_text(card).encode("utf-16-le")) // 2 > 4000
    ):
        raise ValueError(
            "Este cartão excede o limite do Discord; divida as informações."
        )
    kwargs.update(content=None, embeds=[], view=card)
    return kwargs


async def edit(i, **kwargs):
    return await i.edit_original_response(
        **payload(bot=getattr(i, "client", None), **kwargs)
    )


async def edit_response(i, **kwargs):
    return await i.response.edit_message(
        **payload(bot=getattr(i, "client", None), **kwargs)
    )
