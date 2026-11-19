"""Estimate the HP one cannonball removes, from the game's own numbers.

What the client shows players (port equipment screen):
    damage per ball = (cannon penetration + ammo penetration − 2.1) × ammo damage factor
and the targeting hint flags a target whose armor exceeds 40 % of your average
penetration. Penetration values (14–34 for cannons) and armor (3–9.5) are on the
same scale, so the estimate treats armor like the UI's 2.1 reference: it is
subtracted from penetration per ball, scaled by the impact angle.

    damage = max(floor, pen_total − w·armor_eff) × ammo factor × (1 + ball-damage bonuses)
             × range bonus × (1 − target damage reduction) × (bow reduction)

* pen_total = cannon + ammo penetration + MWeaponPenetration
* armor_eff = (base armor × (1 + PArmor) + MArmor) / cos(angle)    [angle term: assumption]
* w = 1 by default (armor counts like the UI's 2.1 reference); calibrate() fits w
  and an overall scale from measured hits.

The server makes the final decision; this is an estimate built from client
formulas, and its uncalibrated parts are listed in ``assumptions``.
"""
from __future__ import annotations

import math
import re

UI_REFERENCE_ARMOR = 2.1


def parse_effects(text):
    """'PArmor +10; MArmor +1' -> {'PArmor': 0.10, 'MArmor': 1.0} (P effects are percent)."""
    out = {}
    for m in re.finditer(r'\b([PMB][A-Z][A-Za-z0-9]+)\s*([+-]?\d+(?:\.\d+)?)', str(text or '')):
        name, value = m.group(1), float(m.group(2))
        out[name] = out.get(name, 0.0) + (value / 100.0 if name.startswith('P') else value)
    return out


def combine(*effect_dicts):
    """Bonuses from upgrades, crew, skills and items add together (PlayerShipDynamicInfo.GetBonus)."""
    out = {}
    for d in effect_dicts:
        for k, v in (d or {}).items():
            out[k] = out.get(k, 0.0) + v
    return out


def _first(v, default=0.0):
    try:
        return float(str(v).split('|')[0])
    except (TypeError, ValueError):
        return default


def ui_damage(cannon, ammo):
    """The per-ball damage the game itself displays in the equipment screen."""
    return (_first(cannon.get('Penetration')) + _first(ammo.get('Penetration')) - UI_REFERENCE_ARMOR) * _first(ammo.get('DamageFactor'), 1.0)


def ui_damage_per_minute(cannon):
    """Cannon info card: (penetration − 2) × 60 / reload seconds."""
    reload_s = _first(cannon.get('Cooldown'), 1.0)
    return (_first(cannon.get('Penetration')) - 2) * 60 / max(0.1, reload_s)


def estimate(cannon, ammo, target_armor, *, shooter=None, target=None, distance=None, max_range=None,
             angle_deg=0.0, zone='side', armor_weight=1.0, scale=1.0):
    shooter = shooter or {}; target = target or {}
    pen = _first(cannon.get('Penetration')) + _first(ammo.get('Penetration')) + shooter.get('MWeaponPenetration', 0.0)
    armor = target_armor * (1 + target.get('PArmor', 0.0)) + target.get('MArmor', 0.0)
    armor_eff = armor / max(0.05, math.cos(math.radians(min(85.0, abs(angle_deg)))))
    floor = _first(ammo.get('MinDamageThroughAnyHitbox'), 0.0)
    base = max(floor, pen - armor_weight * armor_eff)
    dmg = base * _first(ammo.get('DamageFactor'), 1.0) * (1 + shooter.get('PBallDamage', 0.0))
    if distance is not None and max_range:
        dmg *= 1 + shooter.get('PBallDamageWhenMaxDistance', 0.0) * max(0.0, min(1.0, distance / max_range))
    dmg *= 1 - min(0.99, target.get('PReduceDamage', 0.0))
    if zone == 'bow':
        dmg *= 1 - target.get('PReduceDamageToNose', 0.0)
    dmg *= scale
    return {'damage': max(0.0, dmg), 'penetration': pen, 'effective_armor': armor_eff, 'per_ball_before_bonuses': base,
            'ui_damage': ui_damage(cannon, ammo),
            'assumptions': ['armor subtracts from penetration like the UI 2.1 reference (weight %.2f)' % armor_weight,
                            'angle raises effective armor by 1/cos(angle)',
                            'overall scale %.2f (1 = UI scale, uncalibrated)' % scale]}


def calibrate(trials, cannons, ammos):
    """Fit armor_weight and scale to measured hits.

    trials: [{'cannon','ammo','target_armor','damage', optional distance/max_range/angle_deg/zone/...}].
    Grid search on armor weight (0–3) with the scale solved in closed form.
    """
    rows = []
    for t in trials:
        c = cannons.get(t.get('cannon')); a = ammos.get(t.get('ammo'))
        if not c or not a or t.get('damage') in (None, '') or t.get('target_armor') in (None, ''):
            continue
        rows.append((t, c, a, float(t['damage'])))
    if len(rows) < 3:
        return {'ok': False, 'reason': f'need 3+ measured hits with known cannon, ammo and target armor (have {len(rows)})'}
    best = None
    for i in range(0, 301):
        w = i / 100.0
        preds = [estimate(c, a, float(t['target_armor']), distance=_f(t.get('distance')), max_range=_f(t.get('max_range')),
                          angle_deg=_f(t.get('angle_deg')) or 0.0, zone=t.get('zone') or 'side', armor_weight=w)['damage']
                 for t, c, a, _ in rows]
        num = sum(p * m for p, (_, _, _, m) in zip(preds, rows)); den = sum(p * p for p in preds)
        if den <= 0:
            continue
        s = num / den
        err = sum((s * p - m) ** 2 for p, (_, _, _, m) in zip(preds, rows))
        if best is None or err < best[0]:
            best = (err, w, s, preds)
    if not best:
        return {'ok': False, 'reason': 'no usable fit'}
    _, w, s, preds = best
    resid = [{'measured': m, 'predicted': round(s * p, 1), 'error_pct': round((s * p - m) / m * 100, 1) if m else None}
             for p, (_, _, _, m) in zip(preds, rows)]
    mape = sum(abs(r['error_pct']) for r in resid if r['error_pct'] is not None) / len(resid)
    return {'ok': True, 'armor_weight': w, 'scale': round(s, 4), 'samples': len(rows), 'mean_abs_error_pct': round(mape, 1),
            'residuals': resid}


def _f(v):
    try:
        return float(v) if v not in (None, '') else None
    except (TypeError, ValueError):
        return None
