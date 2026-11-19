"""Search-engine and sharing finish for the built WoSB Wiki: meta description, canonical URL, Open Graph and
Twitter cards, favicons and web manifest, JSON-LD, noindex for thin pages, sitemap.xml and robots.txt.

Runs over the finished site folder, so every page gets the same treatment whichever builder wrote it.
"""
from __future__ import annotations

import html
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

BRAND = Path(__file__).resolve().parent / 'viewer' / 'brand'
DEFAULT_URL = 'https://bandofmisfits.org/'
THIN_WORDS = 80           # pages with less text (tables included) than this are kept out of search results and ads
ALWAYS_INDEX = re.compile(r'^(index\.html|map\.html|about\.html|privacy\.html|category/|tools/|wiki/|guide/|ship/|cannon/)')
NEVER_INDEX = re.compile(r'^(recent\.html|tools/(battle|boarding)-simulator\.html)$')
PRIORITY = [(r'^index\.html$', '1.0'), (r'^(category/|map\.html|tools/)', '0.8'), (r'^(ship|cannon|wiki|guide)/', '0.7')]


def _text(page_html):
    m = re.search(r'<main[^>]*>(.*?)</main>', page_html, re.S)
    body = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', m.group(1) if m else '', flags=re.S)
    return html.unescape(re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', body))).strip()


def _description(page_html, title, site_name):
    m = re.search(r'<main[^>]*>.*?<p[^>]*>(.*?)</p>', page_html, re.S)
    d = html.unescape(re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', m.group(1)))).strip() if m else ''
    if len(d) < 40:
        d = f'{title}: World of Sea Battle stats, mechanics and tools on the {site_name}, a community fan wiki.'
    return d if len(d) <= 160 else d[:157].rsplit(' ', 1)[0] + '…'


def finalize(out, *, site_url=DEFAULT_URL, site_name='WoSB Wiki', lastmod=None):
    """Add head metadata to every page and write the brand files, sitemap.xml and robots.txt. Returns counts."""
    out = Path(out)
    site_url = site_url.rstrip('/') + '/'
    lastmod = lastmod or datetime.now(timezone.utc).strftime('%Y-%m-%d')
    brand = out / 'assets' / 'brand'
    if brand.exists():
        shutil.rmtree(brand)
    shutil.copytree(BRAND, brand)
    shutil.copyfile(BRAND / 'favicon.ico', out / 'favicon.ico')          # browsers and crawlers ask for /favicon.ico
    shutil.copyfile(BRAND / 'icon-180.png', out / 'apple-touch-icon.png')
    (out / 'site.webmanifest').write_text(json.dumps({
        'name': site_name, 'short_name': site_name, 'start_url': './', 'display': 'standalone', 'background_color': '#0a2236', 'theme_color': '#123f60',
        'icons': [{'src': 'assets/brand/icon-192.png', 'sizes': '192x192', 'type': 'image/png'},
                  {'src': 'assets/brand/icon-512.png', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any maskable'}]}, indent=1), encoding='utf-8')
    indexed, hidden = [], 0
    for f in sorted(out.rglob('*.html')):
        rel = f.relative_to(out).as_posix()
        if rel.startswith(('pack/', 'assets/')):
            continue
        page = f.read_text(encoding='utf-8')
        if '<head>' not in page or 'name="description"' in page:
            continue
        depth = rel.count('/')
        base = '../' * depth
        tm = re.search(r'<title>(.*?)</title>', page, re.S)
        title = html.unescape(tm.group(1)).split(' · ')[0].strip() if tm else site_name
        words = len(_text(page).split())
        noindex = bool(NEVER_INDEX.match(rel)) or (words < THIN_WORDS and not ALWAYS_INDEX.match(rel))
        url = site_url + ('' if rel == 'index.html' else rel)
        desc = _description(page, title, site_name)
        e = lambda s: html.escape(s, quote=True)
        head = [f'<meta name="description" content="{e(desc)}">',
                f'<link rel="canonical" href="{e(url)}">',
                '<meta name="robots" content="noindex,follow">' if noindex else '<meta name="robots" content="index,follow,max-image-preview:large">',
                f'<meta property="og:site_name" content="{e(site_name)}">', f'<meta property="og:type" content="{"website" if rel == "index.html" else "article"}">',
                f'<meta property="og:title" content="{e(title)}">', f'<meta property="og:description" content="{e(desc)}">', f'<meta property="og:url" content="{e(url)}">',
                f'<meta property="og:image" content="{site_url}assets/brand/social-card.jpg">', '<meta property="og:image:width" content="1200">',
                '<meta property="og:image:height" content="630">', f'<meta property="og:image:alt" content="{e(site_name)} logo">',
                '<meta name="twitter:card" content="summary_large_image">', f'<meta name="twitter:title" content="{e(title)}">',
                f'<meta name="twitter:description" content="{e(desc)}">', f'<meta name="twitter:image" content="{site_url}assets/brand/social-card.jpg">',
                '<meta name="theme-color" content="#123f60">', '<meta name="color-scheme" content="light">',
                f'<link rel="icon" href="{base}favicon.ico" sizes="any">', f'<link rel="icon" href="{base}assets/brand/favicon.svg" type="image/svg+xml">',
                f'<link rel="apple-touch-icon" href="{base}apple-touch-icon.png">', f'<link rel="manifest" href="{base}site.webmanifest">']
        if rel == 'index.html':
            head.append('<script type="application/ld+json">' + json.dumps({
                '@context': 'https://schema.org', '@graph': [
                    {'@type': 'WebSite', 'name': site_name, 'url': site_url, 'inLanguage': 'en', 'description': desc},
                    {'@type': 'Organization', 'name': 'Band of Misfits', 'url': site_url, 'logo': site_url + 'assets/brand/icon-512.png'}]}) + '</script>')
        page = re.sub(r'(<meta name="viewport"[^>]*>)', lambda m: m.group(1) + ''.join(head), page, count=1) if '<meta name="viewport"' in page \
            else page.replace('<head>', '<head>' + ''.join(head), 1)
        f.write_text(page, encoding='utf-8')
        if noindex:
            hidden += 1
        else:
            pr = next((p for rx, p in PRIORITY if re.match(rx, rel)), '0.5')
            indexed.append((url, pr))
    xml = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    xml += [f'<url><loc>{html.escape(u)}</loc><lastmod>{lastmod}</lastmod><priority>{p}</priority></url>' for u, p in indexed]
    xml.append('</urlset>')
    (out / 'sitemap.xml').write_text('\n'.join(xml) + '\n', encoding='utf-8')
    (out / 'robots.txt').write_text(f'User-agent: *\nAllow: /\nDisallow: /pack/\n\nSitemap: {site_url}sitemap.xml\n', encoding='utf-8')
    return {'indexed': len(indexed), 'noindex': hidden}
