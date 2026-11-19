"""Files that make the built wiki a self-hosted site on Cloudflare Pages (wosbwiki.org).

* ``_headers``      security headers: no framing by other sites, HTTPS only (HSTS), no MIME sniffing, a strict referrer and
                    permissions policy, and same-site resource policy on data files so other sites can't hotlink them.
* ``_redirects``    permanent redirects from pages that were folded or merged to where their content now lives.
* ``_worker.js``    + ``_routes.json``: a tiny Pages Function that runs only for ``/pack/*`` (the 3D model pack) and refuses
                    requests that don't come from the wiki's own pages, so the models can't be bulk-downloaded or hotlinked.
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
  Cache-Control: public, max-age=86400

/search.json
  Cross-Origin-Resource-Policy: same-site
  X-Robots-Tag: noindex

/site.json
  X-Robots-Tag: noindex
"""

WORKER = r"""// WoSB Wiki: guard the 3D model pack. Runs only for /pack/* (see _routes.json); everything else is plain static hosting.
const DENY = 'The WoSB Wiki 3D model pack only loads inside the wiki itself.';

function fromOurPages(request, url) {
  const site = request.headers.get('Sec-Fetch-Site');
  if (site) return site === 'same-origin';
  const ref = request.headers.get('Referer') || '';
  try { return new URL(ref).host === url.host; } catch (e) { return false; }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (!url.pathname.startsWith('/pack/')) return env.ASSETS.fetch(request);
    if (request.method !== 'GET' && request.method !== 'HEAD') return new Response(null, { status: 405 });
    if (!fromOurPages(request, url)) {
      return new Response(DENY, { status: 403, headers: { 'content-type': 'text/plain; charset=utf-8', 'cache-control': 'no-store', 'x-robots-tag': 'noindex, nofollow' } });
    }
    const res = await env.ASSETS.fetch(request);
    const out = new Response(res.body, res);
    out.headers.set('Cross-Origin-Resource-Policy', 'same-origin');
    out.headers.set('X-Content-Type-Options', 'nosniff');
    out.headers.set('X-Robots-Tag', 'noindex, nofollow');
    out.headers.set('Cache-Control', 'private, max-age=86400');
    out.headers.set('Vary', 'Sec-Fetch-Site, Referer');
    return out;
  },
};
"""

ROUTES = {'version': 1, 'include': ['/pack/*'], 'exclude': []}


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
    for name in ('_worker.js', '_routes.json'):
        (out / name).unlink(missing_ok=True)
    if has_pack:
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
