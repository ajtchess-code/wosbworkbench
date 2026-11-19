"""Build the 3D battle simulator page (ships, forts, sailing, firing arcs, ballistics, hits).

Data comes from the catalog (ships, cannons, ammo, upgrades, crew), rebuilt
hitboxes with real gun ports, fort hardpoints, and (local builds only) a
low-poly version of each recovered ship model. The rules run in the browser
via wosb_sim.js, a port of combat_sim.py / damage_model.py.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _first(v, default=0.0):
    try:
        return float(str(v).split('|')[0])
    except (TypeError, ValueError):
        return default


def _range(v):
    """'60-140' -> (60, 140); '130' -> (0, 130)."""
    text = str(v or '').split('|')[0]
    m = re.match(r'\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)', text)
    if m:
        return float(m.group(1)), float(m.group(2))
    return 0.0, _first(text, 0.0)


def _records(db, dataset, build='Steam'):
    rows = db.conn.execute('SELECT raw_json, source_root FROM records WHERE dataset=?', (dataset,)).fetchall()
    roots = {r[1] for r in rows}
    chosen = build if build in roots else ('Game' if 'Game' in roots else next(iter(roots), None))
    return [json.loads(r[0]) for r in rows if r[1] == chosen]


def catalog_data(db, *, build='Steam'):
    basics = {str(r.get('ID')): r for r in _records(db, 'ShipsBasics', build)}
    ships = []
    for r in _records(db, 'ShipsToPlay', build):
        name = (r.get('EnglishName') or '').strip()
        if not name or name.startswith('(') or 'test' in name.casefold() or name.isupper():
            continue
        b = basics.get(str(r.get('StaticInfoID')), {})
        ships.append({'n': name, 'hp': _first(r.get('Health')), 'armor': _first(r.get('Armor')), 'speed': _first(r.get('BasicSpeed')),
                      'mob': _first(r.get('BasicMobility')), 'crew': _first(r.get('BaseCrewPlaces')), 'places': _first(r.get('PlacesForUnitsCount')),
                      'rank': r.get('ShipRank'), 'cls': r.get('Type'), 'weight': _first(b.get('Weight'), 20),
                      'sid': int(_first(r.get('StaticInfoID'), 0)), 'model': b.get('ModelName')})
    cannons = []
    for r in _records(db, 'Cannons', build):
        lo, hi = _range(r.get('Distance'))
        parts = str(r.get('Class') or 'LiteCannon Default').split()
        cls, feature = parts[0], (parts[1] if len(parts) > 1 else 'Default')
        extra = {}
        for kv in str(r.get('Extra') or '').split():
            if ':' in kv:
                k, v = kv.split(':', 1); extra[k] = _first(v, 0)
        cannons.append({'n': r.get('EnglishName'), 'pen': _first(r.get('Penetration')), 'min': lo, 'max': hi,
                        'reload': _first(r.get('Cooldown'), 10), 'angle': _first(r.get('Angle'), 15),
                        'scatter': _first(r.get('Scatter'), 3), 'speed': _first(r.get('SpeedFactor'), 1),
                        'splash': _first(r.get('SplashRadius'), 0), 'mortar': 'mortar' in str(r.get('Category', '')).casefold(),
                        'cat': r.get('Category'), 'cls': cls, 'feature': feature, 'extra': extra,
                        'mount': 'bow/stern' if cls == 'Bombardier' else ('special' if cls == 'Special' else ('mortar' if cls == 'Mortar' else 'broadside'))})
    ammo = []
    for r in _records(db, 'CannonBalls', build):
        if (r.get('EnglishName') or '').casefold() in ('', 'removed'):
            continue
        ammo.append({'n': r.get('EnglishName'), 'df': _first(r.get('DamageFactor'), 1), 'pen': _first(r.get('Penetration')),
                     'distF': _first(r.get('DistanceFactor'), 1), 'curve': _first(r.get('CurveMultiplier'), 1),
                     'speed': _first(r.get('Speed'), 1), 'sail': _first(r.get('DamageToSailes')), 'crew': _first(r.get('CrewDamage')),
                     'reload': _first(r.get('ReloadFactor'), 1), 'min': _first(r.get('MinDamageThroughAnyHitbox')),
                     'fx': str(r.get('Effects') or '')})
    upgrades = [{'n': r.get('EnglishName'), 'slot': r.get('Category'), 'fx': r.get('EffectsBoost') or ''}
                for r in _records(db, 'ShipUpgradesNew', build) if r.get('EnglishName')]
    units = [{'id': r.get('ID'), 'type': r.get('Type'), 'n': (r.get('EnglishName') or r.get('Type') or r.get('ID')),
              'dmg': _first(r.get('DDamage')), 'hp': _first(r.get('DHealth')), 'cap': _first(r.get('DCapacity')),
              'cost': _first(r.get('Cost')), 'fx': ' '.join(str(r.get(k) or '') for k in ('Effect', 'EffectPerBoardingUnit', 'EffectPerSailor')).strip()}
             for r in _records(db, 'UnitsInfo', build)]
    skills = [{'n': r.get('EnglishName'), 'fx': r.get('Effect') or ''} for r in _records(db, 'CaptainSkills', build) if r.get('EnglishName')]
    return {'ships': sorted(ships, key=lambda s: s['n']), 'cannons': sorted(cannons, key=lambda c: c['n'] or ''),
            'ammo': ammo, 'upgrades': upgrades, 'units': units, 'skills': skills}


def hull_data(hitboxes_dir):
    """{model: {corpus, sails: [[levels]], masts, ports, figure}} from Rebuild-ship-hitboxes output."""
    out = {}
    d = Path(hitboxes_dir) if hitboxes_dir else None
    if not d or not d.is_dir():
        return out
    for f in d.glob('*.hitboxes.json'):
        try:
            h = json.loads(f.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        r3 = lambda v: [round(x, 3) for x in v]
        out[f.name.replace('.hitboxes.json', '')] = {
            'corpus': {'min': r3(h['corpus']['min']), 'max': r3(h['corpus']['max'])},
            'sails': [{'w': round(s['weight'], 4), 'lv': [{'min': r3(b['min']), 'max': r3(b['max'])} for b in s['levels'] if b]} for s in h['sails']],
            'masts': [{'min': r3(m['box']['min']), 'max': r3(m['box']['max'])} for m in h['masts']],
            'ports': [{'s': p['side'], 'p': r3(p['position'])} for p in h.get('gun_ports', [])],
            'figure': h.get('figurehead_mount')}
    return out


def fort_data(models_root):
    """Imperial forts and fort towers: gun hardpoints + footprint from recovered models."""
    out = {}
    if not models_root:
        return out
    base = Path(models_root)
    for pattern in ('**/special/world/worldfort[0-9].json', '**/special/towers/t_*[0-9].json', '**/special/forts/guildfort_level[0-9].json'):
        for f in base.glob(pattern):
            try:
                rep = json.loads(f.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                continue
            guns = [h for h in rep.get('hardpoints', []) if h.get('type') in ('BuildingWeapon', 'Mortar', 'FireGun', 'CannonSidePoint')]
            b = rep.get('bounds') or [[-20, 0, -20], [20, 20, 20]]
            out[f.stem] = {'guns': [{'p': [round(v, 2) for v in g['position']], 'f': [round(v, 3) for v in g['forward']], 't': g['type']} for g in guns],
                           'bounds': b}
    return out


def lowpoly(obj_path, *, cell=0.9, max_tris=2600, include=('ShipCorpus', 'ShipMin', 'SailStatic', 'SailAnimated', 'MastFrame', 'DeckStuff')):
    """Vertex-clustered low-poly mesh (model units) for local previews; never published."""
    verts = []; faces = []; groups = []; current = None; keep = False
    with open(obj_path, encoding='utf-8', errors='replace') as fh:
        for line in fh:
            if line.startswith('o '):
                current = line[2:].strip(); keep = any(k in current for k in include)
                if 'ShipMin' in current:
                    groups.append('min')
            elif line.startswith('v '):
                p = line.split(); verts.append((float(p[1]), float(p[2]), float(p[3])))
            elif line.startswith('f ') and keep:
                idx = [int(t.split('/')[0]) - 1 for t in line.split()[1:4]]
                faces.append((idx, current))
    has_min = bool(groups)
    faces = [f for f, g in faces if not (has_min and 'ShipCorpus' in g)]   # prefer the low-LOD hull when present
    cluster = {}; out_v = []; out_f = set()
    def cid(i):
        x, y, z = verts[i]; key = (round(x / cell), round(y / cell), round(z / cell))
        if key not in cluster:
            cluster[key] = len(out_v); out_v.append(key)
        return cluster[key]
    for a, b, c in faces:
        ia, ib, ic = cid(a), cid(b), cid(c)
        if ia != ib and ib != ic and ia != ic:
            out_f.add(tuple(sorted((ia, ib, ic))))
        if len(out_f) > max_tris * 3:
            break
    tris = list(out_f)[:max_tris]
    return {'v': [round(c * cell, 2) for key in out_v for c in key], 'f': [i for t in tris for i in t]}


def build_page(db, output, *, hitboxes_dir=None, models_dir=None, forts_root=None, include_models=False,
               damage_calibration=None, inline_lib=True, build='Steam', pack_base=None):
    data = catalog_data(db, build=build)
    if pack_base:
        data['packBase'] = pack_base
    data['hull'] = hull_data(hitboxes_dir)
    data['forts'] = fort_data(forts_root)
    data['calib'] = damage_calibration or {'armor_weight': 1.0, 'scale': 1.0, 'calibrated': False}
    data['meshes'] = {}
    data['fort_hp'] = FORT_HP_BY_PORT_LEVEL
    try:
        data['ports'] = port_battles(db, models_root=forts_root, build=build)
    except Exception:  # catalogs without Map_Objects
        data['ports'] = []
    if include_models and models_dir:
        for s in data['ships']:
            m = s.get('model')
            if m and m in data['hull'] and m not in data['meshes']:
                obj = Path(models_dir) / (m + '.obj')
                if obj.is_file():
                    try:
                        data['meshes'][m] = lowpoly(obj)
                    except (OSError, ValueError):
                        pass
    template = (ROOT / 'viewer' / 'battle_sim.html').read_text(encoding='utf-8')
    lib = (ROOT / 'viewer' / 'wosb_sim.js').read_text(encoding='utf-8')
    payload = json.dumps(data, separators=(',', ':')).replace('<', '\\u003c')
    html = template.replace('/*__SIM_DATA__*/', payload)
    html = html.replace('<!--__SIM_LIB__-->', f'<script>{lib}</script>' if inline_lib else '<script src="../assets/wosb_sim.js"></script>')
    out = Path(output); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding='utf-8')
    return {'output': str(out), 'ships': len(data['ships']), 'with_hitboxes': len(data['hull']),
            'with_meshes': len(data['meshes']), 'forts': len(data['forts']), 'port_sites': len(data['ports'])}


TOWER_SPECS = {
    # WosbPbs.TowerDesription (client): damage per weapon, cooldown s, half-arc, dead zone, max distance.
    't_mortar': {'kind': 'mortar', 'dmg': 120, 'cd': 15, 'arc': 180, 'dead': 50, 'range': 190},
    't_fire': {'kind': 'prometheus', 'dmg': 30, 'cd': 0.5, 'arc': 45, 'dead': 14, 'range': 115},
    't_cannonsstr': {'kind': 'cannon', 'dmg': None, 'cd': None, 'arc': 30, 'dead': 0, 'range': None},
}
FORT_HP_BY_PORT_LEVEL = [10000, 12000, 15000, 20000, 25000, 29000, 33000]   # WosbPbs.FortLevelsByPort


_NEWWORLD = {}


def _newworld(root):
    """The recovered 'newWorld' models folder anywhere under a Full Recovery output."""
    key = str(root)
    if key not in _NEWWORLD:
        base = Path(root); hit = None
        direct = base / 'CommonData' / 'Models' / 'newWorld'
        if direct.is_dir():
            hit = direct
        else:
            for cand in base.glob('**/newWorld'):
                if cand.is_dir() and (cand / 'special').is_dir():
                    hit = cand; break
        _NEWWORLD[key] = hit
    return _NEWWORLD[key]


def latest_recovery(home_dir):
    """Most recent Full Recovery output folder (for forts, towers and island footprints)."""
    roots = [p for p in (Path(home_dir) / 'FullRecovery').glob('*') if p.is_dir()]
    return max(roots, key=lambda p: p.stat().st_mtime) if roots else None


def _model_bounds(models_root, path):
    """Footprint of a placed model from its recovered report (prefers the collision '_shape' model)."""
    if not models_root:
        return None
    base = _newworld(models_root)
    if base is None:
        return None
    rel = path.replace('\\', '/')
    for cand in (base / (rel + '_shape.json'), base / (rel + '.json')):
        try:
            b = json.loads(cand.read_text(encoding='utf-8')).get('bounds')
            if b:
                return [[round(v, 1) for v in b[0]], [round(v, 1) for v in b[1]]]
        except (OSError, ValueError):
            continue
    return None


def port_battles(db, *, models_root=None, radius=650, build='Steam'):
    """Every guild-fort site on the world map with its towers, fortifications, islands and port."""
    rows = [r for r in _records(db, 'Map_Objects', build) if r.get('SceneName') == 'World']
    forts = [r for r in rows if 'guildfort' in r.get('Path', '')]
    out = []
    bounds_cache = {}

    def bounds(path):
        if path not in bounds_cache:
            bounds_cache[path] = _model_bounds(models_root, path)
        return bounds_cache[path]
    for i, f in enumerate(forts):
        fx, fz = f['Position0'], f['Position1']
        objs = []
        for r in rows:
            dx, dz = r['Position0'] - fx, r['Position1'] - fz
            if dx * dx + dz * dz > radius * radius:
                continue
            path = r.get('Path', ''); kind = 'island'
            if 'guildfort' in path:
                kind = 'fort'
            elif 'special\\towers\\t_' in path:
                kind = 'tower'
            elif 'fortification' in path:
                kind = 'fortification'
            elif path.startswith('ports\\'):
                kind = 'port'
            elif path.startswith(('underwater', 'editor', 'decoration')):
                continue
            o = {'k': kind, 'm': path.split('\\')[-1], 'x': round(dx, 1), 'z': round(dz, 1), 'r': round(r.get('Rotation') or 0, 4),
                 's': r.get('AdditionalScale') or 1}
            b = bounds(path)
            if b:
                o['b'] = b
            if kind == 'tower':
                spec = next((v for k, v in TOWER_SPECS.items() if o['m'].startswith(k)), None)
                if spec:
                    o['spec'] = spec
            objs.append(o)
        port = min((o for o in objs if o['k'] == 'port'), key=lambda o: o['x'] ** 2 + o['z'] ** 2, default=None)
        out.append({'id': i, 'x': round(fx), 'z': round(fz), 'port_model': port['m'] if port else None,
                    'towers': sum(1 for o in objs if o['k'] == 'tower'), 'objects': objs})
    return out


def build_boarding_page(db, output, *, inline_lib=True, build='Steam'):
    """Standalone boarding simulator (ship, crew mix, upgrades/skills) on the client's boarding loop."""
    d = catalog_data(db, build=build)
    data = {k: d[k] for k in ('ships', 'units', 'upgrades', 'skills')}
    data['ships'] = [{k: s[k] for k in ('n', 'hp', 'crew', 'places', 'weight', 'sid')} for s in data['ships']]
    template = (ROOT / 'viewer' / 'boarding_sim.html').read_text(encoding='utf-8')
    lib = (ROOT / 'viewer' / 'wosb_sim.js').read_text(encoding='utf-8')
    html = template.replace('/*__SIM_DATA__*/', json.dumps(data, separators=(',', ':')).replace('<', '\\u003c'))
    html = html.replace('<!--__SIM_LIB__-->', f'<script>{lib}</script>' if inline_lib else '<script src="../assets/wosb_sim.js"></script>')
    out = Path(output); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding='utf-8')
    return {'output': str(out), 'ships': len(data['ships']), 'unit_types': sum(1 for u in data['units'] if u['type'] != 'Special')}


