import math
import sqlite3
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sailing_lab import winding_dot_at_angle, wind_speed_component,seed_sailing_pages,rose_records
from workbench_db import CatalogDB

class SailingTests(unittest.TestCase):
 def test_components_from_il(self):
  self.assertAlmostEqual(winding_dot_at_angle(0),1)
  self.assertAlmostEqual(wind_speed_component(0),1.8)
  self.assertAlmostEqual(winding_dot_at_angle(180),-1)
  self.assertAlmostEqual(wind_speed_component(180),0)
  self.assertAlmostEqual(winding_dot_at_angle(90),.6)
  self.assertAlmostEqual(wind_speed_component(90),1.44)
  self.assertAlmostEqual(wind_speed_component(450),wind_speed_component(90))
 def test_wiki_preserves_edits(self):
  with tempfile.TemporaryDirectory() as tmp:
   db=CatalogDB(Path(tmp)/'test.sqlite3')
   db.upsert_record('WindRoses','Game',{'ID':'r','Name':'regular','Source':'fixture','GreenRight':{'Start':36.6}},1)
   self.assertEqual(seed_sailing_pages(db),1)
   row=db.conn.execute('select * from articles where slug=?',('research-sailing-wind-physics',)).fetchone()
   self.assertIn('Common.dll',row['body'])
   db.save_article(row['id'],row['title'],row['section'],'Custom research','reviewed')
   seed_sailing_pages(db)
   self.assertEqual(db.article(row['id'])['body'],'Custom research')
   db.close()

if __name__=='__main__':unittest.main()
