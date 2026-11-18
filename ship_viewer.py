"""Offline, evidence-gated WebGL ship viewer preparation.

OBJ geometry and optional JSON hitbox annotations are imported from files the
user already owns or has exported. Never guesses vulnerable locations.
"""
from __future__ import annotations

import base64
import io
import json
import math
import sys
from pathlib import Path

MAX_FACES = 3_000_000
MAX_VERTICES = 3_000_000
MAX_ZONES = 500


def classify_component(name):
    """Conservative visual categories inferred from mesh names, not game physics."""
    n = str(name).casefold()
    if 'averagebox' in n or 'hitbox' in n or 'shapestr' in n or 'collision' in n:
        return 'helper'
    if 'shiplowcorpus' in n or 'shipmin_' in n or n.startswith('shipmin'):
        return 'lod'
    if 'sail' in n or 'flag' in n:
        return 'sails'
    if 'mast' in n or 'arris' in n or 'frame' in n or 'connection' in n:
        return 'rigging'
    return 'hull'


def read_obj(filename, *, triangle_budget=None):
    """Read complete OBJ geometry without deleting/sampling individual faces.

    A material switch starts a new draw group. This matters for WoSB ship meshes
    where hull, decor and sail textures coexist within one OBJ object.
    ``triangle_budget`` is retained for compatibility, but no longer removes
    faces; excessive models must be handled with a true LOD/GLB viewer.
    """
    path = Path(filename)
    if not path.is_file() or path.stat().st_size > 650 * 1024 * 1024:
        raise ValueError('OBJ must exist and be smaller than 650 MB')
    # Explicit guard prevents silently producing Swiss-cheese geometry. GLB
    # export remains an alternative for assets beyond the browser's memory cap.
    max_display_faces = 750_000
    vertices, uvs, triangles, tri_uv, groups = [], [], [], [], []
    current_name = 'Unlabeled_mesh'
    material = ''
    group = None
    count = 0
    uv_any = False

    def add_group():
        nonlocal group
        group = {'name': current_name, 'first_triangle': count,
                 'triangle_count': 0, 'original_triangles': 0,
                 'category': classify_component(current_name),
                 'material': material}
        groups.append(group)

    with path.open('r', encoding='utf-8', errors='replace') as source:
        for line in source:
            if line.startswith(('o ', 'g ')):
                current_name = line[2:].strip()[:140] or 'Unlabeled_mesh'
                group = None
            elif line.startswith('usemtl '):
                next_material = line[7:].strip()[:140]
                if next_material != material:
                    material = next_material
                    # Even within a single named mesh, a new material needs its
                    # own contiguous GPU draw span and texture binding.
                    group = None
            elif line.startswith('v '):
                vals = line.split()
                if len(vals) >= 4:
                    if len(vertices) >= MAX_VERTICES:raise ValueError('OBJ vertex limit exceeded')
                    pos = [float(v) for v in vals[1:4]]
                    if not all(math.isfinite(v) for v in pos):raise ValueError('Invalid vertex')
                    vertices.append(pos)
            elif line.startswith('vt '):
                vals = line.split()
                if len(vals) >= 3:
                    if len(uvs) >= MAX_VERTICES:raise ValueError('OBJ UV limit exceeded')
                    pair = [float(v) for v in vals[1:3]]
                    if not all(math.isfinite(v) for v in pair):raise ValueError('Invalid UV')
                    uvs.append(pair)
            elif line.startswith('f '):
                refs = line.split()[1:]
                if len(refs) < 3:continue
                count_faces = len(refs) - 2
                if count + count_faces > max_display_faces:
                    raise ValueError(f'Full-resolution mesh has more than {max_display_faces:,} triangles. '
                                     'Use the GLB export / game LOD instead; no faces were discarded.')
                if group is None:add_group()
                def index(ref):
                    bits = ref.split('/')
                    v = int(bits[0]);vi = v-1 if v>0 else len(vertices)+v
                    if not 0 <= vi < len(vertices):raise ValueError('OBJ face vertex out of range')
                    ui = -1
                    if len(bits)>1 and bits[1]:
                        u = int(bits[1]);ui = u-1 if u>0 else len(uvs)+u
                        if not 0 <= ui < len(uvs):raise ValueError('OBJ face UV out of range')
                    return vi,ui
                for j in range(1,len(refs)-1):
                    trip = (index(refs[0]),index(refs[j]),index(refs[j+1]))
                    for vi,ui in trip:
                        triangles.append(vi);tri_uv.append(ui)
                        if ui >= 0:uv_any=True
                    count+=1;group['triangle_count']+=1
                    group['original_triangles']+=1
    if not triangles:raise ValueError('No supported OBJ geometry found')
    used_v=sorted(set(triangles));v_map={old:i for i,old in enumerate(used_v)}
    render_vertices=[vertices[i] for i in used_v]
    render_triangles=[v_map[i] for i in triangles]
    if uv_any:
        used_uv=sorted({i for i in tri_uv if i>=0});u_map={old:i for i,old in enumerate(used_uv)}
        render_uvs=[uvs[i] for i in used_uv]
        render_tri_uv=[u_map.get(i,-1) for i in tri_uv]
    else:render_uvs=[];render_tri_uv=[]
    return {'vertices':render_vertices,'triangles':render_triangles,'uvs':render_uvs,
            'triangle_uvs':render_tri_uv,'triangles_count':count,'original_triangles_count':count,
            'sampling_status':'full_resolution', 'source_name':path.name,
            'groups':[g for g in groups if g['triangle_count']>0]}


