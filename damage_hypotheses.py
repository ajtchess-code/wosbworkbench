"""Evidence-labeled competing hypotheses for World of Sea Battle ballistics.

Values in the client catalog are observed static data. The only recovered
armor equation is BasicArmor*(1+B5)+B13; obliquity, penetration transfer,
range falloff and the initial damage scale remain UNVERIFIED hypotheses.
"""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path

CATALOG=Path(__file__).resolve().parent/'Research-Ballistics-Catalog.json'


def lookup(rows,name):
    matches=[x for x in rows if any(str(x.get(k,'')).casefold()==name.casefold()
                                  for k in ('EnglishName','Name','ID'))]
    if not matches:raise ValueError('Not found in bundled catalog: '+name)
    return matches[0]


def calculate(cannon, ammo, *,target_armor, angle_deg=0, armor_percent_bonus=0,
              armor_flat_bonus=0, penetration_bonus=0, damage_percent_bonus=0,
              direction='side', bow_protection_percent=0, hit_count=1,
              measured_reference_hp_per_hit=None):
    """Returns nonauthoritative comparative indices and two distinct hypotheses.

    If a measured reference HP is supplied, it MUST be a normal-incidence hit
    on the exact same target/loadout. The returned HP outputs should be treated
    as calibration experiments, not actual WoSB server predictions.
    """
    vals=(target_armor,angle_deg,armor_percent_bonus,armor_flat_bonus,
          penetration_bonus,damage_percent_bonus,bow_protection_percent,hit_count)
    if any(not math.isfinite(float(v)) for v in vals):raise ValueError('Inputs must be finite')
    if not 0<=angle_deg<90:raise ValueError('Angle must be from 0 to less than 90 degrees')
    if target_armor<0 or hit_count<1 or hit_count>200:raise ValueError('Invalid armor or hit count')
    if direction not in ('bow','stern','side'):raise ValueError('Invalid impact region')
    base_armor=max(0,target_armor*(1+armor_percent_bonus/100)+armor_flat_bonus)
    effective_armor=base_armor/max(1e-6,math.cos(math.radians(angle_deg)))
    penetration=max(0,float(cannon.get('Penetration',0))+float(ammo.get('Penetration',0))+penetration_bonus)
    poundage=float(cannon.get('Poundage',0) or 0)
    ammo_multiplier=float(ammo.get('DamageFactor',1) or 0)
    bonus=max(0,1+damage_percent_bonus/100)
    assumed_bow_factor=max(0,1-bow_protection_percent/100) if direction=='bow' else 1
    power_index=hit_count*poundage*ammo_multiplier*bonus*assumed_bow_factor
    ratio=penetration/max(1e-9,effective_armor)
    # Two deliberately competing candidate transfer laws, not derived from code.
    hard_gate=1.0 if penetration>=effective_armor else 0.0
    soft_transfer=min(1.0, max(0.0,ratio))
    result={'format':'wosb-damage-hypothesis-v1',
            'weapon':cannon.get('EnglishName'),'ammo':ammo.get('EnglishName'),
            'inputs':{'target_basic_armor':target_armor,'angle_deg':angle_deg,
                      'armor_percent_bonus':armor_percent_bonus,'armor_flat_bonus':armor_flat_bonus,
                      'penetration_bonus':penetration_bonus,'damage_percent_bonus':damage_percent_bonus,
                      'direction':direction,'bow_protection_percent':bow_protection_percent,
                      'hit_count':hit_count},
            'client_facts':{'weapon_penetration':cannon.get('Penetration'),
                            'weapon_poundage':cannon.get('Poundage'),
                            'weapon_range_stat':cannon.get('Distance'),
                            'ammo_penetration':ammo.get('Penetration'),
                            'ammo_damage_factor':ammo.get('DamageFactor'),
                            'armor_expression':'BasicArmor * (1 + GetBonus(5,1)) + GetBonus(13,1)'},
            'hypotheses':{'effective_armor_cosine':effective_armor,
                          'total_penetration_additive':penetration,
                          'penetration_to_armor_ratio':ratio,
                          'threshold_penetration_gate':hard_gate,
                          'smooth_penetration_factor':soft_transfer,
                          'relative_poundage_damage_index':power_index,
                          'index_if_threshold_model':power_index*hard_gate,
                          'index_if_smooth_model':power_index*soft_transfer},
            'confidence':{'armor_expression':'direct client IL',
                          'cannon_and_ammo_values':'client static catalog',
                          'obliquity_penetration_laws':'speculative — both alternatives unvalidated',
                          'poundage_to_HP':'unknown',
                          'range_falloff':'unknown; deliberately not inferred',
                          'bow_percent_interpretation':'assumption, not recovered multiplier',
                          'damage_hp':'not predicted without measured calibration'},
            'warning':'Neither candidate model is confirmed WoSB server logic. No claimed exact damage or hitbox.'}
    if measured_reference_hp_per_hit is not None:
        value=float(measured_reference_hp_per_hit)
        if not math.isfinite(value) or value<0:raise ValueError('Measured calibration must be finite and nonnegative')
        result['calibrated_alternatives_hp']={
            'threshold':value*hit_count*bonus*assumed_bow_factor*hard_gate,
            'smooth':value*hit_count*bonus*assumed_bow_factor*soft_transfer,
            'critical_caveat':'These assume the reference was a normal hit with full damage and identical loadout; verify separately.'}
    return result


def main():
    ap=argparse.ArgumentParser(description='NONAUTHORITATIVE WoSB damage-model hypotheses')
    ap.add_argument('--cannon',default='42-pdr Carronade')
    ap.add_argument('--ammo',default='Round Shot')
    ap.add_argument('--armor',type=float,default=12,help='User-chosen target armor: NOT Golden Bale')
    ap.add_argument('--angle',type=float,default=0)
    ap.add_argument('--hits',type=int,default=1)
    ap.add_argument('--measured-reference-hp',type=float)
    ap.add_argument('--output',help='Optional JSON output file')
    args=ap.parse_args()
    data=json.loads(CATALOG.read_text(encoding='utf-8'))['datasets']
    result=calculate(lookup(data['Cannons'],args.cannon),lookup(data['CannonBalls'],args.ammo),
                     target_armor=args.armor,angle_deg=args.angle,hit_count=args.hits,
                     measured_reference_hp_per_hit=args.measured_reference_hp)
    text=json.dumps(result,indent=2,ensure_ascii=False)
    if args.output:
        output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True);output.write_text(text,'utf-8')
        print('Wrote hypothetical damage report:',output)
    else:print(text)

if __name__=='__main__':main()
