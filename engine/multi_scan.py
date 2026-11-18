#!/usr/bin/env python3
"""Concurrent WoSB analysis of the three standard Windows folders.

Runs one independent worker per existing unique folder, handles missing ones,
keeps logs and checkpoints separated; never writes to client directories.
"""
import argparse
import html
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from v3_progress import atomic_json

DEFAULTS = [
    ('Game', r'C:\Games\World of Sea Battle'),
    ('Launcher', r'C:\Games\Wosb Launcher'),
    ('Steam', r'C:\Program Files (x86)\Steam\steamapps\common\World of Sea Battle'),
]


def targets(paths=None):
    options = [(f'Scan{i+1}', value) for i,value in enumerate(paths)] if paths else DEFAULTS
    found, missing, seen = [], [], set()
    for label, raw in options:
        location = Path(raw).expanduser().resolve()
        if not location.is_dir():
            missing.append({'label':label,'root':str(location),'status':'missing'})
            continue
        key = os.path.normcase(str(location)).casefold()
        if key in seen:
            missing.append({'label':label,'root':str(location),'status':'duplicate_path'})
            continue
        seen.add(key)
        found.append((label,location))
    return found, missing


def status_html(status):
    lines=[]
    for item in status:
        label=html.escape(item['label']); state=html.escape(item.get('status','unknown'))
        lines.append('<tr><td>'+label+'</td><td>'+state+'</td><td>'+html.escape(item.get('stage',''))+'</td>'
                     '<td>'+html.escape(str(item.get('done','')))+'/'+html.escape(str(item.get('total','')))
                     +'</td></tr>')
    return ('<!doctype html><html><meta charset="utf-8"><title>WoSB v3 Scan</title>'
            '<style>body{background:#121b2a;color:#edf2f7;font:16px system-ui;padding:25px}'
            'table{border-collapse:collapse;width:100%}td,th{padding:12px;border-bottom:1px solid #53657e}</style>'
            '<h1>World of Sea Battle — v3 Multi-Client Scan</h1>'
            '<p>Static analysis only. Candidate findings are not confirmed gameplay formulas.</p>'
            '<table><tr><th>Target</th><th>Status</th><th>Stage</th><th>Progress</th></tr>'
            +''.join(lines)+'</table><p>Open each installation report for details.</p></html>')


def run(output, paths=None, *, poll=3, extra_args=None):
    out=Path(output).resolve();out.mkdir(parents=True,exist_ok=True)
    work, missing=targets(paths)
    all_status=[dict(x) for x in missing]
    running=[]
    for label,path in work:
        dest=out/label; dest.mkdir(parents=True,exist_ok=True)
        log=dest/'Scan.log'
        stream=log.open('a',encoding='utf-8')
        cmd=[sys.executable,'-u',str(Path(__file__).with_name('analyze_one.py')),
             '--game',str(path),'--output',str(dest)]+list(extra_args or [])
        try:
            proc=subprocess.Popen(cmd,cwd=str(Path(__file__).resolve().parent),
                                  stdout=stream,stderr=subprocess.STDOUT)
        except OSError as e:
            stream.write(str(e)+'\n');stream.close()
            all_status.append({'label':label,'status':'launch_failed','stage':type(e).__name__})
            continue
        running.append({'label':label,'root':str(path),'proc':proc,'stream':stream,'dest':dest})
        all_status.append({'label':label,'status':'running','stage':'start','done':0,'total':0})
    last_print=0
    while True:
        active=False
        for worker in running:
            proc=worker['proc']; label=worker['label']; dest=worker['dest']
            row=next(x for x in all_status if x['label']==label)
            state=dest/'Progress.json'
            if state.exists():
                try:
                    obj=json.loads(state.read_text(encoding='utf-8'))
                    row.update({k:obj[k] for k in ('stage','done','total','updated_utc') if k in obj})
                except (OSError,ValueError):pass
            code=proc.poll()
            if code is None:
                active=True
            elif row['status']=='running':
                row['status']='complete' if code==0 else 'failed'
                row['exit_code']=code
                worker['stream'].close()
        atomic_json(out/'CombinedStatus.json',{'version':'3.0.0','updated_utc':datetime.now(timezone.utc).isoformat(),
                                               'targets':all_status})
        (out/'CombinedReport.html').write_text(status_html(all_status),encoding='utf-8')
        if time.monotonic()-last_print>=5 or not active:
            for row in all_status:
                print(f"{row['label']:10} {row['status']:14} {row.get('stage',''):18} "
                      f"{row.get('done','')}/{row.get('total','')}",flush=True)
            print('Results:',out,flush=True)
            last_print=time.monotonic()
        if not active:break
        time.sleep(poll)
    return 0 if all(x['status'] in ('complete','missing','duplicate_path') for x in all_status) else 1


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--output',default=str(Path(__file__).resolve().parent/'WoSB-v3-Reports'))
    p.add_argument('--path',action='append',help='Custom target (repeatable); defaults to 3 known installations')
    p.add_argument('--no-check-images',action='store_true')
    p.add_argument('--no-decode-xnb',action='store_true')
    a=p.parse_args()
    args=[]
    if a.no_check_images:args.append('--no-check-images')
    if a.no_decode_xnb:args.append('--no-decode-xnb')
    return run(a.output,a.path,extra_args=args)

if __name__=='__main__':sys.exit(main())
