"""Read-only WoSB ship appearance research, preserving actual client skin links.

ShipDesingElements.Texture contains semicolon-separated base:replacement material IDs.
A material link and an asset basename match are evidence of association, not proof
of exact in-game shaders/effects. Never modifies game files or requests network data.
"""
from __future__ import annotations
import json
import os
import io
import base64
import zipfile
import re
import hashlib
from dataclasses import dataclass
from pathlib import Path
from ship_viewer import embedded_texture

MAX_ASSET_FILES=250_000
MAX_EMBEDDED_TEXTURES=40
MAX_EMBED_BYTES=30*1024*1024
MAX_EXTERNAL_TEXTURES=120
MAX_EXTERNAL_BYTES=512*1024*1024
# Local file:// HTML cannot reliably upload sidecar PNGs into WebGL.
# Write tiny per-texture JavaScript data-URI loaders for on-demand, offline viewing.
MAX_BROWSER_LOADER_BYTES=22*1024*1024
MAX_ARCHIVE_MEMBERS=400_000
MAX_IMAGE_BYTES=64*1024*1024


@dataclass(frozen=True)
class ResearchImage:
    archive: Path
    member: str
    size: int

    @property
    def name(self):
        return Path(self.member).name

    @property
    def suffix(self):
        return Path(self.member).suffix

    def __str__(self):
        return str(self.archive)+"!"+self.member


def _research_archives(base):
    """Find research part ZIPs; never extract an untrusted ZIP to the file system."""
    if base.is_file() and base.suffix.lower()=='.zip':return [base]
    if not base.is_dir():return []
    return sorted((p for p in base.glob('WOSB-Research-Part-*.zip') if p.is_file()),key=lambda p:p.name)


def _archive_assets(base, indexed):
    archives=_research_archives(base)
    total=0
    for archive in archives:
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                total+=1
                if total>MAX_ARCHIVE_MEMBERS:raise ValueError('Research ZIP set has too many entries')
                if info.is_dir() or info.file_size>MAX_IMAGE_BYTES:continue
                member=info.filename.replace('\\','/')
                if not member.startswith('WOSB-AI-Handoff/Images/') or '..' in member.split('/'):continue
                name=Path(member).name
                if Path(name).suffix.casefold() not in ('.png','.jpg','.jpeg','.webp'):continue
                indexed.setdefault(Path(name).stem.casefold(),[]).append(ResearchImage(archive,info.filename,info.file_size))
    return indexed


def _archive_texture(resource):
    """Read one verified user-owned PNG from a ZIP without bulk extraction.

    Reuse the exact decoded PNG bytes when possible; converting a 2048px texture
    can cost seconds and needlessly alter the preserved original image.
    """
    from PIL import Image
    if resource.size>MAX_IMAGE_BYTES:raise ValueError('Image too large')
    with zipfile.ZipFile(resource.archive) as z:
        with z.open(resource.member) as f:
            raw=f.read(MAX_IMAGE_BYTES+1)
    if len(raw)>MAX_IMAGE_BYTES:raise ValueError('Image decompression limit exceeded')
    with Image.open(io.BytesIO(raw)) as img:
        width,height=img.size
        if width*height>30_000_000:raise ValueError('Texture pixel limit exceeded')
        if img.format=='PNG' and width<=2048 and height<=2048 and len(raw)<=12*1024*1024:
            img.verify()
            data=raw
        else:
            im=img.convert('RGBA');im.thumbnail((2048,2048))
            width,height=im.size
            output=io.BytesIO();im.save(output,format='PNG',compress_level=3)
            data=output.getvalue()
    if len(data)>12*1024*1024:raise ValueError('Texture exceeds 12 MB render cap')
    return {'data_uri':'data:image/png;base64,'+base64.b64encode(data).decode('ascii'),
            'source_name':resource.name,'size':[width,height],
            'original_metadata':{'research_archive':resource.archive.name,'member':resource.member}}


def parse_swaps(text):
    swaps={}
    for item in str(text or '').split(';'):
        if ':' not in item:continue
        base,replacement=(x.strip() for x in item.split(':',1))
        if base and replacement and len(base)<128 and len(replacement)<128:
            swaps[base]=replacement
    return swaps


