import json
import shutil
import subprocess
from pathlib import Path

import pytest

import site_titlecase as tc
import wiki_site

ROOT = Path(__file__).resolve().parents[1]


def test_title_case_rules():
    assert tc.title_case('Captain skills') == 'Captain Skills'
    assert tc.title_case('Ports and port battles') == 'Ports and Port Battles'
    assert tc.title_case('3D ship viewer') == '3D Ship Viewer'
    assert tc.title_case('PvP, flags and notoriety') == 'PvP, Flags and Notoriety'
    assert tc.title_case('Reload (s)') == 'Reload (s)' and tc.title_case('Hull HP') == 'Hull HP'
    assert tc.title_case('Category: ship cosmetics') == 'Category: Ship Cosmetics'
    html = tc.apply_html('<h2>about ship cosmetics</h2><a href="x">ships by rank</a><a href="y">Try designs on a ship in the 3D viewer now</a>'
                         '<td>keep me</td><a data-notc href="z">all pages</a>')
    assert '<h2>About Ship Cosmetics</h2>' in html and '>Ships by Rank<' in html and 'Try designs on a ship' in html
    assert '<td>keep me</td>' in html and '>all pages<' in html


@pytest.mark.skipif(not shutil.which('node'), reason='node needed for the Worker test')
def test_worker_api(tmp_path):
    w = tmp_path / 'worker.mjs'; shutil.copy(ROOT / 'viewer' / 'wiki_worker.js', w)
    r = subprocess.run(['node', '--no-warnings', str(ROOT / 'tests' / 'js' / 'worker.test.mjs'), w.as_uri()], capture_output=True, text=True, timeout=120)
    if 'node:sqlite' in r.stderr and 'ERR_UNKNOWN_BUILTIN_MODULE' in r.stderr:
        pytest.skip('node without node:sqlite')
    assert r.returncode == 0, r.stderr[-2000:]
    assert 'worker tests passed' in r.stdout


def test_page_has_login_slot_and_report_bar():
    wiki_site.HOSTING.clear(); wiki_site.HOSTING.update(wiki_site.HOSTING_DEFAULTS)
    page = wiki_site._page('X', '<p>y</p>', depth=1)
    assert '<div id="acct" hidden></div>' in page and 'class="report-bar" hidden' in page and 'assets/community.js' in page
    assert 'data-report="general"' in page
    assert 'report-bar' not in wiki_site._page('X', '', report=False)


def test_icons_copied(tmp_path):
    from PIL import Image
    from workbench_db import CatalogDB
    starter = ROOT / 'Starter-Catalog.sqlite3'
    if not starter.exists():
        pytest.skip('no starter catalog')
    db_path = tmp_path / 'c.sqlite3'; shutil.copy(starter, db_path)
    db = CatalogDB(str(db_path))
    cat = tmp_path / 'Catalog-1'; (cat / 'AI-Data').mkdir(parents=True)
    rec = json.loads(db.conn.execute("SELECT raw_json FROM records WHERE dataset='Cannons' AND source_root='Steam' LIMIT 1").fetchone()[0])
    png = cat / 'Images' / 'Items' / 'gun.png'; png.parent.mkdir(parents=True)
    Image.new('RGBA', (64, 40), (200, 30, 30, 255)).save(png)
    link = {'Category': 'Cannons', 'EntityID': rec['ID'], 'PNGPath': 'Images/Items/gun.png', 'Relationship': 'Exact client reference'}
    db.conn.execute('INSERT INTO records (dataset,source_root,external_id,name,description,source_file,raw_json,sha256,imported_utc) VALUES (?,?,?,?,?,?,?,?,?)',
                    ('Entity_Images', 'Steam', 'x', 'x', '', str(cat / 'AI-Data' / 'Entity_Images.jsonl'), json.dumps(link), 'x', '2026'))
    db.conn.commit()
    out = tmp_path / 'site'
    wiki_site.build_site(db, out, model_pack=False)
    icons = list((out / 'assets' / 'icons' / 'cannon').glob('*.webp'))
    assert len(icons) == 1
    page = next(p for p in (out / 'cannon').glob('*.html') if icons[0].stem in p.name).read_text(encoding='utf-8')
    assert 'class="ibimg"' in page and f'assets/icons/cannon/{icons[0].name}' in page
    assert f'icons/cannon/{icons[0].name}' in (out / 'category' / 'cannons.html').read_text(encoding='utf-8')
    for f in ('_worker.js', '_routes.json', 'admin/index.html', 'assets/community.js', 'assets/admin.js', 'assets/item_viewer.js'):
        assert (out / f).is_file(), f
    assert json.loads((out / '_routes.json').read_text())['include'] == ['/pack/*', '/api/*']
    idx = (out / 'index.html').read_text(encoding='utf-8')
    assert 'gtm.js?id=GTM-TMZFVXTL' in idx and 'adsbygoogle.js?client=ca-pub-6442579332215350' in idx
    assert 'adsbygoogle' not in (out / 'admin' / 'index.html').read_text(encoding='utf-8')
    assert 'noindex' in (out / 'admin' / 'index.html').read_text(encoding='utf-8')
    assert '>Captain Skills<' in idx


def test_assets_are_versioned(tmp_path):
    (tmp_path / 'assets').mkdir(); (tmp_path / 'assets' / 'site.css').write_text('a{}'); (tmp_path / 'tools').mkdir()
    (tmp_path / 'index.html').write_text('<link rel="stylesheet" href="assets/site.css"><script src="assets/missing.js"></script>')
    (tmp_path / 'tools' / 'x.html').write_text('<link rel="stylesheet" href="../assets/site.css">')
    assert wiki_site._version_assets(tmp_path) == 2
    import re
    v = re.search(r'site\.css\?v=([0-9a-f]{10})"', (tmp_path / 'index.html').read_text()).group(1)
    assert f'../assets/site.css?v={v}"' in (tmp_path / 'tools' / 'x.html').read_text()
    assert 'assets/missing.js"' in (tmp_path / 'index.html').read_text()
    (tmp_path / 'assets' / 'site.css').write_text('b{}')
    (tmp_path / 'index.html').write_text('<link rel="stylesheet" href="assets/site.css">')
    wiki_site._version_assets(tmp_path)
    assert v not in (tmp_path / 'index.html').read_text()           # new content, new address
