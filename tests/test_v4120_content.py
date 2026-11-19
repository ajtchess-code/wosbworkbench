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
