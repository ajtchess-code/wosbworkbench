"""Planning tools for the WoSB Wiki: the crafting calculator (and its data), built from the game's own recipes.

Data sources (all read from the catalog):
* ``Crafting_Recipes`` + ``Recipe_Ingredients``: workshop, furnace and Personal Island workshop recipes
  (WosbCrafting .cctor), with craft hours, gold and output batch size.
* ``Ship_Materials`` / ``Ship_Construction``: ship hull materials and base gold.
* ``Cannon_Materials`` / ``Cannon_Crafting``: cannon materials and base gold.
* ``data/consumables.json``: consumable recipes (PowerupItemsGenerator).
* Ship upgrades: the recipe formula in ``Gameplay`` (one recipe per ship rank), ported below.
* ``Resources`` (MediumCost) and ``Market_Price_Limits``: default prices and the market's min/max.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict

import site_extras

# GSI resource ids by annotation (Common.Game.GSI constants), used by MainCraftResource on ship upgrades
GSI_IDS = {'TWoodID': 1, 'TCottonID': 3, 'TIronID': 4, 'TCopper': 11, 'TCoal': 12, 'TResinLaquer': 13, 'RDebris': 20, 'RVulkanoOre': 23,
           'FIronOre': 31, 'FCopperOre': 32, 'TRumID': 2, 'TFruitsAndOthers': 9, 'TCorn': 10, 'RBondman': 8, 'TWater': 5, 'TMeat': 21,
           'TAnimals': 22, 'TFinery': 30, 'CGoldIngot': 24, 'CBronze': 14, 'CBlock': 16, 'CSailcloth': 17, 'CBulkWood': 27, 'CBulkIron': 29,
           'CFishingRod': 36, 'CProvision': 39, 'ArenaLoot': 19, 'RVuduSkull': 38, 'RMarks': 37, 'REscudo': 15, 'RGuildPaper': 40,
           'RDonateChestKey': 43, 'RInsuranePaper': 33, 'REmpireShipDraft': 67, 'REmpireShipCompletedDraft': 68, 'TPearl': 25, 'TFish': 34,
           'TGoldFish': 69, 'TBeer': 7, 'TSugar': 6, 'TISilk': 53, 'TILeather': 59, 'TWhaleOil': 70, 'TAmberChest': 76}

CONTEXT = {'Workshop': 'Workshop', 'Furnace': 'Furnace', 'Personal island workshop': 'Personal Island workshop'}


def upgrade_recipes(rec, medium_cost):
    """The seven recipes (ship rank 1..7) of one ship upgrade: Gameplay.A(ShipUpgradeInfoTokenNew, ref CraftingRecipe[], ...)."""
    main = GSI_IDS.get(str(rec.get('MainCraftResource') or ''), -1)
    low = str(rec.get('LowCost')).lower() == 'true'
    sails = rec.get('Category') == 'Sailes'
    mul = 0.6 if low else 1.0
    out = {}
    for i in range(7):
        rank = i + 1
        k = [0.75, 2, 3, 6, 8, 11, 15][6 - min(6, i)]
        base = int((400 * k - 150) * mul)
        gold = 50 + base // 3
        res = defaultdict(int)
        if sails:
            gold *= 2
            if main != -1:
                b = base * 2 if main == 38 else base
                res[3] = (b // 3) if (rank >= 6 or low) else 0
                res[17] = (b // 70) if (rank < 6 and not low) else 0
                res[38] = max(1, b // 1000) if (main == 38 and rank < 7) else 0
        else:
            if not low and rank <= 3:
                res[16] += int(max(0.0, base / 400 - 0.5))
            if main != -1:
                unit = 25 if main == 37 else 600 if main == 38 else (medium_cost.get(main) or 1)
                res[main] += int(max(1.0, 1.68 * (50 + base / 2) / unit))
            else:
                gold *= 2
            if rank <= 5:
                res[2] += base // 10
                gold = int(gold * 0.75)
            else:
                gold = int(gold * 1.5)
        out[rank] = ({str(r): q for r, q in res.items() if q > 0}, gold)
    return out


def crafting_data(b):
    """{items: {key: {...}}, recipes: [...]} for the calculator."""
    db, build = b.db, b.build
    recs = lambda ds: site_extras.records(db, ds, build) or site_extras.records(db, ds, 'Game')
    items, recipes = {}, []
    url = lambda kind, title: b.urls.get((kind, title.casefold()))
    icon = lambda kind, title: b.icons.get((kind, title.casefold()))
    # resources
    res_ent = {str(r.get('ID')): r for r in b.entities.get('resource', [])}
    medium = {}
    for r in recs('Resources'):
        rid = str(r.get('ID') or '')
        if not rid.startswith('res_') or not rid[4:].isdigit():
            continue
        n = int(rid[4:]); name = r.get('EnglishName') or rid
        if not name or name.casefold() in ('removed', 'res_0'):
            continue
        medium[n] = int(r.get('MediumCost') or 0)
        ent = res_ent.get(rid)
        title = ent['_title'] if ent else name
        items[f'r:{n}'] = {'n': title, 'k': 'Resource', 'p': medium[n] or None, 'u': url('resource', title), 'i': icon('resource', title)}
    items['r:255'] = {'n': 'Gold', 'k': 'Currency', 'p': 1}
    for r in recs('Market_Price_Limits'):
        if str(r.get('TextID', '')).startswith('res_') and f"r:{str(r['TextID'])[4:]}" in items:
            it = items[f"r:{str(r['TextID'])[4:]}"]; it['mn'] = r.get('ClientMinUnitPrice'); it['mx'] = r.get('ClientMaxUnitPrice')
    ing = defaultdict(list)
    for i in recs('Recipe_Ingredients'):
        if i.get('ResourceID') and int(i.get('Quantity') or 0) > 0:
            ing[i['RecipeID']].append([f"r:{int(i['ResourceID'])}", int(i['Quantity'])])
    ammo_names = {}
    for a in recs('CannonBalls'):
        aid = str(a.get('ID') or '')       # the numeric ammo id is the record number (cball_s is 5, Heavy Shots)
        if aid.startswith('cball_') and a.get('SourceRecord') is not None and a.get('EnglishName') and a['EnglishName'] != 'removed':
            n = int(a['SourceRecord']); ammo_names[n] = a
            items[f'a:{n}'] = {'n': a['EnglishName'], 'k': 'Ammunition', 'p': a.get('SingleCost') or None,
                               'u': url('ammo', a['EnglishName']), 'i': icon('ammo', a['EnglishName'])}
    for r in recs('Crafting_Recipes'):
        kind = r.get('OutputType'); oid = int(r.get('OutputID') or 0)
        key = (f'r:{oid}' if kind == 'resource' else f'a:{oid}' if kind == 'ammunition' else None)
        if not key or key not in items or not ing.get(r['RecipeID']):
            continue
        recipes.append({'id': r['RecipeID'], 'o': key, 'q': int(r.get('OutputQuantity') or 1), 'h': float(r.get('CraftHours') or 0),
                        'g': int(r.get('InputGold') or 0), 'c': CONTEXT.get(r.get('Context'), r.get('Context') or 'Workshop'),
                        'ins': ing[r['RecipeID']]})
    # ships
    rules = site_extras.rules()
    ships = {str(s.get('ID')): s for s in b.entities.get('ship', [])}
    cons = {str(c.get('ShipID')): c for c in recs('Ship_Construction')}
    mats = defaultdict(list)
    for m in recs('Ship_Materials'):
        if int(m.get('BaseQuantity') or 0) > 0:
            mats[str(m['ShipID'])].append([f"r:{int(m['ResourceID'])}", int(m['BaseQuantity'])])
    for sid, mlist in mats.items():
        s = ships.get(sid)
        if not s:
            continue
        rank = s.get('ShipRank'); c = cons.get(sid, {})
        secs = rules.get('shipyard_seconds', {}).get(str(rank), 0) if 'Elite' not in str(s.get('Coolness')) else 0
        items[f's:{sid}'] = {'n': s['_title'], 'k': f'Ship (rank {rank})', 'u': url('ship', s['_title']), 'i': icon('ship', s['_title'])}
        recipes.append({'id': f'ship{sid}', 'o': f's:{sid}', 'q': 1, 'h': round(secs / 3600, 3), 'g': int(c.get('BaseGoldCost') or 0),
                        'c': 'Shipyard', 'ins': [x for x in mlist if x[0] in items]})
    # cannons
    cans = {str(c.get('SourceRecord')): c for c in b.entities.get('cannon', [])}
    cgold = {str(c.get('CannonIndex')): int(c.get('BaseGold') or 0) for c in recs('Cannon_Crafting')}
    cmat = defaultdict(list)
    for m in recs('Cannon_Materials'):
        if int(m.get('BaseQuantity') or 0) > 0:
            cmat[str(m['CannonIndex'])].append([f"r:{int(m['ResourceID'])}", int(m['BaseQuantity'])])
    for idx, mlist in cmat.items():
        c = cans.get(idx)
        if not c:
            continue
        items[f'c:{idx}'] = {'n': c['_title'], 'k': 'Cannon', 'u': url('cannon', c['_title']), 'i': icon('cannon', c['_title'])}
        recipes.append({'id': f'cannon{idx}', 'o': f'c:{idx}', 'q': 1, 'h': 0, 'g': cgold.get(idx, 0), 'c': 'Port (cannon foundry)',
                        'ins': [x for x in mlist if x[0] in items]})
    # consumables
    t = b.texts
    for it in site_extras.consumables():
        name = t.get(f'item_name{it["index"]}')
        if not name or not (it.get('recipe') or it.get('gold')):
            continue
        key = f'p:{it["index"]}'
        ic = getattr(b, 'consumable_icons', {}).get(it['index'])
        items[key] = {'n': name, 'k': 'Consumable', 'u': '../guide/consumables.html', 'i': ic}
        recipes.append({'id': f'item{it["index"]}', 'o': key, 'q': 1, 'h': 0, 'g': int(it.get('gold') or 0), 'c': 'Consumables workshop',
                        'ins': [[f'r:{int(r)}', int(q)] for r, q in it['recipe'].items() if f'r:{int(r)}' in items]})
    # ship upgrades: one item per ship rank
    for u in b.entities.get('upgrade', []):
        for rank, (res, gold) in upgrade_recipes(u, medium).items():
            key = f'u:{u.get("SourceRecord")}:{rank}'
            items[key] = {'n': f'{u["_title"]} (rank {rank} ship)', 'k': 'Ship upgrade', 'u': url('upgrade', u['_title']), 'i': icon('upgrade', u['_title'])}
            recipes.append({'id': f'up{u.get("SourceRecord")}r{rank}', 'o': key, 'q': 1, 'h': 0, 'g': gold, 'c': 'Port (upgrades)',
                            'ins': [[f'r:{r}', q] for r, q in res.items() if f'r:{r}' in items]})
    used = {r['o'] for r in recipes} | {k for r in recipes for k, _ in r['ins']}
    items = {k: {kk: vv for kk, vv in v.items() if vv not in (None, '')} for k, v in items.items() if k in used}
    return {'items': items, 'recipes': recipes}


CRAFT_PAGE = '''<p>Pick what you want to make: a ship, a cannon, ammunition, a consumable, an upgrade or any material. The calculator follows every recipe down,
lets you choose for each part whether to <b>buy</b> it or <b>craft</b> it, counts what you already <b>have</b>, and prices it all with your own numbers.
Recipes, batch sizes, craft hours and gold come from the game; prices start at the game's base value, so put in what you actually pay.</p>
<div id="cc"></div><script src="../assets/crafting.js"></script><script>Crafting.mount(document.getElementById('cc'),'../data/crafting.json')</script>
<h2>How it works</h2><ul>
<li><b>Buy or craft</b>: “Auto” crafts a part when that is cheaper than buying it at your price; “Craft” and “Buy” force it. Turn on <b>rawest materials</b> to break everything down as far as it goes.</li>
<li><b>Mixed prices</b>: in “Lots”, list what you can buy and at what price, like <code>500@12, 2000@15</code>. The cheapest lots are used first; anything beyond them is bought at the price column.</li>
<li><b>What you have</b> is used before anything is bought or crafted, at every step of the chain.</li>
<li><b>Batches</b>: workshops make fixed batches (Iron by the furnace comes in 270s), so the calculator rounds up and shows the leftovers.</li>
<li>Port, guild, captain-skill and event discounts are not applied; craft hours are the game's base charge per batch.</li></ul>'''


def write_pages(b, crumbs, page):
    """Write the crafting calculator (data + page). ``page`` is wiki_site._page."""
    data = crafting_data(b)
    b._write('data/crafting.json', json.dumps(data, separators=(',', ':')))
    b._write('tools/crafting-calculator.html', page('Crafting calculator', CRAFT_PAGE, depth=1, crumbs=crumbs, tab='Tool'))
    write_planners(b, crumbs, page)
    return len(data['recipes'])


# ================================================================================================ planners
import re as _re
import site_effects


def _fx_list(text, rank=None):
    """'MSpeed +1.2,+1.0;PArmor +4' -> [[code, value], ...] for one ship rank (ShipBonus: Values[clamp(len - rank)])."""
    out = []
    for part in _re.split(r'[;]', str(text or '')):
        m = _re.match(r'\s*((?:Serv)?[PMBC]?[A-Za-z_]+)\s*(.*)$', part.strip())
        if not m or not m.group(1):
            continue
        vals = [v for v in _re.findall(r'[+-]?\d+(?:\.\d+)?', m.group(2))]
        if not vals:
            out.append([m.group(1), 1]); continue
        if rank is None or len(vals) == 1:
            v = vals[0]
        else:
            v = vals[min(max(len(vals) - rank, 0), len(vals) - 1)]
        out.append([m.group(1), float(v)])
    return out


def _labels(codes):
    """{code: [label, sign, unit]}: the sign is -1 where the wording turns the value round ("damage taken -14%")."""
    out = {}
    for c in codes:
        lab, val = site_extras._label_and_value(c, 5)
        sign = -1 if str(val).startswith('-') else 1
        unit = '%' if '%' in str(val) else ''
        out[c] = [lab, sign, unit]
    return out


STAT_CODES = {'speed': ('MSpeed', 'PSpeed'), 'armor': ('MArmor', 'PArmor'), 'hp': ('MHealth', 'PHealth'), 'mob': ('MMobilityBonus', 'PMobilityBonus'),
              'cargo': ('MCapacity', 'PCapacity'), 'crew': ('MExtraPlaces', None)}


def builder_data(b):
    """Ships, upgrades (effects for every ship rank), special crew and bonus designs for the ship builder."""
    rules = site_extras.rules()
    ships = []
    for r in b.entities.get('ship', []):
        try:
            rank = int(r.get('ShipRank'))
        except (TypeError, ValueError):
            continue
        ships.append({'n': r['_title'], 'id': r.get('ID'), 'rank': rank, 'cls': r.get('TypeEnglish') or r.get('Type'), 'cool': r.get('Coolness'),
                      'speed': r.get('BasicSpeed'), 'armor': r.get('Armor'), 'hp': r.get('Health'), 'mob': r.get('BasicMobility'), 'cargo': r.get('CapacityCg'),
                      'crew': r.get('BaseCrewPlaces'), 'units': r.get('PlacesForUnitsCount'), 'slots': 6 + int(r.get('ExtraPlacesForUpgrades') or 0),
                      'u': b.urls.get(('ship', r['_title'].casefold())), 'i': b.icons.get(('ship', r['_title'].casefold()))})
    codes = set()
    ups = []
    for u in b.entities.get('upgrade', []):
        fx = {rank: _fx_list(u.get('EffectsBoost'), rank) for rank in range(1, 8)}
        if not any(fx.values()):
            continue
        for v in fx.values():
            codes.update(c for c, _ in v)
        ups.append({'n': u['_title'], 'cat': u.get('Category'), 'fx': fx, 'budget': str(u.get('LowCost')).lower() == 'true',
                    'u': b.urls.get(('upgrade', u['_title'].casefold())), 'i': b.icons.get(('upgrade', u['_title'].casefold()))})
    titles = site_extras.crew_titles(b.db, b.build)
    crew = []
    for r in site_extras.records(b.db, 'UnitsInfo', b.build):
        if not str(r.get('ID', '')).startswith('unit_special'):
            continue
        fx = _fx_list(r.get('Effect')); per = _fx_list(r.get('EffectPerSailor')) + _fx_list(r.get('EffectPerBoardingUnit'))
        codes.update(c for c, _ in fx + per)
        crew.append({'n': titles.get(r['ID'], r['ID']), 'g': r.get('Options'), 'fx': fx, 'per': per,
                     'perk': 'sailor' if r.get('EffectPerSailor') else 'boarder' if r.get('EffectPerBoardingUnit') else ''})
    designs = []
    for r in b.entities.get('cosmetic', []):
        if r.get('Category') not in ('Satellite', 'BowFigure') or r.get('BonusEffectType') in (None, '', 'None'):
            continue
        ts = str(r['BonusEffectType']).split(); vs = str(r.get('BonusEffectValue') or '').split()
        fx = [[t_, float(vs[i]) if i < len(vs) else 1] for i, t_ in enumerate(ts)]
        codes.update(t_ for t_ in ts)
        designs.append({'n': r['_title'], 'slot': 'lantern' if r['Category'] == 'Satellite' else 'figurehead', 'fx': fx,
                        'i': b.icons.get(('cosmetic', r['_title'].casefold()))})
    elite = rules.get('elite_status', {}).get('benefits', {})
    return {'ships': sorted(ships, key=lambda s: (s['rank'], s['n'])), 'upgrades': sorted(ups, key=lambda u: (u['cat'] or '', u['n'])),
            'crew': sorted(crew, key=lambda c: (c['g'] or '', c['n'])), 'designs': sorted(designs, key=lambda d: (d['slot'], d['n'])),
            'labels': _labels(codes), 'stats': STAT_CODES, 'elite': elite,
            'slot_costs': {str(rk): site_extras.slot_costs(rk) for rk in range(1, 8)}}


def island_data(b):
    t = b.texts
    keys = [('BigStorage', 4), ('Workshop', 3), ('Dok', 1), ('Shipbuilder', 2), ('Avanpost', 5), ('Pub', 7), ('Factory', 6), ('Lighthouse', 8)]
    labor = {'Workshop': 100, 'Pub': 20, 'Dok': 20, 'Factory': 10}
    buildings = [{'id': k, 'n': t.get(f'personal_isle_b{n}_name', k), 'd': (t.get(f'personal_isle_b{n}_tt') or '').replace('{0}', '7,000').replace('#', ''),
                  'labor': labor.get(k, 0)} for k, n in keys]
    buildings = [x for x in buildings if x['d'] and x['d'] != '???']
    decor = []
    for r in b.entities.get('decoration', []):
        shop = str(r.get('InShop') or '')
        m = _re.match(r'By(Gold|Monets)\s+(\d+)', shop)
        bonus = r.get('EnvDesingBonus')
        decor.append({'n': r['_title'], 'cur': ('gold' if m.group(1) == 'Gold' else 'coins') if m else None, 'p': int(m.group(2)) if m else None,
                      'bonus': site_effects.describe_all(bonus)[0] if bonus else '', 'code': (str(bonus).split() or [''])[0] if bonus else '',
                      'v': float((_re.findall(r'[+-]?\d+(?:\.\d+)?', str(bonus or '')) or [0])[0]),
                      'i': b.icons.get(('decoration', r['_title'].casefold())), 'u': b.urls.get(('decoration', r['_title'].casefold()))})
    return {'buildings': buildings, 'decor': sorted(decor, key=lambda d: d['n']), 'min_rank': 9,
            'storage': [50, 500], 'labor_base': 50, 'labor_per_hour': 1,
            'skills': [{'n': 'Personal Islands', 'pts': 1, 'd': 'A second island, and travel between islands.'},
                       {'n': 'Third Island', 'pts': 0, 'd': 'A third island; travel every 2 hours instead of 4, and a new look for the buildings on all your islands.'}]}


def chest_data(b):
    try:
        data = json.loads((site_extras.DATA / 'chests.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    t = b.texts
    res = site_extras.resource_names(b.db, b.build)
    ammo = {}
    for a in site_extras.records(b.db, 'CannonBalls', b.build):
        if str(a.get('ID') or '').startswith('cball_') and a.get('SourceRecord') is not None:
            ammo[int(a['SourceRecord'])] = a.get('EnglishName')
    kegs = {int(k.get('SourceRecord') or 0): k.get('EnglishName') for k in site_extras.records(b.db, 'PowderKegs', b.build)}
    cans = {int(c.get('SourceRecord') or 0): c['_title'] for c in b.entities.get('cannon', [])}
    ships = {int(s.get('ID') or 0): s['_title'] for s in b.entities.get('ship', []) if str(s.get('ID', '')).isdigit()}
    designs = {int(d.get('SourceRecord') or 0): d['_title'] for d in b.entities.get('cosmetic', [])}
    extra = {35: 'Map Scroll', 67: 'Blueprint Fragment', 68: 'Imperial Blueprint', 72: 'Pirate Token', 77: 'Letters Patent (Elite XP)', 78: 'Letters Patent (Elite level)', 79: 'Letters Patent (full Elite status)'}

    def label(r):
        k, q = r['t'], r.get('q', 1)
        if k == 'res':
            return f'{q:,} × {res.get(r["id"]) or extra.get(r["id"], "item " + str(r["id"]))}'
        if k == 'gold':
            return f'{q:,}–{r["qmax"]:,} gold' if r.get('qmax') else f'{q:,} gold'
        if k == 'coins':
            return f'{q:,} Coins'
        if k == 'ammo':
            return f'{q:,} × {ammo.get(r["id"], "ammo " + str(r["id"]))}'
        if k == 'keg':
            return f'{q:,} × {kegs.get(r["id"], "powder keg " + str(r["id"]))}'
        if k == 'item':
            return f'{q:,} × {t.get("item_name" + str(r["id"]), "consumable " + str(r["id"]))}'
        if k == 'cannon':
            return f'{q:,} × {cans.get(r["id"], "cannon " + str(r["id"]))}'
        if k == 'ship':
            return f'Ship: {ships.get(r["id"], "ship " + str(r["id"]))}'
        if k == 'design':
            names = [designs[i] for i in r.get('ids', []) if i in designs]
            return (r.get('text') + ': ' if r.get('text') else '') + ' or '.join(names) if names else r.get('text') or 'A ship design'
        if k == 'premium':
            return f'{q} days of Premium'
        if k == 'slot':
            return '+1 ship slot in the shipyard'
        if k == 'multi':
            return ' + '.join(label(p) for p in r['parts'])
        return k
    for c in data['chests'].values():
        total = sum(r['w'] for r in c['rewards'])
        for r in c['rewards']:
            r['label'] = label(r) + (f' ({r["note"]})' if r.get('note') else '')
            r['pct'] = r['w'] / total * 100
    return data


PLANNER_PAGES = {
    'ship-builder': ('Ship builder', '<p>Fit a ship the way you would in port: choose the ship and its rank, fill the upgrade slots, pick special crew, a lantern and a figurehead, '
                     'and see what it does to the ship. The effects use the game\'s own values for each ship rank. Share the build with a link, or open any ship from its page.</p>'
                     '<div id="sb"></div><script src="../assets/planners.js"></script><script>Planners.shipBuilder(document.getElementById("sb"),"../data/ship-builder.json")</script>'
                     '<p class="note">Stats are worked out the game\'s way: the base value times the percentage bonuses, plus the flat bonuses. Effects that are not one of the main stats are listed in plain words underneath. '
                     'Captain skills, guild and port bonuses are not included.</p>'),
    'island-planner': ('Personal Island planner', '<p>Plan your Personal Islands: what each building costs at your captain rank and in the order you build them, '
                       'what decorations cost in gold or Coins and what they add, and what the island\'s labour and warehouse come to.</p>'
                       '<div id="ip"></div><script src="../assets/planners.js"></script><script>Planners.islandPlanner(document.getElementById("ip"),"../data/islands.json")</script>'),
    'chest-simulator': ('Chest simulator', '<p>Open chests as many times as you like without spending a Coin. The odds are the game\'s own reward tables; '
                        'the simulator also shows the chance of each reward and what a number of opens costs.</p>'
                        '<div id="cs"></div><script src="../assets/planners.js"></script><script>Planners.chestSim(document.getElementById("cs"),"../data/chests.json")</script>'),
}


def write_planners(b, crumbs, page):
    b._write('data/ship-builder.json', json.dumps(builder_data(b), separators=(',', ':')))
    b._write('data/islands.json', json.dumps(island_data(b), separators=(',', ':')))
    chests = chest_data(b)
    if chests:
        b._write('data/chests.json', json.dumps(chests, separators=(',', ':')))
    for slug, (title, body) in PLANNER_PAGES.items():
        if slug == 'chest-simulator' and not chests:
            continue
        b._write(f'tools/{slug}.html', page(title, body, depth=1, crumbs=crumbs, tab='Tool'))
