"""Read-only, bounded WoSB/XNA XNB payload extraction.

XNB LZX frames have the same 32 KiB block semantics as a cabinet LZX folder.
This module wraps those blocks in a standard CAB stream, preserving the native
LZX dictionary between frames. It never executes client assemblies.

Requires native system LZX support: Windows expand.exe (bundled with Windows),
libarchive on Unix (or an installed Windows libarchive DLL), or optional 7z.
"""
from __future__ import annotations
import ctypes
import ctypes.util
import io
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile

MAX_OUTPUT = 512 * 1024 * 1024
MAX_FRAMES = 32768

class XNBError(ValueError):
    pass


def parse_header(data: bytes):
    if len(data) > MAX_OUTPUT: raise XNBError('Input exceeds 512 MiB safety limit')
    wrap=4 if data.startswith(b'WOSB') else 0
    b=data[wrap:]
    if len(b) < 10 or b[:3]!=b'XNB': raise XNBError('Not a complete XNB header')
    declared=struct.unpack_from('<I',b,6)[0]
    if declared!=len(b): raise XNBError(f'Length mismatch: header={declared}, actual={len(b)}')
    flags=b[5]
    if flags & 0xc0==0xc0: raise XNBError('Conflicting compression flags')
    if flags & 0xc0 and len(b)<14: raise XNBError('Missing decompressed-length field')
    return b,{'wrapper_bytes':wrap,'platform':chr(b[3]),'version':b[4],
              'flags':flags,'stored_bytes':len(b),
              'compression':'LZX' if flags&0x80 else 'LZ4' if flags&0x40 else 'none',
              'decompressed_bytes':struct.unpack_from('<I',b,10)[0] if flags&0xc0 else len(b)-10}


def lzx_frames(b):
    expected=struct.unpack_from('<I',b,10)[0]
    if expected>MAX_OUTPUT: raise XNBError('Declared decompressed output too large')
    pos=14;total=0;frames=[]
    while total<expected and len(frames)<MAX_FRAMES:
        if pos>=len(b): raise XNBError('Truncated LZX frame list')
        if b[pos]==255:
            if pos+5>len(b): raise XNBError('Truncated extended LZX frame')
            out_size=int.from_bytes(b[pos+1:pos+3],'big')
            compressed=int.from_bytes(b[pos+3:pos+5],'big');pos+=5
        else:
            if pos+2>len(b): raise XNBError('Truncated LZX frame')
            out_size=32768
            compressed=int.from_bytes(b[pos:pos+2],'big');pos+=2
        if out_size<1 or compressed<1 or pos+compressed>len(b):
            raise XNBError('Invalid or truncated LZX data block')
        if total+out_size>expected:raise XNBError('LZX frame output exceeds declared size')
        frames.append((b[pos:pos+compressed],out_size))
        total+=out_size;pos+=compressed
    if total!=expected: raise XNBError('LZX frame count or output size mismatch')
    trailing=b[pos:]
    if len(trailing)>7 or any(trailing):
        raise XNBError(f'Unexpected nonzero or excessive trailing frame data ({len(trailing)} bytes)')
    return frames,len(trailing)


def make_cab(b):
    """CAB LZX 64-KiB window, one file. Frames remain ordered and stateful."""
    frames,_=lzx_frames(b)
    expected=struct.unpack_from('<I',b,10)[0]
    name=b'data\0';offset=36+8+16+len(name)
    blocks=b''.join(struct.pack('<IHH',0,len(raw),size)+raw for raw,size in frames)
    hdr=struct.pack('<4sIIIII BB HHHHH',b'MSCF',0,offset+len(blocks),0,44,0,3,1,1,1,0,0,0)
    return hdr+struct.pack('<IHH',offset,len(frames),0x1003)+struct.pack('<IIHHHH',expected,0,0,0,0,0)+name+blocks


