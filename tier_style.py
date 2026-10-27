"""Verified application icons, all derived from the original game wiki artwork."""

from __future__ import annotations

import discord
import aiohttp

from quiz_icons import ICONS, asset

# Positive allowlist: original game items/stat symbols. GUI_Tier-List_icon.png
# belongs to the website and must never be rendered by the active bot.
GAME_FILES = {
    "Stars.png",
    "Unit_Storage.png",
    "Summon_Ticket.png",
    "Star_Fruit.png",
    "Star_Remnant.png",
    "Gems.png",
    "Damage_icon.png",
    "SPA_icon.png",
    "Range_icon.png",
}
GAME_KEYS = {key for key in ICONS if asset(key)["source_file"] in GAME_FILES}


class GameTheme:
    def __init__(self):
        self.available = set()

    async def refresh(self, http, application_id):
        if not application_id:
            self.available.clear()
            return
        try:
            data = await http.get_application_emojis(application_id)
            known = {(str(item["id"]), item["name"]) for item in data["items"]}
            self.available = {
                key
                for key, icon in ICONS.items()
                if key in GAME_KEYS and (icon["id"], icon["name"]) in known
            }
        except (
            discord.HTTPException,
            aiohttp.ClientError,
            KeyError,
            TypeError,
            TimeoutError,
        ):
            self.available.clear()

    def icon(self, key):
        key = "units" if key == "rank" else key
        icon = ICONS.get(key)
        return (
            discord.PartialEmoji(name=icon["name"], id=int(icon["id"]))
            if key in GAME_KEYS and key in self.available and icon and icon["id"]
            else None
        )

    def mark(self, key):
        icon = self.icon(key)
        return f"{icon} " if icon else ""

    def image(self, key):
        icon = self.icon(key)
        return (
            f"https://cdn.discordapp.com/emojis/{icon.id}.png?size=128"
            if icon
            else None
        )

    def observe_error(self, error):
        if (
            isinstance(error, discord.HTTPException)
            and error.code == 50035
            and "emoji" in error.text.lower()
        ):
            self.available.clear()


PLAIN_THEME = GameTheme()


def theme_for(bot=None):
    return getattr(bot, "ui_theme", PLAIN_THEME)


def decorate_controls(view, bot):
    theme = theme_for(bot)
    mapping = {"rollback": "rank", "visual-test": "rank"}
    labels = {
        "My messages": "items",
        "Remove copies": "items",
        "My participation": "units",
        "Join": "units",
        "Meus envios": "items",
        "Remover cópias": "items",
        "Sugerir imagem": "units",
        "Revisar imagens": "units",
        "Restaurar retrato anterior": "units",
        "Testar personagens na imagem": "units",
        "Ver alterações de personagens": "units",
        "Minha participação": "units",
        "Participar": "units",
        "Histórico": "clock",
        "Ver tier list": "units",
    }
    for button in view.children:
        if isinstance(button, discord.ui.Button):
            key = mapping.get(button.custom_id)
            key = labels.get(button.label, key)
            if button.label == "Ver tier list":
                key = "rank"
            elif button.label == "Histórico":
                key = "clock"
            if key:
                button.emoji = theme.icon(key)


def icon_sources():
    return {key: asset(key)["source_page"] for key in GAME_KEYS}
