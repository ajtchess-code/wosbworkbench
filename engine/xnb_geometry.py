"""Bounded, read-only XNA ModelReader geometry recovery for WoSB.

Unlike a filename match, this parser proves vertex/index contents and all
referenced part offsets before exporting.  WoSB's UWModelMeshPartTag schema was
reverse-mapped from the user-supplied Vasa XNB; unknown readers fail closed.
Original UV coordinates are now exported where valid; actual material/texture mappings, animations, hitboxes, and damage multipliers are NOT inferred.
"""
from __future__ import annotations
from v3_progress import replace_with_retry
from dataclasses import dataclass
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct
import tempfile
from xnb_payload import unpack_xnb, XNBError
from xnb_model_probe import Cursor, DecodeLimitError

MAX_MESHES=2048
MAX_PARTS=20000
MAX_TOTAL_VERTICES=3_000_000
MAX_INDICES=10_000_000
MAX_OUTPUT_BYTES=500*1024*1024

class MeshDecodeError(ValueError): pass


def _need(value, condition, msg):
    if not condition: raise MeshDecodeError(msg)
    return value


def _type_index(readers, name):
    found=[i for i,r in enumerate(readers,1) if name in r]
    if len(found)!=1:raise MeshDecodeError(f'Expected one {name} reader; found {len(found)}')
    return found[0]


def _clean_name(s):
    return re.sub(r'[^a-zA-Z0-9_.-]+','_',s or 'unnamed')[:100] or 'unnamed'


def _matmul(a,b):
    # XNA Matrix uses row-vector multiplication: point * local * parent.
    return [sum(a[r*4+k]*b[k*4+c] for k in range(4)) for r in range(4) for c in range(4)]


def _transform(m,v):
    x,y,z=v
    return (x*m[0]+y*m[4]+z*m[8]+m[12],
            x*m[1]+y*m[5]+z*m[9]+m[13],
            x*m[2]+y*m[6]+z*m[10]+m[14])


