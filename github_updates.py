"""Updates from GitHub Releases (default repo: ajtchess-code/wosbworkbench).

Each release (published by .github/workflows/build-and-release.yml) carries:
  WoSBWorkbench-<v>-Setup.exe     full installer (first install / manual upgrade)
  WoSBWorkbench-<v>-Update.zip    in-app patch (backup, verify, rollback, restart)
  WoSBWorkbench-<v>-Portable.zip  no-install copy
  wosb-release.json               version, min_version, sha256 + size of every asset,
                                  optional Ed25519 signature

The app checks the latest release, downloads the asset it needs, verifies the
SHA-256 from wosb-release.json (and the signature when a publisher key is
bundled), then hands the Update.zip to the existing verified offline updater.

Private repositories need a fine-grained token with read-only "Contents"
permission for that repo; it is stored with secret_store (DPAPI on Windows).
"""
from __future__ import annotations

from fsutil import replace_with_retry
import hashlib
import http.client
import json
import os
import re
import ssl
import urllib.parse
from pathlib import Path

DEFAULT_REPO = 'ajtchess-code/wosbworkbench'
API = 'api.github.com'
ALLOWED_HOSTS = {'api.github.com', 'github.com', 'objects.githubusercontent.com',
                 'release-assets.githubusercontent.com', 'codeload.github.com'}
MANIFEST_NAME = 'wosb-release.json'
MAX_MANIFEST = 512 * 1024
MAX_ASSET = 1024 * 1024 * 1024
TOKEN_NAME = 'github_token'


class UpdateError(Exception):
    pass


def version_tuple(text):
    m = re.fullmatch(r'v?(\d+(?:\.\d+){1,3})', str(text).strip())
    if not m:
        raise UpdateError('Not a release version: ' + str(text))
    return tuple(int(x) for x in m.group(1).split('.'))


def _check_repo(repo):
    if not re.fullmatch(r'[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}', str(repo or '')):
        raise UpdateError('Repository must look like owner/name')
    return repo


def _request(url, *, token=None, accept='application/vnd.github+json', limit=MAX_MANIFEST, sink=None,
             progress=None, redirects=5, timeout=60):
    """HTTPS GET with manual redirects so the token is only ever sent to api.github.com
    (GitHub redirects asset downloads to signed storage URLs that reject extra auth)."""
    for _ in range(redirects + 1):
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != 'https' or parts.hostname not in ALLOWED_HOSTS:
            raise UpdateError('Refusing to contact ' + str(parts.hostname))
        conn = http.client.HTTPSConnection(parts.hostname, timeout=timeout, context=ssl.create_default_context())
        headers = {'User-Agent': 'WoSBWorkbench-updater', 'Accept': accept, 'X-GitHub-Api-Version': '2022-11-28'}
        if token and parts.hostname == API:
            headers['Authorization'] = 'Bearer ' + token
        path = parts.path + ('?' + parts.query if parts.query else '')
        try:
            conn.request('GET', path, headers=headers)
            res = conn.getresponse()
            if res.status in (301, 302, 303, 307, 308):
                url = urllib.parse.urljoin(url, res.getheader('Location') or '')
                res.read(); continue
            if res.status == 404:
                raise UpdateError('Not found (404). For a private repository, add a GitHub token with read access in Updates.')
            if res.status in (401, 403):
                raise UpdateError(f'GitHub refused the request ({res.status}). Check the token, or wait if rate-limited.')
            if res.status != 200:
                raise UpdateError(f'GitHub returned HTTP {res.status}')
            total = int(res.getheader('Content-Length') or 0)
            if total > limit:
                raise UpdateError('Download exceeds safety limit')
            if sink is None:
                data = res.read(limit + 1)
                if len(data) > limit:
                    raise UpdateError('Response exceeds safety limit')
                return data
            size = 0
            while True:
                chunk = res.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > limit:
                    raise UpdateError('Download exceeds safety limit')
                sink(chunk)
                if progress:
                    progress(size, total)
            return size
        finally:
            conn.close()
    raise UpdateError('Too many redirects')


def _api_json(path, token=None):
    return json.loads(_request(f'https://{API}{path}', token=token).decode('utf-8'))


