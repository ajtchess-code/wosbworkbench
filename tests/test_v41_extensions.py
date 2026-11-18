from contextlib import closing
"""Regression tests for v4.1 additions; no WoSB game process or network access."""
import json,math,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch

from combat_scenarios import incoming_direction,obliquity_deg,describe_shot
from mechanics_verified import client_sail_damage_energy,client_cannon_penetration
from model_quality import inspect_mesh
from offline_emulator import SandboxWorld
from wiki_expanded import compare_page,shipyard_tree_page,guide_index_page,guide_page

class FormulaTests(unittest.TestCase):
    def test_client_sail_energy(self):
        self.assertEqual([client_sail_damage_energy(i)['sail_damage_energy'] for i in range(5)],
                         [1.0,0.5,1/3,0.0,0.0])
    def test_penetration_override(self):
        self.assertEqual(client_cannon_penetration(None,10)['client_penetration_field'],10)
        self.assertEqual(client_cannon_penetration(23,10)['client_penetration_field'],23)
    def test_geometry_angle(self):
        self.assertAlmostEqual(obliquity_deg([0,0,1],incoming_direction(0,0)),0)
        self.assertAlmostEqual(obliquity_deg([0,0,1],incoming_direction(90,0)),90)
    def test_shot_doesnt_make_up_hp(self):
        ship={'EnglishName':'Vasa','Health':4000,'Armor':8.8}
        result=describe_shot(ship,{'EnglishName':'Gun','Poundage':42},{'EnglishName':'Ball','DamageFactor':1.2},hit_normal=[0,0,1])
        self.assertIsNone(result['damage']['hp'])
        self.assertEqual(result['firing']['impact_obliquity_degrees'],0)
        self.assertFalse(result.get('client_armor'))
        with self.assertRaises(ValueError):describe_shot(ship,{}, {},hit_normal=[0,0,0])

class ModelTests(unittest.TestCase):
    def test_quality_report_not_missing_mesh(self):
        mesh={'vertices':[[0,0,0],[1,0,0],[0,1,0]],'triangles':[0,1,2],
              'original_triangles_count':1,'groups':[{'name':'Hull','first_triangle':0,'triangle_count':1,'material':'hull'}]}
        report=inspect_mesh(mesh)
        self.assertTrue(report['triangle_geometry_preserved'])
        self.assertEqual(report['boundary_edges_sampled'],3)
        self.assertEqual(report['invalid_indices'],0)
        self.assertEqual(report['degenerate_triangles'],0)
    def test_degenerate_triangles_reported(self):
        x=inspect_mesh({'vertices':[[0,0,0],[1,0,0],[2,0,0]],'triangles':[0,1,2]})
        self.assertEqual(x['degenerate_triangles'],1)

class WorldTests(unittest.TestCase):
    def test_no_fabricated_damage(self):
        w=SandboxWorld(tick_seconds=.5)
        w.spawn('a','Apostolov',100)
        w.set_controls('a',speed=4,heading_deg=0)
        w.step(2)
        self.assertAlmostEqual(w.vessels['a'].z,4)
        self.assertEqual(w.vessels['a'].hp,100)
        w.apply_observed_damage('a',30)
        self.assertEqual(w.vessels['a'].hp,70)
        self.assertEqual(w.snapshot()['damage_status'],'observations_only')

class WikiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn=sqlite3.connect('Starter-Catalog.sqlite3');cls.conn.row_factory=sqlite3.Row
        from wiki_server import rows,ship_list,shell
        cls.rows=staticmethod(rows);cls.ships=staticmethod(ship_list);cls.shell=staticmethod(shell)
    @classmethod
    def tearDownClass(cls):cls.conn.close()
    def test_compare(self):
        html=compare_page(self.conn,self.ships,self.shell)
        self.assertIn('Ship comparison',html)
        self.assertIn('Hull HP',html)
    def test_shipyard_atlas(self):
        text=shipyard_tree_page(self.conn,self.ships,self.shell)
        self.assertIn('fleet-lane',text)
        self.assertIn('original ship roster',text)
    def test_guides(self):
        index=guide_index_page(self.shell)
        self.assertIn('/guide/armor',index)
        for slug in ('cannons','ammunition','armor','wind','equipment','hitboxes'):
            body=guide_page(self.conn,self.rows,self.shell,slug)
            self.assertIn('local encyclopedia',body)
            self.assertIn('recovered',body.lower())

class EvidenceTests(unittest.TestCase):
    def test_il_signatures(self):
        from engine.evidence_signatures import audit_folder
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'sample.il.txt'
            p.write_text('# 0x06002533 Common.Game.CannonBall::SailDamageEnergy\n'
                         '0001 ldarg.0\n0002 ldc.i4.3\n0003 bge.s 20\n'
                         '0005 ldc.r4 1.0\n000a ldc.r4 1.0\n0010 conv.r4\n0011 add\n0012 div\n0014 ldc.r4 0.0\n',encoding='utf-8')
            report=audit_folder(td)
            self.assertEqual(report['verified_client_methods']['sail_damage_energy']['status'],'client_signature_matches')

class RecoveryTests(unittest.TestCase):
    def test_build_diffs(self):
        from engine.recover_everything import compare_sources
        with tempfile.TemporaryDirectory() as td:
            paths={}
            for label,hash_value in (('game','aa'),('steam','bb')):
                root=Path(td)/label;root.mkdir()
                with closing(sqlite3.connect(root/'Recovery-State.sqlite3')) as db, db:
                    db.execute('CREATE TABLE assets(path TEXT,sha256 TEXT,kind TEXT,status TEXT)')
                    db.execute('INSERT INTO assets VALUES(?,?,?,?)',('Ship.xnb',hash_value,'model','decoded'))
                paths[label]=root
            report=compare_sources(paths)
            self.assertEqual(report['different_paths_or_hashes'],1)

if __name__=='__main__':unittest.main()
