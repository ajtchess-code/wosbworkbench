"""Write wosb-release.json for a GitHub release (run by the release workflow).

    python packaging/Make-Release-Manifest.py --dist dist --version 4.3.7 [--sign-key FILE]

Lists every release asset with SHA-256 and size; the app verifies downloads
against it. With --sign-key (or WOSB_SIGNING_KEY) the manifest is Ed25519-signed.
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dist', required=True)
    ap.add_argument('--version', required=True)
    ap.add_argument('--min-version', default='3.4.0')
    ap.add_argument('--sign-key', default=os.environ.get('WOSB_SIGNING_KEY'))
    ap.add_argument('--out')
    a = ap.parse_args()
    dist = Path(a.dist)
    names = [f'WoSBWorkbench-{a.version}-Setup.exe', f'WoSBWorkbench-{a.version}-Update.zip',
             f'WoSBWorkbench-{a.version}-Portable.zip']
    assets = []
    for name in names:
        path = next((p for p in (dist / name, dist / 'Installer' / name) if p.is_file()), None)
        if path is None:
            raise SystemExit('Missing release asset: ' + name)
        assets.append({'name': name, 'size': path.stat().st_size, 'sha256': sha256(path)})
    manifest = {'format': 'wosb-release-v1', 'version': a.version, 'min_version': a.min_version,
                'built_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'assets': assets}
    if a.sign_key:
        from update_signing import load_secret, sign_manifest
        manifest = sign_manifest(manifest, load_secret(a.sign_key))
    out = Path(a.out or dist / 'wosb-release.json')
    out.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(out, 'signed' if a.sign_key else 'UNSIGNED')


if __name__ == '__main__':
    main()
