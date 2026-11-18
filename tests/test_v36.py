"""No copyrighted game assets are required for the default v3.6 suite."""
import io
import json
import os
import struct
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'engine'))
from xnb_geometry import parse_geometry,export_obj,convert_xnb,MeshDecodeError
from model_lab import ModelLibrary,match_models,expected_model_for_ship,recover_model_for_ship
from mechanics_lab import (armor_effective,fire_damage_multiplier,microfire_threshold,
    crafting_capacity_scenario,crafting_spend,facility_output_per_operation)
from wiki_enrichment import enrich_catalog
from workbench_db import CatalogDB
from ship_viewer import read_obj


def seven(n):
    b=bytearray()
    while n>127:b.append(0x80|(n&127));n>>=7
    b.append(n);return bytes(b)


def s(v):
    raw=v.encode('utf-8');return seven(len(raw))+raw


def fake_model():
    output=io.BytesIO()
    readers=('Microsoft.Xna.Framework.Content.ModelReader',
             'Microsoft.Xna.Framework.Content.StringReader',
             'UWContentPipelineExtensionRuntime.Tags.UWModelMeshPartTag',
             'UWContentPipelineExtensionRuntime.Tags.SegmentTextureInfoTag',
             'Microsoft.Xna.Framework.Content.VertexBufferReader',
             'Microsoft.Xna.Framework.Content.IndexBufferReader')
    output.write(seven(len(readers)))
    for name in readers:output.write(s(name)+struct.pack('<i',0))
    output.write(seven(3)+seven(1))
    identity=[1.,0,0,0,0,1.,0,0,0,0,1.,0,0,0,0,1.]
    output.write(struct.pack('<I',1)+seven(2)+s('Root')+struct.pack('<16f',*identity))
    output.write(b'\x00'+struct.pack('<I',0))  # no parent, no children
    output.write(struct.pack('<i',1)+seven(2)+s('TestHull')+b'\x01'+struct.pack('<4f',0,0,0,1)+b'\x00')
    output.write(struct.pack('<i',1))
    output.write(struct.pack('<iiii',0,3,0,1))
    output.write(seven(3)+seven(4)+seven(2)+s('Wood')+seven(2)+s('Texture'))
    output.write(struct.pack('<10f',*([0.]*10)))
    output.write(seven(1)+seven(2)+seven(3))
    output.write(b'\x01\x00')  # root bone and model tag (skipped safely)
    output.write(seven(5)+struct.pack('<II',12,1)+struct.pack('<IIII',0,2,0,0))
    output.write(struct.pack('<I',3)+struct.pack('<9f',0,0,0,1,0,0,0,1,0))
    output.write(seven(6)+b'\x01'+struct.pack('<I',6)+struct.pack('<HHH',0,1,2))
    output.write(b'\x00')
    return output.getvalue()


def test_genuine_triangles_from_synthetic_xnb(tmp_path):
    payload=fake_model()
    meta=parse_geometry(payload)
    assert meta['min_vertices']==3 and meta['min_indices']==3
    assert meta['parts'][0]['texture_label']=='Texture'
    obj=tmp_path/'synthetic.obj'
    report=export_obj(payload,obj)
    assert report['triangles']==1 and report['vertices']==3
    assert read_obj(obj)['triangles_count']==1
    raw=b'XNBw'+bytes([5,0])+struct.pack('<I',len(payload)+10)+payload
    xnb=tmp_path/'synthetic.xnb';xnb.write_bytes(raw)
    assert convert_xnb(xnb,tmp_path/'converted.obj')['triangles']==1


def test_invalid_indices_rejected(tmp_path):
    broken=bytearray(fake_model())
    assert broken[-3:]==b'\x02\x00\x00'  # final index followed trailing effect
    broken[-3]=9
    try:
        export_obj(bytes(broken),tmp_path/'bad.obj')
    except MeshDecodeError as err:
        assert 'out-of-range index' in str(err)
    else:raise AssertionError('Rejected index expected')
    assert not (tmp_path/'bad.obj').exists()


def test_static_info_id_is_not_playable_id(tmp_path):
    db=CatalogDB(tmp_path/'db.sqlite3')
    ship={'ID':70,'StaticInfoID':62,'EnglishName':'Vasa','Health':4000}
    db.upsert_record('ShipsToPlay','Game',ship,0)
    db.upsert_record('ShipsBasics','Game',{'ID':62,'ModelName':'Ship_62_Vasa','Source':'ShipBasics_j.xnb'},0)
    expected=expected_model_for_ship(db,ship,'Game')
    assert expected['model_name']=='Ship_62_Vasa'
    found=match_models(ship,[{'source':'CommonData/Models/Ships/Ship_62_Vasa.xnb'}],expected_model_name=expected['model_name'])
    assert found[0]['score']>=100
    db.close()


def test_calculations_are_explicitly_evidence_gated():
    assert abs(armor_effective(8.8,15,2)['effective_armor']-12.12)<1e-8
    assert fire_damage_multiplier(200,110)['large_fire_damage_factor']==.001
    assert fire_damage_multiplier(200,110)['fire_area_damage_factor']==.01
    assert microfire_threshold(4000)['minimum_microfires']==5
    assert microfire_threshold(2500)['minimum_microfires']==3
    x=crafting_capacity_scenario(600,300,5,4)
    assert x['scenario_capacity']==920 and 'NOT verified' in x['status']
    assert crafting_spend(5,20,3)['scenario_hours_after_reduction']==12
    assert facility_output_per_operation(6,2,50,3)['scenario_total']==33


def test_wiki_source_link_and_user_edit_survive(tmp_path):
    db=CatalogDB(tmp_path/'wiki.sqlite3')
    try:
        ship={'ID':70,'StaticInfoID':62,'EnglishName':'Vasa','Armor':8.8,'Health':4000,
              'Source':'ShipsToPlay_j.xnb'}
        db.upsert_record('ShipsToPlay','Game',ship,0)
        db.upsert_record('ShipsBasics','Game',{'ID':62,'ModelName':'Ship_62_Vasa','Source':'ShipsBasics_j.xnb'},0)
        db.upsert_record('Ship_Materials','Game',{'ShipID':70,'ResourceEnglishName':'Wood','BaseQuantity':25},0)
        report=enrich_catalog(db,'Game')
        assert report['created_or_examined']>=1
        row=db.conn.execute("SELECT id,body FROM articles WHERE slug='source-game-shipstoplay-70'").fetchone()
        assert 'Ship_62_Vasa' in row['body'] and '25 units' in row['body']
        db.save_article(row['id'],'Vasa','Ships','Manual research findings','verified')
        enrich_catalog(db,'Game')
        assert db.article(row['id'])['body']=='Manual research findings'
    finally:db.close()
