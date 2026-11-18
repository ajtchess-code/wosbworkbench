import tempfile, unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from workbench_db import CatalogDB

class ViewerExportTests(unittest.TestCase):
 def test_publishes_saved_viewer_and_preserves_data(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)
   db=CatalogDB(root/'catalog.sqlite3')
   viewer=root/'interactive.html';viewer.write_text('<!doctype html><h1>Offline ship</h1>',encoding='utf8')
   db.register_ship_viewer('ship-brig','Brig','22','Game',viewer)
   index=db.export_wiki(root/'out')
   body=index.read_text(encoding='utf-8')
   self.assertIn('Interactive 3D: Brig',body)
   self.assertTrue((root/'out'/'interactive-ships'/'ship-brig.html').is_file())
   db.close()
if __name__=='__main__':unittest.main()
