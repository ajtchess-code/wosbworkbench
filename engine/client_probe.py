#!/usr/bin/env python3
"""Read-only WoSB client diagnostics and improvement discovery.

This tool NEVER runs game DLLs, connects to servers, extracts credentials,
modifies a client, or packages raw game assets. Its evidence ZIP contains only
metadata, schemas, structure and bounded diagnostic summaries.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import os
import re
import struct
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from combat_research import TOPICS, json_write, topics

VERSION = '3.0.0'
SCANNABLE = {'.exe', '.dll', '.xnb', '.wosb', '.json', '.jsonl', '.xml', '.lang', '.txt', '.bin', '.dat',
             '.dds', '.png', '.jpg', '.jpeg', '.webp', '.zip', '.pak', '.ogg', '.wav', '.bmp', '.tga', '.fbx',
             '.model', '.x', '.mgfx', '.fx', '.fnt', '.spritefont', '.atlas'}
ASSETS = {'.xnb', '.png', '.dds', '.jpg', '.jpeg', '.webp', '.bmp', '.tga'}
SKIP_COMPONENTS = {'userdata', 'user_data', 'profiles', 'profile', 'saves', 'save', 'logs', 'log',
                   'crashes', 'crashdumps', 'telemetry', 'sessions', 'cookies', 'secrets', 'credentials',
                   'tokens', 'auth', 'accounts', 'appdata', 'screenshots'}
STRUCTURED = {'.json', '.jsonl', '.xml'}
MAGIC = [(b'\x89PNG\r\n\x1a\n', 'PNG'), (b'DDS ', 'DDS texture'), (b'PK\x03\x04', 'ZIP container'),
         (b'RIFF', 'RIFF/WAV'), (b'OggS', 'OGG'), (b'MZ', 'PE binary'), (b'\xff\xd8\xff', 'JPEG'),
         (b'XNB', 'XNB content'), (b'WOSBXNB', 'WoSB-wrapped XNB'), (b'UnityFS', 'Unity asset bundle')]
FIRE_TOKENS = ('fire', 'ignit', 'burn', 'flame', 'incend', 'extinguish', 'combust')
COMBAT_TERMS = tuple(sorted({w for words in TOPICS.values() for w in words}, key=len, reverse=True))


def norm_rel(p: Path, root: Path) -> str:
    return p.relative_to(root).as_posix()


def skip_path(p: Path, root: Path) -> bool:
    return p.is_symlink() or any(c.casefold() in SKIP_COMPONENTS for c in p.relative_to(root).parts[:-1])


def check_paths(game: Path, out: Path) -> tuple[Path, Path]:
    game, out = game.resolve(), out.resolve()
    if not game.is_dir():
        raise ValueError('Game/client directory not found: ' + str(game))
    if game == out or game in out.parents:
        raise ValueError('Output folder must be OUTSIDE the game installation')
    # Avoid using a parent of the game as an output as it could overwrite the installation.
    if out in game.parents:
        raise ValueError('Output folder cannot contain the game installation')
    return game, out


def iter_client_files(game: Path):
    for p in sorted(game.rglob('*')):
        if p.is_file() and not skip_path(p, game) and p.suffix.lower() in SCANNABLE:
            yield p


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def guess_kind(head: bytes, ext: str) -> str:
    for signature, kind in MAGIC:
        if head.startswith(signature):
            return kind
    if head.startswith(b'XNB', 4):
        return 'XNB with unknown 4-byte wrapper'
    if ext in ('.json', '.jsonl'):
        return 'JSON candidate'
    if ext == '.xml':
        return 'XML candidate'
    return 'unrecognized'


class _XnbReader:
    """Tiny bounds-checked XNB metadata reader independent of image dependencies."""
    def __init__(self,data):self.data=data;self.pos=0
    def read(self,n):
        if n<0 or self.pos+n>len(self.data):raise ValueError('Truncated XNB content')
        val=self.data[self.pos:self.pos+n];self.pos+=n;return val
    def seven(self):
        value=0
        for shift in range(0,35,7):
            b=self.read(1)[0];value|=(b&0x7f)<<shift
            if b<0x80:return value
        raise ValueError('Invalid 7bit number')
    def string(self):
        n=self.seven()
        if n>20000:raise ValueError('XNB type reader name unreasonably large')
        return self.read(n).decode('utf-8')
    def i32(self):return struct.unpack('<i',self.read(4))[0]


def parse_xnb_head(data: bytes, decompress=False, max_unpacked_bytes=40 * 1024 * 1024) -> dict:
    """Inspect XNB header/type readers, optionally try safe bounded decompression."""
    result = {'recognized': False}
    offset = 4 if len(data) >= 7 and data[4:7] == b'XNB' else 0
    if len(data) < offset + 10 or data[offset:offset + 3] != b'XNB':
        return result
    header = data[offset:]
    flags = header[5]
    result = {'recognized': True, 'wrapper_bytes': offset, 'platform': chr(header[3]),
              'version': header[4], 'flags': flags, 'compressed_lzx': bool(flags & 0x80),
              'compressed_lz4': bool(flags & 0x40),
              'declared_file_bytes': struct.unpack_from('<I', header, 6)[0],
              'reader_types': [], 'shared_resources': None, 'root_reader': None}
    if flags & (0x80 | 0x40):
        if len(header) >= 14:
            result['declared_unpacked_bytes'] = struct.unpack_from('<I', header, 10)[0]
        if not decompress:
            result['status'] = 'header_only_compressed'
            return result
        if result.get('declared_unpacked_bytes', 1 << 60) > max_unpacked_bytes:
            result['status'] = 'decompression_skipped_size_limit'
            return result
        try:
            from xnb_images import unpack_xnb
            payload = unpack_xnb(header)
        except Exception as e:
            result['status'] = 'decompression_failed'
            result['error_type'] = type(e).__name__
            # Error strings are deliberately omitted from shareable diagnostics.
            return result
    else:
        payload = header[10:]
    try:
        reader = _XnbReader(payload)
        count = reader.seven()
        if count > 256:
            raise ValueError('Too many declared content readers')
        for _ in range(count):
            result['reader_types'].append(reader.string()[:300])
            reader.i32()
        result['shared_resources'] = reader.seven()
        root_id = reader.seven()
        result['root_reader'] = result['reader_types'][root_id - 1] if 0 < root_id <= count else None
        result['status'] = 'content_header_read'
        if result['root_reader'] and 'Texture2DReader' in result['root_reader']:
            fmt = reader.i32(); width = reader.i32(); height = reader.i32(); mips = reader.i32()
            if 0 < width <= 65536 and 0 < height <= 65536:
                result['texture'] = {'format_id': fmt, 'width': width, 'height': height, 'mips': mips}
    except Exception as e:
        result['status'] = 'content_header_error'
        result['error_type'] = type(e).__name__
    return result


def analyze_zip_container(p: Path, max_entries: int = 100000) -> dict:
    """Read ZIP directory only; never extract encrypted or proprietary archive data."""
    try:
        with zipfile.ZipFile(p) as z:
            infos = z.infolist()
            items = infos[:max_entries]
            examples = []
            suffixes = Counter()
            encrypted = 0
            for entry in items:
                suffixes[Path(entry.filename).suffix.lower() or '[none]'] += 1
                encrypted += bool(entry.flag_bits & 1)
                if len(examples) < 30:
                    # Entry names can reveal personal info; only share extension and structure.
                    examples.append({'extension': Path(entry.filename).suffix.lower(),
                                     'depth': len(Path(entry.filename).parts),
                                     'size': entry.file_size, 'encrypted': bool(entry.flag_bits & 1)})
            return {'is_zip': True, 'entry_count': len(infos), 'encrypted_count_sampled': encrypted,
                    'extensions_sampled': dict(suffixes.most_common(60)), 'samples': examples,
                    'truncated': len(infos) > max_entries}
    except (OSError, zipfile.BadZipFile, ValueError, RuntimeError):
        return {'is_zip': False, 'status': 'unknown_or_non_zip_container'}


def field_type(x):
    if isinstance(x, bool): return 'boolean'
    if x is None: return 'null'
    if isinstance(x, (float, int)): return 'number'
    if isinstance(x, list): return 'array'
    if isinstance(x, dict): return 'object'
    return 'string'


def discover_json_schema(obj, source, max_nodes=150000):
    """Field/type frequency without copying user-visible field values or secrets."""
    paths = Counter(); potential_combat = []; nodes = 0
    def visit(x, loc, depth=0):
        nonlocal nodes
        nodes += 1
        if depth > 30 or nodes > max_nodes:
            return
        if isinstance(x, dict):
            for k, value in x.items():
                # Avoid recording possible token/key names and values in exports.
                k = str(k)
                if re.search(r'(secret|token|password|email|account|auth|session|key$)', k, re.I):
                    continue
                name = (loc + '/' + k)[:240]
                paths[(name, field_type(value))] += 1
                if topics(k) and isinstance(value, (float, int)) and not isinstance(value, bool):
                    potential_combat.append({'source': source, 'field_path': name, 'value': value,
                                             'status': 'configuration value; usage unverified'})
                visit(value, name, depth + 1)
        elif isinstance(x, list):
            for child in x[:1000]:
                visit(child, loc + '/[]', depth + 1)
    visit(obj, '')
    return [{'source': source, 'field_path': path, 'value_type': typ, 'occurrences': n}
            for (path, typ), n in paths.most_common(10000)], potential_combat, nodes > max_nodes


def inspect_structured(p: Path, rel: str, max_bytes=8_000_000):
    try:
        if p.stat().st_size > max_bytes:
            return [], [], {'source': rel, 'reason': 'size_limit'}
        if p.suffix.lower() == '.xml':
            # ElementTree does not expand external entities or resolve network resources.
            import xml.etree.ElementTree as ET
            root = ET.parse(p).getroot()
            keys = Counter()
            def traverse(node, chain, depth=0):
                if depth > 30: return
                key = (chain + '/' + node.tag.split('}')[-1])[:240]
                keys[(key, 'element')] += 1
                for attr in node.attrib:
                    if not re.search(r'(password|secret|token|auth|session|key$)', attr, re.I):
                        keys[(key + '/@' + attr, 'attribute')] += 1
                for child in list(node)[:1000]: traverse(child, key, depth + 1)
            traverse(root, '')
            fields = [{'source': rel, 'field_path': k, 'value_type': t, 'occurrences': n}
                      for (k, t), n in keys.most_common(10000)]
            return fields, [], None
        if p.suffix.lower() == '.jsonl':
            with p.open(encoding='utf-8-sig') as f:
                records = [json.loads(line) for i, line in enumerate(f) if i < 1000 and line.strip()]
            data = records
        else:
            data = json.loads(p.read_text(encoding='utf-8-sig'))
        fields, combat, hit_limit = discover_json_schema(data, rel)
        return fields, combat, {'source': rel, 'reason': 'node_limit'} if hit_limit else None
    except (ValueError, UnicodeError, OSError, ET_ERROR) as e:
        return [], [], {'source': rel, 'reason': 'parse_error', 'error_type': type(e).__name__}


# xml exception type is defined once so the exception handler above works without importing ET globally.
try:
    from xml.etree.ElementTree import ParseError as ET_ERROR
except ImportError:
    ET_ERROR = ValueError


def offline_dashboard(summary: dict, category_rows, hints: list):
    """Return fully self-contained HTML with escaped text and local searching."""
    table_rows = ''.join('<tr><td>'+html.escape(str(row['category']))+'</td><td>'+str(row['count'])+'</td></tr>'
                         for row in category_rows)
    hints_rows = ''.join('<li>'+html.escape(x)+'</li>' for x in hints)
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><title>WoSB Client Probe</title>
<style>body{font:15px system-ui, sans-serif;background:#0e1828;color:#e8eef6;margin:auto;max-width:1080px;padding:30px}
h1{font-size:30px}h2{margin-top:30px}table{border-collapse:collapse;width:100%;background:#1c2b40}
 td,th{padding:12px;text-align:left;border-bottom:1px solid #33445d}a{color:#83d0ff}
 .muted{color:#bbcadb}.note{border-left:3px solid #e7ac50;padding:10px 16px;background:#283344}</style>
<h1>World of Sea Battle — Client Diagnostic Report</h1>
<p class="muted">Analysis toolkit v''' + VERSION + ''' · read-only evidence, no gameplay formulas assumed</p>
<p class="note">A candidate method, string, or numeric value is NOT proof of how the server resolves a combat event.</p>
<h2>Coverage snapshot</h2><table><thead><tr><th>Category</th><th>Count</th></tr></thead><tbody>''' + table_rows + '''</tbody></table>
<h2>Recommended investigations</h2><ul>''' + hints_rows + '''</ul>
<h2>Research files</h2><p>Open <code>Combat/Topics.json</code>, <code>Combat/Methods.csv</code> and <code>Client/SchemaFields.csv</code> for evidence.
The separate <code>WoSB-Analysis-Pack.zip</code> contains shareable diagnostics, not game binaries.</p></html>'''



def sanitized_pack_views(out: Path) -> None:
    """Derive shareable evidence tables without raw strings, absolute paths or config secrets."""
    summary_file = out/'Summary.json'
    if summary_file.exists():
        data=json.loads(summary_file.read_text(encoding='utf-8'))
        combat=data.get('combat_summary')
        if isinstance(combat,dict):
            data['combat_summary']={k:v for k,v in combat.items() if k != 'game_root'}
        json_write(out/'Summary-Share.json',data)
    combat_file=out/'Combat/Summary.json'
    if combat_file.exists():
        c=json.loads(combat_file.read_text(encoding='utf-8'))
        json_write(out/'Combat/ShareSummary.json',{k:v for k,v in c.items() if k != 'game_root'})
    methods_file=out/'Combat/Methods.csv'
    if methods_file.exists():
        with methods_file.open(encoding='utf-8-sig',newline='') as f:
            rows=list(csv.DictReader(f))
        cols=['assembly','token','method','topics','score','evidence_status',
              'calls_related','fields_related','numeric_literals','evidence_path','evidence_sha256']
        write_csv(out/'Combat/ShareMethods.csv',rows,cols)
    config_file=out/'Combat/ConfigFields.csv'
    if config_file.exists():
        with config_file.open(encoding='utf-8-sig',newline='') as f:
            rows=list(csv.DictReader(f))
        for row in rows:
            # Only numeric and boolean scalar values are safe/meaningful for a broad diagnostic pack.
            val=row.get('value','')
            try:
                if not (isinstance(json.loads(val), (float,int,bool))):row['value']='[non-numeric redacted]'
            except (ValueError, TypeError):
                row['value']='[non-numeric redacted]'
        write_csv(out/'Combat/ShareConfigFields.csv',rows,
                  ['source','json_pointer','field','value','topics','evidence_kind','interpretation'])

def make_diagnostic_zip(out: Path) -> Path:
    """Package ONLY an explicit allowlist of generated diagnostics. No raw game assets."""
    archive = out / 'WoSB-Analysis-Pack.zip'
    approved = ['Report.html', 'Summary-Share.json', 'README-ANALYSIS-PACK.md',
                'Client/FileInventory.json', 'Client/FileKinds.json', 'Client/XNBHeaders.json',
                'Client/ArchiveHeaders.json', 'Client/SchemaFields.csv', 'Client/CombatConfig.csv',
                'Client/Errors.csv', 'Combat/ShareSummary.json', 'Combat/Topics.json',
                'Combat/ShareMethods.csv', 'Combat/CallReferences.csv', 'Combat/ShareConfigFields.csv',
                'Combat/Dossiers.json', 'Combat/CallGraph.csv', 'Combat/ILSignals.csv',
                'Client/ImageDecodeHealth.csv']
    # No full IL listings or unfiltered assembly strings are packed by default.
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=8) as z:
        for name in approved:
            path = out / name
            if path.is_file(): z.write(path, name)
    return archive


def write_csv(out: Path, data: list, cols: list):
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('w', newline='', encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f, fieldnames=cols, extrasaction='ignore'); writer.writeheader()
        for row in data:
            clean={}
            for k in cols:
                val=row.get(k, '')
                if isinstance(val, (list,dict)): val=json.dumps(val, ensure_ascii=False)
                if isinstance(val, str) and val.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')):
                    val="'"+val
                clean[k]=val
            writer.writerow(clean)


def run_probe(game, out, *, with_combat=True, decode_xnb=False, max_image_mb=40,
              deep_calls=True, max_evidence_methods=500, reuse_hashes=True, check_images=False, progress=None):
    game,out=check_paths(Path(game),Path(out)); out.mkdir(parents=True,exist_ok=True)
    errors=[];inventory=[];types=Counter();xnb_rows=[];zip_rows=[];schemas=[];combat_values=[];image_health=[]
    previous={}
    statepath=out/'Client/HashState.json'
    if reuse_hashes and statepath.exists():
        try: previous=json.loads(statepath.read_text(encoding='utf-8')).get('files',{})
        except (OSError,ValueError):pass
    current={}
    files_to_scan = list(iter_client_files(game))
    for i,p in enumerate(files_to_scan, 1):
        rel=norm_rel(p,game)
        if progress and (i == 1 or i % 25 == 0):
            progress.update(stage="file-inventory", done=i, total=len(files_to_scan), current=rel)
        try:
            stat=p.stat()
            with p.open('rb') as stream:head=stream.read(18)
            kind=guess_kind(head,p.suffix.lower()); types[kind]+=1
            key=f'{stat.st_size}:{stat.st_mtime_ns}'
            cached=previous.get(rel,{})
            fingerprint=cached.get('sha256') if cached.get('cache_key')==key else None
            if fingerprint is None:fingerprint=sha256_file(p)
            current[rel]={'cache_key':key,'sha256':fingerprint}
            inventory.append({'path':rel,'bytes':stat.st_size,'extension':p.suffix.lower(),'format':kind,'sha256':fingerprint})
            if kind.startswith('XNB') or kind.startswith('WoSB-wrapped XNB'):
                if stat.st_size <= max_image_mb*1024*1024:
                    detail=parse_xnb_head(p.read_bytes(),decompress=decode_xnb)
                else:detail={'recognized':True,'status':'header_skipped_large_file'}
                xnb_rows.append({'source':rel,'size_bytes':stat.st_size,**detail})
                if check_images and stat.st_size <= max_image_mb*1024*1024:
                    try:
                        from xnb_images import texture
                        im,info=texture(p.read_bytes())
                        image_health.append({'source':rel,'status':'decoded','width':im.width,
                                             'height':im.height,'format':info.get('SurfaceFormat',''),
                                             'issue':''})
                    except Exception as e:
                        image_health.append({'source':rel,'status':'failed','width':'','height':'',
                                             'format':'','issue':type(e).__name__})
            if p.suffix.lower() in ('.wosb','.zip') or kind=='ZIP container':
                zip_rows.append({'source':rel,'size_bytes':stat.st_size,**analyze_zip_container(p)})
            if p.suffix.lower() in STRUCTURED:
                fields,combat,problem=inspect_structured(p,rel)
                schemas.extend(fields);combat_values.extend(combat)
                if problem:errors.append(problem)
        except (OSError,ValueError) as e:
            errors.append({'source':rel,'reason':'file_access','error_type':type(e).__name__})
    if progress: progress.update(force=True,stage='inventory-written',done=len(files_to_scan),total=len(files_to_scan),current='Client/FileInventory.json')
    json_write(out/'Client/FileInventory.json',inventory)
    json_write(out/'Client/HashState.json',{'version':VERSION,'files':current})
    json_write(out/'Client/FileKinds.json',dict(types))
    json_write(out/'Client/XNBHeaders.json',xnb_rows)
    json_write(out/'Client/ArchiveHeaders.json',zip_rows)
    write_csv(out/'Client/SchemaFields.csv',schemas,['source','field_path','value_type','occurrences'])
    write_csv(out/'Client/CombatConfig.csv',combat_values,['source','field_path','value','status'])
    write_csv(out/'Client/ImageDecodeHealth.csv',image_health,['source','status','width','height','format','issue'])
    write_csv(out/'Client/Errors.csv',errors,['source','reason','error_type'])
    summary={'tool':'WoSB Client Analysis Toolkit','version':VERSION,'timestamp_utc':datetime.now(timezone.utc).isoformat(),
             'files_scanned':len(inventory),'extensions':dict(Counter(row['extension'] for row in inventory)),
             'file_types':dict(types),'xnb_count':len(xnb_rows),'xnb_statuses':dict(Counter(x['status'] for x in xnb_rows if 'status' in x)),
             'archives':len(zip_rows),'schema_paths':len(schemas),'combat_numeric_fields':len(combat_values),
             'image_decoding_tested':len(image_health),
             'image_decoding_failed':sum(x['status']=='failed' for x in image_health),
             'read_only':True,'game_dlls_executed':False,'warnings':[
                 'All candidate formulas and fields need manual validation and may be client-only.',
                 'Server-only formulas cannot be determined from client content alone.',
                 'Hash cache reuses unchanged size+mtime metadata; use --fresh-hashes to rehash every file.',
                 'Shareable pack excludes raw DLLs, images and IL listings. Review it before sharing.']}
    if with_combat:
        from combat_research import analyze
        try:
            combat_summary=analyze(game,out,max_methods=max_evidence_methods)
            summary['combat_summary']=combat_summary
        except Exception as e:
            summary['combat_error_type']=type(e).__name__
            errors.append({'source':'[combat analyzer]','reason':'analyzer_failed','error_type':type(e).__name__})
            write_csv(out/'Client/Errors.csv',errors,['source','reason','error_type'])
        if deep_calls:
            try:
                from combat_dossiers import build_dossiers
                summary['combat_dossiers']=build_dossiers(game,out)
            except Exception as e:
                summary['dossiers_error_type']=type(e).__name__
                errors.append({'source':'[dossier engine]','reason':'analyzer_failed','error_type':type(e).__name__})
                write_csv(out/'Client/Errors.csv',errors,['source','reason','error_type'])
    hints=[]
    if not xnb_rows:hints.append('No XNB assets found: check whether the client has a nested game/default/game folder.')
    if xnb_rows:
        fail=sum('failed' in r.get('status','') or 'error' in r.get('status','') for r in xnb_rows)
        if fail:hints.append(f'{fail} XNB content-header failures: group by reader type, compression flag and source extension.')
        if sum(r.get('compressed_lz4',False) for r in xnb_rows):hints.append('LZ4-compressed XNB assets found: add LZ4 decoding before texture extraction.')
    if zip_rows:hints.append('Review archive entry counts and encryption flags before attempting catalog extraction.')
    if image_health:
        broken=sum(x['status']=='failed' for x in image_health)
        hints.append(f'Image decoding probe: {len(image_health)-broken} passed, {broken} failed. Group failures by XNB type reader and image format.')
    if summary.get('combat_summary',{}).get('candidate_methods',0)==0:
        hints.append('No combat method candidates found: verify managed DLL locations and dnfile/dncil installation.')
    hints.append('For large fire, inspect Fire and Status Effects dossiers, writer/reader relationships, branch tests, and caller chains.')
    hints.append('For damage mitigation, inspect Damage and Mitigation dossiers together; follow penetration, armor and post-hit methods.')
    rows=[{'category':'Scannable files','count':len(inventory)},{'category':'XNB assets','count':len(xnb_rows)},
          {'category':'Archive candidates','count':len(zip_rows)},{'category':'Structured data paths','count':len(schemas)},
          {'category':'Combat configuration values','count':len(combat_values)},
          {'category':'Parse/access problems','count':len(errors)},
          {'category':'Candidate combat methods','count':summary.get('combat_summary',{}).get('candidate_methods',0)}]
    (out/'Report.html').write_text(offline_dashboard(summary,rows,hints),encoding='utf-8')
    (out/'README-ANALYSIS-PACK.md').write_text('''# WoSB Client Analysis Pack\n\nThis is a **read-only, static inventory**, not verified gameplay documentation.\n\n## What to share\nUpload `WoSB-Analysis-Pack.zip` when asking for the next extractor refinement.\nIt contains inventory, type-reader and content-schema diagnostics, combat candidates, and cross-references.\n**It intentionally excludes:** game executables, DLL binaries, raw artwork, localization strings, save files, full IL listings and extracted assets.\nReview the ZIP before sharing and do not upload credentials or game account files.\n\n## Where to look first\n- `Summary.json`: counts and failures.\n- `Client/XNBHeaders.json`: compression, reader types, image format and failed parsing.\n- `Client/SchemaFields.csv`: structured-data layouts and field names.\n- `Combat/Dossiers.json`: method neighborhoods and evidence candidates.\n- `Combat/Topics.json`: broad search index.\n\nA field or bytecode operation is a **candidate**, not proof of a full calculation or server behavior.\n''',encoding='utf-8')
    json_write(out/'Summary.json',summary)
    sanitized_pack_views(out)
    archive=make_diagnostic_zip(out)
    summary['analysis_pack_name']=archive.name
    json_write(out/'Summary.json',summary)
    sanitized_pack_views(out)
    # Regenerate ZIP after summary update.
    make_diagnostic_zip(out)
    return summary


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--game',required=True,help='Installed game folder; no client files modified')
    p.add_argument('--output',required=True,help='Report folder outside the installation')
    p.add_argument('--no-combat',action='store_true',help='Fast asset+schema discovery only')
    p.add_argument('--no-deep-calls',action='store_true',help='Skip advanced callgraph dossiers')
    p.add_argument('--decode-xnb',action='store_true',help='Try unpacking supported compressed XNB headers')
    p.add_argument('--check-images',action='store_true',help='Try actually decoding XNB textures, report errors, save no images')
    p.add_argument('--max-image-mb',type=int,default=40)
    p.add_argument('--max-evidence-methods',type=int,default=500)
    p.add_argument('--fresh-hashes',action='store_true',help='Rehash every file')
    args=p.parse_args(argv)
    if args.max_image_mb<1 or args.max_evidence_methods<1:p.error('Max limits must be positive')
    result=run_probe(args.game,args.output,with_combat=not args.no_combat,decode_xnb=args.decode_xnb,
                     max_image_mb=args.max_image_mb,deep_calls=not args.no_deep_calls,
                     max_evidence_methods=args.max_evidence_methods,reuse_hashes=not args.fresh_hashes,
                     check_images=args.check_images)
    print(json.dumps(result,indent=2,ensure_ascii=False))
    return 0

if __name__=='__main__':
    try:sys.exit(main())
    except Exception as exc:
        print(f'ERROR ({type(exc).__name__}): {exc}',file=sys.stderr)
        sys.exit(1)
