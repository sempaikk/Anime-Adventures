"""Verify a complete release in a disposable directory without executing the bot."""

import argparse
import json
from pathlib import Path
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bot_release import build_info,shipped_files


def check_package(path):
    with zipfile.ZipFile(path) as archive, tempfile.TemporaryDirectory(prefix='package-check-') as folder:
        names = archive.namelist()
        if len(names) != len(set(names)) or sum(i.file_size for i in archive.infolist()) > 32*1024*1024:
            raise ValueError('Invalid or oversized deployment package')
        for entry in archive.infolist():
            name = Path(entry.filename)
            if name.is_absolute() or '..' in name.parts or (entry.external_attr >> 16) & 0o170000 != 0o100000:
                raise ValueError('Unsafe deployment entry')
        archive.extractall(folder)
        info = build_info(Path(folder))
        if not info['verified']:
            raise ValueError('The deployment package did not match its manifest')
        root=Path(folder)
        allowed={str(p.relative_to(root)) for p in shipped_files(root)}
        allowed.update({'data/build.json','README.md','Procfile','.python-version','.env.example'})
        allowed.update(str(p.relative_to(root)) for p in root.glob('docs/*.md'))
        if set(names)!=allowed:
            raise ValueError('Unexpected or missing files in the deployment package')
        return {'verified': True, 'files': len(names), 'version': info['version'], 'network_used': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package', type=Path)
    args = parser.parse_args()
    print(json.dumps(check_package(args.package)))
