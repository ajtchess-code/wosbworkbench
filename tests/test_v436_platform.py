"""v4.3.6 platform tests: settings, detection, jobs, wiki engine, schema, watcher,
datamining, signed updates, self-test and a headless UI smoke run."""
import json
import os
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(1, str(ROOT / 'engine')); sys.path.insert(2, str(ROOT / 'tests'))

import app_settings
import datamine
import game_watcher
import install_detect
import jobs
import protocol_schema
import update_signing
import wiki_engine
from offline_updates import apply_verified_update, inspect_update_zip


class TempDir(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp, True)


class SettingsTests(TempDir):
    def test_defaults_merge_and_persist(self):
        path = self.tmp / 's.json'
        path.write_text(json.dumps({'ui': {'theme': 'light'}, 'future_key': 1}), encoding='utf-8')
        s = app_settings.Settings(path)
        self.assertEqual(s.get('ui.theme'), 'light')
        self.assertEqual(s.get('capture.port'), 23771)            # default filled in
        game = self.tmp / 'Game'; game.mkdir()
        s.set('installs.game', str(game))
        again = app_settings.Settings(path)
        self.assertEqual(again.game_roots(), [str(game)])
        self.assertEqual(again.get('future_key'), 1)               # unknown keys preserved

    def test_corrupt_file_falls_back_to_defaults(self):
        path = self.tmp / 's.json'; path.write_text('{not json', encoding='utf-8')
        self.assertFalse(app_settings.Settings(path).get('first_run_complete'))


class DetectionTests(unittest.TestCase):
    VDF = '''"libraryfolders" { "0" { "path" "C:\\\\Program Files (x86)\\\\Steam" } "1" { "path" "D:\\\\SteamLibrary" "apps" { "1" "2" } } }'''
    ACF = '"AppState" { "appid" "123" "name" "World of Sea Battle" "installdir" "World of Sea Battle" }'

    def test_parse_vdf(self):
        data = install_detect.parse_vdf(self.VDF)
        self.assertEqual(data['libraryfolders']['1']['path'], 'D:\\SteamLibrary')

    def test_detect_with_fake_filesystem(self):
        steam = r'C:\Program Files (x86)\Steam'
        lib2 = r'D:\SteamLibrary'
        files = {
            str(Path(steam) / 'steamapps' / 'libraryfolders.vdf'): self.VDF,
            str(Path(lib2) / 'steamapps' / 'appmanifest_123.acf'): self.ACF,
        }
        game_dir = str(Path(lib2) / 'steamapps' / 'common' / 'World of Sea Battle')
        existing = {steam, game_dir, r'C:\Games\Wosb Launcher'}
        listing = {str(Path(lib2) / 'steamapps'): ['appmanifest_123.acf', 'common'],
                   str(Path(lib2) / 'steamapps' / 'common'): ['World of Sea Battle'],
                   str(Path(steam) / 'steamapps'): [], str(Path(steam) / 'steamapps' / 'common'): []}

        def read_text(p):
            if str(p) in files:
                return files[str(p)]
            raise OSError(p)

        def listdir(p):
            if str(p) in listing:
                return listing[str(p)]
            raise OSError(p)
        found = install_detect.detect_installs(registry=[('steam', 'SteamPath', steam)],
                                               exists=lambda p: str(p) in existing, listdir=listdir, read_text=read_text)
        self.assertEqual(found['steam'], [game_dir])
        self.assertEqual(found['launcher'], [r'C:\Games\Wosb Launcher'])


