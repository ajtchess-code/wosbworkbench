"""Title Case for the wiki's own labels: page titles, headings, table headers, menus and short link text.

"Captain skills" -> "Captain Skills", "Ports and port battles" -> "Ports and Port Battles". Small words stay lower case
inside a title, and words that already carry their own capitals or digits are left alone (3D, PvP, HP, WoSB, 16-pdr).
Long link text (a whole sentence that happens to be a link) is not touched, and nor are table cells.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

SMALL = {'a', 'an', 'the', 'and', 'but', 'or', 'nor', 'for', 'of', 'on', 'in', 'at', 'to', 'by', 'with', 'vs', 'vs.', 'via', 'per', 'from', 'as', 'into'}
MAX_LINK_WORDS = 5
_TAGS = ('h1', 'h2', 'h3', 'h4', 'h5', 'th', 'title', 'legend', 'summary', 'caption', 'a', 'option', 'button')


def _word(w, first, last):
    if not w:
        return w
    lead = re.match(r'^[(\["“‘]*', w).group(0)
    core = w[len(lead):]
    if not core or not core[0].isalpha():
        return w
    if any(ch.isdigit() for ch in core) or any(ch.isupper() for ch in core[1:]) or core.startswith(('http', 'www.')) or '@' in core or '.' in core.rstrip('.,:;!?)'):
        return w
    if '(' in lead and len(core.rstrip(').,;:')) <= 3:          # units and short notes: (s), (kg), (HP)
        return w
    low = core.lower()
    if not first and not last and low.rstrip('.,:;!?)') in SMALL:
        return lead + low
    return lead + '-'.join(p[:1].upper() + p[1:] if p else p for p in core.split('-'))


def title_case(text):
    """Title Case one label. Text after ':' or a dash starts a new title."""
    out = []
    for seg in re.split(r'(\s*[:–—·|]\s*|\s+-\s+)', text):
        if re.fullmatch(r'\s*[:–—·|]\s*|\s+-\s+', seg or ''):
            out.append(seg); continue
        words = seg.split(' ')
        idx = [i for i, w in enumerate(words) if w]
        out.append(' '.join(_word(w, i == idx[0], i == idx[-1]) if w else w for i, w in enumerate(words)) if idx else seg)
    return ''.join(out)


_RX = re.compile(r'<(' + '|'.join(_TAGS) + r')(\s[^>]*)?>([^<>]+)</\1>', re.I)


def apply_html(page):
    def sub(m):
        tag, attrs, inner = m.group(1).lower(), m.group(2) or '', m.group(3)
        if 'data-notc' in attrs:
            return m.group(0)
        text = html.unescape(inner)
        if tag == 'a' and len(text.split()) > MAX_LINK_WORDS:
            return m.group(0)
        new = title_case(text)
        if new == text:
            return m.group(0)
        return f'<{m.group(1)}{attrs}>{html.escape(new, quote=False)}</{m.group(1)}>'
    return _RX.sub(sub, page)


def _search(items):
    for it in items:
        if it.get('t') and len(str(it['t']).split()) <= MAX_LINK_WORDS:
            it['t'] = title_case(str(it['t']))
        if it.get('c'):
            it['c'] = title_case(str(it['c']))
    return items


def apply(out):
    """Rewrite every page of the built site, plus the search index. Returns the number of pages changed."""
    out = Path(out); changed = 0
    for f in out.rglob('*.html'):
        if f.relative_to(out).parts[0] == 'pack':
            continue
        s = f.read_text(encoding='utf-8'); t = apply_html(s)
        if t != s:
            f.write_text(t, encoding='utf-8'); changed += 1
    sj = out / 'search.json'
    if sj.is_file():
        items = _search(json.loads(sj.read_text(encoding='utf-8')))
        sj.write_text(json.dumps(items, separators=(',', ':')), encoding='utf-8')
        js = out / 'assets' / 'site.js'
        if js.is_file():
            s = js.read_text(encoding='utf-8')
            if s.startswith('window.SEARCH_INDEX='):
                body = s.split('\n', 1)[1] if '\n' in s else ''
                js.write_text('window.SEARCH_INDEX=' + json.dumps(items, separators=(',', ':')) + ';\n' + body, encoding='utf-8')
    return changed
