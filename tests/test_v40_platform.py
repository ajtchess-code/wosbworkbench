import json
import tempfile
import unittest
import zipfile
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ship_viewer import read_obj,candidate_hitboxes_from_mesh,export_viewer
from appearance_lab import canonical_material,designs_for_ship,prepare_appearance
from engine.review_bundle import export_review
from PIL import Image

class V40Tests(unittest.TestCase):
    def test_obj_material_changes_do_not_lose_faces(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'multi.obj'
            f.write_text('''o ShipCorpus_part0
v 0 0 0
v 1 0 0
v 0 1 0
v 0 0 1
vt 0 0
vt 1 0
vt 0 1
usemtl Vasa_hull
f 1/1 2/2 3/3
usemtl Vasa_decor
f 1/1 2/2 4/3
''')
            m=read_obj(f,triangle_budget=1)
            self.assertEqual(m['triangles_count'],2)
            self.assertEqual(m['sampling_status'],'full_resolution')
            self.assertEqual([g['material'] for g in m['groups']],['Vasa_hull','Vasa_decor'])
            self.assertEqual([g['first_triangle'] for g in m['groups']],[0,1])
            page=export_viewer(Path(d)/'vasa.html',{'EnglishName':'Vasa'},f)
            text=page.read_text()
            self.assertIn('showAngleMap',text)
            self.assertIn('Vasa_decor',text)
    def test_candidate_hitbox_from_actual_helper_mesh(self):
        mesh={'vertices':[[0,0,0],[4,0,0],[0,3,2]],'triangles':[0,1,2],
              'groups':[{'name':'AverageBox_part0','category':'helper','first_triangle':0,'triangle_count':1}]}
        zones=candidate_hitboxes_from_mesh(mesh)
        self.assertEqual(zones[0]['evidence_status'],'candidate')
        self.assertEqual(zones[0]['center'],[2.,1.5,1.])
        self.assertEqual(zones[0]['size'],[4,3,2])
        self.assertIsNone(zones[0].get('damage_multiplier'))
    def test_design_case_aliases_resolve(self):
        self.assertEqual(canonical_material('MODEL/Vasa_Hull.XNB'),'vasa_hull')
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);Image.new('RGB',(4,4),(140,20,20)).save(root/'Vasa_hull.png')
            Image.new('RGB',(4,4),(30,140,40)).save(root/'Vasa_hull_hist.png')
            cat=json.loads((Path(__file__).resolve().parents[1]/'Research-Ballistics-Catalog.json').read_text())['datasets']
            ship=next(s for s in cat['ShipsToPlay'] if s.get('EnglishName')=='Vasa')
            appearance=prepare_appearance(ship,{'groups':[{'name':'ShipCorpus','material':'vasa_HULL'}]},game_assets_root=root)
            self.assertIn('Vasa_hull_hist',appearance['textures'])
            self.assertEqual(appearance['designs'][0]['matched_materials'],['Vasa_hull'])
    def test_review_only_keeps_failures_and_not_successes(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d);(out/'Reports').mkdir()
            with (out/'Reports'/'AssetLedger.jsonl').open('w') as f:
                for row in [{'path':'good.xnb','status':'decoded','kind':'model'},
                            {'path':'bad.xnb','status':'failed','kind':'texture','error_type':'XNBError','error':'missing'},
                            {'path':'unknown.xnb','status':'unsupported','kind':'material','reason':'reader_unimplemented'}]:
                    f.write(json.dumps(row)+'\n')
            paths=export_review(out,limit=256*1024)
            self.assertTrue(paths)
            with zipfile.ZipFile(paths[0]) as z:
                failures=z.read('Failed-and-Unsupported.jsonl').decode('utf-8')
                self.assertIn('bad.xnb',failures)
                self.assertIn('unknown.xnb',failures)
                self.assertNotIn('good.xnb',failures)
            self.assertLess(paths[0].stat().st_size,256*1024)
    def test_local_wiki_pages_render_from_real_catalog(self):
        import sqlite3
        from wiki_server import shipyard_page,ship_page,mechanics_page
        db=Path(__file__).resolve().parents[1]/'Starter-Catalog.sqlite3'
        with sqlite3.connect(f'file:{db}?mode=ro',uri=True) as conn:
            conn.row_factory=sqlite3.Row
            shipyard=shipyard_page(conn)
            self.assertIn('shipyard-banner',shipyard)
            self.assertTrue((Path(__file__).resolve().parents[1]/'wiki_site/assets/shipyard_background.png').is_file())
            self.assertIn('Vasa',shipyard)
            ship=ship_page(conn,'70')
            self.assertTrue(ship)
            self.assertIn('At a glance',ship)
        self.assertIn('labCrew',mechanics_page())

if __name__=='__main__':unittest.main()
