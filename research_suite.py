"""Local Workbench health, workspace, asset coverage and release-readiness utilities.

No game executable/DLL is executed. All scanning is read-only. User data lives in
an explicit output directory. This module never guesses official game mechanics.
"""
from __future__ import annotations
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from contextlib import closing
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import zipfile

MAX_WORKSPACE = 2_000_000


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def tool_check(name):
    path = shutil.which(name)
    if not path and name in ('ffmpeg', 'ffprobe'):
        from gameplay_capture import find_video_tool
        path = find_video_tool(name)
    if not path and name=='tshark':
        from network_lab import find_tshark
        path = find_tshark()
    return {'found': bool(path), 'path': path, 'status': 'available' if path else 'missing'}


def _find_client_executable(root, name='WorldOfSeaBattleClient.exe', max_depth=4, max_dirs=4000):
    """Bounded search: rglob() walked every file of a multi-GB install (and of
    whatever folder the user typed) on the UI thread."""
    root=Path(root);seen=0
    target=name.casefold()
    for current,dirs,files in os.walk(root):
        seen+=1
        if any(f.casefold()==target for f in files):return True
        depth=len(Path(current).relative_to(root).parts)
        if depth>=max_depth or seen>=max_dirs:
            dirs[:]=[]
    return False


def setup_report(*,roots=(),required_free_gb=3):
    """Show what is installed, without silently modifying system settings."""
    tools = {x: tool_check(x) for x in ('ffmpeg', 'ffprobe', 'tshark')}
    tools['python'] = {'found': True, 'path': sys.executable, 'version': sys.version.split()[0]}
    tools['pyinstaller'] = {'found': __import__('importlib').util.find_spec('PyInstaller') is not None}
    disk = shutil.disk_usage(Path.home())
    game_roots = []
    for item in roots:
        p = Path(item).expanduser()
        game_roots.append({'path': str(p), 'exists': p.is_dir(),
                           'client_executable_found': _find_client_executable(p) if p.is_dir() and len(str(p)) < 500 else False})
    return {'format':'wosb-setup-check-v43','generated_utc':utc_now(),
            'platform':sys.platform,'windows_supported':os.name=='nt',
            'tools':tools,'disk_free_gb':round(disk.free/(1024**3),2),
            'disk_recommendation': 'space available' if disk.free >= required_free_gb*(1024**3) else 'free disk space before preserving all game assets',
            'game_roots':game_roots,'gpu_visual_test':'requires a real graphics session; not inferred by this preflight',
            'npc_damage_formula':'not validated'}


def save_workspace(path, workspace):
    allowed = ('selected_ship_id','selected_cannon_id','selected_ammo_id','ship_design_id','camera','research_notes','selected_tab','shot_settings','sailing_settings','updated_utc')
    if not isinstance(workspace,dict):raise ValueError('Expected a workspace object')
    output={k:workspace[k] for k in allowed if k in workspace}
    output['updated_utc']=utc_now()
    blob=json.dumps({'format':'wosb-workspace-v43','workspace':output},ensure_ascii=False,indent=2).encode('utf-8')
    if len(blob)>MAX_WORKSPACE:raise ValueError('Workspace too large')
    file=Path(path);file.parent.mkdir(parents=True,exist_ok=True)
    if file.exists():shutil.copy2(file,file.with_suffix(file.suffix+'.bak'))
    with tempfile.NamedTemporaryFile(dir=file.parent,mode='wb',delete=False) as fp:
        tmp=Path(fp.name);fp.write(blob)
    tmp.replace(file)
    return file


def load_workspace(path):
    file=Path(path)
    if not file.exists():return {}
    if file.stat().st_size>MAX_WORKSPACE:raise ValueError('Workspace too large')
    data=json.loads(file.read_text(encoding='utf-8'))
    if data.get('format')!='wosb-workspace-v43' or not isinstance(data.get('workspace'),dict):raise ValueError('Unrecognized workspace')
    return data['workspace']


def asset_coverage(ledger_path, *, max_records=200000):
    """Read v4 FullRecovery AssetLedger JSONL without loading source images."""
    ledger=Path(ledger_path)
    total=0;status=Counter();kind=Counter();reasons=Counter();sample=[]
    with ledger.open('r',encoding='utf-8') as src:
        for line in src:
            if not line.strip():continue
            total+=1
            if total>max_records:raise ValueError('Ledger record limit exceeded')
            try:data=json.loads(line)
            except json.JSONDecodeError:
                status['unreadable_json']+=1;continue
            state=str(data.get('status') or 'unknown');family=str(data.get('kind') or 'unknown')
            status[state]+=1;kind[f'{family}:{state}']+=1
            if state not in ('decoded','complete','ok'):
                reason=str(data.get('reason') or data.get('error') or 'unspecified')[:150];reasons[reason]+=1
                if len(sample)<80:sample.append({'path':str(data.get('path') or data.get('source') or '')[:200],
                                                 'kind':family,'status':state,'reason':reason})
    return {'format':'wosb-asset-coverage-v43','total':total,'statuses':dict(status),
            'by_kind':dict(kind),'failure_reasons':dict(reasons.most_common()),
            'issue_samples':sample,'caveat':'Indexed or decoded does not imply visually accurate or collision-authoritative'}


