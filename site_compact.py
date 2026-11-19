"""Fold thin entity pages into their category page.

Many game records (a captain skill, an achievement, a decoration) have only a few facts. One page each makes hundreds of
near-empty pages that clutter search results and that Google AdSense treats as low-value content. This pass runs over the
finished site and, for every page whose own text is below a threshold once shared boilerplate is removed:

* moves its facts into an anchored entry on the category page (``category/skills.html#aimed-fire``),
* deletes the page, and rewrites every link, the search index and the data files to the new address,
* records a permanent redirect so old links keep working.

Boilerplate (text that repeats across many pages of the same kind, such as the explanation of a cosmetic slot) is shown
once at the top of the category page instead of on every entry.
"""
from __future__ import annotations

import html
import re
from collections import Counter
from pathlib import Path

MIN_WORDS = 80
VOID = {'br', 'img', 'input', 'hr', 'meta', 'link', 'source', 'wbr', 'col', 'area'}
_TAG = re.compile(r'<(/?)([a-zA-Z][a-zA-Z0-9]*)\b[^>]*?(/?)>')


def blocks(fragment):
    """Split an HTML fragment into its top-level elements (text between them is kept as its own block)."""
    out, depth, start, pos = [], 0, 0, 0
    for m in _TAG.finditer(fragment):
        closing, tag, selfclose = m.group(1), m.group(2).lower(), m.group(3)
        if depth == 0 and m.start() > pos and fragment[pos:m.start()].strip():
            out.append(fragment[pos:m.start()])
        if depth == 0 and not closing:
            start = m.start()
        if tag in VOID or selfclose:
            if depth == 0:
                out.append(fragment[start:m.end()]); pos = m.end()
            continue
        depth += -1 if closing else 1
        if depth <= 0:
            depth = 0
            out.append(fragment[start:m.end()]); pos = m.end()
    if fragment[pos:].strip():
        out.append(fragment[pos:])
    return out


