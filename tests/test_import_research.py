import json, tempfile, unittest, zipfile
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from workbench_db import CatalogDB
from workbench_import import Importer

class ResearchImportTests(unittest.TestCase):
 def test_scan_bounded_sources(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);archive=root/'rep.zip'
   with zipfile.ZipFile(archive,'w') as z:
    z.writestr('Game/Catalog/AI-Data/WindRoses.jsonl',json.dumps({'Name':'regular','SourceRecord':1})+'\n')
    z.writestr('Game/Catalog/AI-Data/Asset_Inventory.jsonl',
               json.dumps({'RelativePath':'Data/Models/Hull.xnb','DecodeStatus':'Windows LZX decompression failed'})+'\n')
    z.writestr('Game/Catalog/CodeArchive/Common/0x060027B6_Common.Game.WindRose_SpeedByWind.il.txt',
               '0001 ldarg.0\n0002 ldc.r4 0.5\n')
   db=CatalogDB(root/'db.sqlite3')
   res=Importer(db).catalog_zip(archive)
   self.assertEqual(res['records'],1)
   self.assertEqual(db.conn.execute("select count(*) from records where dataset='ModelAssetCandidates'").fetchone()[0],1)
   self.assertEqual(db.conn.execute("select count(*) from records where dataset='SailingAndMechanicsMethodEvidence'").fetchone()[0],1)
   db.close()

if __name__=='__main__':unittest.main()
