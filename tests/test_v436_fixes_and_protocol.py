"""v4.3.6 regression tests: bug fixes found in review + Protocol Lab."""
import ast
import json
import random
import shutil
import sqlite3
import struct
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(1, str(ROOT / 'engine'))

import network_lab
import protocol_lab
import protocol_extract
import updater_main

T0 = 1_700_000_000.0
CLIENT, SERVER = [10, 0, 0, 2], [5, 6, 7, 8]
PORT = 23771


def tcp_frame(src, dst, sport, dport, seq, payload, flags=0x18):
    tcp = struct.pack('!HHIIBBHHH', sport, dport, seq, 0, 5 << 4, flags, 65535, 0, 0) + payload
    ip = struct.pack('!BBHHHBBH4s4s', 0x45, 0, 20 + len(tcp), 0, 0, 64, 6, 0, bytes(src), bytes(dst)) + tcp
    return b'\x00' * 12 + b'\x08\x00' + ip


def write_pcap(path, frames):
    with open(path, 'wb') as f:
        f.write(struct.pack('<IHHiIII', 0xa1b2c3d4, 2, 4, 0, 0, 65535, 1))
        for ts, fr in frames:
            f.write(struct.pack('<IIII', int(ts), int(round((ts % 1) * 1e6)), len(fr), len(fr))); f.write(fr)


def write_pcapng(path, frames):
    def block(kind, body):
        size = 12 + len(body); return struct.pack('<II', kind, size) + body + struct.pack('<I', size)
    out = block(0x0a0d0d0a, b'\x4d\x3c\x2b\x1a' + struct.pack('<HHq', 1, 0, -1)) + block(1, struct.pack('<HHI', 1, 0, 65535))
    for ts, fr in frames:
        ticks = int(ts * 1e6); pad = b'\x00' * ((-len(fr)) % 4)
        out += block(6, struct.pack('<IIIII', 0, ticks >> 32, ticks & 0xffffffff, len(fr), len(fr)) + fr + pad)
    Path(path).write_bytes(out)


def message(op, body):
    payload = bytes([op]) + body
    return struct.pack('<H', len(payload)) + payload


def synthetic_session(shots=(10, 20, 30, 40), seed=3, with_syn=True, skip_first_bytes=0):
    """Client sends 0x01 every 100 ms and 0x07 at each shot; server sends 0x20.

    Messages are split across TCP segments at random points, like real traffic.
    """
    rnd = random.Random(seed); frames = []; cseq = 1000; sseq = 9000; t = T0
    if with_syn:
        frames.append((t, tcp_frame(CLIENT, SERVER, 50000, PORT, cseq - 1, b'', flags=0x02)))
    pending = b''; first = True
    for i in range(400):
        t += 0.1
        data = message(0x01, struct.pack('<ff', rnd.random(), rnd.random()))
        if any(abs((t - T0) - s) < 0.06 for s in shots):
            data += message(0x07, struct.pack('<I', i))
        pending += data
        if first and skip_first_bytes:
            pending = pending[skip_first_bytes:]; cseq += skip_first_bytes; first = False
        cut = rnd.randint(1, len(pending)); seg, pending = pending[:cut], pending[cut:]
        frames.append((t, tcp_frame(CLIENT, SERVER, 50000, PORT, cseq, seg))); cseq += len(seg)
        if i % 3 == 0:
            body = message(0x20, bytes(rnd.randrange(256) for _ in range(rnd.randint(4, 30))))
            frames.append((t + 0.01, tcp_frame(SERVER, CLIENT, PORT, 50000, sseq, body))); sseq += len(body)
    if pending:
        frames.append((t + 0.05, tcp_frame(CLIENT, SERVER, 50000, PORT, cseq, pending)))
    markers = [{'kind': 'broadside', 'utc': T0 + s} for s in shots]
    return frames, markers


class UpdaterWaitTests(unittest.TestCase):
    def test_posix_wait_returns_for_dead_process(self):
        with mock.patch.object(updater_main.os, 'name', 'posix'), \
             mock.patch.object(updater_main, '_pid_alive_posix', return_value=False):
            updater_main.wait_for_exit(424242, timeout=1, settle=0)

    def test_windows_never_uses_os_kill(self):
        """os.kill(pid, 0) is CTRL_C_EVENT on Windows; the updater must wait on a handle."""
        with mock.patch.object(updater_main.os, 'name', 'nt'), \
             mock.patch.object(updater_main, '_wait_windows', return_value=True) as waited, \
             mock.patch.object(updater_main.os, 'kill', side_effect=AssertionError('os.kill used')):
            updater_main.wait_for_exit(1234, timeout=5, settle=0)
        waited.assert_called_once_with(1234, 5)

    def test_windows_timeout_raises(self):
        with mock.patch.object(updater_main.os, 'name', 'nt'), \
             mock.patch.object(updater_main, '_wait_windows', return_value=False):
            with self.assertRaises(TimeoutError):
                updater_main.wait_for_exit(1234, timeout=1, settle=0)


class CaptureFixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp)

    def test_start_capture_writes_exact_path_without_ring_buffer(self):
        with mock.patch.object(network_lab.subprocess, 'Popen') as popen:
            network_lab.start_capture('3', self.tmp / 'x.pcapng', tshark='/fake/tshark')
        cmd = popen.call_args[0][0]
        self.assertNotIn('-b', cmd, 'ring buffer renames the file, so the UI path never existed')
        self.assertEqual(cmd[cmd.index('-w') + 1], str((self.tmp / 'x.pcapng').resolve()))
        self.assertIn('-a', cmd)

    def test_truncated_final_packet_is_tolerated(self):
        frames, _ = synthetic_session()
        for writer, name in ((write_pcap, 'a.pcap'), (write_pcapng, 'a.pcapng')):
            path = self.tmp / name; writer(path, frames)
            full = sum(1 for _ in protocol_lab._open_packets(path))
            path.write_bytes(path.read_bytes()[:-9])   # tool killed mid-write
            cut = sum(1 for _ in protocol_lab._open_packets(path))
            self.assertEqual(cut, full - 1, name)

    def test_empty_garbage_still_rejected(self):
        path = self.tmp / 'bad.pcap'
        path.write_bytes(b'\xd4\xc3\xb2\xa1' + b'\x00' * 10)
        with self.assertRaises(ValueError):
            list(network_lab.iter_pcap(path))

    def test_naive_event_time_is_utc(self):
        summary = {'timeline': [{'utc': '2026-01-01T12:00:00+00:00', 'packets': 5, 'bytes': 50}]}
        events = [{'event_utc': '2026-01-01T12:00:01', 'category': 'hit', 'note': ''}]
        self.assertEqual(network_lab.event_correlations(summary, events)[0]['packets'], 5)

    def test_advanced_network_accepts_pcapng(self):
        import advanced_network
        frames, _ = synthetic_session()
        path = self.tmp / 's.pcapng'; write_pcapng(path, frames)
        result = advanced_network.analyze_stream_continuity(path)
        self.assertGreater(len(result['tcp_streams']), 0)

    def test_gameplay_analysis_uses_saved_offset(self):
        import gameplay_capture
        folder = self.tmp / 'session'; folder.mkdir()
        (folder / 'session.json').write_text(json.dumps({'schema': 1, 'capture': {
            'video_launch_utc': '2026-01-01T12:00:00+00:00', 'port': PORT, 'video_offset_seconds': 2.5}}), encoding='utf-8')
        (folder / 'events.jsonl').write_text(json.dumps({'utc': '2026-01-01T12:00:10+00:00', 'kind': 'hit', 'note': ''}) + '\n', encoding='utf-8')
        result = gameplay_capture.analyze_session(folder)
        self.assertEqual(result['video_offset_seconds'], 2.5)
        self.assertAlmostEqual(result['events'][0]['video_seconds_approx'], 12.5)


class WikiServerFixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import wiki_server
        cls.tmp = Path(tempfile.mkdtemp())
        db = cls.tmp / 'odd #name%.sqlite3'           # characters that broke the raw file: URI
        shutil.copy2(ROOT / 'Starter-Catalog.sqlite3', db)
        from contextlib import closing
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.execute("INSERT INTO records(dataset,source_root,external_id,name,raw_json,sha256,imported_utc) "
                         "VALUES('ShipsToPlay','Game','9999','Odd',?,'x','now')",
                         (json.dumps({'ID': 9999, 'EnglishName': 'Odd ship', 'ShipRank': 'VII', 'Health': 'n/a'}),))
            conn.execute("INSERT INTO records(dataset,source_root,external_id,name,raw_json,sha256,imported_utc) "
                         "VALUES('Cannons','Game','x1','Gun',?,'x','now')",
                         (json.dumps({'ID': 'x1', 'EnglishName': 'Gun', 'EnglishDescription': None}),))
        cls.server, cls.url = wiki_server.serve(db, open_browser=False)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); shutil.rmtree(cls.tmp)

    def get(self, path, host=None):
        req = urllib.request.Request(self.url.rstrip('/') + path)
        if host:
            req.add_header('Host', host)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read().decode('utf-8')
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode('utf-8', 'replace')

    def test_pages_survive_odd_catalog_values(self):
        for path in ('/', '/shipyard', '/ship/9999', '/weapons', '/compare', '/shipyard-atlas'):
            status, _ = self.get(path)
            self.assertEqual(status, 200, path)

    def test_compare_bars_use_data_percent_not_inline_style(self):
        _, body = self.get('/compare')
        self.assertIn('data-percent=', body)
        self.assertNotIn('style="width', body)

    def test_search_treats_wildcards_literally(self):
        status, body = self.get('/articles?q=%25%25%25zz_')
        self.assertEqual(status, 200)
        self.assertIn('0 articles matched', body)

    def test_foreign_host_rejected(self):
        status, _ = self.get('/', host='evil.example:80')
        self.assertEqual(status, 403)


class UiSourceTests(unittest.TestCase):
    def test_no_hardcoded_wiki_tab_index(self):
        src = (ROOT / 'workbench_ui.py').read_text(encoding='utf-8')
        self.assertNotIn('self.tabs.select(3)', src)
        self.assertNotIn('self.tabs.select(4)', src)
        self.assertIn("select_named('Wiki editor')", src)

    def test_poll_loop_reschedules_in_finally(self):
        tree = ast.parse((ROOT / 'workbench_ui.py').read_text(encoding='utf-8'))
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == '_poll_events')
        tries = [n for n in ast.walk(fn) if isinstance(n, ast.Try)]
        self.assertTrue(any('after' in ast.unparse(t.finalbody) for t in tries))

    def test_hp_bar_lambda_binds_message(self):
        src = (ROOT / 'hp_bar_ui.py').read_text(encoding='utf-8')
        self.assertNotIn("lambda:status.set('Could not extract frame: '+str(exc))", src)


class ImportGuardTests(unittest.TestCase):
    def test_non_dict_xnb_headers_skipped(self):
        import zipfile
        from workbench_db import CatalogDB
        from workbench_import import Importer
        tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, tmp)
        archive = tmp / 'r.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('Scan1/Analysis/Client/XNBHeaders.json',
                       json.dumps([1, 'x', {'source': 'Data/Models/Ships/Ship_1_A.xnb'}]))
            z.writestr('Scan1/AI-Data/Asset_Inventory.jsonl', '[1]\n"Data/Models/x"\n')
        db = CatalogDB(tmp / 'db.sqlite3'); self.addCleanup(db.close)
        Importer(db).catalog_zip(archive)
        n = db.conn.execute("SELECT count(*) FROM records WHERE dataset='ModelAssetCandidates'").fetchone()[0]
        self.assertEqual(n, 1)


class ProtocolLabTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp)

    def analyze(self, **kw):
        frames, markers = synthetic_session(**kw)
        path = self.tmp / 'c.pcapng'; write_pcapng(path, frames)
        return protocol_lab.analyze([path], server_port=PORT, markers=markers), path

    def test_detects_framing_and_message_types(self):
        result, _ = self.analyze()
        f = result['framing']
        self.assertEqual((f['offset'], f['size'], f['endian'], f['inclusive']), (0, 2, 'little', False))
        types = {t['type_id']: t for t in result['catalog']['types']}
        self.assertEqual(types['client:0x1']['count'], 400)
        self.assertTrue(types['client:0x1']['fixed_size'])
        self.assertIn('client:0x7', types)
        self.assertIn('server:0x20', types)
        self.assertEqual(result['unframed_tail_bytes'], 0)

    def test_fire_message_associated_with_broadside_markers(self):
        result, _ = self.analyze()
        best = [a for a in result['marker_associations'] if a['marker_kind'] == 'broadside']
        self.assertEqual(best[0]['type_id'], 'client:0x7')

    def test_resyncs_when_capture_starts_mid_message(self):
        result, _ = self.analyze(with_syn=False, skip_first_bytes=5)
        types = {t['type_id']: t for t in result['catalog']['types']}
        self.assertGreaterEqual(types['client:0x1']['count'], 398)

    def test_message_log_roundtrip(self):
        _, path = self.analyze()
        summary = protocol_lab.export_message_log([path], self.tmp / 'log.jsonl', server_port=PORT)
        lines = (self.tmp / 'log.jsonl').read_text(encoding='utf-8').splitlines()
        self.assertEqual(len(lines) - 1, summary['messages'])
        first = json.loads(lines[1])
        raw = bytes.fromhex(first['hex'])
        self.assertEqual(struct.unpack('<H', raw[:2])[0] + 2, len(raw))

    def test_encrypted_looking_stream_warns(self):
        rnd = random.Random(1); frames = []; seq = 1
        for i in range(300):
            data = bytes(rnd.randrange(256) for _ in range(200))
            frames.append((T0 + i * 0.05, tcp_frame(CLIENT, SERVER, 50000, PORT, seq, data))); seq += len(data)
        path = self.tmp / 'enc.pcapng'; write_pcapng(path, frames)
        result = protocol_lab.analyze([path], server_port=PORT)
        self.assertIn('warning', result)

    def test_reports_written(self):
        result, _ = self.analyze()
        out = protocol_lab.write_reports(result, self.tmp / 'out')
        self.assertTrue(out.is_file())
        self.assertTrue((self.tmp / 'out' / 'Message-Types.csv').is_file())

    def test_definitions_match_observed_opcodes(self):
        result, _ = self.analyze()
        defs = {'opcode_enums': [{'name': 'Net.ClientOpcode', 'members': {'Move': 1, 'Fire': 7, 'Chat': 99}}]}
        match = protocol_lab.match_definitions(result['catalog'], defs)
        self.assertEqual(match[0]['named']['0x7'], 'Fire')