def latest_release(repo=DEFAULT_REPO, *, token=None, include_prerelease=False):
    """Newest published release (optionally including pre-releases) as a dict."""
    _check_repo(repo)
    releases = _api_json(f'/repos/{repo}/releases?per_page=20', token)
    best = None
    for rel in releases:
        if rel.get('draft') or (rel.get('prerelease') and not include_prerelease):
            continue
        try:
            version = version_tuple(rel.get('tag_name', ''))
        except UpdateError:
            continue
        if best is None or version > best[0]:
            best = (version, rel)
    if best is None:
        raise UpdateError('No published releases found in ' + repo)
    rel = best[1]
    assets = {a['name']: {'id': a['id'], 'size': a.get('size', 0), 'api_url': a['url'],
                          'browser_url': a.get('browser_download_url')} for a in rel.get('assets', [])}
    return {'repo': repo, 'tag': rel['tag_name'], 'version': '.'.join(map(str, best[0])), 'name': rel.get('name') or rel['tag_name'],
            'notes': rel.get('body') or '', 'published': rel.get('published_at'), 'prerelease': bool(rel.get('prerelease')),
            'html_url': rel.get('html_url'), 'assets': assets}


def _download_asset(asset, dest, *, token=None, progress=None):
    dest = Path(dest); dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_name(dest.name + '.partial')
    digest = hashlib.sha256()
    try:
        with partial.open('wb') as fh:
            def sink(chunk):
                fh.write(chunk); digest.update(chunk)
            _request(asset['api_url'], token=token, accept='application/octet-stream', limit=MAX_ASSET,
                     sink=sink, progress=progress, timeout=120)
        replace_with_retry(partial, dest)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return dest, digest.hexdigest()


def fetch_manifest(release, *, token=None):
    asset = release['assets'].get(MANIFEST_NAME)
    if not asset:
        raise UpdateError(f'Release {release["tag"]} has no {MANIFEST_NAME}; it was not published by the release workflow')
    data = _request(asset['api_url'], token=token, accept='application/octet-stream')
    manifest = json.loads(data.decode('utf-8'))
    if manifest.get('format') != 'wosb-release-v1' or str(manifest.get('version')) != release['version']:
        raise UpdateError('Release manifest does not match the release tag')
    from update_signing import bundled_public_key, verify_manifest
    key = bundled_public_key()
    if key is not None and not verify_manifest(manifest, key):
        raise UpdateError('Release manifest signature is missing or invalid; update rejected')
    manifest['_signature_verified'] = key is not None
    return manifest


def check(current_version, repo=DEFAULT_REPO, *, token=None, include_prerelease=False):
    rel = latest_release(repo, token=token, include_prerelease=include_prerelease)
    newer = version_tuple(rel['version']) > version_tuple(current_version)
    return {**rel, 'update_available': newer, 'current': current_version}


def pick_asset(release, kind):
    """kind: 'update' | 'setup' | 'portable'."""
    suffix = {'update': '-Update.zip', 'setup': '-Setup.exe', 'portable': '-Portable.zip'}[kind]
    name = f'WoSBWorkbench-{release["version"]}{suffix}'
    if name not in release['assets']:
        raise UpdateError(f'Release {release["tag"]} has no {name}')
    return name


def download(release, kind, folder, *, token=None, progress=None):
    """Download and verify one asset against wosb-release.json. Returns its path."""
    manifest = fetch_manifest(release, token=token)
    name = pick_asset(release, kind)
    expected = next((a for a in manifest.get('assets', []) if a.get('name') == name), None)
    if not expected or not re.fullmatch(r'[0-9a-f]{64}', str(expected.get('sha256', ''))):
        raise UpdateError(f'{name} is not listed with a SHA-256 in the release manifest')
    path, actual = _download_asset(release['assets'][name], Path(folder) / name, token=token, progress=progress)
    if actual != expected['sha256']:
        path.unlink(missing_ok=True)
        raise UpdateError(f'SHA-256 mismatch for {name}; download discarded')
    return {'path': str(path), 'sha256': actual, 'signed': manifest['_signature_verified'],
            'min_version': manifest.get('min_version')}
