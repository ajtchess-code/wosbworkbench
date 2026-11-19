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
        aid = str(a.get('ID') or '')
        if aid.startswith('cball_') and aid[6:].isdigit() and a.get('EnglishName') and a['EnglishName'] != 'removed':
            n = int(aid[6:]); ammo_names[n] = a
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
    return len(data['recipes'])
