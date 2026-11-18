"""Ed25519 signatures for update packages and feed manifests (pure Python, RFC 8032).

Before v4.3.6 an update was only protected by a SHA-256 that travelled inside the
same manifest, so anyone able to replace the manifest could replace the payload.
Now the publisher signs the manifest with a private key that never ships, and
the app verifies it against the public key bundled at build time
(``update-public-key.txt``).

Verification is ~10-30 ms; this is the RFC 8032 reference algorithm, validated
against the RFC's test vectors in the test suite.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

P = 2 ** 255 - 19
L = 2 ** 252 + 27742317777372353535851937790883648493
D = -121665 * pow(121666, P - 2, P) % P
SQRT_M1 = pow(2, (P - 1) // 4, P)


def _sha512(data):
    return hashlib.sha512(data).digest()


def _inv(x):
    return pow(x, P - 2, P)


def _add(a, b):
    x1, y1, z1, t1 = a; x2, y2, z2, t2 = b
    A = (y1 - x1) * (y2 - x2) % P; B = (y1 + x1) * (y2 + x2) % P
    C = t1 * 2 * D * t2 % P; Dd = z1 * 2 * z2 % P
    E, F, G, H = B - A, Dd - C, Dd + C, B + A
    return (E * F % P, G * H % P, F * G % P, E * H % P)


def _mul(s, point):
    q = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            q = _add(q, point)
        point = _add(point, point); s >>= 1
    return q


def _equal(a, b):
    x1, y1, z1, _ = a; x2, y2, z2, _ = b
    return (x1 * z2 - x2 * z1) % P == 0 and (y1 * z2 - y2 * z1) % P == 0


def _recover_x(y, sign):
    if y >= P:
        return None
    x2 = (y * y - 1) * _inv(D * y * y + 1)
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (P + 3) // 8, P)
    if (x * x - x2) % P != 0:
        x = x * SQRT_M1 % P
    if (x * x - x2) % P != 0:
        return None
    if (x & 1) != sign:
        x = P - x
    return x


_GY = 4 * _inv(5) % P
_GX = _recover_x(_GY, 0)
G = (_GX, _GY, 1, _GX * _GY % P)


def _compress(point):
    x, y, z, _ = point
    zi = _inv(z); x = x * zi % P; y = y * zi % P
    return int.to_bytes(y | ((x & 1) << 255), 32, 'little')


def _decompress(data):
    if len(data) != 32:
        return None
    y = int.from_bytes(data, 'little'); sign = y >> 255; y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    return None if x is None else (x, y, 1, x * y % P)


def _expand(secret):
    if len(secret) != 32:
        raise ValueError('Ed25519 secret key must be 32 bytes')
    h = _sha512(secret)
    a = int.from_bytes(h[:32], 'little')
    a &= (1 << 254) - 8; a |= 1 << 254
    return a, h[32:]


def public_key(secret):
    a, _ = _expand(secret)
    return _compress(_mul(a, G))


def sign(secret, message):
    a, prefix = _expand(secret)
    A = _compress(_mul(a, G))
    r = int.from_bytes(_sha512(prefix + message), 'little') % L
    R = _compress(_mul(r, G))
    h = int.from_bytes(_sha512(R + A + message), 'little') % L
    s = (r + h * a) % L
    return R + int.to_bytes(s, 32, 'little')


def verify(public, message, signature):
    if len(public) != 32 or len(signature) != 64:
        return False
    A = _decompress(public)
    R = _decompress(signature[:32])
    if A is None or R is None:
        return False
    s = int.from_bytes(signature[32:], 'little')
    if s >= L:
        return False
    h = int.from_bytes(_sha512(signature[:32] + public + message), 'little') % L
    return _equal(_mul(s, G), _add(R, _mul(h, A)))


# --------------------------------------------------------- package helpers

def canonical(manifest):
    """Bytes that are signed: the manifest without its signature, canonical JSON."""
    data = {k: v for k, v in manifest.items() if k != 'signature'}
    return json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def generate_keypair():
    secret = os.urandom(32)
    return secret, public_key(secret)


def bundled_public_key():
    """Public key embedded in the build (hex text file), or None when unsigned builds."""
    try:
        from workbench_db import bundled_path
        path = bundled_path('update-public-key.txt')
        text = path.read_text(encoding='utf-8').strip() if path.is_file() else ''
    except Exception:
        text = ''
    if not text:
        return None
    key = bytes.fromhex(text.split()[0])
    if len(key) != 32:
        raise ValueError('update-public-key.txt must hold a 32-byte hex Ed25519 public key')
    return key


def sign_manifest(manifest, secret):
    signed = dict(manifest)
    signed['signature'] = {'alg': 'ed25519', 'public_key': public_key(secret).hex(),
                           'value': sign(secret, canonical(manifest)).hex()}
    return signed


def verify_manifest(manifest, public):
    sig = manifest.get('signature') if isinstance(manifest, dict) else None
    if not isinstance(sig, dict) or sig.get('alg') != 'ed25519':
        return False
    try:
        value = bytes.fromhex(sig.get('value', ''))
    except ValueError:
        return False
    return verify(public, canonical(manifest), value)


def load_secret(path):
    text = Path(path).read_text(encoding='utf-8').strip()
    secret = bytes.fromhex(text.split()[0])
    if len(secret) != 32:
        raise ValueError('Signing key file must contain a 32-byte hex secret')
    return secret
