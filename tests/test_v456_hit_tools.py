import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'engine'))

import gameplay_capture  # noqa: E402
import mechanics_pages  # noqa: E402
from workbench_db import CatalogDB  # noqa: E402

STARTER = ROOT / 'Starter-Catalog.sqlite3'
NODE = shutil.which('node')
HIT_DATA = {'ships': [{'n': 'Test', 'armor': 7, 'hp': 3180, 'rank': 3, 'cls': 'Hardship', 'crew': 174, 'speed': 7.5,
                       'box': {'min': [-29, -4, -7], 'max': [29, 12, 7]}, 'ports': {'left': 35, 'right': 35, 'swivel': 10}, 'masts': 3, 'sails': 18}],
            'cannons': [{'n': '32-pdr Cannon', 'pen': 20, 'min': 0, 'max': 135, 'reload': 15.5, 'mortar': False, 'mount': 'broadside'},
                        {'n': '8-inch Mortar', 'pen': 150, 'min': 80, 'max': 150, 'reload': 31, 'splash': 13, 'scatter': 4, 'mortar': True, 'mount': 'mortar'}],
            'ammo': [{'n': 'Cast-Iron Shot', 'pen': 0, 'df': 1, 'min': 0, 'reload': 1}],
            'calib': {'calibrated': False, 'armor_weight': 1, 'scale': 1},
            'towers': [{'n': 'Mortar tower', 'kind': 'mortar', 'dmg': 120, 'cd': 15, 'arc': 180, 'dead': 50, 'range': 190, 'note': ''}],
            'pb': {'base': {'1': [12100, 26400]}, 'base_low': [4500, 10000], 'team': {'10': 0.7}, 'level': [1, 1], 'capture_r': 30, 'tower_armor': 3}}


@unittest.skipUnless(NODE, 'node not installed')
class ViewerMath(unittest.TestCase):
    def run_js(self, files, expr):
        src = 'global.window=global;window.HIT_DATA=' + json.dumps(HIT_DATA) + ';\n'
        src += '\n'.join((ROOT / 'viewer' / f).read_text(encoding='utf-8') for f in files)
        src += f'\nconsole.log(JSON.stringify({expr}));'
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 't.js'; f.write_text(src, encoding='utf-8')
            r = subprocess.run([NODE, str(f)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_fire_threshold_and_tally(self):
        got = self.run_js(['fire_tool.js'], '[FireTool.need(850),FireTool.need(2500),FireTool.need(3180),FireTool.need(3960),FireTool.wilson(15,150)]')
        self.assertEqual(got[:4], [2, 3, 4, 5])          # .NET rounds 2.5 to 2
        p, lo, hi = got[4]; self.assertAlmostEqual(p, 0.1); self.assertLess(lo, 0.1); self.assertGreater(hi, 0.1)

    def test_fire_flare_shapes(self):
        got = self.run_js(['fire_tool.js'], "[FireTool.flare('finite',6,0),FireTool.flare('finite',13,0),FireTool.flare('infinite',2,0),FireTool.flare('mendable',13,0),FireTool.flare('mendable',13,0.6)]")
        self.assertAlmostEqual(got[0], 0.6, places=4); self.assertEqual(got[1], 0); self.assertAlmostEqual(got[2], 0.5)
        self.assertGreaterEqual(got[3], 1.0); self.assertAlmostEqual(got[4], 0.4, places=4)

    def test_hit_zones_and_defenses(self):
        got = self.run_js(['hit_analysis.js', 'defenses.js'],
                          "(()=>{const M=HitAnalysis.model(HIT_DATA.ships[0].box);const p=HitAnalysis.params(HIT_DATA,{ship:'Test',cannon:'32-pdr Cannon',ammo:'Cast-Iron Shot',armorBonus:0,penBonus:0});"
                          "return [HitAnalysis.fromBearing(M,180,p).zone,HitAnalysis.fromBearing(M,0,p).zone,HitAnalysis.fromBearing(M,90,p).zone,"
                          "HitAnalysis.fromBearing(M,180,p).dmg>HitAnalysis.fromBearing(M,90,p).dmg,Defenses.strength(HIT_DATA.pb,1,10,1,true),Defenses.mortarF(0,13),Defenses.mortarF(20,13)]})()")
        self.assertEqual(got[:3], ['stern', 'bow', 'side']); self.assertTrue(got[3])
        self.assertEqual(got[4], 8500); self.assertEqual(got[5], 1); self.assertEqual(got[6], 0)


class FireMarkers(unittest.TestCase):
    def test_fire_markers_and_tally(self):
        self.assertIn('minor-fire', gameplay_capture.ALLOWED_MARKERS); self.assertIn('large-fire', gameplay_capture.ALLOWED_MARKERS)
        with tempfile.TemporaryDirectory() as d:
            lines = [{'utc': '2026-11-19T00:00:0%dZ' % i, 'kind': k, 'ammo': 'Cast-Iron Shot'} for i, k in enumerate(['hit'] * 8 + ['minor-fire'] * 2)]
            (Path(d) / 'events.jsonl').write_text('\n'.join(json.dumps(x) for x in lines), encoding='utf-8')
            t = gameplay_capture.fire_tally(d)
        row = t['Cast-Iron Shot']; self.assertEqual((row['hits'], row['minor_fires']), (8, 2)); self.assertAlmostEqual(row['rate'], 0.25)
        self.assertEqual(gameplay_capture.wilson(0, 0), (None, None, None))

    def test_fire_page_facts(self):
        page = mechanics_pages.FIRES_PAGE
        for fact in ('4 HP per second', '80 seconds', '5% and 95%', 'Sea Ration', 'Infinite', 'rolled by the server'):
            self.assertIn(fact, page)


@unittest.skipUnless(STARTER.exists(), 'starter catalog not bundled')
class WikiPages(unittest.TestCase):
    def test_tools_built(self):
        import wiki_site
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'site'
            wiki_site.build_site(CatalogDB(str(STARTER)), out, model_pack=False)
            for f in ('tools/hit-analysis.html', 'tools/defenses.html', 'tools/fire-calculator.html', 'assets/hit-data.js', 'assets/fire_tool.js'):
                self.assertTrue((out / f).is_file(), f)
            data = json.loads(re.search(r'window\.HIT_DATA=(.*);', (out / 'assets/hit-data.js').read_text(encoding='utf-8')).group(1))
            self.assertIn('towers', data); self.assertIn('pb', data)


if __name__ == '__main__':
    unittest.main()
