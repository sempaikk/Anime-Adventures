"""Build a bot-only, attributed historical pack from an existing read-only archive.

No downloads, Lua execution, website build or edits to the source repository.
"""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
from html import unescape
from html.parser import HTMLParser

TOKEN = re.compile(r'''\s+|--\[\[[\s\S]*?\]\]|--[^\n]*|\[(=*)\[[\s\S]*?\]\1\]|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\d+(?:\.\d*)?(?:[eE][+-]?\d+)?|[A-Za-z_]\w*|.''')


class TableRows(HTMLParser):
    def __init__(self):
        super().__init__();self.stack=[];self.rows=[];self.records=[];self.ignored=0

    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'):self.ignored+=1
        if self.ignored:return
        if tag=='tr':self.stack.append({'cells':[],'spans':[],'current':None,'span':1})
        elif tag in ('td','th') and self.stack:
            self.stack[-1]['current']=[]
            raw=dict(attrs).get('rowspan','1')
            self.stack[-1]['span']=min(20,int(raw)) if raw.isdigit() else 1

    def handle_data(self,data):
        if not self.ignored:
            for row in self.stack:
                if row['current'] is not None:row['current'].append(data)

    def handle_endtag(self,tag):
        if tag in ('script','style'):
            self.ignored=max(0,self.ignored-1);return
        if self.ignored:return
        if tag in ('td','th') and self.stack and self.stack[-1]['current'] is not None:
            self.stack[-1]['cells'].append(re.sub(r'\s+',' ',' '.join(self.stack[-1]['current'])).strip())
            self.stack[-1]['spans'].append(self.stack[-1]['span'])
            self.stack[-1]['current']=None
        elif tag=='tr' and self.stack:
            row=self.stack.pop()
            if row['cells']:self.records.append(row)
            if len(row['cells'])>=2:self.rows.append(row['cells'])


