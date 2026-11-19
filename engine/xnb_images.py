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
                decode=texture2ddecoder.decode_bc1 if fmt==4 else texture2ddecoder.decode_bc3
                im=Image.frombytes('RGBA',(w,h),decode(pixels,w,h),'raw','BGRA')
            except ImportError:
                im=decode_bc_numpy(pixels,w,h,bc3=(fmt==6))
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


def decode_bc_numpy(data,w,h,*,bc3=False):
    """BC1 (DXT1) / BC3 (DXT5) decoder used when texture2ddecoder is not installed."""
    import numpy as np
    bw,bh=max(1,(w+3)//4),max(1,(h+3)//4);bs=16 if bc3 else 8
    blk=np.frombuffer(data[:bw*bh*bs],dtype=np.uint8).reshape(bh*bw,bs)
    col=blk[:,8:] if bc3 else blk
    c0=col[:,0].astype(np.uint32)|(col[:,1].astype(np.uint32)<<8);c1=col[:,2].astype(np.uint32)|(col[:,3].astype(np.uint32)<<8)
    bits=col[:,4].astype(np.uint32)|(col[:,5].astype(np.uint32)<<8)|(col[:,6].astype(np.uint32)<<16)|(col[:,7].astype(np.uint32)<<24)
    def rgb(c):return np.stack([((c>>11)&31)*255//31,((c>>5)&63)*255//63,(c&31)*255//31],1).astype(np.int32)
    a,b=rgb(c0),rgb(c1);four=(c0>c1)|bc3
    p2=np.where(four[:,None],(2*a+b)//3,(a+b)//2);p3=np.where(four[:,None],(a+2*b)//3,0)
    pal=np.stack([a,b,p2,p3],1)                                   # n,4,3
    idx=(bits[:,None]>>(2*np.arange(16,dtype=np.uint32)))&3        # n,16
    rgbpx=np.take_along_axis(pal,idx[:,:,None].astype(np.int64).repeat(3,2),1)  # n,16,3
    if bc3:
        a0=blk[:,0].astype(np.int32);a1=blk[:,1].astype(np.int32)
        ab=np.zeros(len(blk),dtype=np.uint64)
        for k in range(6):ab|=blk[:,2+k].astype(np.uint64)<<np.uint64(8*k)
        ai=((ab[:,None]>>(np.uint64(3)*np.arange(16,dtype=np.uint64)))&np.uint64(7)).astype(np.int64)
        j=np.arange(8)
        eight=np.where(j==0,a0[:,None],np.where(j==1,a1[:,None],((8-j)*a0[:,None]+(j-1)*a1[:,None])//7))
        six=np.where(j==0,a0[:,None],np.where(j==1,a1[:,None],np.where(j<6,((6-j)*a0[:,None]+(j-1)*a1[:,None])//5,np.where(j==6,0,255))))
        apal=np.where((a0>a1)[:,None],eight,six)
        alpha=np.take_along_axis(apal,ai,1)
    else:
        alpha=np.where((~four)[:,None]&(idx==3),0,255)
    px=np.concatenate([rgbpx,alpha[:,:,None]],2).astype(np.uint8).reshape(bh,bw,4,4,4).transpose(0,2,1,3,4).reshape(bh*4,bw*4,4)
    return Image.fromarray(px[:h,:w].copy(),'RGBA')


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
