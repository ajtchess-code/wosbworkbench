import json
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from appearance_lab import designs_for_ship, parse_swaps, prepare_appearance
from calibration_lab import load_trials
from ship_viewer import read_obj,make_html
from PIL import Image

class AppearanceV39Tests(unittest.TestCase):
    def setUp(self):
        catalog=json.loads((Path(__file__).resolve().parents[1]/'Research-Ballistics-Catalog.json').read_text(encoding='utf-8'))['datasets']
        self.vasa=next(r for r in catalog['ShipsToPlay'] if r['EnglishName']=='Vasa')
        self.huracan=next(r for r in catalog['ShipsToPlay'] if r['EnglishName']=='Huracan')

    def test_actual_design_maps(self):
        d=designs_for_ship(self.vasa)
        museum=next(x for x in d if x['name']=='Vasa Museum')
        self.assertEqual(museum['swaps']['Vasa_hull'],'Vasa_hull_hist')
        self.assertEqual(museum['swaps']['Vasa_alpha'],'Vasa_alpha_hist')
        hur=designs_for_ship(self.huracan)
        self.assertGreaterEqual(len(hur),3)
        self.assertEqual(next(x for x in hur if x['name']=='Huracan Red Fish')['swaps']['Empire_1_hull'],'Empire_3_hull')

    def test_xnb_model_segment_names(self):
        model=(Path(__file__).resolve().parents[1]/'engine/xnb_geometry.py').read_text('utf-8')
        self.assertIn("part['segment_label'] or part['texture_label']",model)

    def test_local_exact_asset_images(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'ModelTextures/Lod0/Ships').mkdir(parents=True)
            Image.new('RGB',(4,4),(30,100,100)).save(root/'ModelTextures/Lod0/Ships/Vasa_hull.png')
            Image.new('RGB',(4,4),(80,120,30)).save(root/'ModelTextures/Lod0/Ships/Vasa_hull_hist.png')
            mesh={'groups':[{'material':'Vasa_hull','name':'ShipCorpus_part0'}]}
            resolved=prepare_appearance(self.vasa,mesh,game_assets_root=root)
            self.assertIn('Vasa_hull',resolved['textures'])
            self.assertIn('Vasa_hull_hist',resolved['textures'])
            self.assertIn('Vasa_hull',resolved['expected_texture_paths'])
            self.assertEqual(len(resolved['designs']),1)
            html=make_html(self.vasa,mesh,appearance=resolved)
            self.assertIn('Vasa_hull_hist',html)
            self.assertIn('skinSelect',html)

    def test_full_mesh_preserves_names_and_original_count(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'big.obj'
            with p.open('w',encoding='utf-8') as f:
                f.write('v 0 0 0\nv 1 0 0\nv 0 1 0\n')
                f.write('o ShipCorpus_part0\nusemtl Empire_1_hull\n')
                for i in range(100_000):f.write('f 1 2 3\n')
                f.write('o DeckStuff_part0\nusemtl Empire_floor\n')
                for i in range(100_000):f.write('f 1 2 3\n')
            data=read_obj(p,triangle_budget=20_000)
            self.assertEqual(data['original_triangles_count'],200_000)
            self.assertEqual(data['triangles_count'],200_000)
            self.assertEqual(data['sampling_status'],'full_resolution')
            self.assertEqual(data['groups'][0]['material'],'Empire_1_hull')
            self.assertEqual(data['groups'][1]['material'],'Empire_floor')
            self.assertEqual(data['groups'][0]['first_triangle'],0)
            self.assertEqual(data['groups'][1]['first_triangle'],100_000)

    def test_measured_trials_only(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'shots.csv'
            p.write_text('weapon,ammo,target_ship,target_armor_region,observed_hp_damage,range_m,impact_angle_deg\n'
                         'Long Cannon,Round Shot,Vasa,starboard,75,100,20\n'
                         'Long Cannon,Round Shot,Vasa,starboard,80,100,21\n'
                         'Long Cannon,Round Shot,Vasa,starboard,abc,100,21\n',encoding='utf-8')
            data=load_trials(p)
            self.assertEqual(len(data),2)
            self.assertEqual(data[0]['damage'],75)

if __name__=='__main__':unittest.main()
