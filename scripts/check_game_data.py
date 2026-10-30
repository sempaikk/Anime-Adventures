"""Read-only knowledge pack validation/diff before a normal verified release."""

import argparse
import hashlib
import json
from pathlib import Path


def validate(path):
    path = Path(path)
    if path.stat().st_size > 4*1024*1024:
        raise ValueError('Knowledge pack exceeds its budget.')
    data = json.loads(path.read_text())
    if data.get('schema') != 1 or data.get('status') != 'historical archive, not verified current game data':
        raise ValueError('The pack must retain its explicit historical status.')
    seen = set()
    for row in data['units']:
        if row['id'] in seen or not row.get('name'):
            raise ValueError('Duplicate or invalid exact unit identity.')
        seen.add(row['id'])
        if any(row.get(key) is not None and not isinstance(row[key],str) for key in ('from','to')) or not isinstance(row.get('branches',[]),list) or any(not isinstance(x,str) for x in row.get('branches',[])):
            raise ValueError('Evolution links must identify exact forms; branching outcomes need an explicit list.')
        for source in (row['source'],row['stats_source']):
            if source.get('status') != 'archived' or not source.get('date') or not source.get('revision') or not source.get('hash') or not source.get('url','').startswith('https://animeadventures.fandom.com/'):
                raise ValueError('Attribution and historical provenance are required.')
        for amount in row.get('recipe',{}).values():
            if type(amount) not in (int,float) or not 0 < amount <= 1e12:
                raise ValueError('Recipe amounts must be positive numbers, not booleans.')
        for key in ('damage','cost','attack_cooldown','range','spawn_cap'):
            value = row.get(key)
            if value is not None and (type(value) not in (int,float) or not 0 <= value <= 1e12):
                raise ValueError('Invalid numeric unit fact.')
    if not seen or len(seen)>2000 or len(data.get('items',[]))>3000 or len(data.get('guides',[]))>500:
        raise ValueError('Knowledge pack is empty or exceeds row limits.')
    return data


def compare(current, candidate):
    a,b = validate(current),validate(candidate)
    old,new = ({x['id']:x for x in d['units']} for d in (a,b))
    return {'added':sorted(set(new)-set(old)), 'removed':sorted(set(old)-set(new)),
            'changed':[ident for ident in sorted(set(old)&set(new)) if old[ident]!=new[ident]],
            'unresolved_evolution_refs':sorted({ref for row in new.values() for ref in [row.get('from'),row.get('to'),*row.get('branches',[])] if ref and ref not in new}),
            'historical_status_preserved':True,'candidate_sha256':hashlib.sha256(Path(candidate).read_bytes()).hexdigest(),
            'files_replaced':False,'publication_performed':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('candidate',type=Path)
    parser.add_argument('--current',type=Path,default=Path(__file__).resolve().parents[1]/'data/game_knowledge.json')
    args=parser.parse_args()
    print(json.dumps(compare(args.current,args.candidate),indent=2))
