"""Validated, stage-scoped quiz content. Importing this module never contacts the wiki."""

from __future__ import annotations

import json
import random
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


DATA_FILE = Path(__file__).resolve().parent / "data" / "release.json"
RARITIES = {"Rare": "Rara", "Epic": "Épica", "Legendary": "Lendária", "Mythic": "Mítica"}
RARITY_ANSWERS = {
    "Rare": ["Rare", "Rara", "Raro"], "Epic": ["Epic", "Épica", "Épico"],
    "Legendary": ["Legendary", "Lendária", "Lendário"], "Mythic": ["Mythic", "Mítica", "Mítico"],
}


def normalize_answer(value: str) -> str:
    """Ignore case, accents and separators, without guessing misspelled answers."""
    value = unicodedata.normalize("NFKD", value.casefold())
    value = "".join(char for char in value if not unicodedata.combining(char))
    return " ".join(re.sub(r"[\W_]+", " ", value).split())


@dataclass(frozen=True)
class Question:
    id: str
    category: str
    prompt: str
    answer: str
    accepted: tuple[str, ...]
    explanation: str
    sources: tuple[str, ...]
    subject: str
    rarity: str | None = None

    def accepts(self, answer: str) -> bool:
        return normalize_answer(answer) in self.accepted


@dataclass(frozen=True)
class ContentPack:
    stage: str
    questions: tuple[Question, ...]
    sources: dict
    units: tuple[dict, ...]


def load_pack(path: Path = DATA_FILE) -> ContentPack:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or data.get("stage") != "release":
        raise ValueError("O quiz exige um pacote Release válido.")
    sources = data["sources"]
    for source in sources.values():
        url = urlparse(source["url"])
        if url.scheme != "https" or url.hostname != "animeadventures.fandom.com":
            raise ValueError("Fonte de conteúdo inválida.")
    raw_questions = list(data["questions"])
    for unit in data["units"]:
        if unit["rarity"] not in RARITIES:
            raise ValueError(f"Raridade histórica inválida: {unit['id']}")
        label = f"{unit['character']} · {unit['game_name']}"
        detail = f"{unit['character']} é de {unit['anime']}. No jogo: {unit['game_name']}."
        if unit.get("historical_name"):
            detail += f" Nome histórico: {unit['historical_name']}."
        raw_questions.append({
            "id": f"unit:{unit['id']}", "category": "Unidades", "subject": unit["id"],
            "prompt": f"**Quem é esta unidade?**\n\n{unit['hint']}",
            "answer": label, "answers": [unit["character"], unit["game_name"], *unit["aliases"]],
            "explanation": detail, "sources": unit["sources"], "rarity": unit["rarity"],
        })
        raw_questions.append({
            "id": f"rarity:{unit['id']}", "category": "Raridades", "subject": unit["id"],
            "prompt": f"Qual era a **raridade da forma base** de {unit['character']} no Release?",
            "answer": f"{unit['rarity']} · {RARITIES[unit['rarity']]}",
            "answers": RARITY_ANSWERS[unit["rarity"]],
            "explanation": f"A forma base de {unit['character']} está listada como {unit['rarity']} na lista de julho de 2022.",
            "sources": ["roster"],
        })
    questions = []
    identifiers = set()
    for raw in raw_questions:
        for key in ("id", "category", "subject", "prompt", "answer", "explanation", "answers", "sources"):
            if not raw.get(key):
                raise ValueError(f"Pergunta incompleta ({raw.get('id')}): {key}")
        if raw["id"] in identifiers:
            raise ValueError(f"Pergunta duplicada: {raw['id']}")
        identifiers.add(raw["id"])
        if not set(raw["sources"]) <= sources.keys():
            raise ValueError(f"Fonte ausente: {raw['id']}")
        if not isinstance(raw["answers"], list) or not all(isinstance(a, str) for a in raw["answers"]):
            raise ValueError(f"Lista de respostas inválida: {raw['id']}")
        answers = tuple(dict.fromkeys(normalize_answer(a) for a in raw["answers"]))
        if not all(answers):
            raise ValueError(f"Resposta vazia: {raw['id']}")
        if len(raw["prompt"]) > 1500 or len(raw["explanation"]) > 1000:
            raise ValueError(f"Conteúdo longo demais para o Discord: {raw['id']}")
        questions.append(Question(
            id=raw["id"], category=raw["category"], subject=raw["subject"],
            prompt=raw["prompt"], answer=raw["answer"], accepted=answers,
            explanation=raw["explanation"], sources=tuple(raw["sources"]), rarity=raw.get("rarity"),
        ))
    if not questions:
        raise ValueError("O pacote não tem perguntas.")
    return ContentPack(data["stage"], tuple(questions), sources, tuple(data["units"]))


class QuestionDeck:
    """No repeated question until exhaustion, including across deck boundaries."""

    def __init__(self, questions: tuple[Question, ...], rng=None):
        if not questions:
            raise ValueError("O baralho não pode ser vazio.")
        self.questions = questions
        self.rng = rng or random.Random()
        self.remaining: list[Question] = []
        self.last: Question | None = None

    def draw(self) -> Question:
        if not self.remaining:
            self.remaining = list(self.questions)
        candidates = [q for q in self.remaining if self.last is None or q.id != self.last.id]
        candidates = candidates or self.remaining
        varied = [q for q in candidates if self.last is None or (
            q.category != self.last.category and q.subject != self.last.subject
        )]
        chosen = self.rng.choice(varied or candidates)
        self.remaining.remove(chosen)
        self.last = chosen
        return chosen
