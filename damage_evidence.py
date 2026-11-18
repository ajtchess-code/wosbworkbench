"""Source-typed empirical WoSB damage observations and readable 2-D evidence maps.

No server formula is inferred. A heatmap cell is blank until *three independent*
measured hits of the same weapon/ammo/target and shot type are available.
"""
from __future__ import annotations

import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

MAX_CSV=8*1024*1024
COLUMNS=('trial_id','timestamp_utc','shooter_ship','target_ship','weapon','ammo',
         'shot_type','target_armor_region','range_m','impact_angle_deg',
         'target_hp_before','target_hp_after','observed_hp_damage','game_version','notes')
ZONES=('bow','port','starboard','side','stern','sails','mast','other')


def clean_observation(row):
    def text(k):return str(row.get(k) or '').strip()[:130]
    try:
        distance=float(row['range_m']);angle=float(row['impact_angle_deg']);damage=float(row['observed_hp_damage'])
    except (TypeError,ValueError,KeyError):return None
    if any(not math.isfinite(v) for v in (distance,angle,damage)) or distance<0 or not 0<=angle<=90 or damage<0:return None
    region=text('target_armor_region').lower();shot=text('shot_type').lower() or 'single'
    if region not in ZONES:region='other'
    if shot not in ('single','broadside','mortar','heavy-mortar','barrel','other'):shot='other'
    if not (text('weapon') and text('ammo') and text('target_ship')):return None
    a={'target_ship':text('target_ship'),'shooter_ship':text('shooter_ship'),
       'weapon':text('weapon'),'ammo':text('ammo'),'shot_type':shot,'region':region,
       'distance':distance,'angle':angle,'damage':damage,'source':'user_recorded_gameplay',
       'game_version':text('game_version'),'notes':text('notes')}
    return a


def load_observations(csv_path):
    path=Path(csv_path)
    if path.stat().st_size>MAX_CSV:raise ValueError('Trial evidence file too large')
    observations=[];rejected=0
    with path.open('r',encoding='utf-8-sig',newline='') as f:
        for i,row in enumerate(csv.DictReader(f)):
            if i>=50_000:raise ValueError('Too many recorded trials')
            item=clean_observation(row)
            if item:observations.append(item)
            else:rejected+=1
    return {'observations':observations,'rejected_rows':rejected}


