"""Persistent user settings (JSON under the Workbench data folder).

Replaces paths that were hard-coded and re-typed on several pages. Unknown keys
are preserved so older/newer versions can share the file.
"""
from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
from pathlib import Path

DEFAULTS = {
    'schema': 1,
    'first_run_complete': False,
    'installs': {'game': '', 'steam': '', 'launcher': ''},
    'extra_roots': [],
    'capture': {'interface': '', 'port': 23771, 'auto_capture': False, 'auto_analyze': True},
    'tools': {'ffmpeg': '', 'ffprobe': '', 'tshark': '', 'ilspycmd': ''},
    'ui': {'theme': 'dark', 'geometry': '1430x890', 'last_page': 'Overview', 'font_scale': 1.0,
           'toasts': True},
    'recovery': {'extract_protocol_after_recovery': True, 'track_client_versions': True},
    'updates': {'feed_url': '', 'require_signature': True, 'github_repo': 'ajtchess-code/wosbworkbench',
                'check_on_startup': True, 'include_prerelease': False, 'last_check_utc': '', 'skipped_version': ''},
}


def _merge(defaults, data):
    out = copy.deepcopy(defaults)
    for key, value in (data or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


class Settings:
    def __init__(self, path=None):
        if path is None:
            from workbench_db import home
            path = home() / 'settings.json'
        self.path = Path(path)
        self._lock = threading.RLock()
        self.data = self._load()

    def _load(self):
        try:
            raw = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(raw, dict):
                raise ValueError
        except (OSError, ValueError):
            raw = {}
        return _merge(DEFAULTS, raw)

    def get(self, dotted, default=None):
        node = self.data
        for part in dotted.split('.'):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, dotted, value, *, save=True):
        with self._lock:
            parts = dotted.split('.'); node = self.data
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = value
            if save:
                self.save()

    def update(self, mapping, *, save=True):
        for key, value in mapping.items():
            self.set(key, value, save=False)
        if save:
            self.save()

    def save(self):
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(self.data, indent=2, ensure_ascii=False)
            with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=self.path.parent,
                                             delete=False, suffix='.tmp') as fh:
                fh.write(payload); tmp = Path(fh.name)
            os.replace(tmp, self.path)

    def game_roots(self):
        """All configured install folders that exist, Game first."""
        roots = []
        for key in ('game', 'steam', 'launcher'):
            value = (self.get('installs.' + key) or '').strip()
            if value and value not in roots and Path(value).is_dir():
                roots.append(value)
        for value in self.get('extra_roots') or []:
            if value and value not in roots and Path(value).is_dir():
                roots.append(value)
        return roots


_instance = None


def settings():
    global _instance
    if _instance is None:
        _instance = Settings()
    return _instance


def reset_for_tests(path=None):
    global _instance
    _instance = Settings(path) if path else None
    return _instance
