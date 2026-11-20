"""World data for the wiki's port pages and world map: ports, shallow waters, trade routes and what is near each port.

Shallow waters follow the game's own rules. The world's shallows image (``map_levels``) is read colour by colour:
red 2, orange 3, yellow 4, lime 5, blue 6, white 10, black 0. A ship may enter a cell only if its rank number is at
least that value, so "4" means rank 4 and smaller ships (ranks 4–7); 0 is open to every ship and 10 to none.
The grid spans the world (14,146.483 × 17,290.12 units), with rows following X and columns following Y.

Trade routes are typed the way the game types them. A route of 6,000 or more is Central. Otherwise each end is matched
to the nearest port (Main), trading post at sea (Coastal) or resource node (Supply). Port to port is Main, or Smuggling
when a pirate bay is at either end; otherwise any Supply end makes it Supply, then any Coastal end makes it Coastal.
Main routes carry the end ports' own produce and Supply routes the nodes' output. Coastal routes carry two goods from
the nearby port's trade list, which changes, so the wiki says "varies".
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

WORLD_SIZE = (14146.483, 17290.12)
SHALLOW_COLOURS = {(255, 0, 0): 2, (255, 165, 0): 3, (255, 255, 0): 4, (0, 255, 0): 5, (0, 0, 255): 6, (255, 255, 255): 10, (0, 0, 0): 0}
SHALLOW_TINT = {2: (220, 40, 40), 3: (240, 140, 30), 4: (235, 210, 40), 5: (90, 200, 90), 6: (60, 110, 230)}
CENTRAL_LENGTH = 6000.0
NODE_OUTPUT = {'wood': ('Lumber mill', 'Wood'), 'iron': ('Iron mine', 'Iron Ore'), 'coal': ('Coal mine', 'Coal'), 'ice': ('Ice field', 'Water'),
               'farm': ('Farm', 'Animals'), 'rum': ('Rum distillery', 'Rum'), 'resin': ('Pitch works', 'Pitch'), 'copper': ('Copper mine', 'Copper Ore'),
               'mhidden': ('Underground print shop', 'Battle Mark')}
PRODUCE = {'TCoal': 'Coal', 'TWoodID': 'Wood', 'TCottonID': 'Cotton', 'TRumID': 'Rum', 'TResinLaquer': 'Pitch', 'TWater': 'Water', 'TCopper': 'Copper'}
FLAG_TEXT = {
    'StartPort': 'Starting port: new captains can begin here.',
    'UnitsSamurai': 'Hires Samurai boarding crews.', 'UnitsMusketeer': 'Hires Musketeer crews.', 'UnitsFisher': 'Hires Fisher crews.',
    'NearIce': 'In the cold northern waters, near the ice.', 'Arab': 'One of the Arab ports of the south-east.',
    'OnlyPirateFlag': 'Only ships flying the pirate flag may enter.', 'Stronghold': 'A pirate stronghold.',
    'CaptureWithoutWindow': 'Can be attacked at any time, without a scheduled port-battle window.',
}
TYPE_TEXT = {'City': 'City', 'Bay': 'Bay', 'NeutralBay': 'Neutral bay', 'PirateBay': 'Pirate bay'}
ROUTE_TEXT = {
    'Main': 'Main route: port to port, carrying the two ports\' own produce.',
    'Smuggling': 'Smuggling route: port to port with a pirate bay at one end. No fixed cargo.',
    'Supply': 'Supply route: to or from a resource node, carrying what it produces.',
    'Coastal': 'Coastal route: to or from a trading post at sea. Two goods from the nearby port\'s trade list, which change.',
    'Central': 'Central route: a long crossing (6,000+) through the middle seas. No fixed cargo.',
}


def rank_text(v):
    if not v:
        return 'any ship'
    if v >= 10:
        return 'no ships'
    return f'rank {v} and smaller ships (ranks {v}–7)' if v < 7 else 'rank 7 ships only'


class Shallows:
    """The game's shallow-water grid. ``get(x, y)`` gives the lowest rank number allowed at a world position."""

    def __init__(self, grid):
        self.grid = grid; self.h = len(grid); self.w = len(grid[0]) if grid else 0

    @classmethod
    def from_image(cls, im, *, tolerance=60):
        """Map every pixel to the nearest shallows colour. Returns None unless almost all pixels are shallows colours."""
        im = im.convert('RGB'); w, h = im.size
        px = im.load(); cols = list(SHALLOW_COLOURS.items()); grid = []; off = 0
        cache = {}
        for r in range(h):
            row = []
            for c in range(w):
                p = px[c, r]
                v = cache.get(p)
                if v is None:
                    (col, val) = min(cols, key=lambda kv: sum((a - b) ** 2 for a, b in zip(kv[0], p)))
                    d = math.sqrt(sum((a - b) ** 2 for a, b in zip(col, p)))
                    v = cache[p] = (val, d > tolerance)
                row.append(v[0]); off += v[1]
            grid.append(row)
        return cls(grid) if off <= 0.02 * w * h else None

    def cell(self, x, y):
        r = int((x / WORLD_SIZE[0] + 0.5) * self.h); c = int((y / WORLD_SIZE[1] + 0.5) * self.w)
        return min(self.h - 1, max(0, r)), min(self.w - 1, max(0, c))

    def get(self, x, y):
        r, c = self.cell(x, y)
        return self.grid[r][c]

    def around(self, x, y, radius):
        """Strictest value within ``radius`` of a point (land, 10, is ignored)."""
        best = 0; step = max(WORLD_SIZE[0] / self.h, WORLD_SIZE[1] / self.w)
        n = max(1, int(radius / step))
        for i in range(-n, n + 1):
            for j in range(-n, n + 1):
                if (i * step) ** 2 + (j * step) ** 2 <= radius ** 2:
                    v = self.get(x + i * step, y + j * step)
                    if v < 10:
                        best = max(best, v)
        return best


