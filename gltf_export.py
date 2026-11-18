"""Standards-oriented GLB 2.0 export of recovered ship render geometry.

Materials use matched original image basenames and recovered OBJ UVs; this is a
faithful texture association, NOT a claim to reproduce WoSB's custom shaders,
lighting, hitbox logic, effects, or animations. Preserves the complete recovered OBJ without triangle sampling.
"""
from __future__ import annotations
import base64
import json
import math
import struct
from pathlib import Path

MAX_IMAGE_BYTES=64*1024*1024
MAX_PRIMITIVES=5000
MAX_TRIANGLES=500_000


def _unit(v):
    n=math.sqrt(sum(x*x for x in v))
    return tuple(x/n for x in v) if n>1e-12 else (0.0,1.0,0.0)


def _normal(a,b,c):
    u=[b[i]-a[i] for i in range(3)];v=[c[i]-a[i] for i in range(3)]
    return _unit((u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]))


def _asset_bytes(entry,asset_dir):
    if not entry:return None
    uri=entry.get('data_uri') or ''
    if uri.startswith('data:image/png;base64,'):
        data=base64.b64decode(uri.split(',',1)[1],validate=True)
    else:
        if not asset_dir:return None
        base=Path(asset_dir).resolve();target=(base/uri).resolve()
        if target!=base and base not in target.parents:raise ValueError('Texture path escapes asset directory')
        data=target.read_bytes() if target.is_file() else b''
    if not data or len(data)>MAX_IMAGE_BYTES: return None
    if not data.startswith(b'\x89PNG\r\n\x1a\n'):return None
    return data


