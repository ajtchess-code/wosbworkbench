"""Extra wiki pages: Special Crew, consumables, captain ranks, Elite status, sails compared and lanterns, plus the
build-cost and Elite sections on ship pages.

Rules that the game keeps in code rather than in data tables (Elite status costs, build times, quick-finish price,
the rank cap and the consumables list) are in ``data/game_rules.json`` and ``data/consumables.json``, read from the
current game version.
"""
from __future__ import annotations

import html
import json
import re
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
            ic = getattr(b, 'consumable_icons', {}).get(i)
            img = f'<img class="cicon" src="../{ic}" alt="" loading="lazy" width="40" height="40">' if ic else ''
            rows.append([img + f'<b>{_e(name)}</b>', _e(desc), f'{it["cooldown"]} s' if it['cooldown'] else '—', f'{it["duration"]} s' if it['duration'] else 'instant',
                         recipe or 'Shop or rewards only', _e('; '.join(n for n in notes if n))])
        body.append(f'<h2 id="{cat.lower()}">{cat}</h2>' + _table(['Consumable', 'What it does', 'Cooldown', 'Lasts', 'Crafting cost', 'Notes'], rows))
        fx_items = []
        for it in lst:
            if not it['effects']:
                continue
            i = it['index']; ic = getattr(b, 'consumable_icons', {}).get(i)
            img = f'<img class="ticon" src="../{ic}" alt="" loading="lazy" width="28" height="28">' if ic else ''
            fx_items.append(([img + _e(t.get(f'item_name{i}')), f'{it["cooldown"]} s' if it['cooldown'] else '—',
                              f'{it["duration"]} s' if it['duration'] else 'instant'], [(c, v) for c, v in it['effects']]))
        if len(fx_items) > 1:
            body.append(f'<h3 id="{cat.lower()}-compare">{cat} compared</h3>' + effect_matrix(fx_items, ['Consumable', 'Cooldown', 'Lasts']))
        if cat == 'Repairs':
            rep = []
            for it in lst:
                fx = dict((c, v) for c, v in it['effects'])
                hp = fx.get('ServMendingStrength') or fx.get('ServMendingStrengthTemporal')
                if not hp or not it['cooldown']:
                    continue
                kind = 'Repair' if 'ServMendingStrength' in fx else 'Temporary'
                cost = sum(q for q in it['recipe'].values())
                rep.append([_e(t.get(f'item_name{it["index"]}')), kind, f'{hp:g}', f'{fx.get("ServMendingSailes", 0):g}%' if fx.get('ServMendingSailes') else '',
                            f'{it["cooldown"]} s', f'{hp * 60 / it["cooldown"]:.0f}', f'{hp / cost:.1f}' if cost else ''])
            if rep:
                body.append('<h3 id="repair-value">Repair value</h3><p>How much durability each one gives, how much that is per minute of cooldown if you use it '
                            'every time it is ready, and per crafting material. <b>Temporary</b> durability is a shield that absorbs damage; a <b>repair</b> '
                            'restores lost durability.</p>'
                            + _table(['Consumable', 'Type', 'Durability', 'Sails', 'Cooldown', 'Per minute', 'Per material'], rep))
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