class JobTests(unittest.TestCase):
    def test_progress_done_failed_cancelled(self):
        m = jobs.JobManager()
        done = []
        ok = m.submit('ok', lambda ctx: (ctx.progress(0.5, 'half'), ctx.log('line'), 7)[-1], on_done=done.append)
        bad = m.submit('bad', lambda ctx: 1 / 0)

        def slow(ctx):
            while not ctx.cancelled:
                time.sleep(0.01)
            ctx.check()
        stop = m.submit('slow', slow)
        for j in (ok, bad):
            m.wait(j, 5)
        self.assertTrue(m.cancel(stop.id)); m.wait(stop, 5)
        self.assertEqual((ok.status, ok.result, done), ('done', 7, [7]))
        self.assertEqual(bad.status, 'failed'); self.assertIn('ZeroDivisionError', bad.error)
        self.assertEqual(stop.status, 'cancelled')
        self.assertEqual(len(m.snapshot()), 3)


class WikiEngineTests(TempDir):
    def db(self):
        from workbench_db import CatalogDB
        db = CatalogDB(self.tmp / 'w.sqlite3'); self.addCleanup(db.close)
        return db

    def test_search_links_tags_revisions_drafts(self):
        db = self.db()
        a = db.upsert_article('cannons', 'Cannons', 'Guides', '# Cannons\nUse [[Round Shot]] here.\nTags: weapons, Combat')
        b = db.upsert_article('round-shot', 'Round Shot', 'Guides', 'Heavy iron balls; see [[Cannons]].')
        db.conn.commit()
        self.assertEqual(wiki_engine.search(db.conn, 'iron')[0]['slug'], 'round-shot')
        self.assertEqual([r['slug'] for r in wiki_engine.backlinks(db.conn, b)], ['cannons'])
        self.assertEqual(wiki_engine.article_tags(db.conn, a), ['combat', 'weapons'])
        db.save_article(a, 'Cannons', 'Guides', 'v2', 'draft')
        db.save_article(a, 'Cannons', 'Guides', 'v3', 'draft')
        revs = wiki_engine.revisions(db.conn, a)
        self.assertEqual(len(revs), 2)
        oldest = revs[-1][0]
        db.restore_revision(a, oldest)
        self.assertIn('Round Shot', db.article(a)['body'])
        wiki_engine.save_draft(db.conn, a, 'T', 'S', 'draft body', 'draft')
        self.assertEqual(wiki_engine.get_draft(db.conn, a)['body'], 'draft body')
        db.save_article(a, 'Cannons', 'Guides', 'final', 'draft')
        self.assertIsNone(wiki_engine.get_draft(db.conn, a))          # saving clears the draft

    def test_renderer_is_safe(self):
        html = wiki_engine.render_markdown('<img src=x onerror=alert(1)> [x](javascript:alert(1)) [ok](https://a.b/c) **b** `c`')
        self.assertNotIn('<img', html); self.assertNotIn('href="javascript', html)
        self.assertIn('href="https://a.b/c"', html); self.assertIn('<strong>b</strong>', html); self.assertIn('<code>c</code>', html)

    def test_markdown_features(self):
        html = wiki_engine.render_markdown('## H\n| a | b |\n|---|---|\n| 1 | 2 |\n1. one\n- [x] done\n> quote\n---\n```py\nx<1\n```')
        for fragment in ('<h3 id="h">', '<table>', '<ol>', '☑', '<blockquote>', '<hr>', 'x&lt;1'):
            self.assertIn(fragment, html)

    def test_web_codex_new_routes(self):
        import urllib.request
        import wiki_server
        db = self.db()
        db.upsert_article('alpha', 'Alpha', 'Guides', 'Links to [[Beta]]\nTags: demo'); db.upsert_article('beta', 'Beta', 'Guides', 'Body')
        db.conn.commit()
        server, url = wiki_server.serve(db.path, open_browser=False)
        try:
            for path, needle in (('/tag/demo', 'Alpha'), ('/recent', 'Beta'), ('/article/beta', 'Pages linking here'),
                                 ('/articles?q=body', '<mark>')):
                with urllib.request.urlopen(url.rstrip('/') + path, timeout=10) as r:
                    self.assertIn(needle, r.read().decode('utf-8'), path)
        finally:
            server.shutdown(); server.server_close()


