"""Game questions and bounded practice scenarios derived from cited Release facts.

Generated scenarios are not additional historical discoveries. No anime riddles,
modern statistics, unverified lobby geometry or later-update items are activated.
"""

from itertools import combinations, product
import hashlib
import json
from pathlib import Path
import random


RARITIES = {'Rare': 'Rara', 'Epic': 'Épica', 'Legendary': 'Lendária', 'Mythic': 'Mítica'}
RANK = {name: index for index, name in enumerate(RARITIES)}
RARITY_ANSWERS = {
    'Rare': ['Rare', 'Rara', 'Raro'], 'Epic': ['Epic', 'Épica', 'Épico'],
    'Legendary': ['Legendary', 'Lendária', 'Lendário'], 'Mythic': ['Mythic', 'Mítica', 'Mítico'],
}
MEDIA_FILE = Path(__file__).resolve().parent / 'data/media.json'


def build_questions(data, normalize):
    media = json.loads(MEDIA_FILE.read_text())
    raw = [dict(q) for q in data['questions'] if not q['id'].endswith(':anime')]
    original = {q['id']: q for q in raw}
    units = data['units']
    for u in units:
        if u['rarity'] not in RARITIES:
            raise ValueError('Raridade histórica inválida: ' + u['id'])

    def rng(identifier):
        return random.Random(int.from_bytes(hashlib.sha256(identifier.encode()).digest()[:8], 'big'))

    def choice(q, correct, pool):
        accepted = {normalize(a) for a in q['answers']}
        if normalize(correct) not in accepted:
            raise ValueError('A alternativa correta precisa ser uma resposta aceita: ' + q['id'])
        wrong = {}
        for candidate in pool:
            key = normalize(candidate)
            if key and key not in accepted:
                wrong.setdefault(key, candidate)
        if len(wrong) < 2:
            raise ValueError('Faltam alternativas distintas: ' + q['id'])
        q['options'] = [correct, *rng(q['id']).sample(list(wrong.values()), 2)]
        rng(q['id'] + ':order').shuffle(q['options'])
        return q

    def add(identifier, category, subject, prompt, answer, sources, *, family, pool=None,
            explanation=None, answers=None, media_key=None):
        q = {'id': identifier, 'category': category, 'subject': subject, 'prompt': prompt,
             'answer': answer, 'answers': answers or [answer], 'sources': list(sources),
             'explanation': explanation or answer, 'family': family}
        if category == 'Raridades':
            q['alias_sources'] = ['names']
        if pool is not None:
            choice(q, answer, pool)
        if media_key:
            q['media_key'] = media_key
        raw.append(q)

    # Existing game facts use buttons where typing a long exact phrase is awkward.
    acts = [q for q in raw if q['id'].startswith('act:')]
    for q in acts:
        choice(q, q['answer'], [a['answer'] for a in acts])
    worlds = [q for q in raw if q['id'].startswith('world:') and q['id'].endswith(':order')]
    for q in worlds:
        choice(q, q['answer'], [w['answer'] for w in worlds])

    for u in units:
        aliases = list(dict.fromkeys([u['game_name'], u['character'],
                                      *([u['historical_name']] if u.get('historical_name') else []), *u['aliases']]))
        asset = media['assets'].get(media['units'].get(u['id']))
        if asset and asset.get('quiz_path'):
            raw.append({'id': 'unit:' + u['id'], 'category': 'Unidades', 'subject': u['id'],
                        'prompt': 'Qual é esta **unidade do Anime Adventures**, na forma base?',
                        'answer': u['game_name'] + ' · ' + u['character'], 'answers': aliases,
                        'explanation': '**Também vale:** ' + ', '.join(aliases[1:]) + '.',
                        'sources': u['sources'], 'family': 'unit:image', 'requires_image': True})
        add('rarity:' + u['id'], 'Raridades', u['id'],
            f'Qual era a **raridade de {u["character"]} na forma base**, no lançamento?',
            RARITIES[u['rarity']] + ' · ' + u['rarity'], ['roster'], family='rarity:single',
            answers=RARITY_ANSWERS[u['rarity']],
            explanation=f'{u["game_name"]} ({u["character"]}) era uma unidade {RARITIES[u["rarity"]].lower()}.')

    # Distinct unit pairs: one question per pair, never mirrored or counted by option order.
    for a, b in combinations(units, 2):
        answer = ('Mesma raridade' if a['rarity'] == b['rarity'] else
                  max((a, b), key=lambda u: RANK[u['rarity']])['game_name'])
        add(f'compare:rarity:{a["id"]}:{b["id"]}', 'Raridades', a['id'] + ':' + b['id'],
            f'No lançamento, qual tinha **raridade mais alta**?\n\n'
            f'**{a["game_name"]} ({a["character"]})** ou **{b["game_name"]} ({b["character"]})**? '
            'Considere as formas base.', answer, ['roster'], family='rarity:pair',
            pool=[a['game_name'], b['game_name'], 'Mesma raridade'],
            explanation=f'{a["game_name"]}: {RARITIES[a["rarity"]]}. {b["game_name"]}: {RARITIES[b["rarity"]]}.')

    # A bounded, reproducible selection of team-recognition scenarios; not all 13,244 triples.
    triples = sorted(combinations(units, 3), key=lambda group: hashlib.sha256(
        ':'.join(u['id'] for u in group).encode()).digest())[:360]
    for group in triples:
        highest = max(group, key=lambda u: RANK[u['rarity']])['rarity']
        names = '\n'.join('• ' + u['game_name'] + ' (' + u['character'] + ')' for u in group)
        add('team:rarity:' + ':'.join(u['id'] for u in group), 'Raridades', ':'.join(u['id'] for u in group),
            'Qual era a **maior raridade presente neste trio** no lançamento? Considere as formas base.\n\n' + names,
            RARITIES[highest], ['roster'], family='rarity:team', pool=list(RARITIES.values()),
            explanation=' · '.join(u['game_name'] + ': ' + RARITIES[u['rarity']] for u in group) + '.')

    # Route and progression questions are built from the actual stage/boss records.
    world_names = {q['id'].split(':')[1]: q['answer'] for q in worlds}
    for q in acts:
        _, world, act = q['id'].split(':')
        add('route:' + q['id'], 'Mundos', 'world:' + world,
            f'Em qual **mundo do Story** fica o ato **{q["answer"]}**?', world_names[world], ['story'],
            family='world:act', pool=list(world_names.values()),
            explanation=f'{q["answer"]} é o ato {act} de {world_names[world]}.')
    bosses = [q for q in original.values() if q['id'].startswith('boss:') and not q['id'].endswith(':form')]
    for q in bosses:
        parts = q['id'].split(':'); world, act = parts[1:3]
        add('route:' + q['id'], 'Chefes', 'world:' + world,
            f'Em qual **mundo do Story** você enfrenta **{q["answer"]}**?', world_names[world], ['story'],
            family='boss:world', pool=list(world_names.values()),
            explanation=f'{q["answer"]} aparece no ato {act} de {world_names[world]}.')
        add('stage:' + q['id'], 'Chefes', 'world:' + world,
            f'Em qual **ato de {world_names[world]}** aparece **{q["answer"]}**?', 'Ato ' + act, ['story'],
            family='boss:stage', pool=['Ato ' + str(i) for i in range(1, 7)],
            explanation=f'É o ato {act} de {world_names[world]}.')

    foods = []
    for q in original.values():
        if q['id'].startswith('food:') and q['id'].endswith(':xp'):
            name = q['id'].split(':')[1]
            foods.append((name, int(q['answer'].split()[0]), media['foods'].get(name)))
    for name, xp, key in foods:
        for count in range(2, 21):
            total = count * xp
            add(f'practice:food:{name}:{count}', 'Comida e XP', name,
                f'Pelo valor de XP do lançamento, quanto **XP** somam **{count} itens {name}**, sem bônus?',
                str(total) + ' XP', ['items'], family='food:quantity', pool=[str(v) + ' XP' for v in
                [total + xp, total - xp, total * 2, xp]], media_key=key,
                explanation=f'{count} × {xp} XP = {total} XP. É o valor dos itens, antes de bônus ou limite de nível.')
    for (a, xa, _), (b, xb, _) in combinations(foods, 2):
        for na, nb in product(range(1, 6), repeat=2):
            total = na * xa + nb * xb
            add(f'practice:food-mix:{a}:{b}:{na}:{nb}', 'Comida e XP', a + ':' + b,
                f'Quanto **XP** somam **{na} {a} + {nb} {b}**, usando os valores do lançamento e sem bônus?',
                str(total) + ' XP', ['items'], family='food:mixed', pool=[str(v) + ' XP' for v in
                [total + xa, total + xb, total - xa, total * 2]],
                explanation=f'({na} × {xa}) + ({nb} × {xb}) = {total} XP, antes de bônus ou limite de nível.')

    for count in range(2, 51):
        total = count * 50
        add(f'practice:summon:cost:{count}', 'Summon', 'summon',
            f'No lançamento, quantas **Gems custavam {count} summons comuns**, sem VIP?', str(total) + ' Gems', ['summon'],
            family='summon:budget', pool=[str(v) + ' Gems' for v in [total + 50, total - 50, total * 2]],
            explanation=f'{count} × 50 Gems = {total} Gems.', media_key='currency-gems')
        discount = count * 40
        add(f'practice:summon:vip:{count}', 'Economia', 'summon',
            f'Com o **desconto VIP de 20%** do lançamento, quantas Gems custavam **{count} summons comuns**?',
            str(discount) + ' Gems', ['summon', 'store'], family='economy:vip',
            pool=[str(v) + ' Gems' for v in [total, discount + 40, discount - 40]],
            explanation=f'50 × 0,8 = 40 Gems por summon. {count} × 40 = {discount} Gems.', media_key='currency-gems')
    for completed in range(1, 50):
        remaining = 50 - completed
        add(f'practice:summon:pity:{completed}', 'Summon', 'pity',
            f'Você fez **{completed} summons desde o zero**, sem tirar uma Legendary. Quantos **faltam para completar o pity** do lançamento?',
            str(remaining), ['summon'], family='summon:pity', pool=[str(v) for v in
            [remaining + 1, max(0, remaining - 1), 50, completed + 50]],
            explanation=f'O pity completava em 50 summons: 50 − {completed} = {remaining}.')
    for cycles in range(2, 41):
        seconds, gems = cycles * 150, cycles * 3
        add(f'practice:time:{cycles}', 'Economia', 'time_machine',
            f'No lançamento, depois de **{seconds // 60}min{(" " + str(seconds % 60) + "s") if seconds % 60 else ""}** '
            'dentro da Time Machine, quantas Gems seriam geradas **sem VIP nem Premium**?',
            str(gems) + ' Gems', ['time'], family='economy:time', pool=[str(v) + ' Gems' for v in [gems + 3, gems - 3, gems * 2]],
            explanation=f'{seconds} ÷ 150 = {cycles} ciclos. {cycles} × 3 = {gems} Gems.', media_key='system-time-machine')

    rewards = [q for q in original.values() if q['id'].startswith('quest:') and q['id'].endswith(':reward')]
    for a, b in combinations(rewards, 2):
        va, vb = int(a['answer'].split()[0]), int(b['answer'].split()[0])
        na, nb = a['id'].split(':')[1], b['id'].split(':')[1]
        answer = 'Mesma recompensa' if va == vb else (na if va > vb else nb)
        add(f'compare:quest:{na}:{nb}', 'Missões', 'daily',
            f'Qual Daily quest dava **mais Gems** no lançamento: **{na}** ou **{nb}**?',
            answer, ['quests'], family='quest:compare', pool=[na, nb, 'Mesma recompensa'],
            explanation=f'{na}: {va} Gems. {nb}: {vb} Gems.')
    prices = [q for q in original.values() if q['id'].startswith('store:') and q['id'].endswith(':price')]
    for a, b in combinations(prices, 2):
        va, vb = int(a['answer'].split()[0]), int(b['answer'].split()[0])
        na, nb = a['id'].split(':')[1], b['id'].split(':')[1]
        answer = 'Mesmo preço' if va == vb else (na if va > vb else nb)
        add(f'compare:store:{na}:{nb}', 'Loja e códigos', 'store',
            f'Na loja do lançamento, qual custava **mais Robux**: **{na}** ou **{nb}**?',
            answer, ['store'], family='store:compare', pool=[na, nb, 'Mesmo preço'],
            explanation=f'{na}: {va} Robux. {nb}: {vb} Robux.')
    return raw