def _libarchive_decode(cab,expected):
    library=ctypes.util.find_library('archive')
    if not library:raise XNBError('No system libarchive available')
    lib=ctypes.CDLL(library)
    lib.archive_read_new.restype=ctypes.c_void_p
    funcs={'archive_read_support_format_cab':[ctypes.c_void_p],
           'archive_read_open_memory':[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t],
           'archive_read_next_header':[ctypes.c_void_p,ctypes.POINTER(ctypes.c_void_p)],
           'archive_read_data':[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t],
           'archive_read_free':[ctypes.c_void_p]}
    for name,args in funcs.items():getattr(lib,name).argtypes=args
    lib.archive_read_data.restype=ctypes.c_ssize_t
    lib.archive_error_string.argtypes=[ctypes.c_void_p];lib.archive_error_string.restype=ctypes.c_char_p
    archive=lib.archive_read_new()
    if not archive:raise XNBError('Could not allocate libarchive reader')
    try:
        lib.archive_read_support_format_cab(archive)
        source=ctypes.create_string_buffer(cab)
        if lib.archive_read_open_memory(archive,source,len(cab))!=0:raise XNBError('Cannot open CAB in libarchive')
        entry=ctypes.c_void_p()
        if lib.archive_read_next_header(archive,ctypes.byref(entry))!=0:
            raise XNBError('CAB header could not be read')
        result=io.BytesIO();buf=ctypes.create_string_buffer(65536)
        while True:
            n=lib.archive_read_data(archive,buf,len(buf))
            if n<0:
                err=lib.archive_error_string(archive)
                raise XNBError('libarchive LZX error: '+(err.decode(errors='replace') if err else 'unknown'))
            if not n:break
            if result.tell()+n>expected:raise XNBError('Decompressed data exceeded expected length')
            result.write(buf.raw[:n])
        return result.getvalue()
    finally:lib.archive_read_free(archive)


def _windows_decode(cab, expected=None):
    """Use Windows CAB tools and validate the extracted single-file payload."""
    with tempfile.TemporaryDirectory(prefix='wosb-lzx-') as td:
        path = Path(td)
        source = path / 'source.cab'
        source.write_bytes(cab)
        folder = path / 'out'
        folder.mkdir()
        candidates = []
        expand = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'expand.exe'
        if expand.exists():
            candidates.append([str(expand), '-F:*', str(source), str(folder)])
        exe = shutil.which('7z') or shutil.which('7za')
        if exe:
            candidates.append([exe, 'x', '-y', f'-o{folder}', str(source)])
        errors = []
        if not candidates:
            raise XNBError('No Windows CAB extractor available (expand.exe or 7z)')
        for cmd in candidates:
            for old in folder.rglob('*'):
                if old.is_file(): old.unlink()
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True,
                                      errors='replace', timeout=120,
                                      creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                extracted = [f for f in folder.rglob('*') if f.is_file()]
                matching = [f for f in extracted if expected is None or f.stat().st_size == expected]
                if proc.returncode == 0 and len(extracted) == 1 and len(matching) == 1:
                    result = matching[0].read_bytes()
                    if expected is None or len(result) == expected:
                        return result
                files = ', '.join(f'{f.relative_to(folder)} ({f.stat().st_size} bytes)' for f in extracted)
                output = ((proc.stderr or '') + '\n' + (proc.stdout or ''))[-600:]
                errors.append(f'{Path(cmd[0]).name}: exit={proc.returncode}; files={files or "none"}; '
                              f'expected={expected}; output={output}')
            except (OSError, subprocess.TimeoutExpired) as exc:
                errors.append(f'{Path(cmd[0]).name}: {exc}')
        raise XNBError('Windows CAB decoder failed: ' + ' | '.join(errors))


def unpack_xnb(data,return_info=False):
    b,info=parse_header(data)
    if info['decompressed_bytes']>MAX_OUTPUT:raise XNBError('Exceeds configured decompression size')
    if info['compression']=='none':payload=b[10:];info['decoder']='none'
    elif info['compression']=='LZ4':
        try:import lz4.block
        except ImportError as exc:raise XNBError('LZ4 needs Python lz4 package') from exc
        payload=lz4.block.decompress(b[14:],uncompressed_size=info['decompressed_bytes'])
        info['decoder']='lz4.block'
    else:
        frames,padding=lzx_frames(b);info['frames']=len(frames);info['zero_padding_bytes']=padding
        cab=make_cab(b)
        if os.name=='nt':
            try:payload=_windows_decode(cab,info['decompressed_bytes']);info['decoder']='Windows CAB/expand'
            except XNBError as windows_error:
                try:payload=_libarchive_decode(cab,info['decompressed_bytes']);info['decoder']='libarchive fallback'
                except XNBError as archive_error:raise XNBError(f'{windows_error}; {archive_error}') from archive_error
        else:payload=_libarchive_decode(cab,info['decompressed_bytes']);info['decoder']='libarchive'
    if len(payload)!=info['decompressed_bytes']:
        raise XNBError(f'Decompressed length mismatch: {len(payload)} != {info["decompressed_bytes"]}')
    return (payload,info) if return_info else payload