def find_shallows(roots):
    """Look for the shallows image (map_levels) among texture/catalog folders; decode XNB if needed."""
    from PIL import Image
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        for name in ('map_levels.png', 'map_levels.xnb'):
            for f in list(root.glob(name)) + list(root.glob('**/' + name))[:2]:
                try:
                    if f.suffix.lower() == '.xnb':
                        import sys
                        sys.path.insert(0, str(Path(__file__).resolve().parent / 'engine'))
                        from xnb_images import texture
                        im = texture(f.read_bytes())[0]
                    else:
                        im = Image.open(f)
                    sh = Shallows.from_image(im)
                    if sh:
                        return sh
                except Exception:
                    continue
    return None


def _records(db, dataset, build):
    rows = db.conn.execute('SELECT raw_json, source_root FROM records WHERE dataset=?', (dataset,)).fetchall()
    roots = {r for _, r in rows}
    pick = build if build in roots else ('Game' if 'Game' in roots else next(iter(roots), None))
    return [json.loads(raw) for raw, root in rows if root == pick]


def _texts(db):
    out = {}
    for raw, in db.conn.execute("SELECT raw_json FROM records WHERE dataset='English_Text'"):
        d = json.loads(raw); k = str(d.get('Key', ''))
        if k.startswith('fraction_'):
            out[k] = d.get('English') or ''
    return out


FACTIONS = {}          # filled from the game's text by load()


