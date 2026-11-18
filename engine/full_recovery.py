#!/usr/bin/env python3
"""Read-only, checkpointed full client asset/code recovery for WoSB Workbench.

Every result includes evidence and a decoder status. No DLL or game code is executed,
no anti-cheat bypass, network interception, credential extraction or game mutation.
"""
from __future__ import annotations
from v3_progress import replace_with_retry, status_json
import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import traceback
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

DECODER_REVISION = "4.3.1-asset-reader-3-audit"
# This audit changes which assets are classified and fixes two previously
# failing model files. Unchanged successful models/textures exported by the
# preceding audited readers can be safely reused; FAILED assets are retried.
REUSABLE_SUCCESS_REVISIONS = frozenset({"4.0.0-asset-reader-1", "4.1.0-asset-reader-2"})
MAX_FILE = 512 * 1024 * 1024
MAX_METHODS = 350000
ASSET_EXTS = ('.xnb',)
SKIP_DIRS = {'.git', '__pycache__', '.build-venv', '.extract-venv', 'node_modules'}


def utc():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def sha_file(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def atomic_json(path, val):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=path.parent,delete=False,suffix='.tmp') as f:
        json.dump(val,f,indent=2,ensure_ascii=False);tmp=Path(f.name)
    replace_with_retry(tmp,path)


def safe_rel(path,root):
    rel=path.relative_to(root)
    if '..' in rel.parts or rel.is_absolute():raise ValueError('Unsafe relative path')
    return rel


def identify_readers(payload):
    # XNA ContentReader metadata; reader names do not guarantee the data body
    # can be deserialized by Workbench's supported content decoders.
    from xnb_images import Reader
    r=Reader(payload)
    count=r.seven()
    if count>512:raise ValueError('Too many XNB reader declarations')
    names=[]
    for _ in range(count):
        name=r.string()
        if len(name)>8192:raise ValueError('Excessive content reader name')
        names.append(name)
        r.i32()
    shared=r.seven()
    if shared>500000:raise ValueError('Excessive shared resource count')
    root_id=r.seven()
    return {'readers':names,'shared_resources':shared,'root_reader_id':root_id}


def root_reader_name(names, root_reader_id):
    """Use the XNB *root object* reader, not every declared nested reader.

    A SpriteFont declares Texture2DReader as a nested dependency. Treating it
    as a top-level texture caused 71 false Texture2D failures per client.
    """
    if not isinstance(root_reader_id, int) or not 1 <= root_reader_id <= len(names):
        return ''
    qualified = names[root_reader_id - 1].split(',', 1)[0]
    return qualified.rsplit('.', 1)[-1].lower()


def asset_class(names, rel, root_reader_id=1):
    reader = root_reader_name(names, root_reader_id)
    if 'spritefontreader' in reader:
        return 'font'
    if 'texture2dreader' in reader or 'texturecubereader' in reader:
        return 'texture'
    if 'modelreader' in reader:
        return 'model'
    if 'effectreader' in reader:
        return 'effect'
    if 'material' in reader or str(rel).casefold().endswith('.material.xnb'):
        return 'material'
    return 'other_xnb'


