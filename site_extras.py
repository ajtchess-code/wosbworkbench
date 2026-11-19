"""Extra wiki pages: Special Crew, consumables, captain ranks, Elite status, sails compared and lanterns, plus the
build-cost and Elite sections on ship pages.

Rules that the game keeps in code rather than in data tables (Elite status costs, build times, quick-finish price,
the rank cap and the consumables list) are in ``data/game_rules.json`` and ``data/consumables.json``, read from the
current game version.
"""
from __future__ import annotations

import html
import json
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

import site_effects

DATA = Path(__file__).resolve().parent / 'data'
CREW_GROUPS = [('Sailors', 'Sailors', 'Seamanship specialists: speed, handling, repairs, supplies and fishing.'),
               ('Combats', 'Combat', 'Gunnery and damage-control specialists.'),
               ('Pirates', 'Pirates', 'Boarding, scouting and plunder specialists.'),
               ('Adventurers', 'Adventurers', 'Explorers: more loot, rare items and better chances of finding other specialists.')]
CONSUMABLE_CATS = {'mending': 'Repairs', 'items_cat_up': 'Boosts', 'forGroup': 'Squadron', 'items_cat_guild': 'Guild'}


def _e(s):
    return html.escape(str(s if s is not None else ''), quote=True)


def rules():
    try:
        return json.loads((DATA / 'game_rules.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def consumables():
    try:
        return json.loads((DATA / 'consumables.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []


def texts(db):
    out = {}
    for raw, in db.conn.execute("SELECT raw_json FROM records WHERE dataset IN ('English_Text','System_English_Text')"):
        d = json.loads(raw)
        if d.get('Key') and d.get('English'):
            out.setdefault(d['Key'], d['English'])
    return out


def records(db, dataset, build='Steam'):
    rows = db.conn.execute('SELECT raw_json, source_root FROM records WHERE dataset=?', (dataset,)).fetchall()
    roots = {r for _, r in rows}
    pick = build if build in roots else ('Game' if 'Game' in roots else next(iter(roots), None))
    return [json.loads(r) for r, root in rows if root == pick]


def resource_names(db, build='Steam'):
    out = {}
    for r in records(db, 'Resources', build):
        rid = str(r.get('ID') or '')
        if rid.startswith('res_') and rid[4:].isdigit():
            out[int(rid[4:])] = r.get('EnglishName') or rid
    return out


def _table(heads, rows, cls='wikitable sortable'):
    return (f'<table class="{cls}"><thead><tr>' + ''.join(f'<th>{h}</th>' for h in heads) + '</tr></thead><tbody>'
            + ''.join('<tr>' + ''.join(f'<td>{c}</td>' for c in r) + '</tr>' for r in rows) + '</tbody></table>')


def effects_html(*codes):
    lines = []
    for c in codes:
        lines += site_effects.describe_all(c)
    return '<br>'.join(_e(x) for x in lines) or '—'


# ----------------------------------------------------------------------------------------------- Special Crew
def special_crew(b):
    t = b.texts
    rows = [r for r in records(b.db, 'UnitsInfo', b.build) if str(r.get('ID', '')).startswith('unit_special')]
    if not rows:
        return None
    groups = defaultdict(list)
    for r in rows:
        groups[r.get('Options') or 'Other'].append(r)
    body = ['<p>Specialists (Special Crew) are rare crew members who give the whole ship a bonus. Each one takes a crew slot, serves a limited term and asks for extra wages '
            'while you are at sea. They are separate from your ordinary sailors and boarding crew (Seamen, Soldiers, Mercenaries and Musketeers).</p>',
            '<h2 id="where">Where to find them</h2><ul>'
            '<li><b>Taverns</b>: what you meet depends on the place. Towns offer <b>Combat</b> and <b>Sailors</b> specialists; <b>Pirates</b> turn up in pirate coves and pirate-held towns.</li>'
            '<li><b>At sea</b>: sometimes rescued after battles, and some come from Imperial ships.</li>'
            '<li><b>Taking captives</b>: the chance depends on the ship you capture, and is higher in game modes.</li>'
            '<li><b>Your Personal Island</b>: recruiting there finds rarer and more interesting people than a tavern.</li>'
            '<li><b>Adventurers</b> raise these chances further (Rescuer, Explorer, Seafarer).</li></ul>'
            '<p>Dismissing unused specialists frees their slots and slightly raises the chance of finding a new one in taverns and modes.</p>']
    links = []
    for key, label, blurb in CREW_GROUPS:
        items = groups.get(key)
        if not items:
            continue
        links.append(f'<a href="#{key.lower()}">{label}</a>')
        tr = []
        for r in sorted(items, key=lambda r: t.get(r['ID'] + '_name', r['ID'])):
            name = t.get(r['ID'] + '_name') or r['ID']
            per = ''
            if r.get('EffectPerSailor'):
                per = ' <small>(for every sailor of this kind on board)</small>'
            elif r.get('EffectPerBoardingUnit'):
                per = ' <small>(for every boarder of this kind on board)</small>'
            ic = b.icons.get(('crew', name.casefold()))
            img = f'<img class="ticon" src="../{ic}" alt="" loading="lazy" width="28" height="28">' if ic else ''
            url = b.urls.get(('crew', name.casefold()))
            nm = f'<a href="../{url}">{_e(name)}</a>' if url else _e(name)
            tr.append([img + nm, effects_html(r.get('Effect'), r.get('EffectPerSailor'), r.get('EffectPerBoardingUnit')) + per])
        body.append(f'<h2 id="{key.lower()}">{label}</h2><p>{_e(blurb)}</p>' + _table(['Specialist', 'What it does'], tr))
    body.insert(1, '<p class="toc-inline">Jump to: ' + ' · '.join(links + ['<a href="#where">Where to find them</a>']) + '</p>')
    return ''.join(body)


def crew_titles(db, build='Steam'):
    """ID -> in-game name for every crew unit (Pilot, Lucky One, Soldier...)."""
    t = texts(db)
    return {r['ID']: t[r['ID'] + '_name'] for r in records(db, 'UnitsInfo', build) if r.get('ID') and (r['ID'] + '_name') in t}


# ----------------------------------------------------------------------------------------------- consumables
def consumables_page(b):
    items = consumables()
    if not items:
        return None
    t = b.texts; names = resource_names(b.db, b.build)
    by = defaultdict(list)
    for it in items:
        if f'item_name{it["index"]}' in t:
            by[CONSUMABLE_CATS.get(it['category'], 'Other')].append(it)
    body = ['<p>Consumables go in your ship\'s consumable slots and are used in battle: repair kits and patches, speed and defense boosts, special powders, '
            'and signals that help your whole squadron. Each has a cooldown before you can use it again. Sinking NPS or players can also reward a random consumable '
            'in an extra temporary slot. Crafting costs can be lowered by a captain bonus and an achievement bonus (−5%).</p>']
    nav = []
    for cat in ('Repairs', 'Boosts', 'Squadron', 'Guild', 'Other'):
        lst = by.get(cat)
        if not lst:
            continue
        nav.append(f'<a href="#{cat.lower()}">{cat}</a>')
        rows = []
        for it in lst:
            i = it['index']; name = t.get(f'item_name{i}'); desc = t.get(f'item_desc{i}', '').replace('#', '')
            recipe = ', '.join(f'{q} × {_e(names.get(int(r), "item " + str(r)))}' for r, q in it['recipe'].items())
            if it.get('gold'):
                recipe += (', ' if recipe else '') + f'{it["gold"]:,} gold'
            limit = it['options'].get('DisallowInLowRangShips')
            notes = []
            if limit:
                notes.append(f'not on rank {int(limit) + 1}–7 ships' if int(limit) < 7 else '')
            if it['options'].get('AllowInterrupt') == 'true':
                notes.append('can be cancelled early')
            rows.append([f'<b>{_e(name)}</b>', _e(desc), f'{it["cooldown"]} s' if it['cooldown'] else '—', f'{it["duration"]} s' if it['duration'] else 'instant',
                         recipe or 'Shop or rewards only', _e('; '.join(n for n in notes if n))])
        body.append(f'<h2 id="{cat.lower()}">{cat}</h2>' + _table(['Consumable', 'What it does', 'Cooldown', 'Lasts', 'Crafting cost', 'Notes'], rows))
    body.insert(1, '<p class="toc-inline">Jump to: ' + ' · '.join(nav) + '</p>')
    return ''.join(body)


# ----------------------------------------------------------------------------------------------- captain ranks
def ranks_page(b):
    ri = sorted(records(b.db, 'RangInfo', b.build), key=lambda r: r.get('SourceRecord') or 0)
    xp = [int(r.get('Xp') or 0) for r in ri]
    if not xp:
        return None
    rows, total = [], 0
    for i, x in enumerate(xp):
        total += x
        rows.append([f'{i + 1} → {i + 2}', f'{x:,}', f'{total:,}'])
    cap = len(xp) + 1
    return ('<p>Your captain rank goes up as you earn XP. Higher ranks unlock bigger ships, skill points and more. '
            f'There are {len(xp)} steps to the top rank, <b>rank {cap}</b>.</p>'
            f'<p>After rank {cap}, every further level costs the same <b>{xp[-1]:,} XP</b> as the last step. You no longer gain ranks; '
            'instead, each level earned gives a reward.</p>'
            f'<p>Reaching rank {cap} takes <b>{total:,} XP</b> in total.</p>'
            + _table(['Rank', 'XP needed', 'Total XP so far'], rows))


# ----------------------------------------------------------------------------------------------- Elite status
def elite_table(rank):
    r = rules().get('elite_status', {})
    costs = r.get('costs', {}).get(str(rank))
    if not costs:
        return None
    rows = []; tx = tg = tc = 0
    for lvl, (xp, gold, coins) in enumerate(costs, 1):
        tx += xp; tg += gold; tc += coins
        rows.append([str(lvl), f'{xp:,}', f'{gold:,}', f'{coins:,}', _e(r['benefits'].get(str(lvl), ''))])
    rows.append(['<b>All 6</b>', f'<b>{tx:,}</b>', f'<b>{tg:,}</b>', f'<b>{tc:,}</b>', ''])
    return _table(['Level', 'Elite XP', 'Gold', 'or Coins', 'Unlocks'], rows, cls='wikitable')


def elite_page(b):
    r = rules().get('elite_status')
    if not r:
        return None
    body = ['<p>Elite status is a ship upgrade with six levels, for ships of rank 1 to 5. The ship earns <b>Elite XP</b> as you sail it. '
            'Each level is bought either with Elite XP plus gold, or with Coins instead. Ships that are Elite to begin with have full status from the start. '
            'Letters Patent items can add Elite XP (10,000 each), add one level or grant full status.</p>',
            '<h2>What each level gives</h2><ul>' + ''.join(f'<li><b>Level {k}</b>: {_e(v)}</li>' for k, v in sorted(r['benefits'].items())) + '</ul>']
    for rank in range(1, 6):
        tbl = elite_table(rank)
        if tbl:
            body.append(f'<h2 id="rank{rank}">Rank {rank} ships</h2>' + tbl)
    return ''.join(body)


# ----------------------------------------------------------------------------------------------- ship build costs
def ship_build_html(b, rec):
    """Build materials, shipyard time, instant-finish price and Elite status for one ship page."""
    sid = rec.get('ID') or rec.get('StaticInfoID')
    if not hasattr(b, '_ship_mats'):
        mats = defaultdict(list)
        for m in records(b.db, 'Ship_Materials', b.build):
            mats[str(m.get('ShipID'))].append(m)
        b._ship_mats = mats
        b._ship_cons = {str(c.get('ShipID')): c for c in records(b.db, 'Ship_Construction', b.build)}
    mats = b._ship_mats.get(str(sid), []); cons = b._ship_cons.get(str(sid), {})
    rank = rec.get('ShipRank') or rec.get('Rank')
    try:
        rank = int(rank)
    except (TypeError, ValueError):
        rank = None
    rr = rules()
    out = []
    if mats or cons:
        rows = [[_e(m.get('ResourceEnglishName')), f'{int(m.get("BaseQuantity") or 0):,}'] for m in sorted(mats, key=lambda m: -(m.get('BaseQuantity') or 0)) if m.get('BaseQuantity')]
        secs = None
        if rank and str(rank) in rr.get('shipyard_seconds', {}):
            secs = rr['shipyard_seconds'][str(rank)]
        cool = str(rec.get('Coolness') or '')
        if 'Elite' in cool or 'Unique' in cool:
            secs = 0
        def dur(s):
            return 'instant' if not s else (f'{s // 3600} h' + (f' {s % 3600 // 60} min' if s % 3600 else '') if s >= 3600 else f'{s // 60} min')
        facts = []
        if secs is not None:
            facts.append(f'<b>Shipyard time:</b> {dur(secs)}.')
        if rank:
            mn = max(0, (8 - rank) * 10)
            marks = next((int(m.get('BaseQuantity') or 0) for m in mats if str(m.get('ResourceID')) == '37'), 0)
            full = max(mn, marks)
            facts.append(f'<b>Finish instantly:</b> {full:,} Battle Marks at the start, falling as the ship gets built, never below {mn:,}.')
        out.append('<h2 id="build">Building This Ship</h2><p>' + ' '.join(facts) + '</p>'
                   + (('<p>Base materials, before port, guild and event discounts:</p>' + _table(['Material', 'Amount'], rows, cls='wikitable')) if rows else ''))
    if rank and 1 <= rank <= 5:
        tbl = elite_table(rank)
        if tbl:
            cool = str(rec.get('Coolness') or '')
            note = ' This ship is Elite, so it has full status from the start.' if 'Elite' in cool else ''
            out.append(f'<h2 id="elite">Elite Status</h2><p>Six levels, bought with Elite XP and gold, or with Coins.{note} '
                       '<a href="../guide/elite-status.html">How Elite status works</a>.</p>' + tbl)
    return out


# ----------------------------------------------------------------------------------------------- sails, lanterns
def sails_page(b):
    ups = [r for r in b.entities.get('upgrade', []) if r.get('Category') == 'Sailes']
    if not ups:
        return None
    rows = []
    for r in sorted(ups, key=lambda r: r['_title']):
        url = b.urls.get(('upgrade', r['_title'].casefold()))
        ic = b.icons.get(('upgrade', r['_title'].casefold()))
        img = f'<img class="ticon" src="../{ic}" alt="" loading="lazy" width="28" height="28">' if ic else ''
        rows.append([img + (f'<a href="../{url}">{_e(r["_title"])}</a>' if url else _e(r['_title'])), effects_html(r.get('EffectsBoost')),
                     'yes' if str(r.get('LowCost')).lower() == 'true' else '', _e(r.get('EnglishDescription') or '')])
    return ('<p>Sail upgrades go in a ship\'s sail slot. Only one can be fitted at a time, so they trade speed, handling and protection against each other.</p>'
            + _table(['Sails', 'Effects', 'Budget version', 'Notes'], rows))


def lanterns_page(b):
    lan = [r for r in b.entities.get('cosmetic', []) if r.get('Category') == 'Satellite']
    if not lan:
        return None
    from wiki_site import _fmt
    rows = []
    for r in sorted(lan, key=lambda r: r['_title']):
        ic = b.icons.get(('cosmetic', r['_title'].casefold()))
        img = f'<img class="ticon" src="../{ic}" alt="" loading="lazy" width="40" height="40">' if ic else ''
        bonus = site_effects.describe_pair(r['BonusEffectType'], r.get('BonusEffectValue')) if r.get('BonusEffectType') not in (None, '', 'None') else ''
        rows.append([img + _e(r['_title']), _e(bonus) or '—', _e(_fmt(r.get('InShop'), 'shop') or ''), _e(r.get('EnglishDescription') or '')])
    return ('<p>Lanterns hang on your ship as a cosmetic. Like figureheads, some also give a small bonus. Try them on any ship in the '
            '<a href="../tools/ship-viewer.html">3D ship viewer</a>.</p>' + _table(['Lantern', 'Bonus', 'How to get', 'Description'], rows))


# ----------------------------------------------------------------------------------------------- achievements
def medals():
    try:
        return json.loads((DATA / 'achievement_medals.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def enrich_achievements(b):
    m = medals()
    if not m:
        return
    names = resource_names(b.db, b.build)
    ships = {str(r.get('ID')): r['_title'] for r in b.entities.get('ship', [])}
    unlock = defaultdict(list)
    for sid, needs in m.get('ship_unlocks', {}).items():
        for aid, count in needs:
            if sid in ships:
                unlock[aid].append(ships[sid] + (f' (×{count})' if count > 1 else ''))
    for r in b.entities.get('achievement', []):
        aid = r.get('ID')
        t = m['medal_targets'].get(aid)
        if t:
            r['_medal'] = f'Bronze {t[0]:,} · Silver {t[1]:,} · Gold {t[2]:,}'
        elif any(aid in v for v in m['titles'].values()):
            r['_medal'] = 'Yes'
        rw = m['rewards'].get(aid)
        if rw:
            parts = [f'{q:,} {names.get(int(i), "item " + i)}' for i, q in rw.get('items', {}).items()]
            if rw.get('coins'):
                parts.append(f'{rw["coins"]:,} Coins')
            if rw.get('text_key') and b.texts.get(rw['text_key']):
                parts.append(b.texts[rw['text_key']])
            r['_reward'] = ', '.join(parts)
        if unlock.get(aid):
            r['_unlocks'] = ', '.join(unlock[aid])


def titles_page(b):
    m = medals()
    if not m:
        return None
    ach = {r.get('ID'): r for r in b.entities.get('achievement', [])}
    def link(aid):
        r = ach.get(aid)
        if not r:
            return _e(aid)
        url = b.urls.get(('achievement', r['_title'].casefold()))
        ic = b.icons.get(('achievement', r['_title'].casefold()))
        img = f'<img class="ticon" src="../{ic}" alt="" loading="lazy" width="28" height="28">' if ic else ''
        return img + (f'<a href="../{url}">{_e(r["_title"])}</a>' if url else _e(r['_title']))
    rows = []
    for title, aids in m['titles'].items():
        t = [m['medal_targets'].get(a) for a in aids]
        if any(t):
            levels = ' / '.join(f'{x[0]:,} · {x[1]:,} · {x[2]:,}' for x in t if x)
        else:
            levels = 'Earn it once'
        rows.append([' + '.join(link(a) for a in aids), levels])
    for _k, text in m.get('other_titles', {}).items():
        rows.append([_e(text), '—'])
    return ('<p>A <b>captain title</b> shows next to your name and on your ship. You earn titles through achievements. Many come in three medal levels, '
            '<b>bronze</b>, <b>silver</b> and <b>gold</b>: the numbers are how many times you must earn the achievement for each level. '
            'Where a title needs two achievements, either one counts towards it.</p>'
            + _table(['Achievement(s)', 'Bronze · Silver · Gold'], rows))
