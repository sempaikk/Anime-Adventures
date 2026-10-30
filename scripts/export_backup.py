"""Encrypt a verified snapshot for a user-chosen private destination; never upload."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from storage_maintenance import verify_database


def encrypt_snapshot(snapshot,output,recipient):
    # age uses the recipient's public key; no decryption secret enters the bot.
    # Use the audited age tool instead of implementing an encryption format here.
    if not re.fullmatch(r'age1[0-9a-z]{58}',recipient):
        raise ValueError('Use an age X25519 public recipient key.')
    binary=shutil.which('age')
    if not binary:
        raise ValueError('Install the age tool before configuring encrypted external backups.')
    source=Path(snapshot).resolve()
    output=Path(output).resolve()
    if source==output or output.exists():
        raise ValueError('Choose a new encrypted output path; existing backups are preserved.')
    verify_database(source)
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.encrypted-backup-',dir=output.parent) as folder:
        private=Path(folder)/'snapshot.age'
        subprocess.run([binary,'--recipient',recipient,'--output',str(private),str(source)],
                       stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                       timeout=120,check=True)
        os.chmod(private,0o600)
        if private.stat().st_size<100:
            raise ValueError('Encrypted backup was incomplete.')
        with private.open('rb') as stream:
            os.fsync(stream.fileno())
        # Exclusive link refuses concurrent overwrite; temporary and final share a filesystem.
        os.link(private,output)
    with output.open('rb') as stream:
        digest=hashlib.file_digest(stream,'sha256').hexdigest()
    return {'encrypted':True,'bytes':output.stat().st_size,'sha256':digest,
            'uploaded':False,'restore_test_required':True}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot',type=Path)
    parser.add_argument('output',type=Path)
    parser.add_argument('--recipient',required=True,help='age public recipient key; keep its private key outside the host')
    args=parser.parse_args()
    print(json.dumps(encrypt_snapshot(args.snapshot,args.output,args.recipient)))
