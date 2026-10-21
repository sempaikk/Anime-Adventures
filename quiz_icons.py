"""Original wiki images rendered as application icons, with plain-text fallbacks."""

import json
from pathlib import Path

import discord

import quiz_media as media


ICONS_FILE = Path(__file__).resolve().parent / 'data/ui_icons.json'


def load_icons(path=ICONS_FILE):
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('schema_version') != 1:
        raise ValueError('Manifesto de ícones inválido.')
    for icon in data['icons'].values():
        asset = media.get_asset(icon['asset'])
        if (not asset or asset.get('stage') != 'interface' or asset.get('transparent') is not True
                or asset.get('colored') is not True):
            raise ValueError('O ícone precisa usar uma imagem colorida e transparente da wiki.')
        if icon['id'] is not None and (not isinstance(icon['id'], str) or not icon['id'].isdigit()):
            raise ValueError('Identificador de ícone inválido.')
        if not 2 <= len(icon['name']) <= 32 or not icon['name'].isascii() or not icon['name'].isalnum():
            raise ValueError('Nome de ícone inválido.')
    return data['icons']


ICONS = load_icons()


def component(key):
    icon = ICONS.get(key)
    if not icon or not icon['id']:
        return None
    return discord.PartialEmoji(name=icon['name'], id=int(icon['id']))


def markup(key):
    icon = component(key)
    return f'{icon} ' if icon else ''


def asset(key):
    icon = ICONS.get(key)
    return media.get_asset(icon['asset']) if icon else None