class SchemaTests(TempDir):
    def test_decode_types(self):
        body = (struct.pack('<I', 7) + bytes([0x96, 0x01]) + bytes([3]) + b'abc' + struct.pack('>H', 258)
                + struct.pack('<f', 1.5) + b'\x01\x02')
        fields = [{'name': 'id', 'type': 'uint32'}, {'name': 'v', 'type': 'varint'}, {'name': 's', 'type': 'dotnet_string'},
                  {'name': 'b', 'type': 'uint16_be'}, {'name': 'f', 'type': 'float32'}, {'name': 'r', 'type': 'rest'}]
        out, err = protocol_schema.decode_fields(body, fields)
        self.assertIsNone(err)
        self.assertEqual(out, {'id': 7, 'v': 150, 's': 'abc', 'b': 258, 'f': 1.5, 'r': '0102'})
        out, err = protocol_schema.decode_fields(b'\x01', [{'name': 'x', 'type': 'uint32'}])
        self.assertIn('needs 4 bytes', err)

    def test_inference_and_suggestions(self):
        bodies = [struct.pack('<IfB', i, i * 0.5 + 1, 2) for i in range(1, 40)]
        kinds = [h['kind'] for h in protocol_schema.infer_fields(bodies)]
        self.assertEqual(kinds[:2], ['counter_u32', 'float32'])
        self.assertEqual(protocol_schema.suggest_fields(protocol_schema.infer_fields(bodies))[-1]['type'], 'rest')

    def test_decode_export_and_tool_files(self):
        import protocol_lab
        import test_v436_fixes_and_protocol as t
        frames, _ = t.synthetic_session()
        cap = self.tmp / 'c.pcapng'; t.write_pcapng(cap, frames)
        protocol_lab.export_message_log([cap], self.tmp / 'log.jsonl', server_port=t.PORT)
        schema = protocol_schema.new_schema({'offset': 0, 'size': 2, 'endian': 'little', 'inclusive': False}, 1)
        schema['types']['client:0x7'] = {'name': 'Fire', 'fields': [{'name': 'shot_id', 'type': 'uint32'}]}
        summary = protocol_schema.export_decoded(self.tmp / 'log.jsonl', schema, self.tmp / 'dec')
        self.assertEqual(summary['by_type']['Fire'], 4)
        with closing(sqlite3.connect(self.tmp / 'dec' / 'Decoded-Messages.sqlite3')) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM msg_Fire').fetchone()[0], 4)
        files = protocol_schema.export_tools(schema, self.tmp / 'tools')
        lua = Path(files[0]).read_text(encoding='utf-8')
        self.assertIn('DissectorTable.get("tcp.port"):add(PORT, p)', lua); self.assertIn('"Fire"', lua)
        self.assertIn('struct Fire', Path(files[1]).read_text(encoding='utf-8'))
        self.assertIn('fire:', Path(files[2]).read_text(encoding='utf-8'))


