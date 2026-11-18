#!/usr/bin/env python3
"""Run bounded client analysis and full catalog extraction side by side.

One analysis worker per unique existing installation. Extractor starts only when
archive, localization, and required assemblies exist. Separate output roots and
logs prevent collisions; extraction deliberately does NOT enable --combat.
"""
import argparse
import html
import json
import subprocess
import sys
import time
import threading
from datetime import datetime, timezone
from pathlib import Path
from multi_scan import targets
from v3_progress import atomic_json


def catalog_inputs(root):
    """Return resolved extractable game root, or precise missing prerequisites."""
    for p in (root, root / 'default/game', root / 'game'):
        archive = p / 'CommonData/_lzcommon.wosb'
        if not archive.is_file(): archive = p / '_lzcommon.wosb'
        if not archive.is_file(): continue
        missing=[]
        if not (p/'CommonData/Localization/en-US.lang').is_file() and not (p/'en-US.lang').is_file():
            missing.append('English localization')
        for name in ('Common', 'TheraEngine'):
            if not (p/'Libs'/f'{name}.dll').is_file() and not (p/f'{name}.dll').is_file():
                missing.append(name+'.dll')
        return p, missing
    return None, ['_lzcommon.wosb game data archive']


def unique_catalog_destination(root):
    """Never overwrite older catalog exports on reruns."""
    root=Path(root)
    dest=root/'Catalog'
    if not dest.exists():return dest
    index=2
    while (root/f'Catalog-{index}').exists():index+=1
    return root/f'Catalog-{index}'


def run(output, paths=None, *, poll=2, analysis_extra=None, extraction_extra=None, cancel_event=None):
    out=Path(output).resolve()
    out.mkdir(parents=True,exist_ok=True)
    available,missing=targets(paths)
    states=[]
    for entry in missing:
        for job in ('Analysis','Extraction'):
            states.append({'label':entry['label'],'job':job,'root':entry['root'],
                           'status':entry['status'],'detail':'Input folder not available'})
    running=[]
    for label, root in available:
        game, problems=catalog_inputs(root)
        jobs=[('Analysis', root, ['analyze_one.py','--game',str(root),'--output',str(out/label/'Analysis')]
               +list(analysis_extra or []))]
        if game and not problems:
            # Do not enable --combat: the analysis worker already performs bounded combat research.
            jobs.append(('Extraction',game,['extract_wosb.py','--game',str(game),
                         '--output',str(unique_catalog_destination(out/label))]+list(extraction_extra or [])))
        else:
            states.append({'label':label,'job':'Extraction','root':str(root),'status':'skipped',
                           'detail':'Missing: '+', '.join(problems)})
        for job, source, args in jobs:
            dest=out/label/job
            dest.mkdir(parents=True,exist_ok=True)
            log=(dest/'Worker.log').open('a',encoding='utf-8',buffering=1)
            command=([sys.executable, '--worker', Path(args[0]).stem, *args[1:]]
                     if getattr(sys,'frozen',False) else
                     [sys.executable,'-u',str(Path(__file__).with_name(args[0])),*args[1:]])
            row={'label':label,'job':job,'root':str(source),'status':'running',
                 'stage':'starting','detail':'','done':0,'total':0,'log':str(dest/'Worker.log')}
            states.append(row)
            try:
                proc=subprocess.Popen(command,cwd=str(Path(__file__).resolve().parent),
                                      stdout=log,stderr=subprocess.STDOUT)
                running.append((proc,log,row,dest))
            except OSError as exc:
                row.update(status='failed',detail=str(exc));log.close()
    stop_requested = False
    while True:
        if cancel_event is not None and cancel_event.is_set() and not stop_requested:
            stop_requested=True
            for proc,log,row,dest in running:
                if proc.poll() is None:
                    proc.terminate()
                    row['detail']='Stop requested; completed output retained'
        active=False
        for proc,log,row,dest in running:
            code=proc.poll()
            if code is None:
                active=True
                if row['job']=='Analysis':
                    progress=dest/'Progress.json'
                    if progress.exists():
                        try:
                            p=json.loads(progress.read_text(encoding='utf-8'))
                            for k in ('stage','done','total','current','updated_utc'):
                                if k in p: row[k]=p[k]
                        except (OSError,ValueError):pass
                else:
                    # Extraction progress is collected from stdout, not fabricated as percentages.
                    try:
                        last=(dest/'Worker.log').read_text(encoding='utf-8',errors='replace').splitlines()
                        if last: row['stage']=last[-1][:150]
                    except OSError:pass
            elif row['status']=='running':
                row['status']=('cancelled' if stop_requested else ('complete' if code==0 else 'failed'))
                row['exit_code']=code
                row['detail']=('Finished' if code==0 else 'See Worker.log for error')
                log.close()
        payload={'version':'3.1','updated_utc':datetime.now(timezone.utc).isoformat(),
                 'targets':states}
        atomic_json(out/'CombinedStatus.json',payload)
        rows=''.join('<tr>'+''.join('<td>'+html.escape(str(s.get(k,'')))+'</td>'
                    for k in ('label','job','status','stage','detail'))+'</tr>' for s in states)
        (out/'CombinedReport.html').write_text('<!doctype html><html><meta charset="utf-8">'
             '<title>WoSB Analyzer + Extractor</title><style>body{background:#152033;color:#eef;'
             'font:16px system-ui;padding:25px}td,th{padding:9px;border-bottom:1px solid #667}'
             'table{border-collapse:collapse}</style><h1>WoSB Concurrent Analysis + Extraction</h1>'
             '<p>Refresh for updates. Extraction requires a full game data archive; analysis can scan launcher-only folders.</p>'
             '<table><tr><th>Folder</th><th>Job</th><th>Status</th><th>Stage</th><th>Details</th></tr>'
             +rows+'</table></html>',encoding='utf-8')
        print(' | '.join(f"{s['label']}/{s['job']}: {s['status']} ({s.get('stage','')})" for s in states),flush=True)
        if not active: break
        time.sleep(poll)
    return 1 if any(s['status'] in ('failed','cancelled') for s in states) else 0


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default=str(Path(__file__).resolve().parent/'WoSB-v3-Reports'))
    parser.add_argument('--path',action='append',help='Override default paths; repeatable')
    parser.add_argument('--no-images',action='store_true',help='Disable image export')
    parser.add_argument('--no-check-images',action='store_true',help='Disable image diagnostic decode')
    parser.add_argument('--broad',action='store_true',help='Export expanded client catalog fields')
    args=parser.parse_args()
    return run(args.output,args.path,analysis_extra=['--no-check-images'] if args.no_check_images else None,
               extraction_extra=(['--no-images'] if args.no_images else [])+(['--broad'] if args.broad else []))

if __name__=='__main__':sys.exit(main())