def texture_roots(recovery_dir=None, game_roots=()):
    """Where model textures can come from: recovered PNGs first, then the game's own texture XNBs."""
    roots = []
    if recovery_dir:
        for pattern in ('**/ModelTextures', '**/Data/Textures'):
            for cand in Path(recovery_dir).glob(pattern):
                if cand.is_dir():
                    roots.append(cand)
    for g in game_roots or ():
        for sub in ('ModelTextures', 'Textures'):
            for cand in (Path(g) / 'Data' / sub, Path(g).parent / 'Data' / sub):
                if cand.is_dir():
                    roots.append(cand)
    return roots


def build_model_pack(db, pack_dir, *, recovery_dir, game_roots=(), lod='high', tex_size=1024, build='Steam', progress=None):
    """Real ship, tower, fort and island meshes (with textures) for the battle simulator."""
    import model_pack
    data = catalog_data(db, build=build)
    ships = {s['model'] for s in data['ships'] if s.get('model')}
    world = set()
    try:
        for site in port_battles(db, models_root=recovery_dir, build=build):
            world.update(o['m'] for o in site['objects'])
    except Exception:
        pass
    world.update(fort_data(recovery_dir).keys() if recovery_dir else ())
    found = model_pack.collect_models(recovery_dir, ship_models=ships, world_models=world)
    if not found:
        return {'models': 0, 'textures': 0, 'missing': len(ships | world), 'note': 'no recovered OBJ files found — run Full Recovery first'}
    idx = model_pack.build_pack(pack_dir, found, texture_roots=texture_roots(recovery_dir, game_roots), lod=lod, tex_size=tex_size, progress=progress)
    ok = sum(1 for v in idx['models'].values() if v.get('file'))
    return {'models': ok, 'textures': len(idx['textures']), 'missing': len(ships | world) - ok, 'pack': str(pack_dir)}


