"""Opt-in automatic capture: record while the game is connected, analyze afterwards.

Polls for an established TCP connection owned by WorldOfSeaBattleClient.exe.
When one appears it picks the matching capture adapter, starts a passive TShark
capture (filtered to the game's port) into a Gameplay-style session folder, and
when the connection has been gone for ``grace_polls`` polls it stops, runs the
Protocol Lab catalog on the session and reports the result.

Passive only: it never touches the game process or its traffic. Disabled by
default (settings: capture.auto_capture). Every dependency is injectable, so the
state machine is tested without Windows or TShark.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

IDLE, CAPTURING, ANALYZING, ERROR = 'idle', 'capturing', 'analyzing', 'error'


def _utc():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


class GameWatcher:
    def __init__(self, output_root, *, find_connections=None, pick_interface=None, start=None, stop=None,
                 analyze=None, on_event=None, interval=8.0, grace_polls=3, interface=None):
        from gameplay_capture import discover_game_ports, detect_game_capture_interface
        from network_lab import start_capture, stop_capture
        self.output_root = Path(output_root)
        self.find_connections = find_connections or discover_game_ports
        self.pick_interface = pick_interface or (lambda port: (detect_game_capture_interface(port) or {}).get('interface'))
        self._start = start or (lambda iface, path, port: start_capture(iface, path, bpf=f'tcp port {int(port)}'))
        self._stop = stop or stop_capture
        self._analyze = analyze or self._default_analyze
        self.on_event = on_event or (lambda kind, info: None)
        self.interval = float(interval); self.grace_polls = int(grace_polls)
        self.fixed_interface = interface
        self.state = IDLE; self.session = None; self.proc = None; self.port = None
        self.missing = 0; self.last_error = ''; self.history = []
        self._thread = None; self._stop_event = threading.Event(); self._lock = threading.Lock()

    # ------------------------------------------------------------ control
    def start_background(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, name='game-watcher', daemon=True)
        self._thread.start()
        self.on_event('watching', {'interval': self.interval})

    def stop_background(self, *, finish=True):
        self._stop_event.set()
        if finish and self.state == CAPTURING:
            self._finish_capture(reason='watcher stopped')
        if self._thread:
            self._thread.join(timeout=self.interval + 5)

    def _loop(self):
        while not self._stop_event.is_set():
            try:
                self.tick()
            except Exception as exc:   # keep watching after transient failures
                self.last_error = f'{type(exc).__name__}: {exc}'
                self.on_event('error', {'error': self.last_error})
            self._stop_event.wait(self.interval)

    # ------------------------------------------------------- state machine
    def tick(self):
        with self._lock:
            connections = self.find_connections() or []
            ports = [c['port'] for c in connections if c.get('confirmed', True)]
            if self.state == IDLE and ports:
                self._begin_capture(ports[0])
            elif self.state == CAPTURING:
                if self.port in ports:
                    self.missing = 0
                    if self.proc is not None and self.proc.poll() is not None:
                        self.on_event('error', {'error': 'capture tool exited early', 'session': str(self.session)})
                        self._finish_capture(reason='capture tool exited')
                else:
                    self.missing += 1
                    if self.missing >= self.grace_polls:
                        self._finish_capture(reason='game disconnected')
            return self.state

    def _begin_capture(self, port):
        iface = self.fixed_interface or self.pick_interface(port)
        if not iface:
            self.last_error = 'Could not match the game connection to a capture adapter; set one in Settings.'
            self.on_event('error', {'error': self.last_error})
            return
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        folder = self.output_root / f'Auto-{stamp}'
        folder.mkdir(parents=True, exist_ok=False)
        meta = {'format': 'wosb-gameplay-evidence', 'schema': 1, 'session_id': f'auto-{stamp}',
                'created_utc': _utc(), 'status': 'recording', 'mode': 'automatic packet-only capture',
                'capture': {'video': None, 'pcap': 'game-traffic.pcapng', 'interface': str(iface), 'port': int(port),
                            'filter': f'tcp port {int(port)}', 'game_connection_confirmed': True,
                            'pcap_launch_utc': _utc(), 'video_launch_utc': _utc(), 'video_offset_seconds': 0},
                'privacy': 'Raw packet capture of your own session; stays on this computer.', 'events_count': 0}
        (folder / 'session.json').write_text(json.dumps(meta, indent=2), encoding='utf-8')
        self.proc = self._start(str(iface), folder / 'game-traffic.pcapng', int(port))
        self.session = folder; self.port = int(port); self.missing = 0; self.state = CAPTURING
        self.on_event('capture-started', {'session': str(folder), 'port': port, 'interface': iface})

    def _finish_capture(self, *, reason):
        folder = self.session
        try:
            self._stop(self.proc)
        except Exception as exc:
            self.on_event('error', {'error': f'stop failed: {exc}'})
        self.proc = None
        try:
            meta = json.loads((folder / 'session.json').read_text(encoding='utf-8'))
            meta.update(status='stopped', stopped_utc=_utc(), stop_reason=reason)
            (folder / 'session.json').write_text(json.dumps(meta, indent=2), encoding='utf-8')
        except (OSError, ValueError):
            pass
        self.state = ANALYZING
        self.on_event('capture-stopped', {'session': str(folder), 'reason': reason})
        try:
            summary = self._analyze(folder)
            self.history.append({'session': str(folder), 'summary': summary})
            self.on_event('analysis-finished', {'session': str(folder), 'summary': summary})
        except Exception as exc:
            self.on_event('error', {'error': f'analysis failed: {type(exc).__name__}: {exc}', 'session': str(folder)})
        self.state = IDLE; self.session = None; self.port = None

    @staticmethod
    def _default_analyze(folder):
        import protocol_lab
        files = [p for p in Path(folder).glob('game-traffic*.pcapng') if p.stat().st_size]
        if not files:
            return {'messages': 0, 'note': 'no packets captured'}
        definitions = None
        try:
            from workbench_db import home
            latest = home() / 'Research' / 'Protocol' / 'Protocol-Definitions-latest.json'
            if latest.is_file():
                definitions = json.loads(latest.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            pass
        result = protocol_lab.analyze_session_folder(folder, definitions=definitions)
        protocol_lab.write_reports(result, Path(folder) / 'Protocol')
        return {'messages': result['messages'], 'types': len(result['catalog'].get('types', [])),
                'framing': (result['framing'] or {}).get('description'), 'warning': result.get('warning'),
                'report': str(Path(folder) / 'Protocol' / 'Protocol-Catalog.json')}

    def status(self):
        return {'state': self.state, 'session': str(self.session) if self.session else None,
                'port': self.port, 'last_error': self.last_error, 'completed_sessions': len(self.history)}
