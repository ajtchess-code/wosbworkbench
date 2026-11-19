import json
from pathlib import Path

import site_compact
import site_host
import site_legal
import wiki_site


def _entity(path, title, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'<html><head><meta name="viewport" content="x"></head><body><main id="content"><div class="crumbs"><a href="../index.html">Main</a></div>'
                    f'<h1>{title}</h1>{body}<p style="clear:both"><span class="tag"><a href="../category/skills.html">Category: Captain skills</a></span></p></main></body></html>', encoding='utf-8')


def _site(tmp_path):
    shared = '<h2>About skills</h2><p>Skills are learned with skill points earned as your captain rank goes up, and stay with the captain.</p>'
    for i in range(5):
        _entity(tmp_path / 'skill' / f's{i}.html', f'Skill {i}',
                f'<table class="infobox"><caption>Skill {i}</caption><tr><th>Effect</th><td>Speed +{i}%</td></tr></table>'
                f'<p><b>Skill {i}</b> is a captain skill in World of Sea Battle.</p>' + shared)
    _entity(tmp_path / 'skill' / 'big.html', 'Big skill', '<p>' + ' '.join(f'word{i}' for i in range(120)) + '</p>' + shared)
    (tmp_path / 'category').mkdir()
    (tmp_path / 'category' / 'skills.html').write_text('<main id="content"><table><tr><td><a href="../skill/s1.html">Skill 1</a></td></tr>'
                                                       '<tr><td><a href="../skill/big.html">Big</a></td></tr></table></main>', encoding='utf-8')
    (tmp_path / 'search.json').write_text(json.dumps([{'t': 'Skill 1', 'u': 'skill/s1.html'}]), encoding='utf-8')
    (tmp_path / 'index.html').write_text('<a href="skill/s2.html">x</a> <a href="unskill/s2.html">y</a>', encoding='utf-8')
    return site_compact.compact(tmp_path, {'skill': 'skills'}, plural={'skill': 'Captain skills'})


def test_thin_pages_fold_into_category(tmp_path):
    r = _site(tmp_path)
    assert r['folded'] == 5 and ('/skill/s1.html', '/category/skills.html#s1') in r['redirects']
    assert not (tmp_path / 'skill' / 's1.html').exists() and (tmp_path / 'skill' / 'big.html').exists()
    cat = (tmp_path / 'category' / 'skills.html').read_text()
    assert cat.count('id="s1"') == 1 and 'Speed +1%' in cat                    # facts table kept
    assert cat.count('Skills are learned with skill points') == 1               # shared text once, under "About"
    assert 'is a captain skill in World of Sea Battle' not in cat               # templated sentence dropped
    assert 'Category: Captain skills' not in cat
    assert 'href="../category/skills.html#s1"' in cat and 'href="../skill/big.html"' in cat
    assert json.loads((tmp_path / 'search.json').read_text())[0]['u'] == 'category/skills.html#s1'
    idx = (tmp_path / 'index.html').read_text()
    assert 'category/skills.html#s2' in idx and 'unskill/s2.html' in idx      # only whole path segments are rewritten


def test_blocks_split_top_level():
    b = site_compact.blocks('<p>a <b>b</b></p><br><table><tr><td><p>x</p></td></tr></table>tail')
    assert b == ['<p>a <b>b</b></p>', '<br>', '<table><tr><td><p>x</p></td></tr></table>', 'tail']


def test_host_files(tmp_path):
    (tmp_path / 'pack').mkdir()
    r = site_host.write(tmp_path, redirects=[('/a.html', '/b.html'), ('/a.html', '/c.html')], ad_client='ca-pub-1234567890123456',
                        not_found_html='<html><head><meta name="viewport" content="x"></head><body>nf</body></html>')
    assert r == {'redirects': 1, 'redirects_dropped': 0, 'pack_guard': True}
    h = (tmp_path / '_headers').read_text()
    assert "frame-ancestors 'none'" in h and 'X-Frame-Options: DENY' in h and 'Strict-Transport-Security' in h
    assert (tmp_path / '_redirects').read_text() == '/a.html /b.html 301\n'
    assert json.loads((tmp_path / '_routes.json').read_text())['include'] == ['/pack/*']
    w = (tmp_path / '_worker.js').read_text()
    assert 'Sec-Fetch-Site' in w and 'env.ASSETS.fetch' in w and 'status: 403' in w
    assert (tmp_path / 'ads.txt').read_text() == 'google.com, pub-1234567890123456, DIRECT, f08c47fec0942fa0\n'
    nf = (tmp_path / '404.html').read_text()
    assert '<base href="/">' in nf and 'noindex' in nf
    (tmp_path / 'pack').rmdir()
    site_host.write(tmp_path)
    assert not (tmp_path / '_worker.js').exists()


