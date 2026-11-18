"""Regression checks for version comparisons, decoder triage and wiki task generation."""
from __future__ import annotations
import json
import zipfile

from discovery_center import scan_reports, audit_catalog, save_audit
from workbench_db import CatalogDB
from discovery_extensions import normalize_game_path, compare_inventories


def test_normalized_installation_paths():
    assert normalize_game_path('default/game/CommonData/Ships.xnb','Game')=='commondata/ships.xnb'
    assert normalize_game_path('CommonData/Ships.xnb','Steam')=='commondata/ships.xnb'
    diff=compare_inventories({'Game':{'shared.xnb':'a','one.xnb':'b'},
                              'Steam':{'shared.xnb':'c'},'Launcher':{'launcher.exe':'d'}})
    assert (diff['game_only'],diff['steam_only'],diff['different_hash'],diff['launcher_unique'])==(1,0,1,1)


def test_report_diagnostics_and_decoder_queue(tmp_path):
    path=tmp_path/'reports.zip'
    with zipfile.ZipFile(path,'w') as z:
        for root,sha in [('Game','a'),('Steam','b')]:
            pref=root+'/Analysis/'
            z.writestr(pref+'Summary.json',json.dumps({'files_scanned':2}))
            z.writestr(root+'/Catalog/Extraction-Summary.json',json.dumps({'Tables':{'ShipsToPlay':1},'KnownCodeBuild':True,'CommonSHA256':sha}))
            z.writestr(pref+'Client/FileInventory.json',json.dumps([
                {'path':('default/game/' if root=='Game' else '')+'CommonData/model.xnb','sha256':sha,'format':'WoSB-wrapped XNB','extension':'.xnb'},
                {'path':'mystery.bin','sha256':'q','format':'unrecognized','extension':'.bin'}]))
            z.writestr(pref+'Client/XNBHeaders.json',json.dumps([
                {'source':'CommonData/Models/ship_a.xnb','status':'decompression_failed','compressed_lzx':True,'reader_types':[]}]))
            z.writestr(pref+'Client/ImageDecodeHealth.csv','source,status\nCommonData/Models/ship_a.xnb,failed\n')
            z.writestr(root+'/Catalog/AI-Data/Game_Enums.jsonl',json.dumps({'Type':'ExampleEnum','Member':'Test','Value':1 if root=='Game' else 2})+'\n')
    result=scan_reports(path)
    assert result['comparisons']['different_hash']==1
    assert result['decoder_queue']
    assert any(f['category']=='Unknown data discovery' for f in result['findings'])
    assert any('definitions' in f['title'] for f in result['findings'])


def test_cross_reference_matching_and_auto_tasks(tmp_path):
    db=CatalogDB(tmp_path/'catalog.db')
    db.upsert_record('Resources','Game',{'ID':'res_31','EnglishName':'Iron Ore'},1,'test')
    db.upsert_record('Resources','Game',{'ID':'res_1','EnglishName':'Wood'},2,'test')
    db.upsert_record('Crafting_Recipes','Game',{'RecipeID':'CRAFT1','OutputType':'resource','OutputID':31},1,'test')
    db.upsert_record('Recipe_Ingredients','Game',{'RecipeID':'CRAFT1','ResourceID':31,'Quantity':2},1,'test')
    db.upsert_record('CaptainSkills','Game',{'Name':'skill_20','EnglishName':'Workshop','Effect':'CCraftTimeLimitPerEachWorkshop +5'},1,'test')
    db.upsert_record('GuildBonuses','Game',{'Type':'MCraftTimeLimit','EnglishName':'Shared Workshops'},1,'test')
    db.conn.commit()
    result=audit_catalog(db)
    assert not any('unresolved' in f['title'] and 'Recipe_Ingredients' in f['title'] for f in result['findings'])
    assert result['relationship_count']>0
    assert any('crafting-time' in f['title'] for f in result['findings'])
    save_audit(db,result)
    assert db.conn.execute("SELECT count(*) FROM articles WHERE section='Research backlog'").fetchone()[0]>=1
    db.close()
