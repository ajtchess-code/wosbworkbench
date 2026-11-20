"""Port trade goods and dig sites for the wiki, worked out from the game's own trading and loot rules.

Rules used (WosbTrading, IslePortInfo, WorldMapInfo, WosbLoot):
- The world map is split into 16 sea regions. Each has a danger level (0-6) and most belong to one of four economies
  (North, South, Arab, Center). A port belongs to the region under its entrance.
- Every resource marked as a trade good belongs to one economy. A port with a goods market offers each trade good of its own
  economy (60% chance per good each time the offers are drawn). Goods marked "found on islands" are never sold in ports; they
  come from dig sites instead. Ambergris is offered in small lots everywhere except Arab ports.
- Lot size: 9000 gold worth x the port's size factor x 0.7-1.3, rounded up to a hundred; neutral bays offer 60% of that.
- When you sell a trade good, a port of the good's own economy pays its base value; elsewhere it pays more the further you are
  from that economy's nearest port: base x (1 + 0.69 x f^1.3), f = clamp(2 x distance / map width, 0.14, 1). So the most a
  far port pays is +69%, the least +5%.
- Basic goods every port keeps on sale depend on the kind of port, plus whatever it produces, plus water where ports are
  supplied with it.
- Dig sites (the shovel marker), ruins and buried treasure appear on islands; what they hold scales with the region's level.
"""
import json
import math
import re
from pathlib import Path

DATA = Path(__file__).resolve().parent / 'data'

# WorldMapInfo: region colours in the regions mask, in key order; danger level per key; economy per key
REGION_COLOURS = [(158, 255, 147), (0, 255, 0), (170, 173, 255), (100, 140, 255), (0, 255, 255), (0, 0, 255), (255, 255, 0), (255, 180, 100),
                  (255, 127, 0), (255, 163, 163), (180, 110, 255), (255, 0, 102), (255, 110, 140), (255, 0, 0), (255, 0, 255), (161, 0, 255)]
REGION_LEVEL = [0, 0, 1, 1, 2, 2, 2, 3, 3, 3, 4, 4, 5, 5, 6, 6]
ECONOMY = {**{k: 'North' for k in (5, 9, 10, 13)}, **{k: 'South' for k in (7, 4, 2, 1)}, **{k: 'Arab' for k in (11, 12)}, **{k: 'Center' for k in (14, 15)}}
REGION_NAMES = ['Antillean Islands', 'Aurora Islands', 'Islas Díaz Ahogado', 'Casa Nueva', 'Sea of Conquistadors', 'Stevenson Islands', 'Danmar',
                'Lágrimas de Viudas', 'Lagonaf', 'Strait of a Thousand Dead Men', 'Friesland', 'Dragon Islands', 'Khalij al-Baharat', 'Sea of Nozul',
                'Heart of the Abyss', 'Tripolis']
ECONOMY_TEXT = {'North': 'the cold northern seas', 'South': 'the southern colonies', 'Arab': 'the Khanfar Caliphate (Arab ports)', 'Center': 'the central abyss'}
MAP_W = 14146.483
AMBERGRIS = 25
# IslePortInfo / WosbTrading: basic goods every port keeps on sale, by kind of port (resource IDs)
BASIC_ALL = (1, 13)
BASIC_BY_TYPE = {'PirateBay': (4, 12, 2, 22), 'City': (12, 2, 3, 11), 'Bay': (3, 10, 2, 21), 'NeutralBay': (3, 10, 2, 21)}
PRODUCED = {'TCoal': 12, 'TWoodID': 1, 'TCottonID': 3, 'TRumID': 2, 'TResinLaquer': 13, 'TWater': 5, 'TCopper': 11}
WATER = 5
# WosbLoot: weights of the things that appear at sea (outside events), for "how often"
SEA_FINDS = {'Fishing spot': 22, 'Fishing boat': 20, 'Small debris': 16, 'Small box': 16, 'Ship wreck': 14, 'Debris with a box': 10, 'Dig site': 10,
             'Whale': 8, 'Castaway on a raft': 3.5, 'Ruins': 1.2, 'Sunken imperial box': 1, 'Buried treasure': 0.2}
