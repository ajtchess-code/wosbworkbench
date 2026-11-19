"""Find World of Sea Battle installs (standalone, Steam, launcher) and helper tools.

Read-only: inspects the registry, Steam's libraryfolders.vdf and well-known
folders. Registry and filesystem access are injectable for tests.
"""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

CLIENT_EXE = 'WorldOfSeaBattleClient.exe'
GAME_HINTS = ('world of sea battle', 'worldofseabattle', 'wosb')
# Our own app also matches 'wosb' in Add/Remove Programs; never treat it as a game install.
OWN_APP_HINTS = ('workbench',)
OWN_APP_MARKERS = ('WoSBWorkbench.exe', 'WoSBUpdater.exe')


def is_workbench_dir(path, *, exists=None):
    """True if ``path`` is (or is inside) a WoSB Workbench installation."""
    exists = exists or (lambda p: Path(p).exists())
    try:
        p = Path(str(path))
    except (TypeError, ValueError):
        return False
    if 'workbench' in p.name.casefold():
        return True
    return any(exists(p / marker) for marker in OWN_APP_MARKERS)
COMMON_GAME = [r'C:\Games\World of Sea Battle', r'D:\Games\World of Sea Battle',
               r'C:\Program Files\World of Sea Battle', r'C:\Program Files (x86)\World of Sea Battle']
COMMON_LAUNCHER = [r'C:\Games\Wosb Launcher', r'D:\Games\Wosb Launcher', r'C:\Games\WoSB Launcher']


# ------------------------------------------------------------------- Steam

def parse_vdf(text):
    """Minimal Valve KeyValues parser (enough for libraryfolders.vdf / appmanifest)."""
    tokens = re.findall(r'"((?:[^"\\]|\\.)*)"|([{}])', text)
    stack = [{}]; key = None
    for quoted, brace in tokens:
        if brace == '{':
            child = {}
            if key is not None:
                stack[-1][key] = child
            stack.append(child); key = None
        elif brace == '}':
            if len(stack) > 1:
                stack.pop()
            key = None
        else:
            value = quoted.replace('\\\\', '\\')
            if key is None:
                key = value
            else:
                stack[-1][key] = value; key = None
    return stack[0]


def steam_library_paths(steam_root, *, read_text=None):
    read_text = read_text or (lambda p: Path(p).read_text(encoding='utf-8', errors='replace'))
    roots = [str(steam_root)]
    vdf = Path(steam_root) / 'steamapps' / 'libraryfolders.vdf'
    try:
        data = parse_vdf(read_text(vdf))
    except OSError:
        return roots
    folders = data.get('libraryfolders') or data.get('LibraryFolders') or {}
    for value in folders.values():
        path = value.get('path') if isinstance(value, dict) else value
        if isinstance(path, str) and path and path not in roots and not path.isdigit():
            roots.append(path)
    return roots


def steam_game_dirs(library, *, listdir=None, read_text=None):
    """Game folders under a Steam library whose manifest or folder name matches WoSB."""
    listdir = listdir or (lambda p: os.listdir(p))
    read_text = read_text or (lambda p: Path(p).read_text(encoding='utf-8', errors='replace'))
    apps = Path(library) / 'steamapps'
    found = []
    try:
        names = listdir(apps)
    except OSError:
        return found
    for name in names:
        if not (name.startswith('appmanifest_') and name.endswith('.acf')):
            continue
        try:
            state = parse_vdf(read_text(apps / name)).get('AppState', {})
        except OSError:
            continue
        title = str(state.get('name', '')).casefold()
        if any(h in title.replace(' ', '') or h in title for h in GAME_HINTS) and state.get('installdir'):
            found.append(str(apps / 'common' / state['installdir']))
    try:
        for name in listdir(apps / 'common'):
            if any(h in name.casefold().replace(' ', '') or h in name.casefold() for h in GAME_HINTS):
                candidate = str(apps / 'common' / name)
                if candidate not in found:
                    found.append(candidate)
    except OSError:
        pass
    return found


