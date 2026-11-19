"""Publish the built wiki folder to a git remote branch (GitHub Pages: branch gh-pages).

Uses the git already installed on the machine and its saved credentials; nothing else is sent anywhere.
"""
from __future__ import annotations

import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


class PublishError(RuntimeError):
    pass


def _git(args, cwd):
    r = subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        raise PublishError((r.stderr or r.stdout or 'git failed').strip()[-600:])
    return r.stdout.strip()


def publish(site_dir, remote, *, branch='gh-pages', message=None, snapshot=False):
    """Commit the whole site folder as one snapshot and force-push it to ``remote`` ``branch``.

    ``snapshot`` keeps a single commit (no history), so a host such as Cloudflare Pages always gets a small repository.
    """
    if not shutil.which('git'):
        raise PublishError('git is not installed (https://git-scm.com/download/win)')
    site = Path(site_dir)
    if not (site / 'index.html').is_file():
        raise PublishError('build the wiki website first (no index.html in ' + str(site) + ')')
    (site / '.nojekyll').write_text('', encoding='utf-8')     # serve folders like assets/ as-is on GitHub Pages
    if not (site / '.git').is_dir():
        _git(['init', '-q'], site)
    if snapshot:
        _git(['checkout', '-q', '--orphan', '_wosb_snapshot'], site)
    else:
        _git(['checkout', '-q', '-B', branch], site)
    _git(['config', 'user.name', 'WoSB Workbench'], site)
    _git(['config', 'user.email', 'workbench@localhost'], site)
    _git(['add', '-A'], site)
    status = _git(['status', '--porcelain'], site)
    if status or snapshot:
        _git(['commit', '-q', '--allow-empty', '-m', message or f'Wiki update {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC'], site)
    if snapshot:
        _git(['branch', '-q', '-M', branch], site)
        subprocess.run(['git', 'reflog', 'expire', '--expire=now', '--all'], cwd=site, capture_output=True)
        subprocess.run(['git', 'gc', '-q', '--prune=now'], cwd=site, capture_output=True)
    _git(['push', '-q', '--force', remote, f'{branch}:{branch}'], site)
    return {'remote': remote, 'branch': branch, 'commit': _git(['rev-parse', '--short', 'HEAD'], site), 'changed': bool(status)}


def pages_url(remote):
    """https://github.com/user/repo(.git) or git@github.com:user/repo.git → https://user.github.io/repo/"""
    import re
    m = re.search(r'github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?/?$', remote or '')
    if not m:
        return None
    user, repo = m.groups()
    return f'https://{user.lower()}.github.io/' + ('' if repo.lower() == f'{user.lower()}.github.io' else repo + '/')
