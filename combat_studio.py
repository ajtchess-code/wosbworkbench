"""Evidence-safe projectile geometry, heatmaps and repeatable experiment planning.

This is NOT the game server's combat damage formula. The geometric algorithms are
standard mathematical ray/trajectory calculations, not reconstructed WoSB physics.
"""
from __future__ import annotations
from collections import defaultdict
import math,statistics


def finite(value,*,minimum=-1e12,maximum=1e12):
    v=float(value)
    if not math.isfinite(v) or not minimum<=v<=maximum:raise ValueError('Non-finite or out-of-range numeric input')
    return v


def vector_norm(vector):
    v=[finite(x) for x in vector]
    if len(v)!=3:raise ValueError('3D vector expected')
    length=math.sqrt(sum(x*x for x in v))
    if length<=1e-12:raise ValueError('Zero-length vector')
    return [x/length for x in v]


def impact_angle(incoming_direction, outward_normal):
    """Return 0-degree perpendicular incidence and 90-degree grazing.

    incoming_direction points from shooter towards target. An outward-facing
    normal faces the shooter only when dot(incoming,normal) < 0.
    """
    direction=vector_norm(incoming_direction);normal=vector_norm(outward_normal)
    dot=sum(a*b for a,b in zip(direction,normal))
    return {'front_facing':dot < -1e-8,'obliquity_degrees':round(math.degrees(math.acos(max(0.,min(1.,-dot)))),4)
            if dot<0 else None,'incidence_cosine':round(max(0.,-dot),6),
            'status':'geometric_model_only','hp_damage':None,
            'note':'Surface winding and transform must match the game hitbox to infer actual collision.'}


def attacker_direction(target,attacker):
    return vector_norm([finite(target[i])-finite(attacker[i]) for i in range(3)])


def trajectory(*,origin,velocity,gravity=9.81,duration=6.0,steps=96):
    """Illustrative ballistic trajectory. Gravity/unit scales are user inputs."""
    if not isinstance(steps,int) or not 2<=steps<=2000:raise ValueError('Steps outside allowed range')
    tmax=finite(duration,minimum=.01,maximum=120)
    g=finite(gravity,minimum=0,maximum=1000)
    start=[finite(v) for v in origin];vel=[finite(v) for v in velocity]
    if len(start)!=3 or len(vel)!=3:raise ValueError('Expected 3D vectors')
    return {'sample_points':[[round(start[0]+vel[0]*t,5),round(start[1]+vel[1]*t-g*t*t/2,5),
                              round(start[2]+vel[2]*t,5)] for t in (i*tmax/(steps-1) for i in range(steps))],
            'model':'illustrative_parabola_constant_gravity','verified_game_trajectory':False}


def angle_heatmap(samples, shot_direction, *, sample_limit=300000):
    """Compute front-facing geometric exposure for already-recovered surface normals."""
    if len(samples)>sample_limit:raise ValueError('Too many sample points')
    result=[]
    for sample in samples:
        rec=impact_angle(shot_direction,sample['normal'])
        result.append({'position':sample.get('position'),**rec})
    return {'values':result,'kind':'geometric_exposure','damage_prediction_available':False}


def compare_weapon_inputs(guns,ammo, *, ids=()):
    """Return extracted values without treating fields as complete formulas."""
    keys=('Poundage','Penetration','Distance','Cooldown','Scatter','Angle')
    picked=[x for x in guns if not ids or str(x.get('ID')) in {str(i) for i in ids}]
    return [{'id':x.get('ID'),'name':x.get('EnglishName'),'properties':{k:x.get(k) for k in keys},
             'source':x.get('Source'),'hp_damage':None,'hp_damage_status':'not_recovered'} for x in picked]


def suggested_trials(existing, *, target='Merchant\'s Grace', cannon='42-pound carronade',
                     ammo='Round Shot', zones=('stern','side','bow','sails'), angles=(0,30,60), repeats=5):
    """Recommend controlled experiments where fewest matching measurements exist."""
    if not 1<=repeats<=100:raise ValueError('Repetitions must be 1–100')
    coverage=defaultdict(int)
    for x in existing:
        key=(str(x.get('target_ship','')).casefold(),str(x.get('weapon','')).casefold(),
             str(x.get('ammo','')).casefold(),str(x.get('target_armor_region',x.get('region',''))).casefold(),
             round(float(x.get('impact_angle_deg',x.get('angle',0)))/15)*15)
        coverage[key]+=1
    results=[]
    for zone in zones:
        for angle in angles:
            key=(target.casefold(),cannon.casefold(),ammo.casefold(),zone.casefold(),round(angle/15)*15)
            have=coverage[key]
            results.append({'target_ship':target,'weapon':cannon,'ammo':ammo,'region':zone,
                            'impact_angle_deg':angle,'observed_repetitions':have,
                            'needed_repetitions':max(0,repeats-have),'shot_type':'single',
                            'recommended_setup':'Hold range, bonuses, velocity and target condition constant',
                            'status':'research_plan_not_game_rule'})
    return sorted(results,key=lambda x:(-x['needed_repetitions'],x['region'],x['impact_angle_deg']))


def observe_prediction(records, *, key_fields=('weapon','ammo','target_ship','region'), min_count=3):
    """Empirical summary by exact categorical setup; no interpolation or extrapolation."""
    grouped=defaultdict(list)
    for row in records:
        damage=row.get('damage',row.get('observed_hp_damage'))
        try:value=finite(damage,minimum=0)
        except (ValueError,TypeError):continue
        key=tuple(str(row.get(k,'')).casefold() for k in key_fields)
        if all(key):grouped[key].append(value)
    out=[]
    for key,values in sorted(grouped.items()):
        n=len(values)
        out.append({'conditions':dict(zip(key_fields,key)),'n':n,
                    'observed_mean_hp':round(statistics.mean(values),2) if n>=min_count else None,
                    'observed_range':[min(values),max(values)],
                    'status':'measured_user_supplied' if n>=min_count else 'insufficient_independent_measurements',
                    'authoritative_formula':False})
    return out