class Recovery:
    def __init__(self,game,out,*,preserve=True,payloads=True,catalog=True,code=True,
                 all_il=True,max_methods=MAX_METHODS,cancel=None,force=False):
        self.game=Path(game).expanduser().resolve();self.out=Path(out).expanduser().resolve()
        if not self.game.is_dir():raise ValueError('Game directory not found: '+str(self.game))
        if self.out==self.game or self.game in self.out.parents or self.out in self.game.parents:
            raise ValueError('Recovery output must be outside the game directory and not its parent')
        self.out.mkdir(parents=True,exist_ok=True)
        self.preserve=preserve;self.payloads=payloads;self.catalog=catalog;self.code=code
        self.all_il=all_il;self.max_methods=max_methods;self.cancel=cancel;self.force=force
        self.db=sqlite3.connect(self.out/'Recovery-State.sqlite3')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''CREATE TABLE IF NOT EXISTS assets(
           path TEXT PRIMARY KEY, size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL,
           sha256 TEXT NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL,
           output TEXT NOT NULL DEFAULT '', details TEXT NOT NULL DEFAULT '{}', updated TEXT NOT NULL);
           CREATE TABLE IF NOT EXISTS phases(name TEXT PRIMARY KEY, status TEXT, details TEXT, updated TEXT);''')
        self.db.commit()
        self.report={'tool':'WoSB Full Recovery','version':'4.3.0','game_root':str(self.game),
            'output':str(self.out),'started_utc':utc(),'read_only':True,'decoder_revision':DECODER_REVISION,
            'game_assemblies_executed':False,'server_authoritative_damage_verified':False,
            'phases':{},'progress':{'phase':'starting','done':0,'total':0},
            'limitations':['Decoded geometry is not proof of gameplay collision geometry.',
                           'Material metadata is preserved but unsupported custom shaders are not reconstructed.',
                           'Static IL analysis cannot recover server-exclusive formulas.',
                           'Encrypted/wrapped archives are handled only by a valid local client metadata extractor.']}
        self._write()

    def _write(self):status_json(self.out/'Recovery-Status.json',self.report)

    def phase(self,name,status,details=''):
        self.report['phases'][name]={'status':status,'details':str(details)[:2000],'updated_utc':utc()}
        self.db.execute('INSERT OR REPLACE INTO phases VALUES(?,?,?,?)',(name,status,str(details)[:2000],utc()))
        self.db.commit();self._write()

    def progress(self,phase,done,total,current=''):
        self.report['progress']={'phase':phase,'done':done,'total':total,'current':str(current)[:300]}
        self._write()

    def check_cancel(self):
        if self.cancel and self.cancel.is_set():raise InterruptedError('Recovery stopped safely at a checkpoint')

    def files(self,extensions=None):
        for base,dirs,files in os.walk(self.game,followlinks=False):
            dirs[:]=sorted(d for d in dirs if d not in SKIP_DIRS and not (Path(base)/d).is_symlink())
            for name in sorted(files):
                file=Path(base)/name
                if file.is_symlink() or (extensions and file.suffix.lower() not in extensions):continue
                yield file

    def cached(self,relative,stat):
        if self.force:return None
        row=self.db.execute('SELECT size,mtime_ns,sha256,kind,status,output,details FROM assets WHERE path=?',(relative,)).fetchone()
        if row and row[0]==stat.st_size and row[1]==stat.st_mtime_ns:
            old_details=json.loads(row[6])
            old_revision=old_details.get('decoder_revision')
            current=(old_revision==DECODER_REVISION and row[4] in
                     ('decoded','indexed','preserved','unsupported'))
            trusted_success=(row[4]=='decoded' and row[3] in ('texture','model')
                             and old_revision in REUSABLE_SUCCESS_REVISIONS)
            if current or trusted_success:
                output=row[5]
                if output and (self.out/output).is_file():
                    return {'path':relative,'bytes':stat.st_size,'sha256':row[2],
                        'kind':row[3],'status':row[4],'output':output,**old_details}
        return None

    def persist(self,rel,stat,digest,kind,status,output='',details=None):
        details={**(details or {}),'decoder_revision':DECODER_REVISION}
        self.db.execute('INSERT OR REPLACE INTO assets VALUES (?,?,?,?,?,?,?,?,?)',
            (rel,stat.st_size,stat.st_mtime_ns,digest,kind,status,output,json.dumps(details,ensure_ascii=False),utc()))
        return {'path':rel,'bytes':stat.st_size,'sha256':digest,'kind':kind,'status':status,'output':output,**details}

    def recover_one(self,file):
        from xnb_payload import parse_header,unpack_xnb,XNBError
        stat=file.stat();rel=safe_rel(file,self.game).as_posix()
        old=self.cached(rel,stat)
        if old:return old
        digest=sha_file(file)
        details={'source':rel}
        if stat.st_size>MAX_FILE:
            return self.persist(rel,stat,digest,'unknown','unsupported',details={'reason':'input_above_512MiB_limit'})
        try:
            raw=file.read_bytes()
            header,_=parse_header(raw)
            payload,meta=unpack_xnb(raw,return_info=True)
            details['xnb']=meta
            description=identify_readers(payload)
            details.update(description)
            kind=asset_class(description['readers'],rel,description['root_reader_id'])
            storage=self.out/'Recovered'/kind/safe_rel(file,self.game)
            storage=storage.with_suffix('')
            output=''
            if self.payloads:
                save=self.out/'Decoded-Payloads'/safe_rel(file,self.game)
                save=save.with_suffix('.bin');save.parent.mkdir(parents=True,exist_ok=True)
                save.write_bytes(payload)
                details['decompressed_payload']=save.relative_to(self.out).as_posix()
            if kind=='font':
                # SpriteFont is not a Texture2D root; extract its embedded
                # glyph atlas when possible, preserving source provenance.
                from xnb_images import spritefont_atlas
                image,info=spritefont_atlas(raw)
                png=storage.with_suffix('.png');png.parent.mkdir(parents=True,exist_ok=True)
                image.save(png);output=png.relative_to(self.out).as_posix()
                details.update(info)
                details['glyph_metrics_verified']=False
                return self.persist(rel,stat,digest,kind,'decoded',output,details)
            if kind=='texture':
                from xnb_images import texture
                image,info=texture(raw)
                png=storage.with_suffix('.png');png.parent.mkdir(parents=True,exist_ok=True)
                image.save(png);output=png.relative_to(self.out).as_posix()
                details.update(info)
                return self.persist(rel,stat,digest,kind,'decoded',output,details)
            if kind=='model':
                from xnb_geometry import export_obj
                obj=storage.with_suffix('.obj');obj.parent.mkdir(parents=True,exist_ok=True)
                try:
                    report=export_obj(payload,obj)
                    metadata=storage.with_suffix('.json');atomic_json(metadata,report)
                    output=obj.relative_to(self.out).as_posix()
                    details['geometry_report']=metadata.relative_to(self.out).as_posix()
                    details['mesh_parts']=report.get('parts') or report.get('mesh_parts')
                    return self.persist(rel,stat,digest,kind,'decoded',output,details)
                except Exception:
                    # A failed geometry parse must not leave a misleading partial OBJ.
                    obj.unlink(missing_ok=True)
                    raise
            if kind=='effect':
                # A compiled effect can sometimes be preserved independently
                # even when shader source and parameter behavior are unknown.
                try:
                    from xnb_images import effect_blob
                    blob,info=effect_blob(raw)
                    compiled=storage.with_suffix('.fxb')
                    compiled.parent.mkdir(parents=True,exist_ok=True)
                    compiled.write_bytes(blob)
                    details.update(info)
                    details['compiled_effect_export']=compiled.relative_to(self.out).as_posix()
                except (ValueError,OSError) as exc:
                    details['effect_blob_error']=type(exc).__name__+': '+str(exc)[:200]
                # Still unsupported: extracting a compiled blob is NOT
                # recreating the original shader or render pipeline.

            # Unknown/custom material readers have metadata and raw payload, not
            # a fabricated 3D material/shader implementation.
            description_path=storage.with_suffix('.json')
            description_path.parent.mkdir(parents=True,exist_ok=True)
            atomic_json(description_path,{'source':rel,'kind':kind,'sha256':digest,**details,
                'status':'reader_identified_body_unimplemented'})
            output=description_path.relative_to(self.out).as_posix()
            return self.persist(rel,stat,digest,kind,'unsupported',output,details)
        except Exception as exc:
            if isinstance(exc,XNBError) and 'Not a complete XNB header' in str(exc):
                # Some .xnb-named resources are different binary formats;
                # don't count them as failed texture/model decodes.
                magic=file.read_bytes()[:16].hex()
                return self.persist(rel,stat,digest,'unknown_binary','unsupported',
                    details={**details,'reason':'unrecognized_xnb_header',
                             'first_16_bytes_hex':magic,'needs_custom_format_identification':True})
            try:header=parse_header(file.read_bytes())[1]
            except Exception:header={}
            return self.persist(rel,stat,digest,'xnb','failed',details={**details,'xnb_header':header,
                'error_type':type(exc).__name__,'error':str(exc)[:1000]})

    def assets(self):
        paths=list(self.files(ASSET_EXTS));counts=Counter();rows=[]
        self.phase('assets','running',f'{len(paths)} XNB files')
        indexed=self.out/'Reports'/'AssetLedger.jsonl';indexed.parent.mkdir(parents=True,exist_ok=True)
        for i,file in enumerate(paths,1):
            self.check_cancel()
            try:res=self.recover_one(file)
            except Exception as e:
                res={'path':str(file.relative_to(self.game)),'status':'failed','error_type':type(e).__name__,'error':str(e)[:400]}
            counts[res['status']]+=1;counts['kind:'+res.get('kind','unknown')]+=1
            rows.append(res)
            if i%10==0:self.db.commit()
            if i%20==0 or i==len(paths):self.progress('assets',i,len(paths),res['path'])
        self.db.commit()
        with indexed.open('w',encoding='utf-8') as f:
            for row in rows:f.write(json.dumps(row,ensure_ascii=False)+'\n')
        self.report['assets']={'found':len(paths),'counts':dict(counts),'ledger':indexed.relative_to(self.out).as_posix()}
        self.phase('assets','completed',f'{len(paths)} classified, '+str(counts.get('decoded',0))+' decoded')
        return rows

    def catalog_export(self):
        self.phase('catalog','running','Full English data archive, images, original archive assets and research tables')
        destination=self.out/'Catalog'
        if (destination/'Extraction-Summary.json').exists() or (destination/'WOSB-AI-Handoff.zip').exists():
            self.phase('catalog','completed','Reused saved completed catalog');return
        if destination.exists():
            destination=next(self.out/('Catalog-retry-'+str(i)) for i in range(2,200) if not (self.out/('Catalog-retry-'+str(i))).exists())
        from extract_wosb import Extractor,locate_game
        game=locate_game(self.game)
        engine=Extractor(game,destination,images=True,all_textures=True,broad=True,preserve_assets=self.preserve)
        engine.craft_quantity=1;engine.combat=False
        engine.extract()
        self.phase('catalog','completed',str(destination.relative_to(self.out)))

    def recover_code(self):
        """Emit an IL index of every readable managed method, with optional full IL listings.

        No conversion to C# or claim that client functions are server-authoritative.
        """
        from client_metadata import Metadata
        files=list(self.files({'.dll','.exe'}))
        # Code indexes have an upper bound; index gameplay assemblies before
        # enormous Windows SDK and UI dependencies so combat evidence survives.
        def assembly_priority(path):
            name=path.name.casefold()
            if name=='common.dll':return (0,str(path).casefold())
            if 'worldofseabattle' in name or name=='content.dll':return (1,str(path).casefold())
            if name.startswith(('uw','wosb')):return (2,str(path).casefold())
            return (3,str(path).casefold())
        files.sort(key=assembly_priority)
        count=0;errors=[];assembly_rows=[];limit_hit=False;remaining_uninspected=0
        self.phase('code','running',f'{len(files)} managed-code candidates')
        destination=self.out/'Code-Recovery';destination.mkdir(parents=True,exist_ok=True)
        index_file=destination/'ManagedMethods.jsonl'
        with index_file.open('w',encoding='utf-8') as index:
            for i,file in enumerate(files,1):
                self.check_cancel();rel=safe_rel(file,self.game).as_posix()
                try:
                    if file.stat().st_size>160*1024*1024:raise ValueError('assembly larger than 160 MiB cap')
                    metadata=Metadata(file,prepare_strings=False)
                    if not getattr(metadata.pe,'net',None) or not metadata.pe.net.mdtables:
                        continue
                    members=metadata.pe.net.mdtables.MethodDef.rows
                    dest=destination/'IL'/safe_rel(file,self.game)
                    dest=dest.with_suffix('.il.txt');dest.parent.mkdir(parents=True,exist_ok=True)
                    n_il=0
                    with dest.open('w',encoding='utf-8') as stream:
                        for rid,method in enumerate(members,1):
                            if count>=self.max_methods:break
                            count+=1
                            full=metadata.owners.get(id(method),'?')+'::'+str(method.Name)
                            token=f'0x{(0x06000000|rid):08x}'
                            rec={'assembly':rel,'name':full,'token':token,'has_body':bool(method.Rva)}
                            if method.Rva and self.all_il:
                                try:
                                    body=metadata.body_limited(rid)
                                    rec['instructions']=len(body)
                                    stream.write('\n# '+token+' '+full+'\n')
                                    for ins in body:
                                        stream.write(f'{ins.offset:04x} {ins.opcode.name} {str(ins.operand) if ins.operand is not None else ""}\n')
                                    n_il+=1
                                except Exception as exc:
                                    rec['il_status']='unreadable';rec['il_error']=type(exc).__name__
                            index.write(json.dumps(rec,ensure_ascii=False)+'\n')
                    if n_il==0:dest.unlink(missing_ok=True)
                    assembly_rows.append({'assembly':rel,'methods':len(members),'il_exported':n_il,'status':'indexed'})
                except Exception as exc:
                    errors.append({'assembly':rel,'error_type':type(exc).__name__,'error':str(exc)[:350]})
                if i%4==0 or i==len(files):self.progress('code',i,len(files),rel)
                if count>=self.max_methods:
                    limit_hit=True
                    remaining_uninspected=len(files)-i
                    errors.append({'assembly':'[limit]','error_type':'MethodLimit',
                        'error':'Method cap reached; indexing incomplete. Rerun with increased --max-methods',
                        'assemblies_not_visited':remaining_uninspected})
                    break
        try:
            from combat_evidence_index import build_index
            focus=build_index(index_file,destination/'Combat-and-Protocol-Research-Queue.json')
            self.report['research_queue']={'matched_by_topic':focus['matched_by_topic']}
        except Exception as exc:
            errors.append({'assembly':'[evidence_index]','error_type':type(exc).__name__,'error':str(exc)[:350]})
        try:
            from evidence_signatures import audit_folder
            evidence=audit_folder(destination/'IL',destination/'Verified-Client-Methods.json')
            self.report['evidence_signatures']={name:entry['status'] for name,entry in evidence['verified_client_methods'].items()}
        except Exception as exc:
            errors.append({'assembly':'[client_signatures]','error_type':type(exc).__name__,'error':str(exc)[:350]})
        atomic_json(destination/'Assemblies.json',assembly_rows)
        atomic_json(destination/'Errors.json',errors)
        self.report['code']={'assemblies_indexed':len(assembly_rows),'assemblies_candidates':len(files),
            'assemblies_not_visited_due_to_limit':remaining_uninspected,
            'methods_indexed':count,'methods_limit':self.max_methods,
            'coverage_complete':not limit_hit,'method_limit_reached':limit_hit,
            'full_il_enabled':self.all_il,'errors':len(errors),
            'note':'Game assemblies are prioritized; method limit may omit dependency code.'}
        status='completed_with_limit' if limit_hit else 'completed'
        self.phase('code',status,f'{count} methods indexed; {len(errors)} warnings; '
                   +('INCOMPLETE method index' if limit_hit else 'method index complete'))

    def links(self):
        """Recover candidate material links while excluding non-material placeholders.

        `Texture` is a generic mesh-slot label in this game, not a texture
        filename. The more meaningful `segment_label` must be examined first.
        """
        self.phase('links','running','Matching model material labels to actual texture files')
        catalogue=self.out/'Reports'/'AssetLedger.jsonl'
        if not catalogue.exists():raise ValueError('Asset ledger missing')
        textures=defaultdict(list);models=[]
        with catalogue.open(encoding='utf-8') as fh:
            for line in fh:
                if not line.strip():continue
                row=json.loads(line)
                if row.get('kind')=='texture' and row.get('status')=='decoded':
                    textures[Path(row['path']).stem.casefold()].append(row)
                if row.get('kind')=='model' and row.get('status')=='decoded':
                    models.append(row)
        lines=[];placeholder_count=0;placeholder_models=set()
        for model in models:
            report=self.out/model['geometry_report']
            try:metadata=json.loads(report.read_text('utf-8'))
            except (ValueError,OSError,KeyError):continue
            for part in metadata.get('parts',[]):
                # The generic `Texture` tag is not a missing image.
                for key in ('segment_label','texture_label'):
                    val=part.get(key)
                    if not isinstance(val,str) or not val.strip():continue
                    value=val.strip()
                    if value.casefold() in ('texture','diffuse','none','null'):
                        placeholder_count+=1;placeholder_models.add(model['path'])
                        continue
                    matches=textures.get(Path(value).stem.casefold(),[])
                    lines.append({'model':model['path'],'mesh':part.get('mesh'),'part':part.get('part'),
                        'material_label':value,'evidence_field':key,
                        'candidate_textures':[r['path'] for r in matches],
                        'status':'matched_filename_not_verified_shader' if matches else 'unresolved'})
        out=self.out/'Reports'/'ModelTextureLinks.jsonl'
        with out.open('w',encoding='utf-8') as f:
            for row in lines:f.write(json.dumps(row,ensure_ascii=False)+'\n')
        matched=sum(bool(x['candidate_textures']) for x in lines)
        self.report['links']={
            'specific_material_references':len(lines),
            'model_parts_checked':len(lines), # legacy field for dashboards
            'matched':matched,
            'unmatched':len(lines)-matched,
            'generic_placeholder_labels_ignored':placeholder_count,
            'models_with_generic_placeholders':len(placeholder_models),
            'note':'Generic Texture labels are not missing textures; filename matches do not prove shader equivalence.'}
        self.phase('links','completed',f'{len(lines)} specific material references; '
                   f'{placeholder_count} generic placeholders ignored')

    def finalize(self):
        self.report['finished_utc']=utc()
        with self.db:
            database=self.db.execute('SELECT kind,status,COUNT(*) FROM assets GROUP BY kind,status').fetchall()
        self.report['asset_status_counts']=[{'kind':a,'status':b,'count':c} for a,b,c in database]
        self.report['limits_and_assumptions']={
            'exact_damage_formula':'unverified; only methods and static input values are indexed',
            'skin_rendering':'requires original shader/material behavior beyond type-reader discovery',
            'collision':'part-name is not proof of projectile or damage hitbox',
            'asset_decode_coverage':'use asset ledger; unsupported and failed are not counted as successful'}
        self._write()
        # Human-readable decoder accounting: completed != fully decoded.
        asset_count=sum(n for _,_,n in database)
        decoded_count=sum(n for _,status,n in database if status=='decoded')
        failed_count=sum(n for _,status,n in database if status=='failed')
        unsupported_count=sum(n for _,status,n in database if status=='unsupported')
        summary=['# WoSB Full Recovery — audit summary', '',
                 f'Generated: {self.report.get("finished_utc")}',
                 f'Decoder revision: {DECODER_REVISION}',
                 f'XNB records: {asset_count:,}',
                 f'Decoded assets: {decoded_count:,}',
                 f'Unsupported content: {unsupported_count:,}',
                 f'Decode failures: {failed_count:,}', '',
                 '## Breakdown by asset kind and outcome', '']
        summary+=['- '+kind+' / '+status+': '+str(n) for kind,status,n in database]
        summary+=['', '## Evidence limits',
                  '- Rendered mesh geometry does not establish gameplay hitboxes.',
                  '- Matching a texture name does not prove the original shader or material blend.',
                  '- Static client-code getters do not prove server-authoritative HP damage.',
                  '- See Reports/AssetLedger.jsonl for individual decoded, unsupported and failed reasons.',
                  '- Re-run Recovery to resume; use --recheck to reattempt unchanged items.']
        (self.out/'Reports'/'RecoverySummary.md').write_text('\n'.join(summary)+'\n',encoding='utf-8')
        (self.out/'START-HERE.md').write_text('''# WoSB Full Recovery — Research Output\n\n- `Recovery-Status.json`: progress, phase outcomes, counts and limitations.\n- `Reports/AssetLedger.jsonl`: one line per XNB with actual decode status and reason.\n- `Recovered/texture/`: decoded local game texture PNGs.\n- `Recovered/model/`: recovered real geometry OBJ and source metadata.\n- `Decoded-Payloads/`: optional raw decompressed XNB content.\n- `Code-Recovery/ManagedMethods.jsonl`: .NET method index; IL text is optional.\n- `Catalog/`: original full English tables, preserved assets, and AI handoff (if available).\n- `Reports/ModelTextureLinks.jsonl`: candidate matches only; not verified shaders.\n\nThis tool does not execute game DLLs or query game servers. A decoded mesh or static\nIL expression is not evidence that a collision shape or server-authoritative\ndamage multiplier is correct. Back up this output when retaining raw assets.\n''',encoding='utf-8')

    def run(self):
        try:
            self.assets()
            self.check_cancel()
            if self.catalog:
                try:self.catalog_export()
                except Exception as exc:self.phase('catalog','failed',str(exc))
            self.check_cancel()
            if self.code:
                try:self.recover_code()
                except Exception as exc:self.phase('code','failed',str(exc))
            self.check_cancel()
            try:self.links()
            except Exception as exc:self.phase('links','failed',str(exc))
            self.finalize()
            try:
                from repair_queue import export_queue
                queue=export_queue(self.out)
                self.report['repair_queue']={'tasks':len(queue['tasks']),
                    'path':'Reports/Repair-Queue.json'}
                self.phase('repair_queue','completed',f"{len(queue['tasks'])} research tasks generated")
            except Exception as exc:self.phase('repair_queue','failed',str(exc))
            try:
                from review_bundle import export_review
                review=export_review(self.out)
                self.report['review_only_zips']=[str(p.relative_to(self.out)) for p in review]
                self.phase('review_bundle','completed',f'{len(review)} failure-focused ZIP(s)')
            except Exception as exc:
                self.phase('review_bundle','failed',str(exc))
            self.report['result']='completed_with_errors' if any(x['status']=='failed' for x in self.report['phases'].values()) else 'completed'
            self._write()
            return self.report
        except InterruptedError:
            self.db.commit();self.report['result']='cancelled';self._write();return self.report
        finally:self.db.close()


