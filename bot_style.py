"""Verified application icons, all derived from the original game wiki artwork."""

from __future__ import annotations

import discord
import aiohttp

import json
from pathlib import Path

_DATA = json.loads((Path(__file__).with_name('data') / 'status_icon.json').read_text())
ICONS = {'clock': _DATA['icon']}
GAME_KEYS = {'clock'}

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
    """Controls use text; the only decorative game icon belongs to Bot status."""
    for button in view.children:
        if isinstance(button, discord.ui.Button):
            button.emoji = None


def icon_sources():
    return {key: _DATA["source_page"] for key in GAME_KEYS}
