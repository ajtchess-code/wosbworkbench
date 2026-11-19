"""Fit the server's cannonball damage from measured hits.

The client never computes how much HP a ball removes; the server does. This
module fits a transparent model to hits you measured (HP before/after from
video), so simulators can use calibrated numbers instead of guesses.

Model (log-linear, every term optional when the data cannot support it):

    log(damage) = c0 + c1·log(poundage) + c2·log(ammo damage factor)
                  + c3·log(penetration / effective armor) + c4·(range / max range)
                  + zone terms (stern, bow) + c5·[sail passed]

effective armor = armor / cos(impact angle), the usual geometric assumption;
it is reported as an assumption, and the fit shows whether it helps.
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path

FIELDS = ['shooter_ship', 'cannon', 'poundage', 'penetration', 'max_range', 'ammo', 'ammo_damage_factor',
          'ammo_penetration', 'target_ship', 'target_armor', 'distance', 'angle_deg', 'zone', 'through_sail',
          'hp_before', 'hp_after', 'notes']
FEATURES = ['log_poundage', 'log_ammo_factor', 'log_pen_ratio', 'range_fraction', 'stern', 'bow', 'through_sail']


def load_trials(path):
    path = Path(path)
    if not path.is_file():
        return []
    with path.open(encoding='utf-8', newline='') as fh:
        return [dict(r) for r in csv.DictReader(fh)]


def save_trials(path, rows):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction='ignore')
        w.writeheader(); [w.writerow(r) for r in rows]
    return path


def _f(row, key, default=None):
    try:
        v = row.get(key, '')
        return float(v) if v not in ('', None) else default
    except (TypeError, ValueError):
        return default


def features(row):
    """Feature vector for one hit (None entries mean 'unknown')."""
    pound = _f(row, 'poundage'); factor = _f(row, 'ammo_damage_factor', 1.0)
    pen = _f(row, 'penetration'); ammo_pen = _f(row, 'ammo_penetration', 0.0) or 0.0
    armor = _f(row, 'target_armor'); angle = _f(row, 'angle_deg', 0.0) or 0.0
    dist = _f(row, 'distance'); rng = _f(row, 'max_range')
    eff_armor = armor / max(0.05, math.cos(math.radians(min(85.0, abs(angle))))) if armor else None
    zone = (row.get('zone') or '').strip().casefold()
    return {
        'log_poundage': math.log(pound) if pound and pound > 0 else None,
        'log_ammo_factor': math.log(factor) if factor and factor > 0 else None,
        'log_pen_ratio': math.log((pen + ammo_pen) / eff_armor) if pen and eff_armor else None,
        'range_fraction': dist / rng if dist is not None and rng else None,
        'stern': 1.0 if zone == 'stern' else 0.0,
        'bow': 1.0 if zone == 'bow' else 0.0,
        'through_sail': 1.0 if str(row.get('through_sail', '')).strip().casefold() in ('1', 'yes', 'true', 'y') else 0.0,
    }


def damage(row):
    a, b = _f(row, 'hp_before'), _f(row, 'hp_after')
    return a - b if a is not None and b is not None and a > b else None


def _solve(A, y, ridge=1e-6):
    """Least squares via normal equations with a tiny ridge (pure Python)."""
    n = len(A[0])
    M = [[sum(r[i] * r[j] for r in A) + (ridge if i == j else 0.0) for j in range(n)] for i in range(n)]
    v = [sum(r[i] * yy for r, yy in zip(A, y)) for i in range(n)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(M[r][c]))
        M[c], M[p] = M[p], M[c]; v[c], v[p] = v[p], v[c]
        if abs(M[c][c]) < 1e-12:
            continue
        for r in range(n):
            if r != c:
                k = M[r][c] / M[c][c]
                M[r] = [a - k * b for a, b in zip(M[r], M[c])]; v[r] -= k * v[c]
    return [v[i] / M[i][i] if abs(M[i][i]) > 1e-12 else 0.0 for i in range(n)]


def fit(rows, *, min_samples=6):
    """Fit the model. Only features that vary and are known for every used hit are included."""
    samples = []
    for r in rows:
        d = damage(r)
        if d is None or d <= 0:
            continue
        samples.append((features(r), d, r))
    if len(samples) < min_samples:
        return {'ok': False, 'reason': f'need at least {min_samples} measured hits (have {len(samples)})', 'samples': len(samples)}
    used = []
    for f in FEATURES:
        vals = [s[0][f] for s in samples]
        if all(v is not None for v in vals) and max(vals) - min(vals) > 1e-9:
            used.append(f)
    # Keep at least 3 samples per parameter.
    used = used[:max(0, len(samples) // 3 - 1)]
    A = [[1.0] + [s[0][f] for f in used] for s in samples]
    y = [math.log(s[1]) for s in samples]
    coef = _solve(A, y)
    pred = [sum(c * x for c, x in zip(coef, row)) for row in A]
    ss_res = sum((a - b) ** 2 for a, b in zip(y, pred)); mean = sum(y) / len(y)
    ss_tot = sum((a - mean) ** 2 for a in y) or 1e-12
    resid = [{'measured': round(s[1], 1), 'predicted': round(math.exp(p), 1),
              'error_pct': round((math.exp(p) - s[1]) / s[1] * 100, 1),
              'cannon': s[2].get('cannon'), 'ammo': s[2].get('ammo'), 'target': s[2].get('target_ship'),
              'zone': s[2].get('zone')} for s, p in zip(samples, pred)]
    mape = sum(abs(r['error_pct']) for r in resid) / len(resid)
    terms = {'intercept': coef[0], **{f: c for f, c in zip(used, coef[1:])}}
    return {'ok': True, 'format': 'wosb-damage-fit-v1', 'samples': len(samples), 'terms': terms,
            'r2_log': round(1 - ss_res / ss_tot, 4), 'mean_abs_error_pct': round(mape, 1),
            'residuals': resid, 'explain': explain(terms),
            'note': 'Fitted to your measured hits; valid inside the range of cannons, ammo and armor you tested.'}


def explain(terms):
    out = []
    if 'log_poundage' in terms:
        out.append(f"damage ∝ poundage^{terms['log_poundage']:.2f}")
    if 'log_ammo_factor' in terms:
        out.append(f"damage ∝ ammo damage factor^{terms['log_ammo_factor']:.2f}")
    if 'log_pen_ratio' in terms:
        out.append(f"damage ∝ (penetration ÷ effective armor)^{terms['log_pen_ratio']:.2f}")
    if 'range_fraction' in terms:
        out.append(f"at max range damage × {math.exp(terms['range_fraction']):.2f}")
    if 'stern' in terms:
        out.append(f"stern hits × {math.exp(terms['stern']):.2f}")
    if 'bow' in terms:
        out.append(f"bow hits × {math.exp(terms['bow']):.2f}")
    if 'through_sail' in terms:
        out.append(f"after passing a sail × {math.exp(terms['through_sail']):.2f}")
    return out


def predict(model, row):
    if not model or not model.get('ok'):
        return None
    f = features(row); total = model['terms']['intercept']
    for k, c in model['terms'].items():
        if k == 'intercept':
            continue
        if f.get(k) is None:
            return None
        total += c * f[k]
    return math.exp(total)


def write_model(model, path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(model, indent=1), encoding='utf-8')
    return path


def js_model(model):
    """Compact form for the browser simulators."""
    if not model or not model.get('ok'):
        return None
    return {'terms': model['terms'], 'samples': model['samples'], 'mape': model['mean_abs_error_pct']}