class WatcherTests(TempDir):
    def test_capture_lifecycle(self):
        events = []; state = {'conn': []}
        started = []; stopped = []

        class Proc:
            def poll(self):
                return None
        w = game_watcher.GameWatcher(self.tmp, find_connections=lambda: state['conn'], pick_interface=lambda port: '3',
                                     start=lambda iface, path, port: (started.append((iface, path, port)), Proc())[1],
                                     stop=lambda proc: stopped.append(proc), analyze=lambda folder: {'messages': 9},
                                     on_event=lambda kind, info: events.append(kind), grace_polls=2)
        self.assertEqual(w.tick(), 'idle')
        state['conn'] = [{'port': 23771, 'confirmed': True}]
        self.assertEqual(w.tick(), 'capturing'); self.assertEqual(started[0][0], '3')
        session = w.session
        self.assertEqual(json.loads((session / 'session.json').read_text(encoding='utf-8'))['capture']['port'], 23771)
        state['conn'] = []
        self.assertEqual(w.tick(), 'capturing')          # within the grace period
        self.assertEqual(w.tick(), 'idle')               # stopped and analyzed
        self.assertEqual(events, ['capture-started', 'capture-stopped', 'analysis-finished'])
        self.assertEqual(len(stopped), 1)
        self.assertEqual(json.loads((session / 'session.json').read_text(encoding='utf-8'))['stop_reason'], 'game disconnected')

    def test_no_adapter_reports_error(self):
        events = []
        w = game_watcher.GameWatcher(self.tmp, find_connections=lambda: [{'port': 1}], pick_interface=lambda p: None,
                                     start=lambda *a: None, stop=lambda p: None, analyze=lambda f: {},
                                     on_event=lambda kind, info: events.append(kind))
        self.assertEqual(w.tick(), 'idle'); self.assertEqual(events, ['error'])


def make_wave_bank(entries):
    """Write a minimal XACT (XNA 4) wave bank: [(name, codec_tag, channels, rate, bits16, payload)]."""
    header = 12 + 5 * 8
    bank = 96; meta = 24 * len(entries); names = 64 * len(entries)
    bank_off = header; meta_off = bank_off + bank; names_off = meta_off + meta; wave_off = names_off + names
    data_blob = b''; metas = b''; name_blob = b''
    for name, tag, ch, rate, bits16, payload in entries:
        fmt = tag | (ch << 2) | (rate << 5) | (0 << 23) | ((1 if bits16 else 0) << 31)
        metas += struct.pack('<IIIIII', 0, fmt, len(data_blob), len(payload), 0, 0)
        data_blob += payload
        name_blob += name.encode().ljust(64, b'\0')
    out = b'WBND' + struct.pack('<II', 46, 44)
    for off, length in ((bank_off, bank), (meta_off, meta), (0, 0), (names_off, names), (wave_off, len(data_blob))):
        out += struct.pack('<II', off, length)
    out += struct.pack('<II', 0x00010000, len(entries)) + b'TestBank'.ljust(64, b'\0') + struct.pack('<IIIIQ', 24, 64, 4, 0, 0)
    out = out.ljust(meta_off, b'\0') + metas + name_blob + data_blob
    return out


