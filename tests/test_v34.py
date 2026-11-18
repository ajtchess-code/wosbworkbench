import json
import zipfile
from pathlib import Path
import pytest
from discovery_center import ReportSource, scan_reports
from model_lab import ModelLibrary, match_models, export_xnb_samples
from workbench_import import Importer, path_meta
from workbench_db import CatalogDB


def test_nested_scan_archive_and_duplicate_catalog(tmp_path):
    p=tmp_path/'reports.zip'
    with zipfile.ZipFile(p,'w') as z:
        for label in ('Scan1','Scan2','Scan3'):
            prefix=f'Reports\\{label}\\'
            z.writestr(prefix+'Analysis\\Summary.json',json.dumps({'files_scanned':1}))
            if label!='Scan2':
                z.writestr(prefix+'Catalog\\Extraction-Summary.json',json.dumps({'Tables':{'ShipsToPlay':1}}))
                z.writestr(prefix+'Catalog\\AI-Data\\ShipsToPlay.jsonl',json.dumps({'ID':10,'EnglishName':'Victory'})+'\n')
                z.writestr(prefix+'Catalog-2\\AI-Data\\ShipsToPlay.jsonl',json.dumps({'ID':10,'EnglishName':'Not Victory'})+'\n')
                z.writestr(prefix+'Analysis\\Client\\XNBHeaders.json',json.dumps([{
                    'source':'CommonData/Models/Ships/Ship_10_victory.xnb',
                    'status':'decompression_failed','compressed_lzx':True}]))
    src=ReportSource(p)
    assert src.roots()==['Game','Launcher','Steam']
    assert src.json('Game/Catalog/Extraction-Summary.json')['Tables']['ShipsToPlay']==1
    src.close()
    assert len(scan_reports(p)['findings'])>=2
    db=CatalogDB(tmp_path/'db.sqlite3')
    imp=Importer(db)
    imp.catalog_zip(p)
    rows=db.conn.execute("SELECT name,source_root FROM records WHERE dataset='ShipsToPlay' ORDER BY source_root").fetchall()
    assert [tuple(row) for row in rows]==[('Victory','Game'),('Victory','Steam')]
    assert db.conn.execute("SELECT COUNT(*) FROM records WHERE dataset='ModelAssetCandidates'").fetchone()[0]==2
    db.close()


def test_model_library_persists_without_inventing_zones(tmp_path):
    obj=tmp_path/'hull.obj'
    obj.write_text('v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n',encoding='utf-8')
    ship={'ID':30,'EnglishName':'Victory'}
    lib=ModelLibrary(tmp_path/'models')
    entry=lib.import_obj(ship,'Game',obj)
    assert entry['triangles']==1
    stored=ModelLibrary(tmp_path/'models').lookup(ship,'Game')
    assert Path(stored['mesh_path']).is_file()
    assert stored['zones_path']==''
    assert lib.lookup(ship,'Steam') is None


def test_filename_match_is_candidate_only():
    paths=[{'RelativePath':'CommonData/Models/Ships/Ship_30_victory.xnb','DecodeStatus':'decompression_failed'},
           {'RelativePath':'CommonData/Models/Ships/Ship_30_victory_externalHitbox.xnb','DecodeStatus':'decompression_failed'}]
    candidate=match_models({'ID':30,'EnglishName':'Victory'},paths)
    assert len(candidate)==1
    assert 'not verified' not in candidate[0]['assessment'] or 'no verified' in candidate[0]['assessment'] or 'candidate' in candidate[0]['assessment']


def test_xnb_sample_export_opt_in_and_path_limited(tmp_path):
    root=tmp_path/'game';root.mkdir()
    child=root/'CommonData'/'Models'/'Ships';child.mkdir(parents=True)
    (child/'Ship_30_victory.xnb').write_bytes(b'WOSBXNBw\x05\x81'+b'\x00'*24)
    path=tmp_path/'samples.zip'
    result=export_xnb_samples(root,['CommonData/Models/Ships/Ship_30_victory.xnb','../other.xnb'],path)
    assert result['files']==1
    with zipfile.ZipFile(path) as z:
        assert z.read('sample-01.xnb')[:4]==b'WOSB'
        assert len(json.loads(z.read('manifest.json'))['samples'])==1


def test_report_folder_import_keeps_build_provenance(tmp_path):
    root=tmp_path/'Reports'
    for label in ('Scan1','Scan3'):
        p=root/label/'Catalog'/'AI-Data';p.mkdir(parents=True)
        (p/'ShipsToPlay.jsonl').write_text('{"ID":30,"EnglishName":"Victory"}\n',encoding='utf-8')
        q=root/label/'Catalog-2'/'AI-Data';q.mkdir(parents=True)
        (q/'ShipsToPlay.jsonl').write_text('{"ID":30,"EnglishName":"DO NOT IMPORT"}\n',encoding='utf-8')
    db=CatalogDB(tmp_path/'db.sqlite3')
    result=Importer(db).catalog_folder(root)
    assert result['records']==2
    assert db.conn.execute("SELECT COUNT(*) FROM records WHERE name='DO NOT IMPORT'").fetchone()[0]==0
    assert set(r[0] for r in db.conn.execute("SELECT source_root FROM records WHERE dataset='ShipsToPlay'"))=={'Game','Steam'}
    db.close()


def test_lzx_frame_inspection_is_read_only_and_bounded():
    import struct
    from xnb_diagnostics import inspect_xnb_bytes
    # Two tiny bytes-equivalent frame headers are metadata fixtures, not
    # invented valid LZX compressed game content.
    header=b'XNBw'+bytes([5,0x81])
    body=bytes([0xff,0,4,0,3])+b'abc'
    file_size=14+len(body)
    sample=b'WOSB'+header+struct.pack('<I',file_size)+struct.pack('<I',4)+body
    result=inspect_xnb_bytes(sample)
    assert result['recognized'] is True
    assert result['status']=='lzx_frame_layout_valid_unverified_decompression'
    assert result['lzx_frames']==1
    assert result['unpacked_bytes']==4
    assert result['wrapper_bytes']==4
    corrupted=sample[:-1]
    assert inspect_xnb_bytes(corrupted)['status']=='frame_data_truncated'