def _registry_values():
    """Yield (key_path, value_name, value) for registry spots that may point at installs."""
    if os.name != 'nt':
        return
    import winreg
    spots = [(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam', 'SteamPath'),
             (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Valve\Steam', 'InstallPath'),
             (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Valve\Steam', 'InstallPath')]
    for hive, path, name in spots:
        try:
            with winreg.OpenKey(hive, path) as key:
                yield ('steam', name, winreg.QueryValueEx(key, name)[0])
        except OSError:
            continue
    uninstall = [(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Uninstall'),
                 (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall'),
                 (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall')]
    for hive, path in uninstall:
        try:
            with winreg.OpenKey(hive, path) as root:
                for i in range(winreg.QueryInfoKey(root)[0]):
                    try:
                        with winreg.OpenKey(root, winreg.EnumKey(root, i)) as app:
                            display = str(winreg.QueryValueEx(app, 'DisplayName')[0])
                            folded = display.casefold()
                            if any(h in folded for h in OWN_APP_HINTS):
                                continue
                            if any(h in folded for h in GAME_HINTS) or 'sea battle' in folded:
                                location = winreg.QueryValueEx(app, 'InstallLocation')[0]
                                yield ('uninstall', display, location)
                    except OSError:
                        continue
        except OSError:
            continue


def classify_root(path, *, exists=None):
    """'launcher', 'game' or None from folder content/name."""
    exists = exists or (lambda p: Path(p).exists())
    p = Path(path)
    name = p.name.casefold()
    if 'launcher' in name:
        return 'launcher'
    for candidate in (p / CLIENT_EXE, p / 'default' / 'game' / CLIENT_EXE, p / 'game' / CLIENT_EXE,
                      p / 'CommonData', p / 'default' / 'game' / 'CommonData'):
        if exists(candidate):
            return 'game'
    return None


def client_root(path, *, exists=None):
    """The folder that actually holds the client (the launcher installs it under default\\game)."""
    exists = exists or (lambda p: Path(p).exists())
    p = Path(path)
    for candidate in (p, p / 'default' / 'game', p / 'game'):
        if exists(candidate / CLIENT_EXE) or exists(candidate / 'CommonData'):
            return str(candidate)
    return None


def detect_installs(*, registry=None, exists=None, listdir=None, read_text=None, extra=()):
    """Return {'game': [...], 'steam': [...], 'launcher': [...]} of existing folders."""
    exists = exists or (lambda p: Path(p).exists())
    registry = registry if registry is not None else list(_registry_values())
    result = {'game': [], 'steam': [], 'launcher': []}

    def add(kind, path):
        path = str(path)
        if kind in ('game', 'steam') and path:
            # Point at the client folder itself, not a parent such as C:\\Games\\World of Sea Battle.
            path = client_root(path, exists=exists) or (path if kind == 'steam' else '')
        if path and path not in result[kind] and exists(path) and not is_workbench_dir(path, exists=exists):
            result[kind].append(path)

    steam_roots = [v for kind, _, v in registry if kind == 'steam']
    steam_roots += [r'C:\Program Files (x86)\Steam', r'C:\Program Files\Steam']
    for root in dict.fromkeys(str(Path(r)) for r in steam_roots):
        if not exists(root):
            continue
        for library in steam_library_paths(root, read_text=read_text):
            for game in steam_game_dirs(library, listdir=listdir, read_text=read_text):
                add('steam', game)
    for kind, display, location in registry:
        if kind == 'uninstall' and location:
            # Only accept a registry location whose content looks like the game or launcher;
            # a bare name match is not evidence (it picked up our own app before).
            kind_found = 'launcher' if 'launcher' in str(display).casefold() else classify_root(location, exists=exists)
            if kind_found:
                add(kind_found, location)
    for path in COMMON_GAME:
        add('game', path)
    for path in COMMON_LAUNCHER:
        add('launcher', path)
    for path in extra:
        kind = classify_root(path, exists=exists)
        if kind:
            add(kind, path)
    # A launcher folder that also contains the client counts as a game install too.
    for launcher in list(result['launcher']):
        for candidate in (Path(launcher) / 'Game', Path(launcher) / 'game', Path(launcher) / 'World of Sea Battle',
                          Path(launcher).parent / 'World of Sea Battle'):
            if client_root(candidate, exists=exists):
                add('game', candidate)
    return result


# ------------------------------------------------------------------- tools

def _which_any(*names):
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def detect_tools():
    """Helper programs used by capture, video and decompile features."""
    from gameplay_capture import find_video_tool
    from network_lab import find_tshark
    home = Path.home()
    tools = {
        'ffmpeg': find_video_tool('ffmpeg'),
        'ffprobe': find_video_tool('ffprobe'),
        'tshark': find_tshark(),
        'dotnet': _which_any('dotnet'),
        'ilspycmd': _which_any('ilspycmd') or next((str(p) for p in (home / '.dotnet' / 'tools' / 'ilspycmd.exe',
                                                                     home / '.dotnet' / 'tools' / 'ilspycmd') if p.is_file()), None),
    }
    npcap = None
    if os.name == 'nt':
        windir = os.environ.get('WINDIR', r'C:\Windows')
        for candidate in (Path(windir) / 'System32' / 'Npcap', Path(windir) / 'System32' / 'Npcap' / 'wpcap.dll'):
            if candidate.exists():
                npcap = str(candidate); break
    tools['npcap'] = npcap
    help_urls = {'ffmpeg': 'https://ffmpeg.org/download.html', 'ffprobe': 'https://ffmpeg.org/download.html',
                 'tshark': 'https://www.wireshark.org/download.html', 'npcap': 'https://npcap.com/#download',
                 'dotnet': 'https://dotnet.microsoft.com/download',
                 'ilspycmd': 'https://www.nuget.org/packages/ilspycmd (dotnet tool install --global ilspycmd)'}
    purposes = {'ffmpeg': 'gameplay video recording and clips', 'ffprobe': 'video evidence export',
                'tshark': 'packet capture (Wireshark command line)', 'npcap': 'packet capture driver',
                'dotnet': 'needed by ILSpy decompiler', 'ilspycmd': 'full C# decompile of client assemblies'}
    return {name: {'path': path, 'found': bool(path), 'purpose': purposes[name], 'get_it': help_urls[name]}
            for name, path in tools.items()}
