"""Controlled combat experimentation with explicit evidence provenance.

Stored HP values are user-entered or sourced from an identified observation.
No inference is made about exact server-authoritative damage mechanics.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import csv, hashlib, io, json, math, sqlite3, statistics, uuid, zipfile

SCHEMA='''
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS experiments (
 id TEXT PRIMARY KEY, recorded_utc TEXT NOT NULL, ship TEXT NOT NULL,
 target TEXT NOT NULL, weapon TEXT NOT NULL, ammunition TEXT NOT NULL,
 range_units REAL, impact_angle_deg REAL, target_armor REAL,
 notes TEXT NOT NULL, provenance TEXT NOT NULL, dataset_version TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS observations (
 id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL REFERENCES experiments(id),
 observed_utc TEXT NOT NULL, hp_before REAL NOT NULL, hp_after REAL NOT NULL,
 hits INTEGER NOT NULL, source TEXT NOT NULL, evidence_ref TEXT NOT NULL,
 verified_by_human INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_observations_exp ON observations(experiment_id);
'''


def _finite(value,*,minimum=None,maximum=None):
    if value is None or value=='':return None
    v=float(value)
    if not math.isfinite(v):raise ValueError('Nonfinite measurement')
    if minimum is not None and v<minimum:raise ValueError('Below allowed minimum')
    if maximum is not None and v>maximum:raise ValueError('Above allowed maximum')
    return v


def _utc():return datetime.now(timezone.utc).isoformat(timespec='seconds')


def open_db(path):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(p)
    conn.row_factory=sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def add_experiment(conn,*,ship,target,weapon,ammunition,range_units=None,impact_angle_deg=None,
                   target_armor=None,notes='',provenance='manual',dataset_version='unverified'):
    for value in (ship,target,weapon,ammunition):
        if not str(value).strip() or len(str(value))>200:raise ValueError('Ship/target/weapon/ammunition required, max 200 chars')
    distance=_finite(range_units,minimum=0)
    angle=_finite(impact_angle_deg,minimum=0,maximum=89.99)
    armor=_finite(target_armor,minimum=0)
    eid=str(uuid.uuid4())
    with conn:conn.execute('INSERT INTO experiments VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
        (eid,_utc(),ship,target,weapon,ammunition,distance,angle,armor,str(notes)[:4000],
         str(provenance)[:250],str(dataset_version)[:120]))
    return eid


def add_observation(conn,experiment_id,*,hp_before,hp_after,hits=1,source='manual',evidence_ref='',human_verified=False):
    before=_finite(hp_before,minimum=0);after=_finite(hp_after,minimum=0)
    hits=int(hits)
    if before is None or after is None or hits<1 or hits>200:raise ValueError('Invalid HP or hit count')
    if after>before:raise ValueError('HP after exceeds HP before: heals and repairs require a separate observation type')
    if not conn.execute('SELECT 1 FROM experiments WHERE id=?',(experiment_id,)).fetchone():raise ValueError('Unknown experiment')
    oid=str(uuid.uuid4())
    with conn:conn.execute('INSERT INTO observations VALUES (?,?,?,?,?,?,?,?,?)',
        (oid,experiment_id,_utc(),before,after,hits,str(source)[:200],str(evidence_ref)[:450],bool(human_verified)))
    return oid


def experiment_report(conn):
    sql='''SELECT e.id,e.ship,e.target,e.weapon,e.ammunition,e.range_units,e.impact_angle_deg,e.target_armor,
    e.provenance,e.dataset_version,o.hp_before,o.hp_after,o.hits,o.source,o.evidence_ref,o.verified_by_human
    FROM experiments e LEFT JOIN observations o ON e.id=o.experiment_id ORDER BY e.id'''
    records=[];grouped=defaultdict(list)
    for row in conn.execute(sql):
        d=dict(row)
        if d['hp_before'] is not None:
            damage=d['hp_before']-d['hp_after']
            d['measured_damage_per_hit']=damage/d['hits']
            key=tuple(d[k] for k in ('ship','target','weapon','ammunition','range_units','impact_angle_deg','target_armor'))
            grouped[key].append(d['measured_damage_per_hit'])
        records.append(d)
    summary=[]
    for key,values in grouped.items():
        mean=statistics.mean(values);stdev=statistics.stdev(values) if len(values)>1 else None
        ci=(1.96*stdev/math.sqrt(len(values))) if stdev is not None else None
        summary.append({'configuration':dict(zip(('ship','target','weapon','ammunition','range_units','impact_angle_deg','target_armor'),key)),
                        'observations':len(values),'hp_per_hit_mean':mean,'hp_per_hit_sample_stddev':stdev,
                        'approximate_95pct_half_width':ci,'confidence_interval_note':'normal approximation; repeatable independent observations required' if ci is not None else 'insufficient repeats'})
    return {'format':'wosb-experiment-analysis-v1','experiments':len({r['id'] for r in records}),
            'observations':sum(r['hp_before'] is not None for r in records),
            'groups':summary,'entries':records,
            'limitations':'HP is observed or manually entered. Recorded factors are not guaranteed to control unobserved server conditions.'}


def compare_hypotheses(report,cannon,ammo):
    """Rudimentary cross-configuration diagnostics, no automatic certification."""
    from damage_hypotheses import calculate
    results=[]
    for item in report['groups']:
        c=item['configuration']
        if c['target_armor'] is None or c['impact_angle_deg'] is None:continue
        prediction=calculate(cannon,ammo,target_armor=c['target_armor'],angle_deg=c['impact_angle_deg'])
        results.append({'configuration':c,'mean_hp_per_hit':item['hp_per_hit_mean'],
                        'hard_gate_index':prediction['hypotheses']['index_if_threshold_model'],
                        'smooth_index':prediction['hypotheses']['index_if_smooth_model'],
                        'note':'Indices are not HP; no error metric until calibrated against an independent reference.'})
    return results


def export_experiments(conn,zip_path,*,include_csv=True):
    """Evidence-only portable ZIP. Does not embed game textures, raw PCAP or video."""
    report=experiment_report(conn)
    data=json.dumps(report,indent=2,ensure_ascii=False).encode('utf-8')
    files={'experiments.json':data,'README.txt':b'WoSB local experiment metadata. No raw packet/video contents or game binaries. Measurements require human verification.\n'}
    if include_csv:
        out=io.StringIO();columns=('id','ship','target','weapon','ammunition','range_units','impact_angle_deg','target_armor','hp_before','hp_after','hits','source','verified_by_human','measured_damage_per_hit')
        writer=csv.DictWriter(out,fieldnames=columns,extrasaction='ignore');writer.writeheader();writer.writerows(report['entries'])
        files['experiments.csv']=out.getvalue().encode('utf-8')
    manifest={'format':'wosb-experiment-export-v1','created_utc':_utc(),
              'files':[{'name':name,'bytes':len(content),'sha256':hashlib.sha256(content).hexdigest()} for name,content in sorted(files.items())]}
    output=Path(zip_path);output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for name,content in files.items():z.writestr(name,content)
        z.writestr('manifest.json',json.dumps(manifest,indent=2))
    return {'output':str(output),'manifest':manifest}
