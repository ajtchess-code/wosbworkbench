"""Evidence-gated, reproducible WoSB ship ballistic scenario preparation.

The static client catalogs expose attributes, NOT the authoritative damage code.
This module deliberately refuses to claim a hit point result without a supplied,
measured calibration and keeps geometric approximations separate from client data.
"""
from __future__ import annotations

import json
import math

CATALOG_NAMES = ('Cannons', 'CannonBalls', 'ShipsBasics', 'ShipsToPlay',
                 'ShipUpgradesNew', 'CaptainSkills')


def load_ballistics_catalog(db=None):
    from workbench_db import bundled_path
    path = bundled_path('Research-Ballistics-Catalog.json')
    if path.is_file():
        data = json.loads(path.read_text(encoding='utf-8'))
    else:
        data = {'format':'wosb-ballistics-catalog-1','datasets':{},'provenance':'No packaged catalog available'}
    if not db:
        return data
    try:
        rows = db.conn.execute('''SELECT dataset,raw_json,source_root FROM records
               WHERE dataset IN ('Cannons','CannonBalls','ShipsBasics','ShipsToPlay',
                                 'ShipUpgradesNew','CaptainSkills')
               ORDER BY CASE source_root WHEN 'Game' THEN 0 WHEN 'Steam' THEN 1 ELSE 2 END,id''').fetchall()
        grouped = {}
        for r in rows:
            grouped.setdefault(r['dataset'],{})
            obj=json.loads(r['raw_json'])
            key=str(obj.get('ID',obj.get('Name',obj.get('SourceRecord',''))))
            if key not in grouped[r['dataset']]:
                grouped[r['dataset']][key]=obj
        for name,items in grouped.items():
            if items:
                data.setdefault('datasets',{})[name]=list(items.values())
        if grouped: data['provenance'] += '; local Workbench imported records preferred when present'
    except Exception:
        pass
    return data


def _number(value, label):
    try: result=float(value)
    except (TypeError,ValueError):raise ValueError(label+' must be numeric')
    if not math.isfinite(result):raise ValueError(label+' must be finite')
    return result


def illustrative_shot(cannon, ammo, ship, *, obliquity_deg=0, distance=100,
                      zone='starboard', measured_reference_hp=None,
                      user_zone_multiplier=None, user_damage_bonus_pct=0):
    """Calculate *relative proxy*, not verified WoSB HP or deflection probability.

    Calibration is a measured perpendicular broadside hit under the same loadout
    and distance. It cannot be generalized as an authoritative game formula.
    """
    if zone not in ('bow','stern','port','starboard'):raise ValueError('Invalid zone')
    degrees=_number(obliquity_deg,'obliquity_deg')
    if not 0<=degrees<90:raise ValueError('Obliquity must be in [0,90) degrees')
    distance=_number(distance,'distance')
    if distance<0:raise ValueError('Distance cannot be negative')
    poundage=max(0,_number(cannon.get('Poundage',0),'Poundage'))
    factor=max(0,_number(ammo.get('DamageFactor',1),'DamageFactor'))
    arm=max(0,_number(ship.get('Armor',0),'Armor'))
    pen=_number(cannon.get('Penetration',0),'Cannon.Penetration')
    shot_pen=_number(ammo.get('Penetration',0),'CannonBalls.Penetration')
    effective=arm/max(.001,math.cos(math.radians(degrees)))
    relative_index=poundage*factor  # arbitrary index, not the game's damage
    result={
        'kind':'ILLUSTRATIVE PROXY — NOT VERIFIED IN-GAME DAMAGE',
        'cannon':cannon.get('EnglishName'),'ammo':ammo.get('EnglishName'),
        'ship':ship.get('EnglishName'),'zone':zone,'obliquity_deg':degrees,
        'distance':distance,'cannon_poundage':poundage,'ammo_damage_factor':factor,
        'relative_damage_index':relative_index,
        'base_armor_recorded':arm,'geometric_effective_armor_proxy':effective,
        'cannon_penetration_recorded':pen,'ammo_penetration_recorded':shot_pen,
        'penetration_formula':'Unknown; values are listed separately, NOT combined',
        'deflection_prediction':'Unknown; authoritative threshold and probability not recovered',
        'ship_health_recorded':ship.get('Health'),
        'damage_hp':None,
        'source_warning':'Catalog values are real extracted fields. No server-verified combat formula.'}
    if measured_reference_hp is not None and user_zone_multiplier is not None:
        measured=_number(measured_reference_hp,'measured_reference_hp')
        zone_factor=_number(user_zone_multiplier,'user_zone_multiplier')
        bonus=_number(user_damage_bonus_pct,'user_damage_bonus_pct')
        if measured<0 or zone_factor<0 or bonus< -100:raise ValueError('Invalid calibration inputs')
        # Explicitly user-calibrated only. Do not imply game-derived multipliers.
        result['damage_hp']=measured*zone_factor*(1+bonus/100)
        result['damage_hp_status']='user-calibrated rough estimate, does not model target armor or angle changes'
    return result