def _records(db=None):
    from workbench_db import bundled_path
    default=bundled_path('Research-Ship-Designs.json')
    records=json.loads(default.read_text(encoding='utf-8'))['records'] if default.is_file() else []
    if db is not None:
        try:
            entries=db.conn.execute("SELECT raw_json FROM records WHERE dataset='ShipDesingElements' ORDER BY CASE source_root WHEN 'Game' THEN 0 ELSE 1 END,id").fetchall()
            if entries:
                seen={(r.get('SourceRecord'),r.get('Category'),r.get('EnglishName')) for r in records}
                for entry in entries:
                    r=json.loads(entry['raw_json']);key=(r.get('SourceRecord'),r.get('Category'),r.get('EnglishName'))
                    if key not in seen:seen.add(key);records.append(r)
        except (AttributeError,ValueError):pass
    return records


def canonical_material(name):
    """Match case/path/known suffix variations without fuzzy guessing."""
    value = str(name or '').strip().replace('\\','/').split('/')[-1]
    for suffix in ('.material.xnb','.xnb','.png','.jpg','.jpeg','.webp'):
        if value.casefold().endswith(suffix):value=value[:-len(suffix)]
    return value.casefold()


def designs_for_ship(ship,db=None):
    ship_id=ship.get('ID')
    designs=[]
    for row in _records(db):
        if row.get('Category')!='ShipFullDesign' or str(row.get('ShipId'))!=str(ship_id):continue
        name=str(row.get('EnglishName') or '').strip()
        if not name or name.casefold()=='removed':continue
        swaps=parse_swaps(row.get('Texture'))
        designs.append({'name':name,'id':row.get('SourceRecord'),'ship_id':ship_id,
                        'swaps':swaps,'icon':row.get('IconName'),'availability':row.get('InShop'),
                        'source':row.get('Source'),'status':'catalog mapping, not yet verified in rendered game'})
    return designs


def detect_local_asset_root():
    """Find installed, user-owned textures without modifying the installation.

    This is only a discovery convenience; an explicitly selected folder wins.
    """
    candidates = [
        Path(r'C:\Games\World of Sea Battle'),
        Path(r'C:\Games\World of Sea Battle\default\game\Data'),
        Path(r'C:\Program Files (x86)\Steam\steamapps\common\World of Sea Battle'),
    ]
    for env in ('WOSB_GAME_ROOT', 'WOSB_ASSET_ROOT'):
        if os.environ.get(env):
            candidates.insert(0, Path(os.environ[env]))
    for root in candidates:
        if any((root/sub).is_dir() for sub in (
            'default/game/Data/ModelTextures', 'Data/ModelTextures', 'ModelTextures')):
            return str(root)
    return None


def scan_assets(directory):
    """Index local XNB/images and/or original 36 independently readable research ZIP parts.

    The archive entries remain inside their ZIP files; nothing is unzipped into
    the user's game installation. Indexing costs memory proportional to names,
    not to compressed image payload sizes.
    """
    base=Path(directory).resolve(strict=True)
    if not base.is_dir() and not (base.is_file() and base.suffix.lower()=='.zip'):
        raise ValueError('Select a game asset folder or research ZIP file')
    indexed={};count=0
    if base.is_dir():
        for path, dirs, files in os.walk(base):
            dirs[:]=[d for d in dirs if d.casefold() not in ('.git','node_modules','__pycache__','cache','logs','temp','tmp')]
            for filename in files:
                count+=1
                if count>MAX_ASSET_FILES:raise ValueError('Asset directory too large: narrow it to a game Data folder')
                candidate=Path(path)/filename
                if candidate.suffix.casefold() not in ('.xnb','.png','.jpg','.jpeg','.webp'):continue
                name=candidate.stem.casefold()
                if name and len(name)<=180:indexed.setdefault(name,[]).append(candidate)
    return _archive_assets(base,indexed)


def _best(paths):
    def rank(p):
        s=(p.member if isinstance(p,ResearchImage) else p.as_posix()).casefold()
        # Prefer pre-decoded research images; then LOD0 local model textures.
        return (0 if isinstance(p,ResearchImage) else 1,
                0 if '/modeltextures/' in s or '/textures/' in s else 1,
                0 if '/lod0/' in s else 1,
                0 if str(p).lower().endswith('.png') else 1,
                len(s),s)
    return sorted(paths,key=rank)[0]