class ProtocolExtractTests(unittest.TestCase):
    def test_signature_decoding(self):
        self.assertEqual(protocol_extract.field_type(bytes([0x06, 0x08])), 'int32')
        self.assertEqual(protocol_extract.field_type(bytes([0x06, 0x1d, 0x05])), 'uint8[]')
        self.assertEqual(protocol_extract.field_type(bytes([0x06, 0x12, 0x09]), resolve=lambda t: 'Vec3'), 'Vec3')
        # instance void Write(float32)
        self.assertEqual(protocol_extract.first_param_type(bytes([0x20, 0x01, 0x01, 0x0c])), 'float32')

    def test_wire_op_mapping(self):
        self.assertEqual(protocol_extract.wire_op('System.IO.BinaryReader', 'ReadSingle')['type'], 'float32')
        self.assertEqual(protocol_extract.wire_op('System.IO.BinaryWriter', 'Write', 'int16')['type'], 'int16')
        self.assertIsNone(protocol_extract.wire_op('Game.Ship', 'Update'))

    def test_classification_and_enums(self):
        io = [{'op': 'read', 'type': 'int32', 'call': 'BinaryReader.ReadInt32'}] * 3
        types = [{'name': f'Msg{i}', 'namespace': 'Net', 'base': 'Net.MessageBase', 'fields': [],
                  'methods': [{'name': 'Deserialize', 'io': io}]} for i in range(4)]
        types.append({'name': 'ShipRenderer', 'namespace': 'Gfx', 'base': 'Object', 'fields': [], 'methods': []})
        found = protocol_extract.classify_message_types(types)
        self.assertEqual({m['type'] for m in found}, {f'Net.Msg{i}' for i in range(4)})
        enums = protocol_extract.opcode_enums([{'name': 'PacketType', 'namespace': 'Net', 'members': {'A': 1, 'B': 2}},
                                               {'name': 'Color', 'namespace': 'Gfx', 'members': {'Red': 1}}])
        self.assertEqual([e['name'] for e in enums], ['Net.PacketType'])

    def test_build_diff(self):
        old = {'message_types': [{'type': 'Net.Fire', 'fields': [{'name': 'a', 'type': 'int32'}], 'serializers': []}],
               'opcode_enums': [{'name': 'Op', 'members': {'Fire': 7}}]}
        new = {'message_types': [{'type': 'Net.Fire', 'fields': [{'name': 'a', 'type': 'int64'}], 'serializers': []},
                                 {'type': 'Net.Hit', 'fields': [], 'serializers': []}],
               'opcode_enums': [{'name': 'Op', 'members': {'Fire': 8, 'Hit': 9}}]}
        d = protocol_extract.diff_definitions(old, new)
        self.assertEqual(d['added_types'], ['Net.Hit'])
        self.assertTrue(d['changed_types'][0]['fields_changed'])
        self.assertEqual(d['opcode_enum_changes'][0]['renumbered'], {'Fire': [7, 8]})


if __name__ == '__main__':
    unittest.main()
