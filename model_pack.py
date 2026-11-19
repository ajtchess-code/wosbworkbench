"""Model packs for the 3D battle simulator and wiki: real meshes + their textures.

A pack is a folder of small JSONP scripts so it loads both from a web host and
from file:// (WebGL can't use file:// images directly, so textures are embedded
as data URIs):

    models/<model>.js    WOSB_MODEL("<model>", {...})   quantized mesh groups
    textures/<name>.js   WOSB_TEX("<name>", "data:image/webp;base64,...")
    index.js             WOSB_PACK({...})                what the pack contains

Sources are the recovered OBJ files (Full Recovery) and textures, either the
recovered PNGs or the game's own texture XNBs (decoded with xnb_images).
"""
from __future__ import annotations

import base64
import io
import json
import math
import re
import struct
from array import array
from pathlib import Path

SHIP_SKIP = re.compile(r'Connection\w*Control|AverageBox|ShipMin|ShipLowCorpus|Shape|Hitbox|externalHitbox|^SPAWN_|Collision|Dummy|Lod\d', re.I)
SHIP_LOW_SKIP = re.compile(r'Connection\w*Control|AverageBox|DeckStuff|ShipMin|^ShipCorpus$|Shape|Hitbox|externalHitbox|^SPAWN_|Collision|Dummy', re.I)
WORLD_SKIP = re.compile(r'shape|hitbox|collision|dummy|^SPAWN_|^ConnectionNpc', re.I)


PACK_FORMAT = 2   # 2: terrain groups, environment textures
TERRAIN_MAT = re.compile(r'^TERRAIN\d+$', re.I)
# Terrain materials are drawn by the game's terrain shader from up to three ground textures. The material-to-texture
# table isn't recoverable as plain data, so the simulator blends the game's own ground textures by height and
# slope, picking the set from the island's family (snow/ice, sand/gold, green).
TERRAIN_SETS = {
    'snow': ('SnowGrassLand1', 'SnowGrass', 'GrassRock1'),
    'sand': ('SandDirty', 'GrassLand2', 'GrassRock1'),
    'green': ('SandDirty', 'Grass1', 'GrassRock1'),
}
ENV_TEXTURES = {'water_normal': 'term', 'foam': 'foam_hlsl', 'foam_mask': 'foam_intensivity', 'water': 'Water'}


def terrain_set(model_name):
    n = model_name.lower()
    if re.search(r'snow|show|ice|north|winter|frost', n):
        return 'snow'
    if re.search(r'sand|gold|yel|asia|desert|vulcan|dirt', n):
        return 'sand'
    return 'green'


def _kind(mesh, material):
    if TERRAIN_MAT.match(material or ''):
        return 'terrain'
    m = (mesh + ' ' + material).lower()
    if 'sail' in m:
        return 'sail'
    if 'flag' in m or 'vimpel' in m:
        return 'flag'
    if 'mast' in m or 'rotateframe' in m or 'vants' in m:
        return 'mast'
    if 'corpus' in m or 'hull' in m:
        return 'hull'
    return 'other'


def read_obj(path, *, skip=None):
    """{(mesh, material): (positions[], uvs[], faces[])} with per-group re-indexed vertices."""
    V, T = [], []
    groups = {}
    cur = None; mesh = 'mesh'; mat = 'default'; skipping = False
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            c = line[:2]
            if c == 'v ':
                p = line.split(); V.append((float(p[1]), float(p[2]), float(p[3])))
            elif c == 'vt':
                p = line.split(); T.append((float(p[1]), float(p[2])))
            elif c == 'o ':
                mesh = re.sub(r'_part\d+$', '', line[2:].strip()); mesh = re.sub(r'^\d+_', '', mesh)
                skipping = bool(skip and skip.search(mesh)); cur = None
            elif line.startswith('usemtl'):
                mat = line.split(None, 1)[1].strip() if len(line.split()) > 1 else 'default'; cur = None
            elif c == 'f ':
                if skipping:
                    continue
                if cur is None:
                    cur = groups.setdefault((mesh, mat), ({}, [], [], []))
                lut, pos, uv, idx = cur
                for tok in line.split()[1:4]:
                    a = tok.split('/')
                    vi = int(a[0]) - 1; ti = int(a[1]) - 1 if len(a) > 1 and a[1] else -1
                    key = (vi, ti)
                    k = lut.get(key)
                    if k is None:
                        k = lut[key] = len(pos) // 3
                        pos.extend(V[vi]); uv.extend(T[ti] if 0 <= ti < len(T) else (0.0, 0.0))
                    idx.append(k)
    return {k: (g[1], g[2], g[3]) for k, g in groups.items() if g[3]}


