"""Produce a verified local WoSB patch ZIP from a compiled onedir release or source tree.

Example: py -3.13 packaging/Make-Offline-Update.py --payload-dir dist/WoSBWorkbench \
  --version 3.2.1 --min-version 3.2.0 --output dist/WoSBWorkbench-3.2.1-Update.zip
"""
import argparse
import hashlib
import json
import zipfile
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from offline_updates import validate_path


def make_archive(source, output, version, min_version, previous=None, notes='', sign_key=None):
    source=Path(source).resolve(strict=True)
    if not source.is_dir():raise ValueError('Payload must be a folder')
    output=Path(output).resolve()
    prev=Path(previous).resolve() if previous else None
    files=[]
    for p in sorted(source.rglob('*')):
        if not p.is_file():continue
        if p.is_symlink():raise ValueError('Source symlink not supported: '+str(p))
        relative=validate_path(p.relative_to(source).as_posix())
        if relative.startswith(('.', '__pycache__/')) or '/__pycache__/' in relative or relative.endswith(('.pyc','.partial')):
            continue
        if relative.casefold() in {'workbench.sqlite3','wosb-update.json'}:continue
        content=p.read_bytes()
        h=hashlib.sha256(content).hexdigest()
        if prev and (prev/relative).is_file() and hashlib.sha256((prev/relative).read_bytes()).hexdigest()==h:
            continue
        files.append((relative,content,h))
    if not files:raise ValueError('No changed files found')
    current={validate_path(p.relative_to(source).as_posix()) for p in source.rglob('*') if p.is_file()}
    remove=[]
    if prev:
        # Files present in the previous build but not this one: the updater removes them
        # (after backing them up) so stale libraries cannot shadow new ones.
        for p in sorted(prev.rglob('*')):
            if not p.is_file():continue
            rel=p.relative_to(prev).as_posix()
            if rel not in current and not rel.startswith('.') and '__pycache__' not in rel:remove.append(validate_path(rel))
    manifest={
        'format':1,'type':'wosb-workbench-update','version':version,'min_version':min_version,
        'notes':notes,'files':[{'path':rel,'size':len(payload),'sha256':digest} for rel,payload,digest in files],
        'remove':remove
    }
    if sign_key:
        from update_signing import load_secret, sign_manifest
        manifest=sign_manifest(manifest,load_secret(sign_key))
        print('Signed manifest with publisher key',manifest['signature']['public_key'][:16]+'…')
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as archive:
        archive.writestr('wosb-update.json',json.dumps(manifest,indent=2))
        for rel,payload,_ in files:archive.writestr('payload/'+rel,payload)
    print('Created',output,'with',len(files),'changed files')
    return output

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--payload-dir',required=True)
    p.add_argument('--previous-dir')
    p.add_argument('--version',required=True)
    p.add_argument('--min-version',required=True)
    p.add_argument('--output',required=True)
    p.add_argument('--notes',default='')
    p.add_argument('--sign-key',help='Path to the publisher Ed25519 secret key (hex). Keep it OUT of the repo.')
    a=p.parse_args()
    make_archive(a.payload_dir,a.output,a.version,a.min_version,a.previous_dir,a.notes,a.sign_key)