def candidate_hitboxes_from_mesh(mesh, max_zones=80):
    """Expose already-recovered helper geometry as *candidates*, not game damage zones.

    The boxes are measured from original helper triangles, not invented. A
    corresponding game hitbox role has NOT been proven by the OBJ part name.
    """
    if not mesh:return []
    out=[]
    for group in mesh.get('groups',[]):
        if group.get('category')!='helper':continue
        start=group['first_triangle']*3
        end=start+group['triangle_count']*3
        ids=set(mesh['triangles'][start:end])
        if not ids:continue
        lo=[min(mesh['vertices'][i][axis] for i in ids) for axis in range(3)]
        hi=[max(mesh['vertices'][i][axis] for i in ids) for axis in range(3)]
        size=[hi[i]-lo[i] for i in range(3)]
        if not all(math.isfinite(x) for x in size) or min(size)<=0:continue
        out.append({'name':group['name'],'shape':'box',
                    'center':[(a+b)/2 for a,b in zip(lo,hi)],'size':size,
                    'classification':'suspected collision helper',
                    'evidence_status':'candidate','source':'recovered OBJ helper mesh: '+group['name'],
                    'notes':'Bounds of a mesh labeled as a helper; role in projectile collision or damage has not been established'})
        if len(out)>=max_zones:break
    return out


def catalog_hitbox_candidate(ship, db):
    """Parse explicit ShipsBasics hull bounds when present, with coordinate warning."""
    if db is None or ship.get('StaticInfoID') is None:return []
    try:
        # Prefer the ship's own build, then Game; previously only 'Game' was searched,
        # so Steam-only catalogs never produced the catalog hull candidate.
        build=str(ship.get('_build') or ship.get('source_root') or 'Game')
        rows=db.conn.execute("SELECT raw_json,source_root FROM records WHERE dataset='ShipsBasics' "
                             "ORDER BY CASE source_root WHEN ? THEN 0 WHEN 'Game' THEN 1 ELSE 2 END",(build,)).fetchall()
        match=None
        for r in rows:
            candidate=json.loads(r[0])
            if str(candidate.get('ID'))==str(ship['StaticInfoID']):
                match=candidate;break
        if not match:return []
        def parse(value):
            if isinstance(value,(list,tuple)):arr=value
            else:arr=str(value or '').replace(',',' ').split()
            if len(arr)!=3:return None
            vals=[float(v) for v in arr]
            return vals if all(math.isfinite(v) for v in vals) else None
        center=parse(match.get('CorpusHitboxCenter'))
        size=parse(match.get('CorpusHitboxSize'))
        if center is None or size is None or any(v<=0 for v in size):return []
        return [{'name':'Catalog corpus bounds','shape':'box','center':center,'size':size,
                 'classification':'catalog hull candidate','evidence_status':'candidate',
                 'source':f"ShipsBasics.ID={match.get('ID')}: CorpusHitboxCenter/CorpusHitboxSize",
                 'notes':'Stored client bounds; transform and authoritative collision usage require validation'}]
    except (ValueError,TypeError,KeyError,AttributeError):return []