DIG_RAW = (1, 31, 32, 12)          # one of: Wood, Iron Ore, Copper Ore, Coal
DIG_FALLBACK = (22, 2, 9)          # Animals, Rum or Supplies when the region has no island goods
SUPPLIES, VOLCANIC_ORE, CHEST, VOODOO, KEY, FESTIVAL_MAP = 9, 23, 24, 38, 43, 71


def _e(s):
    import html
    return html.escape(str(s if s is not None else ''), quote=True)


class Regions:
    """The regions mask: region key at a world position (same grid layout as the shallows map)."""
    def __init__(self, im):
        im = im.convert('RGB'); self.w, self.h = im.size; px = im.load()
        self.grid = [[REGION_COLOURS.index(px[c, r]) if px[c, r] in REGION_COLOURS else -1 for c in range(self.w)] for r in range(self.h)]

    def at(self, x, y):
        import site_world
        r = int((x / site_world.WORLD_SIZE[0] + 0.5) * self.h); c = int((y / site_world.WORLD_SIZE[1] + 0.5) * self.w)
        return self.grid[min(self.h - 1, max(0, r))][min(self.w - 1, max(0, c))]


def find_regions(b):
    from PIL import Image
    cands = []
    try:
        cands += [d / 'Images' / 'SharedArchive' / 'WorldMapRegions.png' for d in b._catalog_dirs()]
    except Exception:
        pass
    cands.append(DATA / 'world-regions.png')
    for f in cands:
        try:
            if f.is_file():
                return Regions(Image.open(f))
        except Exception:
            continue
    return None


def goods(db, build='Steam'):
    """{id: {n, cost, econ, isle, npc, food}} for every trade good, from the resources' own flags."""
    import site_extras
    out = {}
    for r in site_extras.records(db, 'Resources', build):
        rid = str(r.get('ID') or '')
        if not rid.startswith('res_') or not rid[4:].isdigit():
            continue
        fx = str(r.get('Effects') or '').split()
        if 'TradingItem' not in fx:
            continue
        econ = next((e for e in ('North', 'South', 'Arab', 'Center') if e in fx), None)
        out[int(rid[4:])] = {'n': r.get('EnglishName') or rid, 'cost': int(r.get('MediumCost') or 0), 'econ': econ,
                             'isle': 'ShouldBeOnIsle' in fx, 'npc': 'ShouldBeInNps' in fx, 'food': 'FoodValue' in fx}
    return out


def leveling(ranks, shallow):
    """IslePortInfo.Leveling: bigger shipyards mean smaller lots; ports behind shallows count one rank smaller."""
    ranks = int(ranks or 6)
    if shallow is not None and 0 < shallow < 3:
        ranks = max(1, ranks - 1)
    return 0.4 + (6 - ranks) / 5 * 0.6


def lot(cost, lev, neutral):
    if not cost:
        return 0
    v = 9000 * lev * (0.6 if neutral else 1)
    return int(math.ceil(v / cost / 100) * 100), int(math.ceil(v * 0.7 / cost / 100) * 100), int(math.ceil(v * 1.3 / cost / 100) * 100)


def sell_price(cost, dist):
    f = max(0.14, min(1.0, 2 * dist / MAP_W)) ** 1.3
    return int(math.ceil(cost * (1 + 0.69 * f)))


_CACHE = {}


