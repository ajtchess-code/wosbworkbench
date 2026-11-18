"""Source-tree and release artifact verification; no claim of Windows runtime test."""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import hashlib,json,os,zipfile

EXCLUDED_PARTS={'.git','.build-venv','dist','build','__pycache__','.pytest_cache','.idea','.vscode'}
EXCLUDED_SUFFIXES={'.pyc','.pyo','.pcap','.pcapng','.mp4','.mov','.avi','.fxb'}
MAX_FILES=10000
MAX_SINGLE_FILE=256*1024*1024


def iter_release_files(root):
    base=Path(root).resolve(strict=True);count=0
    for p in sorted(base.rglob('*')):
        if any(part in EXCLUDED_PARTS for part in p.relative_to(base).parts):continue
        if p.is_symlink():raise ValueError('Symlinks not supported: '+str(p))
        if not p.is_file() or p.suffix.lower() in EXCLUDED_SUFFIXES:continue
        if p.name.endswith(('-wal','-shm','.partial','.tmp')):continue
        size=p.stat().st_size
        if size>MAX_SINGLE_FILE:raise ValueError('Oversized release file: '+str(p))
        count+=1
        if count>MAX_FILES:raise ValueError('Release has too many files')
        yield p,p.relative_to(base).as_posix()


def make_manifest(root,*,version=None,python_compile=True):
    if version is None:
        from workbench_db import VERSION as version
    root=Path(root)
    report={'format':'wosb-source-manifest-v1','version':version,
            'generated_utc':datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'files':[],'checks':[],
            'validation_limits':{'windows_executable_built':False,'live_game_client_tested':False,
                                 'gpu_shader_parity_tested':False,'exact_server_damage_verified':False}}
    for p,rel in iter_release_files(root):
        data=p.read_bytes();report['files'].append({'path':rel,'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)})
    files={x['path'] for x in report['files']}
    for rel in ('desktop_main.py','workbench_ui.py','engine/full_recovery.py','engine/xnb_geometry.py',
                'gameplay_capture.py','packaging/Build-Windows.ps1','advanced_geometry.py',
                'advanced_network.py','advanced_assets.py','advanced_experiments.py',
                'advanced_sailing.py','advanced_catalog.py','advanced_release.py'):
        report['checks'].append({'item':rel,'passed':rel in files})
    if python_compile:
        bad=[]
        for p,rel in iter_release_files(root):
            if p.suffix!='.py':continue
            try:compile(p.read_bytes(),str(p),'exec')
            except SyntaxError as exc:bad.append({'path':rel,'reason':str(exc)})
        report['checks'].append({'item':'all Python sources compile','passed':not bad,'errors':bad})
    report['readiness']='source-structure-checks-passed' if all(c['passed'] for c in report['checks']) else 'failed-source-checks'
    return report


def audit_frozen_runtime(bundle_root, *,version=None):
    if version is None:
        from workbench_db import VERSION as version
    """Check resources in a frozen install; cannot substitute for live Windows QA."""
    root=Path(bundle_root)
    checks=[]
    for rel in ('Starter-Catalog.sqlite3','Research-Ballistics-Catalog.json',
                'viewer/ship_viewer.html','wiki_site/app.js','engine/xnb_geometry.py'):
        checks.append({'item':rel,'present':(root/rel).is_file()})
    return {'format':'wosb-frozen-runtime-check-v1','version':version,
            'checks':checks,'checks_passed':sum(x['present'] for x in checks),
            'checks_failed':sum(not x['present'] for x in checks),
            'build_executed_on_this_machine':False,'live_capture_validated':False,
            'rendering_parity_validated':False,'note':'A resource presence audit is not an end-to-end Windows installation test'}


def build_source_zip(root,zip_path,*,version=None):
    if version is None:
        from workbench_db import VERSION as version
    base=Path(root).resolve(strict=True);destination=Path(zip_path).resolve()
    manifest=make_manifest(base,version=version)
    if manifest['readiness']!='source-structure-checks-passed':raise ValueError('Source checks failed')
    destination.parent.mkdir(parents=True,exist_ok=True)
    temp_zip=destination.with_name(destination.name+'.partial')
    with zipfile.ZipFile(temp_zip,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as z:
        for entry in manifest['files']:
            p=base/entry['path']
            z.write(p,f'WoSB-Workbench-v{version}/'+entry['path'])
        z.writestr(f'WoSB-Workbench-v{version}/SOURCE-MANIFEST-v{version}.json',json.dumps(manifest,indent=2))
    with zipfile.ZipFile(temp_zip) as z:
        corrupted=z.testzip()
        if corrupted:raise IOError('Source ZIP corrupt at '+corrupted)
    os.replace(temp_zip,destination)
    return {'zip':str(destination),'files':len(manifest['files']),'sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),
            'source_checks':manifest['checks'],'limitations':manifest['validation_limits']}