def embedded_texture(texture_path):
    """Pack a local user-selected image or Texture2D XNB into an offline viewer."""
    if not texture_path:return None
    path=Path(texture_path)
    if not path.is_file() or path.stat().st_size>64*1024*1024:
        raise ValueError('Texture must be a local file smaller than 64 MB')
    if path.suffix.lower() not in ('.png','.jpg','.jpeg','.webp','.xnb'):
        raise ValueError('Use a local PNG/JPEG/WEBP or Texture2D XNB')
    from PIL import Image
    if path.suffix.lower()=='.xnb':
        from workbench_db import bundled_path
        engine=str(bundled_path('engine'))
        if engine not in sys.path:sys.path.insert(0,engine)
        from xnb_images import texture
        im,meta=texture(path.read_bytes())
    else:
        im=Image.open(path)
        im.load();meta={'Width':im.width,'Height':im.height}
    if im.width*im.height>30_000_000:
        raise ValueError('Texture resolution exceeds 30 million pixels')
    im=im.convert('RGBA');im.thumbnail((2048,2048))
    buf=io.BytesIO();im.save(buf,format='PNG',optimize=True)
    b=buf.getvalue()
    if len(b)>12*1024*1024:raise ValueError('Texture PNG exceeds 12 MB after conversion')
    return {'data_uri':'data:image/png;base64,'+base64.b64encode(b).decode('ascii'),
            'source_name':path.name,'size':[im.width,im.height],
            'note':'User-selected texture; source part-to-image association not verified',
            'original_metadata':meta}

def validate_zones(data):
    """Only accept sourced, explicitly characterized volumes; unknown is allowed.

    JSON schema: {"zones": [{"name", "shape":"box", "center":[x,y,z],
    "size":[w,h,d], "classification":"hull|mast|sail|...", "source":...
    "damage_multiplier":optional, "evidence_status":"verified|candidate|manual"}]}
    """
    zones = data.get('zones',[]) if isinstance(data,dict) else data
    if not isinstance(zones,list) or len(zones)>MAX_ZONES: raise ValueError('Invalid zones list')
    result=[]
    for item in zones:
        if not isinstance(item,dict):raise ValueError('Each zone must be an object')
        name=str(item.get('name','')).strip()[:140]
        if not name:raise ValueError('Every zone needs a name')
        shape=str(item.get('shape','box')).lower()
        if shape!='box':raise ValueError('Only box-shaped overlays are currently supported')
        center=item.get('center',[0,0,0]);size=item.get('size',[1,1,1])
        if not (isinstance(center,list) and isinstance(size,list) and len(center)==3 and len(size)==3):
            raise ValueError('Zone center and size must each have 3 values')
        center=[float(x) for x in center];size=[float(x) for x in size]
        if not all(math.isfinite(x) and abs(x)<1e9 for x in center+size):raise ValueError('Invalid zone coordinates')
        if not all(x>0 for x in size):raise ValueError('Zone dimensions must be positive')
        status=str(item.get('evidence_status','manual'))
        if status not in ('verified','candidate','manual'):raise ValueError('Invalid evidence status')
        src=str(item.get('source','')).strip()[:500]
        multiplier=item.get('damage_multiplier')
        if multiplier is not None:
            multiplier=float(multiplier)
            if not math.isfinite(multiplier) or multiplier<0:raise ValueError('Invalid damage multiplier')
            if status=='verified' and not src:
                raise ValueError('A verified damage multiplier requires a source')
        # Verified claims must carry source references; the viewer does not certify truth.
        if status=='verified' and not src:raise ValueError('Verified zone requires a source reference')
        result.append({'name':name,'shape':'box','center':center,'size':size,
                       'classification':str(item.get('classification','unknown'))[:80],
                       'source':src,'evidence_status':status,'damage_multiplier':multiplier,
                       'notes':str(item.get('notes',''))[:1000]})
    return result


def make_html(ship, mesh=None, zones=None, template=None, *, texture=None, ballistics=None, appearance=None, observations=None, mesh_quality=None):
    root=Path(__file__).resolve().parent
    template=Path(template or root/'viewer'/'ship_viewer.html')
    html=template.read_text('utf-8')
    data={'ship':ship,'mesh':mesh,'zones':validate_zones({'zones':zones or []}),
          'texture':texture,'ballistics':ballistics or {'datasets':{},'provenance':'No catalog'},'appearance':appearance or {},'observations':observations or [],'mesh_quality':mesh_quality}
    payload=json.dumps(data,ensure_ascii=False,separators=(',',':')).replace('<',r'\u003c').replace('>',r'\u003e').replace('&',r'\u0026')
    return html.replace('/*__MODEL_DATA__*/',payload)