def test_legal_pages_name_the_owner():
    h = {'contact_email': 'contact@wosbwiki.org', 'site_name': 'WoSB Wiki', 'site_url': 'https://wosbwiki.org/'}
    d, t, p = site_legal.disclaimer(h), site_legal.terms(h), site_legal.privacy(h)
    assert 'Thera Interactive' in d and '3D models' in d and 'not affiliated' in d and 'mailto:contact@wosbwiki.org' in d
    assert 'scrape' in t and 'mirror' in t and 'AI models' in t and 'frame' in t
    assert 'adssettings.google.com' in p and 'Cloudflare' in p and 'European Economic Area' in p and 'under 13' in p


def test_guides_merge():
    b = wiki_site.SiteBuilder.__new__(wiki_site.SiteBuilder)
    b.article_alias = {}; b.redirects = []
    gp = lambda k, t, body: {'slug': f'gamepedia-gamewiki-{k}', 'title': t, 'section': 'Game guide', 'source_kind': 'client-gamepedia',
                             'body': f'# {t}\n\n{body}\n\n**See also:** [Trading tool](../tools/x.html)\n\n*From the in-game Gamepedia.*', 'updated': '2026-01-0' + str(len(k) % 9)}
    arts = [gp('earning', 'Making Money', 'Earn gold.'), gp('trading', 'Trading', 'Buy low.'), gp('boarding', 'Boarding', 'Grapple.'),
            {'slug': 'boarding', 'title': 'Boarding', 'section': 'Mechanics', 'source_kind': 'client-code', 'body': '# Boarding\n\n## Crew fight\n\nRules.', 'updated': None}]
    out = b._merge_guides(arts)
    slugs = {a['slug'] for a in out}
    assert slugs == {'trading-and-crafting', 'boarding'}
    tc = next(a for a in out if a['slug'] == 'trading-and-crafting')
    assert '## Making Money' in tc['body'] and '## Trading' in tc['body'] and tc['body'].count('See also') == 1
    bo = next(a for a in out if a['slug'] == 'boarding')
    assert "In the game's own words" in bo['body'] and '### Boarding' in bo['body'] and 'Grapple.' in bo['body']
    assert ('/wiki/gamepedia-gamewiki-trading.html', '/wiki/trading-and-crafting.html') in b.redirects


def test_page_chrome_mobile_and_legal():
    wiki_site.HOSTING.update(wiki_site.HOSTING_DEFAULTS)
    page = wiki_site._page('Test', '<p>x</p>', depth=1)
    assert 'id="menu"' in page and 'aria-controls="side"' in page and 'width=device-width' in page
    for f in ('privacy.html', 'terms.html', 'disclaimer.html'):
        assert f'href="../{f}"' in page
    assert 'Thera Interactive' in page and 'data-host="standalone"' in page and 'paypal.me' in page
    assert '@media(max-width:820px)' in wiki_site.CSS and 'menu-open' in wiki_site.SITE_JS and 'window.top!==window.self' in wiki_site.SITE_JS


def test_effect_prefixes():
    assert wiki_site.humanize_effect('CWorkshopLevel +1') == 'Workshop level +1'
    assert wiki_site.humanize_effect('CannonDamage +2') == 'Cannon damage +2'


def test_main_page_layout(tmp_path):
    import sqlite3, shutil
    from pathlib import Path
    from workbench_db import CatalogDB
    starter = Path(__file__).resolve().parents[1] / 'Starter-Catalog.sqlite3'
    if not starter.exists():
        return
    db_path = tmp_path / 'c.sqlite3'; shutil.copy(starter, db_path)
    wiki_site.build_site(CatalogDB(str(db_path)), tmp_path / 'site', model_pack=False)
    idx = (tmp_path / 'site' / 'index.html').read_text(encoding='utf-8')
    for part in ('class="mp-quick"', 'class="mp-welcome"', 'New visitors', "What's new", 'id="sitemap"', 'class="mp-box"', 'assets/brand/emblem.png'):
        assert part in idx, part
    assert (tmp_path / 'site' / 'assets' / 'brand' / 'emblem.png').is_file()
