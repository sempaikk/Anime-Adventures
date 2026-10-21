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
    alias_sources: tuple[str, ...] = ()
    options: tuple[str, ...] = ()
    family: str = ''
    requires_image: bool = False
    media_key: str | None = None
    image_after_answer: bool = False

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
    from question_factory import build_questions
    raw_questions = build_questions(data, normalize_answer)
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
        alias_sources = raw.get("alias_sources", [])
        if (not isinstance(alias_sources, list) or not all(isinstance(s, str) for s in alias_sources)
                or not set(alias_sources) <= sources.keys()):
            raise ValueError(f"Fonte de nomes inválida: {raw['id']}")
        if not isinstance(raw["answers"], list) or not all(isinstance(a, str) for a in raw["answers"]):
            raise ValueError(f"Lista de respostas inválida: {raw['id']}")
        answers = tuple(dict.fromkeys(normalize_answer(a) for a in raw["answers"]))
        if not all(answers):
            raise ValueError(f"Resposta vazia: {raw['id']}")
        options = raw.get('options', [])
        if not isinstance(options, list) or (options and (len(options) != 3
                        or not all(isinstance(o, str) and 0 < len(o) <= 80 for o in options)
                        or len({normalize_answer(o) for o in options}) != 3
                        or sum(normalize_answer(o) in answers for o in options) != 1)):
            raise ValueError(f"Alternativas inválidas: {raw['id']}")
        if len(raw["prompt"]) > 1500 or len(raw["explanation"]) > 1000:
            raise ValueError(f"Conteúdo longo demais para o Discord: {raw['id']}")
        questions.append(Question(
            id=raw["id"], category=raw["category"], subject=raw["subject"],
            prompt=raw["prompt"], answer=raw["answer"], accepted=answers,
            explanation=raw["explanation"], sources=tuple(raw["sources"]), rarity=raw.get("rarity"),
            alias_sources=tuple(alias_sources),
            options=tuple(options), family=raw.get('family', raw['id'].split(':')[0]),
            requires_image=raw.get('requires_image', False),
            media_key=raw.get('media_key'), image_after_answer=raw.get('image_after_answer', False),
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
        self.rng = rng or random.SystemRandom()
        self.remaining: dict[str, Question] = {}
        self.buckets: dict[tuple[str, str], dict[str, Question]] = {}
        self.last: Question | None = None

    def draw(self) -> Question:
        if not self.remaining:
            self.remaining = {q.id: q for q in self.questions}
            self.buckets = {}
            for q in self.questions:
                self.buckets.setdefault((q.category, q.family), {})[q.id] = q
        keys = list(self.buckets)
        categories = sorted({key[0] for key in keys})
        varied = [c for c in categories if self.last is None or c != self.last.category]
        category = self.rng.choice(varied or categories)
        families = [key for key in keys if key[0] == category]
        varied = [key for key in families if self.last is None or key[1] != self.last.family]
        key = self.rng.choice(varied or families)
        bucket = self.buckets[key]
        candidates = [q for q in bucket.values() if self.last is None or q.id != self.last.id]
        candidates = candidates or list(bucket.values())
        varied = [q for q in candidates if self.last is None or q.subject != self.last.subject]
        chosen = self.rng.choice(varied or candidates)
        del self.remaining[chosen.id]
        del bucket[chosen.id]
        if not bucket:
            del self.buckets[key]
        self.last = chosen
        return chosen