def export_viewer(output, ship, mesh_path=None, zones_path=None, template=None,
                  *, texture_path=None, ballistics=None, game_assets_root=None, db=None, observations_csv=None):
    mesh=read_obj(mesh_path) if mesh_path else None
    zones=json.loads(Path(zones_path).read_text('utf-8')) if zones_path else None
    # Candidate geometry is visible independently from any manually confirmed zones.
    if zones is None:
        zones={'zones':candidate_hitboxes_from_mesh(mesh)+catalog_hitbox_candidate(ship,db)}
    if ballistics is None:
        from ballistics_lab import load_ballistics_catalog
        ballistics=load_ballistics_catalog()
    from appearance_lab import prepare_appearance
    from calibration_lab import load_trials
    # Keep original-resolution PNGs in a sibling folder so the HTML stays small.
    # Browser file:// pages may load their own relative images offline.
    from appearance_lab import detect_local_asset_root
    game_assets_root = game_assets_root or detect_local_asset_root()
    export_path=Path(output)
    texture_output_dir=export_path.parent/(export_path.stem+'-assets') if game_assets_root else None
    appearance=prepare_appearance(ship,mesh,game_assets_root=game_assets_root,db=db,
                                  texture_output_dir=texture_output_dir)
    observations=load_trials(observations_csv) if observations_csv else []
    from model_quality import inspect_mesh
    quality=inspect_mesh(mesh) if mesh else None
    doc=make_html(ship,mesh,zones['zones'] if isinstance(zones,dict) else zones,
                  template=template,texture=embedded_texture(texture_path),ballistics=ballistics,
                  appearance=appearance,observations=observations,mesh_quality=quality)
    path=Path(output);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(doc,encoding='utf-8')
    # Small human-readable report: no embedded images, packet data or private
    # installation paths. Useful for determining why a design stays unchanged.
    active_textures=set(appearance.get('textures',{}))
    report={
        'format':'wosb-appearance-diagnostics-v433',
        'ship':str(ship.get('EnglishName') or ship.get('Name') or ship.get('ID')),
        'mesh_source':Path(mesh_path).name if mesh_path else None,
        'asset_directory_provided':appearance.get('asset_directory_provided',False),
        'mesh_materials':appearance.get('mesh_materials',[]),
        'loaded_texture_candidates':sorted(active_textures),
        'unresolved_materials':appearance.get('unresolved',[]),
        'decode_errors':appearance.get('errors',[]),
        'designs':[
            {'name':d['name'],'matched_base_materials':d.get('matched_materials',[]),
             'unmatched_base_materials':d.get('unmatched_materials',[]),
             'replacement_images_found':{src:(repl in active_textures) for src,repl in d.get('swaps',{}).items()}}
            for d in appearance.get('designs',[])
        ],
        'note':'Texture filename matches are candidates, not verified game shader assignments. Runtime WebGL load errors appear in the viewer.'
    }
    path.with_name(path.stem+'-Appearance-Diagnostics.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    if quality:
        path.with_name(path.stem+'-Mesh-Quality.json').write_text(json.dumps(quality,indent=2),encoding='utf-8')
    return path

def ship_catalog(db, build='Game'):
    rows=db.conn.execute('''SELECT raw_json,source_root FROM records WHERE dataset='ShipsToPlay'
       ORDER BY CASE source_root WHEN ? THEN 0 WHEN 'Steam' THEN 1 ELSE 2 END,name COLLATE NOCASE''',(build,)).fetchall()
    builds={r['source_root'] for r in rows}
    selected=build if build in builds else ('Steam' if 'Steam' in builds else (rows[0]['source_root'] if rows else None))
    return [json.loads(r['raw_json']) for r in rows if r['source_root']==selected]


def seed_hitbox_pages(db):
    doc='''# Ship model vulnerability mapping

**Status:** Source-validated model vertex/index recovery is now available for the user-supplied Vasa XNB, with 168,474 vertices and 155,166 triangles. Other models may use unsupported custom readers. Collision and vulnerability mechanics are NOT verified.

## Recoverable code evidence

- `Common.Resources.CorpusHitbox` — `NodeID`, `Shape`, `Hitmesh`, `EnumerateBaseShapes`.
- `Common.Resources.MastHitbox` and `SailHitbox` — distinct hit target types.
- `Common.Game.Ship.CannonBallCollisionTest` — checks a projectile against the ship collision system.
- `Common.Game.Ship.DistanceToHitbox` — uses `CorpusHalfWidth` and `CorpusHalfLength`.
- `Common.Game.ShipModelContent` — model and pivot metadata.

## How to generate an accurate overlay

1. Decode original XNB model geometry, preserve units, pivot/bone transforms and mesh names.
2. Recover the corresponding hull/mast/sail hitbox data from the game's content structures.
3. Map collision regions into the same coordinate system as the rendered model.
4. Trace the actual damage calculation to determine whether an impact area has a distinct multiplier or armor value.
5. Attach a per-region source, game-client version, and confidence state.
6. Export a mesh and zones JSON, then load them in the **Ship 3D** tab.

A hitbox is not automatically a weak spot. Distinct damage must be supported by code or controlled trials.

## Current extraction blocker

The Vasa sample's shared VertexBufferReader and IndexBufferReader streams were structurally located and decoded into a real OBJ, preserving mesh names and bone transforms. The sample has 93 mesh parts. On other ships, unsupported readers or incompatible layouts must be reported as failures rather than guessed. The Windows decoder still needs a real Windows run. Damage-zone coordinates remain unknown.

## Overlay JSON format

```json
{"zones":[{"name":"Example hull box — not a game observation","shape":"box","center":[0,0,0],"size":[1,1,1],"classification":"hull","evidence_status":"manual","source":"","damage_multiplier":null,"notes":"Template only"}]}
```

Use real coordinates from client hitboxes; don't interpret sample geometry as evidence.
'''
    db.upsert_article('research-ship-model-hitboxes','Ship models, hitboxes and damage zones',
     'Ships, hulls & construction',doc,'research-outline','Common.dll hitbox types; ModelAssetCandidates','needs-review',preserve_edited=True)
    db.upsert_article('research-vasa-xnb-forensics',
        'Vasa XNB model — verified structure', 'Ships, hulls & construction',
        '''# Vasa: verified XNB content structure

**Evidence:** user-provided `default/game/CommonData/Models/Ships/Ship_62_Vasa.xnb`,
SHA-256 `ac892c5186354a2d7c12cb28ffad604e32c813f82ad89886d5345d5e26a550c0`.

- Valid `WOSB`-wrapped XNB v5, Windows platform, LZX compression.
- **153 LZX frames**, followed by 5 zero-padding bytes, are structurally sound.
- Native CAB-compatible decoder successfully recovered **5,004,353 bytes** of payload in the test environment.
- Root content type: `Microsoft.Xna.Framework.Content.ModelReader`.
- **27** XNA content-reader types, including several custom WoSB reflective readers.
- **95** shared-resource references; **40** bone records parsed with hierarchy; **39** mesh records and **93** mesh parts recovered.
- Real shared geometry buffers found with 24-byte vertex stride, 168,474 vertices and 465,498 16-bit indices.
- **155,166 validated triangles** exported to a usable Wavefront OBJ; actual Vasa shape is now available for inspection without invented geometry.
- The playable Vasa ID **70** links to `ShipsBasics.ID = 62` via `ShipsToPlay.StaticInfoID`, which resolves the asset `Ship_62_Vasa`.
- First named mesh: `1_SailAnimated1` (a mesh record, not proof of a damage target).

## What is NOT established

A compatible `UWModelMeshPartTag` layout has been validated on this sample and the real vertex/index buffers converted to OBJ. **Textures, material shaders, animation behavior, collision volumes and damage multipliers are NOT yet decoded or verified.** Structural vertex/index validation is not a substitute for visual inspection. Windows CAB decompression needs real-machine validation.

The filename number `62` is an asset ID; it must not automatically be treated as
an exact gameplay ship ID. Never color a ship region as vulnerable without damage-code
and hitbox evidence.

## Follow-up work

1. Validate the recovered Vasa OBJ visually against the game; test other ship XNB types.
2. Decode textures/material bindings and map other custom tag layouts safely.
3. Link `CorpusHitbox`, `MastHitbox`, and `SailHitbox` to coordinate-correct geometry.
4. Trace damage modifiers and verify weak-point rules experimentally.
5. Preserve ship model source SHA-256 and client build evidence.
''','client-static-evidence',
        'Ship_62_Vasa.xnb + local bounded XNB reader, SHA-256 ac892c51…',
        'needs-review',preserve_edited=True)
    db.conn.commit()
