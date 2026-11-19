import base64
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from array import array
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'engine'))

import ball_damage  # noqa: E402
import battle_sim  # noqa: E402
import combat_sim  # noqa: E402
import damage_fit  # noqa: E402
import install_detect  # noqa: E402
import mechanics_pages  # noqa: E402
import model_pack  # noqa: E402
from workbench_db import CatalogDB  # noqa: E402

STARTER = ROOT / 'Starter-Catalog.sqlite3'
NODE = shutil.which('node')

CUBE_OBJ = """o ShipCorpus_part0
usemtl Wood6
v 0 0 0
v 1 0 0
v 1 1 0
v 0 1 0
vt 0 0
vt 1 0
vt 1 1
vt 0 1
f 1/1 2/2 3/3
f 1/1 3/3 4/4
o 1_SailAnimated3_part0
usemtl Sail6_main
v 0 2 0
v 1 2 0
v 1 3 0
vt 0 0
vt 1 0
vt 1 1
f 5/5 6/6 7/7
o ShipMin_part0
usemtl Wood6
v 0 0 0
v 5 0 0
v 5 5 0
vt 0 0
vt 0 0
vt 0 0
f 8/8 9/9 10/10
"""


class TempDir(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory(); self.tmp = Path(self._t.name)

    def tearDown(self):
        self._t.cleanup()


class CombatSimTests(unittest.TestCase):
    def test_shot_data_matches_client_numbers(self):
        s = combat_sim.shot_data(140, 0.1)
        self.assertAlmostEqual(s.sight_distance, 137, delta=1.5)

    def test_wind_effectivity_profile(self):
        e = lambda a: combat_sim.wind_effectivity(a)[0]
        self.assertAlmostEqual(e(90), 1.0, places=2)
        self.assertLess(e(0), e(30))          # dead downwind penalty
        self.assertAlmostEqual(e(180), 0.0, places=2)
        self.assertGreater(combat_sim.wind_effectivity(160, hardness=1.0)[0], e(160))

    def test_unique_rose_differs_by_tack(self):
        r = combat_sim.wind_effectivity(150, unique=True, tack='right')[0]
        l = combat_sim.wind_effectivity(150, unique=True, tack='left')[0]
        self.assertNotAlmostEqual(r, l, places=3)

    def test_big_fire_threshold_scales_with_hp(self):
        self.assertFalse(combat_sim.big_fire_can_start(3, 1500, 3000)[0])
        self.assertTrue(combat_sim.big_fire_can_start(4, 1500, 3000)[0])
        self.assertFalse(combat_sim.big_fire_can_start(9, 2990, 3000)[0])   # above 95% HP


class BallDamageTests(unittest.TestCase):
    def test_angle_and_armor_reduce_damage(self):
        c = {'Penetration': 12}; a = {'Penetration': 0, 'DamageFactor': 1}
        flat = ball_damage.estimate(c, a, 5)['damage']
        angled = ball_damage.estimate(c, a, 5, angle_deg=50)['damage']
        self.assertGreater(flat, angled)
        self.assertGreater(ball_damage.estimate(c, a, 2)['damage'], flat)

    def test_calibrate_recovers_scale(self):
        cannons = {'G': {'Penetration': 12}}; ammos = {'A': {'Penetration': 0, 'DamageFactor': 1}}
        trials = [{'cannon': 'G', 'ammo': 'A', 'target_armor': arm, 'damage': (12 - arm) * 3.0} for arm in (2, 4, 6, 8)]
        r = ball_damage.calibrate(trials, cannons, ammos)
        self.assertTrue(r['ok']); self.assertAlmostEqual(r['scale'], 3.0, places=2); self.assertAlmostEqual(r['armor_weight'], 1.0, places=2)


class ModelPackTests(TempDir):
    def test_obj_groups_skip_lod_meshes_and_quantize(self):
        obj = self.tmp / 'Ship_1_test.obj'; obj.write_text(CUBE_OBJ)
        m = model_pack.pack_model(obj, kind='ship')
        meshes = {g['mesh'] for g in m['groups']}
        self.assertIn('ShipCorpus', meshes); self.assertIn('SailAnimated3', meshes); self.assertNotIn('ShipMin', meshes)
        g = next(g for g in m['groups'] if g['mesh'] == 'ShipCorpus')
        q = array('h'); q.frombytes(base64.b64decode(g['p']))
        pts = [[(q[i + k] + 32767) * m['scale'][k] + m['min'][k] for k in range(3)] for i in range(0, len(q), 3)]
        self.assertTrue(any(abs(p[0] - 1) < 1e-3 and abs(p[1] - 1) < 1e-3 for p in pts))
        self.assertEqual(next(x for x in m['groups'] if x['mesh'] == 'SailAnimated3')['kind'], 'sail')

    def test_build_pack_matches_textures_and_is_incremental(self):
        from PIL import Image
        obj = self.tmp / 'Ship_1_test.obj'; obj.write_text(CUBE_OBJ)
        tex = self.tmp / 'tex' / 'Lod0'; tex.mkdir(parents=True)
        Image.new('RGBA', (8, 8), (120, 80, 40, 255)).save(tex / 'Wood6.png')
        Image.new('RGBA', (8, 8), (230, 230, 230, 255)).save(tex / 'Sail6_main.png')
        out = self.tmp / 'pack'
        idx = model_pack.build_pack(out, {'Ship_1_test': (obj, 'ship')}, texture_roots=[self.tmp / 'tex'])
        self.assertEqual(idx['models']['Ship_1_test']['textured'], 2)
        self.assertTrue((out / 'index.js').read_text().startswith('WOSB_PACK('))
        body = (out / 'models' / 'Ship_1_test.js').read_text()
        self.assertTrue(body.startswith('WOSB_MODEL("Ship_1_test",'))
        before = (out / 'models' / 'Ship_1_test.js').stat().st_mtime_ns
        model_pack.build_pack(out, {'Ship_1_test': (obj, 'ship')}, texture_roots=[self.tmp / 'tex'])
        self.assertEqual(before, (out / 'models' / 'Ship_1_test.js').stat().st_mtime_ns)

    def test_texture_index_prefers_exact_then_prefix(self):
        (self.tmp / 'Lod0' / 'public').mkdir(parents=True)
        for n in ('ship_stel_hull_1.png', 'ship_stel_hull_2.png', 'Vants3.png'):
            (self.tmp / 'Lod0' / 'public' / n).write_bytes(b'x')
        (self.tmp / 'Lod0' / 'Vants3.material.xnb').write_bytes(b'x')
        ix = model_pack.TextureIndex([self.tmp])
        self.assertEqual(ix.find('Vants3').name, 'Vants3.png')
        self.assertEqual(ix.find('ship_stel_hull').name, 'ship_stel_hull_1.png')
        self.assertIsNone(ix.find('nothing_here'))


class TextureDecodeTests(unittest.TestCase):
    def test_numpy_bc1_block(self):
        from xnb_images import decode_bc_numpy
        red, blue = (31 << 11), 31
        block = red.to_bytes(2, 'little') + blue.to_bytes(2, 'little') + (0b01010101).to_bytes(1, 'little') + bytes(3)
        im = decode_bc_numpy(block, 4, 4)
        px = [im.getpixel((i % 4, i // 4)) for i in range(16)]
        self.assertEqual(px[0][:3], (0, 0, 255))     # index 1 -> c1 (blue)
        self.assertEqual(px[4][:3], (255, 0, 0))     # index 0 -> c0 (red)
        self.assertEqual(px[0][3], 255)


@unittest.skipUnless(STARTER.exists(), 'starter catalog not bundled')
class BattleSimBuildTests(TempDir):
    def setUp(self):
        super().setUp()
        self.db_path = self.tmp / 'catalog.sqlite3'; shutil.copy2(STARTER, self.db_path)

    def test_pages_build_and_embed_data(self):
        db = CatalogDB(str(self.db_path))
        r = battle_sim.build_page(db, self.tmp / 'b.html', pack_base='pack/')
        html = (self.tmp / 'b.html').read_text(encoding='utf-8')
        self.assertNotIn('/*__SIM_DATA__*/', html); self.assertNotIn('<!--__SIM_LIB__-->', html)
        self.assertIn('"packBase":"pack/"', html); self.assertGreater(r['ships'], 0)
        b = battle_sim.build_boarding_page(db, self.tmp / 'board.html')
        self.assertGreater(b['unit_types'], 0)

    def test_simulators_without_recovery(self):
        db = CatalogDB(str(self.db_path))
        r = battle_sim.build_simulators(db, self.tmp / 'sim', recovery_dir=None)
        self.assertTrue((self.tmp / 'sim' / 'battle_sim.html').is_file()); self.assertEqual(r['pack'], {})

    def test_calibration_from_trials(self):
        db = CatalogDB(str(self.db_path))
        d = battle_sim.catalog_data(db)
        if not d['cannons'] or not d['ammo'] or not d['ships']:
            self.skipTest('starter catalog has no combat data')
        c = max(d['cannons'], key=lambda c: c['pen'] or 0); a = next(x for x in d['ammo'] if (x['df'] or 0) > 0)
        rows = [{'cannon': c['n'], 'ammo': a['n'], 'target_armor': arm, 'hp_before': 1000,
                 'hp_after': 1000 - max(0, (c['pen'] + a['pen'] - arm)) * a['df'] * 2} for arm in (1, 2, 3, 4)]
        csv = damage_fit.save_trials(self.tmp / 't.csv', rows)
        res = battle_sim.calibration_from_trials(db, csv)
        self.assertTrue(res['calibrated']); self.assertAlmostEqual(res['scale'], 2.0, places=1)


class MechanicsPagesTests(unittest.TestCase):
    def test_pages_have_no_code_paths(self):
        for slug, title, section, body in mechanics_pages.PAGES:
            self.assertEqual(section, 'Mechanics')
            self.assertNotRegex(body, r'\.dll|\.cs\b|\.xnb|0x[0-9a-f]{6}')
            self.assertTrue(body.startswith('# '))

    def test_fire_page_states_threshold(self):
        body = dict((p[0], p[3]) for p in mechanics_pages.PAGES)['large-and-minor-fires']
        self.assertIn('1 + (max HP ÷ 1000, rounded)', body)


class InstallDetectTests(TempDir):
    def test_client_root_resolves_nested_client(self):
        game = self.tmp / 'World of Sea Battle' / 'default' / 'game'
        game.mkdir(parents=True); (game / 'CommonData').mkdir(); (game / 'WorldOfSeaBattle.exe').write_bytes(b'')
        got = install_detect.client_root(self.tmp / 'World of Sea Battle')
        self.assertEqual(Path(got).resolve(), game.resolve())


@unittest.skipUnless(NODE, 'node not installed')
class JavaScriptTests(TempDir):
    def _script(self, html):
        parts = re.findall(r'<script>(.*?)</script>', html, flags=re.S)
        return '\n'.join(parts)

    def test_battle_page_script_parses(self):
        html = (ROOT / 'viewer' / 'battle_sim.html').read_text(encoding='utf-8').replace('/*__SIM_DATA__*/', '{}')
        f = self.tmp / 'b.js'; f.write_text(self._script(html), encoding='utf-8')
        r = subprocess.run([NODE, '--check', str(f)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_boarding_page_script_parses(self):
        html = (ROOT / 'viewer' / 'boarding_sim.html').read_text(encoding='utf-8').replace('/*__SIM_DATA__*/', '{}')
        f = self.tmp / 'b.js'; f.write_text(self._script(html), encoding='utf-8')
        r = subprocess.run([NODE, '--check', str(f)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_js_wind_matches_python(self):
        js = (ROOT / 'viewer' / 'wosb_sim.js').read_text(encoding='utf-8')
        f = self.tmp / 'w.js'
        f.write_text(js + '\nconsole.log(JSON.stringify([0,10,30,90,150,170].map(a=>WoSBSim.windEff(a,{}))));', encoding='utf-8')
        out = json.loads(subprocess.run([NODE, str(f)], capture_output=True, text=True).stdout)
        for a, v in zip([0, 10, 30, 90, 150, 170], out):
            self.assertAlmostEqual(v, combat_sim.wind_effectivity(a)[0], places=4)


if __name__ == '__main__':
    unittest.main()


@unittest.skipUnless(shutil.which('git'), 'git not installed')
class WikiPublishTests(TempDir):
    def test_publish_to_bare_remote(self):
        import wiki_publish
        site = self.tmp / 'site'; site.mkdir(); (site / 'index.html').write_text('<h1>hi</h1>')
        remote = self.tmp / 'remote.git'
        subprocess.run(['git', 'init', '-q', '--bare', str(remote)], check=True)
        r = wiki_publish.publish(site, str(remote))
        self.assertTrue(r['changed'])
        out = subprocess.run(['git', '--git-dir', str(remote), 'ls-tree', '--name-only', 'gh-pages'], capture_output=True, text=True).stdout
        self.assertIn('index.html', out); self.assertIn('.nojekyll', out)
        self.assertFalse(wiki_publish.publish(site, str(remote))['changed'])

    def test_pages_url(self):
        import wiki_publish
        self.assertEqual(wiki_publish.pages_url('https://github.com/Me/wosb-wiki.git'), 'https://me.github.io/wosb-wiki/')
        self.assertEqual(wiki_publish.pages_url('git@github.com:me/me.github.io.git'), 'https://me.github.io/')
