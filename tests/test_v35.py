"""No game assets required. Full client XNB validated separately on user sample."""
import io
import json
import struct
import sys
import zipfile
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'engine'))
from xnb_payload import parse_header,lzx_frames,XNBError
from xnb_model_probe import inspect_model_payload
from xnb_diagnostics import inspect_xnb_bytes
from model_lab import ModelLibrary,match_models
from workbench_db import CatalogDB
from workbench_import import Importer


def fake_xnb(padding=b'\0'*5):
    # A syntactically correct LZX frame layout, not a valid LZX bitstream.
    frame=b'\0\x03abc'
    size=14+len(frame)+len(padding)
    return b'WOSBXNBw'+bytes([5,0x80])+struct.pack('<II',size,32768)+frame+padding


def test_v35_lzx_accepts_zero_alignment_padding():
    raw=fake_xnb()
    payload,head=parse_header(raw)
    frames,padding=lzx_frames(payload)
    assert len(frames)==1 and padding==5
    assert head['wrapper_bytes']==4
    assert inspect_xnb_bytes(raw)['status']=='lzx_frame_layout_valid_unverified_decompression'


def test_v35_lzx_rejects_nonzero_trailing_data():
    with pytest.raises(XNBError):lzx_frames(parse_header(fake_xnb(b'\x01'))[0])


def seven(n):
    out=bytearray()
    while n>127:out.append((n&127)|128);n>>=7
    out.append(n);return bytes(out)


def test_v35_model_metadata_bones():
    types=['Microsoft.Xna.Framework.Content.ModelReader','Microsoft.Xna.Framework.Content.StringReader']
    out=io.BytesIO();out.write(seven(2))
    for typ in types:
        b=typ.encode('utf8');out.write(seven(len(b))+b+struct.pack('<I',0))
    out.write(seven(0)+seven(1))
    out.write(struct.pack('<I',1))
    out.write(seven(2)+seven(4)+b'Root')
    out.write(struct.pack('<16f',*([1.0]*16)))
    out.write(bytes([0])+struct.pack('<I',0))
    out.write(struct.pack('<i',0))
    result=inspect_model_payload(out.getvalue())
    assert result['bone_count']==1
    assert result['mesh_count']==0
    assert result['bones'][0]['name']=='Root'


def test_v35_candidate_matching_and_explicit_link(tmp_path):
    ship={'ID':99,'EnglishName':'Vasa'}
    c=[{'source':'default/game/CommonData/Models/Ships/Ship_62_Vasa.xnb'}]
    assert match_models(ship,c)[0]['path']==c[0]['source']
    lib=ModelLibrary(tmp_path/'models')
    link=lib.link_candidate(ship,'Game',c[0]['source'],'Game')
    assert lib.linked_candidate(ship,'Game')['path']==link['path']
    with pytest.raises(ValueError):lib.link_candidate(ship,'Game',c[0]['source'],'Steam')


def test_v35_skip_all_duplicate_catalogs(tmp_path):
    zipfile_path=tmp_path/'reports.zip'
    with zipfile.ZipFile(zipfile_path,'w') as z:
        row=json.dumps({'ID':1,'EnglishName':'Test Ship'})+'\n'
        for name in ('Catalog','Catalog-2','Catalog-3'):
            z.writestr(f'Reports/Scan1/{name}/AI-Data/ShipsToPlay.jsonl',row)
    db=CatalogDB(tmp_path/'test.sqlite3')
    try:
        result=Importer(db).catalog_zip(zipfile_path)
        assert result['records']==1
        assert db.conn.execute("SELECT count(*) FROM records WHERE dataset='ShipsToPlay'").fetchone()[0]==1
    finally:db.close()
