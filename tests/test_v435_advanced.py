"""v4.3.5 regression tests for research tooling and evidence boundaries."""
from __future__ import annotations
import json,os,sqlite3,struct,tempfile,unittest,zipfile
from pathlib import Path

from advanced_geometry import MeshRaycaster,compare_impacts,sample_heatmap
from advanced_assets import failure_class,recovery_triage,inventory_tree,diff_inventories,audit_design
from advanced_network import fit_clocks,assign_target_ids,analyze_stream_continuity
from advanced_experiments import open_db,add_experiment,add_observation,experiment_report,export_experiments
from advanced_sailing import evaluate_maneuver,trajectory,compare_wind_profiles
from advanced_catalog import dataset_snapshot,compare_catalogs,record_provenance
from advanced_release import make_manifest,build_source_zip


class AdvancedResearchTests(unittest.TestCase):
    def mesh(self):
        return {'vertices':[[0,0,0],[1,0,0],[0,1,0],[0,0,1]],
                'triangles':[0,1,2,0,1,3],
                'groups':[{'first_triangle':0,'triangle_count':2,'name':'ship_hull','material':'wood','category':'hull'}]}

    def test_atomic_report_write_preserves_prior_on_failure(self):
        from advanced_io import write_json_atomic
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'summary.json'
            write_json_atomic(p,{'verified':False})
            with self.assertRaises(ValueError):write_json_atomic(p,{'oversized':'12345'},limit=3)
            self.assertEqual(json.loads(p.read_text(encoding='utf-8')),{'verified':False})
            self.assertFalse(list(Path(tmp).glob('*.partial')))

    def test_video_frame_budget_rejected_before_subprocess(self):
        from advanced_video import candidate_events
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'mock.mp4';p.write_bytes(b'mock')
            with self.assertRaisesRegex(ValueError,'128 MiB'):
                candidate_events(p,ffmpeg='/does-not-exist',fps=12,max_seconds=3600,width=400,height=300)

    def test_bvh_hit_and_miss(self):
        caster=MeshRaycaster(self.mesh(),leaf_size=2)
        hit=caster.hit([.2,.2,1],[0,0,-1])
        self.assertEqual(hit['triangle'],0)
        self.assertEqual(hit['point'],[.2,.2,0])
        self.assertEqual(hit['incidence_angle_deg'],0)
        self.assertFalse(hit['game_collision_verified'])
        self.assertIsNone(caster.hit([9,9,9],[0,0,-1]))

    def test_bvh_rejects_invalid_indices(self):
        with self.assertRaises(ValueError):MeshRaycaster({'vertices':[[0,0,0]],'triangles':[0,1,2]})

    def test_raycast_provenance(self):
        result=compare_impacts(self.mesh(),[{'origin':[.1,.1,1],'direction':[0,0,-1]}])
        self.assertEqual(result['rays'][0]['impact']['mesh_group']['material'],'wood')
        self.assertEqual(result['provenance']['collision'],'UNVERIFIED')

    def test_heatmap_never_certifies_collision(self):
        data=sample_heatmap(self.mesh(),{'Poundage':42,'Penetration':10},{'DamageFactor':1,'Penetration':0},target_armor=5,samples=4,axis=2)
        self.assertEqual(data['total_samples'],16)
        self.assertFalse(data['authoritative_damage'])
        self.assertIn('UNIFORM',data['armor_model'])

    def test_failure_classification(self):
        self.assertEqual(failure_class('MeshDecodeError: invalid index'),'mesh_layout_or_triangle')
        self.assertEqual(failure_class('XNB LZX decompress failed'),'compression_or_xnb_header')
        self.assertEqual(failure_class('Unsupported effect reader'),'unsupported_reader_or_effect')

    def test_triage_reads_real_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'ledger.jsonl'
            p.write_text('\n'.join(json.dumps(x) for x in [
                {'path':'a.xnb','status':'decoded'},
                {'path':'b.xnb','status':'failed','error_type':'MeshDecodeError'}]))
            result=recovery_triage(p)
            self.assertEqual(sum(result['counts'].values()),1)
            self.assertFalse(result['queues'][0].get('verified_fixed',False))

    def test_snapshot_and_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'sample.obj').write_text('abc',encoding='utf-8');a=inventory_tree(root)
            (root/'sample.obj').write_text('abd',encoding='utf-8');(root/'new.xnb').write_bytes(b'XNB')
            b=inventory_tree(root);d=diff_inventories(a,b)
            self.assertEqual(d['changed'],['sample.obj'])
            self.assertEqual(d['added'],['new.xnb'])

    def test_design_status_never_claims_shader_parity(self):
        app={'mesh_materials':['Wood_Hull'],'textures':{'Red_Hull':{'data_uri':'data:x'}},
             'designs':[{'name':'Crimson','id':5,'swaps':{'Wood_Hull':'Red_Hull'}}]}
        result=audit_design(app)
        self.assertEqual(result['designs'][0]['status'],'candidate complete')
        self.assertFalse(result['game_shader_equivalence_verified'])

    def test_clock_fit_offset_and_drift(self):
        pairs=[{'capture_utc':'2026-11-17T12:00:00+00:00','video_seconds':1.5},
               {'capture_utc':'2026-11-17T12:01:00+00:00','video_seconds':61.56}]
        r=fit_clocks(pairs)
        self.assertAlmostEqual(r['video_offset_seconds'],1.5,places=4)
        self.assertAlmostEqual(r['drift_ms_per_minute'],60,places=3)

    def test_target_identity_does_not_guess(self):
        r=assign_target_ids([{'target_token':'real-npc-111','kind':'shot'}, {'kind':'shot'},
                             {'target_token':'real-npc-111','kind':'hit'}])
        self.assertEqual(r['ambiguous'],1)
        self.assertEqual(r['events'][0]['target_stable_id'],r['events'][2]['target_stable_id'])
        self.assertNotIn('real-npc-111',json.dumps(r))

    def test_tcp_continuity_retrans_gap_and_privacy(self):
        # Minimal Ethernet+IPv4+TCP packets in a PCAP with seq 100, 103 duplicate, 110.
        def packet(seq,payload):
            eth=b'\0'*12+b'\x08\x00'
            ip=bytes([0x45,0,0,40+len(payload),0,0,0,0,64,6,0,0,10,0,0,1,10,0,0,2])
            tcp=struct.pack('!HHII',1234,5555,seq,0)+bytes([0x50,0x18])+b'\0'*6
            return eth+ip+tcp+payload
        with tempfile.TemporaryDirectory() as tmp:
            f=Path(tmp)/'test.pcap'
            with f.open('wb') as out:
                out.write(b'\xd4\xc3\xb2\xa1'+struct.pack('<HHiIII',2,4,0,0,65535,1))
                for i,(seq,body) in enumerate([(100,b'abc'),(103,b'def'),(103,b'def'),(110,b'xyz')]):
                    raw=packet(seq,body);out.write(struct.pack('<IIII',10+i,0,len(raw),len(raw)));out.write(raw)
            report=analyze_stream_continuity(f)
            self.assertEqual(report['tcp_streams'][0]['retransmitted_segments'],1)
            self.assertEqual(report['tcp_streams'][0]['missing_sequence_bytes'],4)
            self.assertNotIn('10.0.0.1',json.dumps(report))

    def test_experiment_lifecycle_and_ci(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'research.sqlite3';conn=open_db(p)
            try:
                eid=add_experiment(conn,ship='Huracan',target='NPC',weapon='42pdr',ammunition='round',range_units=10,impact_angle_deg=15)
                add_observation(conn,eid,hp_before=1000,hp_after=900,source='video',hits=2)
                add_observation(conn,eid,hp_before=850,hp_after=730,source='video',hits=2)
                report=experiment_report(conn)
                self.assertEqual(report['observations'],2)
                self.assertAlmostEqual(report['groups'][0]['hp_per_hit_mean'],55)
                out=Path(tmp)/'evidence.zip';export_experiments(conn,out)
                with zipfile.ZipFile(out) as z:
                    self.assertIsNone(z.testzip())
                    self.assertIn('manifest.json',z.namelist())
            finally:conn.close()

    def test_experiment_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn=open_db(Path(tmp)/'db.sqlite3')
            try:
                eid=add_experiment(conn,ship='ship',target='target',weapon='gun',ammunition='round')
                with self.assertRaises(ValueError):add_observation(conn,eid,hp_before=10,hp_after=11)
            finally:conn.close()

    def test_maneuver_kinematics(self):
        r=evaluate_maneuver([{'time_s':0,'x':0,'y':0},{'time_s':1,'x':1,'y':0},{'time_s':2,'x':1,'y':1}])
        self.assertAlmostEqual(r['mean_speed_model_units_per_s'],1)
        self.assertAlmostEqual(abs(r['turns'][0]['turn_deg_per_s']),90)

    def test_sailing_and_projectile_are_not_game_certified(self):
        t=trajectory(initial_speed=10,launch_angle_deg=45)
        self.assertFalse(t['game_physics_verified'])
        r=compare_wind_profiles({'Ship A':{'base_index':1},'Ship B':{'base_index':2}},increment_degrees=90)
        self.assertEqual(len(r['samples']),5)
        self.assertAlmostEqual(r['samples'][0]['Ship B'],2*r['samples'][0]['Ship A'])

    def test_catalog_diff_and_provenance(self):
        conn=sqlite3.connect(':memory:');conn.row_factory=sqlite3.Row
        try:
            conn.execute('''CREATE TABLE records(dataset TEXT,source_root TEXT,external_id TEXT,name TEXT,
                            raw_json TEXT,sha256 TEXT,source_file TEXT,description TEXT)''')
            conn.executemany('INSERT INTO records VALUES(?,?,?,?,?,?,?,?)',[
                ('ShipsToPlay','Steam','9','Vasa','{}','sha1','ships.csv',''),
                ('ShipsToPlay','Game','9','Vasa','{}','sha2','ships.csv','')])
            a=dataset_snapshot(conn,'Steam');b=dataset_snapshot(conn,'Game')
            self.assertEqual(len(compare_catalogs(a,b)['changes']['changed']),1)
            self.assertEqual(len(record_provenance(conn,'Vasa')['matches']),2)
        finally:conn.close()

    def test_manifest_and_verifiable_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)/'source';base.mkdir()
            # Without real sources the readiness gate must fail rather than producing
            # an apparently releasable source archive.
            (base/'desktop_main.py').write_text('x=1',encoding='utf-8')
            self.assertEqual(make_manifest(base)['readiness'],'failed-source-checks')
            with self.assertRaises(ValueError):build_source_zip(base,Path(tmp)/'bad.zip')


