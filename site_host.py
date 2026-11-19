"""Files that make the built wiki a self-hosted site on Cloudflare Pages (wosbwiki.org).

* ``_headers``      security headers: no framing by other sites, HTTPS only (HSTS), no MIME sniffing, a strict referrer and
                    permissions policy, and same-site resource policy on data files so other sites can't hotlink them.
* ``_redirects``    permanent redirects from pages that were folded or merged to where their content now lives.
* ``_worker.js``    + ``_routes.json``: a Pages Function that runs only for ``/api/*`` (Discord login, reports, the admin
                    dashboard's data) and ``/pack/*`` (the 3D model pack, refused unless the request comes from the wiki's
                    own pages, so the models can't be bulk-downloaded or hotlinked).
* ``ads.txt``       the Google AdSense seller line.
* ``404.html``      a not-found page in the site's own style.

Static hosting can't make a public page impossible to copy; these files stop framing, hotlinking and casual mirroring,
and the Cloudflare dashboard settings in docs/WOSBWIKI-HOSTING.md (bot protection, AI-crawler blocking, rate limits)
handle automated scrapers.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

MAX_REDIRECTS = 2000          # Cloudflare Pages static redirect limit

HEADERS = """/*
  X-Frame-Options: DENY
  Content-Security-Policy: frame-ancestors 'none'; base-uri 'self'; object-src 'none'; upgrade-insecure-requests
  Strict-Transport-Security: max-age=31536000; includeSubDomains
  X-Content-Type-Options: nosniff
  Referrer-Policy: strict-origin-when-cross-origin
  Permissions-Policy: camera=(), microphone=(), geolocation=(), usb=(), serial=(), bluetooth=()
  Cross-Origin-Opener-Policy: same-origin-allow-popups

/assets/*
  Cross-Origin-Resource-Policy: same-site
  Cache-Control: public, max-age=3600, must-revalidate

/search.json
  Cross-Origin-Resource-Policy: same-site
  X-Robots-Tag: noindex

/site.json
  X-Robots-Tag: noindex
"""

WORKER_FILE = Path(__file__).resolve().parent / 'viewer' / 'wiki_worker.js'
WORKER = WORKER_FILE.read_text(encoding='utf-8') if WORKER_FILE.is_file() else ''

ROUTES = {'version': 1, 'include': ['/pack/*', '/api/*'], 'exclude': []}


def write(out, *, redirects=(), ad_client='', not_found_html=None):
    """Write the Cloudflare Pages files into the built site ``out``. Returns a summary dict."""
    out = Path(out)
    (out / '_headers').write_text(HEADERS, encoding='utf-8')
    seen, lines = set(), []
    for old, new in redirects:
        if old in seen or old == new:
            continue
        seen.add(old); lines.append(f'{old} {new} 301')
    dropped = max(0, len(lines) - MAX_REDIRECTS)
    (out / '_redirects').write_text('\n'.join(lines[:MAX_REDIRECTS]) + ('\n' if lines else ''), encoding='utf-8')
    has_pack = (out / 'pack').is_dir()
    # the Worker serves the login/report API on every build, and guards the model pack when there is one
    (out / '_worker.js').write_text(WORKER, encoding='utf-8')
    (out / '_routes.json').write_text(json.dumps(ROUTES, indent=1), encoding='utf-8')
    pub = re.sub(r'^ca-', '', ad_client or '')
    if re.fullmatch(r'pub-\d{10,20}', pub):
        (out / 'ads.txt').write_text(f'google.com, {pub}, DIRECT, f08c47fec0942fa0\n', encoding='utf-8')
    if not_found_html:
        page = re.sub(r'(<head[^>]*>)', r'\1<base href="/">', not_found_html, count=1)
        page = page.replace('<meta name="viewport"', '<meta name="robots" content="noindex"><meta name="viewport"', 1)
        (out / '404.html').write_text(page, encoding='utf-8')
    return {'redirects': min(len(lines), MAX_REDIRECTS), 'redirects_dropped': dropped, 'pack_guard': has_pack}
