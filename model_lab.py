"""Ship model discovery, persistent verified OBJ library, and opt-in XNB samples.

Actual geometry and hitboxes are never inferred from names, XNB paths, or code
references. Content-reader and LZX support must be validated on game-owned files
before XNB assets can be represented as meshes.
"""
from __future__ import annotations
from fsutil import replace_with_retry
import hashlib
import json
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from datetime import datetime, timezone
from workbench_db import home, slugify
from ship_viewer import read_obj, validate_zones
from xnb_diagnostics import inspect_xnb_bytes

MAX_SAMPLES = 12
MAX_SAMPLE_SIZE = 8 * 1024 * 1024
MAX_SAMPLE_TOTAL = 48 * 1024 * 1024
SHIP_XNB = re.compile(r'(^|/)(?:CommonData/|Data/)?Models/Ships/[^/]+\.xnb$', re.I)


def match_models(ship: dict, candidates, limit=8, expected_model_name=None):
    """Rank *candidate* model paths, never label any path as verified geometry."""
    name = str(ship.get('EnglishName') or ship.get('Name') or '')
    ship_id = str(ship.get('ID') or '')
    needle = slugify(name).replace('-', '_')
    expected = Path(str(expected_model_name or '')).stem.casefold()
    words = [word for word in needle.split('_') if len(word) > 2]
    ranked=[]
    for value in candidates:
        src = value.get('source') or value.get('RelativePath') or ''
        stem = Path(str(src).replace('\\','/')).stem.casefold()
        if not SHIP_XNB.search(str(src).replace('\\','/')): continue
        if 'externalhitbox' in stem.casefold(): continue
        score=100 if expected and stem==expected else 0
        # Source filename integer is usually an asset naming ID, not proof of
        # equivalence to a gameplay ship ID. Treat it as a research lead only.
        m=re.match(r'ship_(\d+)_',stem)
        # Numeric asset IDs are not always equal to ShipsToPlay IDs. Never
        # suggest a ship based only on the number (e.g. Victory 31 vs model 30).
        for word in words:
            if word in stem.replace('-','_'):score+=2
        if needle and needle in stem.replace('-','_'):score+=3
        if score:ranked.append({'path':src,'score':score,'status':value.get('status') or value.get('DecodeStatus') or 'unverified asset',
                                'assessment':('model link supported by ShipsToPlay.StaticInfoID → ShipsBasics.ModelName; geometry still must decode'
                                  if expected and stem==expected else 'filename candidate only; no verified geometry or hitbox relationship')})
    return sorted(ranked,key=lambda v:(-v['score'],v['path']))[:limit]


