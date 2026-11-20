import json
import sqlite3
from types import SimpleNamespace

import site_effects
import site_extras


class _DB:
    def __init__(self, rows):
        self.conn = sqlite3.connect(':memory:')
        self.conn.execute('CREATE TABLE records (dataset TEXT, source_root TEXT, raw_json TEXT)')
        for ds, d in rows:
            self.conn.execute('INSERT INTO records VALUES (?,?,?)', (ds, 'Steam', json.dumps(d)))


def test_effects_in_plain_words():
    assert site_effects.describe('PSpeed', 5) == 'Ship speed +5%'
    assert site_effects.describe('PServer_XpAndRewardBonus', 7) == 'XP and rewards +7%'
    assert site_effects.describe_pair('PSpeed PArmor', '5 4') == 'Ship speed +5%, Armor +4%'
    assert site_effects.describe('CanMakeAnyBurnings') == 'Can start fires'
    # unknown codes still read as words, never as raw code
    assert site_effects.describe('PSomethingNew', 3) == 'Something new +3%'
    assert site_effects.describe_all('PSpeed +4 PArmor 2') == ['Ship speed +4%', 'Armor +2%']


def test_rank_table_and_cap():
    rows = [('RangInfo', {'SourceRecord': i, 'Xp': 100 * (i + 1)}) for i in range(29)]
    b = SimpleNamespace(db=_DB(rows), build='Steam')
    page = site_extras.ranks_page(b)
    assert 'rank 30' in page and '2,900 XP' in page               # the last step repeats after the cap
    assert f'{sum(100 * (i + 1) for i in range(29)):,} XP' in page


def test_elite_table_totals():
    r = site_extras.rules()['elite_status']['costs']['3']
    tbl = site_extras.elite_table(3)
    assert f'{sum(x for x, _, _ in r):,}' in tbl and 'All 6' in tbl
    assert site_extras.elite_table(7) is None


def test_consumables_and_medals_data():
    cons = site_extras.consumables()
    assert len(cons) >= 30 and all('index' in c for c in cons)
    m = site_extras.medals()
    assert m['medal_targets'] and m['titles'] and m['ship_unlocks']


def test_crew_titles_and_achievement_enrichment():
    db = _DB([('UnitsInfo', {'ID': 'unit_special_01'}), ('English_Text', {'Key': 'unit_special_01_name', 'English': 'Lucky One'}),
              ('Resources', {'ID': 'res_37', 'EnglishName': 'Battle Mark'})])
    assert site_extras.crew_titles(db) == {'unit_special_01': 'Lucky One'}
    m = site_extras.medals()
    aid = next(iter(m['medal_targets']))
    ach = {'ID': aid, '_title': 'Test'}
    b = SimpleNamespace(db=db, build='Steam', texts={}, entities={'achievement': [ach], 'ship': []})
    site_extras.enrich_achievements(b)
    assert ach['_medal'].startswith('Bronze ')


def test_upgrade_slot_costs_match_game_formula():
    # Gameplay.OpenExtraUpgradeSlotPrice: base by rank, slot 1 = base/4+250, 2 = base/2+500, 3 = base+1000
    assert site_extras.slot_costs(3) == [(1, 6500, 37, 216), (2, 13000, 37, 433), (3, 26000, 37, 866)]
    assert site_extras.slot_costs(7)[0] == (1, 250, 1, 10)            # small ships pay Wood, never less than 10
    assert site_extras.slot_costs(5)[0] == (1, 1375, 37, 22)
    assert site_extras.slot_costs(9) == []


def test_worker_serves_languages_without_waiting(tmp_path):
    import shutil, subprocess
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    if not shutil.which('node'):
        return
    w = tmp_path / 'worker.mjs'; shutil.copy(root / 'viewer' / 'wiki_worker.js', w)
    r = subprocess.run(['node', '--no-warnings', str(root / 'tests' / 'js' / 'translated.test.mjs'), w.as_uri()], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]


def test_wrangler_config_for_worker_deploys(tmp_path):
    import site_host
    site_host.write(tmp_path, worker_name='my-wiki', kv_id='abc')
    cfg = json.loads((tmp_path / 'wrangler.jsonc').read_text())
    assert cfg['name'] == 'my-wiki' and cfg['main'] == '_worker.js' and cfg['assets']['binding'] == 'ASSETS'
    assert '/es/*' in cfg['assets']['run_worker_first'] and '/api/*' in cfg['assets']['run_worker_first']
    assert cfg['kv_namespaces'][0]['id'] == 'abc' and 'd1_databases' not in cfg
    assert '_worker.js' in (tmp_path / '.assetsignore').read_text()      # the worker source is never served as a file


def test_hosting_dialog_covers_every_build_setting():
    import re
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / 'workbench_ui.py').read_text(encoding='utf-8')
    fields = set(re.findall(r"\('(\w+)','[^']+','[^']*','[^']*'\)", src.split('WIKI_HOSTING_FIELDS=[', 1)[1].split(']', 1)[0]))
    for key in ('site_url', 'worker_name', 'kv_id', 'd1_id', 'gtm_id', 'ad_client', 'discord_url', 'contact_email', 'donate_url'):
        assert key in fields
        assert f"self.settings.get('wiki.{key}')" in src or key == 'site_url'      # the build reads what the dialog saves
    assert "_wiki_hosting_dialog" in src.split('def _wiki_site_bar', 1)[1].split('def ', 1)[0]


