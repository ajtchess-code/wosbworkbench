"""In-game style shipyard for the Compendium's Ships page.

Layout, stars and premium badges follow the game's Shipyard screen (ported from the
Band of Misfits wiki's ShipyardTree). Ship art ships with the Workbench in viewer/shipyard.
"""
from __future__ import annotations

import html
import re
import shutil
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent / 'viewer' / 'shipyard'

GROUPS = [
    ('antilia', 'ANTILIA', [(2, ['Southampton', 'Falmouth', 'Mordaunt', 'Bonhomme Richard']),
                            (0, ['Pickle', 'Fair American', 'Black Wind', 'Essex', 'Anson', 'Sans Pareil', 'Victory']),
                            (2, ['Rota', 'Constitution', 'Bellona'])]),
    ('espanol', 'ESPAÑOL', [(1, ['Le Cerf', 'La Creole', 'Surprise', 'Iberia']),
                            (0, ['Friede', 'Mercury', 'Buen Viento', 'San Martin', 'Le Saint Louis', 'La Sirene', 'La Couronne']),
                            (0, ['La Salamandre', 'Le Requin', 'Diana', 'Friedrich Wilhelm', 'San Leandro', 'Montanes'])]),
    ('kai', 'KAI & SEVERIA', [(0, ['Horizont', 'Polacca', 'Russia', 'Qing Long', 'Poltava', 'Ingermanland']),
                              (1, ['Phoenix', 'Tie Long', 'Three Hierarchs', 'Georgy Pobedonosec', 'St. Pavel', '12 Apostolov'])]),
    ('empire', 'EMPIRE', [(0, ['Balloon', 'Black Prince', 'Devourer', 'Deadfish', 'Octopus', 'Huracan'])]),
    ('premium', 'PREMIUM AND UNIQUE SHIPS', [(1, ['Savannah', 'Eagle', 'Red Arrow', 'Prins Willem', 'Neptuno', 'Firestorm']),
                                             (1, ['Golden Apostle', 'Axel Thorsen', 'Sparrow', 'Shen', 'Adventure', 'Santisima Trinidad']),
                                             (1, ['Shunsen', 'Kwee Song', 'Flying Cloud', 'San Juan Nepomuceno', 'Azov', 'De Zeven Provincien']),
                                             (3, ['Kobukson', 'Vasa', 'Sovereign']),
                                             (5, ['Redoutable', 'La Royale'])]),
    ('event', 'EVENT SHIPS', [(0, ['Leopard'])]),
]
STARS = {'essex': 'silver', 'anson': 'gold', 'victory': 'gold', 'constitution': 'silver', 'bellona': 'gold', 'sanmartin': 'gold',
         'lacouronne': 'gold', 'poltava': 'silver', '12apostolov': 'gold', 'prinswillem': 'gold', 'neptuno': 'gold', 'adventure': 'gold',
         'santisimatrinidad': 'gold', 'dezevenprovincien': 'gold', 'sovereign': 'gold', 'redoutable': 'gold'}
PREMIUM = {'savannah', 'eagle', 'redarrow', 'prinswillem', 'neptuno', 'firestorm', 'goldenapostle', 'axelthorsen', 'sparrow', 'shen',
           'adventure', 'santisimatrinidad', 'shunsen', 'kweesong', 'flyingcloud', 'sanjuannepomuceno', 'azov', 'dezevenprovincien',
           'kobukson', 'vasa', 'sovereign', 'redoutable', 'laroyale'}
ALIASES = {'horizon': 'horizont', 'redoubtable': 'redoutable', 'twelveapostolov': '12apostolov', '12aspotolov': '12apostolov',
           'santissimatrinidad': 'santisimatrinidad'}
SAILS = [
    '<path d="M21 7L8 26h13z" fill="#ede8d2"/><path d="M25 6l12 19H25z" fill="#f4eed8"/>',
    '<path d="M21 9L7 27h14z" fill="#eee5c8"/><path d="M25 10l12 17H25z" fill="#ded1aa"/><path d="M9 24h30" stroke="#9e8d65" stroke-width="1"/>',
    '<path d="M20 8L9 27h11z" fill="#e9e3cd"/><path d="M25 5l13 22H25z" fill="#d9cca8"/><path d="M5 28h34" stroke="#b9a981" stroke-width="1.4"/>',
]


def key(name) -> str:
    k = unicodedata.normalize('NFKD', str(name or '')).encode('ascii', 'ignore').decode().lower()
    k = re.sub(r'[^a-z0-9]+', '', k)
    return ALIASES.get(k, k)


def art_index() -> dict:
    """{ship key: relative art path}; transparent cutouts win over the older thumbnails."""
    out = {}
    for sub in ('ships', 'cutouts'):
        for f in sorted((ROOT / sub).glob('*.png')):
            out[key(f.stem[1:] if f.stem.startswith('m') else f.stem)] = f'{sub}/{f.name}'
    return out