def faction_name(key, texts=None):
    if not key:
        return ''
    return (texts or {}).get('fraction_' + key) or FACTIONS.get('fraction_' + key) or re.sub(r'And', ' & ', re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', key)).replace('  ', ' ')


def load(db, build='Steam', shallows=None):
    """Ports, towers, forts, trading posts, resource nodes and classified trade routes, in world coordinates (x, y)."""
    texts = _texts(db); FACTIONS.update(texts)
    defs = {}
    for d in _records(db, 'WorldPorts', build):
        defs.setdefault(d.get('PortName'), d)
    ports, towers, forts, posts, lights, nodes, altars = [], [], [], [], [], [], []
    for r in _records(db, 'Map_Objects', build):
        if r.get('SceneName') != 'World' or r.get('Position0') is None:
            continue
        x, y = float(r['Position0']), float(r['Position1'])
        path = str(r.get('Path') or ''); model = path.split('\\')[-1]
        params = str(r.get('Parameters') or '').replace(',', ' ').split()
        name = next((t for t in params if t in defs), None)
        if path.startswith('ports\\') and name:
            d = defs[name]
            flags = [f for f in str(d.get('Flags') or '').split() if f]
            ports.append({'key': name, 'n': d.get('EnglishName') or d.get('PortNameEnglish') or name, 'x': x, 'y': y,
                          'type': d.get('Type') or '', 'faction': faction_name(d.get('LegalFraction'), texts), 'faction_key': d.get('LegalFraction') or '',
                          'produces': PRODUCE.get(d.get('ProducedResourceId') or '', re.sub(r'^T|ID$', '', d.get('ProducedResourceId') or '')),
                          'flags': flags, 'ranks': d.get('BuildShipRangs'), 'fixed_level': d.get('FixedLevel') or 0,
                          'pb_limit': d.get('PbsTeamLimitation') or ''})
        elif path.startswith('ports\\'):
            (lights if 'pharos' in model else posts).append({'x': x, 'y': y, 'n': 'Lighthouse' if 'pharos' in model else 'Fishing village' if 'fishing' in model else 'Trading post'})
        elif 'worldfort' in path:
            m = re.search(r'worldfort(\d)', path)
            forts.append({'x': x, 'y': y, 'n': f'Imperial fort, type {m.group(1)}' if m else 'Imperial fort'})
        elif 'special\\towers\\t_' in path:
            towers.append({'x': x, 'y': y, 'n': {'t_mortar': 'Mortar tower', 't_fire': 'Prometheus tower'}.get(re.sub(r'\d+$', '', model), 'Cannon tower')})
        elif path.startswith('buildings\\factory'):
            k = model.replace('factory_', '')
            label, res = NODE_OUTPUT.get(k, (k.replace('_', ' ').title(), k.replace('_', ' ').title()))
            nodes.append({'x': x, 'y': y, 'n': label, 'res': res})
        elif path.startswith('buildings\\altar'):
            altars.append({'x': x, 'y': y, 'n': 'Altar'})
    routes = []
    for i, d in enumerate(_records(db, 'TradingRoutesInfo', build)):
        try:
            pts = [tuple(map(float, p.split())) for p in d.get('Value') or []]
        except (ValueError, TypeError):
            continue
        if len(pts) > 2:
            routes.append(classify(i, pts, ports, posts, nodes, shallows))
    return {'ports': ports, 'towers': towers, 'forts': forts, 'posts': posts, 'lights': lights, 'nodes': nodes, 'altars': altars, 'routes': routes}


def _nearest(p, items):
    best, bd = None, float('inf')
    for it in items:
        d = math.hypot(it['x'] - p[0], it['y'] - p[1])
        if d < bd:
            best, bd = it, d
    return best, bd


def classify(i, pts, ports, posts, nodes, shallows=None):
    length = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))
    ends = []
    for p in (pts[0], pts[-1]):
        port, dp = _nearest(p, ports); post, dc = _nearest(p, posts); node, dn = _nearest(p, nodes)
        kind = min([('Main', dp, port), ('Coastal', dc, post), ('Supply', dn, node)], key=lambda t: t[1])
        ends.append({'kind': kind[0], 'item': kind[2], 'port': port})
    k1, k2 = ends[0]['kind'], ends[1]['kind']
    if length >= CENTRAL_LENGTH:
        kind = 'Central'
    elif k1 == 'Main' and k2 == 'Main':
        kind = 'Smuggling' if any(e['item'] and e['item']['type'] == 'PirateBay' for e in ends) else 'Main'
    elif 'Supply' in (k1, k2):
        kind = 'Supply'
    else:
        kind = 'Coastal'
    cargo = []
    if kind == 'Main':
        cargo = sorted({e['item']['produces'] for e in ends if e['item'] and e['item'].get('produces')})
    elif kind == 'Supply':
        cargo = sorted({e['item']['res'] for e in ends if e['kind'] == 'Supply' and e['item']})
    elif kind == 'Coastal':
        cargo = ['varies']
    start, end = ends[0]['port'], ends[1]['port']        # the game names each end after its nearest port
    deep = max((shallows.get(*p) for p in pts if shallows.get(*p) < 10), default=0) if shallows else None
    return {'id': i, 'pts': pts, 'type': kind, 'from': start['n'] if start else '', 'to': end['n'] if end else '',
            'cargo': cargo, 'length': round(length), 'loop': math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) < 100, 'shallow': deep}


def near(items, x, y, radius):
    return [it for it in items if math.hypot(it['x'] - x, it['y'] - y) <= radius]


def shallows_overlay(sh, size, uv_to_world):
    """RGBA image (size = (w, h)) tinting restricted waters on the world map image."""
    from PIL import Image
    w, h = size
    im = Image.new('RGBA', size, (0, 0, 0, 0)); px = im.load()
    for j in range(h):
        for i in range(w):
            x, y = uv_to_world((i + 0.5) / w, (j + 0.5) / h)
            v = sh.get(x, y)
            if v in SHALLOW_TINT:
                px[i, j] = SHALLOW_TINT[v] + (120,)
    return im