def build_simulators(db, out_dir, *, hitboxes_dir=None, recovery_dir=None, game_roots=(), with_models=True, build='Steam', progress=None,
                     damage_calibration=None):
    """Local battle + boarding simulator pages, with a real-model pack next to them."""
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    pack = {}
    if with_models and recovery_dir:
        pack = build_model_pack(db, out / 'pack', recovery_dir=recovery_dir, game_roots=game_roots, build=build, progress=progress)
    # the page reads the library inline and the pack through relative <script> files, so it also works from file://
    res = build_page(db, out / 'battle_sim.html', hitboxes_dir=hitboxes_dir, forts_root=recovery_dir, build=build,
                     pack_base='pack/' if pack.get('models') else None, damage_calibration=damage_calibration)
    build_boarding_page(db, out / 'boarding_sim.html', build=build)
    res['pack'] = pack
    return res


def calibration_from_trials(db, trials_csv, *, build='Steam'):
    """Fit the simulators' damage scale and armor weight to measured hits (Damage-Trials.csv).

    Each row: cannon, ammo, target_armor (or target_ship), hp_before, hp_after, optional distance,
    max_range, angle_deg, zone. Returns the calibration dict the battle simulator reads.
    """
    import ball_damage
    import damage_fit
    d = catalog_data(db, build=build)
    cannons = {c['n']: {'Penetration': c['pen'], 'MaxDistance': c['max']} for c in d['cannons']}
    ammos = {a['n']: {'Penetration': a['pen'], 'DamageFactor': a['df'], 'MinDamageThroughAnyHitbox': a.get('min') or 0} for a in d['ammo']}
    armor = {s['n']: s['armor'] for s in d['ships']}
    trials = []
    for r in damage_fit.load_trials(trials_csv):
        try:
            dmg = float(r['hp_before']) - float(r['hp_after'])
        except (KeyError, TypeError, ValueError):
            continue
        ta = r.get('target_armor') or armor.get(r.get('target_ship'))
        trials.append({**r, 'damage': dmg, 'target_armor': ta})
    res = ball_damage.calibrate(trials, cannons, ammos)
    if not res.get('ok'):
        return {'calibrated': False, 'armor_weight': 1.0, 'scale': 1.0, 'reason': res.get('reason')}
    return {'calibrated': True, 'armor_weight': res['armor_weight'], 'scale': res['scale'], 'samples': res['samples'],
            'mape': res['mean_abs_error_pct'], 'residuals': res['residuals']}


def load_calibration(home_dir):
    try:
        c = json.loads((Path(home_dir) / 'Research' / 'Damage-Calibration.json').read_text(encoding='utf-8'))
        return c if c.get('calibrated') else None
    except (OSError, ValueError):
        return None


def ensure_hitboxes(home_dir, hitboxes_dir=None, *, progress=None):
    """Use existing rebuilt hitboxes, or build them from the latest Full Recovery when there are none."""
    import hitbox_recovery
    hb = Path(hitboxes_dir) if hitboxes_dir else Path(home_dir) / 'Research' / 'Hitboxes'
    if hb.is_dir() and any(hb.glob('*.hitboxes.json')):
        return hb
    dirs = hitbox_recovery.find_models_dirs(home_dir)
    if not dirs:
        return hb if hb.is_dir() else None
    hitbox_recovery.batch(dirs[0], hb, progress=progress)
    return hb
