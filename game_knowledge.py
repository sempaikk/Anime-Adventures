"""Small attributed local lookup pack. Historical facts are never called current."""

from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import unicodedata

from bot_domain import ROOT, safe


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(text)).casefold() if not unicodedata.combining(c) and c.isalnum())


@lru_cache(maxsize=1)
def load_pack():
    path = ROOT / 'data/game_knowledge.json'
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError('The local knowledge pack exceeds its size budget.')
    data = json.loads(path.read_text())
    if data.get('schema') != 1 or not isinstance(data.get('units'), list) or len(data['units']) > 2000:
        raise ValueError('The local knowledge pack needs review.')
    seen = set()
    for row in data['units']:
        if not isinstance(row.get('id'), str) or row['id'] in seen or not row.get('source', {}).get('date'):
            raise ValueError('Unit identities and attribution must be unambiguous.')
        seen.add(row['id'])
    data['fingerprint'] = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    return data


class Knowledge:
    def __init__(self):
        self.data = load_pack()
        self.units = {x['id']: x for x in self.data['units']}
        self.items = {x['id']: x for x in self.data['items']}
        self.guides = {x['id']: x for x in self.data['guides']}

    def search(self, query, kind='unit', filters=None):
        query = normalized(query)
        if len(query) < 2 and not (filters and any(filters.values())):
            raise ValueError('Enter at least two letters to search.')
        pool = self.units if kind == 'unit' else self.items if kind == 'item' else self.guides
        hits = []
        for row in pool.values():
            terms = [row['name'], row['id'], *row.get('aliases', [])]
            names = [normalized(x) for x in terms]
            if not any(query in word for word in names):
                continue
            if filters:
                if any(value and normalized(row.get(key)) != normalized(value) for key, value in filters.items() if key != 'element'):
                    continue
                if filters.get('element') and normalized(filters['element']) not in [normalized(x) for x in row.get('elements', [])]:
                    continue
            score = 0 if query in names else 1 if any(word.startswith(query) for word in names) else 2
            hits.append((score, row['name'], row))
        return [x[2] for x in sorted(hits, key=lambda x: (x[0], x[1]))]

    def exact(self, query):
        if query in self.units:
            return self.units[query]
        hits = self.search(query)
        matches = [x for x in hits if normalized(query) in [normalized(x['name']), *[normalized(a) for a in x.get('aliases', [])]]]
        if len(matches) != 1:
            raise ValueError('Choose the exact form from Search units before using its ID in a team or goal.')
        return matches[0]

    def item_name(self, ident):
        return self.items.get(ident, {}).get('name', ident)

    def exact_item(self, query):
        if query in self.items:return self.items[query]['id']
        matches=[x['id'] for x in self.items.values() if normalized(x['name'])==normalized(query)]
        if len(matches)!=1:raise ValueError('Choose an exact material name/variant or the ID shown in its recipe.')
        return matches[0]

    def unit_name(self, ident):
        if ident is not None and not isinstance(ident,str):return 'unknown'
        return self.units.get(ident, {}).get('name', 'Unknown exact form ('+ident+')' if ident else 'unknown')

    def recipe(self, ident):
        row = self.units[ident]
        if row['recipe']:
            return row
        parent = self.units.get(row.get('from'))
        if parent and (parent.get('to') == ident or ident in parent.get('branches',[])):
            return parent
        return None

    def source(self, row, stats=False):
        source = row.get('stats_source') if stats else row.get('source')
        if not source:
            source = self.data['item_source']
        return f"Historical source: {safe(source['date'][:10])} · [revision {source['revision']}]({source['url']})"

    def card(self, ident, kind='unit'):
        if kind == 'item':
            row = self.items[ident]
            uses = [u for u in self.units.values() if ident in u['recipe']]
            links = [g for g in self.guides.values() if normalized(row['name']) in normalized(g['summary'])]
            text = f"## {safe(row['name'])}\nItem ID: `{ident}`\n"
            text += '\nUsed in archived evolution recipes: ' + (', '.join(safe(u['name'], 70) for u in uses[:8]) or 'not documented in this pack')
            if row.get('archived_details'):
                source=row['details_source']
                text+='\n\n**Archived obtaining / crafting details:**\n'+safe(row['archived_details'],1000)+f"\n[Source · {source['date'][:10]}]({source['url']})\nCurrent availability and prices must be confirmed in the game."
            text += '\n\nArchived guide references:\n' + ('\n'.join(f"[{safe(g['name'])}]({g['source']['url']})" for g in links[:4]) or 'Current farming location is not verified. Use the source to check the requirement.')
            return text + '\n\n' + self.source(row)
        if kind == 'guide':
            row = self.guides[ident]
            return f"## {safe(row['name'])}\n{safe(row['summary'], 1800)}\n\n{self.source(row)}"
        row = self.units[ident]
        value = lambda key: 'unknown' if row.get(key) is None else str(row[key])
        text = f"## {safe(row['name'])}\nExact form ID: `{row['id']}`\n**Historical data — current game values are not verified.**\nSource-data starting values; level, traits, buffs and hit patterns are not inferred.\n\n"
        text += f"Damage type: {safe(value('damage_type'))} · Elements: {safe(', '.join(row['elements']) or 'unknown')}\nPlacement: {safe(value('tower_type'))} · Rarity: {safe(value('rarity'))}\n"
        text += f"Placement cost: {value('cost')} · Base damage: {value('damage')} · Base SPA: {value('attack_cooldown')}\nRange: {value('range')} · Placement cap: {value('spawn_cap')}"
        text += '\n\nAir targeting: ' + safe(row.get('air_note') or 'Not verified. Ground placement alone does not establish whether an attack can hit air.', 350)
        text += '\n\n' + safe(row['summary'], 650)
        return text + '\n\n' + self.source(row) + '\n' + self.source(row, stats=True)

    def evolution(self, ident):
        row = self.units[ident]
        chain, seen, current = [], set(), row
        while current and current['id'] not in seen and len(chain) < 12:
            chain.append(current['name']); seen.add(current['id'])
            current = self.units.get(current.get('to'))
        text = '## Evolution plan\n' + ' → '.join(safe(x, 90) for x in chain)
        if row.get('from'):
            text += '\nPrevious form: ' + safe(self.unit_name(row['from']))
        if row.get('branches'):
            text += '\n\nBranching / random outcomes recorded: '+', '.join(safe(self.unit_name(x),80) for x in row['branches'])+'. Current outcome rates are not verified.'
        recipe = self.recipe(ident)
        if recipe:
            target=self.unit_name(recipe['to']) if recipe.get('to') else 'branching / random recorded outcome'
            text += f"\n\n**{safe(recipe['name'])} → {safe(target)}**\n"
            text += '\n'.join(f"{amount:g} × {safe(self.item_name(item), 90)} (`{item}`)" for item, amount in recipe['recipe'].items())
            if recipe.get('takedowns') is not None:
                text += f"\nTakedown requirement: {recipe['takedowns']}"
            text += '\n\n' + self.source(recipe, stats=True)
        else:
            text += '\n\nNo recipe is documented for this exact form in the local pack.'
        return text + '\nHistorical recipe; confirm it in the current game before spending resources.'

    def upgrades(self, ident, page=0):
        row = self.units[ident]
        selected = row['upgrades'][page*5:page*5+5]
        text = f"## {safe(row['name'])} · upgrades {page+1}\nHistorical stats; attack damage is not automatically DPS.\n"
        for u in selected:
            show = lambda key: 'unknown' if u.get(key) is None else str(u[key])
            text += f"\n**Upgrade {u['level']}** · cost {show('cost')}\nDamage {show('damage')} · SPA {show('attack_cooldown')} · range {show('range')}\n{safe(u['note'], 180)}\n"
        return text + '\n' + self.source(row, stats=True)

    def compare(self, first, second):
        a, b = self.exact(first), self.exact(second)
        text = f"## Compare exact forms\n**{safe(a['name'])} / {safe(b['name'])}**\nHistorical base values, same unmodified conditions.\n"
        for key, label in [('damage_type','Damage type'), ('cost','Placement cost'), ('damage','Base damage'), ('attack_cooldown','Base SPA'), ('range','Range'), ('spawn_cap','Placement cap')]:
            text += f"\n{label}: {a.get(key) if a.get(key) is not None else 'unknown'} / {b.get(key) if b.get(key) is not None else 'unknown'}"
        return text + '\n\n' + self.source(a, True) + '\n' + self.source(b, True)

    def coverage(self, ids):
        units = [self.exact(ident) for ident in ids]
        text = '## Team coverage\nManual team; historical unit facts. This does not predict a guaranteed win.\n'
        text += '\nDamage types: ' + ', '.join(sorted({u['damage_type'] for u in units if u['damage_type']}))
        text += '\nElements: ' + ', '.join(sorted({e for u in units for e in u['elements']}))
        text += '\n\nAir targeting must be confirmed at the upgrade you can afford:\n'
        for u in units:
            text += f"\n**{safe(u['name'], 80)}:** {safe(u.get('air_note') or 'unknown; check exact attacks/upgrades', 220)}"
        return text + '\n\nAlso confirm shield hit requirements, regeneration counters and economy in the current mode. These abilities cannot be inferred from Magic/Physical alone.'