def _normals(pos, idx):
    n = [0.0] * len(pos)
    for i in range(0, len(idx), 3):
        a, b, c = idx[i] * 3, idx[i + 1] * 3, idx[i + 2] * 3
        ux, uy, uz = pos[b] - pos[a], pos[b + 1] - pos[a + 1], pos[b + 2] - pos[a + 2]
        vx, vy, vz = pos[c] - pos[a], pos[c + 1] - pos[a + 1], pos[c + 2] - pos[a + 2]
        nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
        for j in (a, b, c):
            n[j] += nx; n[j + 1] += ny; n[j + 2] += nz
    out = array('b')
    for i in range(0, len(n), 3):
        l = math.sqrt(n[i] ** 2 + n[i + 1] ** 2 + n[i + 2] ** 2) or 1.0
        out.extend((round(n[i] / l * 127), round(n[i + 1] / l * 127), round(n[i + 2] / l * 127)))
    return out


def _b64(arr):
    return base64.b64encode(arr.tobytes()).decode('ascii')


def _decimate(pos, uv, idx, max_tris):
    """Vertex clustering for very heavy world meshes (keeps first vertex's UV per cell)."""
    if len(idx) // 3 <= max_tris:
        return pos, uv, idx
    xs, ys, zs = pos[0::3], pos[1::3], pos[2::3]
    span = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)) or 1
    cell = span / 40
    for _ in range(12):
        cells, remap, npos, nuv = {}, [], [], []
        for i in range(len(xs)):
            key = (int(xs[i] // cell), int(ys[i] // cell), int(zs[i] // cell))
            k = cells.get(key)
            if k is None:
                k = cells[key] = len(npos) // 3; npos.extend((xs[i], ys[i], zs[i])); nuv.extend(uv[i * 2:i * 2 + 2])
            remap.append(k)
        nidx = []
        for i in range(0, len(idx), 3):
            a, b, c = remap[idx[i]], remap[idx[i + 1]], remap[idx[i + 2]]
            if a != b and b != c and a != c:
                nidx.extend((a, b, c))
        if len(nidx) // 3 <= max_tris:
            return npos, nuv, nidx
        cell *= 1.4
    return npos, nuv, nidx


def pack_model(obj_path, *, kind='ship', lod='high', max_tris=60000):
    skip = (SHIP_LOW_SKIP if lod == 'low' else SHIP_SKIP) if kind == 'ship' else WORLD_SKIP
    groups = read_obj(obj_path, skip=skip)
    if kind == 'ship' and lod == 'low' and not any(m == 'ShipLowCorpus' for m, _ in groups):
        groups = read_obj(obj_path, skip=SHIP_SKIP)           # model has no low hull: use the full one
    allp = [v for g in groups.values() for v in g[0]]
    if not allp:
        raise ValueError('no renderable meshes')
    mn = [min(allp[i::3]) for i in range(3)]; mx = [max(allp[i::3]) for i in range(3)]
    sc = [(mx[i] - mn[i]) / 65534 or 1e-6 for i in range(3)]
    total = sum(len(g[2]) // 3 for g in groups.values())
    out = []
    for (mesh, mat), (pos, uv, idx) in sorted(groups.items()):
        if kind != 'ship' and total > max_tris:
            pos, uv, idx = _decimate(pos, uv, idx, max(500, int(max_tris * len(idx) / 3 / total)))
            if not idx:
                continue
        q = array('h', (int(round((pos[i] - mn[i % 3]) / sc[i % 3])) - 32767 for i in range(len(pos))))
        ia = array('H' if len(pos) // 3 < 65536 else 'I', idx)
        us, vs = uv[0::2] or [0.0], uv[1::2] or [0.0]
        umin = [min(us), min(vs)]; usc = [(max(us) - umin[0]) / 65534 or 1e-6, (max(vs) - umin[1]) / 65534 or 1e-6]
        uq = array('h', (int(round((uv[i] - umin[i % 2]) / usc[i % 2])) - 32767 for i in range(len(uv))))
        out.append({'mesh': mesh, 'mat': mat, 'kind': _kind(mesh, mat), 'n': len(idx) // 3,
                    'p': _b64(q), 'nr': _b64(_normals(pos, idx)), 'uq': _b64(uq), 'umin': umin, 'usc': usc,
                    'i': _b64(ia), 'i32': ia.typecode == 'I'})
    return {'min': mn, 'scale': sc, 'bounds': [mn, mx], 'groups': out, 'tris': sum(g['n'] for g in out)}


class TextureIndex:
    """Material name → texture file, from recovered PNG folders and/or game texture XNB folders."""
    def __init__(self, roots):
        self.files = {}
        for root in roots or []:
            root = Path(root)
            if not root.is_dir():
                continue
            for f in root.rglob('*'):
                if f.suffix.lower() not in ('.png', '.xnb') or f.name.lower().endswith('.material.xnb'):
                    continue
                self.files.setdefault(f.stem.lower(), []).append(f)

    @staticmethod
    def _rank(p):
        s = p.as_posix().lower()
        return (('/lod0/' not in s), ('/public' in s), ('_dark' in s or '_grey' in s or '_red' in s), p.suffix.lower() != '.png', len(s))

    def find(self, material):
        m = material.lower()
        if m in self.files:
            return sorted(self.files[m], key=self._rank)[0]
        pref = [p for k, ps in self.files.items() if k.startswith(m + '_') for p in ps]
        if pref:
            return sorted(pref, key=lambda p: (len(p.stem),) + self._rank(p) + (p.name.lower(),))[0]
        return None


def encode_texture(path, *, max_size=1024):
    from PIL import Image
    if path.suffix.lower() == '.xnb':
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent / 'engine'))
        from xnb_images import texture
        im = texture(path.read_bytes())[0]
    else:
        im = Image.open(path)
    im = im.convert('RGBA')
    if max(im.size) > max_size:
        r = max_size / max(im.size); im = im.resize((max(1, int(im.width * r)), max(1, int(im.height * r))), Image.LANCZOS)
    alpha = im.getchannel('A').getextrema()[0] < 250
    buf = io.BytesIO()
    if alpha:
        im.save(buf, 'WEBP', quality=82, method=4)
    else:
        im.convert('RGB').save(buf, 'WEBP', quality=80, method=4)
    return 'data:image/webp;base64,' + base64.b64encode(buf.getvalue()).decode('ascii'), alpha


def _jsonp(fn, name, payload):
    return f'{fn}({json.dumps(name)},{json.dumps(payload, separators=(",", ":"))});\n'


def _old_index(out):
    try:
        txt = (out / 'index.js').read_text(encoding='utf-8')
        return json.loads(txt[txt.index('(') + 1:txt.rindex(')')])
    except (OSError, ValueError):
        return {}


def build_pack(out_dir, models, *, texture_roots=(), lod='high', tex_size=1024, progress=None, incremental=True):
    """models: {model name: (obj path, kind)} with kind 'ship' | 'world'. Returns the pack index.

    With incremental=True a model whose pack file is newer than its OBJ (same LOD) is kept as is.
    """
    out = Path(out_dir); (out / 'models').mkdir(parents=True, exist_ok=True); (out / 'textures').mkdir(exist_ok=True)
    texidx = TextureIndex(texture_roots)
    old = _old_index(out) if incremental else {}
    same = old.get('lod') == lod and old.get('tex_size') == tex_size and old.get('format') == PACK_FORMAT
    index = {'models': {}, 'textures': dict(old.get('textures', {})) if same else {}, 'lod': lod, 'tex_size': tex_size, 'format': PACK_FORMAT}
    done_tex = {k: v for k, v in index['textures'].items() if (out / v['file']).is_file()}

    def _add_tex(material, *, size=None):
        key = material.lower()
        if key in done_tex:
            return done_tex[key]
        src = texidx.find(material)
        done_tex[key] = None
        if src:
            try:
                uri, alpha = encode_texture(src, max_size=size or tex_size)
                safe = re.sub(r'[^a-z0-9_.-]', '_', key)
                (out / 'textures' / f'{safe}.js').write_text(_jsonp('WOSB_TEX', key, uri), encoding='utf-8')
                done_tex[key] = {'file': f'textures/{safe}.js', 'alpha': alpha}
                index['textures'][key] = done_tex[key]
            except Exception:
                pass
        return done_tex[key]

    index['env'] = {}
    for role, tex in ENV_TEXTURES.items():
        if _add_tex(tex, size=512):
            index['env'][role] = tex.lower()
    for set_ in TERRAIN_SETS.values():
        for t in set_:
            _add_tex(t)
    for i, (name, (obj, kind)) in enumerate(sorted(models.items())):
        if progress:
            progress(i, len(models), name)
        prev = old.get('models', {}).get(name) if same else None
        target = out / 'models' / f'{name}.js'
        if prev and prev.get('file') and target.is_file() and target.stat().st_mtime >= Path(obj).stat().st_mtime:
            index['models'][name] = prev
            continue
        try:
            m = pack_model(obj, kind=kind, lod=lod)
        except (OSError, ValueError) as exc:
            index['models'][name] = {'error': type(exc).__name__}
            continue
        for g in m['groups']:
            if g['kind'] == 'terrain':
                g['terrain'] = [t.lower() for t in TERRAIN_SETS[terrain_set(name)]]
                for t in TERRAIN_SETS[terrain_set(name)]:
                    _add_tex(t)
                g['tex'] = None
                continue
            key = g['mat'].lower()
            _add_tex(g['mat'])
            g['tex'] = key if done_tex.get(key) else None
        (out / 'models' / f'{name}.js').write_text(_jsonp('WOSB_MODEL', name, m), encoding='utf-8')
        index['models'][name] = {'file': f'models/{name}.js', 'tris': m['tris'], 'kind': kind,
                                 'textured': sum(1 for g in m['groups'] if g['tex']), 'groups': len(m['groups'])}
    (out / 'index.js').write_text(f'WOSB_PACK({json.dumps(index, separators=(",", ":"))});\n', encoding='utf-8')
    return index


def collect_models(recovery_dir, *, ship_models=(), world_models=()):
    """Find recovered OBJs for the wanted model names under a Full Recovery folder."""
    found = {}
    root = Path(recovery_dir) if recovery_dir else None
    if not root or not root.is_dir():
        return found
    want_s = {m.lower(): m for m in ship_models}; want_w = {m.lower(): m for m in world_models}
    for obj in root.rglob('*.obj'):
        k = obj.stem.lower()
        if k in want_s and want_s[k] not in found:
            found[want_s[k]] = (obj, 'ship')
        elif k in want_w and want_w[k] not in found:
            found[want_w[k]] = (obj, 'world')
    return found