def angle_bin(angle):
    return min(75,int(angle//15)*15)


def aggregate_observations(records,*,min_trials=3):
    cells=defaultdict(list)
    for r in records:
        key=(r['target_ship'].casefold(),r['weapon'].casefold(),r['ammo'].casefold(),
             r['shot_type'],r['region'],angle_bin(r['angle']),int(r['distance']//50)*50,r['game_version'].casefold())
        cells[key].append(r['damage'])
    results=[]
    for key,values in sorted(cells.items()):
        n=len(values);mean=statistics.mean(values);stdev=statistics.stdev(values) if n>1 else None
        interval=(1.96*stdev/math.sqrt(n)) if n>=3 else None
        results.append({'target_ship':key[0],'weapon':key[1],'ammo':key[2],
          'shot_type':key[3],'region':key[4],'angle_from':key[5],'angle_to':min(90,key[5]+15),
          'range_from':key[6],'range_to':key[6]+50,'game_version':key[7],
          'n':n,'mean_hp':round(mean,2) if n>=min_trials else None,
          'sample_mean_not_validated':round(mean,2),
          'observed_min':min(values),'observed_max':max(values),
          'confidence_interval_95_approx':[round(mean-interval,2),round(mean+interval,2)] if interval is not None else None,
          'status':'measured_cell_mean' if n>=min_trials else 'insufficient_samples'})
    return results


def write_trial_template(path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8-sig',newline='') as f:csv.writer(f).writerow(COLUMNS)
    return path


def generate_trial_dashboard(csv_path,output):
    source=load_observations(csv_path);cells=aggregate_observations(source['observations'])
    payload=json.dumps({'cells':cells,'rows':len(source['observations']),'rejected':source['rejected_rows']},ensure_ascii=False).replace('<','\\u003c')
    html='''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>WoSB · Measured Damage</title>
<style>:root{color-scheme:dark;font:15px system-ui;background:#0a1220;color:#e8f3fc}body{max-width:1250px;margin:35px auto;padding:0 20px}h1{color:#72d7e0}.note{padding:14px;border-left:3px solid #edbf84;background:#172b40}label{display:inline-block;margin:10px 15px 10px 0}select{background:#17354e;color:white;padding:9px;border-radius:8px;border:1px solid #5a8198}canvas{max-width:100%;background:#112439;border:1px solid #3a6178;border-radius:12px}table{width:100%;border-collapse:collapse;margin-top:24px}td,th{border-bottom:1px solid #2d4559;padding:11px;text-align:left}th{color:#aad6dd}small{color:#a9bfd4}</style></head>
<body><h1>⚓ Measured Damage Atlas</h1><p>Recorded in-game hits, organized by ship, weapon, ammo, shot type and impact angle.</p>
<div class="note"><strong>Evidence only.</strong> Colored cells require at least three measured hits with matching equipment and region. Grey means untested. This map is a 2-D summary of recorded trials, not a reconstructed server formula, a 3-D hull heatmap or a guaranteed damage prediction. Different ranges and game versions are kept in separate evidence groups and filter selections. Player bonuses, target conditions and other unrecorded influences may still vary.</div>
<p id="stats"></p><label>Target ship <select id="ship"></select></label><label>Weapon <select id="weapon"></select></label><label>Ammo <select id="ammo"></select></label><label>Shot type <select id="shot"></select></label><label>Range (game units) <select id="range"></select></label><label>Client build <select id="version"></select></label>
<canvas id="map" width="1050" height="465" aria-label="Damage by target region and angle"></canvas><div id="details"></div>
<script>const DATA=__PAYLOAD__,keys=['ship','weapon','ammo','shot','range','version'],fields=['target_ship','weapon','ammo','shot_type','range_from','game_version'],sels=keys.map(k=>document.getElementById(k));
for(let i=0;i<keys.length;i++){let vals=[...new Set(DATA.cells.map(c=>c[fields[i]]))].sort();sels[i].innerHTML='<option value="">All</option>';for(const v of vals){let o=document.createElement('option');o.value=v;o.textContent=i===4?`${v}–${Number(v)+50}`:v;sels[i].appendChild(o)}sels[i].onchange=draw}
const zones=['bow','port','starboard','side','stern','sails','mast','other'],c=document.getElementById('map'),ctx=c.getContext('2d');
function draw(){let data=DATA.cells.filter(x=>sels.every((s,i)=>!s.value||x[fields[i]]===s.value));
ctx.clearRect(0,0,c.width,c.height);ctx.font='14px system-ui';ctx.fillStyle='#cee4f5';ctx.fillText('Observed hull / sail HP loss — impact obliquity, degrees',210,27);
const max=Math.max(1,...data.filter(r=>r.mean_hp!==null).map(r=>r.mean_hp)),left=140,top=60,w=140,h=43;
for(let x=0;x<6;x++){ctx.fillStyle='#9dbece';ctx.fillText(`${x*15}–${x*15+15}°`,left+x*w+42,top-12)}
for(let y=0;y<zones.length;y++){ctx.fillStyle='#d7eafa';ctx.fillText(zones[y],20,top+y*h+25);
for(let x=0;x<6;x++){let matching=data.filter(r=>r.region===zones[y]&&r.angle_from===x*15&&r.mean_hp!==null);let n=matching.reduce((a,r)=>a+r.n,0);let mean=n?matching.reduce((a,r)=>a+r.mean_hp*r.n,0)/n:null;
const intensity=mean===null?0:Math.max(0,Math.min(1,mean/max));ctx.fillStyle=mean===null?'#344454':`rgb(${Math.round(42+180*intensity)},${Math.round(151-95*intensity)},${Math.round(163-100*intensity)})`;
ctx.fillRect(left+x*w,top+y*h,w-3,h-3);ctx.fillStyle=mean===null?'#a6bac8':'#ffffff';ctx.fillText(mean===null?'No evidence':`${mean.toFixed(1)} HP · n=${n}`,left+x*w+9,top+y*h+25)}}
let table='<table><thead><tr><th>Area</th><th>Angle</th><th>Range</th><th>Tests</th><th>Observed mean HP</th><th>95% interval (approx.)</th><th>Evidence</th></tr></thead><tbody>';
for(const x of data){let ci=x.confidence_interval_95_approx;table+=`<tr><td>${x.region}</td><td>${x.angle_from}–${x.angle_to}°</td><td>${x.range_from}–${x.range_to}</td><td>${x.n}</td><td>${x.mean_hp===null?'Not enough trials':x.mean_hp}</td><td>${ci?ci.join(' – '):'—'}</td><td>${x.status}</td></tr>`}table+='</tbody></table>';
document.getElementById('details').innerHTML=table;document.getElementById('stats').textContent=DATA.rows+' accepted measurements · '+DATA.rejected+' rejected rows · '+data.length+' evidence cells';}
draw();</script></body></html>'''.replace('__PAYLOAD__',payload)
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(html,encoding='utf-8');return output
