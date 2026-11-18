"""New player-facing research suite regression tests, using only local fixtures."""
import csv
import io
import json
import math
import tempfile
import unittest
import urllib.request
from pathlib import Path

from combat_studio import impact_angle,attacker_direction,trajectory,angle_heatmap,suggested_trials,observe_prediction
from research_suite import setup_report,save_workspace,load_workspace,asset_coverage,material_coverage,release_audit
from video_evidence import measure_bar,hp_estimate,correlate_markers


class MechanicsV43Test(unittest.TestCase):
    def test_angle_perpendicular_front(self):
        self.assertEqual(impact_angle([0,0,-1],[0,0,1])['obliquity_degrees'],0)
    def test_angle_grazing(self):
        self.assertAlmostEqual(impact_angle([1,0,-0.1],[0,0,1])['obliquity_degrees'],84.2894,places=3)
    def test_backface_not_colored(self):
        self.assertIsNone(impact_angle([0,0,1],[0,0,1])['obliquity_degrees'])
    def test_nonfinite_rejected(self):
        with self.assertRaises(ValueError):impact_angle([math.nan,1,2],[0,0,1])
    def test_attacker_direction(self):
        self.assertEqual(attacker_direction([0,0,0],[-5,0,0]),[1,0,0])
    def test_trajectory_no_gravity(self):
        d=trajectory(origin=[0,0,0],velocity=[0,3,0],duration=2,steps=3,gravity=0)
        self.assertEqual(d['sample_points'][-1],[0,6,0]);self.assertFalse(d['verified_game_trajectory'])
    def test_trajectory_limits(self):
        with self.assertRaises(ValueError):trajectory(origin=[0,0,0],velocity=[1,0,0],steps=10000)
    def test_heatmap_backface(self):
        a=angle_heatmap([{'normal':[0,0,-1]},{'normal':[0,0,1]}],[0,0,1])
        self.assertTrue(a['values'][0]['front_facing']);self.assertFalse(a['values'][1]['front_facing'])
    def test_experiment_plan(self):
        p=suggested_trials([],zones=['stern'],angles=[0,30],repeats=4)
        self.assertEqual(len(p),2);self.assertEqual(p[0]['needed_repetitions'],4)
    def test_empirical_insufficient(self):
        r=observe_prediction([{'target_ship':'A','weapon':'B','ammo':'C','region':'stern','damage':3}])
        self.assertEqual(r[0]['status'],'insufficient_independent_measurements')
        self.assertIsNone(r[0]['observed_mean_hp'])


class HPVideoV43Test(unittest.TestCase):
    def test_measure_colored_bar(self):
        from PIL import Image
        image=Image.new('RGB',(100,20),(11,11,11))
        for x in range(60):
            for y in range(20):image.putpixel((x,y),(200,20,20))
        result=measure_bar(image,(0,0,100,20),bar_color=(200,20,20),tolerance=25)
        self.assertAlmostEqual(result['fraction'],.6,delta=.04)
        self.assertGreater(result['confidence'],.9)
    def test_uncolored_bar_uncertain(self):
        from PIL import Image
        image=Image.new('RGB',(30,12),'black')
        result=measure_bar(image,(0,0,30,12),bar_color=(180,20,20))
        self.assertTrue(result['empty_bar_ambiguous']);self.assertEqual(result['confidence'],0)
    def test_bar_invalid_region(self):
        from PIL import Image
        with self.assertRaises(ValueError):measure_bar(Image.new('RGB',(20,20)),(-1,0,20,20),bar_color=(1,2,3))
    def test_hp_projection_is_assumption(self):
        r=hp_estimate({'fraction':.4},known_max_hp=3000)
        self.assertEqual(r['hp_from_linear_bar_assumption'],1200);self.assertFalse(r['in_game_hp_confirmed'])
    def test_temporal_matching_only(self):
        from datetime import datetime,timezone
        t=1000.0
        result=correlate_markers([{'time':t,'kind':'broadside'}], [{'time':1001.0,'bytes':45,'direction':'client'}])
        self.assertEqual(result['events'][0]['candidate_segments_nearby'],1)
        self.assertIn('unverified',result['events'][0]['classification'])