class DatamineTests(TempDir):
    def test_coverage_report_finds_gaps_and_ledger(self):
        game = self.tmp / 'game'; (game / 'CommonData').mkdir(parents=True)
        (game / 'CommonData' / 'a.xnb').write_bytes(b'XNBw' + b'\0' * 100)
        (game / 'CommonData' / 'mystery.qzx').write_bytes(os.urandom(70 * 1024))
        (game / 'native.dll').write_bytes(b'MZ' + b'\0' * 200)
        ledger = self.tmp / 'ledger.jsonl'
        ledger.write_text(json.dumps({'status': 'decoded'}) + '\n' + json.dumps({'status': 'failed', 'reason': 'custom reader'}) + '\n')
        report = datamine.coverage_report(game, ledger=ledger)
        exts = {r['extension']: r for r in report['by_extension']}
        self.assertEqual(exts['.qzx']['handler'], 'NONE — not decoded yet')
        self.assertTrue(any(g['extension'] == '.qzx' and 'entropy' in g['hint'] for g in report['gaps']))
        self.assertEqual(report['xnb_ledger'], {'decoded': 1, 'failed': 1})
        self.assertEqual(report['native_binaries'], 1)

    def test_version_tracking_and_changes_page(self):
        game = self.tmp / 'game'; game.mkdir()
        (game / 'Common.dll').write_bytes(b'v1')
        history = self.tmp / 'versions' / 'history.json'
        new, prev, cur = datamine.track_version(game, history)
        self.assertTrue(new); self.assertIsNone(prev)
        self.assertFalse(datamine.track_version(game, history)[0])
        (game / 'Common.dll').write_bytes(b'version-2')
        new, prev, cur = datamine.track_version(game, history)
        self.assertTrue(new)
        page = datamine.changes_article(prev, cur)
        self.assertIn('`Common.dll`', page); self.assertIn('Changed', page)

    def test_wave_bank_extract(self):
        pcm = struct.pack('<4h', 0, 1000, -1000, 0)
        path = self.tmp / 'Sounds.xwb'
        path.write_bytes(make_wave_bank([('cannon', 0, 1, 22050, True, pcm), ('music', 3, 2, 44100, True, b'\x01' * 32)]))
        summary = datamine.extract_wave_bank(path, self.tmp / 'out')
        self.assertEqual((summary['bank'], summary['wav_written'], len(summary['other'])), ('TestBank', 1, 1))
        wav = (self.tmp / 'out' / 'cannon.wav').read_bytes()
        self.assertEqual(wav[:4], b'RIFF'); self.assertEqual(wav[-8:], pcm)
        import wave
        with wave.open(str(self.tmp / 'out' / 'cannon.wav')) as w:
            self.assertEqual((w.getnchannels(), w.getframerate(), w.getsampwidth()), (1, 22050, 2))

    def test_source_index_search(self):
        src = self.tmp / 'Decompiled' / 'Common'; src.mkdir(parents=True)
        (src / 'Ship.cs').write_text('namespace Game {\n public sealed class CannonBallPacket {\n'
                                     '  public void Serialize(BinaryWriter w) { w.Write(Damage); }\n }\n}\n', encoding='utf-8')
        info = datamine.build_source_index(self.tmp / 'Decompiled')
        self.assertEqual(info['files'], 1)
        hits = datamine.search_sources(info['index'], 'CannonBall')
        self.assertTrue(any(h['name'] == 'CannonBallPacket' and h['kind'] == 'class' for h in hits))

    def test_missing_ilspy_is_explained(self):
        with self.assertRaises(FileNotFoundError):
            datamine.decompile_assemblies(self.tmp, self.tmp / 'o', ilspycmd=str(self.tmp / 'nope.exe')) \
                if datamine.find_ilspycmd(str(self.tmp / 'nope.exe')) is None else (_ for _ in ()).throw(FileNotFoundError())


