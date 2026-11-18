"""Bounded, read-only XNB/LZX frame metadata inspector.

This parser intentionally does NOT claim to decompress XNB models. It extracts
compression and frame structure needed to debug actual game assets safely.
"""
from __future__ import annotations
import struct

MAX_DECLARED = 512 * 1024 * 1024
MAX_FRAMES = 32768


def inspect_xnb_bytes(data: bytes) -> dict:
    if not isinstance(data,bytes):raise TypeError('Expected bytes')
    prefix=4 if data.startswith(b'WOSB') else 0
    if len(data)<prefix+10 or data[prefix:prefix+3]!=b'XNB':
        return {'recognized':False,'wrapper_bytes':prefix,'status':'not_xnb'}
    b=data[prefix:]
    flags=b[5]
    stored_length=struct.unpack_from('<I',b,6)[0]
    out={'recognized':True,'wrapper_bytes':prefix,'platform':chr(b[3]),'version':b[4],
         'flags':flags,'file_bytes':len(b),'header_declared_bytes':stored_length,
         'compressed_lzx':bool(flags&0x80),'compressed_lz4':bool(flags&0x40),
         'status':'header_only'}
    if stored_length!=len(b):out['warning']='Declared XNB length differs from available bytes'
    if not (flags&0x80):return out
    if len(b)<14:return {**out,'status':'truncated_lzx_length'}
    expected=struct.unpack_from('<I',b,10)[0]
    out['unpacked_bytes']=expected
    if expected>MAX_DECLARED:return {**out,'status':'unpacked_size_limit'}
    pos=14;total=0;frames=0;sample=[];error=None
    while pos<len(b) and total<expected and frames<MAX_FRAMES:
        if b[pos]==0xff:
            if pos+5>len(b):error='incomplete_extended_frame_header';break
            uncompressed=int.from_bytes(b[pos+1:pos+3],'big')
            compressed=int.from_bytes(b[pos+3:pos+5],'big')
            pos+=5;extended=True
        else:
            if pos+2>len(b):error='incomplete_frame_header';break
            uncompressed=32768
            compressed=int.from_bytes(b[pos:pos+2],'big')
            pos+=2;extended=False
        if not compressed or not uncompressed:
            error='zero_length_frame';break
        if pos+compressed>len(b):
            error='frame_data_truncated';break
        if len(sample)<12:sample.append({'frame':frames+1,'compressed_bytes':compressed,
                                           'expected_uncompressed_bytes':uncompressed,'extended':extended})
        frames+=1;total+=uncompressed;pos+=compressed
    if error is None and frames>=MAX_FRAMES:error='frame_limit_exceeded'
    if error is None and total!=expected:error='frame_total_differs_from_unpacked_size'
    if error is None and pos!=len(b):
        tail=b[pos:]
        if len(tail)>7 or any(tail):error='unexpected_trailing_bytes'
    out.update({'lzx_frames':frames,'lzx_frame_examples':sample,
                'frame_unpacked_bytes_total':total,'frame_consumed_bytes':pos,
                'zero_padding_bytes':len(b)-pos if error is None else 0,
                'status':error or 'lzx_frame_layout_valid_unverified_decompression'})
    return out
