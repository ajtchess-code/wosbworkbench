"""v4.2 capture, evidence and visual QA regression tests (no game/network tools required)."""
import json
import socket
import struct
import tempfile
import unittest
import zipfile
from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace

from damage_evidence import clean_observation,aggregate_observations,generate_trial_dashboard,write_trial_template
from gameplay_capture import (game_process_connection,game_traffic_bins,analyze_session,
    export_sanitized_review,GameplaySession,ALLOWED_MARKERS,load_events,load_session)
from visual_reference import compare_screenshots
from PIL import Image


def tcp_payload(payload=b'\x2b\x00'+b'x'*43, sport=55555,dport=23771,seq=42):
    tcp=struct.pack('!HHIIBBHHH',sport,dport,seq,0,5<<4,0x18,0,0,0)+payload
    ip=bytes([0x45,0])+struct.pack('!H',20+len(tcp))+b'\x00'*5+bytes([6])+b'\x00\x00'+socket.inet_aton('192.0.2.5')+socket.inet_aton('198.51.100.7')
    return b'\x00'*12+b'\x08\x00'+ip+tcp


def write_test_pcap(out):
    raw=tcp_payload()
    out.write_bytes(b'\xd4\xc3\xb2\xa1'+struct.pack('<HHiIII',2,4,0,0,65535,1)+
      struct.pack('<IIII',1700000000,123456,len(raw),len(raw))+raw+
      struct.pack('<IIII',1700000000,123456,len(raw),len(raw))+raw) # deliberate retransmission


class SessionTests(unittest.TestCase):
    def test_ownership_check_scrubs_addresses(self):
        runner=lambda args:SimpleNamespace(stdout='{"PID":10476,"Name":"WorldOfSeaBattleClient","Port":23771,"Address":"sensitive"}')
        result=game_process_connection(23771,runner=runner)
        self.assertTrue(result['confirmed']);self.assertEqual(result['pid'],10476)
        self.assertNotIn('Address',result)

    def test_unsafe_ports_and_interface(self):
        with self.assertRaises(ValueError):GameplaySession('/tmp/fake',port=-2)
        with self.assertRaises(ValueError):GameplaySession('/tmp/fake',interface='1; rm -rf /')
        self.assertIn('single-shot',ALLOWED_MARKERS)

    def test_packet_timing_and_dedup(self):
        with tempfile.TemporaryDirectory() as td:
            f=Path(td)/'game-traffic.pcap';write_test_pcap(f)
            result=game_traffic_bins([f])
            self.assertEqual(result['segments']['client_payload_segments'],1)
            self.assertEqual(result['segments']['duplicates_skipped'],1)
            self.assertEqual(result['timeline'][0]['client_45_bytes'],1)
            self.assertEqual(result['timeline'][0]['prefix_matches'],1)
            self.assertNotIn('198.51.100',json.dumps(result))

    def test_review_session_zip_private(self):
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td);write_test_pcap(folder/'game-traffic.pcapng') # intentionally PCAP data with pcapng suffix; uses magic detection
            # replace with actual .pcap & rename matcher requires *.pcapng
            t='2023-11-14T22:13:19.123+00:00'
            meta={'schema':1,'capture':{'video_launch_utc':t,'port':23771,'game_connection_confirmed':True},'status':'stopped'}
            (folder/'session.json').write_text(json.dumps(meta))
            (folder/'events.jsonl').write_text(json.dumps({'utc':t,'kind':'single-shot','note':'target HP 300 to 280'})+'\n')
            data=analyze_session(folder)
            self.assertEqual(data['recorded_events'],1)
            self.assertGreaterEqual(data['events'][0]['packet_window']['client_segments'],1)
            z=export_sanitized_review(folder)
            with zipfile.ZipFile(z) as archive:
                self.assertNotIn('game-traffic.pcapng',archive.namelist())
                self.assertNotIn('gameplay.mp4',archive.namelist())
                self.assertNotIn('192.0.2',archive.read('review.json').decode())

    def test_no_packet_review(self):
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td);(folder/'session.json').write_text(json.dumps({'schema':1,'capture':{'video_launch_utc':'2026-11-17T18:00:00+00:00','port':23771}}))
            data=analyze_session(folder)
            self.assertEqual(data['recorded_events'],0)
            self.assertEqual(data['traffic']['timeline'],[])

class DamageTests(unittest.TestCase):
    def test_strict_matching_shot_types_and_min_count(self):
        row={'target_ship':'Merchant Grace','weapon':'42-pound carronade','ammo':'round','shot_type':'single',
             'target_armor_region':'stern','range_m':'100','impact_angle_deg':'8','observed_hp_damage':'40'}
        records=[clean_observation(row) for _ in range(2)]
        a=aggregate_observations(records)
        self.assertEqual(a[0]['status'],'insufficient_samples')
        self.assertIsNone(a[0]['mean_hp'])
        records.append(clean_observation({**row,'observed_hp_damage':'46'}))
        records.append(clean_observation({**row,'shot_type':'broadside','observed_hp_damage':'300'}))
        a=aggregate_observations(records)
        self.assertEqual(len(a),2)
        self.assertEqual(next(x for x in a if x['shot_type']=='single')['mean_hp'],42)
        self.assertIsNone(next(x for x in a if x['shot_type']=='broadside')['mean_hp'])

    def test_invalid_trials_and_dashboard(self):
        self.assertIsNone(clean_observation({'observed_hp_damage':'nan','range_m':'2','impact_angle_deg':'30'}))
        with tempfile.TemporaryDirectory() as td:
            csvpath=write_trial_template(Path(td)/'shots.csv')
            with csvpath.open('a',encoding='utf-8') as f:
                f.write('trial1,,Huracan,Merchant Grace,42 pound carronade,Round shot,single,stern,100,30,400,360,40,game1,test\n')
            p=generate_trial_dashboard(csvpath,Path(td)/'atlas.html')
            self.assertIn('Measured Damage Atlas',p.read_text())
            self.assertIn('insufficient_samples',p.read_text())

    def test_screenshot_comparison(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);Image.new('RGB',(10,10),(100,100,100)).save(p/'game.png')
            Image.new('RGB',(10,10),(100,50,50)).save(p/'viewer.png')
            report=compare_screenshots(p/'game.png',p/'viewer.png',p/'diff.png')
            self.assertFalse(report['resized_workbench']);self.assertTrue((p/'diff.png').is_file())

if __name__=='__main__':unittest.main()