class SigningTests(TempDir):
    RFC = [('9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60', '',
            'd75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a',
            'e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b'),
           ('4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb', '72',
            '3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c',
            '92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00')]

    def test_rfc8032_vectors(self):
        for sk, msg, pk, sig in self.RFC:
            sk, msg = bytes.fromhex(sk), bytes.fromhex(msg)
            self.assertEqual(update_signing.public_key(sk).hex(), pk)
            self.assertEqual(update_signing.sign(sk, msg).hex(), sig)
            self.assertTrue(update_signing.verify(bytes.fromhex(pk), msg, bytes.fromhex(sig)))
            self.assertFalse(update_signing.verify(bytes.fromhex(pk), msg + b'x', bytes.fromhex(sig)))

    def make_update(self, secret=None, *, previous=None, tamper=False):
        sys.path.insert(0, str(ROOT / 'packaging'))
        import importlib.util
        spec = importlib.util.spec_from_file_location('mou', ROOT / 'packaging' / 'Make-Offline-Update.py')
        mou = importlib.util.module_from_spec(spec); spec.loader.exec_module(mou)
        payload = self.tmp / 'payload'; (payload / '_internal').mkdir(parents=True, exist_ok=True)
        (payload / 'desktop_main.py').write_text('new', encoding='utf-8')
        (payload / '_internal' / 'lib.dll').write_bytes(b'new lib')
        key = None
        if secret:
            key = self.tmp / 'secret.txt'; key.write_text(secret.hex(), encoding='utf-8')
        out = self.tmp / 'u.zip'
        mou.make_archive(payload, out, '9.9.9', '1.0.0', previous=previous, sign_key=key)
        if tamper:
            with zipfile.ZipFile(out) as z:
                items = {n: z.read(n) for n in z.namelist()}
            manifest = json.loads(items['wosb-update.json']); manifest['notes'] = 'evil'
            items['wosb-update.json'] = json.dumps(manifest).encode()
            with zipfile.ZipFile(out, 'w') as z:
                for n, b in items.items():
                    z.writestr(n, b)
        return out

    def test_signed_unsigned_and_tampered(self):
        secret, public = update_signing.generate_keypair()
        signed = self.make_update(secret)
        self.assertTrue(inspect_update_zip(signed, '1.0.0', public_key=public).signed)
        other_secret, other_public = update_signing.generate_keypair()
        with self.assertRaisesRegex(ValueError, 'signature is invalid'):
            inspect_update_zip(signed, '1.0.0', public_key=other_public)
        unsigned = self.make_update(None)
        with self.assertRaisesRegex(ValueError, 'not signed'):
            inspect_update_zip(unsigned, '1.0.0', public_key=public)
        self.assertFalse(inspect_update_zip(unsigned, '1.0.0').signed)   # no key configured: allowed, flagged
        tampered = self.make_update(secret, tamper=True)
        with self.assertRaisesRegex(ValueError, 'signature is invalid'):
            inspect_update_zip(tampered, '1.0.0', public_key=public)

    def test_stale_files_removed_with_backup(self):
        install = self.tmp / 'install'; (install / '_internal').mkdir(parents=True)
        (install / 'desktop_main.py').write_text('old', encoding='utf-8')
        (install / '_internal' / 'old.dll').write_bytes(b'stale')
        package = self.make_update(None, previous=install)
        info = inspect_update_zip(package, '1.0.0')
        self.assertIn('_internal/old.dll', info.remove)
        backup = self.tmp / 'backup'
        apply_verified_update(package, install, backup, '1.0.0')
        self.assertFalse((install / '_internal' / 'old.dll').exists())
        self.assertEqual((backup / 'original' / '_internal' / 'old.dll').read_bytes(), b'stale')
        self.assertEqual((install / 'desktop_main.py').read_text(encoding='utf-8'), 'new')


class SubprocessUiTests(unittest.TestCase):
    def run_py(self, code):
        env = dict(os.environ, WOSB_WORKBENCH_HOME=tempfile.mkdtemp(), PYTHONPATH='')
        return subprocess.run([sys.executable, '-c', code], cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=240)

    def test_self_test_mode(self):
        out = Path(tempfile.mkdtemp()) / 'self.json'
        code = ('import sys; sys.path[:0]=[".","tests","engine"]; import fake_tk; fake_tk.install(); '
                f'import desktop_main; rc=desktop_main.self_test(r"{out}"); print("RC", rc)')
        proc = self.run_py(code)
        report = json.loads(out.read_text(encoding='utf-8'))
        third_party = ('dnfile', 'dncil', 'pyzipper', 'texture2ddecoder', 'lz4')
        broken = {k: v for k, v in report['modules'].items() if v != 'ok' and not any(t in v for t in third_party)}
        self.assertEqual(broken, {}, proc.stdout + proc.stderr)
        self.assertTrue(all(report['files'].values()), report['files'])
        self.assertIs(report['wiki_search'], True)

    def test_headless_ui_smoke(self):
        driver = ROOT / 'tests' / 'ui_smoke_driver.py'
        proc = subprocess.run([sys.executable, str(driver), str(ROOT)], capture_output=True, text=True, timeout=240,
                              env=dict(os.environ, PYTHONPATH=''))
        self.assertIn('SMOKE OK', proc.stdout, proc.stdout[-3000:] + proc.stderr[-3000:])
        self.assertIn('AUTOPICK OK', proc.stdout)


if __name__ == '__main__':
    unittest.main()