class LocalRecoveryV43Test(unittest.TestCase):
    def test_workspace_round_trip_and_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'state.json'
            save_workspace(p,{'selected_ship_id':65,'camera':{'bearing':45},'untrusted':'ignore'})
            save_workspace(p,{'selected_ship_id':70})
            self.assertEqual(load_workspace(p)['selected_ship_id'],70)
            self.assertTrue(p.with_suffix('.json.bak').exists())
            self.assertNotIn('untrusted',load_workspace(p))
    def test_asset_ledger_grouping(self):
        with tempfile.TemporaryDirectory() as directory:
            f=Path(directory)/'ledger.jsonl';f.write_text('\n'.join(map(json.dumps,[
                {'kind':'model','status':'decoded','path':'A.xnb'},
                {'kind':'effect','status':'unsupported','path':'B.xnb','reason':'unsupported reader'},
                {'kind':'xnb','status':'failed','path':'C.xnb','error':'bad header'}]))+'\n')
            output=asset_coverage(f)
            self.assertEqual(output['total'],3);self.assertEqual(output['statuses']['decoded'],1)
            self.assertEqual(len(output['issue_samples']),2)
    def test_material_status_count(self):
        with tempfile.TemporaryDirectory() as directory:
            f=Path(directory)/'links.jsonl';f.write_text(json.dumps({'status':'unresolved','material':'Wood'})+'\n')
            self.assertEqual(material_coverage(f)['statuses']['unresolved'],1)
    def test_setup_report_is_non_destructive(self):
        out=setup_report();self.assertIn('disk_free_gb',out);self.assertFalse(out.get('auto_installed',False))
    def test_release_checks(self):
        result=release_audit(Path(__file__).resolve().parents[1]);self.assertEqual(result['failed'],0)
    def test_repair_queue_against_two_records(self):
        from engine.repair_queue import make_queue
        with tempfile.TemporaryDirectory() as directory:
            report=Path(directory)/'Reports';report.mkdir()
            (report/'AssetLedger.jsonl').write_text(json.dumps({'path':'Some.fx.xnb','kind':'effect',
                      'status':'unsupported','reason':'reader_identified_body_unimplemented'})+'\n')
            (report/'ModelTextureLinks.jsonl').write_text(json.dumps({'status':'unresolved','material_label':'test'})+'\n')
            out=make_queue(directory)
            self.assertGreaterEqual(len(out['tasks']),2)


class WebV43Test(unittest.TestCase):
    def test_new_pages_and_designs_work(self):
        import wiki_server
        root=Path(__file__).resolve().parents[1]
        server,url=wiki_server.serve(root/'Starter-Catalog.sqlite3',open_browser=False)
        try:
            for path,needle in [('/studio','Research Center'),('/workshop','Ship Outfitting Studio'),
                   ('/experiments','Combat Experiment Builder'),('/ballistics-studio','Ballistics Studio'),
                   ('/damage-research','Damage Evidence Atlas'),('/capture-research','Capture'),
                   ('/visual-parity','Visual Fidelity Lab'),('/preflight','Setup'),
                   ('/weapon-compare','Cannon'),('/sailing-performance','Wind'),('/protocol-library','Protocol')]:
                with urllib.request.urlopen(url.rstrip('/')+path,timeout=5) as response:
                    self.assertEqual(response.status,200,path)
                    self.assertIn(needle,response.read().decode(),path)
            with urllib.request.urlopen(url.rstrip('/')+'/api/catalog') as response:
                datasets=json.load(response)['datasets']
                variants=[r for r in datasets['ShipDesingElements'] if r['Category']=='ShipFullDesign' and r['ShipId']==65]
                self.assertGreaterEqual(len(variants),3)
            with urllib.request.urlopen(url.rstrip('/')+'/static/next.js') as response:
                script=response.read().decode()
                self.assertIn('WoSB Codex v4.3',script)
                # The options are server-rendered by ID but client datasets are array indexed.
                self.assertIn('setOptions(selection,ships);',script)
        finally:server.shutdown();server.server_close()

if __name__=='__main__':unittest.main()
