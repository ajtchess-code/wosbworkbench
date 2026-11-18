import json
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ship_viewer import read_obj, classify_component, export_viewer, embedded_texture
from ballistics_lab import load_ballistics_catalog, illustrative_shot

class BallisticsViewerV38Tests(unittest.TestCase):
 def test_catalog_from_actual_extraction(self):
  data=load_ballistics_catalog()
  self.assertGreaterEqual(len(data['datasets']['Cannons']),42)
  self.assertGreaterEqual(len(data['datasets']['CannonBalls']),21)
  ship=next(x for x in data['datasets']['ShipsToPlay'] if x.get('EnglishName')=='Vasa')
  self.assertEqual(ship['Health'],4000)
  self.assertEqual(ship['Armor'],8.8)

 def test_helper_mesh_exclusion(self):
  self.assertEqual(classify_component('AverageBox_part0'),'helper')
  self.assertEqual(classify_component('Hitbox_part0'),'helper')
  self.assertEqual(classify_component('ShipLowCorpus_part0'),'lod')
  self.assertEqual(classify_component('ShipCorpus_part0'),'hull')

 def test_obj_uv_import_and_inline_safe_export(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)
   obj=root/'test.obj';obj.write_text('''o ShipCorpus_part0
usemtl Texture
v 0 0 0
v 1 0 0
v 0 1 0
vt 0 0
vt 1 0
vt 0 1
f 1/1 2/2 3/3
''')
   mesh=read_obj(obj)
   self.assertEqual(len(mesh['triangle_uvs']),3)
   self.assertEqual(mesh['groups'][0]['category'],'hull')
   self.assertEqual(mesh['groups'][0]['material'],'Texture')
   out=export_viewer(root/'view.html',{'EnglishName':'</script><script>alert(9)</script>'},obj)
   text=out.read_text()
   self.assertIn('Ballistics',text)
   self.assertIn('u003c',text)
   self.assertNotIn('</script><script>alert(9)</script>',text)

 def test_calculator_never_fabricates_hp(self):
  cat=load_ballistics_catalog()['datasets']
  vasa=next(s for s in cat['ShipsToPlay'] if s.get('EnglishName')=='Vasa')
  no=illustrative_shot(cat['Cannons'][0],cat['CannonBalls'][0],vasa,obliquity_deg=60)
  self.assertIsNone(no['damage_hp'])
  self.assertAlmostEqual(no['geometric_effective_armor_proxy'],17.6,places=5)
  yes=illustrative_shot(cat['Cannons'][0],cat['CannonBalls'][0],vasa,
                        measured_reference_hp=100,user_zone_multiplier=1.2)
  self.assertAlmostEqual(yes['damage_hp'],120)
  with self.assertRaises(ValueError):illustrative_shot(cat['Cannons'][0],cat['CannonBalls'][0],vasa,obliquity_deg=90)

if __name__=='__main__':unittest.main()
