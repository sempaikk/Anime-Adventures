"""Build a Windows companion ZIP from public source only; never user state."""

import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def build(target, *, patch=False):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    paths = [ROOT/'game_knowledge.py',ROOT/'knowledge_pc.py',ROOT/'LEIA-ME-ATUALIZACAO.txt'] if patch else sorted(ROOT.glob('*.py')) + [ROOT/name for name in (
        'requirements.txt','requirements-pc.txt','CONFIGURAR-PC.cmd','INICIAR-PC.cmd',
        'FINALIZAR-MIGRACAO.cmd','LEIA-ME-PC.md','LEIA-ME-ATUALIZACAO.txt','data/game_wiki.json')]
    files = {str(path.relative_to(ROOT)):path.read_bytes() for path in paths}
    manifest = {name:hashlib.sha256(data).hexdigest() for name,data in files.items()}
    files['patch-manifest.json' if patch else 'package-manifest.json'] = json.dumps(manifest,indent=2).encode()
    with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED) as bundle:
        for name,data in sorted(files.items()):
            info=zipfile.ZipInfo(('' if patch else 'Anime-Adventures-PC/')+name,date_time=(2026,10,27,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED
            bundle.writestr(info,data)
    result={'file':target.name,'bytes':target.stat().st_size,'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'files':len(files)}
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target')
    parser.add_argument('--patch',action='store_true')
    args=parser.parse_args()
    print(json.dumps(build(args.target,patch=args.patch),indent=2))
