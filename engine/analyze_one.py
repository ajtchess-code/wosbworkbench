#!/usr/bin/env python3
"""One installation per Python process: inventory then bounded combat scanner.

Never loads/executes target assemblies, writes only to destination folder.
"""
import argparse
import json
import traceback
from pathlib import Path
from v3_progress import Progress, single_run, atomic_json
from client_probe import run_probe, sanitized_pack_views, make_diagnostic_zip, check_paths
from combat_fast import scan_fast


def analyze(game, out, *, decode_xnb=True, check_images=True, max_candidates=60):
    game,out=check_paths(Path(game),Path(out))
    with single_run(out):
        progress=Progress(out)
        try:
            progress.event('Reading assets and client structure')
            summary=run_probe(game,out,with_combat=False,decode_xnb=decode_xnb,
                              check_images=check_images, progress=progress)
            progress.update(force=True,stage='combat-index',done=0,total=0,current='Starting bounded assembly indexing')
            combat=scan_fast(game,out,progress=progress,max_candidates_per_assembly=max_candidates)
            summary['combat_summary']=combat
            summary['version']='3.0.0'
            summary['analysis_pack_name']='WoSB-Analysis-Pack.zip'
            summary['warnings'].append('Combat scanner is metadata-first and bounded; anonymous/obfuscated methods can be missed.')
            atomic_json(out/'Summary.json',summary)
            sanitized_pack_views(out)
            make_diagnostic_zip(out)
            progress.update(force=True,status='complete',stage='complete',done=1,total=1,current='WoSB-Analysis-Pack.zip')
            progress.event('Finished successful scan')
            return summary
        except BaseException as exc:
            progress.update(force=True,status='failed',stage='error',current=type(exc).__name__)
            (out/'Failure.log').write_text(traceback.format_exc(),encoding='utf-8')
            raise


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--game',required=True)
    p.add_argument('--output',required=True)
    p.add_argument('--no-decode-xnb',action='store_true')
    p.add_argument('--no-check-images',action='store_true')
    p.add_argument('--max-candidates',type=int,default=60)
    a=p.parse_args()
    summary=analyze(a.game,a.output,decode_xnb=not a.no_decode_xnb,
                    check_images=not a.no_check_images,max_candidates=a.max_candidates)
    print(json.dumps({'files_scanned':summary['files_scanned'],'combat_summary':summary['combat_summary']},indent=2))

if __name__=='__main__':main()
