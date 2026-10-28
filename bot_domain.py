"""Small text and path helpers shared by active commands."""

from pathlib import Path
import discord

ROOT = Path(__file__).resolve().parent


def safe(value, limit=1000):
    value = ''.join(c for c in str(value) if c == '\n' or
                    (c.isprintable() and c not in '\u202e\u202d\u2066\u2067\u2068\u2069'))
    escaped = discord.utils.escape_mentions(discord.utils.escape_markdown(value[:limit]))
    return escaped.encode('utf-16-le')[:limit * 2].decode('utf-16-le', errors='ignore')