def prepare_appearance(ship,mesh,*,game_assets_root=None,db=None,limit=MAX_EMBEDDED_TEXTURES,
                       texture_output_dir=None):
    designs=designs_for_ship(ship,db)
    materials=sorted({str(g.get('material') or '').strip() for g in (mesh or {}).get('groups',[]) if g.get('material') and str(g.get('material')).casefold() not in ('texture','unassigned')})
    requests=set(materials)
    canonical_mesh={canonical_material(m) for m in materials}
    for d in designs:
        d['matched_materials']=[name for name in d['swaps'] if canonical_material(name) in canonical_mesh]
        d['unmatched_materials']=[name for name in d['swaps'] if canonical_material(name) not in canonical_mesh]
        for original,replacement in d['swaps'].items():
            if canonical_material(original) in canonical_mesh:requests.add(replacement)
    from workbench_db import bundled_path
    inventory=bundled_path('Research-Texture-Paths.json')
    known_paths=json.loads(inventory.read_text('utf-8')).get('paths',[]) if inventory.is_file() else []
    lookup={}
    for path_string in known_paths:lookup.setdefault(Path(path_string).stem.casefold(),[]).append(path_string)
    out={'format':'wosb-appearance-1','designs':designs,'mesh_materials':materials,
         'textures':{},'unresolved':[],
         'expected_texture_paths':{name:lookup.get(name.casefold(),[])[:3] for name in sorted(requests)},'available_designs':len(designs),
         'evidence':'Client ShipDesingElements texture replacements + mesh SegmentTextureInfoTag + exact local asset filename matches; game shader effects unverified',
         'asset_directory_provided':bool(game_assets_root)}
    if not game_assets_root:
        out['unresolved']=sorted(requests)
        return out
    index=scan_assets(game_assets_root)
    if texture_output_dir is not None:
        texture_output_dir=Path(texture_output_dir)
        texture_output_dir.mkdir(parents=True,exist_ok=True)
        limit=max(limit,MAX_EXTERNAL_TEXTURES)
    total=0
    for name in sorted(requests,key=lambda n:(n not in materials,n.casefold())):
        candidates=index.get(canonical_material(name)) or []
        if not candidates:
            out['unresolved'].append(name)
            continue
        if len(out['textures'])>=min(limit,MAX_EXTERNAL_TEXTURES if texture_output_dir else MAX_EMBEDDED_TEXTURES):
            out['unresolved'].append(name);continue
        asset=_best(candidates)
        try:
            resource=_archive_texture(asset) if isinstance(asset,ResearchImage) else embedded_texture(asset)
            encoded=resource['data_uri']
            if texture_output_dir is not None:
                data=base64.b64decode(encoded.partition(',')[2],validate=True)
                estimate=len(data)
                if total+estimate>MAX_EXTERNAL_BYTES:
                    out['unresolved'].append(name);continue
                clean=re.sub('[^a-zA-Z0-9_-]+','_',name)[:80]
                digest=hashlib.sha256(str(asset).encode('utf-8')).hexdigest()[:12]
                filename=clean+'-'+digest+'.png'
                path=texture_output_dir/filename
                if not path.exists() or path.stat().st_size!=len(data):path.write_bytes(data)
                uri=texture_output_dir.name+'/'+filename
                # A user may open exported HTML using file://, whose opaque origin
                # blocks texImage2D uploads from adjacent PNG files in browsers.
                # A same-folder script is allowed and supplies a data:image/png URI
                # only when the selected material is actually used in the viewer.
                # The original PNG remains for GLB export; no remote server is used.
                if len(data)<=MAX_BROWSER_LOADER_BYTES:
                    browser_name=filename+'.js'
                    browser_path=texture_output_dir/browser_name
                    encoded_uri='data:image/png;base64,'+base64.b64encode(data).decode('ascii')
                    script=("window.__WOSB_LOCAL_TEXTURES__=window.__WOSB_LOCAL_TEXTURES__||{};\n"
                            + 'window.__WOSB_LOCAL_TEXTURES__['+json.dumps(name)+']='
                            +json.dumps(encoded_uri)+';\n')
                    browser_path.write_text(script,encoding='utf-8')
                    loader=texture_output_dir.name+'/'+browser_name
                else:
                    loader=None
            else:
                loader=None
                estimate=len(encoded)
                if total+estimate>MAX_EMBED_BYTES:
                    out['unresolved'].append(name);continue
                uri=encoded
            total+=estimate
            out['textures'][name]={'data_uri':uri,'source_name':asset.name,
                                   'size':resource['size'],'asset_source':str(asset),
                                   'browser_loader':loader,
                                   'match':'exact basename; verify against in-game materials'}
        except (OSError,ValueError,ImportError,RuntimeError,IndexError,KeyError) as exc:
            out['unresolved'].append(name)
            out.setdefault('errors',[]).append({'material':name,'asset':str(asset),'reason':str(exc)[:240]})
    out['embedded_bytes']=total if texture_output_dir is None else 0
    out['sidecar_bytes']=total if texture_output_dir is not None else 0
    out['sidecar_directory']=str(texture_output_dir) if texture_output_dir is not None else None
    return out