def test_hit_mesh_kept_and_box_is_its_bounds(tmp_path):
    import hitbox_recovery
    obj = tmp_path / 'Ship_1_test.obj'
    obj.write_text('o ShipCorpus_part0\nv -9 -3 -3\nv 9 6 3\nv 0 0 0\nf 1 2 3\n'
                   'o Hitbox_part0\nv -5 -2 -2\nv 5 -2 -2\nv 5 4 2\nv -5 4 2\nf 4 5 6\nf 4 6 7\n'
                   'o Hitbox_part1\nv 5 4 2\nf 6 8 7\n')
    r = hitbox_recovery.build(obj)
    assert r['hitmesh_source'] == 'Hitbox mesh'
    assert r['corpus'] == {'min': [-5.0, -2.0, -2.0], 'max': [5.0, 4.0, 2.0]}    # the box is the mesh's bounds, not the visible hull's
    m = r['hitmesh']
    assert len(m['v']) == 12 and len(m['e']) == 10                                # 4 shared points, 5 unique edges


def test_share_links_kept_30_days_after_last_use(tmp_path):
    import shutil, subprocess
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    if not shutil.which('node'):
        return
    w = tmp_path / 'worker.mjs'; shutil.copy(root / 'viewer' / 'wiki_worker.js', w)
    r = subprocess.run(['node', '--no-warnings', str(root / 'tests' / 'js' / 'plans.test.mjs'), w.as_uri()], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]


def test_upgrade_recipe_formula_matches_game():
    import site_tools
    r = site_tools.upgrade_recipes({'Category': 'Armor', 'LowCost': False, 'MainCraftResource': ''}, {})
    # rank 7: base 150, gold (50 + 50) x2 (no main resource) x1.5 (rank above 5) = 300, nothing else
    assert r[7] == ({}, 300)
    # rank 1: base 5850, plates int(5850/400 - 0.5) = 14, rum 585, gold (50 + 1950) x2 x0.75 = 3000
    assert r[1] == ({'16': 14, '2': 585}, 3000)
    sails = site_tools.upgrade_recipes({'Category': 'Sailes', 'LowCost': False, 'MainCraftResource': 'CSailcloth'}, {})
    assert sails[1][0] == {'17': 83} and sails[7][0] == {'3': 50}       # sailcloth below rank 6, fabric from rank 6


def test_island_building_prices_and_chest_tables(tmp_path):
    import shutil, subprocess, json as _j
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    chests = _j.loads((root / 'data' / 'chests.json').read_text())
    for key in ('elite', 'incas', 'newyear'):
        assert abs(sum(r['w'] for r in chests['chests'][key]['rewards']) - 100) < 1e-6     # these tables are given in percent
    assert len(chests['chests']['big']['rewards']) == 41 and len(chests['chests']['altar']['rewards']) == 15
    if not shutil.which('node'):
        return
    test = tmp_path / 't.mjs'
    test.write_text("""import assert from 'node:assert/strict';
globalThis.window = {}; await import(process.argv[2]); const { buildingPrice } = window.Planners._test;
assert.deepEqual(buildingPrice(5, 0), { gold: 200, res: {} });                       // first building: gold only, 20 x 10 below rank 10
assert.deepEqual(buildingPrice(25, 4), { gold: Math.floor(400 / 2) * 6 + Math.floor(200 / 3) * 100, res: { Plate: 100, Wreckage: 200, Wood: 400 } });
console.log('ok');""")
    shutil.copy(root / 'viewer' / 'planners.js', tmp_path / 'p.js')
    r = subprocess.run(['node', str(test), (tmp_path / 'p.js').as_uri()], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-1500:]


def test_store_prices_events_and_wording():
    import site_tools, site_wording, json as _j
    from pathlib import Path
    assert site_tools.design_price({'Category': 'ShipFullDesign', 'InShop': 'true Tier3'}) == (690, None)
    assert site_tools.design_price({'Category': 'ShipFullDesign', 'InShop': 'true Tier3'}, ship_rank=6) == (455, None)   # rank 5-7 skins: -34%
    assert site_tools.design_price({'Category': 'Flag', 'InShop': 'true'}) == (77, None)
    assert site_tools.design_price({'Category': 'BowFigure', 'InShop': 'ByGold 2000'}) == (None, 2000)
    assert site_tools.design_price({'Category': 'Flag', 'InShop': 'false'}) == (None, None)
    ev = _j.loads((Path(__file__).resolve().parents[1] / 'data' / 'events.json').read_text())
    assert set(ev) == {'Halloween', 'NewYear', 'Anniversary', 'Spring'} and all(len(e['days']) == 14 for e in ev.values())
    assert site_tools._quest_text('KillAnyNpc(15)') == 'Sink 15 NPC ships'
    assert site_wording.clean_text('By Monets 890') == '890 Coins'