def material_coverage(links_file, *, max_records=100000):
    """Summarize unresolved links without falsely certifying exact shader match."""
    total=0;statuses=Counter();missing=[]
    with Path(links_file).open(encoding='utf-8') as f:
        for line in f:
            if not line.strip():continue
            total+=1
            if total>max_records:raise ValueError('Too many material links')
            try:r=json.loads(line)
            except json.JSONDecodeError:statuses['malformed']+=1;continue
            status=str(r.get('status') or ('candidate' if r.get('matched') else 'unknown'))
            statuses[status]+=1
            if ('unmatched' in status or status in ('unknown','missing','false')) and len(missing)<60:
                missing.append({k:r.get(k) for k in ('ship','model','part','material','texture','source') if k in r})
    return {'format':'wosb-material-coverage-v43','references':total,'statuses':dict(statuses),
            'unresolved_samples':missing,'verified_shaders':False}


def release_audit(root, *, source_db=None):
    """Check core local files, critical data tables, wiki assets and generated sources."""
    root=Path(root);critical=['desktop_main.py','workbench_ui.py','wiki_server.py','wiki_site/app.js',
                              'wiki_site/style.css','engine/full_recovery.py','gameplay_capture.py',
                              'engine/recover_everything.py','packaging/Build-Windows.ps1']
    checks=[{'check':name,'pass':(root/name).is_file()} for name in critical]
    script=(root/'wiki_site/app.js');js_bytes=script.stat().st_size if script.is_file() else 0
    checks.append({'check':'wiki JS nonempty','pass':js_bytes>500})
    db=Path(source_db or root/'Starter-Catalog.sqlite3')
    if db.is_file():
        with closing(sqlite3.connect(Path(db).resolve().as_uri()+'?mode=ro',uri=True)) as con:
            tables={x[0] for x in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            checks.append({'check':'catalog articles table','pass':'articles' in tables})
            checks.append({'check':'catalog records table','pass':'records' in tables})
            if 'records' in tables:
                for dataset in ('Cannons','CannonBalls','ShipsToPlay'):
                    count=con.execute('SELECT COUNT(*) FROM records WHERE dataset=?',(dataset,)).fetchone()[0]
                    checks.append({'check':dataset,'pass':count>0,'records':count})
    else:checks.append({'check':'catalog database present','pass':False})
    return {'format':'wosb-release-audit-v43','created_utc':utc_now(),
            'checks':checks,'passed':sum(x['pass'] for x in checks),'failed':sum(not x['pass'] for x in checks),
            'live_capture_validated':False,'windows_build_validated':False,
            'damage_server_formula_verified':False,
            'note':'These checks validate local artifacts and catalog presence, not game-rendering equivalence or live Windows behavior'}


def review_zip(folder,output,*,max_bytes=45*1024*1024):
    """Pack a minimal health report without game assets, raw packets or secrets."""
    root=Path(folder);safe=('Recovery-Status.json','RecoverySummary.md','Combined-Recovery-Status.json',
                             'Client-Differences-Summary.json','Recovery-Readiness.json')
    target=Path(output);target.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as archive:
        for name in safe:
            path=root/name
            if path.is_file() and path.stat().st_size<=5*1024*1024:archive.write(path,name)
        archive.writestr('README.txt','Local WoSB recovery status only. No PCAP, tokens, video, extracted game binary or raw assets.\n')
    if target.stat().st_size>max_bytes:
        target.unlink(missing_ok=True);raise ValueError('Review cap exceeded')
    return target


def cli(argv=None):
    import argparse
    p=argparse.ArgumentParser();p.add_argument('command',choices=('check','release','assets','materials'))
    p.add_argument('--root',default=str(Path(__file__).parent));p.add_argument('--input');p.add_argument('--output')
    args=p.parse_args(argv)
    if args.command=='check':result=setup_report()
    elif args.command=='release':result=release_audit(args.root)
    elif args.command=='assets':result=asset_coverage(args.input)
    else:result=material_coverage(args.input)
    if args.output:Path(args.output).write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2));return 0
if __name__=='__main__':raise SystemExit(cli())
