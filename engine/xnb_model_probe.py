"""Decode XNB containers and inspect ContentReaders + reliable ModelReader metadata.

Reports ModelReader metadata and attempts bounded, validated vertex/index
buffer discovery. Mesh export is provided by xnb_geometry.py for supported tag
layouts; unsupported custom readers are reported rather than guessed.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
import zipfile
from xnb_payload import unpack_xnb, XNBError

MAX_READERS=256
MAX_BONES=4096
MAX_NAMES=16000
MAX_NAME_BYTES=32768

class DecodeLimitError(ValueError): pass

class Cursor:
    def __init__(self,data):self.data=data;self.pos=0
    def read(self,n):
        if n<0 or self.pos+n>len(self.data):raise DecodeLimitError('Unexpected end of model metadata')
        o=self.data[self.pos:self.pos+n];self.pos+=n;return o
    def u8(self):return self.read(1)[0]
    def u32(self):return struct.unpack('<I',self.read(4))[0]
    def i32(self):return struct.unpack('<i',self.read(4))[0]
    def seven(self):
        result=0
        for shift in (0,7,14,21,28):
            v=self.u8();result|=(v&127)<<shift
            if v<128:return result
        raise DecodeLimitError('Invalid 7-bit integer')
    def string(self):
        length=self.seven()
        if length>MAX_NAME_BYTES:raise DecodeLimitError('Excessive content reader string')
        return self.read(length).decode('utf-8','replace')
    def floats(self,n):return list(struct.unpack('<'+'f'*n,self.read(4*n)))


def inspect_model_payload(data):
    c=Cursor(data)
    count=c.seven()
    if count<1 or count>MAX_READERS:raise DecodeLimitError(f'Invalid reader count: {count}')
    readers=[]
    for _ in range(count):
        readers.append({'type':c.string(),'version':c.i32()})
    shared=c.seven();root=c.seven()
    result={'content_readers':readers,'reader_count':count,'shared_resource_count':shared,
            'root_type_index':root,'payload_bytes':len(data),
            'model_metadata_status':'not_model','geometry_status':'not decoded'}
    if not (1<=root<=count) or 'ModelReader' not in readers[root-1]['type']:
        return result
    try:
        bones=c.u32()
        if not 1<=bones<=MAX_BONES:raise DecodeLimitError('Unsupported bone count')
        entries=[]
        for i in range(bones):
            typ=c.seven()
            if not (1<=typ<=count and 'StringReader' in readers[typ-1]['type']):
                raise DecodeLimitError('Unsupported bone-name reader')
            name=c.string()
            matrix=c.floats(16)
            if not all(math.isfinite(x) for x in matrix):raise DecodeLimitError('Invalid bone transform')
            entries.append({'index':i,'name':name,'local_matrix':matrix})
        for i in range(bones):
            raw=c.u8() if bones<255 else c.u32()
            parent=raw-1 if raw else None
            if parent is not None and not 0<=parent<bones:raise DecodeLimitError('Parent out of bounds')
            child_count=c.u32()
            if child_count>bones:raise DecodeLimitError('Too many child references')
            children=[]
            for _ in range(child_count):
                value=c.u8() if bones<255 else c.u32()
                if value and not 0<=value-1<bones:raise DecodeLimitError('Child out of bounds')
                if value:children.append(value-1)
            entries[i].update({'parent_index':parent,'child_indices':children})
        mesh_count=c.i32()
        if not 0<=mesh_count<=MAX_NAMES:raise DecodeLimitError('Invalid mesh count')
        result.update({'model_metadata_status':'bones_verified; mesh parts need custom readers',
                       'bone_count':bones,'bones':entries,'mesh_count':mesh_count})
        if mesh_count:
            typ=c.seven()
            if 1<=typ<=count and 'StringReader' in readers[typ-1]['type']:
                first_name=c.string()
                parent_raw=c.u8() if bones<255 else c.u32()
                sphere=c.floats(4)
                tag_reader=c.seven()
                result['first_mesh']={'name':first_name,'parent_bone_index':parent_raw-1 if parent_raw else None,
                                      'bounding_sphere':sphere,'tag_reader_index':tag_reader,
                                      'tag_type':readers[tag_reader-1]['type'] if 1<=tag_reader<=count else None}
        result['bytes_read_to_first_mesh_tag']=c.pos
    except (ValueError,struct.error) as exc:
        result['model_metadata_status']='partial model metadata: '+str(exc)
        result['bytes_read_to_failure']=c.pos
    return result


def inspect_asset(data,source_label='<bytes>'):
    payload,container=unpack_xnb(data,return_info=True)
    result=inspect_model_payload(payload)
    if result.get('model_metadata_status')!='not_model':
        try:
            from xnb_geometry import parse_geometry
            geometry=parse_geometry(payload)
            result.update({'geometry_status':'validated triangle index buffers; OBJ export supported',
                           'vertex_count':geometry['buffer']['vertices'],
                           'triangle_count':sum(x['triangle_count'] for x in geometry['parts']),
                           'mesh_part_count':len(geometry['parts']),
                           'vertex_stride':geometry['buffer']['stride']})
        except (ValueError,ImportError,IndexError,KeyError,struct.error) as exc:
            result['geometry_status']='not yet decodable: '+str(exc)[:300]
    return {'source':source_label,'sha256':hashlib.sha256(data).hexdigest(),
            'xnb':container,'model':result}


def inspect_sample_zip(filename):
    items=[]
    with zipfile.ZipFile(filename) as z:
        manifest={}
        try:manifest=json.loads(z.read('manifest.json'))
        except (KeyError,ValueError):pass
        paths={s.get('sample'):s.get('relative_path') for s in manifest.get('samples',[]) if isinstance(s,dict)}
        for info in z.infolist():
            if not info.filename.lower().endswith('.xnb') or info.is_dir():continue
            if len(items)>=24:raise DecodeLimitError('Too many samples in ZIP')
            if info.file_size>16*1024*1024:raise DecodeLimitError('Oversized XNB sample')
            raw=z.read(info)
            try:items.append(inspect_asset(raw,paths.get(info.filename,info.filename)))
            except (ValueError,ImportError,OSError) as exc:
                items.append({'source':paths.get(info.filename,info.filename),'error':str(exc)})
    return {'tool':'WoSB XNB model probe','status':'static evidence; no mesh geometry or damage zones verified',
            'samples':items}


def main():
    parser=argparse.ArgumentParser(description='Inspect WoSB XNB model metadata, no game code execution')
    parser.add_argument('source',help='.xnb file or sample ZIP');parser.add_argument('--output',help='Save JSON report')
    args=parser.parse_args()
    source=Path(args.source)
    if source.suffix.lower()=='.zip':result=inspect_sample_zip(source)
    else:result={'tool':'WoSB XNB model probe','samples':[inspect_asset(source.read_bytes(),str(source))]}
    doc=json.dumps(result,indent=2,ensure_ascii=False)
    if args.output:Path(args.output).write_text(doc,encoding='utf-8')
    print(doc[:6000]+('\n... truncated display; full report written to disk' if len(doc)>6000 else ''))
if __name__=='__main__':main()
