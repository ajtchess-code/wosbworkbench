import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from appearance_lab import detect_local_asset_root, prepare_appearance
from ship_viewer import export_viewer

class AppearanceV433Tests(unittest.TestCase):
    def setUp(self):
        data=json.loads((Path(__file__).resolve().parents[1]/'Research-Ballistics-Catalog.json').read_text())['datasets']
        self.ship=next(x for x in data['ShipsToPlay'] if x['EnglishName']=='Huracan')

    def make_asset_tree(self,root):
        path=root/'default/game/Data/ModelTextures/Lod0/Ships'
        path.mkdir(parents=True)
        Image.new('RGBA',(4,4),(100,90,40,255)).save(path/'Empire_1_hull.png')
        Image.new('RGBA',(4,4),(150,15,50,255)).save(path/'Empire_3_hull.png')

    def test_detects_installed_game_from_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.make_asset_tree(root)
            with patch.dict(os.environ,{'WOSB_GAME_ROOT':str(root)}):
                self.assertEqual(detect_local_asset_root(),str(root))

    def test_offline_scripts_created_for_default_and_design(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.make_asset_tree(root)
            dest=root/'viewer-assets'
            mesh={'groups':[{'material':'Empire_1_hull','name':'ShipCorpus_part0'}]}
            app=prepare_appearance(self.ship,mesh,game_assets_root=root,texture_output_dir=dest)
            self.assertIn('Empire_1_hull',app['textures'])
            self.assertIn('Empire_3_hull',app['textures'])
            for name in ('Empire_1_hull','Empire_3_hull'):
                item=app['textures'][name]
                self.assertTrue((root/item['browser_loader']).exists())
                self.assertIn('data:image/png;base64,',(root/item['browser_loader']).read_text())
                self.assertEqual(item['asset_source'].endswith('.png'),True)

    def test_diagnostics_written_for_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.make_asset_tree(root)
            obj=root/'huracan.obj';obj.write_text('v 0 0 0\nv 1 0 0\nv 0 1 0\nvt 0 0\nvt 1 0\nvt 0 1\no ShipCorpus_part0\nusemtl Empire_1_hull\nf 1/1 2/2 3/3\n')
            out=root/'huracan.html'
            export_viewer(out,self.ship,obj,game_assets_root=root)
            diagnostics=json.loads((root/'huracan-Appearance-Diagnostics.json').read_text())
            self.assertEqual(diagnostics['format'],'wosb-appearance-diagnostics-v433')
            self.assertIn('Empire_1_hull',diagnostics['loaded_texture_candidates'])
            red=next(d for d in diagnostics['designs'] if d['name']=='Huracan Red Fish')
            self.assertTrue(red['replacement_images_found']['Empire_1_hull'])
            self.assertIn('browser_loader',out.read_text())

if __name__=='__main__':unittest.main()
