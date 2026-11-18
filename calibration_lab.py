"""Portable, opt-in empirical damage observations (never claims a game formula)."""
import csv
import math
from pathlib import Path


def load_trials(path,max_rows=10_000):
    source=Path(path)
    if source.stat().st_size>4*1024*1024:raise ValueError('Combat trials CSV exceeds 4 MB')
    rows=[]
    with source.open('r',encoding='utf-8-sig',newline='') as stream:
        reader=csv.DictReader(stream)
        required={'weapon','ammo','target_ship','target_armor_region','observed_hp_damage','range_m','impact_angle_deg'}
        if not required.issubset(set(reader.fieldnames or [])):raise ValueError('Combat trials CSV is missing required columns')
        for row in reader:
            if len(rows)>=max_rows:break
            try:
                damage=float(row['observed_hp_damage']);dist=float(row['range_m']);angle=float(row['impact_angle_deg'])
                if not all(map(math.isfinite,(damage,dist,angle))) or damage<0 or dist<0 or not 0<=angle<=90:continue
            except (TypeError,ValueError):continue
            rows.append({'weapon':str(row['weapon'])[:140], 'ammo':str(row['ammo'])[:140],
                         'target_ship':str(row['target_ship'])[:140],
                         'zone':str(row['target_armor_region'])[:60].lower().strip(),
                         'damage':damage,'distance':dist,'angle':angle,
                         'game_version':str(row.get('game_version') or '')[:80]})
    return rows
