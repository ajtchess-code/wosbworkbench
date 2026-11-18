"""XNB texture decoder, including WOSB's four-byte prefix and LZX frames."""
import io,struct,subprocess,tempfile,os
from pathlib import Path
from PIL import Image

from xnb_payload import make_cab, unpack_xnb, XNBError

class Reader:
    def __init__(self,b):self.b=b;self.p=0
    def read(self,n):
        v=self.b[self.p:self.p+n];self.p+=n
        if len(v)!=n:raise ValueError('Truncated XNB data')
        return v
    def i32(self):return struct.unpack('<i',self.read(4))[0]
    def seven(self):
        v=0
        for shift in range(0,35,7):
            c=self.read(1)[0];v|=(c&127)<<shift
            if c<128:return v
        raise ValueError('Invalid 7-bit integer')
    def string(self):return self.read(self.seven()).decode('utf-8')

def texture(b):
    r=Reader(unpack_xnb(b));readers=[]
    for _ in range(r.seven()):readers.append(r.string());r.i32()
    shared=r.seven();idx=r.seven()
    if idx<1 or idx>len(readers) or 'Texture2DReader' not in readers[idx-1]:raise ValueError('XNB is not a Texture2D asset')
    fmt,w,h,mips=r.i32(),r.i32(),r.i32(),r.i32()
    if not 0<w<=32768 or not 0<h<=32768 or w*h>100000000:raise ValueError('Invalid texture dimensions')
    pixels=r.read(r.i32())
    if fmt==0:im=Image.frombytes('RGBA',(w,h),pixels)
    elif fmt in (4,5,6):
        if fmt==5:im=decode_dxt3(pixels,w,h)
        else:
            try:
                import texture2ddecoder
            except ImportError as exc:
                raise ValueError('BC1/BC3 textures require texture2ddecoder; install engine/requirements.txt') from exc
            decode=texture2ddecoder.decode_bc1 if fmt==4 else texture2ddecoder.decode_bc3
            im=Image.frombytes('RGBA',(w,h),decode(pixels,w,h),'raw','BGRA')
    elif fmt==1:im=Image.frombytes('RGB',(w,h),pixels,'raw','BGR;16').convert('RGBA')
    elif fmt==12:
        im=Image.new('RGBA',(w,h),(255,255,255,255));im.putalpha(Image.frombytes('L',(w,h),pixels))
    else:raise ValueError('Unsupported XNA surface format '+str(fmt))
    # XNA stores premultiplied alpha. Restore straight alpha for PNG display.
    if im.getextrema()[3][0]<255:
        raw=bytearray(im.tobytes())
        for i in range(0,len(raw),4):
            a=raw[i+3]
            if 0<a<255:
                raw[i]=min(255,(raw[i]*255+a//2)//a)
                raw[i+1]=min(255,(raw[i+1]*255+a//2)//a)
                raw[i+2]=min(255,(raw[i+2]*255+a//2)//a)
        im=Image.frombytes('RGBA',(w,h),bytes(raw))
    return im,{'Width':w,'Height':h,'MipLevels':mips,'SurfaceFormat':fmt}


def decode_dxt3(data,w,h):
    out=bytearray(w*h*4);pos=0
    for by in range(0,h,4):
        for bx in range(0,w,4):
            block=data[pos:pos+16];pos+=16
            alpha=int.from_bytes(block[:8],'little');c0,c1,bits=struct.unpack('<HHI',block[8:])
            def rgb(c):return (((c>>11)&31)*255//31,((c>>5)&63)*255//63,(c&31)*255//31)
            a,b=rgb(c0),rgb(c1);cols=[a,b,tuple((2*x+y)//3 for x,y in zip(a,b)),tuple((x+2*y)//3 for x,y in zip(a,b))]
            for i in range(16):
                x=bx+i%4;y=by+i//4
                if x<w and y<h:
                    off=(y*w+x)*4;out[off:off+4]=bytes((*cols[(bits>>(2*i))&3],((alpha>>(4*i))&15)*17))
    return Image.frombytes('RGBA',(w,h),bytes(out))


def _seven_encode(value):
    """Encode an XNA 7-bit non-negative integer for a bounded synthetic atlas."""
    if value < 0 or value > 0x0fffffff:
        raise ValueError('Invalid XNA reader integer')
    output=bytearray()
    while value >= 128:
        output.append((value & 127) | 128)
        value >>= 7
    output.append(value)
    return bytes(output)


def spritefont_atlas(original_xnb):
    """Recover the embedded SpriteFont texture atlas, not glyph positions.

    An XNA SpriteFont has a SpriteFontReader root and a nested Texture2DReader
    object. Merely seeing Texture2DReader in the reader table is insufficient.
    This function exports the image with its source reader provenance; it does
    not guess glyph kerning, baseline or string layout.
    """
    payload=unpack_xnb(original_xnb)
    r=Reader(payload)
    count=r.seven()
    if not 1 <= count <= 128:
        raise ValueError('Invalid SpriteFont content reader count')
    readers=[]
    for _ in range(count):
        readers.append(r.string());r.i32()
    _shared=r.seven();root=r.seven()
    if root < 1 or root > count or 'SpriteFontReader' not in readers[root-1]:
        raise ValueError('XNB is not a SpriteFont asset')
    ref=r.seven()
    if ref < 1 or ref > count or 'Texture2DReader' not in readers[ref-1]:
        raise ValueError('SpriteFont has no supported embedded Texture2D atlas')
    atlas_start=r.p
    # Texture2D body: format, dimensions, mip-count, first mip size, first mip bytes.
    fmt,w,h,mips=r.i32(),r.i32(),r.i32(),r.i32()
    if not 0 < w <= 32768 or not 0 < h <= 32768 or w*h > 100_000_000:
        raise ValueError('Invalid SpriteFont atlas dimensions')
    if not 1 <= mips <= 32:
        raise ValueError('Invalid SpriteFont atlas mip count')
    for _ in range(mips):
        size=r.i32()
        if size < 0 or size > 400 * 1024 * 1024:
            raise ValueError('Invalid SpriteFont mip bytes')
        r.read(size)
    atlas=r.b[atlas_start:r.p]
    # Wrap only the verified atlas body in a minimal, uncompressed XNB envelope
    # so the same surface-format decoder is used for ordinary and font textures.
    name=b'Microsoft.Xna.Framework.Content.Texture2DReader'
    data=_seven_encode(1)+_seven_encode(len(name))+name+struct.pack('<i',0)
    data+=_seven_encode(0)+_seven_encode(1)+atlas
    wrapped=b'XNBw'+bytes((5,0))+struct.pack('<I',10+len(data))+data
    image,info=texture(wrapped)
    info.update({'asset_type':'SpriteFont','atlas_only':True,'font_reader':readers[root-1],
                 'embedded_texture_reader':readers[ref-1]})
    return image,info


def effect_blob(original_xnb):
    """Preserve the compiled EffectReader byte sequence without executing it.

    The game shader source and parameter semantics are not reconstructed here.
    Returned data is an archival binary payload only, not an executable script.
    """
    payload=unpack_xnb(original_xnb)
    r=Reader(payload)
    count=r.seven()
    if not 1<=count<=128:raise ValueError('Invalid effect reader count')
    readers=[]
    for _ in range(count):readers.append(r.string());r.i32()
    shared=r.seven();root=r.seven()
    if root<1 or root>count or 'EffectReader' not in readers[root-1]:
        raise ValueError('Not an EffectReader root')
    size=r.i32()
    if not 0<size<=100*1024*1024:
        raise ValueError('Invalid compiled effect length')
    binary=r.read(size)
    # XNA effect blobs may have a platform-specific binary format, so don't
    # assume file extension, source HLSL, or a shader parameter binding.
    return binary,{'asset_type':'EffectReader','compiled_effect_bytes':size,
                    'compiled_effect_magic_hex':binary[:8].hex(),
                    'shader_source_reconstructed':False}
