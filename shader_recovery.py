"""Read-only XNA EffectReader forensics for locally installed WoSB assets.

Extracts *compiled* Effect bytes and records provenance, but does not pretend
that the Direct3D9 effect has been decompiled or converted to runnable WebGL.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'engine'))
from xnb_images import effect_blob

MAX_EFFECT_BYTES = 100 * 1024 * 1024
MAX_FILES = 2500
MAX_PRINTABLE = 120


def inspect_effect_bytes(data):
    """Inventory signatures and printable bytes; strings are only *candidates*."""
    if len(data) > MAX_EFFECT_BYTES:
        raise ValueError('Compiled effect exceeds safety cap')
    signatures = []
    for marker in (b'DXBC', b'CTAB', b'MGFX', b'XNA', b'FXC', b'VS_2_0', b'PS_2_0'):
        offset = data.find(marker)
        if offset >= 0:
            signatures.append({'marker': marker.decode('ascii'), 'offset': offset})
    raw = re.findall(rb'[ -~]{4,96}', data)
    printable = []
    for item in raw:
        text = item.decode('ascii', 'replace').strip()
        if text and text not in printable:
            printable.append(text)
        if len(printable) >= MAX_PRINTABLE:
            break
    return {'compiled_effect_size':len(data),
            'compiled_effect_sha256':hashlib.sha256(data).hexdigest(),
            'leading_magic_hex':data[:16].hex(),
            'binary_markers':signatures, 'candidate_strings':printable,
            'parameters_parsed':False,'techniques_parsed':False,
            'render_states_parsed':False,'runnable_shader_recovered':False}


def inspect_shader_file(path, base, output=None, export_compiled=False):
    path=Path(path);base=Path(base)
    relative=path.relative_to(base).as_posix()
    result={'source_relative':relative, 'source_size':path.stat().st_size}
    if path.stat().st_size>MAX_EFFECT_BYTES:
        return {**result,'status':'skipped','error':'Oversize input'}
    try:
        compiled, info = effect_blob(path.read_bytes())
        result.update(info)
        result.update(inspect_effect_bytes(compiled))
        result['status']='compiled_blob_extracted'
        if export_compiled and output is not None:
            # Keep a collision-free relative directory tree in local analysis output.
            destination=Path(output)/'CompiledEffects'/Path(relative).with_suffix('.fxb')
            destination.parent.mkdir(parents=True,exist_ok=True)
            destination.write_bytes(compiled)
            result['local_compiled_export']=destination.relative_to(output).as_posix()
    except (ValueError, OSError, RuntimeError) as exc:
        result['status']='unsupported_or_failed'
        result['error']=type(exc).__name__+': '+str(exc)[:220]
    return result


def audit_effects(game_root,output,*,export_compiled=False):
    base=Path(game_root).expanduser().resolve(strict=True)
    if not base.is_dir():raise ValueError('The game root must be a directory')
    output=Path(output).expanduser().resolve()
    candidates = []
    for path in base.rglob('*.xnb'):
        if 'shader' in path.as_posix().lower() and path.is_file():
            candidates.append(path)
            if len(candidates)>MAX_FILES: raise ValueError('Too many shader candidates; select a narrower game root')
    rows=[inspect_shader_file(p,base,output,export_compiled) for p in sorted(candidates)]
    tally=dict(Counter(r['status'] for r in rows))
    report={'format':'wosb-compiled-effects-audit-v1','source_root_present':True,
            'files_considered':len(rows),'status_counts':tally,'effects':rows,
            'disclaimer':('Compiled shader byte export is not source-code recovery. Binary strings are only '
              'search hints; parameters, techniques, blend/depth states, and GPU behavior require format-aware '
              'decoding and parity tests with the running game. The report does not contain full shader bytecode.')}
    output.mkdir(parents=True,exist_ok=True)
    destination=output/'Shader-Audit.json'
    destination.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    return destination,report


def main():
    parser=argparse.ArgumentParser(description='Read-only compiled effect extraction/inspection')
    parser.add_argument('--game-root',required=True,help='WoSB client folder (or default/game)')
    parser.add_argument('--output',required=True,help='Separate writable destination for audit JSON')
    parser.add_argument('--export-compiled',action='store_true',help='Optionally save your game-owned compiled effect blobs locally')
    args=parser.parse_args()
    dest,report=audit_effects(args.game_root,args.output,export_compiled=args.export_compiled)
    print('Shader audit:',dest,'| effect files:',report['files_considered'],'| status:',report['status_counts'])
    print('Note: this is NOT a verified native renderer or converted shader code.')

if __name__=='__main__':main()
