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

import html as _html
import json
import math
import re
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
    b.search.append({'t': 'Crafting calculator', 'u': 'tools/crafting-calculator.html', 'c': 'Tool', 'k': 'craft recipe materials cost plan'})
    b._write('tools/crafting-calculator.html', page('Crafting calculator', CRAFT_PAGE, depth=1, crumbs=crumbs, tab='Tool'))
    write_planners(b, crumbs, page)
    events_pages(b, crumbs, page)
    world_pages(b, crumbs, page)
    shop_page(b, crumbs, page)
    npc_ships_page(b, crumbs, page)
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


# building → its model on the Personal Island (Connection<group>_level1/2; level 2 is the Third Island look)
ISLE_GROUPS = {'Dok': 'Dok', 'Shipbuilder': 'Ship', 'Workshop': 'Workshop', 'BigStorage': 'Storage', 'Avanpost': 'Tower',
               'Factory': 'Factory', 'Pub': 'Trader', 'Lighthouse': 'Lighthouse'}


def island_data(b):
    t = b.texts
    keys = [('BigStorage', 4), ('Workshop', 3), ('Dok', 1), ('Shipbuilder', 2), ('Avanpost', 5), ('Pub', 7), ('Factory', 6), ('Lighthouse', 8)]
    labor = {'Workshop': 100, 'Pub': 20, 'Dok': 20, 'Factory': 10}
    buildings = [{'id': k, 'n': t.get(f'personal_isle_b{n}_name', k), 'd': (t.get(f'personal_isle_b{n}_tt') or '').replace('{0}', '7,000').replace('#', ''),
                  'labor': labor.get(k, 0), 'g': ISLE_GROUPS.get(k)} for k, n in keys]
    buildings = [x for x in buildings if x['d'] and x['d'] != '???']
    decor = []
    for r in b.entities.get('decoration', []):
        shop = str(r.get('InShop') or '')
        m = _re.match(r'By(Gold|Monets)\s+(\d+)', shop)
        bonus = r.get('EnvDesingBonus')
        decor.append({'n': r['_title'], 'cur': ('gold' if m.group(1) == 'Gold' else 'coins') if m else None, 'p': int(m.group(2)) if m else None,
                      'bonus': site_effects.describe_all(bonus)[0] if bonus else '', 'code': (str(bonus).split() or [''])[0] if bonus else '',
                      'v': float((_re.findall(r'[+-]?\d+(?:\.\d+)?', str(bonus or '')) or [0])[0]),
                      'i': b.icons.get(('decoration', r['_title'].casefold())), 'u': b.urls.get(('decoration', r['_title'].casefold())),
                      'm': str(r.get('Name') or '').lower() or None})
    return {'buildings': buildings, 'decor': sorted(decor, key=lambda d: d['n']), 'min_rank': 9,
            'models': bool(getattr(b, 'model_pack', False) and getattr(b, 'recovery_dir', None)),
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
            if r['id'] == 69:
                return f'{q:,} × {res.get(69) or "Golden Fish"} (the event currency)'
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
                       '<div id="ip"></div><script src="../assets/item_viewer.js"></script><script src="../assets/planners.js"></script><script>Planners.islandPlanner(document.getElementById("ip"),"../data/islands.json")</script>'),
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
        b.search.append({'t': title, 'u': f'tools/{slug}.html', 'c': 'Tool', 'k': {'ship-builder': 'fit upgrades crew lantern build',
                         'island-planner': 'personal island buildings decorations', 'chest-simulator': 'chest loot odds open altar'}.get(slug, '')})
        b._write(f'tools/{slug}.html', page(title, body, depth=1, crumbs=crumbs, tab='Tool'))


