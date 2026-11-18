import json
import os
import sqlite3
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'engine'))

import damage_model as dm  # noqa: E402
import hitbox_recovery  # noqa: E402
import install_detect  # noqa: E402
import protocol_lab  # noqa: E402
import source_schemas  # noqa: E402
import datamine  # noqa: E402


class TempDir(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory(); self.tmp = Path(self._t.name)

    def tearDown(self):
        self._t.cleanup()


class DamageModelTests(unittest.TestCase):
    def test_zero_hp_starts_sinking_not_destroyed(self):
        r = dm.simulate(1000, [{'source': 'CannonBall', 'health_damage': 400}, {'source': 'CannonBall', 'health_damage': 700}])
        self.assertTrue(r['sinking']); self.assertFalse(r['destroyed']); self.assertEqual(r['final_hp'], 1.0)

    def test_hp_below_half_rounds_to_zero(self):
        s = dm.ShipState(max_hp=100)
        dm.hp_damage(s, 99.6)
        self.assertGreater(s.sinking_ms, 0)

    def test_mortar_on_sinking_ship_is_instant(self):
        r = dm.simulate(1000, [{'source': 'CannonBall', 'health_damage': 2000}, {'source': 'MortarShot', 'health_damage': 1}])
        self.assertTrue(r['destroyed'])

    def test_ram_pushes_flooding(self):
        s = dm.ShipState(max_hp=1000)
        dm.apply_damage(s, dm.DamageData(source=dm.DamageID.CannonBall, health_damage=5000))
        before = s.sinking_ms
        dm.apply_damage(s, dm.DamageData(source=dm.DamageID.Collision, health_damage=10, source_uid=7), source_ship_uid=7)
        self.assertAlmostEqual(s.sinking_ms - before, 800, places=3)

    def test_flooding_ends_in_destruction(self):
        s = dm.ShipState(max_hp=1000)
        dm.apply_damage(s, dm.DamageData(source=dm.DamageID.CannonBall, health_damage=5000))
        dm.tick_flooding(s, 14)
        self.assertTrue(s.destroyed and s.destroyed_by_flooding)
        self.assertEqual(s.flooding_factor, 1.0)

    def test_sail_damage_weighted(self):
        s = dm.ShipState(max_hp=500, sail_weights=[0.5, 0.3, 0.2])
        dm.apply_damage(s, dm.DamageData(flags=dm.Flags.TotalSailDamage, damage_to_sails=0.3))
        self.assertAlmostEqual(s.sail_strength[0], 1 - 0.3 / 1.5)
        self.assertAlmostEqual(s.sail_strength[2], 1 - 0.3 / 0.6)

    def test_negative_damage_rejected(self):
        with self.assertRaises(ValueError):
            dm.apply_damage(dm.ShipState(max_hp=10), dm.DamageData(health_damage=-1))

    def test_factors(self):
        self.assertEqual(dm.sail_damage_energy(0), 1.0)
        self.assertEqual(dm.sail_damage_energy(3), 0.0)
        self.assertEqual(dm.mortar_splash_factor(0.5, 10), 1.0)
        self.assertAlmostEqual(dm.mortar_splash_factor(11, 10), 0.1)
        self.assertAlmostEqual(dm.damage_to_sail_factor(0.5, sail_closed=True), 0.6)
        self.assertEqual(dm.max_hp(1000, 0.1, 5), 1105.0)


class HitboxTests(TempDir):
    def _obj(self):
        lines = []
        def box(name, lo, hi):
            lines.append(f'o {name}_part0')
            for x in (lo[0], hi[0]):
                for y in (lo[1], hi[1]):
                    for z in (lo[2], hi[2]):
                        lines.append(f'v {x} {y} {z}')
            # interior points so every sail level has vertices
            for k in range(1, 40):
                t = k / 40
                lines.append(f'v {lo[0] + (hi[0]-lo[0])*t} {lo[1] + (hi[1]-lo[1])*t} {lo[2] + (hi[2]-lo[2])*t}')
        box('Hitbox', (-10, -2, -3), (10, 4, 3))
        box('ShipCorpus', (-11, -3, -3.5), (11, 5, 3.5))
        box('1_SailStatic1', (-5, 6, -2), (-3, 20, 2))
        box('2_SailAnimated2', (3, 6, -2), (5, 18, 2))
        box('MastFrame', (-4.2, 0, -0.3), (-3.8, 30, 0.3))
        path = self.tmp / 'Ship_99_test.obj'; path.write_text('\n'.join(lines))
        return path

    def test_build_rules(self):
        res = hitbox_recovery.build(self._obj())
        self.assertEqual(res['hitmesh_source'], 'Hitbox mesh')
        self.assertEqual(res['corpus']['max'][1], 4)
        self.assertEqual([s['name'] for s in res['sails']], ['1_SailStatic1', '2_SailAnimated2'])
        self.assertAlmostEqual(sum(s['weight'] for s in res['sails']), 1.0)
        mast = res['masts'][0]['box']
        self.assertAlmostEqual(mast['min'][1], 4)                    # starts at deck line
        self.assertAlmostEqual(mast['max'][0] - mast['min'][0], 1.3 * 1.8)
        self.assertEqual([r['node_id'] for r in res['node_table']], [0, 1, 2, 3])
        zones = hitbox_recovery.zones_for_viewer(res)
        import ship_viewer
        ship_viewer.validate_zones({'zones': zones})

    def test_batch_writes_summary(self):
        self._obj()
        res = hitbox_recovery.batch(self.tmp, self.tmp / 'out')
        self.assertEqual(res['ships'][0]['sails'], 2)
        self.assertTrue((self.tmp / 'out' / 'Ship_99_test.zones.json').is_file())


class SchemaTests(TempDir):
    CS = '''namespace Common.Game;
public enum DamageID : byte { Other, CannonBall }
public struct DamageData : IMPSerializable
{
    public int TargetUID;
    public float HealthDamage;
    public ushort Flags;
    public DamageID SourcePawnType;
    public float UDamageToSailes;
    public string Note;
    void IMPSerializable.Boxing(WriterExtern P_0) { this.A(P_0); }
    private void A(WriterExtern P_0)
    {
        P_0.WriteStruct(ref TargetUID);
        P_0.WriteStruct(ref HealthDamage);
        P_0.WriteStruct(ref Flags);
        P_0.WriteByte((byte)SourcePawnType);
        if ((Flags & 1) == 1)
        {
            P_0.WriteStruct(ref UDamageToSailes);
        }
        P_0.Write(Note);
    }
    private void A(ReaderExtern P_0) { }
}
'''

    def test_extract_layout_with_condition(self):
        db = self.tmp / 'idx.sqlite3'
        with sqlite3.connect(db) as conn:
            conn.execute('CREATE VIRTUAL TABLE source_fts USING fts5(path, body)')
            conn.execute('INSERT INTO source_fts VALUES (?,?)', ('Common/Common/Game/DamageData.cs', self.CS))
        res = source_schemas.extract_from_index(db)
        t = res['types'][0]
        self.assertEqual(t['type'], 'Common.Game.DamageData')
        names = [f['name'] for f in t['fields']]
        self.assertEqual(names, ['TargetUID', 'HealthDamage', 'Flags', 'SourcePawnType', 'UDamageToSailes', 'Note'])
        self.assertEqual(t['fields'][1]['size'], 4)
        self.assertIsNone(t['fields'][3]['condition'])
        self.assertIn('Flags', t['fields'][4]['condition'])
        self.assertEqual(t['fields'][5]['wire'], 'string')
        self.assertIn('| 5 |', source_schemas.describe(t))


class FramingTests(unittest.TestCase):
    def _frame(self, payload, seq):
        return struct.pack('<HHB', len(payload) + 5, 0, seq & 0xff) + payload

    def test_big_first_frame_still_syncs_at_zero(self):
        buf = self._frame(os.urandom(20000), 0) + b''.join(self._frame(os.urandom(20 + i % 30), i) for i in range(1, 200))
        self.assertEqual(protocol_lab.sync_offset(buf, protocol_lab.WOSB_FRAMING), 0)
        self.assertTrue(protocol_lab._wosb_fits([buf]))

    def test_frame_stats(self):
        msgs = [('server', None, self._frame(b'x' * 10, 3)), ('client', None, self._frame(b'y' * 5, 4))]
        stats = protocol_lab.wosb_frame_stats(msgs)
        self.assertEqual(stats['server']['frames'], 1); self.assertEqual(stats['client']['max_frame'], 10)


class InstallAndDatamineTests(TempDir):
    def test_workbench_folder_is_never_an_install(self):
        wb = self.tmp / 'Programs' / 'WoSBWorkbench'; wb.mkdir(parents=True)
        (wb / 'WoSBWorkbench.exe').write_bytes(b'MZ')
        self.assertTrue(install_detect.is_workbench_dir(wb))
        game = self.tmp / 'World of Sea Battle'; game.mkdir()
        self.assertFalse(install_detect.is_workbench_dir(game))

    def test_settings_repair_clears_workbench_path(self):
        import app_settings
        wb = self.tmp / 'WoSBWorkbench'; wb.mkdir(); (wb / 'WoSBWorkbench.exe').write_bytes(b'MZ')
        s = app_settings.Settings(self.tmp / 'settings.json')
        s.update({'installs.game': str(wb)})
        self.assertEqual(s.game_roots(), [])
        self.assertEqual(s.repair_installs(), ['game'])
        self.assertEqual(s.get('installs.game'), '')

    def test_framework_filter(self):
        self.assertTrue(datamine.is_framework_assembly('System.Private.CoreLib.dll'))
        self.assertTrue(datamine.is_framework_assembly('PresentationFramework.Classic.dll'))
        self.assertFalse(datamine.is_framework_assembly('Common.dll'))
        self.assertFalse(datamine.is_framework_assembly('Reskana_7_0.dll'))

    def test_asar_extract(self):
        files = {'package.json': b'{"name":"launcher"}', 'dist/main.js': b'console.log(1)'}
        table = {'files': {'package.json': {'size': 19, 'offset': '0'},
                           'dist': {'files': {'main.js': {'size': 14, 'offset': '19'}}},
                           '..': {'size': 1, 'offset': '0'}}}
        js = json.dumps(table).encode()
        pickle_payload = struct.pack('<I', len(js)) + js
        pickle_payload += b'\0' * ((4 - len(pickle_payload) % 4) % 4)
        header = struct.pack('<I', len(pickle_payload)) + pickle_payload
        blob = struct.pack('<II', 4, len(header)) + header + files['package.json'] + files['dist/main.js']
        arc = self.tmp / 'app.asar'; arc.write_bytes(blob)
        res = datamine.extract_asar(arc, self.tmp / 'out')
        self.assertEqual(res['files_written'], 2)
        self.assertEqual((self.tmp / 'out' / 'dist' / 'main.js').read_bytes(), b'console.log(1)')
        self.assertIn('..', res['skipped'])

    def test_sniff_json_bin(self):
        game = self.tmp / 'g'; game.mkdir()
        (game / 'loadingev.bin').write_bytes(b'{"A":1}' + b' ' * 20000)
        rep = datamine.coverage_report(game)
        row = [r for r in rep['by_extension'] if r['extension'] == '.bin'][0]
        self.assertEqual(row['kind'], 'JSON (by content)')

    def test_catalog_rotation(self):
        from multi_workflow import unique_catalog_destination
        root = self.tmp / 'Scan1'; (root / 'Catalog').mkdir(parents=True)
        (root / 'Catalog' / 'old.txt').write_text('1')
        dest = unique_catalog_destination(root)
        self.assertEqual(dest.name, 'Catalog')
        self.assertTrue((root / 'Catalog-previous' / 'old.txt').is_file())


if __name__ == '__main__':
    unittest.main()


class WikiSiteTests(TempDir):
    def test_site_is_public_safe_and_complete(self):
        import wiki_site
        from workbench_db import CatalogDB
        db = CatalogDB(self.tmp / 'w.sqlite3')
        try:
            def rec(ds, ext, data, root='Steam'):
                db.conn.execute('INSERT INTO records(dataset,source_root,external_id,name,raw_json,sha256,imported_utc) VALUES(?,?,?,?,?,?,?)',
                                (ds, root, ext, data.get('EnglishName', ext), json.dumps(data), 'x', 'now'))
            rec('ShipsToPlay', '1', {'ID': 1, 'EnglishName': 'Essex', 'Type': 'Destroyer', 'Health': 2160, 'Armor': 4.8,
                                     'StaticInfoID': 7, 'Source': '_lzcommon.wosb/ShipsToPlay_j.xnb'})
            rec('ShipsToPlay', '2', {'ID': 2, 'EnglishName': '(testing ship)', 'Health': 1})
            rec('ShipsBasics', '7', {'ID': 7, 'ModelName': 'Ship_11_essex'})
            rec('Cannons', 'c1', {'ID': 'c1', 'EnglishName': '24-pound cannon', 'Poundage': 24, 'Scatter': '5|5'})
            rec('English_Names', 'ship_1', {'Key': 'ship_1', 'EnglishDescription': 'A heavily armed frigate.'})
            rec('WindRoses', 'regular', {'Name': 'regular', 'HeadwindLeft': 40, 'HeadwindRight': 40})
            db.upsert_article('damage-and-sinking', 'Damage and sinking', 'Mechanics', '# Damage\n\nSee [[Essex]].\n\nFile: `x.xnb`\n')
            db.upsert_article('combat-message-layouts', 'Combat message layouts', 'Research', '# secret')
            db.conn.commit()
            hb = self.tmp / 'hb'; hb.mkdir()
            (hb / 'Ship_11_essex.hitboxes.json').write_text(json.dumps({'corpus': {'min': [0, 0, 0], 'max': [1, 1, 1]},
                                                                         'sails': [], 'masts': []}))
            out = self.tmp / 'site'
            m = wiki_site.build_site(db, out, hitboxes_dir=hb)
        finally:
            db.close()
        self.assertEqual(m['entities']['ship'], 1)
        self.assertEqual(m['ships_with_hitboxes'], 1)
        ship = (out / 'ship' / 'essex.html').read_text(encoding='utf-8')
        self.assertIn('2,160', ship); self.assertIn('heavily armed', ship); self.assertIn('canvas class="hitbox"', ship)
        self.assertFalse((out / 'wiki' / 'combat-message-layouts.html').exists())
        everything = ''.join(p.read_text(encoding='utf-8') for p in out.rglob('*.html'))
        for leak in ('.xnb', '_lzcommon', 'secret', 'testing ship'):
            self.assertNotIn(leak, everything)
        article = (out / 'wiki' / 'damage-and-sinking.html').read_text(encoding='utf-8')
        self.assertIn('../ship/essex.html', article)
        self.assertTrue((out / 'tools' / 'damage-simulator.html').is_file())
        self.assertIn('Essex', (out / 'search.json').read_text(encoding='utf-8'))

    def test_humanize_effect(self):
        import wiki_site
        self.assertEqual(wiki_site.humanize_effect('PSightSpeed +50'), 'Sight speed +50%')
        self.assertEqual(wiki_site.humanize_effect('MMarchingSpeed +4'), 'Marching speed +4')
