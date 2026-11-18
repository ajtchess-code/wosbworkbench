"""Windows process helpers.

* hide_console_windows(): every child process started by this GUI app gets
  CREATE_NO_WINDOW unless it explicitly asked for a console. Without this, each
  background PowerShell/TShark/FFmpeg call flashed a console window.
* tcp_connections(): established TCP connections with owning PID, read directly
  from the IP Helper API (GetExtendedTcpTable). Used by the auto-capture watcher
  so it no longer starts PowerShell every few seconds.
"""
from __future__ import annotations

import os
import socket
import subprocess

CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_CONSOLE = 0x00000010
_patched = False


def hide_console_windows():
    """Idempotently make subprocess children windowless on Windows."""
    global _patched
    if os.name != 'nt' or _patched:
        return False
    original = subprocess.Popen.__init__

    def __init__(self, *args, **kwargs):
        flags = kwargs.get('creationflags', 0) or 0
        if len(args) < 13 and not flags & CREATE_NEW_CONSOLE:   # creationflags is positional #13
            kwargs['creationflags'] = flags | CREATE_NO_WINDOW
        original(self, *args, **kwargs)
    subprocess.Popen.__init__ = __init__
    _patched = True
    return True


def _windll():
    import ctypes
    return ctypes, ctypes.windll


def tcp_connections(*, established_only=True):
    """[(local_ip, local_port, remote_ip, remote_port, pid)] for IPv4 and IPv6."""
    if os.name != 'nt':
        raise OSError('Windows only')
    ctypes, windll = _windll()
    from ctypes import wintypes
    iphlpapi = windll.iphlpapi
    TCP_TABLE_OWNER_PID_ALL = 5
    ESTABLISHED = 5
    results = []

    class ROW4(ctypes.Structure):
        _fields_ = [('state', wintypes.DWORD), ('local_addr', wintypes.DWORD), ('local_port', wintypes.DWORD),
                    ('remote_addr', wintypes.DWORD), ('remote_port', wintypes.DWORD), ('pid', wintypes.DWORD)]

    class ROW6(ctypes.Structure):
        _fields_ = [('local_addr', ctypes.c_ubyte * 16), ('local_scope', wintypes.DWORD), ('local_port', wintypes.DWORD),
                    ('remote_addr', ctypes.c_ubyte * 16), ('remote_scope', wintypes.DWORD), ('remote_port', wintypes.DWORD),
                    ('state', wintypes.DWORD), ('pid', wintypes.DWORD)]

    for family, row_type in ((socket.AF_INET, ROW4), (socket.AF_INET6, ROW6)):
        size = wintypes.DWORD(0)
        iphlpapi.GetExtendedTcpTable(None, ctypes.byref(size), False, family, TCP_TABLE_OWNER_PID_ALL, 0)
        for _ in range(4):
            buf = ctypes.create_string_buffer(size.value + 4096)
            size = wintypes.DWORD(ctypes.sizeof(buf))
            rc = iphlpapi.GetExtendedTcpTable(buf, ctypes.byref(size), False, family, TCP_TABLE_OWNER_PID_ALL, 0)
            if rc == 0:
                break
            if rc != 122:   # ERROR_INSUFFICIENT_BUFFER: table grew, retry
                raise OSError(f'GetExtendedTcpTable failed ({rc})')
        else:
            continue
        count = ctypes.c_uint32.from_buffer(buf).value
        rows = (row_type * count).from_buffer(buf, 4 if family == socket.AF_INET else 4)
        for row in rows:
            if established_only and row.state != ESTABLISHED:
                continue
            lport = socket.ntohs(row.local_port & 0xffff); rport = socket.ntohs(row.remote_port & 0xffff)
            if family == socket.AF_INET:
                lip = socket.inet_ntoa(int(row.local_addr).to_bytes(4, 'little'))
                rip = socket.inet_ntoa(int(row.remote_addr).to_bytes(4, 'little'))
            else:
                lip = socket.inet_ntop(socket.AF_INET6, bytes(row.local_addr))
                rip = socket.inet_ntop(socket.AF_INET6, bytes(row.remote_addr))
            results.append((lip, lport, rip, rport, int(row.pid)))
    return results


def process_name(pid):
    """Executable name without extension (e.g. 'WorldOfSeaBattleClient'), or ''."""
    if os.name != 'nt' or not pid:
        return ''
    ctypes, windll = _windll()
    from ctypes import wintypes
    handle = windll.kernel32.OpenProcess(0x1000, False, int(pid))   # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ''
    try:
        buf = ctypes.create_unicode_buffer(1024); size = wintypes.DWORD(1024)
        if not windll.kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return ''
        name = os.path.basename(buf.value)
        return name[:-4] if name.lower().endswith('.exe') else name
    finally:
        windll.kernel32.CloseHandle(handle)


def game_connections(process='WorldOfSeaBattleClient', *, port=None):
    """Established connections owned by the game process, without remote addresses."""
    names = {}
    out = {}
    for _lip, _lport, _rip, rport, pid in tcp_connections():
        if port is not None and rport != int(port):
            continue
        if pid not in names:
            names[pid] = process_name(pid)
        if names[pid] == process:
            out[(pid, rport)] = {'confirmed': True, 'pid': pid, 'port': rport, 'process': process}
    return list(out.values())