# ================================================================================================ events
QUESTS = {
    'KillAnyNpc': 'Sink {0} NPC ships', 'BoardingAnyNpc': 'Board and capture {0} NPC ships', 'RamDamage': 'Deal {0} ramming damage',
    'BuyAndSell': 'Trade {0} goods: buy in the south or Arab region, sell in the north', 'KillEmpireNpcInSeamlessSea': 'Sink {0} Empire ships in the open sea',
    'CollectAndSellFish': 'Catch and sell {0} fish', 'CollectKeys': 'Collect {0} chest keys', 'ArenaNotTraining': 'Play {0} arena battles (not training)',
    'FortDamage': 'Deal {0} damage to forts', 'CollectEmpireDrop': 'Pick up {0} Empire cargo drops', 'WhaleDamage': 'Deal {0} damage to whales',
    'FalkonetDamage': 'Deal {0} damage with swivel guns', 'FireAreaDamage': 'Deal {0} fire damage', 'KillNamedEmpireShips': 'Sink {0} named Empire ship(s)',
    'CollectSpecialUnits': 'Hire {0} special crew', 'KillEmpireLegend': 'Sink {0} Empire legendary ships', 'PassingMapEpic': 'Complete an epic-difficulty map',
    'KillWhale': 'Kill {0} whales', 'KillAnyNpcByMortar': 'Sink {0} NPC ships with mortars',
}
FLAGS = {
    'GoldFishingEnabled': 'Golden fish can be caught while fishing, to spend at the event trader.',
    'PumpkinLootEnabled': 'Ships and loot drop pumpkins.', 'RandomizedQuestDays': 'The daily quests come in a different order for each player.',
    'FastFortRespawnEnabled': 'Forts come back faster after they are captured.', 'EventMapDropEnabled': 'Event treasure maps drop.',
    'AltarGoldFishEnabled': 'Altars can give golden fish.', 'SnowballEnabled': 'Snowball shot is available.', 'IceBallsDropEnabled': 'Ice shot drops.',
    'AmberChestEnabled': 'Amber chests can be found.', 'IcebergEnabled': 'Icebergs appear at sea.',
}
EVENT_NAMES = {'Halloween': 'Halloween', 'NewYear': 'New Year', 'Anniversary': 'Anniversary', 'Spring': 'Spring Festival'}


_esc = _html.escape


def _quest_text(q):
    m = re.match(r'(\w+)\((.*)\)$', q)
    if not m:
        return q
    name, args = m.group(1), [a.strip() for a in m.group(2).split(',')]
    nums = [a for a in args if re.fullmatch(r'\d+', a)]
    tpl = QUESTS.get(name)
    if tpl:
        return tpl.format(*([f'{int(n):,}' for n in nums] or ['']))
    return re.sub(r'(?<!^)(?=[A-Z])', ' ', name).capitalize() + (f' ({", ".join(nums)})' if nums else '')


