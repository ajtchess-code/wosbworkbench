#!/usr/bin/env python3
"""Optional controlled combat observations for WoSB mechanic validation.

No network access, game hooking or automated gameplay. Records are entered by
researchers from legitimate gameplay observation. Aggregate comparisons do not
prove causality or reconstruct a hidden server formula.
"""
import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path

COLUMNS=['trial_id','session','timestamp_utc','weapon','ammo','shooter_ship','target_ship',
         'range_m','impact_angle_deg','armor_rating','target_armor_region','weapon_buff',
         'crew_buffs','raw_damage_if_known','observed_hp_damage','normal_fire','large_fire',
         'fire_duration_s','damage_over_time','flooding','target_hp_before','target_hp_after',
         'game_version','notes']
ALLOWED_GROUPS={'weapon','ammo','shooter_ship','target_ship','target_armor_region','weapon_buff','crew_buffs','game_version'}


def create_template(dest):
    dest=Path(dest)
    if dest.exists():raise FileExistsError('Refusing to overwrite an existing combat trial sheet')
    dest.parent.mkdir(parents=True,exist_ok=True)
    with dest.open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=COLUMNS);w.writeheader()
    return dest


def maybe_float(value):
    if value is None:return None
    t=str(value).strip()
    if not t:return None
    try:
        v=float(t)
        return v if math.isfinite(v) else None
    except ValueError:return None


def maybe_bool(value):
    if value is None:return None
    val=str(value).strip().lower()
    if val in {'1','true','yes','y','on'}:return True
    if val in {'0','false','no','n','off'}:return False
    return None


def wilson(success,n,z=1.96):
    if n<=0:return None
    p=success/n;z2=z*z;denom=1+z2/n
    center=(p+z2/(2*n))/denom
    half=z*math.sqrt((p*(1-p)+z2/(4*n))/n)/denom
    return [round(max(0,center-half),5),round(min(1,center+half),5)]


def stats(rows):
    damages=[maybe_float(x.get('observed_hp_damage')) for x in rows]
    damages=[v for v in damages if v is not None and v>=0]
    fires=[maybe_bool(x.get('large_fire')) for x in rows]
    fires=[v for v in fires if v is not None]
    normal=[maybe_bool(x.get('normal_fire')) for x in rows]
    normal=[v for v in normal if v is not None]
    p_large=sum(fires)/len(fires) if fires else None
    avg=sum(damages)/len(damages) if damages else None
    sd=(math.sqrt(sum((v-avg)**2 for v in damages)/(len(damages)-1)) if len(damages)>1 else None)
    return {'trials':len(rows),'observed_damage_count':len(damages),
            'mean_hp_damage':round(avg,5) if avg is not None else None,
            'damage_min':min(damages) if damages else None,
            'damage_max':max(damages) if damages else None,
            'damage_sample_stddev':round(sd,5) if sd is not None else None,
            'large_fire_observations':len(fires),'large_fire_occurrences':sum(fires),
            'large_fire_rate':round(p_large,5) if p_large is not None else None,
            'large_fire_95pct_wilson_interval':wilson(sum(fires),len(fires)),
            'normal_fire_observations':len(normal),'normal_fire_occurrences':sum(normal)}


def analyze_trials(src,output,group_by=('weapon','ammo','target_ship')):
    src=Path(src);output=Path(output)
    if any(k not in ALLOWED_GROUPS for k in group_by):raise ValueError('Invalid grouping column')
    if src.resolve()==output.resolve():raise ValueError('Report cannot overwrite trial data')
    with src.open(encoding='utf-8-sig',newline='') as f:
        r=csv.DictReader(f)
        if not {'observed_hp_damage','large_fire'}.issubset(r.fieldnames or []):
            raise ValueError('Missing observed_hp_damage/large_fire columns')
        rows=[item for item in r if any((v or '').strip() for v in item.values())]
    groups=defaultdict(list)
    for x in rows:
        groups[tuple((x.get(col) or '[unknown]').strip() or '[unknown]' for col in group_by)].append(x)
    report={'method':'Descriptive grouped statistics and Wilson 95% interval; not a verified game formula',
            'total':stats(rows),'group_by':list(group_by),'groups':[],
            'study_advice':['Change one combat variable at a time and hold other conditions constant.',
                            'Use many trials per condition. Different target ships, buffs, impact locations and game versions may confound results.',
                            'A 95% Wilson interval describes sampling uncertainty, not a proof of independence or causality.',
                            'Do not infer a server formula solely from matching means or observed ignition frequencies.']}
    for key,items in sorted(groups.items()):
        report['groups'].append({'conditions':dict(zip(group_by,key)),**stats(items)})
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='action',required=True)
    init=sub.add_parser('template',help='Create an empty, editable combat-observation CSV')
    init.add_argument('--output',required=True)
    run=sub.add_parser('analyze',help='Summarize trial observations without networking or gameplay hooks')
    run.add_argument('--input',required=True)
    run.add_argument('--output',required=True)
    run.add_argument('--group-by',nargs='+',default=['weapon','ammo','target_ship'])
    args=p.parse_args()
    if args.action=='template':print('Created',create_template(args.output))
    else:print(json.dumps(analyze_trials(args.input,args.output,args.group_by)['total'],indent=2))
if __name__=='__main__':main()