def main(argv=None):
    p=argparse.ArgumentParser(description='WoSB one-pass read-only asset and managed-code recovery')
    p.add_argument('--game',required=True,help='Installed game folder or parent containing default/game')
    p.add_argument('--output',required=True,help='Persistent output folder outside game installation')
    p.add_argument('--no-catalog',action='store_true');p.add_argument('--no-code',action='store_true')
    p.add_argument('--recheck',action='store_true',help='Ignore asset cache and recheck every original asset')
    p.add_argument('--no-preserve',action='store_true');p.add_argument('--no-payloads',action='store_true')
    p.add_argument('--index-only-il',action='store_true');p.add_argument('--max-methods',type=int,default=MAX_METHODS)
    args=p.parse_args(argv)
    try:
        from extract_wosb import locate_game
        game=locate_game(args.game)
    except (ValueError,ImportError):
        game=Path(args.game)
    result=Recovery(game,args.output,catalog=not args.no_catalog,code=not args.no_code,
        preserve=not args.no_preserve,payloads=not args.no_payloads,all_il=not args.index_only_il,
        max_methods=args.max_methods,force=args.recheck).run()
    print(json.dumps({'result':result.get('result'),'output':str(args.output),'phases':result['phases']},indent=2))
    return 0 if result.get('result')=='completed' else 1

if __name__=='__main__':sys.exit(main())