GLOSSARY = {
    'SPA': 'Seconds per attack. Lower SPA means attacks occur more often. A 20% SPA reduction gives 25% more attacks per second when all other conditions stay equal.',
    'DPS': 'Damage per second. Basic DPS = damage per attack / SPA. Multi-hit attacks, DoT, uptime, crit, resistance and targets can change effective output.',
    'Damage and element': 'Magic/Physical and an elemental affinity are different fields. A magic-only team is not automatically a team of one element.',
    'Air': 'Ground/Hill/Hybrid describes placement. Check whether the exact attack can hit air and which upgrade unlocks it.',
    'Shields': 'Check the current shield rule and attack hit counts. High damage alone does not establish that a team can break a shield quickly.',
    'Regeneration': 'Regeneration can increase the damage needed during a fight. Confirm the modifier and counters instead of assuming the displayed HP is the whole requirement.',
    'Chance': 'Independent attempts use 1-(1-p)^n. Pity and changing drop rates need their own verified rules. An expected number of attempts is not a guarantee.',
    'Dungeon goals': 'Completion safety, chests per completed run and useful rewards per hour are different objectives. Compare completion rate and duration as well as chest count.'
}


def advisor(kind, objective, modifiers, coverage=''):
    words = {normalized(x) for x in re.split(r'[,;\n]', modifiers) if x.strip()}
    advice = []
    if any('flight' in x or 'air' in x for x in words):
        advice.append('Flight: confirm air-targeting attacks at an affordable upgrade before choosing it.')
    if any('shield' in x for x in words):
        advice.append('Shielding: confirm the current shield rule and sufficient hit frequency; raw damage alone is not enough.')
    if any('regen' in x or 'vamp' in x for x in words):
        advice.append('Regen: account for healing and confirmed counters; sustained effective damage matters.')
    if any('chaos' in x or 'random' in x for x in words):
        advice.append('Random effects: results cannot be ranked reliably without seeing the actual effect.')
    if any('money' in x or 'shopping' in x for x in words):
        advice.append('Money/shopping: check remaining currency and whether the effect limits placements, upgrades or purchases in this version.')
    if objective == 'chests':
        advice.append('Prioritize the available rare-chest route, then ordinary chests, while retaining enough power to finish. Shop value depends on affordable, confirmed luck effects and remaining rooms.')
    elif objective == 'time':
        advice.append('Compare expected useful rewards per hour: completion rate × rewards per successful run / average attempt duration.')
    else:
        advice.append('Prefer known effects your team already covers. Avoid selecting an unknown effect merely because a fixed list places it higher.')
    if kind=='dungeon':
        offers=normalized(modifiers)
        luck=[name for name in ('Genie Lamp','Golden Fishhook','Fishhook') if normalized(name) in offers]
        # Avoid counting Golden Fishhook as a separate ordinary Fishhook offer.
        if 'Golden Fishhook' in luck and offers.count('fishhook')==1:
            luck=[x for x in luck if x!='Fishhook']
        magic=[name for name in ("Archmage's Hat",'Magic Tome','Mage Coat') if normalized(name) in offers]
        if luck and objective=='chests':
            advice.append('Among these named offers, the archived chest-luck order is: '+' → '.join(luck)+'. This assumes affordable prices and enough combat power. Confirm the current item effects and luck-stacking rule before buying.')
        if magic:
            advice.append('For a magic-damage team, the archived flat magic-bonus order among these offers is: '+' → '.join(magic)+'. Price, remaining rooms and current survival needs may change the best purchase.')
        if 'philosophersstone' in offers:
            advice.append("Philosopher's Stone converts ordinary chests in the archived rules. Its value depends on how many convertible chests you have; it is not directly comparable to a flat luck percentage without current drop rules.")
    if not advice:
        advice.append('Select the modifier shown by the game. No current modifier is inferred from an image hash.')
    source='\n\nArchived item reference: [Dungeon · 2025-03-29](https://animeadventures.fandom.com/wiki/Dungeon?oldid=44215).' if kind=='dungeon' else ''
    return f'## {kind.title()} guidance\nGoal: {objective}\nConditions supplied by you: {safe(modifiers, 350)}\n\n' + '\n\n'.join(advice) + ('\n\nTeam notes: ' + safe(coverage, 400) if coverage else '') + source + '\n\nConditional guidance, not a win prediction. Current room effects, luck stacking and drop rates must be confirmed.'
