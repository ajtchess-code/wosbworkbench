#!/usr/bin/env python3
"""Single command for multiple local WoSB installations and compact audit exports.

Every client path is read-only. Scan archives and temporary outputs are written
outside the installation. A failed installation does not stop subsequent scans.
No game process is hooked and no authentication or server endpoint is accessed.
"""
from __future__ import annotations
from contextlib import closing
import argparse
from datetime import datetime,timezone
import hashlib,json,os,sqlite3,sys
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED

DEFAULTS=(r'C:\Games\World of Sea Battle',r'C:\Games\Wosb Launcher',
          r'C:\Program Files (x86)\Steam\steamapps\common\World of Sea Battle')
MAX_ZIP=45*1024*1024


def discover(paths=(),*,environ=None):
    """Resolve known installations and caller-selected roots, deduplicated by path."""
    from extract_wosb import locate_game
    found=[];seen=set()
    for entry in [*paths,*DEFAULTS]:
        if not Path(entry).exists():continue
        try:path=Path(locate_game(entry)).resolve()
        except Exception:continue
        key=os.path.normcase(str(path)).casefold()
        if key not in seen:seen.add(key);found.append(path)
    return found


def _rows(root):
    db=root/'Recovery-State.sqlite3'
    if not db.exists():return {}
    with closing(sqlite3.connect(Path(db).resolve().as_uri()+'?mode=ro',uri=True)) as conn:
        return {p:(digest,kind,status) for p,digest,kind,status in conn.execute('SELECT path,sha256,kind,status FROM assets')}


def compare_sources(report_roots):
    """Compare matching relative asset paths; do not assume same installed version."""
    groups={name:_rows(Path(out)) for name,out in report_roots.items()}
    names=list(groups);diff=[]
    if len(names)>1:
        for p in sorted(set().union(*(set(x) for x in groups.values()))):
            present={name:groups[name][p] for name in names if p in groups[name]}
            if len(present)<len(groups) or len({v[0] for v in present.values()})>1:
                diff.append({'relative_path':p,'versions':{name:{'sha256':v[0],'kind':v[1],
                                                          'decode_status':v[2]} for name,v in present.items()}})
    return {'sources':names,'different_paths_or_hashes':len(diff),'items':diff,
            'warning':'File hash differences are build/asset differences, not proof of altered gameplay mechanics.'}


def _write_review(root,summary,comparisons):
    """Small, independent final cross-client research ZIP (without source binaries)."""
    output=root/'One-Click-Review-For-Analysis';output.mkdir(parents=True,exist_ok=True)
    files={'Combined-Recovery-Status.json':json.dumps(summary,indent=2).encode('utf-8'),
           'Client-Differences.json':json.dumps(comparisons,indent=2).encode('utf-8'),
           'README.txt':b'WoSB read-only multi-client recovery review. Source game binaries and images omitted.\n'}
    # Chunk potentially large build-difference metadata at record boundaries.
    record_lines=[json.dumps(v,ensure_ascii=False).encode('utf-8')+b'\n' for v in comparisons.get('items',[])]
    files['Client-Differences.json']=json.dumps({'sources':comparisons['sources'],
          'different_paths_or_hashes':comparisons['different_paths_or_hashes']},indent=2).encode()
    pieces=[];chunk=b''
    for line in record_lines:
        if len(chunk)+len(line)>MAX_ZIP//3 and chunk:pieces.append(chunk);chunk=b''
        chunk+=line
    if chunk:pieces.append(chunk)
    if not pieces:pieces=[b'']
    result=[]
    for i,part in enumerate(pieces,1):
        path=output/f'WoSB-Combined-Review-{i:03d}.zip'
        with ZipFile(path,'w',ZIP_DEFLATED,compresslevel=6) as archive:
            for name,contents in files.items():archive.writestr(name,contents)
            archive.writestr('Client-Differences.jsonl',part)
        if path.stat().st_size>MAX_ZIP:raise ValueError('Review ZIP exceeded cap')
        result.append(path)
    return result


def run_all(output,*,sources=(),recheck=False,preserve=True,payloads=True,code=True,catalog=True,cancel=None):
    from full_recovery import Recovery
    root=Path(output).expanduser().resolve();root.mkdir(parents=True,exist_ok=True)
    installations=discover(sources)
    if not installations:raise ValueError('No supported game installation found. Supply --game explicitly.')
    summary={'format':'wosb-multi-client-recovery-1','created_utc':datetime.now(timezone.utc).isoformat(),
             'read_only':True,'installations':[],'completed':0,'failed':0,
             'server_damage_formula':'not established from client-only data'}
    report_roots={}
    for index,game in enumerate(installations,1):
        if cancel is not None and cancel.is_set():break
        identifier=hashlib.sha256(str(game).casefold().encode('utf-8')).hexdigest()[:12]
        dest=root/('Client-'+str(index)+'-'+identifier);label=game.name+'-'+identifier
        result={'source':str(game),'id':label,'report':str(dest)}
        try:
            status=Recovery(game,dest,force=recheck,preserve=preserve,payloads=payloads,
                            code=code,catalog=catalog,cancel=cancel).run()
            result['result']=status.get('result','unknown')
            result['asset_status_counts']=status.get('asset_status_counts',[])
            result['review_only_zips']=status.get('review_only_zips',[])
            if result['result']=='completed':summary['completed']+=1
            else:summary['failed']+=1
        except Exception as exc:
            result['result']='failed';result['error']=type(exc).__name__+': '+str(exc)[:500]
            summary['failed']+=1
        summary['installations'].append(result);report_roots[label]=dest
        (root/'Combined-Recovery-Status.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    comparison=compare_sources(report_roots)
    (root/'Client-Differences-Summary.json').write_text(json.dumps({k:v for k,v in comparison.items() if k!='items'},indent=2),encoding='utf-8')
    packs=_write_review(root,summary,comparison)
    summary['combined_review_zips']=[str(p.relative_to(root)) for p in packs]
    (root/'Combined-Recovery-Status.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    return summary


def main(argv=None):
    p=argparse.ArgumentParser(description='One button WoSB asset, code and catalog research across local installations')
    p.add_argument('--game',action='append',default=[],help='May be repeated for multiple installations')
    p.add_argument('--output',required=True);p.add_argument('--recheck',action='store_true')
    p.add_argument('--no-preserve',action='store_true');p.add_argument('--no-payloads',action='store_true')
    p.add_argument('--no-code',action='store_true');p.add_argument('--no-catalog',action='store_true')
    args=p.parse_args(argv)
    report=run_all(args.output,sources=args.game,recheck=args.recheck,preserve=not args.no_preserve,
                   payloads=not args.no_payloads,code=not args.no_code,catalog=not args.no_catalog)
    print(json.dumps({'completed':report['completed'],'failed':report['failed'],
                      'combined_review_zips':report['combined_review_zips']},indent=2))
    return 0 if not report['failed'] else 1

if __name__=='__main__':sys.exit(main())