def data(b):
    """Per-port trade picture: region, economy, goods offered (with lot sizes), basic goods, and what it pays for every trade good."""
    key = id(b)
    if key in _CACHE:
        return _CACHE[key]
    import site_extras
    world = getattr(b, 'world', None) or {}
    ports = world.get('ports') or []
    reg = find_regions(b)
    gd = goods(b.db, getattr(b, 'build', 'Steam'))
    names = site_extras.resource_names(b.db, getattr(b, 'build', 'Steam'))
    defs = {d.get('PortName'): d for d in site_extras.records(b.db, 'WorldPorts', getattr(b, 'build', 'Steam'))}
    sh = getattr(b, 'shallows', None)
    out = {'ports': [], 'goods': gd, 'names': names, 'ok': bool(reg and ports and gd)}
    if not out['ok']:
        _CACHE[key] = out
        return out
    for p in ports:
        rk = reg.at(p['x'], p['y'])
        p2 = {'n': p['n'], 'type': p['type'], 'x': p['x'], 'y': p['y'], 'region': REGION_NAMES[rk] if rk >= 0 else None,
              'level': REGION_LEVEL[rk] if rk >= 0 else None, 'econ': ECONOMY.get(rk), 'arab': 'Arab' in p['flags']}
        out['ports'].append(p2)
    for p in out['ports']:
        d = next((x for x in defs.values() if (x.get('EnglishName') or x.get('PortNameEnglish')) == p['n']), {})
        market = p['type'] not in ('PirateBay', 'Event')
        neutral = p['type'] == 'NeutralBay'
        shallow = sh.get(p['x'], p['y']) if sh else None
        lev = leveling(d.get('BuildShipRangs'), shallow)
        offers = []
        if market:
            for gid, g in sorted(gd.items(), key=lambda kv: kv[1]['n']):
                if g['isle'] or not g['econ']:
                    continue
                if gid == AMBERGRIS:
                    if not p['arab']:
                        offers.append({'id': gid, 'n': g['n'], 'qty': (10, 10, 10), 'always': True})
                    continue
                if g['econ'] == p['econ']:
                    offers.append({'id': gid, 'n': g['n'], 'qty': lot(g['cost'], lev, neutral), 'always': False})
        basic = list(BASIC_ALL) + list(BASIC_BY_TYPE.get(p['type'], ()))
        prod = PRODUCED.get(str(d.get('ProducedResourceId') or ''))
        if prod and prod not in basic and prod in (1, 3, 4, 2, 12, 22, 13, 11, 10, 34, 21):
            basic.append(prod)
        capturable = p['type'] not in ('Event', 'NeutralBay', 'PirateBay') and not p['arab']
        if capturable:
            basic.append(WATER)
        pays = {}
        for gid, g in gd.items():
            if not g['econ'] or not g['cost']:
                continue
            if gid == AMBERGRIS or g['econ'] == p['econ']:
                pays[gid] = g['cost']; continue
            same = [q for q in out['ports'] if q['econ'] == g['econ']]
            if not same:
                continue
            dist = min(math.hypot(q['x'] - p['x'], q['y'] - p['y']) for q in same)
            pays[gid] = sell_price(g['cost'], dist)
        p.update({'market': market, 'neutral': neutral, 'offers': offers, 'basic': [names.get(i, f'item {i}') for i in dict.fromkeys(basic)],
                  'pays': pays, 'lev': round(lev, 2)})
    _CACHE[key] = out
    return out