class ModelLibrary:
    """Keep user-imported verified OBJ meshes outside the installed program tree."""
    def __init__(self,root=None):
        self.root=Path(root or home()/'Models').resolve()
        self.root.mkdir(parents=True,exist_ok=True)
        self.index_file=self.root/'index.json'

    def _read(self):
        if not self.index_file.is_file():return {}
        try:
            data=json.loads(self.index_file.read_text('utf-8'))
            return data if isinstance(data,dict) else {}
        except (OSError,ValueError):return {}

    def _write(self,data):
        with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=self.root,delete=False,suffix='.tmp') as temp:
            name=Path(temp.name);json.dump(data,temp,indent=2,ensure_ascii=False)
        replace_with_retry(name,self.index_file)

    @staticmethod
    def key(ship,build):
        identifier=str(ship.get('ID') or slugify(str(ship.get('EnglishName') or ship.get('Name') or 'unknown')))
        return str(build).casefold()+':'+identifier

    def import_obj(self,ship,build,obj_path,zones_path=None,provenance='User-provided OBJ; game origin not independently verified'):
        obj=Path(obj_path).resolve(strict=True)
        if not obj.is_file() or obj.suffix.lower()!='.obj':raise ValueError('Select a Wavefront OBJ file')
        geometry=read_obj(obj)  # validate before the library is mutated
        zones=None
        if zones_path:
            original=Path(zones_path).resolve(strict=True)
            if original.suffix.lower()!='.json':raise ValueError('Select a JSON zones file')
            if original.stat().st_size>2*1024*1024:raise ValueError('Zones JSON too large')
            candidate=json.loads(original.read_text('utf-8'))
            zones=validate_zones(candidate)
        key=self.key(ship,build)
        directory=self.root/slugify(key)
        directory.mkdir(exist_ok=True)
        target=directory/'mesh.obj'
        with tempfile.NamedTemporaryFile('wb',dir=directory,delete=False,suffix='.tmp') as tmp:
            tmp_path=Path(tmp.name)
            with obj.open('rb') as inp:shutil.copyfileobj(inp,tmp,1024*1024)
        replace_with_retry(tmp_path,target)
        zones_file=None
        if zones is not None:
            zones_file=directory/'zones.json'
            zones_file.write_text(json.dumps({'zones':zones},indent=2),encoding='utf-8')
        index=self._read()
        index[key]={'mesh':str(target.relative_to(self.root)),'zones':str(zones_file.relative_to(self.root)) if zones_file else '',
                    'name':str(ship.get('EnglishName') or ship.get('Name') or ''),'ship_id':str(ship.get('ID') or ''),
                    'build':build,'source_label':provenance[:500],
                    'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
                    'imported_utc':datetime.now(timezone.utc).isoformat(),
                    'vertices':len(geometry['vertices']),'triangles':geometry['triangles_count'],
                    'geometry_status':'user-imported mesh; gameplay coordinate/hitbox alignment unverified'}
        self._write(index)
        return index[key]

    def _associations(self):
        filename=self.root/'candidate_links.json'
        try:
            data=json.loads(filename.read_text('utf-8'))
            return data if isinstance(data,dict) else {}
        except (OSError,ValueError):return {}

    def link_candidate(self,ship,build,candidate_path,source_root):
        """User-selected asset path; records a research lead, never a verified mesh."""
        value=str(candidate_path).replace('\\','/').strip()
        if not SHIP_XNB.search(value) or '\x00' in value or len(value)>2048:
            raise ValueError('Select an XNB file under Models/Ships')
        if source_root != build:
            raise ValueError('The candidate belongs to another game build')
        index=self._associations();index[self.key(ship,build)]={
            'path':value,'build':build,'source_root':source_root,
            'assessment':'User-linked filename only; actual mesh geometry not verified',
            'linked_utc':datetime.now(timezone.utc).isoformat()}
        with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=self.root,delete=False,suffix='.tmp') as temp:
            temporary=Path(temp.name);json.dump(index,temp,indent=2,ensure_ascii=False)
        replace_with_retry(temporary,self.root/'candidate_links.json')
        return index[self.key(ship,build)]

    def linked_candidate(self,ship,build):
        return self._associations().get(self.key(ship,build))

    def lookup(self,ship,build):
        entry=self._read().get(self.key(ship,build))
        if not entry:return None
        try:
            mesh=(self.root/entry['mesh']).resolve(strict=True)
            if self.root not in mesh.parents or not mesh.is_file():return None
            zones=None
            if entry.get('zones'):
                zones=(self.root/entry['zones']).resolve(strict=True)
                if self.root not in zones.parents:zones=None
            return {**entry,'mesh_path':str(mesh),'zones_path':str(zones) if zones and zones.is_file() else ''}
        except (OSError,ValueError):return None


def export_xnb_samples(game_root,paths,output):
    """Explicitly collect a small set of XNB files for decoder troubleshooting.

    Contains potentially copyrighted game assets. Caller must obtain user intent
    and warn that archive should be reviewed before it is shared.
    """
    root=Path(game_root).resolve(strict=True)
    if not root.is_dir():raise ValueError('Game root must be a directory')
    if len(paths)>MAX_SAMPLES:raise ValueError('Too many sample candidates')
    included=[];total=0
    for filename in paths:
        rel=str(filename).replace('\\','/').strip('/')
        if not rel or not rel.lower().endswith('.xnb') or ':' in rel or '\x00' in rel:
            continue
        parts=rel.split('/')
        if any(p in ('','..','.') for p in parts):continue
        actual=(root/Path(*parts)).resolve()
        if root not in actual.parents or not actual.is_file() or actual.stat().st_size>MAX_SAMPLE_SIZE:continue
        size=actual.stat().st_size
        if total+size>MAX_SAMPLE_TOTAL:break
        total+=size
        included.append((rel,actual))
    if not included:raise ValueError('No matching local XNB files in the selected game directory')
    out=Path(output).resolve()
    out.parent.mkdir(parents=True,exist_ok=True)
    manifest=[]
    with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for i,(rel,path) in enumerate(included,1):
            data=path.read_bytes()
            label=f'sample-{i:02d}.xnb'
            z.writestr(label,data)
            manifest.append({'sample':label,'relative_path':rel,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),
                            'xnb_magic':data[:8].hex(),
                            'diagnostics':inspect_xnb_bytes(data)})
        z.writestr('README-FIRST.txt','Contains RAW game assets collected only on user request. Review before sharing; do not redistribute without permission.\n')
        z.writestr('manifest.json',json.dumps({'samples':manifest,'warning':'Game assets may be copyrighted. No license or reuse rights are granted by this export.'},indent=2))
    return {'output':str(out),'files':len(included),'bytes':total}


