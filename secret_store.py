"""Small secret storage for the GitHub access token (private release repos).

Windows: encrypted with DPAPI (CryptProtectData), so only this Windows user on
this machine can decrypt it. Elsewhere: a file readable only by the user.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path


def _path(name):
    from workbench_db import home
    return home() / 'secrets' / (name + '.bin')


def _dpapi(data: bytes, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]
    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = BLOB()
    crypt32 = ctypes.windll.crypt32
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    ok = fn(ctypes.byref(blob_in), 'WoSB Workbench' if protect else None, None, None, None, 0x1, ctypes.byref(blob_out))
    if not ok:
        raise OSError('Windows could not ' + ('protect' if protect else 'unprotect') + ' the secret')
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def save(name, value):
    path = _path(name); path.parent.mkdir(parents=True, exist_ok=True)
    if not value:
        path.unlink(missing_ok=True); return
    raw = value.encode('utf-8')
    if os.name == 'nt':
        payload = b'DPAPI1' + _dpapi(raw, True)
    else:
        payload = b'PLAIN1' + base64.b64encode(raw)
    path.write_bytes(payload)
    if os.name != 'nt':
        os.chmod(path, 0o600)


def load(name):
    path = _path(name)
    try:
        data = path.read_bytes()
    except OSError:
        return ''
    try:
        if data.startswith(b'DPAPI1') and os.name == 'nt':
            return _dpapi(data[6:], False).decode('utf-8')
        if data.startswith(b'PLAIN1'):
            return base64.b64decode(data[6:]).decode('utf-8')
    except (OSError, ValueError):
        return ''
    return ''


def exists(name):
    return Path(_path(name)).is_file()
