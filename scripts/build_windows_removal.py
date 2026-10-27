"""Package only the readable Windows removal tools; never user state."""

import argparse
import hashlib
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def build(target):
    target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
    files={'REMOVER-PYTHON-E-BOT.cmd':ROOT/'REMOVER-PYTHON-E-BOT.cmd',
           'remove_python_windows.ps1':ROOT/'scripts/remove_python_windows.ps1',
           'LEIA-ME-REMOCAO.txt':ROOT/'LEIA-ME-REMOCAO.txt'}
    with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED) as bundle:
        for name,path in sorted(files.items()):
            info=zipfile.ZipInfo(name,date_time=(2026,10,27,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
            bundle.writestr(info,path.read_bytes())
    return {'bytes':target.stat().st_size,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('target')
    print(build(parser.parse_args().target))
