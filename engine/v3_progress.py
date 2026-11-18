"""Durable run status and single-instance lock, usable in Windows PowerShell 5.1."""
from __future__ import annotations
import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f'.{os.getpid()}.tmp')
    with tmp.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, default=str)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)


class Progress:
    def __init__(self, out):
        self.out = Path(out)
        self.started = time.monotonic()
        self.last_update = 0
        self.last_print = 0
        self.data = {'version': '3.0.0', 'pid': os.getpid(), 'started_utc': stamp(),
                     'updated_utc': stamp(), 'status': 'starting', 'stage': 'start',
                     'done': 0, 'total': 0, 'current': '', 'notes': []}
        self.update(force=True)

    def update(self, *, force=False, **changes):
        self.data.update(changes)
        now = time.monotonic()
        if force or now - self.last_update >= 2:
            self.data['updated_utc'] = stamp()
            self.data['elapsed_seconds'] = round(now - self.started, 1)
            atomic_json(self.out / 'Progress.json', self.data)
            self.last_update = now
        if force or now - self.last_print >= 5:
            print(f"[{self.data['stage']}] {self.data['done']}/{self.data['total']} "
                  f"{self.data['current']} ({self.data['elapsed_seconds'] if 'elapsed_seconds' in self.data else 0}s)",
                  flush=True)
            self.last_print = now

    def event(self, message):
        (self.out / 'Events.log').parent.mkdir(parents=True, exist_ok=True)
        with (self.out / 'Events.log').open('a', encoding='utf-8') as stream:
            stream.write(f'[{stamp()}] {message}\n')
        self.update(force=True, current=message)


@contextmanager
def single_run(out):
    """Advisory OS file lock; released even when killed. No PID-only stale locks."""
    path = Path(out) / '.v3-run.lock'
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open('a+b')
    try:
        stream.seek(0)
        stream.write(b'0')
        stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            raise RuntimeError('Another v3 analysis is already running in this output folder.') from e
        yield
    finally:
        try:
            if os.name == 'nt':
                import msvcrt
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        except (OSError, ValueError):
            pass
        stream.close()
