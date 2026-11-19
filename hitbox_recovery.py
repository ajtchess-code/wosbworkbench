"""Rebuild ship hitboxes from recovered models using the client's own rules.

Construction rules ported from your decompiled Common.dll:

* ``ShipStaticInfo`` ctor — the corpus (hull) hitbox is the bounding box of the
  hit mesh (the model's ``Hitbox`` mesh, or the separate ``*_externalHitbox``
  model when the ship has one); the same mesh is the triangle hitmesh.
* ``ShipStaticInfo.B()`` / ``ShapeHelper.Levels`` — each sail becomes 4
  horizontal slices ("levels") starting 1 unit below the deck line
  (corpus max Y − 1), X/Z scaled by 0.94; its weight is its share of the summed
  level-sphere radii.
* ``MastHitbox`` — mast box from the mast mesh bounds: Y from the deck to 55 %
  of the mast height (then ×0.8 at the top), X/Z a fixed 2.34 × 2.08 block near
  the mast foot.
* Node ids — 0 = corpus, then every sail (static, then animated), then masts.
  ``DamageData.CollisionNodeID`` refers to this table.

Which mesh is a sail or mast comes from the recovered mesh names
(``SailStatic`` / ``SailAnimated`` / ``MastFrame`` / ``Hitbox``). The client's
own grouping strings are obfuscated, so that name mapping and the exact sail
ordering inside each group are inferred, and flagged as such in the output.
Coordinates are model space; multiply by 0.3 for world metres-ish units.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

FORMAT = 'wosb-hitboxes-v1'
WORLD_SCALE = 0.3
LEVELS = 4
SAIL_XZ_SCALE = 0.94
SOURCE = 'Common.dll: ShipStaticInfo ctor/B(), ShapeHelper.Levels, MastHitbox, SailHitbox, CorpusHitbox'

PART_SUFFIX = re.compile(r'_part\d+$')
SAIL = re.compile(r'Sail(Static|Animated)', re.I)
MAST = re.compile(r'^MastFrame', re.I)
HITMESH = re.compile(r'^Hitbox$', re.I)


def read_groups(obj_path):
    """{mesh name: [(x, y, z), ...]} from a recovered OBJ (``o <Mesh>_partN`` groups)."""
    groups = {}; current = None
    with open(obj_path, encoding='utf-8', errors='replace') as fh:
        for line in fh:
            if line.startswith('o '):
                current = PART_SUFFIX.sub('', line[2:].strip())
                groups.setdefault(current, [])
            elif line.startswith('v ') and current is not None:
                parts = line.split()
                try:
                    groups[current].append((float(parts[1]), float(parts[2]), float(parts[3])))
                except (IndexError, ValueError):
                    continue
    return {k: v for k, v in groups.items() if v}


def _bounds(points):
    xs, ys, zs = zip(*points)
    return [min(xs), min(ys), min(zs)], [max(xs), max(ys), max(zs)]


def _box(lo, hi, scale=(1.0, 1.0, 1.0)):
    """BoxShape(BoundingBox, scale): extents scaled about the centre."""
    c = [(a + b) / 2 for a, b in zip(lo, hi)]
    half = [(b - a) / 2 * s for a, b, s in zip(lo, hi, scale)]
    return {'min': [c[i] - half[i] for i in range(3)], 'max': [c[i] + half[i] for i in range(3)]}


def _radius(box):
    return math.dist(box['min'], box['max']) / 2


def sail_levels(points, min_y, levels=LEVELS, scale=SAIL_XZ_SCALE):
    """ShapeHelper.Levels(minY, 4, 1, sail, 0.94): per-slice vertex bounds, clamped at minY."""
    lo, hi = _bounds(points)
    step = (hi[1] - lo[1]) / levels
    slices = [[[math.inf] * 3, [-math.inf] * 3] for _ in range(levels)]
    for p in points:
        for k in range(levels):
            if lo[1] + k * step < p[1] < lo[1] + (k + 1) * step:
                s = slices[k]
                for a in range(3):
                    s[0][a] = min(s[0][a], p[a]); s[1][a] = max(s[1][a], p[a])
    boxes = []
    for k, (smin, smax) in enumerate(slices):
        if not all(math.isfinite(v) for v in smin + smax):
            boxes.append(None); continue
        y0 = max(min_y, lo[1] + k * step)
        y1 = max(lo[1] + (k + 1) * step, y0)
        boxes.append(_box([smin[0], y0, smin[2]], [smax[0], y1, smax[2]], (scale, 1.0, scale)))
    real = [b for b in boxes if b]
    common = ({'min': [min(b['min'][a] for b in real) for a in range(3)],
               'max': [max(b['max'][a] for b in real) for a in range(3)]} if real else None)
    return boxes, common


def mast_box(points, corpus_max_y):
    """ShipStaticInfo.B() mast bounds + MastHitbox ctor reshaping."""
    lo, hi = _bounds(points)
    lo[1] = corpus_max_y
    hi[1] = (hi[1] - lo[1]) * 0.55 + lo[1]
    num = 1.3
    x = hi[0] * 0.8 + lo[0] * 0.2
    lo[0], hi[0] = x - num * 1.6, x + num * 0.2
    lo[2], hi[2] = -num * 0.8, num * 0.8
    hi[1] *= 0.8
    return {'min': lo, 'max': hi}


def _sail_order_key(name):
    # SortTop(-A(MeshName)): A() is obfuscated; the leading mast-group digit is the best evidence we have.
    m = re.match(r'^(\d+)_', name)
    return -(int(m.group(1)) if m else 0)


def build(obj_path, external_hitbox=None):
    groups = read_groups(obj_path)
    notes = []
    hit_points = None; hit_source = None
    if external_hitbox and Path(external_hitbox).is_file():
        ext = read_groups(external_hitbox)
        hit_points = [p for name, pts in ext.items() for p in pts]
        hit_source = Path(external_hitbox).name
    if not hit_points:
        named = [pts for name, pts in groups.items() if HITMESH.match(name)]
        if named:
            hit_points = [p for pts in named for p in pts]; hit_source = 'Hitbox mesh'
    if not hit_points:
        corpus = [pts for name, pts in groups.items() if name == 'ShipCorpus']
        if not corpus:
            raise ValueError('No Hitbox or ShipCorpus mesh in ' + str(obj_path))
        hit_points = [p for pts in corpus for p in pts]; hit_source = 'ShipCorpus (fallback: no Hitbox mesh)'
        notes.append('No Hitbox mesh: corpus box taken from ShipCorpus bounds, which is larger than the real hitbox.')
    clo, chi = _bounds(hit_points)
    corpus = {'min': clo, 'max': chi}
    static = sorted((n for n in groups if SAIL.search(n) and 'static' in n.casefold()), key=_sail_order_key)
    animated = sorted((n for n in groups if SAIL.search(n) and 'animated' in n.casefold()), key=_sail_order_key)
    sails = []
    for name in static + animated:
        levels, common = sail_levels(groups[name], chi[1] - 1.0)
        if common is None:
            notes.append(f'{name}: no vertices inside the level slices; skipped'); continue
        sails.append({'name': name, 'animated': name in animated, 'levels': levels, 'common': common,
                      'radius_sum': sum(_radius(b) for b in levels if b)})
    total = sum(s['radius_sum'] for s in sails)
    for i, s in enumerate(sails):
        s['strength_index'] = i
        s['weight'] = s['radius_sum'] / total if total else 0.0
        s['weight_mul'] = s['weight'] * len(sails)
    masts = [{'name': n, 'box': mast_box(groups[n], chi[1])} for n in sorted(n for n in groups if MAST.match(n))]
    table = [{'node_id': 0, 'type': 'Corpus', 'name': 'Corpus'}]
    table += [{'node_id': len(table) + i, 'type': 'Sail', 'name': s['name'], 'strength_index': s['strength_index']}
              for i, s in enumerate(sails)]
    base = len(table)
    table += [{'node_id': base + i, 'type': 'Mast', 'name': m['name']} for i, m in enumerate(masts)]
    if len(table) >= 255:
        notes.append('255+ hitboxes: the client throws for this ship')
    ports = gun_ports(obj_path)
    return {'format': FORMAT, 'model': Path(obj_path).name, 'hitmesh_source': hit_source, **ports,
            'world_scale': WORLD_SCALE, 'corpus': corpus,
            'corpus_half_extents_world': [(chi[a] - clo[a]) * WORLD_SCALE * 0.5 for a in range(3)],
            'deck_line_y': chi[1], 'sails': sails, 'masts': masts, 'node_table': table,
            'source': SOURCE,
            'confidence': {'construction_rules': 'ported from client code',
                           'mesh_role_mapping': 'inferred from recovered mesh names (client strings are obfuscated)',
                           'sail_order_within_group': 'inferred (leading mast-group digit)',
                           'damage_per_zone': 'not in client: HealthDamage comes from the server'},
            'notes': notes}


PORT_TYPES = {'CannonSidePoint': 'side', 'CannonNoLafetSidePoint': 'side', 'CannonTopPoint': 'bow', 'CannonBackPoint': 'stern',
              'Mortar': 'mortar', 'ExtraMort': 'mortar', 'Falkonet': 'swivel', 'FireGun': 'firegun'}


def gun_ports(obj_path):
    """Real gun ports and the figurehead mount from the model's hardpoints (saved next to the OBJ by recovery).

    Side ports are stored once per side in the model; the client mirrors left/right
    (ShipStaticInfo LeftSidePorts/RightSidePorts), so ports are mirrored across Z here.
    """
    report = Path(obj_path).with_suffix('.json')
    try:
        hps = json.loads(report.read_text(encoding='utf-8')).get('hardpoints') or []
    except (OSError, ValueError):
        hps = []
    ports = []; figure = None
    for h in hps:
        kind = PORT_TYPES.get(h.get('type'))
        if h.get('type') == 'BowFigurePlace':
            figure = h['position']
        if not kind:
            continue
        x, y, z = h['position']
        if kind == 'side':
            ports.append({'kind': 'side', 'side': 'left' if z < 0 else 'right', 'position': [x, y, z]})
            ports.append({'kind': 'side', 'side': 'right' if z < 0 else 'left', 'position': [x, y, -z], 'mirrored': True})
        else:
            ports.append({'kind': kind, 'side': kind, 'position': [x, y, z]})
    # Mirroring can duplicate ports the model already lists on both sides.
    seen = set(); unique = []
    for prt in ports:
        key = (prt['kind'], prt['side'], tuple(round(v, 2) for v in prt['position']))
        if key not in seen:
            seen.add(key); unique.append(prt)
    counts = {}
    for prt in unique:
        counts[prt['side']] = counts.get(prt['side'], 0) + 1
    return {'gun_ports': unique, 'port_counts': counts, 'figurehead_mount': figure,
            'ports_source': 'model hardpoints' if hps else 'not available (re-run Full Recovery with 4.5+)'}


def zones_for_viewer(result, *, include_levels=True):
    """Ship 3D overlay zones (ship_viewer.validate_zones format)."""
    def zone(name, box, cls, note):
        size = [max(1e-3, box['max'][a] - box['min'][a]) for a in range(3)]
        center = [(box['max'][a] + box['min'][a]) / 2 for a in range(3)]
        return {'name': name, 'shape': 'box', 'center': center, 'size': size, 'classification': cls,
                'evidence_status': 'candidate', 'source': SOURCE, 'damage_multiplier': None, 'notes': note}
    out = [zone('Corpus hitbox (node 0)', result['corpus'], 'hull', 'Bounds of ' + result['hitmesh_source'])]
    for s in result['sails']:
        node = 1 + s['strength_index']
        if include_levels:
            for k, b in enumerate(s['levels']):
                if b:
                    out.append(zone(f"Sail {s['name']} level {k + 1} (node {node})", b, 'sail',
                                    f"weight {s['weight']:.3f}; a ball passing 1/2/3 sails keeps 1/2, 1/3, 0 energy"))
        else:
            out.append(zone(f"Sail {s['name']} (node {node})", s['common'], 'sail', f"weight {s['weight']:.3f}"))
    for m, row in zip(result['masts'], [r for r in result['node_table'] if r['type'] == 'Mast']):
        out.append(zone(f"Mast {m['name']} (node {row['node_id']})", m['box'], 'mast', 'MastHitbox box rule'))
    return out[:400]


def batch(models_dir, out_dir, *, progress=None):
    """Hitboxes for every ``Ship_*.obj`` under ``models_dir`` (pairs ``*_externalHitbox.obj``)."""
    models_dir = Path(models_dir); out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    objs = sorted(p for p in models_dir.rglob('*.obj') if not p.stem.endswith('_externalHitbox')
                  and re.match(r'^(ship|megaship|balloon|old_)', p.stem, re.I))
    summary = []
    for i, obj in enumerate(objs, 1):
        if progress:
            progress(i / max(1, len(objs)), obj.stem)
        ext = obj.with_name(obj.stem + '_externalHitbox.obj')
        try:
            res = build(obj, ext if ext.is_file() else None)
        except (OSError, ValueError) as exc:
            summary.append({'model': obj.stem, 'error': str(exc)[:300]}); continue
        (out / (obj.stem + '.hitboxes.json')).write_text(json.dumps(res, indent=1), encoding='utf-8')
        (out / (obj.stem + '.zones.json')).write_text(json.dumps({'zones': zones_for_viewer(res)}, indent=1), encoding='utf-8')
        summary.append({'model': obj.stem, 'hitmesh': res['hitmesh_source'], 'sails': len(res['sails']), 'ports': res.get('port_counts'),
                        'masts': len(res['masts']), 'nodes': len(res['node_table']),
                        'corpus_world_size': [round(2 * h, 2) for h in res['corpus_half_extents_world']],
                        'notes': res['notes'][:3]})
    (out / 'Hitbox-Summary.json').write_text(json.dumps({'format': FORMAT + '-summary', 'ships': summary}, indent=1), encoding='utf-8')
    return {'ships': summary, 'output': str(out)}


def find_models_dirs(data_home):
    """Recovered ship model folders from Full Recovery (single and all-clients runs)."""
    data_home = Path(data_home)
    dirs = [p for p in list(data_home.glob('FullRecovery/*/Recovered/model/CommonData/Models/Ships')) +
            list(data_home.glob('FullRecovery-AllClients/*/Recovered/model/CommonData/Models/Ships')) if p.is_dir()]
    return sorted(dirs, key=lambda p: p.stat().st_mtime, reverse=True)
