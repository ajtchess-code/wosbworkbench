"""Ship fitting and cannon mount research without invented game slot counts."""
from __future__ import annotations
import math,re,statistics


def mount_candidates(mesh):
    """Find named gun-related mesh groups; not a count of usable gun ports."""
    hits=[];names=set()
    for group in mesh.get('groups',[]):
        name=str(group.get('name',''))
        if not re.search(r'(?i)(gunport|cannon|carronade|gun_deck|gunmount|artillery)',name):continue
        first=int(group.get('first_triangle',0));count=int(group.get('triangle_count',0))
        indices=mesh['triangles'][first*3:(first+count)*3]
        if not indices:continue
        points=[mesh['vertices'][i] for i in set(indices)]
        center=[sum(p[k] for p in points)/len(points) for k in range(3)]
        hits.append({'name':name,'center':center,'triangle_count':count,'category':'candidate weapon-related geometry',
                     'actual_fireable_mount_verified':False})
        names.add(name)
    return {'format':'wosb-mount-candidates-v1','matching_groups':hits,'candidate_groups':len(hits),
            'verified_fireable_cannon_slots':None,
            'warning':'Mesh component names do not establish gun-port counts, slot limits or weapons mounted.'}


def outfit_hypothesis(base_stats,modifiers):
    """Uniform user-supplied percent/flat modifier research—not a verified bonus stack."""
    if len(modifiers)>250:raise ValueError('Too many modifiers')
    result={};provenance={}
    for name,value in base_stats.items():
        base=float(value)
        if not math.isfinite(base):raise ValueError('Invalid base stat')
        additions=[];percent=0;flat=0
        for item in modifiers:
            if item.get('stat')!=name:continue
            val=float(item.get('value',0))
            if not math.isfinite(val):raise ValueError('Invalid modifier')
            kind=item.get('kind')
            if kind=='percent':percent+=val
            elif kind=='flat':flat+=val
            else:raise ValueError('Unknown modifier kind')
            additions.append({'source':str(item.get('source','manual'))[:200],'kind':kind,'value':val})
        result[name]=base*(1+percent/100)+flat
        provenance[name]=additions
    return {'format':'wosb-config-hypothesis-v1','base_stats':base_stats,'modeled_stats':result,
            'modifiers':provenance,'stacking_rule':'additive percentage then flat (USER HYPOTHESIS)',
            'game_authoritative':False}


def sail_condition_observations(rows):
    """Tabulate observed speed versus sail health; avoid inferring causality."""
    if len(rows)<3:raise ValueError('Three or more independent observations required')
    observations=[]
    for x in rows:
        health=float(x['sail_health_pct']);speed=float(x['observed_speed'])
        if not math.isfinite(health+speed) or health<0 or health>100 or speed<0:raise ValueError('Invalid sail observation')
        observations.append({'health_pct':health,'speed':speed,'wind_angle_deg':x.get('wind_angle_deg'),
                             'source':str(x.get('source','manual'))[:200]})
    healths=[x['health_pct'] for x in observations];speeds=[x['speed'] for x in observations]
    mean_h=statistics.mean(healths);mean_s=statistics.mean(speeds)
    var=sum((x-mean_h)**2 for x in healths)
    slope=sum((h-mean_h)*(s-mean_s) for h,s in zip(healths,speeds))/var if var>0 else None
    return {'format':'wosb-sail-observation-v1','observations':observations,
            'observed_speed_slope_per_sail_health_point':slope,'warning':'Only sample association. Wind, loadout, current, damage and server modifiers may confound this relationship.'}
