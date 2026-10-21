"""Editorial difficulty: recall breadth and calculation steps, never unit rarity."""

import json
from pathlib import Path

LABELS = {'all': 'Todos os níveis', 'easy': 'Fácil', 'medium': 'Médio', 'hard': 'Difícil'}
FORMATS = {'mixed': 'Misto', 'choices': 'Alternativas', 'text': 'Texto', 'image': 'Imagens'}
PROFILE = Path(__file__).resolve().parent / 'data/difficulty.json'
FAMILY_LEVELS = {
    'unit:image': 'easy', 'rarity:single': 'easy', 'rarity:pair': 'medium', 'rarity:team': 'hard',
    'world:act': 'medium', 'boss:world': 'medium', 'boss:stage': 'hard',
    'food:quantity': 'medium', 'food:mixed': 'hard', 'summon:budget': 'medium',
    'economy:vip': 'hard', 'summon:pity': 'medium', 'economy:time': 'hard',
    'quest:compare': 'hard', 'store:compare': 'hard',
}


def classify(question, profile):
    level = profile['questions'].get(question['id'], FAMILY_LEVELS.get(question.get('family')))
    if level not in ('easy', 'medium', 'hard'):
        raise ValueError('Dificuldade sem curadoria: ' + question['id'])
    return level


def matches(question, level='all', mode='mixed'):
    if level != 'all' and question.difficulty != level:
        return False
    return (mode == 'mixed' or (mode == 'choices' and bool(question.options))
            or (mode == 'image' and question.requires_image)
            or (mode == 'text' and not question.options and not question.requires_image))


def load_profile():
    data = json.loads(PROFILE.read_text(encoding='utf-8'))
    if data.get('schema_version') != 1 or not isinstance(data.get('questions'), dict):
        raise ValueError('Perfil de dificuldade inválido.')
    return data