def locate_model_candidate(relative_path, source_build, additional_roots=()):
    """Locate a *loose* XNB by its report path without guessing the ship ID.

    Does not search arbitrary archives or execute any game code.
    """
    rel=str(relative_path).replace('\\','/').strip('/')
    if not SHIP_XNB.search(rel):raise ValueError('Candidate is not a ship-model XNB')
    if '\x00' in rel or ':' in rel or any(x in ('..','.') for x in rel.split('/')):
        raise ValueError('Unsafe model asset path')
    roots=list(additional_roots)
    if source_build=='Game':roots.append(r'C:\Games\World of Sea Battle')
    if source_build=='Steam':roots.append(r'C:\Program Files (x86)\Steam\steamapps\common\World of Sea Battle')
    for root in roots:
        base=Path(root)
        if not base.is_dir():continue
        possibilities=[base/Path(*rel.split('/'))]
        if rel.casefold().startswith('default/game/'):
            possibilities.append(base/Path(*rel.split('/')[2:]))
        else:
            possibilities.append(base/'default'/'game'/Path(*rel.split('/')))
        for candidate in possibilities:
            if candidate.is_file():
                actual=candidate.resolve()
                if base.resolve() in actual.parents:return actual
    return None


def recover_model_for_ship(ship,build,xnb_path,library=None,*,source_label=None,expected_model_name=None):
    """Recover an actual OBJ from a raw XNB, save it and its evidence persistently.

    Only the explicitly selected XNB is converted. The selected ship association is
    user-confirmed, because asset indices do not always match game ship IDs.
    """
    import sys
    from workbench_db import bundled_path
    engine=str(bundled_path('engine'))
    if engine not in sys.path:sys.path.insert(0,engine)
    from xnb_geometry import convert_xnb
    library=library or ModelLibrary()
    source=Path(xnb_path).resolve(strict=True)
    if source.suffix.lower() not in ('.xnb','.zip') or source.stat().st_size>512*1024*1024:
        raise ValueError('Select a supported ship-model .xnb or debug sample ZIP')
    with tempfile.TemporaryDirectory(prefix='wosb-recover-') as directory:
        src=source
        if source.suffix.lower()=='.zip':
            with zipfile.ZipFile(source) as archive:
                items=[x for x in archive.infolist() if x.filename.lower().endswith('.xnb') and not x.is_dir()]
                if not 1<=len(items)<=MAX_SAMPLES:raise ValueError('Debug archive must contain 1 to 12 model samples')
                try:manifest=json.loads(archive.read('manifest.json'))
                except (KeyError,ValueError):manifest={}
                original={x.get('sample'):x.get('relative_path') for x in manifest.get('samples',[]) if isinstance(x,dict)}
                expected=Path(str(expected_model_name or '')).stem.casefold()
                chosen=[x for x in items if expected and Path(str(original.get(x.filename,x.filename))).stem.casefold()==expected]
                if len(chosen)==1:item=chosen[0]
                elif len(items)==1:item=items[0]
                else:raise ValueError('Multiple XNBs in debug ZIP; select a single ship model, or supply its exact ShipsBasics.ModelName')
                if item.file_size>MAX_SAMPLE_SIZE:raise ValueError('XNB sample exceeds safe size limit')
                src=Path(directory)/'sample.xnb';src.write_bytes(archive.read(item))
                source_label=str(source)+'!'+str(original.get(item.filename,item.filename))
        out=Path(directory)/'ship.obj'
        report=convert_xnb(src,out)
        note=('XNB decoded into real mesh triangles; game asset association selected by user. '
              'No textures or damage-zone correspondences verified. Source SHA-256: '+report['sha256'])
        entry=library.import_obj(ship,build,out,provenance=note)
        key=library.key(ship,build)
        record=library._read()
        record[key].update({'xnb_source':str(source_label or source),'xnb_sha256':report['sha256'],
                            'mesh_decoder':'XNA ModelReader validated buffers + UV v3.8',
                            'mesh_geometry_status':report['geometry_status'],
                            'vulnerability_status':'unknown; no damage location evidence verified'})
        library._write(record)
        model_dir=library.root/slugify(key)
        report_file=model_dir/'model-provenance.json'
        report['source']=str(source_label or source)
        report_file.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
        return {**library.lookup(ship,build),'recovery_report':str(report_file),
                'mesh_count':report['mesh_count'],'triangles':report['triangles']}


def expected_model_for_ship(db, ship, build):
    """Authoritative *catalog linkage* (not a damage map): playable StaticInfoID → basics ModelName."""
    reference=ship.get('StaticInfoID')
    if reference is None:return None
    row=db.conn.execute("SELECT raw_json FROM records WHERE dataset='ShipsBasics' AND source_root=? AND external_id=?",
                        (build,str(reference))).fetchone()
    if not row:
        # Builds may serialize the id in a different external_id field.
        rows=db.conn.execute("SELECT raw_json FROM records WHERE dataset='ShipsBasics' AND source_root=?",
                             (build,)).fetchall()
        for candidate in rows:
            obj=json.loads(candidate['raw_json'])
            if str(obj.get('ID'))==str(reference):
                row=candidate;break
    if not row:return None
    obj=json.loads(row['raw_json'])
    model=str(obj.get('ModelName') or '').strip()
    if not model or len(model)>160 or '/' in model or '\\' in model:return None
    return {'model_name':model,'static_info_id':reference,'source':obj.get('Source',''),
            'assessment':'client catalog mapping only; model decode and damage relationships separate'}