if __name__=='__main__':unittest.main()

class AdvancedV435ExtraTests(unittest.TestCase):
    def test_model_vertex_declaration_diagnostics(self):
        import sys
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'engine'))
        from xnb_geometry import describe_vertex_declaration
        r=describe_vertex_declaration({'stride':24,'declaration':[
            {'format':2,'usage':0,'usage_index':0,'offset':0},
            {'format':1,'usage':2,'usage_index':0,'offset':12}]})
        self.assertEqual(r['elements'][1]['semantic'],'TextureCoordinate')
        self.assertFalse(r['shader_input_match_verified'])
        self.assertFalse(r['warnings'])

    def test_outfit_is_explicitly_hypothetical(self):
        from advanced_ship_config import outfit_hypothesis
        r=outfit_hypothesis({'armor':10},[
            {'stat':'armor','kind':'percent','value':10,'source':'manual'},
            {'stat':'armor','kind':'flat','value':2,'source':'manual'}])
        self.assertAlmostEqual(r['modeled_stats']['armor'],13)
        self.assertFalse(r['game_authoritative'])

    def test_mount_candidate_is_not_gun_slot(self):
        from advanced_ship_config import mount_candidates
        mesh={'vertices':[[0,0,0],[1,0,0],[0,1,0]],'triangles':[0,1,2],
              'groups':[{'name':'CannonMount01','first_triangle':0,'triangle_count':1}]}
        r=mount_candidates(mesh)
        self.assertEqual(r['candidate_groups'],1)
        self.assertIsNone(r['verified_fireable_cannon_slots'])

    def test_sail_association_needs_trials(self):
        from advanced_ship_config import sail_condition_observations
        with self.assertRaises(ValueError):sail_condition_observations([{'sail_health_pct':50,'observed_speed':5}])
        result=sail_condition_observations([{'sail_health_pct':25,'observed_speed':1},
                {'sail_health_pct':50,'observed_speed':3},{'sail_health_pct':100,'observed_speed':7}])
        self.assertIsNotNone(result['observed_speed_slope_per_sail_health_point'])
        self.assertIn('confound',result['warning'])

    def test_benchmark_is_cpu_only(self):
        from advanced_performance import benchmark_geometry
        report=benchmark_geometry(grid=3,ray_count=5)
        self.assertEqual(report['triangles'],18)
        self.assertIn('not a GPU',report['scope'])

    def test_video_transients_marked_for_review(self):
        from unittest.mock import patch
        from advanced_video import candidate_events
        class Dummy:
            returncode=0
            stderr=b''
            stdout=(bytes([0]*32*32)*3)+(bytes([255]*32*32))+(bytes([0]*32*32))
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'video.mp4';p.write_bytes(b'fixture')
            with patch('subprocess.run',return_value=Dummy()):
                report=candidate_events(p,ffmpeg='ffmpeg',width=32,height=32,fps=2.0)
        self.assertGreaterEqual(len(report['events']),1)
        self.assertTrue(report['events'][0]['requires_manual_review'])
        self.assertIn('false positives',report['notes'])