def parse_model_header(data):
    """Parse all bones, 3D mesh parts and shared references, before binary buffers.

    The custom WoSB tag observed in Vasa has a nullable SegmentTextureInfoTag,
    followed by ten float32 numbers. Unsupported layouts are reported explicitly.
    """
    c=Cursor(data)
    count=c.seven()
    _need(count,1<=count<=256,'Invalid content reader count')
    readers=[]
    for _ in range(count):
        type_name=c.string();_version=c.i32()
        readers.append(type_name)
    shared=c.seven();root=c.seven()
    _need(root,1<=root<=count and 'ModelReader' in readers[root-1], 'XNB root content is not an XNA ModelReader')
    _need(shared,2<=shared<=20000, 'Invalid model shared-resource count')
    str_reader=_type_index(readers,'StringReader')
    vertex_reader=_type_index(readers,'VertexBufferReader')
    index_reader=_type_index(readers,'IndexBufferReader')
    custom_reader=_type_index(readers,'UWModelMeshPartTag')
    segment_reader=_type_index(readers,'SegmentTextureInfoTag')
    n_bones=c.u32();_need(n_bones,1<=n_bones<=4096,'Invalid bone count')
    bones=[]
    for idx in range(n_bones):
        typ=c.seven()
        _need(typ,typ==str_reader,'Unsupported bone name reader')
        name=c.string();mat=c.floats(16)
        if not all(math.isfinite(x) for x in mat):raise MeshDecodeError('Non-finite bone transform')
        bones.append({'index':idx,'name':name,'matrix':mat})
    width=1 if n_bones<255 else 4
    def bone_ref():
        raw=c.u8() if width==1 else c.u32()
        if raw and raw>n_bones:raise MeshDecodeError('Bone reference outside table')
        return raw-1 if raw else None
    for bone in bones:
        bone['parent']=bone_ref()
        children=c.u32();_need(children,children<=n_bones,'Excessive bone children')
        bone['children']=[bone_ref() for _ in range(children)]
    mesh_count=c.i32();_need(mesh_count,0<=mesh_count<=MAX_MESHES,'Excessive model mesh count')
    meshes=[];parts=[]
    for mesh_id in range(mesh_count):
        if c.seven()!=str_reader:raise MeshDecodeError('Unsupported mesh-name encoding')
        name=c.string();bone=bone_ref();sphere=c.floats(4);tag_type=c.seven()
        if tag_type:
            raise MeshDecodeError('Unsupported mesh-level tag layout: '+str(tag_type))
        num_parts=c.i32();_need(num_parts,0<=num_parts<=MAX_PARTS-len(parts),'Too many mesh parts')
        mesh={'name':name,'parent_bone':bone,'bounding_sphere':sphere,'parts':num_parts}
        meshes.append(mesh)
        for part_id in range(num_parts):
            offset=c.i32();vertices=c.i32();start=c.i32();primitives=c.i32()
            if not (0<=offset<=MAX_TOTAL_VERTICES and 0<vertices<=MAX_TOTAL_VERTICES and
                    0<=start<=MAX_INDICES and 0<primitives<=MAX_INDICES//3):
                raise MeshDecodeError('Implausible mesh part range')
            tag=c.seven();segment='';texture='';extra=None
            if tag==custom_reader:
                nested=c.seven()
                if nested==segment_reader:
                    if c.seven()!=str_reader:raise MeshDecodeError('Unsupported segment-name reader')
                    segment=c.string()
                    if c.seven()!=str_reader:raise MeshDecodeError('Unsupported texture-name reader')
                    texture=c.string()
                elif nested!=0:
                    raise MeshDecodeError('Unknown custom mesh tag child '+str(nested))
                extra=c.floats(10)
                if not all(math.isfinite(x) for x in extra):raise MeshDecodeError('Nonfinite mesh tag values')
            elif tag:
                raise MeshDecodeError('Unknown mesh tag reader '+str(tag))
            vref=c.seven();iref=c.seven();eref=c.seven()
            # XNA shared-resource references are 1-based, with zero reserved
            # for an absent optional resource. Frames may have no effect object.
            if vref!=1 or iref!=2 or not (eref==0 or 3<=eref<=shared):
                raise MeshDecodeError(f'Unsupported shared-resource layout ({vref}, {iref}, {eref})')
            parts.append({'mesh':name,'mesh_index':mesh_id,'part':part_id,'vertex_offset':offset,
                          'vertex_count':vertices,'start_index':start,'triangle_count':primitives,
                          'texture_label':texture,'segment_label':segment,'effects_ref':eref,
                          'parent_bone':bone,'tag_values':extra})
    if not parts:raise MeshDecodeError('Model has no exportable mesh parts')
    max_vertex=max(x['vertex_offset']+x['vertex_count'] for x in parts)
    max_index=max(x['start_index']+3*x['triangle_count'] for x in parts)
    if max_vertex>MAX_TOTAL_VERTICES or max_index>MAX_INDICES:
        raise MeshDecodeError('Model exceeds configured geometry size')
    return {'readers':readers,'bones':bones,'meshes':meshes,'parts':parts,'shared_count':shared,
            'vertex_reader':vertex_reader,'index_reader':index_reader,'mesh_end_offset':c.pos,
            'min_vertices':max_vertex,'min_indices':max_index}


def _locate_buffers(data, metadata):
    """Locate the shared VB/IB pair with exact reader and declaration validation.

    Supports vertex buffers with unused trailing vertices; does not need to
    deserialize the game's custom root tags or effect material objects.
    """
    minimum=metadata['min_vertices'];start=metadata['mesh_end_offset']
    scan_end=min(len(data)-10,start+128*1024*1024)
    marker=bytes([metadata['vertex_reader']]);position=start;hits=[]
    while True:
        idx=data.find(marker,position,scan_end)
        if idx<0:break
        position=idx+1
        if idx+13>len(data):continue
        stride,elements=struct.unpack_from('<II',data,idx+1)
        if not 12<=stride<=256 or not 1<=elements<=16:continue
        countpos=idx+9+16*elements
        if countpos+4>=len(data):continue
        declaration=[];valid=True
        for e in range(elements):
            off,fmt,usage,usage_index=struct.unpack_from('<IIII',data,idx+9+e*16)
            if off>=stride or fmt>32 or usage>32 or usage_index>64:
                valid=False;break
            declaration.append({'offset':off,'format':fmt,'usage':usage,'usage_index':usage_index})
        if not valid or not any(x['usage']==0 and x['format']==2 and x['offset']+12<=stride for x in declaration):
            continue
        vertexcount=struct.unpack_from('<I',data,countpos)[0]
        if vertexcount<minimum or vertexcount>MAX_TOTAL_VERTICES:continue
        vb_start=countpos+4;vb_end=vb_start+vertexcount*stride
        if vb_end+6>len(data) or data[vb_end]!=metadata['index_reader']:continue
        use16=data[vb_end+1]
        if use16 not in (0,1):continue
        size=struct.unpack_from('<I',data,vb_end+2)[0]
        word=2 if use16 else 4
        if size%word or size<metadata['min_indices']*word or vb_end+6+size>len(data):continue
        idx_count=size//word
        if idx_count>MAX_INDICES:continue
        hits.append({'vertex_buffer_offset':vb_start,'index_buffer_offset':vb_end+6,
                     'vertices':vertexcount,'stride':stride,'declaration':declaration,
                     'indices':idx_count,'index_size':word,'index_end_offset':vb_end+6+size,
                     'root_tag_bytes':idx-start})
        if len(hits)>1:break
    if len(hits)!=1:
        raise MeshDecodeError(f'Could not uniquely validate shared vertex/index buffers ({len(hits)} candidates)')
    return hits[0]


# XNA 4.0 vertex declaration semantic names; detection is not validation that
# the shader actually consumes each declared channel.
_VERTEX_FORMATS={0:('Single',4),1:('Vector2',8),2:('Vector3',12),3:('Vector4',16),
                 4:('Color',4),5:('Byte4',4),6:('Short2',4),7:('Short4',8),
                 8:('NormalizedShort2',4),9:('NormalizedShort4',8),
                 10:('HalfVector2',4),11:('HalfVector4',8)}
_VERTEX_USAGES={0:'Position',1:'Color',2:'TextureCoordinate',3:'Normal',
                4:'Binormal',5:'Tangent',6:'BlendIndices',7:'BlendWeight',
                8:'Depth',9:'Fog',10:'PointSize',11:'Sample',12:'TessellateFactor'}


def describe_vertex_declaration(buffer):
    stride=buffer['stride'];elements=[];errors=[]
    for row in buffer.get('declaration',[]):
        fmt,size=_VERTEX_FORMATS.get(row['format'],('Unknown',None))
        label=_VERTEX_USAGES.get(row['usage'],'Unknown')
        end=row['offset']+size if size is not None else None
        if end is None:errors.append(f"Unrecognized format {row['format']}")
        elif end>stride:errors.append(f"{label}#{row['usage_index']} overflows stride")
        elements.append({'semantic':label,'channel':row['usage_index'],'format':fmt,
                         'offset':row['offset'],'bytes':size,'readable':end is not None and end<=stride})
    return {'vertex_stride':stride,'elements':elements,'warnings':errors,
            'shader_input_match_verified':False,
            'note':'Vertex declaration recovered from model buffer; effects and shader input matches remain unverified'}


def parse_geometry(data):
    meta=parse_model_header(data);buffers=_locate_buffers(data,meta)
    pos_elem=next(x for x in buffers['declaration'] if x['usage']==0 and x['format']==2)
    for part in meta['parts']:
        ix=part['start_index'];num=part['triangle_count']*3
        begin=buffers['index_buffer_offset']+ix*buffers['index_size']
        fmt='<H' if buffers['index_size']==2 else '<I'
        # Structural check: all indices must be local to the part's vertex span.
        for at in range(begin,begin+num*buffers['index_size'],buffers['index_size']):
            val=struct.unpack_from(fmt,data,at)[0]
            if val>=part['vertex_count']:
                raise MeshDecodeError(f'Mesh {part["mesh"]} has out-of-range index {val} / {part["vertex_count"]}')
    meta['buffer']=buffers;meta['position_offset']=pos_elem['offset']
    meta['vertex_declaration_report']=describe_vertex_declaration(buffers)
    # XNA TextureCoordinate(usage=2): Vector2(format=1) or HalfVector2(format=10).
    tex=next((e for e in buffers['declaration'] if e['usage']==2 and e['format'] in (1,10)),None)
    meta['texcoord_element']=tex
    return meta


def _absolute_bones(bones):
    cache={};seen=set()
    def get(idx):
        if idx is None:return [1.,0,0,0, 0,1.,0,0, 0,0,1.,0, 0,0,0,1.]
        if idx in cache:return cache[idx]
        if idx in seen:raise MeshDecodeError('Cyclic bone hierarchy')
        seen.add(idx);parent=bones[idx]['parent']
        m=_matmul(bones[idx]['matrix'],get(parent));seen.remove(idx);cache[idx]=m
        return m
    for i in range(len(bones)):get(i)
    return cache


def export_obj(data, output_path, *, include_meshes=None):
    """Writes actual decoded triangles, not approximations. Returns provenance report.

    Only game-provided geometry is exported. No hitboxes, inferred damage
    vulnerabilities, or guessed materials are introduced.
    """
    meta=parse_geometry(data);buffers=meta['buffer'];bounds=[[math.inf]*3,[-math.inf]*3]
    transforms=_absolute_bones(meta['bones']);target=Path(output_path);target.parent.mkdir(parents=True,exist_ok=True)
    include={x.casefold() for x in include_meshes} if include_meshes else None
    total_v=0;total_t=0;stats=[]
    with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=target.parent,delete=False,suffix='.obj.tmp') as f:
        tmp=Path(f.name)
        try:
            f.write('# WoSB XNB geometry recovery; true decoded vertex/index buffers.\n')
            f.write('# UV coordinates recovered when the XNB vertex declaration supports it.\n')
            f.write('# Material/texture ASSET LINKAGE and gameplay vulnerabilities NOT established.\n')
            for part in meta['parts']:
                mesh=part['mesh']
                if include is not None and mesh.casefold() not in include:continue
                first=total_v+1
                if (total_v+part['vertex_count']>MAX_TOTAL_VERTICES or
                    total_t+part['triangle_count']>MAX_INDICES//3):raise MeshDecodeError('Output too large')
                f.write('\no '+_clean_name(mesh)+'_part'+str(part['part'])+'\n')
                f.write('# source texture label: '+_clean_name(part['texture_label'])+'\n')
                f.write('usemtl '+_clean_name(part['segment_label'] or part['texture_label'] or 'unassigned')+'\n')
                mat=transforms.get(part['parent_bone'], _absolute_bones([]).get(None))
                if mat is None:mat=_absolute_bones([]).get(None) or [1.,0,0,0,0,1.,0,0,0,0,1.,0,0,0,0,1.]
                voff=buffers['vertex_buffer_offset']+part['vertex_offset']*buffers['stride']+meta['position_offset']
                for index in range(part['vertex_count']):
                    v=struct.unpack_from('<fff',data,voff+index*buffers['stride'])
                    if not all(math.isfinite(x) for x in v):raise MeshDecodeError('Nonfinite vertex coordinate')
                    x,y,z=_transform(mat,v)
                    if not all(math.isfinite(q) and abs(q)<1e7 for q in (x,y,z)):
                        raise MeshDecodeError('Invalid transformed coordinate')
                    for j,val in enumerate((x,y,z)):
                        bounds[0][j]=min(bounds[0][j],val);bounds[1][j]=max(bounds[1][j],val)
                    f.write(f'v {x:.7g} {y:.7g} {z:.7g}\n')
                uv=meta.get('texcoord_element')
                if uv:
                    uv_offset=buffers['vertex_buffer_offset']+part['vertex_offset']*buffers['stride']+uv['offset']
                    uv_fmt='<ff' if uv['format']==1 else '<ee'
                    for index in range(part['vertex_count']):
                        tu,tv=struct.unpack_from(uv_fmt,data,uv_offset+index*buffers['stride'])
                        if not (math.isfinite(tu) and math.isfinite(tv) and abs(tu)<100000 and abs(tv)<100000):
                            raise MeshDecodeError('Invalid recovered texture coordinates')
                        f.write(f'vt {tu:.7g} {tv:.7g}\n')
                base=buffers['index_buffer_offset']+part['start_index']*buffers['index_size']
                for j in range(part['triangle_count']):
                    if buffers['index_size']==2:a,b,c=struct.unpack_from('<HHH',data,base+j*6)
                    else:a,b,c=struct.unpack_from('<III',data,base+j*12)
                    if uv:
                        f.write(f'f {first+a}/{first+a} {first+b}/{first+b} {first+c}/{first+c}\n')
                    else:f.write(f'f {first+a} {first+b} {first+c}\n')
                total_v+=part['vertex_count'];total_t+=part['triangle_count']
                stats.append({'mesh':mesh,'part':part['part'],'vertices':part['vertex_count'],
                              'triangles':part['triangle_count'],'texture_label':part['texture_label'],'segment_label':part['segment_label'],'export_material':part['segment_label'] or part['texture_label'] or 'unassigned'})
            f.flush()
            if f.tell()>MAX_OUTPUT_BYTES:raise MeshDecodeError('Output exceeds configured 500 MB limit')
        except Exception:
            f.close();tmp.unlink(missing_ok=True);raise
    if not total_t:
        tmp.unlink(missing_ok=True);raise MeshDecodeError('No geometry was selected')
    replace_with_retry(tmp,target)
    return {'geometry_status':'triangles verified from XNB vertex/index buffers; visual alignment pending',
            'output':str(target),'vertices':total_v,'triangles':total_t,'part_count':len(stats),
            'mesh_count':len(meta['meshes']),'bone_count':len(meta['bones']),
            'uv_exported':bool(meta.get('texcoord_element')),
            'texture_mapping_status':'Tagged SegmentTextureInfoTag segment names preserved as OBJ usemtl names; real image files must be matched separately',
            'vertex_stride':buffers['stride'],'vertex_declaration':meta['vertex_declaration_report'],'bounds':bounds,'parts':stats,
            'damage_overlay_status':'not recovered; no weak-zone coloring',
            'mesh_source':'XNA ModelReader + validated shared resources'}


def convert_xnb(source, output_obj, *, report_path=None, include_meshes=None):
    raw=Path(source).read_bytes();payload,xnb=unpack_xnb(raw,return_info=True)
    report=export_obj(payload,output_obj,include_meshes=include_meshes)
    report.update({'source':str(source),'sha256':hashlib.sha256(raw).hexdigest(),'xnb':xnb})
    if report_path:
        report_path=Path(report_path);report_path.parent.mkdir(parents=True,exist_ok=True)
        report_path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report


def main():
    p=argparse.ArgumentParser(description='Read-only WoSB XNA model geometry exporter')
    p.add_argument('source',help='Original XNB model file')
    p.add_argument('--output',required=True,help='OBJ file path')
    p.add_argument('--report',help='JSON provenance report')
    args=p.parse_args()
    print(json.dumps(convert_xnb(args.source,args.output,report_path=args.report),indent=2)[:10000])

if __name__=='__main__':main()
