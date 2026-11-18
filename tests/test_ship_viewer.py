import json, tempfile, unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ship_viewer import read_obj,validate_zones,export_viewer

class ShipViewerTests(unittest.TestCase):
 def test_obj_and_html(self):
  with tempfile.TemporaryDirectory() as tmp:
   tmp=Path(tmp)
   mesh=tmp/'ship.obj';mesh.write_text('v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nf 1 2 3 4\nf -4 -3 -2\n',encoding='utf-8')
   model=read_obj(mesh)
   self.assertEqual(model['triangles_count'],3)
   self.assertEqual(len(model['triangles']),9)
   out=tmp/'ship.html'
   zones=tmp/'zones.json';zones.write_text(json.dumps({'zones':[{'name':'Mast candidate','center':[0,0,0],
           'size':[1,2,1],'evidence_status':'candidate','source':'Common.dll 0x6','classification':'mast'}]}))
   export_viewer(out,{'EnglishName':'<script>evil()</script>'},mesh,zones)
   html=out.read_text(encoding='utf-8')
   self.assertIn('Mast candidate',html)
   self.assertIn('WebGL',html)
   self.assertNotIn('<script>evil()</script>',html)
 def test_source_required(self):
  with self.assertRaises(ValueError):
   validate_zones([{'name':'Fake verified','center':[0,0,0],'size':[1,1,1],
                  'evidence_status':'verified','damage_multiplier':1.5}])
  self.assertEqual(validate_zones([{'name':'Unknown zone','size':[1,1,1],
                  'center':[0,0,0]}])[0]['evidence_status'],'manual')
 def test_invalid_geometry_rejected(self):
  with tempfile.TemporaryDirectory() as tmp:
   mesh=Path(tmp)/'bad.obj';mesh.write_text('v 0 0 0\nv 1 0 0\nf 1 2 3\n',encoding='utf-8')
   with self.assertRaises(ValueError):read_obj(mesh)

if __name__=='__main__':unittest.main()