def _text(fragment):
    return html.unescape(re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', fragment))).strip()


def _main(page):
    m = re.search(r'(<main[^>]*>)(.*?)(</main>)', page, re.S)
    return m


def _content(page):
    """(title, content blocks) of an entity page: crumbs and heading removed."""
    m = _main(page)
    inner = m.group(2)
    inner = re.sub(r'^\s*<div class="crumbs">.*?</div>', '', inner, count=1, flags=re.S)
    h = re.search(r'<h1>(.*?)</h1>', inner, re.S)
    title = html.unescape(re.sub(r'<[^>]+>', '', h.group(1))).strip() if h else ''
    inner = inner.replace(h.group(0), '', 1) if h else inner
    return title, blocks(inner)


def _key(block, title):
    t = _text(block)
    return t.replace(title, '\x00') if title else t


def compact(out, kinds, *, keep_kinds=('ship', 'cannon'), min_words=MIN_WORDS, plural=None):
    """Fold thin pages of ``kinds`` ({kind: category file stem}). Returns {'folded': n, 'redirects': [(old, new)]}."""
    out = Path(out)
    plural = plural or {}
    moves, redirects = {}, []
    for kind, cat in kinds.items():
        folder = out / kind
        cat_file = out / 'category' / f'{cat}.html'
        if kind in keep_kinds or not folder.is_dir() or not cat_file.is_file():
            continue
        pages = {}
        for f in sorted(folder.glob('*.html')):
            title, bl = _content(f.read_text(encoding='utf-8'))
            pages[f] = (title, bl)
        if not pages:
            continue
        seen = Counter(k for title, bl in pages.values() for k in {_key(b, title) for b in bl})
        lim = 3                                   # the same text on three or more pages is template text
        common, entries = [], []
        for f, (title, bl) in pages.items():
            keep, words = [], 0
            for b in bl:
                k = _key(b, title)
                # facts tables always stay, and so do short lines with numbers in them (a bonus, a price)
                boiler = seen[k] >= lim and not re.match(r'\s*<table', b) and (not re.search(r'\d', k) or len(k.split()) >= 25)
                if boiler:
                    if '\x00' not in k and len(k.split()) >= 8 and 'Category:' not in k and k not in common:
                        common.append(k)
                    continue
                if 'Category:' in k:
                    continue
                keep.append(b); words += len(_text(b).split())
            # a heading whose whole section was boilerplate goes too
            pruned = []
            for i, b in enumerate(keep):
                if re.match(r'\s*<h2', b) and (i + 1 == len(keep) or re.match(r'\s*<h2', keep[i + 1])):
                    continue
                pruned.append(b)
            if words >= min_words:
                continue
            slug = f.stem
            body = re.sub(r'<h2([^>]*)>', r'<h4\1>', ''.join(pruned)).replace('</h2>', '</h4>')
            entries.append(f'<section class="entry" id="{slug}"><h3><a href="#{slug}">{html.escape(title)}</a></h3>{body}</section>')
            moves[f'{kind}/{slug}.html'] = f'category/{cat}.html#{slug}'
            redirects.append((f'/{kind}/{slug}.html', f'/category/{cat}.html#{slug}'))
            f.unlink()
        if not entries:
            continue
        # shared explanations, once, from the original sections (headings kept)
        about = _common_sections(pages, seen, lim)
        page = cat_file.read_text(encoding='utf-8')
        name = plural.get(kind, cat)
        extra = ''
        if about:
            extra += f'<h2 id="about">About {html.escape(name.lower())}</h2>' + about
        extra += f'<h2 id="details">Details</h2><div class="entries">' + ''.join(entries) + '</div>'
        page = page.replace('</main>', extra + '</main>', 1)
        cat_file.write_text(page, encoding='utf-8')
        if not any(folder.iterdir()):
            folder.rmdir()
    if moves:
        _rewrite(out, moves)
    return {'folded': len(moves), 'redirects': redirects}


def _common_sections(pages, seen, lim):
    """Boilerplate h2 sections and long paragraphs, each once, in first-seen order."""
    done, parts = set(), []
    for title, bl in pages.values():
        i = 0
        while i < len(bl):
            b = bl[i]; k = _key(b, title)
            if re.match(r'\s*<h2', b):
                sec = [b]; j = i + 1
                while j < len(bl) and not re.match(r'\s*<h2', bl[j]):
                    if 'Category:' not in _text(bl[j]):
                        sec.append(bl[j])
                    j += 1
                ks = [_key(x, title) for x in sec]
                if all(seen[x] >= lim and '\x00' not in x for x in ks) and len(sec) > 1 and not any(re.search(r'\d', x) for x in ks[1:]) and ks[0] not in done and 'How to get' not in ks[0] and ks[0] != 'Effects':
                    done.add(ks[0]); parts.append(''.join(sec).replace('<h2', '<h3').replace('</h2>', '</h3>'))
                i = j; continue
            if seen[k] >= lim and '\x00' not in k and len(k.split()) >= 8 and 'Category:' not in k and k not in done and not re.match(r'\s*<table', b):
                done.add(k); parts.append(b)
            i += 1
    return ''.join(parts)


def _rewrite(out, moves):
    """Point every link and data reference at the folded entries."""
    kinds = sorted({m.split('/')[0] for m in moves})
    rx = re.compile(r'(?<![\w-])(' + '|'.join(map(re.escape, kinds)) + r')/([\w-]+)\.html')
    def sub(m):
        return moves.get(f'{m.group(1)}/{m.group(2)}.html', m.group(0))
    for f in out.rglob('*'):
        if not f.is_file() or f.suffix not in ('.html', '.js', '.json') or f.relative_to(out).parts[0] == 'pack':
            continue
        s = f.read_text(encoding='utf-8')
        t = rx.sub(sub, s)
        if t != s:
            f.write_text(t, encoding='utf-8')
