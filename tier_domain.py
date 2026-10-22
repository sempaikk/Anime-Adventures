"""Local relevance and presentation rules; never execute community text."""

import hashlib
import json
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import discord

from community_domain import normalize

CRITERIA = (
    "Compare contribuição real para o time, desempenho, custo, upgrades, condições, "
    "utilidade e limitações. Diferencie dano, suporte, controle e economia sem criar "
    "listas separadas. Não conclua superioridade geral por um atributo, raridade, "
    "popularidade ou número de mensagens. Separe forma, evolução, skin e balanceamento."
)
GAME_TERMS = re.compile(
    r"\b(?:dps|spa|upgrades?|evolu\w*|evo|traits?|passiv\w*|nerf\w*|buff\w*|"
    r"summon|summoning|banner|raids?|infinito|infinite|hill|ground|aereo|"
    r"placement|colocacoes|cooldown|stun|bleed|bleeding|sangramento|slow|"
    r"veneno|poison|congelamento|freeze|time stop|wave|waves|ondas|gold|yen|"
    r"gems|gemas|shiny|boss|portal|portais|reliquia|relic|aoe|range|"
    r"custo|alcance|fases?|partida|mapas?|suporte|economia|tier|meta)\b"
)
COMPARISON = re.compile(
    r"\b(?:melhor|pior|mais|menos|supera|superior|inferior|passa|passar|porque|pois|contra|good|better|best|worse|stronger|damage|dano)\b"
)
INJECTION = re.compile(
    r"(?:ignore|ignora|desconsidere|esqueca).{0,45}(?:instrucoes|regras|prompt|sistema)|"
    r"(?:system|developer)\s*[:>]|reveal.{0,20}(?:token|key|prompt)|"
    r"(?:execute|executar).{0,20}(?:codigo|shell|comando)|"
    r"(?:api key|discord token|groq api key)"
)


def relevant_units(catalog, text):
    text = str(text)
    if not 20 <= len(text) <= 4000 or text.lstrip().startswith((">", "```")):
        return set()
    normalized = normalize(text)
    if INJECTION.search(normalized):
        return set()
    explicit = "anime adventures" in normalized
    if not (
        explicit or (GAME_TERMS.search(normalized) and COMPARISON.search(normalized))
    ):
        return set()
    return catalog.mentions(text)


def safe(value, limit=1000):
    value = "".join(
        c
        for c in str(value)
        if c == "\n"
        or (c.isprintable() and c not in "\u202e\u202d\u2066\u2067\u2068\u2069")
    )
    escaped = discord.utils.escape_mentions(
        discord.utils.escape_markdown(value[:limit])
    )
    return escaped.encode("utf-16-le")[: limit * 2].decode("utf-16-le", errors="ignore")


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def place(ranking, unit_id):
    for row in ranking:
        if row["unit_id"] == unit_id:
            position = [
                r["unit_id"] for r in ranking if r["tier"] == row["tier"]
            ].index(unit_id) + 1
            return f"{position}º do {'Meta' if row['tier'] == 'META' else row['tier']}"
    return "Sem avaliação"


def moment(timestamp):
    if not timestamp:
        return "Aguardando a primeira classificação aprovada"
    return (
        datetime.fromtimestamp(timestamp, timezone.utc)
        .astimezone(ZoneInfo("America/Sao_Paulo"))
        .strftime("%d/%m/%Y · %H:%M BRT")
    )
