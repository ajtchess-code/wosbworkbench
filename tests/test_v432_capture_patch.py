"""v4.3.2 recording/packaging QA; synthetic clips, no actual user gameplay."""
from __future__ import annotations
import json
import shutil
import struct
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace

from gameplay_capture import (
    detect_game_capture_interface, capture_traffic_health, preview_interface_traffic,
    GameplaySession, analyze_session, export_combat_evidence, find_video_tool,
)
from tests.test_v42_gameplay import write_test_pcap


class CapturePatchTests(unittest.TestCase):
    def test_adapter_resolution_uses_exact_route_and_not_first_adapter(self):
        guid='01234567-89ab-cdef-0123-456789abcdef'
        def mocked(cmd):
            if cmd[0]=='powershell.exe':
                return SimpleNamespace(stdout=json.dumps({'Alias':'Wi-Fi','Guid':guid}))
            return SimpleNamespace(stdout=(
                '1. \\Device\\NPF_{abcdefab-0000-0000-0000-000000000001} (Local Area Connection* 10)\n'
                '5. \\Device\\NPF_{'+guid.upper()+'} (Wi-Fi)\n'
                '11. \\Device\\NPF_{abcdefab-0000-0000-0000-000000000011} (Ethernet)'))
        info=detect_game_capture_interface(23771,runner=mocked,tshark='fake-tshark')
        self.assertEqual(info['interface'],'5')
        self.assertNotIn('IPAddress',str(info))

    def test_never_auto_selects_ambiguous_interfaces(self):
        def mocked(cmd):
            if cmd[0]=='powershell.exe':return SimpleNamespace(stdout='{"Alias":"Wi-Fi"}')
            return SimpleNamespace(stdout='1. adapter (Wi-Fi)\n2. adapter2 (Wi-Fi)')
        self.assertIsNone(detect_game_capture_interface(23771,runner=mocked,tshark='fake'))

    def test_preview_interface_validation(self):
        seen=[]
        def mocked(cmd):
            seen.extend(cmd)
            return SimpleNamespace(stdout='1\n2\n3\n')
        result=preview_interface_traffic('5',runner=mocked,tshark='fake')
        self.assertTrue(result['active']);self.assertEqual(result['game_frames'],3)
        self.assertIn('tcp port 23771',seen)
        with self.assertRaises(ValueError):preview_interface_traffic('5;rm -rf /',runner=mocked,tshark='fake')

    def test_capture_health_reads_packets_not_file_presence(self):
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td)
            (folder/'game-traffic.pcapng').write_bytes(bytes.fromhex('0a0d0d0a'))
            # Corrupt captures should fail loudly, not be marked successful.
            with self.assertRaises(ValueError):capture_traffic_health(folder)
            write_test_pcap(folder/'game-traffic.pcapng')
            state=capture_traffic_health(folder)
            self.assertEqual(state['status'],'active_game_traffic')
            self.assertEqual(state['game_payload_frames'],2)

    def test_per_target_marker_and_review_zero_packet_warning(self):
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td)
            session=GameplaySession(folder,interface='5',port=23771,capture_packets=False)
            # Start not needed: emulate user-mark semantics safely with no FFmpeg process.
            folder.mkdir(exist_ok=True);session.started=True;session.meta={'events_count':0,'fight':{'target_ship':'Merchant Grace'},
                'schema':1,'capture':{'video_launch_utc':'2026-11-17T20:38:51.000+00:00','port':23771}}
            from gameplay_capture import _write_atomic
            _write_atomic(folder/'session.json',session.meta)
            import time
            session._clock_anchor=time.perf_counter()
            session.mark('single-shot',target='Golden Bale',weapon='42-pound carronade',ammo='Round')
            session.mark('target-sunk',target='Prosperity')
            review=analyze_session(folder)
            self.assertEqual(review['events'][0]['target'],'Golden Bale')
            self.assertEqual(review['events'][1]['target'],'Prosperity')
            self.assertEqual(review['traffic']['capture_status'],'no_game_payloads')

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'Local FFmpeg unavailable')
    def test_compact_evidence_zip_and_source_privacy(self):
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td)
            video=folder/'gameplay.mp4'
            subprocess.run(['ffmpeg','-y','-loglevel','error','-f','lavfi',
               '-i','color=c=navy:s=640x360:d=3:r=10','-c:v','libx264','-pix_fmt','yuv420p',str(video)],
               check=True,timeout=30)
            meta={'schema':1,'session_id':'fixture-test','capture':{
              'video_launch_utc':'2026-11-17T20:38:51+00:00','video':'gameplay.mp4','port':23771},
              'fight':{'target_ship':'Ship A'}}
            (folder/'session.json').write_text(json.dumps(meta),encoding='utf-8')
            (folder/'events.jsonl').write_text(json.dumps({'utc':'2026-11-17T20:38:52+00:00',
                'kind':'single-shot','note':'target hp unreadable','target':'Ship A'})+'\n')
            analyze_session(folder)
            target=export_combat_evidence(folder,max_events=1,video_budget_mb=5)
            self.assertLess(target.stat().st_size,45*1024*1024)
            with zipfile.ZipFile(target) as z:
                self.assertIsNone(z.testzip())
                self.assertIn('Gameplay-Review.mp4',z.namelist())
                self.assertIn('Evidence-Manifest.json',z.namelist())
                self.assertIn('packet-timeline-video-seconds.csv',z.namelist())
                self.assertEqual(len([x for x in z.namelist() if x.startswith('Event-Frames/')]),2)
                self.assertNotIn('game-traffic.pcapng',z.namelist())
                self.assertEqual(json.loads(z.read('Evidence-Manifest.json'))['event_frames'][0]['target'],'Ship A')


if __name__=='__main__':unittest.main()