def port_html(b, title):
    """The 'Trade goods' section of a port page."""
    d = data(b)
    if not d['ok']:
        return []
    p = next((x for x in d['ports'] if x['n'] == title), None)
    if not p:
        return []
    link = lambda n: (f'<a href="../{b.urls[("resource", n.casefold())]}">{_e(n)}</a>' if ('resource', n.casefold()) in b.urls else _e(n))
    out = ['<h2 id="trade">Trade goods</h2>']
    where = f'{_e(p["region"])} (danger level {p["level"]})' if p['region'] else 'open water between regions'
    econ = f', part of the {_e(p["econ"])} economy' if p['econ'] else ', which belongs to no trading economy'
    out.append(f'<p>{_e(title)} lies in <b>{where}</b>{econ}.</p>')
    if not p['market']:
        out.append('<p>This port has no goods market: trade goods are not bought or sold here.</p>')
    else:
        own = [o for o in p['offers'] if not o['always']]
        if own:
            rows = [[link(o['n']), f'{o["qty"][0]:,}', f'{o["qty"][1]:,}–{o["qty"][2]:,}' if o['qty'][1] != o['qty'][2] else f'{o["qty"][1]:,}'] for o in own]
            import site_extras
            out.append('<p>Each of these goods is on offer about <b>6 times in 10</b> when the market\'s offers are drawn'
                       + (' (a neutral bay offers smaller lots)' if p['neutral'] else '') + ':</p>'
                       + site_extras._table(['Good', 'Typical lot', 'Range'], rows))
        else:
            out.append('<p>No regional trade goods are offered here' + ('' if p['econ'] else ', because the port is outside every trading economy') + '.</p>')
        if any(o['always'] for o in p['offers']):
            out.append(f'<p>Plus a small lot of {link(d["names"].get(AMBERGRIS, "Ambergris"))} (10).</p>')
    if p['basic']:
        out.append('<p><b>Always on sale:</b> ' + ', '.join(link(n) for n in p['basic']) + '.</p>')
    far = sorted(((g, d['goods'][g]) for g in p['pays'] if d['goods'][g]['econ'] != p['econ'] and g != AMBERGRIS), key=lambda kv: -p['pays'][kv[0]] / kv[1]['cost'])
    if far:
        best = far[:4]
        out.append('<p><b>Good place to sell:</b> ' + ', '.join(f'{link(g["n"])} ({p["pays"][gid]} gold, +{round(100 * (p["pays"][gid] / g["cost"] - 1))}%)' for gid, g in best)
                   + '. See <a href="../guide/trade-goods.html">Trade goods</a> for every port.</p>')
    return out


