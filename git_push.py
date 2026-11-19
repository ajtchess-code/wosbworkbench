"""Push a folder to a GitHub branch without Git installed.

Builds the Git objects for the folder (blobs, trees, one commit with no parent), writes them into a single packfile and
sends it with Git's smart-HTTP protocol (``git-receive-pack``), authenticated with a GitHub access token. The branch is
replaced by that one snapshot commit, the same as ``wiki_publish.publish(..., snapshot=True)``.

Use a fine-grained personal access token limited to the one repository, with "Contents: Read and write".
"""
from __future__ import annotations

import base64
import hashlib
import os
import re
import struct
import tempfile
import time
import urllib.error
import urllib.request
import zlib
from pathlib import Path

ZERO = '0' * 40
SKIP = {'.git'}
TYPES = {'commit': 1, 'tree': 2, 'blob': 3}


class PushError(RuntimeError):
    pass


def _obj_sha(kind, data):
    return hashlib.sha1(f'{kind} {len(data)}\0'.encode() + data).hexdigest()


def _tree_key(name, is_dir):
    return name.encode('utf-8') + (b'/' if is_dir else b'')        # Git's tree order: directories sort as "name/"


def build(folder, *, message='Wiki update', when=None):
    """(objects {sha: (kind, path or bytes)}, commit sha). Blob contents stay on disk until the pack is written."""
    folder = Path(folder)
    objects = {}

    def tree(d):
        entries = []
        for p in d.iterdir():
            if p.name in SKIP or p.is_symlink():
                continue
            if p.is_dir():
                sha = tree(p)
                if sha:
                    entries.append((_tree_key(p.name, True), b'40000 ' + p.name.encode('utf-8') + b'\0' + bytes.fromhex(sha)))
            elif p.is_file():
                data = p.read_bytes()
                sha = _obj_sha('blob', data)
                objects.setdefault(sha, ('blob', p))
                entries.append((_tree_key(p.name, False), b'100644 ' + p.name.encode('utf-8') + b'\0' + bytes.fromhex(sha)))
        if not entries:
            return None
        body = b''.join(e for _, e in sorted(entries))
        sha = _obj_sha('tree', body)
        objects[sha] = ('tree', body)
        return sha

    root = tree(folder)
    if not root:
        raise PushError(f'{folder} is empty')
    ts = int(when if when is not None else time.time())
    who = f'WoSB Workbench <workbench@localhost> {ts} +0000'
    commit = f'tree {root}\nauthor {who}\ncommitter {who}\n\n{message}\n'.encode('utf-8')
    csha = _obj_sha('commit', commit)
    objects[csha] = ('commit', commit)
    return objects, csha


def write_pack(objects, fh):
    """Write a version-2 packfile (no deltas) with every object. Returns the number of bytes written."""
    h = hashlib.sha1()
    def out(b):
        h.update(b); fh.write(b)
    out(b'PACK' + struct.pack('>II', 2, len(objects)))
    for kind, src in objects.values():
        data = src.read_bytes() if isinstance(src, Path) else src
        size = len(data)
        b = (TYPES[kind] << 4) | (size & 15); size >>= 4
        head = bytearray()
        while size:
            head.append(b | 0x80); b = size & 0x7f; size >>= 7
        head.append(b)
        out(bytes(head)); out(zlib.compress(data, 6))
    fh.write(h.digest())
    return fh.tell()


def _pkt(line):
    data = line.encode('utf-8') if isinstance(line, str) else line
    return f'{len(data) + 4:04x}'.encode() + data


def _read_pkts(buf):
    i, out = 0, []
    while i + 4 <= len(buf):
        n = int(buf[i:i + 4], 16)
        if n == 0:
            out.append(None); i += 4; continue
        out.append(buf[i + 4:i + n]); i += n
    return out


def repo_url(remote):
    """https://github.com/o/r(.git) or git@github.com:o/r.git -> https://github.com/o/r.git"""
    m = re.search(r'github\.com[:/]([^/\s]+)/([^/\s]+?)(?:\.git)?/?$', remote or '')
    if m:
        return f'https://github.com/{m.group(1)}/{m.group(2)}.git'
    if re.match(r'https?://', remote or ''):
        return remote.rstrip('/')
    raise PushError(f'not a GitHub repository URL: {remote}')


def _open(req, what):
    try:
        return urllib.request.urlopen(req, timeout=600)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise PushError(f'{what}: GitHub refused the token (HTTP {e.code}). Use a token for this repository with "Contents: Read and write".') from None
        if e.code == 404:
            raise PushError(f'{what}: repository not found, or the token can\'t see it (HTTP 404).') from None
        raise PushError(f'{what}: HTTP {e.code} {e.reason}') from None
    except urllib.error.URLError as e:
        raise PushError(f'{what}: {e.reason}') from None


def push(folder, remote, token, *, branch='main', message=None, progress=None):
    """Replace ``branch`` of ``remote`` with one snapshot commit of ``folder``. Returns a summary dict."""
    base = repo_url(remote)
    auth = {'Authorization': 'Basic ' + base64.b64encode(f'x-access-token:{token}'.encode()).decode(), 'User-Agent': 'git/2.45 (WoSB Workbench)'}
    say = progress or (lambda msg: None)
    say('Checking the repository…')
    with _open(urllib.request.Request(base + '/info/refs?service=git-receive-pack', headers=auth), 'Reading the repository') as r:
        adv = r.read()
    old = ZERO
    for p in _read_pkts(adv):
        if not p or p.startswith(b'#'):
            continue
        sha, _, rest = p.partition(b' ')
        ref = rest.split(b'\0', 1)[0].strip().decode('utf-8', 'replace')
        if ref == f'refs/heads/{branch}':
            old = sha.decode()
    say('Packing the site…')
    objects, new = build(folder, message=message or f'Wiki update {time.strftime("%Y-%m-%d %H:%M", time.gmtime())} UTC')
    with tempfile.TemporaryFile() as pack:
        cmd = _pkt(f'{old} {new} refs/heads/{branch}\0 report-status agent=wosb-workbench\n') + b'0000'
        pack.write(cmd)
        size = write_pack(objects, pack)
        pack.seek(0)
        say(f'Uploading {size / 1e6:,.1f} MB…')
        req = urllib.request.Request(base + '/git-receive-pack', data=pack, method='POST', headers={
            **auth, 'Content-Type': 'application/x-git-receive-pack-request', 'Accept': 'application/x-git-receive-pack-result',
            'Content-Length': str(size)})
        with _open(req, 'Uploading') as r:
            result = r.read()
    lines = [p.decode('utf-8', 'replace').strip() for p in _read_pkts(result) if p]
    if not any(l == 'unpack ok' for l in lines) or not any(l.startswith(f'ok refs/heads/{branch}') for l in lines):
        raise PushError('GitHub did not accept the upload: ' + ('; '.join(lines) or result[:300].decode('utf-8', 'replace')))
    return {'remote': base, 'branch': branch, 'commit': new[:7], 'objects': len(objects), 'bytes': size, 'changed': old != new}


def find_git():
    """Path of git.exe/git if installed, including the usual Windows install folders that aren't on PATH yet."""
    import shutil
    g = shutil.which('git')
    if g:
        return g
    for root in (os.environ.get('ProgramFiles'), os.environ.get('ProgramFiles(x86)'), os.environ.get('LOCALAPPDATA') and os.path.join(os.environ['LOCALAPPDATA'], 'Programs')):
        if root:
            p = os.path.join(root, 'Git', 'cmd', 'git.exe')
            if os.path.isfile(p):
                return p
    return None