def copy_assets(out_assets: Path, background: Path | None = None) -> bool:
    """Copy shipyard art into assets/shipyard; returns True when the game's shipyard background was found."""
    dst = out_assets / 'shipyard'
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(ROOT, dst, ignore=shutil.ignore_patterns('shipyard-bg.css'))
    if background and background.is_file():
        shutil.copyfile(background, dst / 'shipyard_background.png')
        (dst / 'shipyard.css').write_text((ROOT / 'shipyard.css').read_text(encoding='utf-8') + (ROOT / 'shipyard-bg.css').read_text(encoding='utf-8'), encoding='utf-8')
        return True
    return False


def _fmt(v, d=0):
    try:
        return f'{float(v):,.{d}f}'
    except (TypeError, ValueError):
        return '—'


def render(ships: list[dict], href, depth: int = 1) -> str:
    """ships: [{name, rank, cls, hp, speed, mob, armor, crew, hold}]; href(ship) -> page url relative to the site root."""
    up = '../' * depth
    arts = art_index()
    by = {}
    for s in ships:
        by.setdefault(key(s['name']), s)
    used = set()

    def tile(s, premium, column):
        k = key(s['name']); star = STARS.get(k)
        art = arts.get(k)
        img = (f'<img class="shipyardGameShipImg" src="{up}assets/shipyard/{art}" alt="" loading="lazy">' if art else
               '<span class="shipyardGameNoArt" aria-hidden="true">⛵</span>')
        badge = '<span class="shipyardGamePremiumIcon" title="Premium or unique hull">✥</span>' if premium and k in PREMIUM else ''
        stats = ''.join(f'<span><small>{lab}</small><b>{val}</b></span>' for lab, val in (
            ('Hull', _fmt(s.get('hp'))), ('Speed', _fmt(s.get('speed'), 1)), ('Mnv', _fmt(s.get('mob'))),
            ('Armor', _fmt(s.get('armor'), 1)), ('Crew', _fmt(s.get('crew'))), ('Hold', _fmt(s.get('hold')))))
        return (f'<div class="shipyardGameFleetSlot" style="grid-column:{column}">'
                f'<a class="shipyardGameShip shipyardGameShip-{k}" href="{up}{href(s)}" aria-label="Open {html.escape(s["name"])}">'
                f'<span class="shipyardGameShipArt">{img}</span>'
                f'<span class="shipyardGameShipName">{badge}{html.escape(s["name"])}</span>'
                f'<span class="shipyardGameShipStar {star or "none"}">{"★" if star else "&nbsp;"}</span>'
                f'<span class="shipyardGameHover" role="tooltip"><strong>{html.escape(s["name"])}</strong>'
                f'<em>Rate {s.get("rank") or "—"}{" · " + html.escape(str(s["cls"])) if s.get("cls") else ""}</em>{stats}<i>Click for ship details</i></span></a></div>')

    def section(gid, label, rows):
        body = []
        for ri, (offset, names) in enumerate(rows):
            cells = []
            for i, n in enumerate(names):
                s = by.get(key(n))
                if not s or key(s['name']) in used:
                    continue
                used.add(key(s['name'])); cells.append(tile(s, gid == 'premium', offset + i + 1))
            if cells:
                body.append(f'<div class="shipyardGameRow"><span class="shipyardGameSail shipyardGameSail-{ri % 3}" aria-hidden="true">'
                            f'<svg viewBox="0 0 44 38" fill="none"><path d="M10 28.5h26l-4.5 4H14.5z" fill="#dbcba5"/><path d="M23 4.5v25" stroke="#a4987b" stroke-width="1.3"/>{SAILS[ri % 3]}</svg></span>'
                            f'<div class="shipyardGameFleet"><span class="shipyardGameWave" aria-hidden="true"></span><div class="shipyardGameFleetGrid">{"".join(cells)}</div></div></div>')
        if not body:
            return ''
        crest = (f'<span class="shipyardGameOtherGlyph" aria-hidden="true">{"★" if gid == "event" else "✦"}</span>' if gid in ('event', 'other')
                 else f'<img src="{up}assets/shipyard/crest-{gid}.png" alt="" loading="lazy">')
        return (f'<section class="shipyardGameFaction shipyardGame-{gid}" aria-label="{label} shipyard"><div class="shipyardGameFactionLabel">{crest}'
                f'<strong>{label}</strong></div><div class="shipyardGameRows">{"".join(body)}</div></section>')

    sections = [section(g, l, r) for g, l, r in GROUPS]
    extra = sorted((s for s in ships if key(s['name']) not in used), key=lambda s: s['name'])
    if extra:
        sections.append(section('other', 'OTHER SHIPS', [(0, [s['name'] for s in extra[i:i + 7]]) for i in range(0, len(extra), 7)]))
    return (f'<link rel="stylesheet" href="{up}assets/shipyard/shipyard.css"><div class="shipyardWrap"><div class="shipyardGameTree">'
            '<div class="shipyardGameHeading"><span>THE ARCHIPELAGO SHIPYARDS</span><span>Hover for ship statistics · Select a vessel to open details</span></div>'
            f'<div class="shipyardGameViewport" tabindex="0"><div class="shipyardGameSections">{"".join(sections)}</div></div>'
            '<span class="shipyardGameMobileHint">Swipe sideways to explore the complete ship tree on smaller screens.</span></div></div>')