def trade_page(b, crumbs, page):
    import site_extras
    d = data(b)
    if not d['ok']:
        return
    gd = d['goods']; names = d['names']
    link = lambda n: (f'<a href="../{b.urls[("resource", n.casefold())]}">{_e(n)}</a>' if ('resource', n.casefold()) in b.urls else _e(n))
    plink = lambda n: (f'<a href="../{b.urls[("port", n.casefold())]}">{_e(n)}</a>' if ('port', n.casefold()) in b.urls else _e(n))
    body = ['<p>Every trade good belongs to one of the sea\'s trading economies. Ports sell the goods of their own economy and pay the most for goods '
            'from far away. These are the game\'s own rules; what is actually on the shelves changes each time a market\'s offers are drawn.</p>',
            '<h2 id="economies">Economies and their goods</h2>']
    rows = []
    for econ in ('North', 'South', 'Arab', 'Center'):
        regs = [REGION_NAMES[k] for k in sorted(ECONOMY) if ECONOMY[k] == econ]
        sold = [g['n'] for gid, g in sorted(gd.items(), key=lambda kv: kv[1]['n']) if g['econ'] == econ and not g['isle'] and gid != AMBERGRIS]
        isle = [g['n'] for gid, g in sorted(gd.items(), key=lambda kv: kv[1]['n']) if g['econ'] == econ and g['isle']]
        rows.append([f'<b>{econ}</b>', ', '.join(regs), ', '.join(link(n) for n in sold) or '–', ', '.join(link(n) for n in isle) or '–'])
    rows.append(['<i>none</i>', ', '.join(REGION_NAMES[k] for k in range(16) if k not in ECONOMY), '–', '–'])
    body.append(site_extras._table(['Economy', 'Sea regions', 'Sold in its ports', 'Found only on islands (dig sites)'], rows, cls='wikitable'))
    body.append('<ul><li>A port offers each good of its economy about <b>6 times in 10</b>. Lots are worth about 9,000 gold at the biggest ports and less at small ones; '
                'neutral bays offer 60% of that.</li><li><b>Ambergris</b> is offered in lots of 10 at every port with a market except Arab ports.</li>'
                '<li>Goods marked as island goods are never sold in ports: you dig them up on islands of that economy (see <a href="dig-sites.html">Dig sites</a>).</li>'
                '<li>Pirate ports have no goods market.</li></ul>')
    body.append('<h2 id="selling">Where to sell</h2><p>A port of the good\'s own economy pays its base value. Every other port pays more, the further it is from the nearest '
                'port of that economy: from about +5% close by up to about <b>+70%</b> across the map (cheap goods a little more, as prices round up to whole gold). The table shows what each port pays (gold per unit); the best price for each good is in bold.</p>')
    cols = [gid for gid, g in sorted(gd.items(), key=lambda kv: (kv[1]['econ'] or '', kv[1]['n'])) if g['econ'] and g['cost'] and gid != AMBERGRIS]
    market = [p for p in d['ports'] if p['market']]
    best = {gid: max((p['pays'].get(gid, 0) for p in market), default=0) for gid in cols}
    rows = []
    for p in sorted(market, key=lambda p: (p['econ'] or 'zz', p['n'])):
        rows.append([plink(p['n']), _e(p['econ'] or '–')] + [(f'<b>{p["pays"][g]}</b>' if p['pays'].get(g) == best[g] else str(p['pays'].get(g, '–'))) for g in cols])
    body.append('<div class="table-scroll">' + site_extras._table(['Port', 'Economy'] + [f'{_e(gd[g]["n"])}<br><small>{gd[g]["econ"]}, base {gd[g]["cost"]}</small>' for g in cols], rows) + '</div>')
    body.append('<h2 id="ports">What each port stocks</h2>')
    rows = []
    for p in sorted(d['ports'], key=lambda p: p['n']):
        offers = ', '.join(f'{link(o["n"])} (~{o["qty"][0]:,})' for o in p['offers'] if not o['always']) if p['market'] else 'no goods market'
        rows.append([plink(p['n']), _e(p['region'] or '–'), _e(p['econ'] or '–'), offers or '–', ', '.join(link(n) for n in p['basic'])])
    body.append(site_extras._table(['Port', 'Region', 'Economy', 'Regional trade goods (typical lot)', 'Always on sale'], rows))
    body.append('<p class="note">Lot sizes are the middle of the range (each draw is 70–130% of it), before trading skills that increase lot sizes. '
                'Prices are what the port pays you before taxes.</p>')
    b._write('guide/trade-goods.html', page('Trade goods', ''.join(body), depth=1, crumbs=crumbs, tab='Guide'))
    b.search.append({'t': 'Trade goods', 'u': 'guide/trade-goods.html', 'c': 'Guide', 'k': 'trade goods port market stock sell price economy region sugar silk wine'})