def events_pages(b, crumbs, page):
    crumbs = [('Main page', 'index.html'), ('Guides & mechanics', 'category/articles.html'), ('Events', 'guide/events.html')]
    try:
        events = json.loads((site_extras.DATA / 'events.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return 0
    res = site_extras.resource_names(b.db, b.build)
    designs = {int(d.get('SourceRecord') or -1): d for d in b.entities.get('cosmetic', [])}
    decor = {int(d.get('SourceRecord') or -1): d for d in b.entities.get('decoration', [])}
    ships = {str(s.get('ID')): s['_title'] for s in b.entities.get('ship', [])}
    cans = {int(c.get('SourceRecord') or -1): c['_title'] for c in b.entities.get('cannon', [])}
    ammo = {int(a.get('SourceRecord') or -1): a.get('EnglishName') for a in site_extras.records(b.db, 'CannonBalls', b.build)}
    fish = 'the event currency' + (f' (in the game files now: {res[69]})' if res.get(69) else '')

    def dlink(i, kind='cosmetic'):
        d = (designs if kind == 'cosmetic' else decor).get(i)
        if not d:
            return f'design #{i}' if kind == 'cosmetic' else f'decoration #{i}'
        u = b.urls.get((kind, d['_title'].casefold())); ic = b.icons.get((kind, d['_title'].casefold()))
        img = f'<img class="ticon" src="../{ic}" alt="" width="28" height="28" loading="lazy">' if ic else ''
        return img + (f'<a href="../{u}">{_esc(d["_title"])}</a>' if u else _esc(d['_title']))

    def offer(o):
        if o.get('ship'):
            return 'Ship: ' + _esc(ships.get(str(o['ship']), f'ship #{o["ship"]}'))
        if o.get('design') is not None:
            return dlink(o['design'])
        if o.get('res'):
            rid, q, kind = o['res']
            n = ammo.get(rid) if kind == 'Ammo' else res.get(rid)
            return f'{q:,} × {_esc(n or ("item " + str(rid)))}'
        if o.get('cannon') is not None:
            return f'Cannon: {_esc(cans.get(o["cannon"], "#" + str(o["cannon"])))}'
        if o.get('gold'):
            return f'{o["gold"]:,} gold'
        if o.get('monets'):
            return f'{o["monets"]:,} Coins'
        if o.get('premium'):
            return f'{o["premium"]} days of Premium'
        if o.get('xp'):
            return f'{o["xp"]:,} XP for all ships'
        if o.get('flag'):
            return f'Legendary flag for {o["flag"]} days'
        return '—'

    rows, n = [], 0
    for key, ev in sorted(events.items(), key=lambda kv: kv[1]['start'][5:]):
        name = EVENT_NAMES.get(key, key)
        slug = 'event-' + re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
        days = ''.join(f'<li>{_esc(_quest_text(q))}</li>' for q in ev['days'])
        ms = []
        for d, c in sorted(ev['milestones'].items(), key=lambda kv: int(kv[0])):
            parts = []
            if c.get('coins'): parts.append(f'{c["coins"]} Coins')
            parts += [dlink(i) for i in c.get('designs', [])] + [dlink(i, 'decoration') for i in c.get('decor', [])]
            if c.get('premium'): parts.append(f'{c["premium"][0]} days of Premium (or {c["premium"][1]} Coins if you already have it)')
            parts += [f'{int(q):,} more {_esc(res.get(int(r), "item " + r))}' for r, q in c.get('items', {}).items()]
            parts += [f'the achievement “{_esc(re.sub(r"(?<!^)(?=[A-Z])", " ", a))}”' for a in c.get('achievement', [])]
            ms.append([str(d), ', '.join(parts)])
        daily = ', '.join([f'{q:,} {_esc(res.get(int(r), "item " + r))}' for r, q in ev['daily'].get('items', {}).items()]
                          + [f'{q:,} {_esc(ammo.get(int(r), "ammo " + r))}' for r, q in ev['daily'].get('balls', {}).items()])
        first = ', '.join([dlink(i) for i in ev['first_open'].get('designs', [])] + [dlink(i, 'decoration') for i in ev['first_open'].get('decor', [])])
        npc = ships.get(str(ev.get('npc_ship'))) if ev.get('npc_ship') else None
        body = (f'<p>The {_esc(name)} event lasts <b>{len(ev["days"])} days</b>. The last time the game set it up, it started on <b>{ev["start"]}</b>; '
                'it comes back every year around the same date. The event currency stays usable for 3 days after the end.</p>'
                + (f'<p>Opening the event the first time gives you {first}.</p>' if first else '')
                + '<h2 id="features">What changes during the event</h2><ul>' + ''.join(f'<li>{_esc(FLAGS.get(f, f))}</li>' for f in ev['flags'])
                + (f'<li>An event ship sails the seas: <b>{_esc(npc)}</b>.</li>' if npc else '')
                + (f'<li>All ships are {ev["ship_discount"] * 100:.0f}% cheaper.</li>' if ev.get('ship_discount') else '') + '</ul>'
                + f'<h2 id="quests">Daily quests</h2><p>One quest a day. Each one you finish gives <b>{daily}</b> (the event currency changes its name and look from event to event). '
                + ('The order is different for every player. ' if 'RandomizedQuestDays' in ev['flags'] else '')
                + f'A quest you do not want can be skipped for 89 Coins.</p><ol>{days}</ol>'
                + '<h2 id="milestones">Rewards for days completed</h2><p>Extra rewards for the number of days you have finished, in any order:</p>'
                + site_extras._table(['Days finished', 'Reward'], ms)
                + (f'<h2 id="trader">Event trader</h2><p>Prices are in {_esc(fish)}. Offers marked “once per event” can be bought one time.</p>' + site_extras._table(['Offer', 'Price'], [
                    [offer(o) + (' <span class="pl-sub">(once per event)</span>' if o.get('once') else ''), f'{o["price"]:,}'] for o in ev.get('trader', [])]) if ev.get('trader') else ''))
        b._write(f'guide/{slug}.html', page(f'{name} event', body, depth=1, crumbs=crumbs, tab='Guide'))
        b.search.append({'t': f'{name} event', 'u': f'guide/{slug}.html', 'c': 'Event', 'k': 'event quests rewards trader ' + ' '.join(ev['flags'])})
        rows.append([f'<a href="{slug}.html">{_esc(name)}</a>', ev['start'][5:].replace('-', '/') + ' (month/day)', f'{len(ev["days"])} days',
                     _esc('; '.join(FLAGS.get(f, f).rstrip('.') for f in ev['flags'] if f not in ('RandomizedQuestDays', 'GoldFishingEnabled')))])
        n += 1
    over = ('<p>The game runs four yearly events. Each has 14 daily quests, rewards for the days you finish, event-only features at sea and a trader '
            'who takes golden fish.</p>' + site_extras._table(['Event', 'Usually starts', 'Length', 'Highlights'], rows))
    b._write('guide/events.html', page('Events', over, depth=1, crumbs=crumbs[:2], tab='Guide'))
    b.search.append({'t': 'Events', 'u': 'guide/events.html', 'c': 'Guide', 'k': 'events halloween new year anniversary spring festival'})
    return n


# ================================================================================================ forts, altars, weather
def _unused_sector_table(guns, half_arc=45):
    def d(a, b):
        return abs((a - b + 180) % 360 - 180)
    rows = []
    for t in range(0, 360, 30):
        n = sum(1 for g in guns if d(g['f'], t) < half_arc)
        rows.append([f'{t}°', str(n), '■' * n])
    return rows


def world_pages(b, crumbs, page):
    import shutil
    crumbs = [('Main page', 'index.html'), ('Guides & mechanics', 'category/articles.html')]
    altar = None
    try:
        chests = json.loads((b.out / 'data' / 'chests.json').read_text(encoding='utf-8'))
        altar = chests['chests'].get('altar')
    except (OSError, ValueError, KeyError):
        pass
    # ---- Imperial forts: three different buildings
    try:
        fd = json.loads((site_extras.DATA / 'forts.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        fd = {'types': {}, 'placements': []}
    (b.out / 'assets' / 'img').mkdir(parents=True, exist_ok=True)
    ports = (getattr(b, 'world', None) or {}).get('ports', []) if isinstance(getattr(b, 'world', None), dict) else []
    def near(px, py):
        if not ports:
            return None
        pt = min(ports, key=lambda q: (q['x'] - px) ** 2 + (q['y'] - py) ** 2)
        return pt.get('n')
    count = {}
    for pl in fd.get('placements', []):
        count[pl['m'][-1]] = count.get(pl['m'][-1], 0) + 1
    half = fd.get('half_arc', 45)
    sections, summary = [], []
    for n, t in sorted(fd.get('types', {}).items()):
        pic = site_extras.DATA / f'worldfort{n}-coverage.webp'
        img = ''
        if pic.is_file():
            shutil.copyfile(pic, b.out / 'assets' / 'img' / f'worldfort{n}-coverage.webp')
            img = (f'<figure class="fig-right"><img src="../assets/img/worldfort{n}-coverage.webp" alt="Imperial fort type {n} from above with its guns" '
                   'width="500" height="500" loading="lazy"><figcaption>Red dots are guns, the black line shows where each faces. '
                   'Ring: red where many guns reach you, green where few do.</figcaption></figure>')
        sect = t['sectors']; dirs = list(range(0, 360, 30))
        lo = min(sect); hi = max(sect)
        safest = [f'{dirs[k]}°' for k, v in enumerate(sect) if v == lo]
        where = [near(pl['x'], pl['y']) for pl in fd.get('placements', []) if pl['m'][-1] == n]
        where_txt = (f'<p><b>{count.get(n, 0)} on the world map</b>' + (f', near {", ".join(sorted({w for w in where if w}))}' if where and count.get(n, 0) <= 6 and any(where) else '') + '.</p>'
                     if count.get(n) else '<p>Not placed on the open-sea map in the current game files (it may be used elsewhere or later).</p>')
        rows = [[f'{dd}°', str(v), '■' * v] for dd, v in zip(dirs, sect)]
        sections.append(f'<h2 id="type{n}">Fort type {n}: {len(t["guns"])} guns</h2>' + img + where_txt
                        + f'<p>Safest: <b>{", ".join(safest)}</b> ({lo} guns can bear). Most dangerous: up to {hi} guns at once.</p>'
                        + site_extras._table(['Direction', 'Guns that can bear', ''], rows) + '<div style="clear:both"></div>')
        summary.append([f'<a href="#type{n}">Type {n}</a>', str(len(t['guns'])), str(count.get(n, 0)), ', '.join(safest), str(lo), str(hi)])
    total = sum(count.values())
    body = ('<p><b>Imperial forts</b> are the Empire\'s strongholds on the open sea' + (f' ({total} on the world map)' if total else '') + '. '
            'They are not all the same: the game has <b>three fort buildings</b>, each with its own layout of guns, so the safe side differs from fort to fort. '
            'Recognise the type by its shape from above, then come in from its weak side.</p>'
            + site_extras._table(['Fort', 'Guns', 'On the map', 'Safest directions', 'Guns there', 'Most guns'], summary)
            + f'<p>How to read it: every gun faces outwards and only fires at ships inside its arc. The counts assume each gun can swing {half}° either way '
            '(the exact arc is set by the server, not stored in the game files). Directions are measured around the fort as drawn: 0° is the right-hand side '
            'of the picture, 90° the top, 180° the left, 270° the bottom (the side with the curved wall). Guns also have a short dead zone right under the walls.</p>'
            + ''.join(sections)
            + '<h2 id="loot">Loot</h2><ul><li>The fort shows its current reward before you attack; it changes from fort to fort and over time (the server decides it).</li>'
            '<li>When the fort falls it drops a <b>loot crate that floats for 15 minutes</b>. Sail right up to it to pick it up; anyone can take it.</li>'
            '<li>“Deal damage to forts” is a common event quest.</li></ul>'
            '<h2 id="respawn">Respawn</h2><p>A captured fort comes back after a while. The timer is kept on the server, so it is not in the game files; '
            'during the <a href="event-halloween.html">Halloween event</a> forts come back faster.</p>'
            '<p>See them on the <a href="../map.html">world map</a> (Forts layer), and the <a href="../tools/defenses.html">Towers, Forts &amp; Mortars</a> tool for port-battle defences.</p>')
    b._write('guide/imperial-forts.html', page('Imperial forts', body, depth=1, crumbs=crumbs, tab='Guide'))
    b.search.append({'t': 'Imperial forts', 'u': 'guide/imperial-forts.html', 'c': 'Guide', 'k': 'fort empire loot respawn angles guns'})
    # ---- altars
    if altar:
        rows = [[_esc(r['label']), f'{r["pct"]:.1f}%'] for r in sorted(altar['rewards'], key=lambda r: -r['w'])]
        nalt = len(getattr(b, 'world', {}).get('altars', []) or []) if isinstance(getattr(b, 'world', None), dict) else 0
        body = ('<p><b>Altars</b> are small shrines on islands around the world' + (f' ({nalt} on the world map)' if nalt else '') + '. '
                'Make an offering and the altar gives one reward, drawn from the table below with the game\'s own weights.</p>'
                + site_extras._table(['Reward', 'Chance'], rows)
                + '<p>During some events (Anniversary, Spring Festival, New Year) altars can also give the event currency. '
                'Try your luck without sailing out in the <a href="../tools/chest-simulator.html">chest simulator</a> (choose “Altar offering”), '
                'and find altars on the <a href="../map.html">world map</a>.</p>')
        b._write('guide/altars.html', page('Altars', body, depth=1, crumbs=crumbs, tab='Guide'))
        b.search.append({'t': 'Altars', 'u': 'guide/altars.html', 'c': 'Guide', 'k': 'altar offering loot rewards skull'})
    # ---- wind and weather
    body = ('<p>How the game decides the wind, the weather and the sea, from the game\'s weather rules. For how much speed a ship gets at each angle to the wind, '
            'see <a href="../tools/wind-rose.html">Wind &amp; Sailing</a>.</p>'
            '<h2 id="wind">Wind direction</h2><ul>'
            '<li>There is <b>one wind for the whole open sea</b>: every ship feels the same direction. The server picks it and changes it from time to time.</li>'
            '<li>A change is not instant: the wind <b>turns smoothly to the new direction over 20 seconds</b>.</li>'
            '<li>Arena battles use a fixed wind from one diagonal, so every match starts the same.</li></ul>'
            '<h2 id="sea">Sea state and wind strength</h2><p>The sea has four states. Changes blend in over 60 seconds.</p>'
            + site_extras._table(['Sea', 'Wave height', 'Wind strength'], [['Calm', '0.3', '15%'], ['Restless', '0.7', '40%'], ['Storm', '1.1', '70%'], ['Dangerous storm', '3.5', '100%']])
            + '<p>Waves are lower over shallow water (down to 60% of the sea state\'s height) and higher over deep water (up to about twice it).</p>'
            '<h2 id="storms">Storms and fog banks</h2><ul>'
            '<li>At most <b>one storm</b> and <b>two fog banks</b> are at sea at a time.</li>'
            '<li>A storm forms at the edge of the world on the side the wind blows from, then drifts downwind and crosses the whole map in about <b>23 minutes</b>. '
            'Fog banks drift at half that speed.</li>'
            '<li>A storm is huge: its outer edge reaches about a third of the map\'s width from its centre, and its violent core about a sixth. Sizes vary by up to 30%. Fog banks are 40% of that size.</li>'
            '<li>Inside a storm the waves rise towards the dangerous-storm height and the wind blows harder. The edges of the world are always stormy.</li>'
            '<li>The volcano is wrapped in its own fog, out to about a tenth of the map\'s width.</li></ul>'
            '<h2 id="whirlpool">The whirlpool (sea current)</h2><p>The only current in the game is the <b>whirlpool</b>:</p><ul>'
            '<li>It appears somewhere new about <b>every 12 hours</b>, grows to full size quickly, stays, then fades away before moving.</li>'
            '<li>At full size it reaches about four or five large-ship lengths from its centre. Inside, it both <b>pulls ships towards the centre</b> and <b>swings them around it</b>, '
            'gently at the edge and hardest near the middle.</li>'
            '<li>The sea surface sinks into a funnel towards the centre.</li></ul>')
    b._write('guide/wind-and-weather.html', page('Wind, weather and currents', body, depth=1, crumbs=crumbs, tab='Guide'))
    b.search.append({'t': 'Wind, weather and currents', 'u': 'guide/wind-and-weather.html', 'c': 'Guide', 'k': 'wind direction weather storm fog whirlpool current waves'})


# ================================================================================================ store
TIER_PRICES = {  # DonateShopApply.GetDesignPriceByTier (Coins)
    'ShipFullDesign': {1: 390, 2: 490, 3: 690, 4: 990, 5: 1290, 'U': 9779}, 'SailTexture': {1: 137, 2: 370, 3: 590},
    'Decal1': {1: 137, 2: 370, 3: 590, 4: 900}, 'Decal2': {1: 137, 2: 370, 3: 590, 4: 900}, 'Flag': {1: 77, 2: 170},
    'Satellite': {1: 259, 2: 370, 3: 579, 4: 757}, 'BowFigure': {1: 127, 2: 290, 3: 370}}
KIND_NAMES = {'ShipFullDesign': 'Ship skin', 'SailTexture': 'Sail cloth', 'Decal1': 'Paint', 'Decal2': 'Sail pattern', 'Flag': 'Flag',
              'Satellite': 'Lantern', 'BowFigure': 'Figurehead'}


def design_price(rec, ship_rank=None):
    """(coins, gold) for a ship design, or (None, None) when it is not sold. Skins for rank 5-7 ships cost 34% less."""
    shop = str(rec.get('InShop') or '')
    m = re.match(r'ByGold\s+(\d+)', shop)
    if m:
        return None, int(m.group(1))
    if not shop.lower().startswith('true'):
        return None, None
    t = re.search(r'Tier(\w+)', shop)
    tier = (int(t.group(1)) if t.group(1).isdigit() else t.group(1)) if t else 1
    price = TIER_PRICES.get(rec.get('Category'), {}).get(tier)
    if price and ship_rank is not None and ship_rank >= 5:
        price = int(price * 0.66)
    return price, None


def shop_page(b, crumbs, page):
    crumbs = [('Main page', 'index.html'), ('Guides & mechanics', 'category/articles.html')]
    ranks = {str(s.get('ID')): s.get('ShipRank') for s in b.entities.get('ship', [])}
    rows = []
    for r in b.entities.get('cosmetic', []):
        try:
            rk = int(ranks.get(str(r.get('ShipId')))) if r.get('ShipId') not in (None, '', -1, '-1') and ranks.get(str(r.get('ShipId'))) else None
        except (TypeError, ValueError):
            rk = None
        coins, gold = design_price(r, rk)
        if coins is None and gold is None:
            continue
        u = b.urls.get(('cosmetic', r['_title'].casefold())); ic = b.icons.get(('cosmetic', r['_title'].casefold()))
        img = f'<img class="ticon" src="../{ic}" alt="" width="28" height="28" loading="lazy">' if ic else ''
        rows.append([img + (f'<a href="../{u}">{_esc(r["_title"])}</a>' if u else _esc(r['_title'])), KIND_NAMES.get(r.get('Category'), r.get('Category') or ''),
                     f'{coins:,} Coins' if coins else f'{gold:,} gold', _esc(r.get('_bonus') or '')])
    rows.sort(key=lambda x: (x[1], x[0]))
    try:
        ch = json.loads((site_extras.DATA / 'chests.json').read_text(encoding='utf-8'))
        cp = ch['prices']
    except (OSError, ValueError, KeyError):
        cp = {}
    seal = [('3 days', 99), ('7 days', 155), ('30 days', 535), ('90 days', 1390), ('180 days', 2590), ('Permanent', 4770)]
    body = ('<p>What the in-game Store sells for <b>Coins</b>, what it costs, and the sales that come round. Prices are the game\'s own; '
            'real-money packages and Coin bundles are priced by the platform and are not listed here.</p>'
            '<h2 id="sales">Sales and discounts</h2><p>The Store runs timed sales, announced in the game\'s news. The kinds of sale the game knows:</p>'
            + site_extras._table(['Sale', 'Discount'], [
                ['Hold Restocking', '15% off items and designs bought with Coins'], ['Victory Hour', '20% off items and designs bought with Coins'],
                ['Hour of Privileges', '10% off any Captain\'s Seal'], ['Treasure Vault', '15% off large chests and treasures'],
                ['Season: Ships', '10% off building ships of one class for the season'], ['Opening 10 chests at once', '5% off, always']])
            + '<p>When a sale runs and how long it lasts are decided by the developers on the server, so they are not in the game files. '
            'Several sales of the same kind add together. Some events also make every ship cheaper to build.</p>'
            '<h2 id="seal">Captain\'s Seal (Premium)</h2>' + site_extras._table(['Length', 'Price'], [[a, f'{p:,} Coins'] for a, p in seal])
            + '<p>The Arena Store also sells 2, 4 or 6 days of Premium for 500, 1,000 or 1,500 arena points, and a 7-day Legendary Flag for 2,000.</p>'
            '<h2 id="services">Services</h2>' + site_extras._table(['Service', 'Price'], [
                ['Peace Treaty: 4 hours of Peace Flags everywhere, no extra mooring fee', '127 Coins'],
                ['Hired Miners: 7 days of +50% crafting time and +50% mine and manufactory speed', '297 Coins'],
                ['Hold Insurance: 1 hour at sea with your hold hidden and safe', '40 Scrolls'], ['Port slot for one more ship', '75 Coins (or Voodoo Skulls up to a limit)']])
            + ('<h2 id="chests">Chests</h2>' + site_extras._table(['Chest', 'Price'], [
                ['Large Chest', f'{cp["single"]} Coins'], ['3 Large Chests (three different rewards)', f'{cp["triple"]} Coins'],
                ['Elite (Imperial) Chest', f'{cp["elite"]} Coins'], ['Inca Treasure Chest', f'{cp["incas"]} Coins'],
                ['New Year Chest', f'{cp["newyear"]} Coins'], ['Specialists: 5 random special crew of a category', f'{cp["crew"]} Coins']])
                + '<p>Chest keys found in the game open a chest for free. See every reward and its odds in the <a href="../tools/chest-simulator.html">chest simulator</a>.</p>'
                if cp else '')
            + '<h2 id="designs">Designs</h2><p>Every design the Store sells, at its full price. Skins for rank 5–7 ships cost 34% less than for bigger ships.</p>'
            '<p><input class="tfilter" type="search" placeholder="Filter designs…" aria-label="Filter designs"></p>'
            + site_extras._table(['Design', 'Kind', 'Price', 'Bonus'], rows))
    b._write('guide/store.html', page('Store', body, depth=1, crumbs=crumbs, tab='Guide'))
    b.search.append({'t': 'Store', 'u': 'guide/store.html', 'c': 'Guide', 'k': 'shop store coins prices discounts sale premium seal chest designs'})


def npc_ships_page(b, crumbs, page):
    crumbs = [('Main page', 'index.html'), ('Missions & NPCs', 'category/missions.html')]
    def row(s):
        u = b.urls.get(('ship', s['_title'].casefold())); ic = b.icons.get(('ship', s['_title'].casefold()))
        img = f'<img class="ticon" src="../{ic}" alt="" width="40" height="40" loading="lazy">' if ic else ''
        name = img + (f'<a href="../{u}">{_esc(s["_title"])}</a>' if u else _esc(s['_title']))
        return [name, str(s.get('ShipRank') or ''), _esc(s.get('TypeEnglish') or s.get('Type') or ''), f'{int(s.get("Health") or 0):,}',
                f'<a href="../tools/ship-viewer.html?ship={_esc(s["_title"])}">3D model</a>']
    ships = b.entities.get('ship', [])
    empire = [s for s in ships if str(s.get('Coolness', '')).startswith('Empire')]
    npc = [s for s in ships if str(s.get('CanBeUsedForNpc')).lower() == 'true' and s not in empire]
    if not empire and not npc:
        return
    head = ['Ship', 'Rank', 'Class', 'Hull HP', 'Model']
    key = lambda s: (int(s.get('ShipRank') or 9), s['_title'])
    body = ('<p>NPC captains sail the same ships players do, so every NPC ship has its own page, picture and 3D model. '
            'Event bosses and the Empire\'s fleet use ships players cannot normally build.</p>'
            + (f'<h2 id="empire">Empire and event ships</h2>' + site_extras._table(head, [row(s) for s in sorted(empire, key=key)]) if empire else '')
            + (f'<h2 id="npc">Ships NPCs sail</h2><p>{len(npc)} player ships can turn up under an NPC flag: pirates, traders and Empire patrols.</p>'
               + site_extras._table(head, [row(s) for s in sorted(npc, key=key)]) if npc else '')
            + '<p>Where they appear: the <a href="../category/missions.html">PvE missions</a> list the NPC waves of each map, and event pages name each event\'s special ship.</p>')
    b._write('guide/npc-ships.html', page('NPC ships', body, depth=1, crumbs=crumbs, tab='Guide'))
    b.search.append({'t': 'NPC ships', 'u': 'guide/npc-ships.html', 'c': 'Guide', 'k': 'npc ships empire pirates traders models ghost ship'})