# ----------------------------------------------------------------------------------------------- upgrade slots
def slot_costs(rank):
    """[(slot, xp, resource_id, amount)] for the three locked upgrade slots of a ship of this rank (Gameplay.OpenExtraUpgradeSlotPrice)."""
    u = rules().get('upgrade_slots')
    if not u or str(rank) not in u['base_xp_by_rank']:
        return []
    base = u['base_xp_by_rank'][str(rank)]
    out = []
    for slot in (1, 2, 3):
        xp = {1: base // 4 + 250, 2: base // 2 + 500, 3: base + 1000}[slot]
        rid, _f, floor = u['price'].get(str(rank), u['price']['default'])
        div = {7: 40, 6: 10, 5: 60}.get(rank, 30)
        out.append((slot, xp, rid, max(floor, xp // div)))
    return out


def slots_html(b, rank, rec=None):
    rows = slot_costs(rank)
    if not rows:
        return ''
    names = resource_names(b.db, b.build)
    extra = int((rec or {}).get('ExtraPlacesForUpgrades') or 0)
    base = 6 + extra
    need = rules()['upgrade_slots']['third_slot_needs_branches']
    tbl = _table(['Locked slot', 'Ship XP to earn', 'Then pay'],
                 [[f'Slot {base - 3 + s}' + (f' (needs {need} researched branches)' if s == 3 else ''), f'{xp:,}', f'{amt:,} {_e(_plural(names.get(rid, "item " + str(rid)), amt))}']
                  for s, xp, rid, amt in rows], cls='wikitable')
    return (f'<h2 id="slots">Upgrade Slots</h2><p>This ship has <b>{base} upgrade slots</b>'
            + (f' (6 plus {extra} extra)' if extra else '') + '. Each Modification you fit adds one more. '
            f'The last three start locked. XP you earn sailing this ship fills them one at a time; once a slot has its XP, '
            f'you open it in port by paying the price below from your warehouse. The last slot only gathers XP once you have fully researched {need} ship branches.</p>' + tbl)


def slots_page(b):
    names = resource_names(b.db, b.build)
    need = rules().get('upgrade_slots', {}).get('third_slot_needs_branches', 5)
    rows = []
    for rank in range(1, 8):
        c = slot_costs(rank)
        if c:
            rows.append([f'Rank {rank}'] + [f'{xp:,} XP + {amt:,} {_e(_plural(names.get(rid, "item " + str(rid)), amt))}' for _s, xp, rid, amt in c])
    if not rows:
        return None
    return ('<p>Every ship has 6 upgrade slots, plus any extra the ship comes with, plus one for each Modification fitted. '
            'The <b>last three</b> start locked. XP earned while sailing that ship fills them in order, and once a slot has its XP '
            'you open it in port by paying from your warehouse. The third locked slot only gathers XP after you have fully researched '
            f'{need} ship branches. Ships that come fully researched have the first two open already.</p>'
            + _table(['Ship rank', 'First locked slot', 'Second', 'Third'], rows, cls='wikitable'))


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
    if rank:
        sl = slots_html(b, rank, rec)
        if sl:
            out.append(sl)
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
    items = []
    for r in sorted(ups, key=lambda r: r['_title']):
        url = b.urls.get(('upgrade', r['_title'].casefold())); ic = b.icons.get(('upgrade', r['_title'].casefold()))
        img = f'<img class="ticon" src="../{ic}" alt="" loading="lazy" width="28" height="28">' if ic else ''
        items.append(([img + (f'<a href="../{url}">{_e(r["_title"])}</a>' if url else _e(r['_title'])),
                       'Budget' if str(r.get('LowCost')).lower() == 'true' else ''], _parse_fx(r.get('EffectsBoost'))))
    return ('<p>Sail upgrades go in a ship\'s sail slot. Only one can be fitted at a time, so they trade speed, handling and protection against each other.</p>'
            '<h2 id="compare">Side by Side</h2><p>One column per stat; an empty cell means the sail does not change it. Click a heading to sort, '
            'or use the drop-downs to filter. <b>Cruising Mode</b> is full sail: the ship builds up extra speed over time.</p>'
            + effect_matrix(items, ['Sails', 'Version'])
            + '<h2 id="details">Details</h2>' + _table(['Sails', 'Effects', 'Budget version', 'Notes'], rows))


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
        imgs = ''.join(_medal_img(x, 'medal', 40) for x in getattr(b, 'medal_icons', {}).get(title, []) if x)
        rows.append([imgs, ' + '.join(link(a) for a in aids), levels])
    for k, text in m.get('other_titles', {}).items():
        imgs = ''.join(_medal_img(x, 'medal', 40) for x in getattr(b, 'medal_icons', {}).get(k, []) if x)
        rows.append([imgs, _e(text), '—'])
    return ('<p>A <b>captain title</b> shows next to your name and on your ship. You earn titles through achievements. Many come in three medal levels, '
            '<b>bronze</b>, <b>silver</b> and <b>gold</b>: the numbers are how many times you must earn the achievement for each level. '
            'Where a title needs two achievements, either one counts towards it.</p>'
            + _table(['Medal', 'Achievement(s)', 'Bronze · Silver · Gold'], rows))


def _plural(name, n):
    return name + 's' if n != 1 and name.endswith(('Mark', 'Shot')) else name


# ----------------------------------------------------------------------------------------------- icons the catalog links miss
def _save_icon(im, dst, size):
    from PIL import Image
    im = im.convert('RGBA'); bbox = im.getchannel('A').getbbox()
    if bbox:
        im = im.crop(bbox)
    im.thumbnail((size, size), Image.LANCZOS)
    dst.parent.mkdir(parents=True, exist_ok=True)
    im.save(dst, 'WEBP', quality=88, method=4)


def _find(roots, rel):
    return next((root / rel for root in roots if (root / rel).is_file()), None)


def medal_cells():
    a = medals().get('medal_atlas')
    if not a:
        return []
    out = []
    for x0, y0, rows, cols, drop in a['blocks']:
        cells = [(x0 + a['pitch'] * c, y0 + a['pitch'] * r) for r in range(rows) for c in range(cols)]
        out += cells[:len(cells) - drop] if drop else cells
    return out


def extra_icons(b, roots, size=128):
    """Achievement pictures (Items/Achievements/<ID>.png), lantern and figurehead icons cut from the Icons sheet,
    consumable icons, and the bronze / silver / gold title medals cut from the objects atlas."""
    from PIL import Image
    n = 0
    slug = getattr(b, '_slug_fn', None)
    import wiki_site
    slug = wiki_site._slug
    for r in b.entities.get('achievement', []):
        key = ('achievement', r['_title'].casefold())
        src = None if key in b.icons else _find(roots, f'Images/SharedArchive/Items/Achievements/{r.get("ID")}.png')
        if src:
            rel = f'assets/icons/achievement/{slug(r["_title"])}.webp'
            try:
                _save_icon(Image.open(src), b.out / rel, size); b.icons[key] = rel; n += 1
            except OSError:
                pass
    sheet_path = _find(roots, 'Images/LooseFiles/Data/Textures/Icons.png')
    if sheet_path:
        sheet = Image.open(sheet_path)
        for r in b.entities.get('cosmetic', []):
            key = ('cosmetic', r['_title'].casefold()); parts = str(r.get('IconName') or '').split()
            if key in b.icons or len(parts) != 5 or parts[0] != 'Icons':
                continue
            k = 1 if int(r.get('SourceRecord') or 0) >= 420 else 2          # ShipDesignInfo: older entries are given at half scale
            x, y, w, h = (int(v) * k for v in parts[1:])
            if x + w > sheet.width or y + h > sheet.height:
                continue
            rel = f'assets/icons/cosmetic/{slug(r["_title"])}.webp'
            _save_icon(sheet.crop((x, y, x + w, y + h)), b.out / rel, size); b.icons[key] = rel; n += 1
    b.consumable_icons = {}
    for c in consumables():
        src = c.get('icon') and _find(roots, f'Images/SharedArchive/Items/PowerupItems/{c["icon"]}.png')
        if src:
            rel = f'assets/icons/consumable/{c["icon"].lower()}.webp'
            try:
                _save_icon(Image.open(src), b.out / rel, size); b.consumable_icons[c['index']] = rel; n += 1
            except OSError:
                pass
    b.medal_icons = {}
    m = medals(); atlas = m.get('medal_atlas')
    apath = atlas and _find(roots, atlas['texture'])
    if apath:
        img = Image.open(apath); cells = medal_cells(); cs = atlas['cell']
        def cut(idx, name):
            if 0 <= idx < len(cells):
                x, y = cells[idx]; rel = f'assets/icons/medal/{name}.webp'
                _save_icon(img.crop((x, y, x + cs, y + cs)), b.out / rel, 96)
                return rel
        for title, idxs in atlas['levels'].items():
            b.medal_icons[title] = [cut(i, f'{title.lower()}-{lvl}') for i, lvl in zip(idxs, ('bronze', 'silver', 'gold'))]
        for title, i in atlas['single'].items():
            b.medal_icons[title] = [cut(i, title.lower())]
    return n


def _medal_img(src, alt, px=48):
    return f'<img class="medal" src="../{src}" alt="{_e(alt)}" title="{_e(alt)}" width="{px}" height="{px}" loading="lazy">' if src else ''


def titles_for(aid):
    m = medals()
    return [t for t, aids in m.get('titles', {}).items() if aid in aids]


def achievement_medal_html(b, rec):
    m = medals(); aid = rec.get('ID'); out = []
    for title in titles_for(aid):
        imgs = getattr(b, 'medal_icons', {}).get(title, [])
        t = m['medal_targets'].get(aid)
        if t and len(imgs) == 3:
            cells = ''.join(f'<figure class="medal-lvl">{_medal_img(src, lvl + " medal", 64)}<figcaption><b>{lvl}</b><br>{n:,}×</figcaption></figure>'
                            for src, lvl, n in zip(imgs, ('Bronze', 'Silver', 'Gold'), t))
            out.append('<h2 id="medal">Title Medal</h2><p>Earning this achievement counts towards a captain title you can show on your ship. '
                       'The medal changes colour as you reach each level:</p><div class="medal-row">' + cells + '</div>')
        elif imgs and imgs[0]:
            out.append('<h2 id="medal">Title Medal</h2><div class="medal-row"><figure class="medal-lvl">' + _medal_img(imgs[0], 'medal', 64)
                       + '<figcaption>Earn it once</figcaption></figure></div>')
    return out


# ----------------------------------------------------------------------------------------------- comparison matrices
_NUM = re.compile(r'([+\-−]?\d[\d,]*(?:\.\d+)?)\s*(%|°|s\b)?')


def _label_and_value(code, value):
    """('Gun reload speed', '+24%') from one effect, keeping the sign flips of the wording (damage taken −14%)."""
    text = site_effects.describe(code, value)
    m = _NUM.search(text)
    if not m or code.startswith('B'):
        return text, '✓'
    knots = re.search(r'≈([\d.\-]+) knots', text)
    label = re.sub(r'\(\s*≈[^)]*\)|\(\s*(strength)?\s*\)', '', text[:m.start()] + text[m.end():])
    label = re.sub(r'\s+', ' ', label).strip(' :')
    val = m.group(1).replace('−', '-') + (m.group(2) or '')
    return label, val + (f' (≈{knots.group(1)} kn)' if knots else '')


def effect_matrix(items, lead_heads, min_share=1):
    """items: [(lead_cells, [(code, value)])] -> one table with a column for every effect any item has."""
    cols, seen = [], {}
    for _lead, fx in items:
        for code, v in fx:
            lab, _ = _label_and_value(code, v)
            if lab not in seen:
                seen[lab] = 0; cols.append(lab)
            seen[lab] += 1
    cols = [c for c in cols if seen[c] >= min_share]
    cols.sort(key=lambda c: -seen[c])
    rows = []
    for lead, fx in items:
        vals = {}
        for code, v in fx:
            lab, val = _label_and_value(code, v)
            vals[lab] = val
        rows.append(list(lead) + [_e(vals.get(c, '')) for c in cols])
    return _table(lead_heads + [_e(c) for c in cols], rows)


def _parse_fx(text):
    return [(m.group(1), m.group(2)) for m in re.finditer(r'((?:Serv)?[PMBC]?[A-Z][A-Za-z0-9_]+)\s*([+-]?\d+(?:\.\d+)?)?', str(text or ''))]
