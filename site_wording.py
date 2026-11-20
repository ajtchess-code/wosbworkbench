"""Reader-facing wording for the public wiki: talk about "the game", never about how the facts were gathered.

Runs over the text of every page (not over markup, scripts or styles). It rewrites phrases such as "the game client"
to "the game", and drops sentences that mention the team's own tools (Workbench, datamining, scans, recovery).
"""
from __future__ import annotations

import re
from pathlib import Path

PHRASES = [
    (r"\bthe decompiled client\b", 'the game'), (r"\bthe game client's own\b", "the game's own"), (r"\bthe game client's\b", "the game's"),
    (r"\bthe public game client\b", 'the game'), (r"\bthe game client\b", 'the game'), (r"\bgame client\b", 'game'),
    (r"\b(?:is|are) not in the client\b", lambda m: ('is' if m.group(0).startswith('is') else 'are') + " not shown by the game"),
    (r"\bisn't in the client\b", "isn't shown by the game"), (r"\bin the client\b", 'in the game'), (r"\bby the client\b", 'by the game'),
    (r"\bfrom the client's\b", "from the game's"), (r"\bthe client's\b", "the game's"), (r"\bThe client's\b", "The game's"),
    (r"\bthe client\b", 'the game'), (r"\bThe client\b", 'The game'), (r"\bclient-side\b", 'in-game'), (r"\bthe Compendium's\b", "the wiki's"),
    (r"\bBy Monets (\d[\d,]*)", lambda m: f"{int(m.group(1).replace(',', '')):,} Coins"), (r"\bBy Gold (\d[\d,]*)", lambda m: f"{int(m.group(1).replace(',', '')):,} gold"),
    (r"\bMonets\b", 'Coins'), (r"\bmonets\b", 'Coins'),
    (r"\bdatamined\b", 'game'), (r"\bDatamined\b", 'Game'), (r"\bread straight from the game\b", 'taken from the game'),
]
TOOLING = re.compile(r'\b(?:WoSB Workbench|Workbench|datamin\w*|Full Recovery|recovery run|gameplay capture|capture hotkeys?|run a scan|scan report)\b', re.I)
_SENT = re.compile(r'[^.!?]*[.!?]+\s*|[^.!?]+$')


def clean_text(t):
    for pat, rep in PHRASES:
        t = re.sub(pat, rep, t)
    if TOOLING.search(t):
        t = ''.join(s for s in _SENT.findall(t) if not TOOLING.search(s))
    return t


def clean_html(page):
    parts = re.split(r'(<script\b.*?</script>|<style\b.*?</style>|<[^>]+>)', page, flags=re.S | re.I)
    for i in range(0, len(parts), 2):
        if parts[i].strip():
            parts[i] = clean_text(parts[i])
    return ''.join(parts)


def apply(out):
    out = Path(out); n = 0
    for f in out.rglob('*.html'):
        if f.relative_to(out).parts[0] == 'pack':
            continue
        s = f.read_text(encoding='utf-8'); t = clean_html(s)
        if t != s:
            f.write_text(t, encoding='utf-8'); n += 1
    return n