def export_glb(mesh,appearance,output,*,design_name=None,asset_dir=None):
    """Write a mesh with original material IDs, texture PNGs and UV coordinates.

    Returns a report with data provenance, source triangle count and missing
    texture IDs. The binary GLB contains only materials used by this design.
    """
    groups=mesh.get('groups') or []
    ntri=int(mesh.get('triangles_count',0))
    if not groups or ntri<=0 or ntri>MAX_TRIANGLES or len(groups)>MAX_PRIMITIVES:
        raise ValueError('Unsupported or oversized recovered display mesh')
    designs=appearance.get('designs') or []
    if design_name:
        selected=next((x for x in designs if x['name']==design_name),None)
        if selected is None:raise ValueError('Unknown full-ship design: '+design_name)
    else:selected=None
    swaps=selected.get('swaps',{}) if selected else {}
    def normalized(value):
        return str(value or '').strip().replace('\\','/').split('/')[-1].casefold()
    swap_lookup={normalized(key):value for key,value in swaps.items()}
    textures=appearance.get('textures') or {}
    texture_lookup={normalized(key):value for key,value in textures.items()}
    def chosen_material(original):
        return swap_lookup.get(normalized(original), original)

    result={'asset':{'version':'2.0','generator':'WoSB Workbench v4.0 recovered-asset GLB exporter'},
            'scene':0,'scenes':[{'nodes':[0]}],
            'nodes':[{'mesh':0,'name':'Recovered ship visual mesh'}],
            'meshes':[{'name':'Recovered WoSB geometry','primitives':[]}],
            'materials':[],'accessors':[],'bufferViews':[],'buffers':[{'byteLength':0}],
            'images':[],'textures':[],
            'extras':{'source':mesh.get('source_name'),'sample_status':mesh.get('sampling_status'),
                      'original_triangles':mesh.get('original_triangles_count'),'display_triangles':ntri,
                      'design_name':design_name or 'Default',
                      'important':'Matched recovered textures are real client assets, but custom shaders, animation, and damage hitboxes are unverified.'}}
    binary=bytearray();material_cache={};texture_cache={};missing=set()
    def add_view(data,target=None):
        while len(binary)%4:binary.append(0)
        off=len(binary);binary.extend(data)
        view={'buffer':0,'byteOffset':off,'byteLength':len(data)}
        if target:view['target']=target
        result['bufferViews'].append(view)
        return len(result['bufferViews'])-1
    def add_accessor(data,components,kind,*,min_vals=None,max_vals=None):
        v=add_view(data,target=34962)
        accessor={'bufferView':v,'componentType':5126,
                  'count':len(data)//(components*4),'type':kind}
        if min_vals is not None:accessor['min']=min_vals
        if max_vals is not None:accessor['max']=max_vals
        result['accessors'].append(accessor)
        return len(result['accessors'])-1
    def material(name):
        if name in material_cache:return material_cache[name]
        mat={'name':name or 'Unassigned','doubleSided':True,'pbrMetallicRoughness':{
            'baseColorFactor':[1,1,1,1],'metallicFactor':0,'roughnessFactor':1},
             'extras':{'wosb_material':name,'material_matching':'exact filename, shader not recovered'}}
        source=textures.get(name) or texture_lookup.get(normalized(name))
        if source:
            content=_asset_bytes(source,asset_dir)
            if content:
                if name not in texture_cache:
                    view=add_view(content)
                    result['images'].append({'mimeType':'image/png','bufferView':view,'name':name})
                    result['textures'].append({'source':len(result['images'])-1})
                    texture_cache[name]=len(result['textures'])-1
                mat['pbrMetallicRoughness']['baseColorTexture']={'index':texture_cache[name]}
                if any(label in name.casefold() for label in ('alpha','sail','flag','decal')):
                    mat['alphaMode']='BLEND'
            else:missing.add(name)
        else:missing.add(name)
        result['materials'].append(mat)
        material_cache[name]=len(result['materials'])-1
        return material_cache[name]

    v=mesh['vertices'];tri=mesh['triangles'];uv=mesh.get('uvs',[]);triuv=mesh.get('triangle_uvs',[])
    covered=0
    for group in groups:
        if group.get('category') in ('helper','lod'):continue
        start=group['first_triangle']*3;end=start+group['triangle_count']*3
        if end>len(tri):raise ValueError('Mesh group exceeds triangle data')
        points=[];normals=[];coords=[]
        minmax_lo=[float('inf')]*3;minmax_hi=[float('-inf')]*3
        for i in range(start,end,3):
            vertices=[v[tri[j]] for j in (i,i+1,i+2)]
            n=_normal(*vertices)
            for j,pos in enumerate(vertices):
                points.extend(pos);normals.extend(n)
                for a in range(3):
                    minmax_lo[a]=min(minmax_lo[a],pos[a]);minmax_hi[a]=max(minmax_hi[a],pos[a])
                uv_index=triuv[i+j] if triuv else -1
                if uv_index>=0 and uv_index<len(uv):
                    # Match the HTML viewer's v -> 1-v orientation for PNG images.
                    coords.extend([float(uv[uv_index][0]),1.0-float(uv[uv_index][1])])
                else:coords.extend([0.0,0.0])
        if not points:continue
        src_name=group.get('material') or ''
        mat_name=chosen_material(src_name)
        pos_index=add_accessor(struct.pack('<%sf'%len(points),*points),3,'VEC3',
                               min_vals=minmax_lo,max_vals=minmax_hi)
        norm_index=add_accessor(struct.pack('<%sf'%len(normals),*normals),3,'VEC3')
        uv_index=add_accessor(struct.pack('<%sf'%len(coords),*coords),2,'VEC2')
        result['meshes'][0]['primitives'].append({'attributes':{'POSITION':pos_index,'NORMAL':norm_index,
                                            'TEXCOORD_0':uv_index},'material':material(mat_name),'mode':4,
                                            'extras':{'source_mesh':group.get('name'),'category':group.get('category'),
                                                      'source_material':src_name}})
        covered+=group['triangle_count']
    if not result['meshes'][0]['primitives']:raise ValueError('No visible mesh groups')
    while len(binary)%4:binary.append(0)
    result['buffers'][0]['byteLength']=len(binary)
    json_chunk=json.dumps(result,separators=(',',':'),ensure_ascii=False).encode('utf-8')
    json_chunk+=b' ' *((-len(json_chunk))%4)
    glb=b'glTF'+struct.pack('<II',2,12+8+len(json_chunk)+8+len(binary))
    glb+=struct.pack('<I4s',len(json_chunk),b'JSON')+json_chunk
    glb+=struct.pack('<I4s',len(binary),b'BIN\x00')+binary
    dest=Path(output);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(glb)
    return {'path':str(dest),'bytes':len(glb),'materials':len(result['materials']),
            'embedded_textures':len(result['images']),'missing_texture_materials':sorted(missing),
            'visual_triangles':covered,'sampled':mesh.get('sampling_status')=='sampled_display_mesh',
            'authoritative_hitboxes':False,'authoritative_damage':False}
