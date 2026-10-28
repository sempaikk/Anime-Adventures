"""Create a reproducible complete deployment archive, excluding all private state."""

import argparse
from pathlib import Path
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from bot_release import build_info,shipped_files


def build_package(output,root=ROOT):
    info=build_info(root)
    if not info['verified']:
        raise ValueError('Generate and verify the release manifest before packaging.')
    paths=set(shipped_files(root))
    paths.update(root/name for name in ('data/build.json','README.md','Procfile','.python-version','.env.example'))
    paths.update(root.glob('docs/*.md'))
    output=Path(output).resolve()
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(paths):
            if not path.is_file() or path.is_symlink():
                raise ValueError('An expected release file is missing or is a symbolic link.')
            entry=zipfile.ZipInfo(str(path.relative_to(root)),date_time=(2026,1,1,0,0,0))
            entry.external_attr=0o100644<<16
            entry.compress_type=zipfile.ZIP_DEFLATED
            archive.writestr(entry,path.read_bytes())
    return {'version':info['version'],'files':len(paths),'bytes':output.stat().st_size}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    import json
    print(json.dumps(build_package(args.output)))
