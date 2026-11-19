"""Publish a built Compendium to the Band of Misfits site (bandofmisfits.org).

The site is split into ZIP parts of at most ~40 MB (each under Cloudflare's 100 MB request limit), each
part is uploaded with its SHA-256, and the site activates the release only after every part verified.
Authentication is an upload token created by a dashboard admin (Dashboard → Wiki → Compendium).
"""
from __future__ import annotations

import hashlib
import io
import json
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

PART_LIMIT = 40_000_000
DEFAULT_URL = 'https://bandofmisfits.org'
STORED = {'.png', '.webp', '.jpg', '.jpeg', '.gif', '.zip', '.glb'}


def make_parts(site: Path, limit: int = PART_LIMIT) -> list[bytes]:
    """ZIP the site into parts of about `limit` bytes; a single larger file gets a part of its own."""
    site = Path(site)
    files = sorted(p for p in site.rglob('*') if p.is_file())
    parts, buf, zf, size = [], None, None, 0

    def close():
        nonlocal buf, zf, size
        if zf:
            zf.close(); parts.append(buf.getvalue())
        buf, zf, size = None, None, 0
    for f in files:
        n = f.stat().st_size
        if zf and size + n > limit:
            close()
        if not zf:
            buf = io.BytesIO(); zf = zipfile.ZipFile(buf, 'w')
        method = zipfile.ZIP_STORED if f.suffix.lower() in STORED else zipfile.ZIP_DEFLATED
        zf.write(f, f.relative_to(site).as_posix(), compress_type=method)
        size += n
    close()
    return parts


def _call(url, token, *, method='POST', body=None, ctype='application/json', timeout=300):
    req = urllib.request.Request(url, data=body, method=method, headers={'Authorization': f'Bearer {token}', 'Content-Type': ctype,
                                                                         'User-Agent': 'WoSB-Workbench'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode('utf-8') or '{}')
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode('utf-8')).get('message') or e.reason
        except Exception:
            msg = e.reason
        raise RuntimeError(f'The site refused the upload ({e.code}): {msg}') from None


def publish(site: Path, token: str, base_url: str = DEFAULT_URL, *, release: str | None = None, progress=None, retries: int = 3) -> dict:
    """Upload `site` (a built Compendium folder) and activate it. Returns the site's final answer."""
    site = Path(site)
    if not (site / 'index.html').is_file():
        raise ValueError('That folder is not a built Compendium (index.html is missing).')
    if not token:
        raise ValueError('Create an upload token in the dashboard first (Dashboard → Wiki → Compendium).')
    say = progress or (lambda *_: None)
    say('Packing the site…')
    parts = make_parts(site)
    meta = {}
    try:
        meta = json.loads((site / 'site.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        pass
    release = release or time.strftime('compendium-%Y%m%d-%H%M%S')
    api = base_url.rstrip('/') + '/api/compendium/upload'
    manifest = [{'index': i, 'size': len(p), 'sha256': hashlib.sha256(p).hexdigest()} for i, p in enumerate(parts)]
    begun = _call(api, token, body=json.dumps({'action': 'begin', 'release': release, 'parts': manifest, 'meta': meta}).encode())
    done = set(begun.get('completed') or [])
    for i, p in enumerate(parts):
        if i in done:
            continue
        for attempt in range(retries):
            say(f'Uploading part {i + 1} of {len(parts)} ({len(p) / 1e6:.1f} MB)…')
            try:
                _call(f'{api}?id={begun["id"]}&part={i}', token, method='PUT', body=p, ctype='application/zip', timeout=900)
                break
            except (RuntimeError, OSError) as exc:
                if attempt == retries - 1:
                    raise RuntimeError(f'Part {i + 1} failed: {exc}') from None
                time.sleep(3 * (attempt + 1))
    say('Activating…')
    return _call(api, token, body=json.dumps({'action': 'finish', 'id': begun['id']}).encode())
