import json
import re
import struct
import xml.etree.ElementTree as ET
from pathlib import Path

import site_seo

ROOT = Path(__file__).resolve().parents[1]
LONG = ' '.join(['frigate broadside armor'] * 60)


def _page(path, body, title='Thing'):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
                    f'<title>{title} · WoSB Wiki</title></head><body><main><p>{body}</p></main></body></html>', encoding='utf-8')


def _build(tmp_path):
    _page(tmp_path / 'index.html', LONG, 'WoSB Wiki')
    _page(tmp_path / 'item' / 'long.html', LONG, 'Long item')
    _page(tmp_path / 'item' / 'thin.html', 'Short.', 'Thin item')
    _page(tmp_path / 'ship' / 'tiny.html', 'Short.', 'Tiny ship')
    _page(tmp_path / 'recent.html', LONG, 'Recent')
    _page(tmp_path / 'pack' / 'x.html', LONG)
    return site_seo.finalize(tmp_path, site_url='https://example.org', lastmod='2026-11-19')


def test_head_tags_and_counts(tmp_path):
    counts = _build(tmp_path)
    assert counts == {'indexed': 3, 'noindex': 2}
    page = (tmp_path / 'item' / 'long.html').read_text()
    assert '<link rel="canonical" href="https://example.org/item/long.html">' in page
    assert 'property="og:title" content="Long item"' in page
    assert 'og:image" content="https://example.org/assets/brand/social-card.jpg"' in page
    assert 'href="../favicon.ico"' in page and 'href="../site.webmanifest"' in page
    assert 'index,follow' in page
    assert page.index('name="viewport"') < page.index('name="description"')
    desc = re.search(r'name="description" content="([^"]*)"', page).group(1)
    assert 40 <= len(desc) <= 160
    assert 'noindex' in (tmp_path / 'item' / 'thin.html').read_text()
    assert 'noindex' not in (tmp_path / 'ship' / 'tiny.html').read_text()      # ship pages always indexed
    assert 'noindex' in (tmp_path / 'recent.html').read_text()
    assert 'canonical' not in (tmp_path / 'pack' / 'x.html').read_text()
    idx = (tmp_path / 'index.html').read_text()
    ld = json.loads(re.search(r'application/ld\+json">(.*?)</script>', idx).group(1))
    assert ld['@graph'][0]['@type'] == 'WebSite' and ld['@graph'][0]['url'] == 'https://example.org/'


def test_sitemap_robots_icons(tmp_path):
    _build(tmp_path)
    tree = ET.parse(tmp_path / 'sitemap.xml')
    ns = {'s': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
    locs = [e.text for e in tree.findall('.//s:loc', ns)]
    assert 'https://example.org/' in locs and 'https://example.org/item/long.html' in locs
    assert 'https://example.org/item/thin.html' not in locs and 'https://example.org/recent.html' not in locs
    assert all(e.text == '2026-11-19' for e in tree.findall('.//s:lastmod', ns))
    robots = (tmp_path / 'robots.txt').read_text()
    assert 'Disallow: /pack/' in robots and 'Sitemap: https://example.org/sitemap.xml' in robots
    man = json.loads((tmp_path / 'site.webmanifest').read_text())
    assert man['name'] == 'WoSB Wiki' and {i['sizes'] for i in man['icons']} == {'192x192', '512x512'}
    for f in ['favicon.ico', 'apple-touch-icon.png', 'assets/brand/emblem.svg', 'assets/brand/logo.svg']:
        assert (tmp_path / f).stat().st_size > 0


def test_finalize_is_idempotent(tmp_path):
    _build(tmp_path)
    once = (tmp_path / 'index.html').read_text()
    site_seo.finalize(tmp_path, site_url='https://example.org', lastmod='2026-11-19')
    assert (tmp_path / 'index.html').read_text() == once


def test_brand_files():
    b = ROOT / 'viewer' / 'brand'
    ico = (b / 'favicon.ico').read_bytes()
    assert ico[:4] == b'\0\0\1\0' and struct.unpack('<H', ico[4:6])[0] >= 3
    for n, size in [('icon-16.png', 16), ('icon-32.png', 32), ('icon-180.png', 180), ('icon-192.png', 192), ('icon-512.png', 512)]:
        d = (b / n).read_bytes()
        assert d[:8] == b'\x89PNG\r\n\x1a\n' and struct.unpack('>II', d[16:24]) == (size, size)
    for n in ['emblem.svg', 'logo.svg', 'favicon.svg']:
        ET.fromstring((b / n).read_text())
    assert (b / 'social-card.jpg').read_bytes()[:2] == b'\xff\xd8'