class LiteralTable:
    """Small data reader. Supports tables/literals and basic numeric arithmetic only."""
    def __init__(self, source):
        if len(source.encode()) > 4 * 1024 * 1024:
            raise ValueError('Source table exceeds the build limit.')
        self.tokens = [m.group() for m in TOKEN.finditer(source) if not m.group().isspace() and not m.group().startswith('--')]
        if 'function' in self.tokens or len(self.tokens) > 600000:
            raise ValueError('Only bounded literal data tables are accepted.')
        self.i = 0

    def pop(self):
        token = self.tokens[self.i]
        self.i += 1
        return token

    def string(self, token):
        if token.startswith(('"', "'")):
            return re.sub(r'\\(.)', lambda m: {'n': '\n', 'r': '\r', 't': '\t'}.get(m[1], m[1]), token[1:-1])
        m = re.match(r'\[(=*)\[', token)
        return token[len(m[0]):-len(m[1])-2] if m else None

    def value(self, depth=0):
        if depth > 40 or self.i >= len(self.tokens):
            raise ValueError('Invalid table depth or truncated data.')
        token = self.pop()
        if token == '{':
            result, index = {}, 1
            while self.tokens[self.i] != '}':
                if self.tokens[self.i] in (',', ';'):
                    self.pop(); continue
                if self.tokens[self.i] == '[':
                    self.pop(); key = self.string(self.pop())
                    if self.pop() != ']' or self.pop() != '=':
                        raise ValueError('Invalid literal table key.')
                elif re.fullmatch(r'[A-Za-z_]\w*', self.tokens[self.i]) and self.tokens[self.i+1] == '=':
                    key = self.pop(); self.pop()
                else:
                    key, index = index, index + 1
                result[key] = self.value(depth+1)
                if self.i >= len(self.tokens):
                    raise ValueError('Unterminated literal table.')
            self.pop()
            return result
        if token in ('true', 'false', 'nil'):
            return {'true': True, 'false': False, 'nil': None}[token]
        text = self.string(token)
        if text is not None:
            return text
        # Read a scalar expression until its field delimiter. Unknown identifiers
        # remain unknown; no eval, imports, lookups or calls are permitted.
        parts = [token]
        while self.i < len(self.tokens) and self.tokens[self.i] not in (',', ';', '}'):
            parts.append(self.pop())
        expression = ''.join(parts)
        if not re.fullmatch(r'[\d.eE+*/()\- ]{1,100}', expression):
            return None
        import ast
        import operator
        operators = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
        def numeric(node):
            if isinstance(node, ast.Constant) and type(node.value) in (int, float):
                return node.value
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                return numeric(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
            if isinstance(node, ast.BinOp) and type(node.op) in operators:
                return operators[type(node.op)](numeric(node.left), numeric(node.right))
            raise ValueError('Unsupported scalar.')
        try:
            result = numeric(ast.parse(expression, mode='eval').body)
            return result if math.isfinite(result) and abs(result) <= 1e12 else None
        except (ValueError, SyntaxError, ZeroDivisionError, OverflowError):
            return None

    def read(self):
        if self.pop() != 'return':
            raise ValueError('Expected a literal returned table.')
        data = self.value()
        if self.i != len(self.tokens):
            raise ValueError('Unexpected executable content after the table.')
        return data


def clean(text):
    text = re.sub(r'\{\{Rarity\|([^{}|]+)\}\}',r'\1',text)
    text = re.sub(r'\[\[[^\]]*tier[ _-]?list[^\]]*\]\]','',text,flags=re.I)
    text = re.sub(r'tier[ _-]?list','',text,flags=re.I)
    for _ in range(12):
        previous=text
        text = re.sub(r'\{\{[^{}]*\}\}', '', text)
        if previous==text:break
    text = re.sub(r'\[\[(?:[^]|]+\|)?([^]]+)\]\]', r'\1', text)
    text = re.sub(r'<[^>]*>|\'{2,}|={2,}', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def build(archive):
    raw = archive / 'source/raw'
    wiki = json.loads((archive / 'source/wiki.json').read_text())
    articles = {a['title']: a for a in wiki['articles']}
    sources = {a['pageid']: a for a in wiki['sources']}
    units = LiteralTable((raw / '369.wiki').read_text()).read()
    item_groups = LiteralTable((raw / '728.wiki').read_text()).read()
    items = {}
    def visit(group):
        for label, value in group.items():
            if isinstance(value, dict):
                if isinstance(label, str) and isinstance(value.get('name'), str):
                    items[value['name']] = {'id': value['name'], 'name': label}
                else:
                    visit(value)
    visit(item_groups)
    def provenance(article):
        return {'url': article['source_url'] + ('&' if '?' in article['source_url'] else '?') + 'oldid=' + str(article['revision_id']), 'revision': article['revision_id'], 'date': article['revision_timestamp'], 'hash': article['sha256'], 'status': 'archived'}
    result = []
    for identity in wiki['units']:
        article = articles.get(identity.get('name'))
        if identity.get('retired') or not article or article.get('retired') or article['kind'] != 'unit':
            continue
        unit = units.get(identity['id'], {})
        if unit.get('id') != identity['id']:
            unit = {}
        facts = {x['label']: x['value'] for x in article.get('facts', [])}
        record = {'id': identity['id'], 'name': identity['name'], 'aliases': identity.get('aliases', []), 'rarity': identity.get('rarity'), 'source': provenance(article), 'stats_source': provenance(sources[369]), 'damage_type': unit.get('_base_damage_type'), 'elements': [k.removesuffix('_damage') for k,v in (unit.get('_secondary_damage_types') or {}).items() if v is True], 'tower_type': facts.get('Tower Type'), 'upgrades': []}
        text = (raw / f"{article['pageid']}.wiki").read_text()
        intro = text.split('==Stats')[0].split('==Overview==')[-1]
        record['summary'] = clean(intro.replace('{{PAGENAME}}',identity['name']))[:700]
        record['air_note'] = next((clean(line)[:350] for line in text.splitlines() if re.search(r'air|flying', line, re.I) and re.search(r'hit|attack|target|upgrade', line, re.I)), None)
        rendered = archive / 'source/rendered' / f"{article['pageid']}.json"
        if rendered.exists():
            parsed = json.loads(rendered.read_text()).get('parse',{}).get('text',{})
            html = parsed.get('*','') if isinstance(parsed,dict) else parsed
            visible = re.sub(r'\s+',' ',unescape(re.sub(r'<[^>]*>',' ',html)))
            candidates = re.findall(r'[^.!?]{0,100}(?:hit|target|attack)[^.!?]{0,60}(?:air|flying)[^.!?]{0,100}',visible,re.I)
            if candidates:
                candidates.sort(key=lambda x:('upgrade' not in x.casefold(),len(x)))
                note=candidates[0].strip()
                start=re.search(r'Attacks? starting|Can hit|Hits air|Can attack|From [Uu]pgrade',note)
                record['air_note'] = (note[start.start():] if start else note)[:350]
        record['from'] = (unit.get('evolved') or {}).get('from')
        evolve = unit.get('evolve') or {}
        outcome=evolve.get('evolve_unit')
        record['to'] = outcome if isinstance(outcome,str) else None
        record['branches']=[x['unit_id'] for x in outcome.values() if isinstance(x,dict) and isinstance(x.get('unit_id'),str)] if isinstance(outcome,dict) else []
        req = (evolve.get('normal') or {}).get('item_requirement') or {}
        record['recipe'] = {row['item_id']: row['amount'] for row in req.values() if isinstance(row, dict) and isinstance(row.get('item_id'), str) and type(row.get('amount')) in (int,float) and row['amount'] > 0}
        record['takedowns'] = (evolve.get('normal') or {}).get('_takedown_requirement')
        for key in ('cost', 'damage', 'attack_cooldown', 'range', 'spawn_cap'):
            v = unit.get(key)
            record[key] = v if type(v) in (int,float) and v >= 0 else None
        for n, upgrade in (unit.get('upgrade') or {}).items():
            if type(n) is int and isinstance(upgrade, dict):
                row = {'level': n}
                for key in ('cost', 'damage', 'attack_cooldown', 'range'):
                    v = upgrade.get(key)
                    row[key] = v if type(v) in (int,float) and v >= 0 else None
                row['note'] = str(upgrade.get('note') or '')[:200]
                record['upgrades'].append(row)
        result.append(record)
    allowed = {'guide', 'item', 'mode', 'mechanic'}
    approved_guides={'Challenges','Contracts','Currencies','Curses','Damage Affinities / Elements','Dungeon','Dungeons','Effects','Enemy Mechanics','Evolution','Infinite','Items','Legend Stages','Map Lengths','Portals','Powerups','Quests','Raids','Relics','Relic Shards','Secret Portal','Store','Story','Summon','Time Machine','Traits','Travelling Merchant Shop'}
    guides = []
    for a in wiki['articles']:
        if a['kind'] not in allowed or a['title'] not in approved_guides or a.get('retired') or a.get('empty'):
            continue
        text = (raw / f"{a['pageid']}.wiki").read_text()
        guides.append({'id': str(a['pageid']), 'name': a['title'], 'kind': a['kind'], 'summary': clean(text)[:1800], 'source': provenance(a)})
    # Exact first-column matches only: an ingredient mentioned in another
    # item's recipe is not evidence of where the ingredient itself is found.
    norm=lambda value:re.sub(r'[^a-z0-9]','',value.casefold())
    for title in ('Items','Evolution'):
        article=articles[title]
        parsed=json.loads((archive/'source/rendered'/f"{article['pageid']}.json").read_text())['parse']['text']
        html=parsed.get('*','') if isinstance(parsed,dict) else parsed
        table=TableRows();table.feed(html)
        names={norm(item['name']) for item in items.values()}
        details={};active=None;remaining=0
        for row in table.records:
            cells=row['cells'];first=norm(cells[0])
            key=first if first in names else next((name for name in names if first==name*2),None)
            if key and len(cells)>=2:
                details[key]=cells[1:]
                active,remaining=key,row['spans'][0]-1
            elif active and remaining>0:
                details[active].extend(cells);remaining-=1
            else:active=None;remaining=0
        for item in items.values():
            row=details.get(norm(item['name']))
            if row and any(re.search(r'obtain|purchas|craft|reward|drop|challeng|merchant',v,re.I) for v in row):
                item['archived_details']=' '.join(row)[:1000]
                item['details_source']=provenance(article)
    return {'schema': 1, 'license': 'CC-BY-SA; Fandom contributors. Text attribution retained in each source link. No image files copied.', 'status': 'historical archive, not verified current game data', 'units': result, 'items': list(items.values()), 'guides': guides, 'item_source': provenance(sources[728])}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] / 'data/game_knowledge.json')
    args = parser.parse_args()
    data = build(args.archive)
    from check_game_data import validate
    staged=args.output.with_name('.'+args.output.name+'.pending')
    try:
        staged.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')) + '\n')
        validate(staged)
        os.replace(staged,args.output)
    finally:
        staged.unlink(missing_ok=True)
    print(json.dumps({'units': len(data['units']), 'items': len(data['items']), 'guides': len(data['guides']), 'bytes': args.output.stat().st_size, 'source_edited': False}))