def dig_page(b, crumbs, page):
    import site_extras
    gd = goods(b.db, getattr(b, 'build', 'Steam')); names = site_extras.resource_names(b.db, getattr(b, 'build', 'Steam'))
    costs = {}
    for r in site_extras.records(b.db, 'Resources', getattr(b, 'build', 'Steam')):
        rid = str(r.get('ID') or '')
        if rid.startswith('res_') and rid[4:].isdigit():
            costs[int(rid[4:])] = int(r.get('MediumCost') or 0)
    nm = lambda i: names.get(i, f'item {i}')
    link = lambda n: (f'<a href="../{b.urls[("resource", n.casefold())]}">{_e(n)}</a>' if ('resource', n.casefold()) in b.urls else _e(n))
    total = sum(SEA_FINDS.values())
    body = ['<p>Islands hide three kinds of finds. They appear at random on islands across the open sea, among everything else that turns up at sea '
            '(fishing spots, wrecks, whales and so on). What they hold grows with the danger level of the sea region they are in.</p>',
            '<h2 id="kinds">Kinds of find</h2>']
    body.append(site_extras._table(['Find', 'How you get it', 'Share of all finds at sea', 'What it holds'], [
        ['<b>Dig site</b> (shovel marker)', 'Land on the islet and dig (a short mini-game).', f'{100 * SEA_FINDS["Dig site"] / total:.1f}%',
         f'Raw materials, the region\'s island trade good, {link(nm(SUPPLIES))} and {link(nm(VOLCANIC_ORE))}; 2% chance of a {link(nm(CHEST))}.'],
        ['<b>Ruins</b>', 'Land and search; takes a while. Can be a pirate trap.', f'{100 * SEA_FINDS["Ruins"] / total:.1f}%',
         f'One of {link(nm(VOODOO))} (1 in 4), {link(nm(KEY))} (1 in 4) or {link(nm(CHEST))} (1 in 2), plus {link(nm(VOLCANIC_ORE))}.'],
        ['<b>Buried treasure</b>', 'Shown to everyone on the world map ("treasure lies near this spot"); not available with PvP protection. Land and search.',
         f'{100 * SEA_FINDS["Buried treasure"] / total:.2f}%', f'About 30–60 {link(nm(CHEST))}s; 30% chance of a {link(nm(VOODOO))} too, otherwise 10% chance of a {link(nm(KEY))} (with half the chests).'],
    ], cls='wikitable'))
    body.append('<p>The ship upgrade that speeds up searching also speeds up digging and searching ruins (but not crew landings).</p>')
    # per-region dig site contents
    body.append('<h2 id="regions">Dig sites by region</h2><p>A dig site is worth about <b>375 gold × the region factor</b> (each one varies from half to one and a half times that). '
                'It holds about 45% of that value in one raw material and 45% in a second good, 70% in Supplies and 50% in Volcanic Ore. The second good is one of '
                'the region\'s island trade goods if it has any; otherwise Animals, Rum or Supplies.</p>')
    rows = []
    for k in range(16):
        lvl = REGION_LEVEL[k]; f = 1 + lvl * 0.15 * 9 / 7; v = 375 * f
        econ = ECONOMY.get(k)
        isle = [g['n'] for g in gd.values() if g['isle'] and g['econ'] == econ] if econ else []
        second = ' or '.join(link(n) for n in sorted(isle)) if isle else ' or '.join(link(nm(i)) for i in DIG_FALLBACK)
        sup = round(v * 0.7 / (costs.get(SUPPLIES) or 15)); ore = round(v * 0.5 / (costs.get(VOLCANIC_ORE) or 30))
        raw = ', '.join(f'{round(max(1, v * 0.45 / (costs.get(i) or 1)))} {nm(i)}' for i in DIG_RAW)
        rows.append([_e(REGION_NAMES[k]), str(lvl), f'×{f:.2f}', _e(econ or '–'), second, f'one of: {raw}', str(sup), str(ore)])
    body.append(site_extras._table(['Region', 'Level', 'Factor', 'Economy', 'Second good', 'Raw material (typical)', 'Supplies', 'Volcanic Ore'], rows))
    body.append('<p class="note">Typical amounts are for an average dig; each site rolls between half and one and a half times as much. '
                'During holiday events a dig site can also hold a part of the festival treasure map (1 in 4).</p>')
    body.append('<p>Island trade goods can\'t be bought in any port, so they sell well: see <a href="trade-goods.html#selling">where to sell</a>.</p>')
    b._write('guide/dig-sites.html', page('Dig sites, ruins and buried treasure', ''.join(body), depth=1, crumbs=crumbs, tab='Guide'))
    b.search.append({'t': 'Dig sites', 'u': 'guide/dig-sites.html', 'c': 'Guide', 'k': 'dig site shovel islet island search ruins buried treasure chest voodoo skull'})


def write_pages(b, crumbs, page):
    crumbs = [('Main page', 'index.html'), ('Guides & mechanics', 'category/articles.html')]
    trade_page(b, crumbs, page)
    dig_page(b, crumbs, page)
