"""Build a public fan wiki website from the Workbench catalog and articles.

Layout follows classic game wikis (left navigation, top search, entity pages
with an infobox, category tables): our own name and styling.

Public-safe by design:
* No code, file paths, internal ids, decompiled source or message layouts.
  Articles in research sections are skipped.
* No game model files: ship pages show reconstructed hit *zones* (boxes),
  not meshes, unless ``include_models`` is set for a private/local build.
* Static files only: works from disk, GitHub Pages or any web host.
"""
from __future__ import annotations

import html
import json
import math
import re
import shutil

import site_legal
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

SITE_NAME = 'WoSB Wiki'
SITE_URL = 'https://wosbwiki.org/'
# Who runs the public site and how it is paid for. SiteBuilder fills this from its ``hosting`` argument.
HOSTING_DEFAULTS = {'site_url': SITE_URL, 'site_name': SITE_NAME, 'ad_client': 'ca-pub-6442579332215350', 'donate_url': 'https://paypal.me/litefootz',
                    'discord_url': '', 'contact_email': 'contact@wosbwiki.org', 'standalone': True, 'gtm_id': 'GTM-TMZFVXTL'}
HOSTING = dict(HOSTING_DEFAULTS)
COSMETIC_KIND = {'ShipFullDesign': 'Ship design (skin)', 'SailTexture': 'Sail cloth', 'Decal1': 'Paint', 'Decal2': 'Sail pattern', 'Decal3': 'Premium sail pattern',
                 'Flag': 'Flag', 'Flag2': 'Second flag', 'BowFigure': 'Figurehead', 'Satellite': 'Lantern', 'MastColor': 'Mast colour'}
# Short game-guide pages folded into one topic page each: target slug -> (title or None to extend an existing page, intro, source keys)
GUIDE_MERGE = {
    'ships-guns-and-consumables': ('Ships, guns and consumables', 'How ships, artillery, special weapons and consumables work, from the game\'s own help pages.',
                                   ['buildingships', 'weapons', 'ammonition', 'powerupitems']),
    'boarding': (None, '', ['boarding', 'shipscapturing', 'crew']),
    'sailing-and-wind': (None, '', ['windandspeed', 'windrose', 'storm']),
    'ports-and-port-battles': ('Ports and port battles', 'Ports, town growth, tension, plunder and port battles, from the game\'s own help pages.',
                               ['ports', 'hqs', 'tensity', 'portsrobbing', 'portscapturing']),
    'guilds-and-factions': ('Guilds and factions', 'How guilds and factions work: development, influence, the vault and treasury, and the social menu.',
                            ['guildsfractions', 'guildsgrow', 'treasury', 'socialmenu']),
    'trading-and-crafting': ('Trading, crafting and making money', 'Ways to earn gold: trading, merchants at sea, mines, the workshop and your hold.',
                             ['earning', 'trading', 'tradersinsea', 'factories', 'workshop', 'hold']),
    'pvp-and-reputation': ('PvP, flags and notoriety', 'Fighting other captains, choosing a flag and what raises your notoriety.', ['pvp', 'flags', 'wanted-level']),
    'the-world-and-npc-ships': ('The world, adventures and NPC ships', 'The Archipelago\'s story, water danger and adventures, and the ships the game sails itself.',
                                ['cataclysm', 'travallingandhazard', 'nps']),
}
MECHANICS_MERGE = {'damage-formula': ['damage-formula-calibration']}
PRIVATE_SECTIONS = {'Research', 'Research backlog', 'Client metadata & research evidence', 'Networking and protocols'}
PRIVATE_SOURCE_KINDS = {'decompiled-client'}
HIDDEN_FIELDS = {'Source', 'SourceRecord', 'Name', 'IconName', 'IconTexture', 'IconTextureName', 'Icon', 'Texture',
                 'TexturePath', 'Model', 'StaticInfoID', 'ConstructionDataStatus', 'EnglishName', 'EnglishDescription',
                 'NameEnglish', 'PortName', 'PortNameEnglish', 'SubtypeEnglish', 'TypeEnglish', 'IDEnglish', 'PowerUpId',
                 'ID', 'Subtype', 'InternalBaseSpeed', 'GoldCostStatus', 'ConstructionStatus', 'Status'}

# entity kind -> (dataset, plural title, infobox fields [(field, label, fmt)], table columns)
ENTITIES = {
    'ship': ('ShipsToPlay', 'Ships', [
        ('Type', 'Class', 'camel'), ('SubtypeEnglish', 'Type', None), ('ShipRank', 'Rank', None),
        ('RequiredRank', 'Required rank', None), ('Coolness', 'Tier', 'tier'), ('Fraction', 'Faction', 'none'),
        ('Health', 'Hull HP', 'int'), ('Armor', 'Armor', None), ('BasicSpeed', 'Speed', None),
        ('BasicMobility', 'Mobility', None), ('BaseCrewPlaces', 'Crew', 'int'), ('CapacityCg', 'Cargo', 'int'),
        ('PlacesForUnitsCount', 'Unit slots', None), ('ExtraPlacesForUpgrades', 'Extra upgrade slots', None)],
        ['Type', 'Rank', 'Hull HP', 'Armor', 'Speed', 'Mobility', 'Crew', 'Cargo']),
    'cannon': ('Cannons', 'Cannons', [
        ('Category', 'Category', 'camel'), ('Poundage', 'Poundage', None), ('Penetration', 'Penetration', None),
        ('Distance', 'Range', None), ('Cooldown', 'Reload (s)', None), ('Angle', 'Vertical angle', None),
        ('Scatter', 'Scatter', 'first'), ('SpeedFactor', 'Ball speed', 'first'), ('SplashRadius', 'Splash radius', 'first'),
        ('Price', 'Price', 'int'), ('CraftingType', 'Obtained by', 'obtain'), ('Extra', 'Notes', 'extra')],
        ['Category', 'Poundage', 'Penetration', 'Range', 'Reload (s)', 'Price']),
    'ammo': ('CannonBalls', 'Ammunition', [
        ('DamageFactor', 'Damage factor', None), ('Penetration', 'Penetration bonus', None),
        ('DistanceFactor', 'Range factor', None), ('DamageToSailes', 'Sail damage', None),
        ('CrewDamage', 'Crew damage', None), ('ReloadFactor', 'Reload factor', None), ('Speed', 'Speed factor', None),
        ('MassKg', 'Mass (kg)', None), ('SingleCost', 'Cost per shot', None), ('IsRare', 'Rare', 'bool'),
        ('Effects', 'Effects', 'effects')],
        ['Damage factor', 'Penetration bonus', 'Range factor', 'Sail damage', 'Crew damage', 'Reload factor']),
    'upgrade': ('ShipUpgradesNew', 'Ship upgrades', [
        ('Category', 'Slot', 'category'), ('EffectsBoost', 'Effect', 'effects'), ('WearType', 'Wear', 'none'),
        ('LowCost', 'Budget version', 'bool')], ['Slot', 'Effect']),
    'crew': ('UnitsInfo', 'Crew', [
        ('TypeEnglish', 'Type', None), ('Cost', 'Cost', 'int'), ('DHealth', 'Health', None),
        ('DDamage', 'Damage', None), ('DCapacity', 'Capacity', None), ('Effect', 'Effect', 'effects')],
        ['Type', 'Cost', 'Health', 'Damage', 'Effect']),
    'skill': ('CaptainSkills', 'Captain skills', [
        ('Effect', 'Effect', 'effects'), ('CostPoints', 'Skill points', None), ('RequiredRank', 'Required rank', 'none')],
        ['Effect', 'Skill points']),
    'resource': ('Resources', 'Resources', [
        ('Mass', 'Mass', None), ('MediumCost', 'Typical price', 'int'), ('Effects', 'Effects', 'effects')],
        ['Mass', 'Typical price']),
    'port': ('WorldPorts', 'Ports', [
        ('Type', 'Type', 'porttype'), ('LegalFraction', 'Faction', 'faction'), ('ProducedResourceId', 'Produces', 'produce'),
        ('BuildShipRangs', 'Shipyard builds', 'rankup'), ('PbsTeamLimitation', 'Port battle size', 'pbsize'), ('Flags', 'Features', 'portflags')],
        ['Type', 'Faction', 'Produces', 'Shipyard builds']),
    'achievement': ('Achievements', 'Achievements', [
        ('UiCategory', 'Category', None), ('CommonRatingWeight', 'Rating weight', None)], ['Category', 'Rating weight']),
    'cosmetic': ('ShipDesingElements', 'Ship cosmetics', [
        ('Category', 'Kind', 'cosmetic'), ('InShop', 'In shop', 'shop'), ('BonusEffectType', 'Bonus', 'fxname'),
        ('BonusEffectValue', 'Bonus value', None), ('EnglishDescription', 'Description', None)], ['Kind', 'In shop', 'Bonus']),
    'decoration': ('EnvDesingElements', 'Island decorations', [
        ('InShop', 'How to get', 'shop'), ('EnglishDescription', 'Description', None)], ['How to get']),
    'recipe': ('Crafting_Recipes', 'Crafting recipes', [
        ('Category', 'Workshop', None), ('Context', 'Where', None), ('CraftHours', 'Hours', None), ('OutputQuantity', 'Makes', None),
        ('InputGold', 'Gold', 'int'), ('OutputType', 'Output type', 'camel')], ['Workshop', 'Hours', 'Makes', 'Gold']),
}
NAV = [('Main page', 'index.html'), ('Ships', 'category/ships.html'), ('Cannons', 'category/cannons.html'),
       ('Ammunition', 'category/ammo.html'), ('Ship upgrades', 'category/upgrades.html'), ('Crew', 'category/crew.html'),
       ('Captain skills', 'category/skills.html'), ('Resources', 'category/resources.html'), ('Ports', 'category/ports.html'),
       ('Achievements', 'category/achievements.html'), ('Ship cosmetics', 'category/cosmetics.html'),
       ('Island decorations', 'category/decorations.html'), ('Crafting', 'category/recipes.html'), ('Missions & NPCs', 'category/missions.html'),
       ('World map', 'map.html'),
       ('Guides & mechanics', 'category/articles.html')]
TOOLS = [('Damage simulator', 'tools/damage-simulator.html'), ('Wind & sailing', 'tools/wind-rose.html'),
         ('Ship comparison', 'tools/compare-ships.html'), ('Hitbox viewer', 'tools/hitboxes.html'),
         ('3D ship viewer', 'tools/ship-viewer.html'), ('Hit analysis', 'tools/hit-analysis.html'), ('Towers, forts & mortars', 'tools/defenses.html'), ('Fire calculator', 'tools/fire-calculator.html'),
         ('Battle simulator', 'tools/battle-simulator.html'), ('Boarding simulator', 'tools/boarding-simulator.html')]
CATEGORY_FILE = {'ship': 'ships', 'cannon': 'cannons', 'ammo': 'ammo', 'upgrade': 'upgrades', 'crew': 'crew',
                 'skill': 'skills', 'resource': 'resources', 'port': 'ports', 'achievement': 'achievements',
                 'cosmetic': 'cosmetics', 'decoration': 'decorations', 'recipe': 'recipes'}
SLOT_NAMES = {'Sailes': 'Sails', 'Corpus': 'Hull', 'Cannons': 'Cannons', 'Crew': 'Crew'}
EFFECT_WORDS = {'Hp': 'HP', 'Pvp': 'PvP', 'Npc': 'NPC', 'Sailes': 'Sails'}


def _slug(text):
    s = re.sub(r'[^a-z0-9]+', '-', str(text).casefold()).strip('-')
    return s or 'page'


def _camel(text):
    return re.sub(r'(?<=[a-z0-9])(?=[A-Z])', ' ', str(text)).strip()


def humanize_effect(text):
    """'PSightSpeed +50' -> 'Sight speed +50%'; 'MMarchingSpeed +4' -> 'Marching speed +4'."""
    parts = []
    for m in re.finditer(r'([PMBC]?)([A-Z][A-Za-z]+)\s*([+-]?\d+(?:\.\d+)?)?', str(text or '')):
        prefix, name, value = m.groups()
        words = _camel(name).split()
        words = [EFFECT_WORDS.get(w, w) for w in words]
        label = ' '.join([words[0]] + [w.lower() if w not in EFFECT_WORDS.values() else w for w in words[1:]]) if words else name
        if value is None:
            parts.append(label)
        else:
            parts.append(f'{label} {value}{"%" if prefix == "P" else ""}')
    return '; '.join(parts) or str(text or '')


def _fmt(value, kind):
    if value is None or value == '':
        return None
    if kind == 'int':
        try:
            return f'{int(float(value)):,}'
        except (TypeError, ValueError):
            return str(value)
    if kind == 'first':
        return str(value).split('|')[0]
    if kind == 'shop':
        v = str(value); m = re.match(r'ByGold\s+(\d+)', v)
        if m:
            return f'{int(m.group(1)):,} gold'
        if v.lower().startswith('true'):
            return 'Premium shop' + (f' (tier {v[-1]})' if 'Tier' in v else '')
        return 'Not sold (rewards, chests, events)' if v.lower() in ('false', '') else _camel(v)
    if kind == 'bool':
        return 'Yes' if value in (True, 'true', 'True', 1) else 'No'
    if kind == 'none':
        return None if str(value) in ('None', '', '0') else _camel(value)
    if kind == 'tier':
        return ' · '.join(_camel(w) for w in str(value).split()).replace('Sailage Legend', 'Sailage legend')
    if kind == 'effects':
        return humanize_effect(value)
    if kind == 'camel':
        return _camel(value)
    if kind == 'category':
        return SLOT_NAMES.get(str(value), _camel(value))
    if kind == 'cosmetic':
        return COSMETIC_KIND.get(str(value), _camel(value))
    if kind == 'porttype':
        return {'City': 'City', 'Bay': 'Bay', 'NeutralBay': 'Neutral bay', 'PirateBay': 'Pirate bay'}.get(str(value), _camel(value))
    if kind == 'faction':
        import site_world
        return site_world.faction_name(str(value))
    if kind == 'produce':
        import site_world
        return site_world.PRODUCE.get(str(value), _camel(str(value)))
    if kind == 'rankup':
        return f'Rank {value} and smaller'
    if kind == 'pbsize':
        return f'{value} per side'
    if kind == 'portflags':
        names = {'StartPort': 'Starting port', 'UnitsSamurai': 'Samurai crews', 'UnitsMusketeer': 'Musketeer crews', 'UnitsFisher': 'Fisher crews',
                 'NearIce': 'Northern ice', 'Arab': 'Arab port', 'OnlyPirateFlag': 'Pirates only', 'Stronghold': 'Stronghold', 'CaptureWithoutWindow': 'No battle window'}
        return ', '.join(names.get(f, _camel(f)) for f in str(value).split()) or None
    if kind == 'obtain':
        return {'ByGold': 'Bought with gold', 'ByCraft': 'Crafted', 'Craft': 'Crafted', 'ByPremium': 'Premium shop'}.get(str(value), _camel(value))
    if kind == 'extra':
        return '; '.join(f'{_camel(k).capitalize()} ×{v}' if v else _camel(k).capitalize() for k, _, v in
                         (part.strip().partition(':') for part in str(value).split(';') if part.strip()))
    if kind == 'fxname':
        return None if str(value) in ('None', '') else fx_label(str(value))[0]
    if isinstance(value, float):
        return f'{value:g}'
    return str(value)


def _e(text):
    return html.escape(str(text), quote=True)


def load_entities(db, *, build='Steam'):
    """{kind: [record dicts]} preferring one build, de-duplicated by English name."""
    out = {}
    descriptions = {}
    for raw, in db.conn.execute("SELECT raw_json FROM records WHERE dataset='English_Names'"):
        rec = json.loads(raw)
        if rec.get('Key') and rec.get('EnglishDescription'):
            descriptions.setdefault(rec['Key'], rec['EnglishDescription'])
    for kind, (dataset, _title, _fields, _cols) in ENTITIES.items():
        rows = db.conn.execute('SELECT raw_json, source_root, name FROM records WHERE dataset=?', (dataset,)).fetchall()
        builds = {r[1] for r in rows}
        chosen = build if build in builds else ('Game' if 'Game' in builds else next(iter(builds), None))
        seen = {}
        for raw, root, name in rows:
            if root != chosen:
                continue
            rec = json.loads(raw)
            title = (rec.get('EnglishName') or rec.get('NameEnglish') or rec.get('PortNameEnglish') or name or '').strip()
            if kind == 'crew':
                m = re.match(r'unit_([a-z]+)_(\d+)', str(rec.get('ID') or ''))
                if m:
                    english = (rec.get('EnglishName') or '').strip()
                    title = f"{m.group(1).capitalize()} unit {m.group(2)}" + (f' ({english})' if english and english.casefold() not in (m.group(1), 'special') else '')
            if not title or title.startswith('(') or 'test' in title.casefold() or (kind == 'ship' and title.isupper()) \
                    or re.fullmatch(r'(removed|deleted|unused|placeholder)\b.*', title.casefold()):
                continue
            if kind == 'ship' and not rec.get('EnglishDescription'):
                rec['EnglishDescription'] = descriptions.get(f"ship_{rec.get('ID')}", '')
            rec['_title'] = title
            key = title.casefold()
            # Same name twice (e.g. flag vs decal): keep the first, suffix later ones by slot/category.
            if key in seen:
                extra = rec.get('Category') or rec.get('Type') or ''
                candidate = f'{title} ({_camel(extra)})' if extra else title
                n = 2
                while candidate.casefold() in seen:
                    candidate = f'{title} ({_camel(extra) + " " if extra else ""}{n})'; n += 1
                rec['_title'] = candidate; key = candidate.casefold()
            seen[key] = rec
        out[kind] = sorted(seen.values(), key=lambda r: r['_title'].casefold())
    return out


# --------------------------------------------------------------- page chrome

STUB_SOURCE_KINDS = {'ontology', 'discovery-audit', 'research-outline', 'auto-capture', 'client-static-evidence', 'derived-research'}
STUB_MARKERS = ('Research status: not yet verified', '*Add verified findings here', 'explanatory text has not yet been')
GUIDE_ORDER = ['Game guide', 'Mechanics', 'Data overviews']
GAMEPEDIA_SEE_ALSO = {
    'boarding': [('Boarding mechanics', '../wiki/boarding.html'), ('Boarding simulator', '../tools/boarding-simulator.html')],
    'windandspeed': [('Sailing and wind', '../wiki/sailing-and-wind.html'), ('Wind & sailing tool', '../tools/wind-rose.html')],
    'windrose': [('Sailing and wind', '../wiki/sailing-and-wind.html'), ('Wind & sailing tool', '../tools/wind-rose.html')],
    'weapons': [('Cannons compared', '../guide/cannons-compared.html'), ('Damage formula', '../wiki/damage-formula.html')],
    'ammonition': [('Ammunition compared', '../wiki/ammunition-compared.html')],
    'portscapturing': [('Port battle rules', '../guide/port-battle-rules.html'), ('Battle simulator', '../tools/battle-simulator.html?preset=pbfleet')],
    'buildingships': [('Ships by rank', '../guide/ships-by-rank.html')],
    'crew': [('Boarding mechanics', '../wiki/boarding.html')],
    'shipscapturing': [('Boarding mechanics', '../wiki/boarding.html')],
    'workshop': [('Crafting recipes', '../category/recipes.html')], 'factories': [('Crafting recipes', '../category/recipes.html')],
}

CSS = r'''
.feature{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:10px;margin:12px 0 18px}.feature a{display:grid;gap:4px;padding:12px 14px;border-radius:8px;
background:linear-gradient(135deg,#123f60,#1d5d86);color:#f6efdc;text-decoration:none}.feature a:hover{filter:brightness(1.12)}.feature b{font:700 17px Georgia,serif;color:#f3d58e}.feature span{font-size:13px;color:#dbe7ee}
ul.cols{columns:3 220px;padding-left:18px}
.mp-notice{text-align:center;font-size:12px;color:#33414e;margin:2px 0 8px}.mp-notice span{color:#b03a2e;font-weight:600}
.mp-quick{max-width:820px;margin:0 auto 14px;border:1px solid #a2a9b1;background:#f8f9fa;text-align:center;font-size:12.5px}.mp-quick p{margin:0;padding:4px 10px;border-top:1px solid #dde2e7}
.mp-quick p:first-child{border-top:0}.mp-quick-main{font-variant:small-caps;font-weight:700;font-size:14px;background:#e8f0f8}.mp-quick-small{font-size:11px;color:#54595d}
.mp-welcome{display:grid;grid-template-columns:minmax(0,1fr) 260px;gap:18px;background:#dfeaf7;border:1px solid #a7c1dd;padding:12px 16px;margin:0 0 16px}
.mp-title{border:0;margin:0 0 8px;text-align:center;font:700 17px system-ui,sans-serif}
.mp-hero{position:relative;overflow:hidden;display:flex;align-items:center;gap:16px;max-width:560px;margin:0 auto 10px;padding:14px 18px;min-height:150px;border-radius:6px;
 background:radial-gradient(circle at 25% 40%,#2a6fa3,#0d2e4b 75%);color:#f6efdc;box-shadow:inset 0 0 0 2px #c9994a}
.mp-hero-logo{filter:drop-shadow(0 0 6px rgba(255,255,255,.55)) drop-shadow(0 2px 4px rgba(0,0,0,.4));background:rgba(255,255,255,.85);border-radius:50%;padding:8px;position:relative;z-index:1}
.mp-hero b{display:block;font:700 34px/1.1 Georgia,serif;color:#f3d58e;position:relative;z-index:1}.mp-hero span{font-size:13px;color:#dbe7ee;position:relative;z-index:1}
.mp-hero-ship{position:absolute;right:-20px;bottom:-12px;height:150px;opacity:.9}
.mp-visitors{font-size:13px}.mp-visitors h3{margin:0 0 4px}.mp-visitors ul{padding-left:18px;margin:4px 0}
.mp-h{margin-top:10px}.mp-h small{font-size:13px}
.mp-news{display:flex;gap:10px;overflow-x:auto;padding:4px 2px 10px;scroll-snap-type:x mandatory;background:#dfeaf7;border:1px solid #a7c1dd;padding:10px}
.mp-card{flex:0 0 340px;scroll-snap-align:start;background:#fff;border:1px solid #c8ccd1;font-size:12.5px}.mp-card ul{margin:6px 0 8px;padding-left:22px}
.mp-card-head{display:flex;align-items:center;justify-content:center;gap:8px;min-height:30px;background:#f4a582;color:#7a2a12;font-weight:700;padding:3px 52px;position:relative}
.mp-card-head img{position:absolute;right:4px;top:3px;height:38px;border:1px solid #fff;background:#fff}
.mp-boxes{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px;background:#dfeaf7;border:1px solid #a7c1dd;padding:10px}
.mp-box{background:#fff;border:1px solid #c8ccd1;font-size:12.5px;padding:0 0 6px}.mp-box h4{margin:8px 12px 2px;font-size:13px;color:#1d4e6f}.mp-box p{margin:0 12px}
.mp-box-head{display:flex;align-items:center;justify-content:center;min-height:42px;background:#eee8aa;position:relative;padding:4px 56px}
.mp-box-head img{position:absolute;right:4px;top:3px;height:36px;max-width:64px;object-fit:contain}.mp-ico{position:absolute;right:6px;top:3px;width:36px;height:36px}.mp-ico svg{width:36px;height:36px}
@media(max-width:820px){.mp-welcome{grid-template-columns:1fr}.mp-hero b{font-size:26px}.mp-hero-ship{height:110px;opacity:.5}.mp-card{flex-basis:85%}.mp-quick{font-size:13px}.mp-quick p{padding:6px 8px;line-height:1.9}}#logo img{display:block;margin:0 auto 6px}

.wm-bar{display:flex;flex-wrap:wrap;gap:6px 14px;align-items:center;margin:6px 0;font-size:13px}.wm-bar input[type=search]{padding:4px 8px;min-width:200px}
.wm-view{position:relative;overflow:hidden;background:#6f6a5b;border-radius:8px;touch-action:none;cursor:grab;user-select:none}.wm-view:active{cursor:grabbing}
.wm-world{position:absolute;left:0;top:0;transform-origin:0 0}.wm-img{width:100%;height:100%;display:block}
.wm-routes{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}.wm-shallow{position:absolute;inset:0;width:100%;height:100%;pointer-events:none;image-rendering:pixelated}.wm-routes polyline{fill:none;vector-effect:non-scaling-stroke}.wm-rline{stroke-width:var(--sw,2.4px);stroke-opacity:.85;stroke-dasharray:6 4;pointer-events:none}.wm-rhit{stroke:transparent;stroke-width:var(--hw,14px);pointer-events:stroke;cursor:pointer}.wm-routes g:hover .wm-rline{stroke-opacity:1}.wm-routes g.sel .wm-rline{stroke-width:var(--sws,4.5px);stroke-opacity:1;stroke-dasharray:none}.wm-layers{position:relative}.wm-layers summary{cursor:pointer;border:1px solid var(--border);border-radius:6px;padding:4px 10px;background:#fff;list-style:none}.wm-layers[open]>label{display:block}.wm-layers>label{display:none;white-space:nowrap}.wm-layers[open]{z-index:6}.wm-layers[open]::after{content:none}.wm-layers[open]{background:#fff;border:1px solid var(--border);border-radius:6px;padding:0 10px 6px}.wm-rtypes{display:flex;flex-wrap:wrap;gap:4px 10px}.wm-rt i,.wm-dot{display:inline-block;width:14px;height:4px;border-radius:2px;margin:0 4px 2px;vertical-align:middle}.wm-small{font-size:11px;max-width:260px}.wm-big .wm-pin span{font-size:13px}.wm-legend{font-size:12px;color:var(--muted);margin:6px 0}
.wm-pins{position:absolute;inset:0;pointer-events:none}.wm-pin{position:absolute;transform:translate(-50%,-50%);pointer-events:auto;border:1.5px solid #fff;border-radius:50%;width:11px;height:11px;padding:0;cursor:pointer;box-shadow:0 1px 3px rgba(0,0,0,.5)}
.wm-pin span{display:none;position:absolute;left:12px;top:-4px;white-space:nowrap;font:600 11px system-ui;color:#fff;text-shadow:0 1px 2px #000,0 0 3px #000}
.wm-labels .wm-pin span{display:block}.wm-port{width:13px;height:13px}.wm-pb{background:#e0552b;width:16px;height:16px;border-color:#ffe2a8}
.wm-tower{background:#c0392b;width:7px;height:7px;border-width:1px}.wm-fort{background:#7d3c98;width:14px;height:14px}.wm-village{background:#9b7b4b;width:7px;height:7px;border-width:1px}
.wm-mine{background:#5f6a6a;width:8px;height:8px;border-radius:2px;border-width:1px}.wm-altar{background:#1abc9c;width:9px;height:9px}
.wm-pop{position:absolute;transform:translate(-50%,calc(-100% - 14px));background:#fff;color:#223;border-radius:8px;padding:8px 26px 8px 10px;box-shadow:0 6px 18px rgba(0,0,0,.35);font-size:13px;display:grid;gap:3px;min-width:180px;z-index:3}
.wm-pop span{color:#556}.wm-close{position:absolute;right:4px;top:2px;border:0;background:none;font-size:17px;cursor:pointer}

.sv{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:12px}.sv-stage{position:relative;height:620px;border:1px solid #d5dbe2;border-radius:8px;overflow:hidden}
.sv-gl{width:100%;height:100%;display:block;cursor:crosshair;touch-action:none}.sv-hud{position:absolute;left:10px;top:8px;background:rgba(255,255,255,.85);padding:3px 8px;border-radius:5px;font-size:13px}
.sv-load{position:absolute;inset:0;display:grid;place-items:center;font-size:15px;color:#345;background:rgba(255,255,255,.4)}.sv-load[hidden]{display:none}
.sv-side{display:grid;gap:8px;align-content:start;font-size:13px}.sv-side fieldset{border:1px solid #dde3ea;border-radius:6px;padding:6px 8px;display:grid;gap:5px}.sv-side legend{font-weight:600}
.sv-side select{max-width:100%}.sv-legend{display:flex;gap:6px;align-items:center;font-size:11px;color:#555}.sv-legend i{flex:1;height:8px;background:linear-gradient(90deg,#28325a,#3c6ebe,#5abe78,#f0c83c,#dc3228)}
.sv-sails{max-height:260px;overflow:auto;border:1px solid #dde3ea;border-radius:6px;padding:6px;display:grid;gap:2px}.sv-sails small{color:#889}.sv-sbtn{display:flex;gap:4px;flex-wrap:wrap}.sv-pat{display:flex;gap:6px;align-items:end;flex-wrap:wrap}
.sv-shot{border-top:1px solid #eee;padding:4px 0}.sv-shot small{display:block;color:#667}.sv-fire{padding:5px 8px}
@media(max-width:900px){.sv{grid-template-columns:1fr}.sv-stage{height:440px}}
.ha-controls{display:flex;flex-wrap:wrap;gap:12px 18px;margin:8px 0;align-items:center}.ha-controls select,.ha-controls input{font:inherit;padding:3px 5px}
.ha-grid{display:flex;flex-wrap:wrap;gap:20px;align-items:flex-start}.ha-legend{font-size:12px;color:#555;max-width:600px}.ha-legend i{display:inline-block;width:160px;height:10px;margin:0 6px;vertical-align:middle;background:linear-gradient(90deg,#28325a,#3c6ebe,#5abe78,#f0c83c,#dc3228)}
.ha-side-col{flex:1;min-width:320px}.ha-note{font-size:12px;color:#555}.ha canvas{max-width:100%;height:auto;border:1px solid #e3e6ea;border-radius:4px;background:#fff}
.ha-stats{display:flex;flex-wrap:wrap;gap:8px;margin:6px 0}.ha-stats div{background:#f4f7fa;border:1px solid #dde3ea;border-radius:6px;padding:5px 10px;min-width:92px}.ha-stats span{display:block;font-size:11px;color:#667}.ha-stats b{font-size:15px}
.ha-bar{position:relative;min-width:90px}.ha-bar span{position:absolute;left:0;top:3px;bottom:3px;opacity:.28;border-radius:2px}.ha-bar b{position:relative}
.ha-cur{background:#fff7d6}.ha-more{margin:10px 0;border:1px solid #dde3ea;border-radius:6px;padding:6px 10px}.ha-more summary{cursor:pointer;font-weight:600}
.sw{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px}img.infographic{max-width:100%;border:1px solid #ddd;border-radius:6px;margin:8px 0}

.tfilter{width:320px;max-width:100%;padding:6px 8px;border:1px solid #a2a9b1;border-radius:3px;font:inherit}

.vbar{position:relative;min-width:90px;height:18px;background:#eef2f5;border-radius:3px;overflow:hidden}.vbar i{position:absolute;left:0;top:0;bottom:0;background:linear-gradient(90deg,#9cc3dc,#4f8fb8)}.vbar b{position:relative;padding-left:5px;font-weight:600;font-size:12px;line-height:18px;color:#16324a}
.vbar.warm i{background:linear-gradient(90deg,#f3c58a,#d9782f)}.vbar.green i{background:linear-gradient(90deg,#b7dfa0,#5aa144)}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px;margin:10px 0}.cards a.cardl{display:block;border:1px solid #c9d3dd;border-radius:6px;padding:10px;text-decoration:none;background:#f8fafc}.cards a.cardl b{display:block;color:#20486b}.cards a.cardl span{color:#555;font-size:13px}
.keyfacts{background:#f4f8fb;border-left:4px solid #4f8fb8;padding:8px 12px;margin:8px 0}

:root{--link:#0645ad;--visited:#0b0080;--border:#a2a9b1;--side:#f6f6f6;--head:#eaecf0;--ink:#202122;--muted:#54595d;--accent:#1d4e6f}
*{box-sizing:border-box}html{background:#f6f6f6}body{margin:0;font:14px/1.6 "Segoe UI",system-ui,Arial,sans-serif;color:var(--ink)}
a{color:var(--link);text-decoration:none}a:hover{text-decoration:underline}a.new{color:#ba0000}
#top{display:flex;align-items:center;gap:16px;height:52px;padding:0 18px 0 196px;background:#fff;border-bottom:1px solid var(--border)}
#top .tabs a{display:inline-block;padding:14px 10px 12px;color:var(--muted);border-bottom:3px solid transparent}#top .tabs a.on{color:var(--ink);border-color:var(--accent)}
#search{margin-left:auto;position:relative}#search input{width:320px;padding:6px 10px;border:1px solid var(--border);border-radius:2px;font:inherit}
#results{position:absolute;right:0;top:34px;width:420px;max-height:420px;overflow:auto;background:#fff;border:1px solid var(--border);box-shadow:0 4px 14px rgba(0,0,0,.15);display:none;z-index:9}
#results a{display:block;padding:6px 10px;border-bottom:1px solid #eee}#results small{color:var(--muted);margin-left:6px}
#side{position:absolute;top:0;left:0;width:180px;padding:12px 10px}#logo{display:block;height:120px;margin-bottom:8px;text-align:center;color:var(--accent);font:700 17px/1.2 Georgia,serif}
#logo svg{display:block;margin:6px auto}#side h3{font-size:12px;color:var(--muted);font-weight:600;margin:14px 0 4px;padding-bottom:2px;border-bottom:1px solid #c8ccd1}
#side a{display:block;font-size:13px;padding:2px 0}
#content{margin-left:176px;background:#fff;border:1px solid var(--border);border-right:0;padding:16px 26px 32px;min-height:calc(100vh - 52px)}
h1{font:400 28px/1.3 Georgia,"Linux Libertine",serif;margin:0 0 4px;border-bottom:1px solid var(--border);padding-bottom:4px}
h2{font:400 21px/1.3 Georgia,serif;border-bottom:1px solid var(--border);margin:22px 0 8px}h3{font-size:16px;margin:16px 0 6px}
.crumbs{font-size:12px;color:var(--muted);margin-bottom:10px}
.infobox{float:right;clear:right;width:300px;margin:0 0 14px 18px;border:1px solid var(--border);background:#f8f9fa;font-size:13px;border-collapse:collapse}
.infobox caption{font-weight:700;font-size:15px;padding:6px;background:var(--accent);color:#fff}.infobox td.ibimg{text-align:center;background:#fff;padding:8px}.infobox td.ibimg img{max-width:100%;max-height:220px;object-fit:contain}.entry .infobox td.ibimg img{max-height:72px}img.ticon{width:28px;height:28px;object-fit:contain;vertical-align:middle;margin-right:6px}.rt{display:inline-block;border-radius:999px;padding:0 8px;font-size:12px;font-weight:600;color:#fff}.rt-main{background:#1f5fbf}.rt-supply{background:#2e8b57}.rt-coastal{background:#b8860b}.rt-central{background:#7d3c98}.rt-smuggling{background:#333}
.portmap{margin:8px 0;max-width:560px}.portmap img{width:100%;height:auto;border:1px solid var(--border);border-radius:6px}.portmap figcaption{font-size:12px;color:var(--muted)}
.lg{display:inline-block;width:11px;height:11px;margin:0 3px 0 8px;vertical-align:-1px;border-radius:2px}.lg-port{background:#e8c05a;border-radius:50%}.lg-tower{background:#c0392b}.lg-fort{background:#7d3c98}
.lg-node{background:#5f6a6a}.lg-route{background:#1f5fbf;height:3px;vertical-align:3px}.lg-s2{background:#dc2828}.lg-s3{background:#f08c1e}.lg-s4{background:#ebd228}.lg-s5{background:#5ac85a}.lg-s6{background:#3c6ee6}
.iv{border:1px solid var(--border);border-radius:6px;background:#eef2f6;padding:10px;max-width:640px}.iv-gl{display:block;width:100%;height:340px;border:0;background:#eef2f6;touch-action:none;cursor:grab}.iv-go{background:var(--accent);color:#fff;border:0;border-radius:4px;padding:8px 14px;font:inherit;cursor:pointer}.iv-msg{display:block;color:var(--muted);margin-top:4px}
.infobox th{text-align:left;padding:4px 8px;vertical-align:top;width:45%;background:var(--head)}.infobox td{padding:4px 8px}
table.wikitable{border-collapse:collapse;background:#f8f9fa;margin:10px 0;font-size:13px}
.wikitable th,.wikitable td{border:1px solid var(--border);padding:4px 8px}.wikitable th{background:var(--head);cursor:pointer;white-space:nowrap}
.wikitable th.sorted-asc:after{content:" ▲"}.wikitable th.sorted-desc:after{content:" ▼"}
.portal{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:12px;margin:12px 0}
.portal div{border:1px solid var(--border);background:#f8f9fa;padding:10px 12px}.portal h3{margin:0 0 4px;color:var(--accent)}
.welcome{border:1px solid #a3bfb1;background:#f5fffa;padding:12px 16px;margin-bottom:14px}
.note{border-left:4px solid #fc3;background:#fef6e7;padding:8px 12px;margin:10px 0}.toc{display:inline-block;border:1px solid var(--border);background:#f8f9fa;padding:8px 16px;margin:6px 0 10px;font-size:13px}
.toc b{display:block;text-align:center}.toc ul{margin:4px 0;padding-left:18px}.toc li.l1{margin-left:14px;font-size:12px}
.tool{border:1px solid var(--border);background:#f8f9fa;padding:12px 14px;margin:10px 0}
.tool label{display:inline-block;margin:4px 12px 4px 0}.tool input,.tool select,.tool textarea{font:inherit;padding:4px 6px;border:1px solid var(--border)}
.tool button{background:var(--accent);color:#fff;border:0;padding:6px 14px;cursor:pointer;font:inherit}.tool textarea{width:100%;font-family:Consolas,monospace}
canvas{background:#fff;border:1px solid var(--border);max-width:100%}
.bar{height:10px;background:#d33;display:inline-block;vertical-align:middle}.barwrap{display:inline-block;width:160px;background:#eee;margin-right:8px}
code{background:#f8f9fa;border:1px solid #eaecf0;padding:1px 4px}
footer{margin:0 0 0 176px;padding:16px 26px 28px;font-size:12px;color:var(--muted);border-top:1px solid var(--border);background:#f6f6f6}footer p{margin:6px 0;max-width:980px}
footer .legal a{margin-right:14px}.donate{display:flex;flex-wrap:wrap;gap:6px 12px;align-items:center;background:#fff8e6;border:1px solid #ecd9a8;border-radius:8px;padding:10px 14px;margin-bottom:10px;font-size:13px;color:#4a3d1c}
.donatebtn{background:#f2c14e;color:#1b1b1b!important;border-radius:999px;padding:6px 16px;font-weight:700;text-decoration:none!important;margin-left:auto}
.skip{position:absolute;left:-999px;top:0;background:#fff;padding:6px 10px;z-index:99}.skip:focus{left:8px}
#acct{position:relative;margin-left:10px}#acct[hidden]{display:none}.acct-login{display:inline-flex;align-items:center;gap:6px;background:#5865f2;color:#fff!important;border-radius:6px;padding:6px 12px;font-weight:600;white-space:nowrap}
.acct-login:hover{text-decoration:none;filter:brightness(1.08)}.acct-login.big{padding:10px 18px;font-size:15px}.acct-btn{display:flex;align-items:center;gap:6px;border:1px solid var(--border);background:#fff;border-radius:999px;padding:2px 10px 2px 2px;cursor:pointer;font:inherit}
.acct-btn img{border-radius:50%}.acct-init{display:inline-grid;place-items:center;width:26px;height:26px;border-radius:50%;background:#5865f2;color:#fff;font-style:normal;font-weight:700}.acct-menu{position:absolute;right:0;top:40px;background:#fff;border:1px solid var(--border);border-radius:8px;box-shadow:0 6px 18px rgba(0,0,0,.15);min-width:180px;z-index:30;display:grid}
.acct-menu[hidden]{display:none}#langs{position:relative;margin-left:10px}#langs[hidden]{display:none}.lang-btn{display:flex;align-items:center;gap:4px;border:1px solid var(--border);background:#fff;border-radius:6px;padding:5px 8px;cursor:pointer;font:inherit;font-size:12px;font-weight:600}.lang-menu{position:absolute;right:0;top:38px;background:#fff;border:1px solid var(--border);border-radius:8px;box-shadow:0 6px 18px rgba(0,0,0,.15);display:grid;grid-template-columns:1fr 1fr;min-width:330px;z-index:31;padding:4px}.lang-menu[hidden]{display:none}.lang-menu a{padding:7px 10px;border-radius:5px;display:flex;align-items:center;gap:8px;white-space:nowrap}img.flag{width:21px;height:14px;border-radius:2px;box-shadow:0 0 0 1px rgba(0,0,0,.15);flex:none}.lang-menu a:hover{background:#f3f6fa;text-decoration:none}.lang-menu a[aria-current]{font-weight:700;background:#eef4fb}.tr-wait{background:#fff8e6;border:1px solid #ecd9a8;border-radius:6px;padding:6px 10px;font-size:13px}[dir=rtl] .infobox{float:left;margin:0 18px 12px 0}[dir=rtl] ul,[dir=rtl] ol{padding-right:22px;padding-left:0}.acct-menu a,.acct-menu button{padding:10px 14px;text-align:left;border:0;background:none;font:inherit;color:var(--link);cursor:pointer}.acct-menu a:hover,.acct-menu button:hover{background:#f3f6fa;text-decoration:none}
.report-bar{clear:both;display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center;margin:28px 0 0;padding:10px 14px;border:1px dashed #a7c1dd;border-radius:8px;background:#f5f9fd;font-size:13px;color:var(--muted)}
.report-bar[hidden]{display:none}.report-bar button{background:#fff;border:1px solid var(--accent);color:var(--accent);border-radius:6px;padding:6px 12px;font:inherit;font-weight:600;cursor:pointer}.report-bar button:hover{background:var(--accent);color:#fff}
.rp-wrap{position:fixed;inset:0;background:rgba(10,20,30,.55);z-index:60;display:grid;place-items:center;padding:12px}body.rp-open{overflow:hidden}
.rp{position:relative;background:#fff;border-radius:10px;padding:18px 20px;width:min(520px,100%);max-height:92vh;overflow:auto;display:grid;gap:10px;box-shadow:0 18px 60px rgba(0,0,0,.35)}
.rp h2{margin:0;border:0;font-size:20px}.rp label{display:grid;gap:4px;font-weight:600;font-size:13px}.rp label small{font-weight:400;color:var(--muted)}
.rp select,.rp textarea,.rp input{font:inherit;font-weight:400;padding:8px 10px;border:1px solid var(--border);border-radius:6px;width:100%}.rp-page,.rp-who{margin:0;font-size:13px;color:var(--muted)}
.rp-x{position:absolute;right:8px;top:6px;border:0;background:none;font-size:24px;cursor:pointer;color:var(--muted)}.rp-msg{margin:0;min-height:1em;color:#b03a2e;font-size:13px}
.rp-actions{display:flex;gap:8px}.rp-send{background:var(--accent);color:#fff;border:0;border-radius:6px;padding:9px 18px;font:inherit;font-weight:600;cursor:pointer}.rp-send:disabled{opacity:.6}
.rp-cancel{background:#fff;border:1px solid var(--border);border-radius:6px;padding:9px 14px;font:inherit;cursor:pointer}
.ad-bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:8px 0 12px}.ad-tabs{display:flex;gap:4px;flex-wrap:wrap}.ad-tabs button{border:1px solid var(--border);background:#f8f9fa;border-radius:6px;padding:6px 12px;font:inherit;cursor:pointer}
.ad-tabs button.on{background:var(--accent);color:#fff;border-color:var(--accent)}.ad-q{flex:1;min-width:180px;padding:7px 10px;border:1px solid var(--border);border-radius:6px;font:inherit}
.ad-reload{border:1px solid var(--border);background:#fff;border-radius:6px;padding:6px 12px;font:inherit;cursor:pointer}
.ad-item{border:1px solid var(--border);border-left:5px solid #e0a030;border-radius:6px;padding:10px 14px;margin:0 0 10px;background:#fff}.ad-item.ad-resolved{border-left-color:#4caf50}.ad-item.ad-wontfix{border-left-color:#9e9e9e}
.ad-item header{display:flex;flex-wrap:wrap;gap:6px 12px;align-items:center;font-size:13px}.ad-item time{margin-left:auto;color:var(--muted)}.ad-kind{border-radius:999px;padding:1px 10px;font-size:12px;font-weight:600;background:#eef2f6}
.ad-k-wrong{background:#fde2dc;color:#8a2a12}.ad-k-missing{background:#e3eefb;color:#1d4e6f}.ad-k-suggestion{background:#e6f5e6;color:#2e6b2e}.ad-msg{white-space:pre-wrap;margin:8px 0}.ad-from{margin:2px 0;font-size:12px;color:var(--muted)}
.ad-act{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}.ad-act select,.ad-act input{font:inherit;padding:5px 8px;border:1px solid var(--border);border-radius:5px}.ad-note{flex:1;min-width:160px}
.ad-act button{border:1px solid var(--border);background:#fff;border-radius:5px;padding:5px 12px;font:inherit;cursor:pointer}.ad-save{background:var(--accent)!important;color:#fff;border-color:var(--accent)!important}.ad-err{color:#b03a2e;font-size:12px}.ad-empty{color:var(--muted)}
#menu,#toplogo{display:none}#scrim{display:none}.tw{max-width:100%;overflow-x:auto;-webkit-overflow-scrolling:touch}.tw>table.wikitable{margin:0}.tw{margin:10px 0}
.entries{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px;margin:10px 0}.entry{border:1px solid var(--border);background:#fbfcfd;border-radius:6px;padding:8px 12px;scroll-margin-top:70px}
.entry:target{outline:3px solid #f2c14e;background:#fffbea}.entry h3{margin:2px 0 6px;font:600 16px/1.3 Georgia,serif}.entry .infobox{float:none;width:100%;margin:0 0 8px}.entry .infobox caption{display:none}
.entry h4{margin:8px 0 2px;font-size:13px}.entry p,.entry ul{margin:4px 0;font-size:13px}.entry img{max-width:100%;height:auto}
.tag{display:inline-block;background:#eaf3ff;border:1px solid #c5d9f1;border-radius:2px;padding:0 6px;margin:2px;font-size:12px}
@media(max-width:1100px){#search input{width:240px}#results{width:360px}}
@media(max-width:820px){
#top{position:sticky;top:0;z-index:20;height:56px;padding:0 10px;gap:8px}#top .tabs{display:none}
#menu{display:inline-grid;gap:4px;align-content:center;justify-items:center;width:44px;height:44px;border:1px solid var(--border);border-radius:8px;background:#fff;cursor:pointer;padding:0}
#menu span{display:block;width:20px;height:2px;background:var(--ink);border-radius:2px}
#toplogo{display:flex;align-items:center;gap:6px;color:var(--accent);font:700 16px Georgia,serif;white-space:nowrap}#toplogo:hover{text-decoration:none}
#search{flex:1;min-width:0}#search input{width:100%;font-size:16px;padding:9px 10px;border-radius:6px}.acct-login span,.acct-btn span{display:none}.acct-btn{padding:2px}#acct{margin-left:0}
#results{position:fixed;left:8px;right:8px;top:58px;width:auto;max-height:70vh}#results a{padding:10px 12px;font-size:15px}
#side{position:fixed;top:0;bottom:0;left:0;width:280px;max-width:85vw;transform:translateX(-105%);transition:transform .2s ease;background:#f6f6f6;z-index:40;overflow-y:auto;
 padding:10px 14px 40px;box-shadow:4px 0 18px rgba(0,0,0,.25)}
body.menu-open #side{transform:none}body.menu-open #scrim{display:block;position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:30}body.menu-open{overflow:hidden}
#side a{padding:8px 4px;font-size:15px;border-bottom:1px solid #ebedef}#logo{height:auto}
#content{margin:0;border:0;padding:12px 14px 24px;min-height:0}footer{margin:0;padding:16px 14px 28px}
h1{font-size:24px}h2{font-size:19px}.infobox{float:none;width:100%;margin:0 0 12px}
.tool label{display:block;margin:6px 0}.tool input,.tool select{max-width:100%;font-size:16px}
ul.cols{columns:2 150px}.toc{display:block}.donatebtn{margin-left:0}.tfilter{width:100%;font-size:16px}
.sv-stage{height:380px}.ha-side-col{min-width:0}.portal,.feature{grid-template-columns:1fr}
}
@media(max-width:480px){ul.cols{columns:1}#toplogo b{display:none}.entries{grid-template-columns:1fr}.wikitable{font-size:12px}}
'''

SITE_JS = r'''
function wikiFilter(inp){const q=inp.value.toLowerCase();document.querySelectorAll('main table.wikitable tbody tr').forEach(tr=>{tr.style.display=tr.innerText.toLowerCase().includes(q)?'':'none'})}

if(window.top!==window.self){try{window.top.location.replace(window.self.location.href)}catch(e){document.documentElement.style.display='none'}}
(function(){
const base=document.body.dataset.base||'';
const FLAG=c=>`<img class="flag" src="/assets/flags/${c}.svg" alt="" width="21" height="14">`;
const LANGS=[['en','English'],['zh','中文'],['hi','हिन्दी'],['es','Español'],['ar','العربية'],['fr','Français'],['bn','বাংলা'],['pt','Português'],['ru','Русский'],
 ['id','Bahasa Indonesia'],['ur','اردو'],['de','Deutsch'],['ja','日本語'],['tr','Türkçe'],['ko','한국어']];
const lb=document.getElementById('langs');
if(lb&&/^https?:$/.test(location.protocol)){const cur=document.body.dataset.lang||'en';const codes=LANGS.map(l=>l[0]).filter(c=>c!=='en');
 const parts=location.pathname.split('/');const rest=codes.includes(parts[1])?'/'+parts.slice(2).join('/'):location.pathname;
 lb.innerHTML=`<button type="button" class="lang-btn" aria-haspopup="true" aria-expanded="false" aria-label="Language">${FLAG(cur)}<span>${cur.toUpperCase()}</span></button>
  <div class="lang-menu" hidden>${LANGS.map(([c,n])=>`<a href="${c==='en'?rest:'/'+c+rest}${location.search}" lang="${c}"${c===cur?' aria-current="true"':''}>${FLAG(c)}${n}</a>`).join('')}</div>`;
 const b=lb.querySelector('.lang-btn'),mm=lb.querySelector('.lang-menu');b.onclick=()=>{mm.hidden=!mm.hidden;b.setAttribute('aria-expanded',String(!mm.hidden))};
 document.addEventListener('click',e=>{if(!lb.contains(e.target))mm.hidden=true});lb.hidden=false}
const menu=document.getElementById('menu'),scrim=document.getElementById('scrim');
function setMenu(open){document.body.classList.toggle('menu-open',open);if(menu)menu.setAttribute('aria-expanded',open?'true':'false')}
if(menu){menu.addEventListener('click',()=>setMenu(!document.body.classList.contains('menu-open')));scrim.addEventListener('click',()=>setMenu(false));
 document.addEventListener('keydown',e=>{if(e.key==='Escape')setMenu(false)})}
document.querySelectorAll('main table.wikitable').forEach(t=>{if(t.parentElement.classList.contains('tw'))return;const w=document.createElement('div');w.className='tw';t.parentNode.insertBefore(w,t);w.appendChild(t)});
const box=document.querySelector('#search input'),res=document.getElementById('results');let idx=null;
async function load(){if(idx)return idx;try{idx=await (await fetch(base+'search.json')).json()}catch(e){idx=window.SEARCH_INDEX||[]}return idx}
if(box){box.addEventListener('input',async()=>{const q=box.value.trim().toLowerCase();if(!q){res.style.display='none';return}
 const items=(await load()).filter(x=>x.t.toLowerCase().includes(q)||x.k.toLowerCase().includes(q)).slice(0,40);
 res.innerHTML=items.map(x=>'<a href="'+base+x.u+'">'+x.t.replace(/</g,'&lt;')+'<small>'+x.c+'</small></a>').join('')||'<a>No matches</a>';res.style.display='block'});
 box.addEventListener('keydown',e=>{if(e.key==='Enter'){const a=res.querySelector('a[href]');if(a)location=a.href}});
 document.addEventListener('click',e=>{if(!e.target.closest('#search'))res.style.display='none'})}
document.querySelectorAll('table.sortable').forEach(t=>{t.querySelectorAll('th').forEach((th,i)=>th.addEventListener('click',()=>{
 const asc=!th.classList.contains('sorted-asc');t.querySelectorAll('th').forEach(h=>h.classList.remove('sorted-asc','sorted-desc'));th.classList.add(asc?'sorted-asc':'sorted-desc');
 const rows=[...t.tBodies[0].rows];const num=v=>{const n=parseFloat(String(v).replace(/[,%]/g,''));return isNaN(n)?null:n};
 rows.sort((a,b)=>{const x=a.cells[i].innerText,y=b.cells[i].innerText,nx=num(x),ny=num(y);const r=(nx!==null&&ny!==null)?nx-ny:x.localeCompare(y);return asc?r:-r});
 rows.forEach(r=>t.tBodies[0].appendChild(r))}))});
})();
'''

LOGO = '<img src="{base}assets/brand/emblem.png" alt="" width="80" height="80">'


def _page(title, body, *, depth=0, crumbs=None, tab='Page', report=True):
    base = '../' * depth
    h = HOSTING
    side = [f'<a id="logo" href="{base}index.html">{LOGO.format(base=base)}{_e(SITE_NAME)}</a>', '<h3>Navigation</h3>']
    side += [f'<a href="{base}{u}">{_e(t)}</a>' for t, u in NAV]
    side += ['<h3>Tools</h3>'] + [f'<a href="{base}{u}">{_e(t)}</a>' for t, u in TOOLS]
    side += ['<h3>Wiki</h3>', f'<a href="{base}about.html">About</a>', f'<a href="{base}sitemap.html">All pages</a>', f'<a href="{base}recent.html">Recent changes</a>',
             f'<a href="{base}privacy.html">Privacy policy</a>', f'<a href="{base}terms.html">Terms of use</a>', f'<a href="{base}disclaimer.html">Copyright disclaimer</a>']
    community = ([f'<a href="{_e(h["discord_url"])}" rel="noopener" target="_blank">Join our Discord</a>'] if h.get('discord_url') else []) + \
                ([f'<a href="{_e(h["donate_url"])}" rel="noopener" target="_blank">Donate</a>'] if h.get('donate_url') else [])
    if community:
        side += ['<h3>Community</h3>'] + community
    crumb = ''
    if crumbs:
        crumb = '<div class="crumbs">' + ' › '.join(f'<a href="{base}{u}">{_e(t)}</a>' if u else _e(t) for t, u in crumbs) + '</div>'
    donate = (f'<div class="donate"><b>Enjoying the wiki?</b> <span>It\'s free, ad-supported and run by volunteers. Donations keep it online and up to date.</span>'
              f'<a class="donatebtn" href="{_e(h["donate_url"])}" target="_blank" rel="noopener">♥ Donate</a></div>') if h.get('donate_url') else ''
    year = datetime.now(timezone.utc).year
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{_e(SITE_NAME + " · World of Sea Battle wiki: ships, guns, maps and battle tools" if title == "Main page" else title + " · " + SITE_NAME)}</title><link rel="stylesheet" href="{base}assets/site.css"></head>'
            f'<body data-base="{base}"{' data-host="standalone"' if h.get('standalone') else ''}><a class="skip" href="#content">Skip to content</a><nav id="side" aria-label="Site">{"".join(side)}</nav><div id="scrim"></div>'
            f'<header id="top"><button id="menu" type="button" aria-label="Open menu" aria-controls="side" aria-expanded="false"><span></span><span></span><span></span></button>'
            f'<a id="toplogo" href="{base}index.html"><img src="{base}assets/brand/emblem.png" alt="" width="34" height="34"><b>{_e(SITE_NAME)}</b></a>'
            f'<span class="tabs"><a class="on">{_e(tab)}</a></span>'
            '<div id="search" role="search"><input type="search" placeholder="Search the WoSB Wiki" aria-label="Search the wiki" autocomplete="off"><div id="results"></div></div>'
            + ('<div id="langs" translate="no" hidden></div><div id="acct" hidden></div>' if h.get('standalone') else '') + '</header>'
            f'<main id="content">{crumb}<h1>{_e(SITE_NAME if title == "Main page" else title)}</h1>{body}'
            + ('<div class="report-bar" hidden><button type="button" data-report>Report a problem with this page</button>'
               '<span>Spotted something wrong or missing? Let us know.</span></div>' if h.get('standalone') and report else '') + '</main>'
            f'<footer id="foot">{donate}<p>© {year} {_e(SITE_NAME)} · Band of Misfits. Our guides, tools and logo are our own work. <b>World of Sea Battle</b> and all of its imagery, '
            '3D models, textures, designs, names and game data are the property of Thera Interactive. This is an unofficial fan site and is not affiliated with or endorsed by Thera Interactive.</p>'
            f'<p class="legal"><a href="{base}about.html">About</a><a href="{base}privacy.html">Privacy policy</a><a href="{base}terms.html">Terms of use</a>'
            f'<a href="{base}disclaimer.html">Copyright disclaimer</a><a href="{base}sitemap.html">All pages</a>'
            + (f'<a href="{base}about.html#contact" data-report="general">Tell us</a>' if h.get('standalone') else '') + '</p></footer>'
            f'<script src="{base}assets/site.js"></script>' + (f'<script src="{base}assets/community.js" defer></script>' if h.get('standalone') else '') + '</body></html>')


def _infobox(title, rows, image=None):
    cells = ''.join(f'<tr><th>{_e(k)}</th><td>{_e(v)}</td></tr>' for k, v in rows if v not in (None, ''))
    pic = (f'<tr><td colspan="2" class="ibimg"><img src="{_e(image)}" alt="{_e(title)}" loading="lazy"></td></tr>') if image else ''
    return f'<table class="infobox"><caption>{_e(title)}</caption>{pic}{cells}</table>'


def _table(headers, rows, *, cls='wikitable sortable'):
    head = ''.join(f'<th>{_e(h)}</th>' for h in headers)
    body = ''.join('<tr>' + ''.join(f'<td>{c}</td>' for c in r) + '</tr>' for r in rows)
    return f'<table class="{cls}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


# --------------------------------------------------------------- builder

class SiteBuilder:
    def __init__(self, db, out, *, hitboxes_dir=None, build='Steam', include_models=False, recovery_dir=None, game_roots=(), progress=None, model_pack=True, damage_calibration=None, site_url=None, hosting=None):
        self.db = db; self.out = Path(out); self.hitboxes_dir = Path(hitboxes_dir) if hitboxes_dir else None
        self.build = build; self.include_models = include_models
        self.recovery_dir = Path(recovery_dir) if recovery_dir else None
        self.game_roots = list(game_roots or ()); self.progress = progress; self.model_pack = model_pack
        self.damage_calibration = damage_calibration
        self.site_url = site_url or (hosting or {}).get('site_url') or SITE_URL
        HOSTING.clear(); HOSTING.update(HOSTING_DEFAULTS); HOSTING.update({k: v for k, v in (hosting or {}).items() if v is not None})
        HOSTING['site_url'] = self.site_url
        self.article_alias = {}; self.redirects = []
        self.search = []; self.pages = 0
        self.entities = load_entities(db, build=build)
        self.urls = {}
        for kind, recs in self.entities.items():
            for r in recs:
                self.urls[(kind, r['_title'].casefold())] = f'{kind}/{_slug(r["_title"])}.html'
        self.articles = self._articles()
        self.icons = {}           # (kind, title casefold) -> 'assets/icons/<kind>/<slug>.webp' (filled by _copy_icons)
        self.article_urls = {a['slug']: f'wiki/{_slug(a["slug"])}.html' for a in self.articles}

    def _articles(self):
        rows = self.db.conn.execute('SELECT slug,title,section,body,source_kind,updated_utc FROM articles ORDER BY section,title').fetchall()
        out = []
        for r in rows:
            a = dict(zip(('slug', 'title', 'section', 'body', 'source_kind', 'updated'), r))
            if (a['section'] in PRIVATE_SECTIONS or a['source_kind'] in PRIVATE_SOURCE_KINDS or a['source_kind'] in STUB_SOURCE_KINDS
                    or str(a['slug']).startswith('research-') or 'research' in str(a['section']).casefold()):
                continue
            if a['source_kind'] == 'client-gamepedia':
                body = self._gamepedia_body(a['slug'], a['title'])
                if not body:
                    continue
                a['body'] = body; a['section'] = 'Game guide'
            elif any(marker in (a['body'] or '') for marker in STUB_MARKERS):
                continue            # empty research outlines: nothing a reader can use
            out.append(a)
        return self._merge_guides(out)

    @staticmethod
    def _split_help(body):
        """(text, see-also links) of one help page body, without its title and source line."""
        body = re.sub(r'^#\s+.*\n+', '', body or '', count=1)
        see = []
        def grab(m):
            see.extend(re.findall(r'\[([^\]]+)\]\(([^)]+)\)', m.group(0))); return ''
        body = re.sub(r'(?m)^\*\*See also:\*\*.*$', grab, body)
        body = re.sub(r'(?m)^\*From the in-game Gamepedia\.\*\s*$', '', body)
        return body.strip(), see

    def _merge_guides(self, arts):
        """Fold short help pages into one topic page each (GUIDE_MERGE, MECHANICS_MERGE)."""
        by_slug = {a['slug']: a for a in arts}
        by_key = {a['slug'].split('gamewiki-', 1)[-1]: a for a in arts if a['source_kind'] == 'client-gamepedia'}
        drop, new = set(), []
        def absorb(target, title, intro, sources, section):
            srcs = [a for a in sources if a and a['slug'] not in drop and a['slug'] != target]
            if not srcs:
                return
            base = by_slug.get(target)
            parts, see = [], []
            for a in srcs:
                text, links = self._split_help(a['body']) if a['source_kind'] == 'client-gamepedia' else (re.sub(r'^#\s+.*\n+', '', a['body'] or '', count=1).strip(), [])
                text = re.sub(r'(?m)^(#{2,5})\s', lambda m: '#' + m.group(1) + ' ', text)        # nest its own headings one level down
                parts.append(f'## {a["title"]}\n\n{text}'); see += links
                drop.add(a['slug']); self.article_alias[a['slug']] = (a['title'], target)
            urls = {f'../wiki/{_slug(target)}.html'} | {f'../wiki/{_slug(a["slug"])}.html' for a in srcs}
            uniq = []
            for t, u in see:
                if u not in urls and (t, u) not in uniq:
                    uniq.append((t, u))
            tail = ('\n\n**See also:** ' + ' · '.join(f'[{t}]({u})' for t, u in uniq)) if uniq else ''
            src_note = '\n\n*Text from the game\'s in-game help (Gamepedia).*' if any(a['source_kind'] == 'client-gamepedia' for a in srcs) else ''
            if base:
                lead = '\n\n## In the game\'s own words\n\nThe game\'s help pages on this topic, in full.\n\n' if any(a['source_kind'] == 'client-gamepedia' for a in srcs) else '\n\n'
                demote = (lambda t: re.sub(r'(?m)^(#{2,5})\s', lambda m: '#' + m.group(1) + ' ', t)) if lead.strip() else (lambda t: t)
                base['body'] = (base['body'] or '').rstrip() + lead + '\n\n'.join(demote(p) for p in parts) + tail
                base['updated'] = max(filter(None, [base.get('updated')] + [a.get('updated') for a in srcs]), default=base.get('updated'))
            else:
                title = title or srcs[0]['title']
                new.append({'slug': target, 'title': title, 'section': section, 'source_kind': 'merged',
                            'body': f'# {title}\n\n{intro}\n\n' + '\n\n'.join(parts) + tail + src_note,
                            'updated': max(filter(None, [a.get('updated') for a in srcs]), default=None)})
        for target, (title, intro, keys) in GUIDE_MERGE.items():
            absorb(target, title, intro, [by_key.get(k) for k in keys], 'Game guide')
        for target, slugs in MECHANICS_MERGE.items():
            if target in by_slug:
                absorb(target, None, '', [by_slug.get(x) for x in slugs], by_slug[target]['section'])
        out = [a for a in arts if a['slug'] not in drop] + new
        for old, (_t, target) in self.article_alias.items():
            self.redirects.append((f'/wiki/{_slug(old)}.html', f'/wiki/{_slug(target)}.html'))
        return sorted(out, key=lambda a: (a['section'], a['title'].casefold()))

    def _gamepedia_body(self, slug, title):
        """The game's own help text for a Gamepedia entry (English_Text keys <id>_text1, _text2, …)."""
        if not hasattr(self, '_gp_text'):
            self._gp_text = {}
            for raw, in self.db.conn.execute("SELECT raw_json FROM records WHERE dataset='English_Text'"):
                r = json.loads(raw); k = str(r.get('Key', ''))
                if k.startswith('gamewiki_'):
                    self._gp_text[k] = r.get('English') or ''          # later rows (newer client) win
        base = 'gamewiki_' + str(slug).split('gamewiki-', 1)[-1].replace('-', '_')
        parts = sorted(((int(m.group(1)), v) for k, v in self._gp_text.items()
                        for m in [re.fullmatch(re.escape(base) + r'_text(\d+)', k)] if m and v.strip()), key=lambda kv: kv[0])
        if not parts:
            return ''
        paras = []
        for _, v in parts:
            v = re.sub(r'\{\d+\}', '…', v).replace('$$', '\n\n').replace('$', '\n')
            # in-game highlight markup: #word #word → **word word**
            v = re.sub(r'#([\w’\'-]+(?:[\s–-]+#[\w’\'-]+)*)', lambda m: '**' + m.group(1).replace('#', '') + '**', v)
            paras.append(v.strip())
        key = base.replace('gamewiki_', '')
        see = GAMEPEDIA_SEE_ALSO.get(key, [])
        tail = ('\n\n**See also:** ' + ' · '.join(f'[{t}]({u})' for t, u in see)) if see else ''
        return f'# {title}\n\n' + '\n\n'.join(paras) + tail + '\n\n*From the in-game Gamepedia.*'

    def _catalog_dirs(self):
        """Catalog export folders (they hold Images/ next to AI-Data/), newest first."""
        dirs = []
        for sf, in self.db.conn.execute("SELECT DISTINCT source_file FROM records WHERE dataset='Entity_Images'"):
            p = Path(str(sf).replace('\\', '/')) if sf else None
            if p and p.parent.name == 'AI-Data':
                dirs.append(p.parent.parent)
            elif sf:   # a Windows path read on another OS, or a moved folder
                dirs.append(Path(str(sf)).parent.parent)
        try:
            from workbench_db import home
            dirs += sorted(home().glob('Reports/*/Catalog-*'), key=lambda d: d.stat().st_mtime, reverse=True)
        except Exception:
            pass
        seen, out = set(), []
        for d in dirs:
            if str(d) not in seen and (d / 'Images').is_dir():
                seen.add(str(d)); out.append(d)
        return out

    def _copy_icons(self, *, size=128):
        """The game's own icon for each item (Entity_Images links from the catalog export), as small WebP files."""
        from PIL import Image
        roots = self._catalog_dirs()
        if not roots:
            return 0
        by_ds = {v[0]: k for k, v in ENTITIES.items()}
        links = defaultdict(list)
        for raw, in self.db.conn.execute("SELECT raw_json FROM records WHERE dataset='Entity_Images'"):
            l = json.loads(raw)
            kind = by_ds.get(l.get('Category'))
            if kind and l.get('PNGPath'):
                exact = 0 if str(l.get('Relationship', '')).startswith(('Exact', 'Client StaticInfoID')) else 1
                links[(kind, str(l.get('EntityID')).casefold())].append((exact, l['PNGPath']))
        n = 0
        for kind, recs in self.entities.items():
            for r in recs:
                keys = [str(r.get(f)).casefold() for f in ('ID', 'Name', 'StaticInfoID', 'IconName') if r.get(f) not in (None, '')]
                cands = sorted({c for k in keys for c in links.get((kind, k), [])})
                src = next((root / c for _, c in cands for root in roots if (root / c).is_file()), None)
                if not src:
                    continue
                rel = f'assets/icons/{kind}/{_slug(r["_title"])}.webp'
                dst = self.out / rel; dst.parent.mkdir(parents=True, exist_ok=True)
                try:
                    im = Image.open(src).convert('RGBA')
                    bbox = im.getchannel('A').getbbox()
                    if bbox:
                        im = im.crop(bbox)
                    im.thumbnail((size, size), Image.LANCZOS)
                    im.save(dst, 'WEBP', quality=88, method=4)
                except OSError:
                    continue
                self.icons[(kind, r['_title'].casefold())] = rel; n += 1
        return n

    def _design_thumbs(self, *, size=128):
        """Cosmetics without an icon: a thumbnail of the design's own texture (flags, sail cloth, patterns)."""
        import battle_sim, model_pack
        roots = battle_sim.texture_roots(self.recovery_dir, self.game_roots)
        if not roots:
            return 0
        idx = model_pack.TextureIndex(roots)
        n = 0
        for r in self.entities.get('cosmetic', []):
            key = ('cosmetic', r['_title'].casefold())
            if key in self.icons or not r.get('Texture'):
                continue
            src = idx.find(str(r['Texture']))
            if not src:
                continue
            try:
                uri, _alpha = model_pack.encode_texture(src, max_size=size)
            except Exception:
                continue
            import base64
            rel = f'assets/icons/cosmetic/{_slug(r["_title"])}.webp'
            dst = self.out / rel; dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(base64.b64decode(uri.split(',', 1)[1]))
            self.icons[key] = rel; n += 1
        return n

    def _write(self, rel, content):
        path = self.out / rel; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8'); self.pages += 1

    def _link(self, target):
        """Wiki-link resolver for article Markdown: articles, then entity pages."""
        import wiki_engine
        key = wiki_engine.slugify(target)
        for old, (title, new) in self.article_alias.items():
            if key in (wiki_engine.slugify(old), wiki_engine.slugify(title)):
                return f'../wiki/{_slug(new)}.html', True
        for a in self.articles:
            if wiki_engine.slugify(a['slug']) == key or wiki_engine.slugify(a['title']) == key:
                return '../' + self.article_urls[a['slug']], True
        for (kind, name), url in self.urls.items():
            if wiki_engine.slugify(name) == key:
                return '../' + url, True
        for t, u in TOOLS:
            if wiki_engine.slugify(t) == key or (key == 'damage-simulator' and 'damage' in u):
                return '../' + u, True
        return '../wiki/' + _slug(target) + '.html', False

    def _scrub(self, body):
        """Drop code-ish lines and internal references from article bodies."""
        body = re.sub(r'```.*?```', '', body, flags=re.S)
        body = re.sub(r'`[^`]*(?:\.dll|\.cs|0x0[0-9a-fA-F]{7}|::)[^`]*`', '', body)
        body = re.sub(r'(?im)^.*(?:Common\.dll|decompiled|IL offset|token 0x|Client record:|File:\s|\.xnb|\.wosb|\.dll|\.jsonl?\b|AI-Data|Source:).*$\n?', '', body)
        body = re.sub(r'`[^`]*(?:\.xnb|\.wosb|_j\b|AI-Data|\.jsonl?)[^`]*`', '', body)
        return body

    # ---- pages
    def build_site(self):
        if self.out.exists():
            for child in ('ship', 'cannon', 'ammo', 'upgrade', 'crew', 'skill', 'resource', 'port', 'achievement', 'cosmetic', 'decoration', 'recipe', 'mission',
                          'category', 'wiki', 'tools', 'assets', 'data', 'guide'):
                shutil.rmtree(self.out / child, ignore_errors=True)
        self.out.mkdir(parents=True, exist_ok=True)
        self._write('assets/site.css', CSS); self._write('assets/site.js', SITE_JS)
        try:
            self._copy_icons()
            self._design_thumbs()
        except Exception as exc:   # pictures are a bonus: never fail the build over them
            self.progress and self.progress(f'Item icons skipped: {exc}')
        flags = Path(__file__).resolve().parent / 'viewer' / 'flags'
        if flags.is_dir():
            for f in flags.glob('*.svg'):
                self._write(f'assets/flags/{f.name}', f.read_text(encoding='utf-8'))
        for name in ('item_viewer.js', 'community.js', 'admin.js'):
            src = Path(__file__).resolve().parent / 'viewer' / name
            if src.is_file():
                self._write(f'assets/{name}', src.read_text(encoding='utf-8'))
        hitboxes = self._hitboxes()
        try:
            self._prepare_world()
        except Exception as exc:   # the map and port pages fall back to plain text
            self.world = None; self.progress and self.progress(f'World data skipped: {exc}')
        try:
            self._hit_data(hitboxes)
        except Exception as exc:  # keep the rest of the wiki building
            self._hd = None; self.progress and self.progress(f'Hit analysis data skipped: {exc}')
        for kind, recs in self.entities.items():
            for r in recs:
                self._entity_page(kind, r, hitboxes)
            self._category_page(kind, recs)
        for a in self.articles:
            self._article_page(a)
        self._articles_category()
        self._tools(hitboxes)
        self._main_page()
        self._recent(); self._about(); self._world_map(); self._missions()
        (self.out / 'search.json').write_text(json.dumps(self.search, separators=(',', ':')), encoding='utf-8')
        # Also inline the index so search works when opened straight from disk (file://).
        js = (self.out / 'assets' / 'site.js').read_text(encoding='utf-8')
        (self.out / 'assets' / 'site.js').write_text('window.SEARCH_INDEX=' + json.dumps(self.search, separators=(',', ':')) + ';\n' + js, encoding='utf-8')
        manifest = {'site': SITE_NAME, 'generated_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                    'pages': self.pages, 'entities': {k: len(v) for k, v in self.entities.items()},
                    'articles': len(self.articles), 'ships_with_hitboxes': len(hitboxes), 'build': self.build, 'models': (getattr(self, 'pack_info', {}) or {}).get('models', 0)}
        # fold thin entity pages into their category, and point merged guides at their new page
        import site_compact, site_host, site_seo
        moved = site_compact.compact(self.out, {**CATEGORY_FILE, 'mission': 'missions'}, keep_kinds=('ship', 'cannon', 'port'), plural={**{k: v[1] for k, v in ENTITIES.items()}, 'mission': 'Missions'})
        amoves = {o.lstrip('/'): n.lstrip('/') for o, n in self.redirects}
        if amoves:
            site_compact._rewrite(self.out, amoves)
        moves = {**{o.lstrip('/'): n.lstrip('/') for o, n in moved['redirects']}, **amoves}
        for it in self.search:
            it['u'] = moves.get(it['u'], it['u'])
        manifest['folded'] = moved['folded']; manifest['merged_guides'] = len(amoves)
        self._sitemap_page()
        import site_titlecase, site_wording
        manifest['reworded'] = site_wording.apply(self.out)
        manifest['titlecased'] = site_titlecase.apply(self.out)
        manifest['seo'] = site_seo.finalize(self.out, site_url=self.site_url, site_name=SITE_NAME, ad_client=HOSTING.get('ad_client') or '',
                                            inject_ads=bool(HOSTING.get('standalone')), gtm_id=HOSTING.get('gtm_id') or '',
                                            langs=__import__('site_host').LANGS if HOSTING.get('standalone') else ())
        if HOSTING.get('standalone'):
            nf = _page('Page not found', '<p>That page isn\'t here. It may have moved when similar pages were combined.</p>'
                       '<p>Try the search box above, browse <a href="sitemap.html">all pages</a>, or go to the <a href="index.html">main page</a>.</p>')
            manifest['host'] = site_host.write(self.out, redirects=self.redirects + moved['redirects'], ad_client=HOSTING.get('ad_client') or '',
                                               not_found_html=site_titlecase.apply_html(nf))
        manifest['pages'] = sum(1 for f in self.out.rglob('*.html') if f.relative_to(self.out).parts[0] != 'pack')
        manifest['asset_version'] = _version_assets(self.out)
        (self.out / 'site.json').write_text(json.dumps(manifest, indent=1), encoding='utf-8')
        return manifest

    def _sitemap_page(self):
        """A readable index of every page, grouped like the navigation."""
        groups = defaultdict(list)
        for it in self.search:
            if '?' not in it['u']:
                groups[it['c']].append(it)
        body = '<p>Every page on the WoSB Wiki, grouped by section. Use the search box for anything specific.</p>' + ''.join(
            f'<h2>{_e(c)}</h2><ul class="cols">' + ''.join(f'<li><a href="{_e(i["u"])}">{_e(i["t"])}</a></li>' for i in sorted(v, key=lambda i: i['t'].casefold())) + '</ul>'
            for c, v in sorted(groups.items()))
        self._write('sitemap.html', _page('All pages', body))

    def _hitboxes(self):
        """{model name: compact zone list} from 'Rebuild ship hitboxes' output."""
        out = {}
        if not self.hitboxes_dir or not self.hitboxes_dir.is_dir():
            return out
        for f in self.hitboxes_dir.glob('*.hitboxes.json'):
            try:
                d = json.loads(f.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                continue
            zones = [{'t': 'hull', 'b': d['corpus']}]
            zones += [{'t': 'sail', 'b': b, 'w': round(s['weight'], 4), 'n': 1 + s['strength_index']}
                      for s in d['sails'] for b in s['levels'] if b]
            zones += [{'t': 'mast', 'b': m['box']} for m in d['masts']]
            for z in zones:
                z['b'] = {'min': [round(v, 3) for v in z['b']['min']], 'max': [round(v, 3) for v in z['b']['max']]}
            out[f.name.replace('.hitboxes.json', '')] = {'zones': zones, 'sails': len(d['sails']), 'masts': len(d['masts']), 'ports': d.get('port_counts'),
                                                          'fig': d.get('figurehead_mount'), 'half': round((d['corpus']['max'][0] - d['corpus']['min'][0]) / 2, 3),
                                                          # model sail mesh -> the client's per-sail index (SailStrengthIndex) used by the pattern slots
                                                          'sailmap': {s['name'].split('_', 1)[-1]: [s['strength_index'], bool(s.get('animated'))] for s in d['sails'] if s.get('name')}}
        return out

    def _model_for(self, ship):
        row = self.db.conn.execute("SELECT raw_json FROM records WHERE dataset='ShipsBasics' AND external_id=? LIMIT 1",
                                   (str(ship.get('StaticInfoID')),)).fetchone()
        if not row:
            for raw, in self.db.conn.execute("SELECT raw_json FROM records WHERE dataset='ShipsBasics'"):
                rec = json.loads(raw)
                if str(rec.get('ID')) == str(ship.get('StaticInfoID')):
                    return rec.get('ModelName')
            return None
        return json.loads(row[0]).get('ModelName')

    def _entity_page(self, kind, rec, hitboxes):
        dataset, plural, fields, _cols = ENTITIES[kind]
        title = rec['_title']
        rows = [(label, _fmt(rec.get(field), fmt)) for field, label, fmt in fields]
        img = self.icons.get((kind, title.casefold()))
        if kind == 'ship':
            try:
                import shipyard
                art = shipyard.art_index().get(shipyard.key(title))
                img = f'assets/shipyard/{art}' if art else img
            except Exception:
                pass
        body = [_infobox(title, rows, image=('../' + img) if img else None)]
        desc = (rec.get('EnglishDescription') or '').replace('#', '')
        if desc:
            body.append(f'<p>{_e(desc)}</p>')
        elif kind != 'port':           # port pages open with their own description
            body.append(f'<p><b>{_e(title)}</b> is {"an" if plural[0] in "AEIOU" else "a"} {_e(plural[:-1].lower() if plural.endswith("s") else plural.lower())} in World of Sea Battle.</p>')
        if kind == 'ship':
            body += self._ship_sections(rec, hitboxes)
        if kind == 'cannon':
            if rec.get('Model') and self.model_pack and self.recovery_dir:
                body.append(f'<h2>3D model</h2><div class="iv" data-model="weapons" data-mesh="{_e(rec["Model"])}" data-pack="../pack/"></div>'
                            '<script src="../assets/item_viewer.js" defer></script>')
            body += self._cannon_vs_ships(rec)
        if kind == 'recipe':
            body += self._recipe_sections(rec)
        if kind == 'cosmetic':
            body += self._cosmetic_sections(rec)
        if kind == 'resource':
            body += self._resource_sections(rec)
        if kind == 'port':
            body += self._port_sections(rec)
        if kind in ('ammo', 'upgrade', 'skill', 'crew') and rec.get('Effects') or rec.get('EffectsBoost') or rec.get('Effect'):
            eff = rec.get('Effects') or rec.get('EffectsBoost') or rec.get('Effect')
            body.append('<h2>Effects</h2><ul>' + ''.join(f'<li>{_e(x.strip())}</li>' for x in humanize_effect(eff).split(';') if x.strip()) + '</ul>')
        cat = CATEGORY_FILE[kind]
        body.append(f'<p style="clear:both"><span class="tag"><a href="../category/{cat}.html">Category: {_e(plural)}</a></span></p>')
        url = self.urls[(kind, title.casefold())]
        self._write(url, _page(title, ''.join(body), depth=1, crumbs=[('Main page', 'index.html'), (plural, f'category/{cat}.html'), (title, None)]))
        self.search.append({'t': title, 'u': url, 'c': plural, 'k': ' '.join(str(v) for _, v in rows if v)})

    COSMETIC_TEXT = {
        'ShipFullDesign': ('Ship design (skin)', 'A full design repaints one particular ship: it swaps the textures of the hull, masts and rigging for a new look. '
                           'It only fits the ship it was made for and sits in the ship\'s design slot.'),
        'SailTexture': ('Sail cloth', 'Sail cloth replaces the cloth of every sail on the ship at once. Each sail shape (main, small, side and triangle sails) uses its own '
                        'version of the design, the same way the game does. Paints and patterns are drawn on top of it.'),
        'Decal1': ('Paint (pattern slot 1)', 'A paint is laid over the sail cloth. In the game\'s design screen you choose, sail by sail, which sails carry it; '
                   'by default it goes on every sail.'),
        'Decal2': ('Sail pattern (pattern slots 2 and 3)', 'A pattern or emblem is laid over the sail cloth and any paint. It can go in the second pattern slot, or in the '
                   'extra pattern slot premium ships get, and each slot is switched on or off sail by sail. By default patterns go on the square sails.'),
        'Flag': ('Flag', 'A flag flown from the ship\'s main flagpole. Ships whose model has two main flags have a second flag slot, so they can fly two different flags.'),
        'BowFigure': ('Figurehead', 'A figurehead is mounted on the bow. The game scales it to the ship\'s length, and ships without a bow mount can\'t carry one.'),
        'Satellite': ('Lantern', 'A lantern hung on the ship. Lanterns are mostly cosmetic but many carry a small bonus.'),
    }

    def _cosmetic_sections(self, rec):
        cat = rec.get('Category') or ''
        name, text = self.COSMETIC_TEXT.get(cat, ('Ship cosmetic', 'A design element for your ship.'))
        out = [f'<h2>{_e(name)}</h2><p>{_e(text)}</p>']
        shop = str(rec.get('InShop') or '')
        m = re.match(r'ByGold\s+(\d+)', shop)
        how = (f'Sold in port for {int(m.group(1)):,} gold.' if m else 'Sold in the premium shop' + (f' (price tier {shop.split()[-1][-1]}).' if 'Tier' in shop else '.')
               if shop.lower().startswith('true') else 'Not sold in the shop: it comes from chests, events, achievements or rewards.')
        out.append(f'<h2>How to get it</h2><p>{_e(how)}</p>')
        if rec.get('BonusEffectType'):
            lab, val = fx_label(f"{rec['BonusEffectType']} {rec.get('BonusEffectValue') or ''}")
            out.append(f'<h2>Bonus</h2><p>{_e(lab)}: <b>{_e(val or rec.get("BonusEffectValue") or "")}</b>. Design bonuses count while the design is fitted.</p>')
        out.append('<p><a href="../tools/ship-viewer.html">Try designs on a ship in the 3D ship viewer</a>, where you can combine sail cloth, paints, patterns, '
                   'two flags and figureheads.</p>')
        return out

    PORT_TYPES = {'City': 'a city port: it has a shipyard, market, workshops and quests, and can be fought over in port battles',
                  'Bay': 'a bay: a smaller harbour with trade and repairs',
                  'NeutralBay': 'a neutral bay: open to every nation, a safe place to trade and repair',
                  'PirateBay': 'a pirate bay: a haven for pirates, where wanted captains can still trade and repair'}

    def _prepare_world(self):
        """World positions, shallow waters and trade routes (site_world), plus the map image, for the map and port pages."""
        import battle_sim, site_world
        self.world = None; self.shallows = None; self._map_src = None
        roots = list(battle_sim.texture_roots(self.recovery_dir, self.game_roots))
        roots += [d / 'Images' / 'LooseFiles' / 'Data' / 'Textures' for d in self._catalog_dirs()]
        for root in roots:
            if (root / 'map.png').is_file():
                self._map_src = root / 'map.png'; break
        self.shallows = site_world.find_shallows(roots)
        w = site_world.load(self.db, self.build, self.shallows)
        self.world = w if w['ports'] else None

    @classmethod
    def _world_uv(cls, u, v):
        su, ou, sv, ov = cls.MAP_FIT
        return (ov - v) * sv, (u - ou) * su          # (x, y) in world units

    def _port_map(self, port, *, radius=1700, size=560):
        """A picture of the waters around a port: the game map, shallow-water tint, towers, forts, nodes and routes."""
        if not self._map_src:
            return None
        from PIL import Image, ImageDraw
        import site_world
        Image.MAX_IMAGE_PIXELS = None
        if not hasattr(self, '_map_im'):
            self._map_im = Image.open(self._map_src).convert('RGB')
        im = self._map_im; W, H = im.size
        def px(x, y):
            u, v = self._uv(x, y); return u * W, v * H
        cx, cy = px(port['x'], port['y']); rx = abs(px(port['x'], port['y'] + radius)[0] - cx)
        box = (int(cx - rx), int(cy - rx), int(cx + rx), int(cy + rx))
        crop = im.crop(box).resize((size, size), Image.LANCZOS).convert('RGBA')
        k = size / (box[2] - box[0])
        to = lambda x, y: ((px(x, y)[0] - box[0]) * k, (px(x, y)[1] - box[1]) * k)
        if self.shallows:
            tint = Image.new('RGBA', (size // 4, size // 4), (0, 0, 0, 0)); tp = tint.load(); n = size // 4
            for j in range(n):
                for i in range(n):
                    u = (box[0] + (i + 0.5) * 4 / k) / W; v = (box[1] + (j + 0.5) * 4 / k) / H
                    val = self.shallows.get(*self._world_uv(u, v))
                    if val in site_world.SHALLOW_TINT:
                        tp[i, j] = site_world.SHALLOW_TINT[val] + (90,)
            crop = Image.alpha_composite(crop, tint.resize((size, size), Image.NEAREST))
        d = ImageDraw.Draw(crop)
        w = self.world
        for r in w['routes']:
            pts = [to(x, y) for x, y in r['pts']]
            for a_, b_ in zip(pts, pts[1:]):
                d.line([a_, b_], fill=(31, 95, 191, 220), width=3)
        for n_ in site_world.near(w['nodes'], port['x'], port['y'], radius * 1.5):
            x, y = to(n_['x'], n_['y']); d.rectangle([x - 5, y - 5, x + 5, y + 5], fill=(95, 106, 106), outline='white')
        for t in site_world.near(w['towers'], port['x'], port['y'], radius * 1.5):
            x, y = to(t['x'], t['y']); d.polygon([(x, y - 7), (x - 6, y + 5), (x + 6, y + 5)], fill=(192, 57, 43), outline='white')
        for f in site_world.near(w['forts'], port['x'], port['y'], radius * 1.5):
            x, y = to(f['x'], f['y']); d.rectangle([x - 7, y - 7, x + 7, y + 7], fill=(125, 60, 152), outline='white')
        for o in site_world.near(w['ports'], port['x'], port['y'], radius * 1.5):
            x, y = to(o['x'], o['y']); big = o is port
            d.ellipse([x - (11 if big else 7), y - (11 if big else 7), x + (11 if big else 7), y + (11 if big else 7)],
                      fill=(232, 192, 90) if big else (90, 169, 232), outline='white', width=3 if big else 2)
            d.text((x + 12, y - 8), o['n'], fill='white', stroke_width=3, stroke_fill='black')
        rel = f'assets/ports/{_slug(port["n"])}.webp'
        dst = self.out / rel; dst.parent.mkdir(parents=True, exist_ok=True)
        crop.convert('RGB').save(dst, 'WEBP', quality=82, method=4)
        return rel

    PORT_TYPES = {'City': 'a city port, with a shipyard, market, workshops and quests, that guilds fight over in port battles',
                  'Bay': 'a bay that guilds can capture and hold in port battles',
                  'NeutralBay': 'a neutral bay that no guild can capture, with a market and services open to everyone',
                  'PirateBay': 'a pirate bay, home to the pirates of the Archipelago'}

    def _port_world(self, title):
        w = getattr(self, 'world', None)
        if not w:
            return None
        return next((p for p in w['ports'] if p['n'].casefold() == title.casefold()), None)

    def _port_sections(self, rec):
        import site_world
        title = rec['_title']; port = self._port_world(title)
        t = self.PORT_TYPES.get(str(rec.get('Type') or ''), 'a port')
        out = [f'<p><b>{_e(title)}</b> is {_e(t)}.</p>']
        if not port:
            out.append(f'<p><a href="../map.html?port={_e(title)}">Show {_e(title)} on the world map</a>.</p>')
            return out
        w = self.world
        facts = []
        if port['faction']:
            facts.append(f'<b>Faction:</b> a {_e(port["faction"])} port.')
        if port['produces']:
            res_url = self.urls.get(('resource', port['produces'].casefold()))
            name = f'<a href="../{res_url}">{_e(port["produces"])}</a>' if res_url else _e(port['produces'])
            facts.append(f'<b>Produces:</b> {name}.' + (' Main trade routes from here carry it.' if any(r['type'] == 'Main' and title in (r['from'], r['to']) for r in w['routes']) else ''))
        if port['ranks']:
            facts.append(f'<b>Shipyard:</b> builds rank {port["ranks"]} and smaller ships.')
        if self.shallows:
            v = self.shallows.around(port['x'], port['y'], 220)
            facts.append(f'<b>Waters:</b> the approaches allow {_e(site_world.rank_text(v))}.')
        if port['pb_limit']:
            facts.append(f'<b>Port battles:</b> up to {_e(port["pb_limit"])} players per side.')
        if port['fixed_level']:
            facts.append(f'<b>Port level:</b> always level {port["fixed_level"]}.')
        for f in port['flags']:
            if f in site_world.FLAG_TEXT:
                facts.append(_e(site_world.FLAG_TEXT[f]))
        out.append('<h2>At a Glance</h2><ul>' + ''.join(f'<li>{x}</li>' for x in facts) + '</ul>')
        img = self._port_map(port)
        if img:
            out.append(f'<h2>Map</h2><figure class="portmap"><a href="../map.html?port={_e(title)}"><img src="../{img}" alt="Map of the waters around {_e(title)}" loading="lazy" width="560" height="560"></a>'
                       '<figcaption><span class="lg lg-port"></span>Port <span class="lg lg-tower"></span>Tower <span class="lg lg-fort"></span>Imperial fort '
                       '<span class="lg lg-node"></span>Resource node <span class="lg lg-route"></span>Trade route'
                       + (' · tinted water: <span class="lg lg-s2"></span>rank 2+ <span class="lg lg-s3"></span>3+ <span class="lg lg-s4"></span>4+ '
                          '<span class="lg lg-s5"></span>5+ <span class="lg lg-s6"></span>6+ ships only' if self.shallows else '') +
                       f'. <a href="../map.html?port={_e(title)}">Open on the world map</a>.</figcaption></figure>')
        towers = site_world.near(w['towers'], port['x'], port['y'], 1500)
        forts = site_world.near(w['forts'], port['x'], port['y'], 2500)
        if towers or forts:
            from collections import Counter
            c = Counter(t_['n'] for t_ in towers)
            out.append('<h2>Defences</h2><p>' + (', '.join(f'{n} {k.lower()}{"s" if n > 1 else ""}' for k, n in c.most_common()) + ' guard the waters near the port.' if towers else '')
                       + (f' {len(forts)} imperial fort{"s" if len(forts) > 1 else ""} nearby.' if forts else '')
                       + ' See <a href="../tools/defenses.html">towers, forts &amp; mortars</a> for their damage and range.</p>')
        mine = [r for r in w['routes'] if title in (r['from'], r['to'])]
        if mine:
            rows = []
            for r in sorted(mine, key=lambda r: (r['type'], r['length'])):
                other = r['to'] if r['from'] == title else r['from']
                cargo = 'changes' if r['cargo'] == ['varies'] else ', '.join(r['cargo']) or '—'
                rows.append([_e(r['type']), _e(other if other != title else '(round trip)'), _e(cargo), f'{r["length"]:,}',
                             _e(site_world.rank_text(r['shallow'])) if r['shallow'] is not None else '',
                             f'<a href="../map.html?route={r["id"]}">map</a>'])
            heads = ['Type', 'Other end', 'Cargo', 'Length', 'Ships that fit', '']
            if not self.shallows:
                heads.pop(4); rows = [r_[:4] + r_[5:] for r_ in rows]
            out.append('<h2>Trade Routes</h2><p>NPC merchant routes that start or end here. Main routes carry the ports\' produce; '
                       'supply routes carry what a resource node makes.</p>' + _table(heads, rows))
        nodes = site_world.near(w['nodes'], port['x'], port['y'], 2200)
        if nodes:
            from collections import Counter
            c = Counter(f'{n_["n"]} ({n_["res"]})' for n_ in nodes)
            out.append('<h2>Resources Nearby</h2><ul>' + ''.join(f'<li>{_e(k)}' + (f' ×{n}' if n > 1 else '') + '</li>' for k, n in sorted(c.items())) + '</ul>')
        import math
        nb = sorted((o for o in w['ports'] if o is not port), key=lambda o: math.hypot(o['x'] - port['x'], o['y'] - port['y']))[:4]
        if nb:
            out.append('<h2>Neighbouring Ports</h2><ul>' + ''.join(
                f'<li><a href="../{self.urls.get(("port", o["n"].casefold()), "map.html")}">{_e(o["n"])}</a> · {math.hypot(o["x"] - port["x"], o["y"] - port["y"]):,.0f} away'
                + (f' · {_e(o["faction"])}' if o['faction'] else '') + '</li>' for o in nb) + '</ul>')
        return out

    def _resource_sections(self, rec):
        if not hasattr(self, '_res_use'):
            self._recipe_sections({})          # loads the ingredient tables
            uses, makes = defaultdict(list), defaultdict(list)
            for r in self.entities.get('recipe', []):
                for n, q in self._ingredients.get(r.get('RecipeID'), []):
                    uses[str(n).casefold()].append((r['_title'], q))
                if str(r.get('OutputType')).lower() == 'resource':
                    n = self._res_names.get(str(r.get('OutputID')))
                    if n:
                        makes[str(n).casefold()].append((r['_title'], r.get('OutputQuantity') or 1, r.get('CraftHours')))
            self._res_use, self._res_make = uses, makes
        key = rec['_title'].casefold(); out = []
        link = lambda t: (f'<a href="../{self.urls[("recipe", t.casefold())]}">{_e(t)}</a>' if ('recipe', t.casefold()) in self.urls else _e(t))
        if self._res_make.get(key):
            out.append('<h2>How it is made</h2><ul>' + ''.join(f'<li>{link(t)}: makes {_e(q)}{f" in {_e(h)} h" if h else ""}</li>' for t, q, h in self._res_make[key]) + '</ul>')
        if self._res_use.get(key):
            out.append(f'<h2>Used in crafting</h2><p>{_e(rec["_title"])} is an ingredient in {len(self._res_use[key])} recipe{"s" if len(self._res_use[key]) != 1 else ""}:</p><ul>' +
                       ''.join(f'<li>{link(t)} ({_e(q)} needed)</li>' for t, q in self._res_use[key]) + '</ul>')
        mass, price = rec.get('Mass'), rec.get('MediumCost')
        if mass or price:
            bits = []
            if mass:
                bits.append(f'each unit weighs {_e(mass)} in the hold, which counts toward the ship\'s load and slows it when heavily loaded')
            if price:
                bits.append(f'its typical trade price is about {int(float(price)):,} gold, though prices differ from port to port')
            out.append('<h2>Trading</h2><p>' + _e(rec['_title']) + ': ' + '; '.join(bits) + '.</p>')
        return out

    def _recipe_sections(self, rec):
        if not hasattr(self, '_ingredients'):
            self._ingredients = defaultdict(list); names = {}
            for raw, in self.db.conn.execute("SELECT raw_json FROM records WHERE dataset='Resources'"):
                r = json.loads(raw); names[str(r.get('ID'))] = r.get('EnglishName') or r.get('Name')
            for raw, in self.db.conn.execute("SELECT raw_json FROM records WHERE dataset='Recipe_Ingredients'"):
                r = json.loads(raw)
                self._ingredients[r.get('RecipeID')].append((r.get('EnglishName') or names.get(str(r.get('ResourceID'))) or '?', r.get('Quantity')))
            self._res_names = names
        ing = self._ingredients.get(rec.get('RecipeID'), [])
        out = []
        if ing:
            items = []
            for n, q in ing:
                url = self.urls.get(('resource', str(n).casefold()))
                items.append(f'<li>{_e(q)} × ' + (f'<a href="../{url}">{_e(n)}</a>' if url else _e(n)) + '</li>')
            out.append('<h2>Ingredients</h2><ul>' + ''.join(items) + '</ul>')
        if str(rec.get('OutputType')).lower() == 'resource':
            n = self._res_names.get(str(rec.get('OutputID')))
            url = n and self.urls.get(('resource', str(n).casefold()))
            if n:
                out.append('<h2>Makes</h2><p>' + _e(rec.get('OutputQuantity') or 1) + ' × ' + (f'<a href="../{url}">{_e(n)}</a>' if url else _e(n)) + '</p>')
        return out

    def _missions(self):
        """PvE missions (waves of NPC ships per map) and the NPC kinds the client knows."""
        waves = defaultdict(set)
        for raw, in self.db.conn.execute("SELECT raw_json FROM records WHERE dataset='NPC_Mission_Waves'"):
            r = json.loads(raw)
            waves[(r.get('EnglishMapName') or r.get('MapKey'), r.get('MapKey'))].add((r.get('Wave') or 0, r.get('Entry') or 0, r.get('SourceType') or '', r.get('Count') or 0))
        kinds = set()
        for raw, in self.db.conn.execute("SELECT raw_json FROM records WHERE dataset='NPC_Types'"):
            r = json.loads(raw)
            if str(r.get('Type', '')).endswith('.NpcType') and r.get('Member') not in ('None',):
                kinds.add((r.get('Value'), r.get('Member')))
        if not waves and not kinds:
            return
        label = {'Pirate': 'Pirates', 'BossByName': 'Named boss', 'Trader': 'Traders', 'Reinforced': 'Reinforced pirates'}
        rows = []
        for (name, key), ws in sorted(waves.items(), key=lambda kv: str(kv[0][0])):
            slug = 'mission/' + _slug(name) + '.html'
            by_wave = defaultdict(list); acc = defaultdict(int)
            for w, e, src, n in sorted(ws):
                acc[(w, src)] += n
            for (w, src), n in sorted(acc.items()):
                by_wave[w].append((src, n))
            body = [f'<p>A PvE mission with <b>{len(by_wave)}</b> waves of NPC ships.</p>',
                    _table(['Wave', 'Ships'], [[str(w), ', '.join(f'{n} × {_e(label.get(src, _camel(src)))}' for src, n in grp)] for w, grp in sorted(by_wave.items())]),
                    '<p class="note">Counts are per spawn entry in the mission definition; named bosses appear as single ships.</p>']
            self._write(slug, _page(name, ''.join(body), depth=1, crumbs=[('Main page', 'index.html'), ('Missions & NPCs', 'category/missions.html'), (name, None)]))
            self.search.append({'t': name, 'u': slug, 'c': 'Mission', 'k': 'mission pve npc waves'})
            total = sum(n for grp in by_wave.values() for _, n in grp)
            rows.append([f'<a href="../{slug}">{_e(name)}</a>', str(len(by_wave)), str(total),
                         ', '.join(sorted({label.get(src, _camel(src)) for grp in by_wave.values() for src, _ in grp}))])
            self.pages += 1
        body = ['<h2>Missions</h2>', _table(['Mission', 'Waves', 'Ships', 'Enemies'], rows)]
        if kinds:
            body += ['<h2>NPC kinds</h2><p>The kinds of computer-controlled ships in the game.</p><ul class="cols">',
                     ''.join(f'<li>{_e(_camel(m).replace("_", " "))}</li>' for _, m in sorted(kinds)), '</ul>']
        self._write('category/missions.html', _page('Missions & NPCs', ''.join(body), depth=1))
        self.search.append({'t': 'Missions & NPCs', 'u': 'category/missions.html', 'c': 'Category', 'k': 'npc missions pve pirates boss'})

    # The game's map texture (Data/Textures/map.png) against world coordinates, fitted to the island
    # placements: u = Position1 / 22700 + 0.5, v = 0.495 - Position0 / 18800 (uniform scale, 0.225 px per unit).
    MAP_FIT = (22700.0, 0.5, 18800.0, 0.495)

    @classmethod
    def _uv(cls, x, z):
        su, ou, sv, ov = cls.MAP_FIT
        return round(z / su + ou, 5), round(ov - x / sv, 5)

    def _world_map(self):
        """Interactive world map: the game's map with ports, port-battle sites, forts, towers, trading posts, resource nodes,
        trade routes (typed, with cargo) and the shallow waters that limit ship size."""
        import battle_sim, site_world
        w = getattr(self, 'world', None)
        if not w:
            self._write('map.html', _page('World map', '<p class="note">No map data in this build.</p>')); return
        try:
            sites = battle_sim.port_battles(self.db, models_root=self.recovery_dir, build=self.build)
        except Exception:
            sites = []
        uv = self._uv
        def pt(o, **kw):
            u, v = uv(o['x'], o['y']); return dict(u=u, v=v, **kw)
        def nearest(u, v):
            best = min(w['ports'], key=lambda p: (uv(p['x'], p['y'])[0] - u) ** 2 + (uv(p['x'], p['y'])[1] - v) ** 2, default=None)
            return best['n'] if best else ''
        ports = []
        for p_ in w['ports']:
            info = [x for x in (site_world.TYPE_TEXT.get(p_['type'], p_['type']), (p_['faction'] + ' port') if p_['faction'] else '',
                                ('Produces ' + p_['produces']) if p_['produces'] else '', f'shipyard: rank {p_["ranks"]}+' if p_['ranks'] else '') if x]
            if self.shallows:
                info.append('waters: ' + site_world.rank_text(self.shallows.around(p_['x'], p_['y'], 220)))
            ports.append(pt(p_, n=p_['n'], type=p_['type'], info=' · '.join(info), url=self.urls.get(('port', p_['n'].casefold()))))
        pb = []
        for s_ in sites:
            u, v = uv(s_['x'], s_['z'])
            pb.append({'id': s_['id'], 'u': u, 'v': v, 'towers': s_['towers'], 'n': nearest(u, v)})
        routes = []
        for r in w['routes']:
            routes.append({'id': r['id'], 'type': r['type'], 'from': r['from'], 'to': r['to'], 'cargo': r['cargo'], 'len': r['length'], 'loop': r['loop'],
                           'ships': site_world.rank_text(r['shallow']) if r['shallow'] is not None else '',
                           'pts': [list(uv(x, y)) for x, y in r['pts']]})
        image, aspect = self._map_image()
        shallow_img = ''
        if self.shallows:
            try:
                ov = site_world.shallows_overlay(self.shallows, (900, int(900 / aspect)), self._world_uv)
                dst = self.out / 'assets' / 'map' / 'shallows.webp'; dst.parent.mkdir(parents=True, exist_ok=True)
                ov.save(dst, 'WEBP', quality=80, method=4); shallow_img = 'assets/map/shallows.webp'
            except Exception:
                shallow_img = ''
        data = {'image': image, 'aspect': aspect, 'shallows': shallow_img, 'ports': ports, 'pb': pb,
                'towers': [pt(t, n=t['n']) for t in w['towers']], 'forts': [pt(f, n=f['n']) for f in w['forts']],
                'villages': [pt(v_, n=v_['n']) for v_ in w['posts'] + w['lights']],
                'mines': [pt(m, n=f'{m["n"]} · {m["res"]}') for m in w['nodes']], 'altars': [pt(a_, n='Altar') for a_ in w['altars']],
                'routes': routes, 'route_text': site_world.ROUTE_TEXT}
        self._write('assets/world-map.js', 'window.WORLD_MAP=' + json.dumps(data, separators=(',', ':')) + ';\n' +
                    (Path(__file__).resolve().parent / 'viewer' / 'world_map.js').read_text(encoding='utf-8'))
        from collections import Counter
        kinds = Counter(r['type'] for r in routes)
        rrows = [[f'<span class="rt rt-{_e(r["type"].lower())}">{_e(r["type"])}</span>', _e(r['from']), _e(r['to'] if r['to'] != r['from'] else '(round trip)'),
                  _e('changes' if r['cargo'] == ['varies'] else ', '.join(r['cargo']) or '—'), f'{r["len"]:,}', _e(r['ships']),
                  f'<a href="map.html?route={r["id"]}">show</a>'] for r in sorted(routes, key=lambda r: (r['type'], r['from'], r['to']))]
        table = _table(['Port battle', 'Towers', 'Simulate'],
                       [[_e(s_['n'] or f'Site {s_["id"] + 1}'), str(s_['towers']),
                         f'<a href="tools/battle-simulator.html?preset=pbfleet&amp;site={s_["id"]}">port battle</a> · '
                         f'<a href="tools/battle-simulator.html?preset=port&amp;site={s_["id"]}">towers only</a> · '
                         f'<a href="map.html?port={_e(s_["n"])}">on the map</a>'] for s_ in sorted(pb, key=lambda x: x['n'])])
        body = ('<p>Drag to move, scroll or pinch to zoom, double-click to zoom in. Click a port, marker or trade route for details. Port names appear as you zoom in. '
                + ('Turn on <b>Shallow waters</b> to see where large ships can\'t sail.' if shallow_img else '') + '</p>'
                '<div id="wmap"></div><script src="assets/world-map.js"></script><script>WorldMap.mount(document.getElementById("wmap"),window.WORLD_MAP)</script>'
                + (('<h2>Shallow Waters</h2><p>Some waters are too shallow for big ships. On the map, tinted water shows the largest ship allowed: '
                    '<span class="lg lg-s2"></span>rank 2 and smaller, <span class="lg lg-s3"></span>rank 3 and smaller, <span class="lg lg-s4"></span>rank 4 and smaller, '
                    '<span class="lg lg-s5"></span>rank 5 and smaller, <span class="lg lg-s6"></span>rank 6 and smaller. Rank 1 is the largest class. '
                    'Sailing a bigger ship into these waters is blocked in game.</p>') if shallow_img else '')
                + '<h2>Trade Routes</h2><p>NPC merchants sail these routes. ' + ' '.join(_e(site_world.ROUTE_TEXT[k]) for k in ('Main', 'Supply', 'Coastal', 'Central', 'Smuggling') if kinds.get(k)) + '</p>'
                + '<p>' + ' · '.join(f'{kinds[k]} {k.lower()}' for k in ('Main', 'Supply', 'Coastal', 'Central', 'Smuggling') if kinds.get(k)) + ' routes.</p>'
                + _table(['Type', 'From', 'To', 'Cargo', 'Length', 'Ships that fit', ''], rrows)
                + '<h2>Port-Battle Sites</h2>' + table)
        self._write('map.html', _page('World map', body))
        self.search.append({'t': 'World map', 'u': 'map.html', 'c': 'Map', 'k': 'map ports forts towers port battle trade routes shallow waters'})

    def _map_image(self):
        """assets/map/world.webp from the game's map texture; a plain sea when the texture wasn't recovered."""
        import battle_sim
        src = None
        for root in battle_sim.texture_roots(self.recovery_dir, self.game_roots):
            if (root / 'map.png').is_file():
                src = root / 'map.png'; break
        if not src:
            self._write('assets/map/world.svg', '<svg xmlns="http://www.w3.org/2000/svg" width="1206" height="1000"><rect width="100%" height="100%" fill="#9fb7c1"/></svg>')
            return 'assets/map/world.svg', 1.206
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = None
        dst = self.out / 'assets' / 'map' / 'world.webp'; dst.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(src) as im:
            aspect = im.width / im.height
            im = im.convert('RGBA'); im.thumbnail((4096, 4096))
            im.save(dst, 'WEBP', quality=80, method=4)
        return 'assets/map/world.webp', round(aspect, 5)

    def _sim_ships(self):
        if not hasattr(self, '_simships'):
            try:
                import battle_sim
                self._simships = {x['n']: x for x in battle_sim.catalog_data(self.db, build=self.build)['ships']}
            except Exception:
                self._simships = {}
        return self._simships

    def _ship_sections(self, rec, hitboxes):
        import combat_sim
        out = []
        ships = self._sim_ships(); me = ships.get(rec.get('_title'))
        model = self._model_for(rec)
        hb = hitboxes.get(model) if model else None
        if me and me.get('rank'):
            peers = [x for x in ships.values() if x.get('rank') == me['rank'] and x.get('hp')]
            rows = []
            for key, label, fmt, cls in (('hp', 'Hull HP', '{:,.0f}', ''), ('armor', 'Armor', '{:.1f}', 'warm'),
                                         ('speed', 'Speed', '{:.1f}', 'green'), ('mob', 'Turn (° per 10 s)', '{:.0f}', ''), ('crew', 'Crew', '{:,.0f}', '')):
                vals = [x[key] or 0 for x in peers]; top = max(vals) if vals else 0; avg = sum(vals) / len(vals) if vals else 0
                better = sorted(vals, reverse=True).index(me[key] or 0) + 1 if (me[key] or 0) in vals else None
                rows.append(f'<tr><td>{label}</td>' + _bar(me[key], top, fmt=fmt, cls=cls) +
                            f'<td>{fmt.format(avg)}</td><td>{f"#{better} of {len(peers)}" if better else ""}</td></tr>')
            out.append(f'<h2>Compared with rank {me["rank"]}</h2><table class="wikitable"><tr><th>Stat</th><th>{_e(rec.get("_title"))}</th>'
                       f'<th>Rank average</th><th>Place</th></tr>' + ''.join(rows) + '</table>'
                       f'<p><a href="../guide/ships-by-rank.html#rank-{me["rank"]}">All rank {me["rank"]} ships side by side</a></p>')
        facts = []
        if hb and hb.get('ports'):
            p = hb['ports']; facts.append(f'<tr><td>Broadside guns</td><td>{p.get("left", 0)} per side' + (f', {p["swivel"]} swivels' if p.get('swivel') else '') + '</td></tr>')
        if me:
            _, hard = combat_sim.hull_factors(me.get('weight') or 0, me.get('sid'))
            uniq = me.get('sid') in combat_sim.UNIQUE_ROSE_STATIC_IDS
            facts.append(f'<tr><td>Wind rose</td><td>{"Unique (points higher on one tack)" if uniq else "Regular"}</td></tr>')
            facts.append(f'<tr><td>Hardness</td><td>{hard:.2f} (0 = light and nimble, 1 = heavy, keeps speed at poor wind angles)</td></tr>')
        if facts:
            out.append('<h2>Handling</h2><table class="wikitable">' + ''.join(facts) + '</table>')
        if hb:
            out.append(f'<h2>Hit zones</h2><p>The blue box is the hull hitbox cannonballs are tested against first; then the {hb["masts"]} masts; '
                       f'then the {hb["sails"]} sails (4 slices each). Drag to rotate; scroll to zoom.</p><canvas class="hitbox" width="640" height="360" '
                       f'data-zones="{_e(json.dumps(hb["zones"], separators=(",", ":")))}"></canvas>'
                       '<script src="../assets/hitboxes.js"></script>')
        name = rec.get('_title') or ''
        if getattr(self, '_hd', None):
            out.append('<h2>Where to hit it</h2><p>Damage per ball from every direction, from this ship\'s real hull box, with every ammo, gun and mortar.</p>'
                       f'<div class="ha-mount" data-ship="{_e(name)}"></div><script src="../assets/hit-data.js"></script><script src="../assets/hit_analysis.js"></script>'
                       '<script>document.querySelectorAll(".ha-mount").forEach(e=>HitAnalysis.mount(e,{ship:e.dataset.ship,compact:true}))</script>'
                       f'<p><a href="../tools/ship-viewer.html?ship={_e(name)}">3D model, hitboxes &amp; designs</a> · <a href="../tools/hit-analysis.html?ship={_e(name)}">Full hit analysis</a> · <a href="../tools/fire-calculator.html">Fire calculator</a></p>')
        out.append('<h2>Try it</h2><p>'
                   f'<a href="../tools/battle-simulator.html?ship={_e(name)}">Battle simulator with the {_e(name)}</a> · '
                   f'<a href="../tools/damage-simulator.html?hp={_e(rec.get("Health"))}">Damage simulator</a> · '
                   '<a href="../tools/wind-rose.html">Wind &amp; sailing</a> · '
                   f'<a href="../tools/boarding-simulator.html">Boarding</a></p>')
        return out

    def _category_page(self, kind, recs):
        dataset, plural, fields, cols = ENTITIES[kind]
        labels = {label: (field, fmt) for field, label, fmt in fields}
        def num(v):
            try:
                return float(str(v).replace(',', '')) if v not in (None, '', True, False) else None
            except (TypeError, ValueError):
                return None
        numeric = {c for c in cols if sum(num(r.get(labels[c][0])) is not None for r in recs) >= max(3, len(recs) * 0.6)
                   and c not in ('Rank', 'Required rank', 'Tier', 'In shop', 'Hours', 'Makes')}
        tops = {c: max((num(r.get(labels[c][0])) or 0 for r in recs), default=0) for c in numeric}
        palette = {'Armor': 'warm', 'Speed': 'green', 'Penetration': 'warm', 'Range': 'green'}
        rows = []
        if kind == 'ship':
            recs = sorted(recs, key=lambda r: (num(r.get('ShipRank')) or 9, -(num(r.get('Health')) or 0)))
        for r in recs:
            ic = self.icons.get((kind, r['_title'].casefold()))
            cells = [(f'<img class="ticon" src="../{ic}" alt="" loading="lazy" width="28" height="28">' if ic else '')
                     + f'<a href="../{self.urls[(kind, r["_title"].casefold())]}">{_e(r["_title"])}</a>']
            for c in cols:
                field, fmt = labels[c]
                text = _e(_fmt(r.get(field), fmt) or '')
                v = num(r.get(field))
                if c in numeric and v is not None and tops.get(c):
                    w = max(0, min(100, 100 * v / tops[c]))
                    cells.append(f'<div class="vbar {palette.get(c, "")}"><i style="width:{w:.0f}%"></i><b>{text}</b></div>')
                else:
                    cells.append(text)
            rows.append(cells)
        intro = (f'<p>All {len(recs)} {_e(plural.lower())}. Bars compare each value with the highest in the list; click a heading to sort.</p>'
                 f'<p><input class="tfilter" type="search" placeholder="Filter {_e(plural.lower())}…" oninput="wikiFilter(this)"></p>')
        if kind == 'ship':
            groups = defaultdict(list)
            for r, cells in zip(recs, rows):
                groups[_fmt(r.get('Type'), 'camel') or 'Other'].append(cells)
            body = intro + ''.join(f'<h2>{_e(g)}</h2>' + _table(['Ship'] + cols, groups[g]) for g in sorted(groups))
            body = '<h2>Shipyard</h2>' + self._shipyard(recs) + '<h2>All ships by class</h2>' + body
        else:
            body = intro + _table([plural[:-1] if plural.endswith('s') else plural] + cols, rows)
        cat = CATEGORY_FILE[kind]
        self._write(f'category/{cat}.html', _page(f'Category: {plural}', body, depth=1,
                    crumbs=[('Main page', 'index.html'), (plural, None)]))
        self.search.append({'t': plural, 'u': f'category/{cat}.html', 'c': 'Category', 'k': plural})

    def _shipyard(self, recs):
        import shipyard
        bg = None
        for root in __import__('battle_sim').texture_roots(self.recovery_dir, self.game_roots):
            if (root / 'shipyard_background.png').is_file():
                bg = root / 'shipyard_background.png'; break
        shipyard.copy_assets(self.out / 'assets', bg)
        ships = [{'name': r['_title'], 'rank': r.get('ShipRank'), 'cls': r.get('SubtypeEnglish') or r.get('TypeEnglish') or r.get('Type'),
                  'hp': r.get('Health'), 'speed': r.get('BasicSpeed'), 'mob': r.get('BasicMobility'), 'armor': r.get('Armor'),
                  'crew': r.get('BaseCrewPlaces'), 'hold': r.get('CapacityCg'), 'url': self.urls[('ship', r['_title'].casefold())]} for r in recs]
        return shipyard.render(ships, lambda s: s['url'], depth=1)

    def _article_page(self, a):
        import wiki_engine
        md = self._scrub(a['body'])
        md = re.sub(r'^#\s+.*\n', '', md, count=1)       # title is rendered by the page chrome
        toc = wiki_engine.table_of_contents(md) if hasattr(wiki_engine, 'table_of_contents') else []
        html_body = wiki_engine.render_markdown(md, self._link).replace('href="/tag/', 'href="../category/articles.html#')
        toc_html = ''
        if toc and len(toc) >= 3:
            items = [(t['level'], t.get('title', ''), t.get('anchor', '')) if isinstance(t, dict) else tuple(t) for t in toc]
            top = min(lv for lv, _, _ in items)
            ids = set(re.findall(r'id="([^"]+)"', html_body))
            lis = [f'<li class="l{lv - top}"><a href="#{_e(an)}">{_e(re.sub(r"[*_`]", "", tt))}</a></li>' for lv, tt, an in items if lv <= top + 1 and an in ids]
            toc_html = ('<div class="toc"><b>Contents</b><ul>' + ''.join(lis) + '</ul></div>') if len(lis) >= 3 else ''
        url = self.article_urls[a['slug']]
        body = toc_html + html_body + f'<p><span class="tag"><a href="../category/articles.html#{_e(_slug(a["section"]))}">{_e(a["section"])}</a></span></p>'
        self._write(url, _page(a['title'], body, depth=1, crumbs=[('Main page', 'index.html'), ('Guides & mechanics', 'category/articles.html'), (a['section'], None)]))
        self.search.append({'t': a['title'], 'u': url, 'c': a['section'], 'k': a['section']})

    def _articles_category(self):
        groups = defaultdict(list)
        for a in self.articles:
            groups[a['section']].append(a)
        try:
            ov = _Overviews(self).pages()
        except Exception:
            ov = []
        for slug, title, blurb, body in ov:
            self._write(f'guide/{slug}.html', _page(title, body, depth=1, crumbs=[('Main page', 'index.html'), ('Guides & mechanics', 'category/articles.html'), (title, None)]))
            self.search.append({'t': title, 'u': f'guide/{slug}.html', 'c': 'Guide', 'k': 'overview data compare ' + blurb})
        if ov:
            groups['Data overviews'] = [{'title': t, 'slug': None, 'url': f'guide/{sl}.html', 'blurb': b} for sl, t, b, _ in ov]
        body = [f'<p>{len(self.articles)} guides: the game\'s own help pages, verified mechanics, and data overviews built from the game files.</p>']
        for sec in [x for x in GUIDE_ORDER if x in groups] + sorted(x for x in groups if x not in GUIDE_ORDER):
            if sec == 'Data overviews':
                body.append(f'<h2 id="{_e(_slug(sec))}">{_e(sec)}</h2><div class="cards">' + ''.join(
                    f'<a class="cardl" href="../{a["url"]}"><b>{_e(a["title"])}</b><span>{_e(a["blurb"])}</span></a>' for a in groups[sec]) + '</div>')
                continue
            body.append(f'<h2 id="{_e(_slug(sec))}">{_e(sec)}</h2><ul class="cols">' + ''.join(
                f'<li><a href="../{self.article_urls[a["slug"]]}">{_e(a["title"])}</a></li>' for a in groups[sec]) + '</ul>')
        self._write('category/articles.html', _page('Guides & mechanics', ''.join(body), depth=1, crumbs=[('Main page', 'index.html'), ('Guides & mechanics', None)]))

    # small original line icons for the main page's sitemap boxes
    ICONS = {
        'combat': '<svg viewBox="0 0 48 48"><circle cx="13" cy="35" r="7" fill="#7a4b26"/><circle cx="13" cy="35" r="3" fill="#f3d58e"/><rect x="12" y="20" width="30" height="10" rx="5" transform="rotate(-24 27 25)" fill="#2c3e50"/><circle cx="41" cy="11" r="3" fill="#2c3e50"/></svg>',
        'world': '<svg viewBox="0 0 48 48"><circle cx="24" cy="24" r="19" fill="#dfeaf7" stroke="#1d4e6f" stroke-width="3"/><path d="M24 8 L29 24 L24 40 L19 24Z" fill="#c8442f"/><path d="M24 24 L29 24 L24 40Z" fill="#1d4e6f"/><circle cx="24" cy="24" r="3" fill="#f3d58e"/></svg>',
        'crew': '<svg viewBox="0 0 48 48"><circle cx="24" cy="10" r="5" fill="none" stroke="#1d4e6f" stroke-width="3"/><path d="M24 15 V42 M14 22 H34 M8 30 Q10 42 24 42 Q38 42 40 30" fill="none" stroke="#1d4e6f" stroke-width="3.5" stroke-linecap="round"/></svg>',
        'economy': '<svg viewBox="0 0 48 48"><ellipse cx="24" cy="36" rx="15" ry="5" fill="#b8873a"/><rect x="9" y="26" width="30" height="10" fill="#d9a948"/><ellipse cx="24" cy="26" rx="15" ry="5" fill="#f3d58e"/><rect x="9" y="16" width="30" height="10" fill="#d9a948"/><ellipse cx="24" cy="16" rx="15" ry="5" fill="#f8e3a8"/></svg>',
        'cosmetic': '<svg viewBox="0 0 48 48"><path d="M10 6 V44" stroke="#5b4636" stroke-width="3"/><path d="M12 8 Q24 2 30 9 T42 9 V27 Q36 21 30 27 T12 27Z" fill="#2f7fbf"/><path d="M20 12 l3 5 5 1-4 4 1 5-5-3-5 3 1-5-4-4 5-1z" fill="#f3d58e"/></svg>',
        'guide': '<svg viewBox="0 0 48 48"><path d="M6 10 Q16 6 24 11 Q32 6 42 10 V40 Q32 36 24 41 Q16 36 6 40Z" fill="#f6efdc" stroke="#1d4e6f" stroke-width="2.5"/><path d="M24 11 V41" stroke="#1d4e6f" stroke-width="2"/><path d="M10 17 H20 M10 23 H20 M10 29 H18 M28 17 H38 M28 23 H38 M28 29 H36" stroke="#8aa2b8" stroke-width="2"/></svg>',
        'tools': '<svg viewBox="0 0 48 48"><circle cx="24" cy="24" r="8" fill="none" stroke="#1d4e6f" stroke-width="4"/><path d="M24 4 V12 M24 36 V44 M4 24 H12 M36 24 H44 M10 10 L16 16 M32 32 L38 38 M38 10 L32 16 M16 32 L10 38" stroke="#1d4e6f" stroke-width="4" stroke-linecap="round"/></svg>',
        'wiki': '<svg viewBox="0 0 48 48"><circle cx="24" cy="24" r="19" fill="#123f60"/><path d="M13 16 L18 34 L24 20 L30 34 L35 16" fill="none" stroke="#f3d58e" stroke-width="3.5" stroke-linejoin="round"/></svg>',
    }

    def _main_page(self):
        import wiki_engine
        h = HOSTING
        counts = {k: len(v) for k, v in self.entities.items()}
        ship_art = sorted((self.out / 'assets' / 'shipyard' / 'ships').glob('m*.png')) if (self.out / 'assets' / 'shipyard' / 'ships').is_dir() else []
        def art(*names):
            for n in names:
                for f in ship_art:
                    if f.stem.lower() == ('m' + n).lower():
                        return f'assets/shipyard/ships/{f.name}'
            return f'assets/shipyard/ships/{ship_art[0].name}' if ship_art else ''
        def links(items):
            return ' • '.join(f'<a href="{u}">{_e(t)}</a>' for t, u in items if u)
        def art_url(slug):
            for a in self.articles:
                if a['slug'] == slug:
                    return self.article_urls[a['slug']]
            return None
        guides = [(a['title'], self.article_urls[a['slug']]) for a in self.articles]
        mech = [(t, art_url(sl)) for t, sl in [('Damage formula', 'damage-formula'), ('Damage and sinking', 'damage-and-sinking'), ('Fires', 'large-and-minor-fires'),
                                              ('Hitboxes', 'ship-hitboxes'), ('Ammunition compared', 'ammunition-compared'), ('Boarding', 'boarding')]]
        classes = sorted({_fmt(r.get('Type'), 'camel') or 'Other' for r in self.entities.get('ship', [])})
        # --- notice + quick navigation (the wiki's "front desk")
        built = datetime.now(timezone.utc).strftime('%B %d, %Y').replace(' 0', ' ')
        notice = (f'<div class="mp-notice"><b>{_e(SITE_NAME)}</b>: every number comes straight from the game. '
                  f'<span>Data updated {built}.</span> Spotted a mistake? '
                  + '<a href="about.html#contact" data-report="general">Tell us</a>.' + '</div>')
        quick = ('<div class="mp-quick"><p class="mp-quick-main">' + links([('New player guide', art_url('ships-guns-and-consumables')), ('Shipyard', 'category/ships.html'),
                 ('World map', 'map.html'), ('3D ships', 'tools/ship-viewer.html'), ('Battle simulator', 'tools/battle-simulator.html'),
                 ('Guides', 'category/articles.html')] + ([('Discord', h['discord_url'])] if h.get('discord_url') else [])) + '</p>'
                 '<p>' + links([('Ships', 'category/ships.html'), ('Cannons', 'category/cannons.html'), ('Ammunition', 'category/ammo.html'), ('Upgrades', 'category/upgrades.html'),
                                ('Crew', 'category/crew.html'), ('Captain skills', 'category/skills.html'), ('Resources', 'category/resources.html'),
                                ('Crafting', 'category/recipes.html'), ('Ports', 'category/ports.html'), ('Missions', 'category/missions.html'),
                                ('Cosmetics', 'category/cosmetics.html'), ('Achievements', 'category/achievements.html')]) + '</p>'
                 '<p class="mp-quick-small">The wiki is free and run by volunteers' + (f' · <a href="{_e(h["donate_url"])}" rel="noopener" data-notc>donations keep it online</a>' if h.get('donate_url') else '')
                 + ' · <a href="sitemap.html" data-notc>all pages</a></p></div>')
        # --- welcome panel
        hero_ship = art('Bellona', 'Victory', 'Anson')
        welcome = ('<div class="mp-welcome"><div class="mp-welcome-main"><h2 class="mp-title">Welcome to the WoSB Wiki!</h2>'
                   f'<div class="mp-hero"><img class="mp-hero-logo" src="assets/brand/emblem.png" alt="" width="120" height="120">'
                   f'<div><b>WoSB Wiki</b><span>Ships · Guns · Maps · Battle tools</span></div>'
                   + (f'<img class="mp-hero-ship" src="{hero_ship}" alt="" loading="lazy">' if hero_ship else '') + '</div>'
                   f'<p>Welcome to the WoSB Wiki, a free community reference for <b>World of Sea Battle</b>, the open-world MMO of the age of sail. '
                   f'It covers {counts.get("ship", 0)} ships, {counts.get("cannon", 0)} cannons, {counts.get("ammo", 0)} kinds of ammunition, every upgrade, crew unit, '
                   f'captain skill, port and cosmetic, read straight from the game, with interactive tools to test damage, fires, sailing and whole port battles.</p></div>'
                   '<div class="mp-visitors"><h3>New visitors</h3><p>Find information by:</p><ul>'
                   '<li>the links at the <b>top</b> and in the <b>sidebar</b></li><li>the <a href="#sitemap">sitemap</a> below</li>'
                   '<li>the list of <a href="sitemap.html">all pages</a></li><li>the <b>search box</b> at the top right</li></ul>'
                   '<p>Read <a href="about.html">where the facts come from</a>.</p></div></div>')
        # --- what's new: this build, then recently changed guides grouped by day
        cards = [(f'This update ({built})', [f'{counts.get("ship", 0)} ships, {counts.get("cannon", 0)} cannons and {counts.get("ammo", 0)} ammo types',
                                            '<a href="tools/ship-viewer.html">3D ship viewer</a> with every design, flag and figurehead',
                                            '<a href="tools/hit-analysis.html">Hit analysis</a> and <a href="tools/fire-calculator.html">fire calculator</a>',
                                            '<a href="tools/battle-simulator.html">Battle simulator</a> for duels and port battles',
                                            '<a href="map.html">World map</a> with ports, forts and trade routes'], art('Victory', 'Bellona'))]
        days = defaultdict(list)
        for a in sorted((a for a in self.articles if a.get('updated')), key=lambda a: a['updated'], reverse=True):
            days[a['updated'][:10]].append(a)
        for day in list(days)[:3]:
            try:
                label = datetime.strptime(day, '%Y-%m-%d').strftime('%B %d, %Y').replace(' 0', ' ')
            except ValueError:
                label = day
            cards.append((f'Guides updated ({label})', [f'<a href="{self.article_urls[a["slug"]]}">{_e(a["title"])}</a>' for a in days[day][:8]], None))
        whatsnew = ('<h2 class="mp-h">What\'s New <small>(<a href="recent.html">recent changes</a>)</small></h2><div class="mp-news">' + ''.join(
            f'<div class="mp-card"><div class="mp-card-head">{_e(t)}' + (f'<img src="{img}" alt="" loading="lazy">' if img else '') + '</div><ul>'
            + ''.join(f'<li>{x}</li>' for x in items) + '</ul></div>' for t, items, img in cards) + '</div>')
        # --- sitemap boxes
        def box(title, icon, groups, img=None):
            pic = f'<img src="{img}" alt="" loading="lazy">' if img else f'<span class="mp-ico">{self.ICONS[icon]}</span>'
            return (f'<div class="mp-box"><div class="mp-box-head"><b>{_e(title)}</b>{pic}</div>' + ''.join(
                f'<h4>{_e(g)}</h4><p>{links(items)}</p>' for g, items in groups if any(u for _, u in items)) + '</div>')
        boxes = [
            box('Ships', 'combat', [('Ship classes', [(c, 'category/ships.html') for c in classes]),
                                    ('Browse', [('Shipyard', 'category/ships.html'), ('Ships by rank', 'guide/ships-by-rank.html'), ('Compare ships', 'tools/compare-ships.html')]),
                                    ('In 3D', [('3D ship viewer', 'tools/ship-viewer.html'), ('Hitbox viewer', 'tools/hitboxes.html'), ('Hit analysis', 'tools/hit-analysis.html')])],
                art('Bellona', 'Anson')),
            box('Combat', 'combat', [('Weapons', [('Cannons', 'category/cannons.html'), ('Cannons compared', 'guide/cannons-compared.html'), ('Ammunition', 'category/ammo.html'),
                                                  ('Ship upgrades', 'category/upgrades.html'), ('Upgrades by effect', 'guide/upgrades-by-effect.html')]),
                                     ('Mechanics', mech),
                                     ('Tools', [('Damage simulator', 'tools/damage-simulator.html'), ('Fire calculator', 'tools/fire-calculator.html'),
                                                ('Towers, forts & mortars', 'tools/defenses.html'), ('Battle simulator', 'tools/battle-simulator.html')])]),
            box('World', 'world', [('The Archipelago', [('World map', 'map.html'), ('Ports', 'category/ports.html'), ('Missions & NPCs', 'category/missions.html')]),
                                   ('Port battles', [('Port battle rules', 'guide/port-battle-rules.html'), ('Ports and port battles', art_url('ports-and-port-battles')),
                                                     ('Towers & forts', 'tools/defenses.html')]),
                                   ('Sailing', [('Sailing and wind', art_url('sailing-and-wind')), ('Wind & sailing tool', 'tools/wind-rose.html'),
                                                ('The world and NPC ships', art_url('the-world-and-npc-ships'))])]),
            box('Captain & crew', 'crew', [('Your crew', [('Crew units', 'category/crew.html'), ('Boarding', art_url('boarding')), ('Boarding simulator', 'tools/boarding-simulator.html')]),
                                           ('Your captain', [('Captain skills', 'category/skills.html'), ('Achievements', 'category/achievements.html'),
                                                             ('PvP, flags and notoriety', art_url('pvp-and-reputation')), ('Guilds and factions', art_url('guilds-and-factions'))])]),
            box('Economy', 'economy', [('Goods', [('Resources', 'category/resources.html'), ('Crafting recipes', 'category/recipes.html')]),
                                       ('Making money', [('Trading, crafting and making money', art_url('trading-and-crafting')), ('Ships, guns and consumables', art_url('ships-guns-and-consumables'))])]),
            box('Cosmetics & islands', 'cosmetic', [('Ship designs', [('Ship cosmetics', 'category/cosmetics.html'), ('Try them in 3D', 'tools/ship-viewer.html')]),
                                                    ('Personal islands', [('Island decorations', 'category/decorations.html')])]),
            box('Guides', 'guide', [('All guides', guides[:24] or [('Guides & mechanics', 'category/articles.html')])]),
            box('About the wiki', 'wiki', img='assets/brand/emblem.png', groups=[('Wiki', [('About', 'about.html'), ('All pages', 'sitemap.html'), ('Recent changes', 'recent.html')]),
                                           ('Policies', [('Privacy policy', 'privacy.html'), ('Terms of use', 'terms.html'), ('Copyright disclaimer', 'disclaimer.html')]),
                                           ('Community', [(t, u) for t, u in [('Discord', h.get('discord_url')), ('Donate', h.get('donate_url'))] if u])]),
        ]
        sitemap = '<h2 class="mp-h" id="sitemap">Sitemap</h2><div class="mp-boxes">' + ''.join(boxes) + '</div>'
        body = notice + quick + welcome + whatsnew + sitemap
        self._write('index.html', _page('Main page', body, depth=0, tab='Main page'))

    def _recent(self):
        rows = sorted((a for a in self.articles if a.get('updated')), key=lambda a: a['updated'], reverse=True)[:50]
        body = '<ul>' + ''.join(f'<li>{_e(a["updated"][:10])} · <a href="{self.article_urls[a["slug"]]}">{_e(a["title"])}</a></li>' for a in rows) + '</ul>'
        self._write('recent.html', _page('Recent changes', body or '<p>No changes yet.</p>'))

    def _about(self):
        body = ('<p>The WoSB Wiki is a free community reference for World of Sea Battle, run by the Band of Misfits guild. Ship, gun, ammo, upgrade, crew, '
                'port and cosmetic data is taken from the game and refreshed when the game updates, so numbers match what the game itself uses.</p>'
                '<h2>Where the facts come from</h2><ul><li><b>Game data</b>: the game\'s own tables (stats, prices, recipes, map positions).</li>'
                '<li><b>Mechanics</b>: the game\'s rules for hit zones, fires, sailing, boarding and port battles, explained in plain words.</li>'
                '<li><b>Server-side values</b> (exact cannonball damage, fire chances) are decided on the game\'s servers; pages mark them as estimates.</li></ul>'
                '<h2>Models and artwork</h2><p>Ship models, textures and map art shown in the 3D viewer, simulators and shipyard come from World of Sea Battle and belong to '
                'Thera Interactive. They are shown for reference on this non-profit community site and are not offered for download; see the <a href="disclaimer.html">copyright disclaimer</a>.</p>'
                '<h2 id="contact">Contact</h2><p>Found a mistake or want to help? Use <a href="#contact" data-report="general">Tell us</a>, or the '
                '"Report a problem with this page" button at the bottom of any page. Representing the game\'s makers? ' + site_legal._contact(HOSTING).capitalize() + '.</p>'
                '<p>See also the <a href="privacy.html">privacy policy</a>, <a href="terms.html">terms of use</a> and <a href="disclaimer.html">copyright disclaimer</a>.</p>')
        self._write('about.html', _page('About', body))
        self._write('privacy.html', _page('Privacy policy', site_legal.privacy(HOSTING)))
        self._write('terms.html', _page('Terms of use', site_legal.terms(HOSTING)))
        self._write('disclaimer.html', _page('Copyright disclaimer', site_legal.disclaimer(HOSTING)))
        if HOSTING.get('standalone'):
            self._write('admin/index.html', _page('Admin dashboard', '<p>Reports and messages sent from the wiki\'s "Report a problem" and "Tell us" forms.</p>'
                        '<div id="admin-app"><p>Checking your login…</p></div><script src="../assets/admin.js" defer></script>', depth=1,
                        crumbs=[('Main page', 'index.html'), ('Admin dashboard', None)], report=False))

    # ---- tools
    def _tools(self, hitboxes):
        ships = [{'n': r['_title'], 'hp': r.get('Health'), 'armor': r.get('Armor'), 'speed': r.get('BasicSpeed'),
                  'mob': r.get('BasicMobility'), 'crew': r.get('BaseCrewPlaces'), 'cargo': r.get('CapacityCg'),
                  'rank': r.get('ShipRank'), 'cls': r.get('TypeEnglish') or r.get('Type'),
                  'model': self._model_for(r), 'sid': r.get('StaticInfoID')} for r in self.entities.get('ship', [])]
        roses = [json.loads(raw) for raw, in self.db.conn.execute(
            "SELECT raw_json FROM records WHERE dataset='WindRoses' ORDER BY CASE source_root WHEN ? THEN 0 ELSE 1 END", (self.build,))]
        seen = set(); rose_data = []
        for r in roses:
            key = (r.get('Name') or '').casefold()
            if key in seen:
                continue
            seen.add(key)
            rose_data.append({k: r.get(k) for k in ('Name', 'FordewindFineEdge', 'GreenLeft', 'GreenRight', 'HeadwindLeft', 'HeadwindRight')})
        self._write('data/ships.json', json.dumps(ships, separators=(',', ':')))
        self._write('assets/hitboxes.js', HITBOX_JS)
        crumbs = [('Main page', 'index.html'), ('Tools', None)]
        self._write('tools/damage-simulator.html', _page('Damage simulator', DAMAGE_TOOL.replace('__SHIPS__', json.dumps(ships, separators=(',', ':'))), depth=1, crumbs=crumbs, tab='Tool'))
        try:
            import battle_sim
            wmap = {s['n']: (s['weight'], s['sid']) for s in battle_sim.catalog_data(self.db, build=self.build)['ships']}
        except Exception:
            wmap = {}
        wind_ships = [{'n': s['n'], 'weight': wmap.get(s['n'], (None,))[0], 'sid': wmap.get(s['n'], (None, s.get('sid')))[1]} for s in ships]
        self._write('assets/wosb_sim.js', (Path(__file__).resolve().parent / 'viewer' / 'wosb_sim.js').read_text(encoding='utf-8'))
        self._write('tools/wind-rose.html', _page('Wind & sailing', WIND_TOOL.replace('__ROSES__', json.dumps(rose_data)).replace('__SHIPS__', json.dumps(wind_ships, separators=(',', ':'))), depth=1, crumbs=crumbs, tab='Tool'))
        self._write('tools/compare-ships.html', _page('Ship comparison', COMPARE_TOOL.replace('__SHIPS__', json.dumps(ships, separators=(',', ':'))), depth=1, crumbs=crumbs, tab='Tool'))
        hb_ships = [s for s in ships if s['model'] in hitboxes]
        options = ''.join(f'<option value="{_e(s["model"])}">{_e(s["n"])}</option>' for s in hb_ships)
        payload = json.dumps({s['model']: hitboxes[s['model']]['zones'] for s in hb_ships}, separators=(',', ':'))
        hb_body = ('<p>Reconstructed hit zones: hull (blue), sail slices (orange, darker = larger share of sail health), masts (brown). '
                   'Drag to rotate, scroll to zoom.</p>' + (f'<div class="tool"><label>Ship <select id="hbship">{options}</select></label></div>'
                   '<canvas id="hbcanvas" class="hitbox" width="900" height="480"></canvas>'
                   f'<script>window.HITBOXES={payload};</script><script src="../assets/hitboxes.js"></script>'
                   if hb_ships else '<p class="note">Hit zones for the ships aren\'t available yet. Check back after the next wiki update.</p>'))
        self._write('tools/hitboxes.html', _page('Hitbox viewer', hb_body, depth=1, crumbs=crumbs, tab='Tool'))
        self._write('assets/wosb_sim.js', (Path(__file__).resolve().parent / 'viewer' / 'wosb_sim.js').read_text(encoding='utf-8'))
        if getattr(self, '_hd', None):
            self._hit_tools(hitboxes, crumbs)
        self._sim_tools()
        for t, u in TOOLS:
            self.search.append({'t': t, 'u': u, 'c': 'Tool', 'k': 'tool calculator simulator'})

    def _hit_data(self, hitboxes):
        if getattr(self, '_hd', None) is not None:
            return self._hd
        import battle_sim
        d = battle_sim.catalog_data(self.db, build=self.build)
        ships = []
        for s_ in d['ships']:
            hb = hitboxes.get(s_.get('model')) if s_.get('model') else None
            ships.append({'n': s_['n'], 'armor': s_['armor'], 'hp': s_['hp'], 'rank': s_['rank'], 'cls': s_['cls'], 'crew': s_['crew'], 'speed': s_['speed'],
                          'box': hb['zones'][0]['b'] if hb and hb.get('zones') else None,
                          'ports': hb.get('ports') if hb else None, 'masts': hb.get('masts') if hb else None, 'sails': hb.get('sails') if hb else None})
        cal = self.damage_calibration or {}
        towers = []
        names = {'t_mortar': ('Mortar tower', 'Lobs shells over everything; can\'t hit ships inside its dead zone.'),
                 't_fire': ('Prometheus (fire) tower', 'Short-range flamethrowers, each covering ±45°; sets ships on fire.'),
                 't_cannonsstr': ('Cannon tower', 'Long guns covering ±30° per gun; damage depends on your armor.')}
        for key, spec in battle_sim.TOWER_SPECS.items():
            n, note = names.get(key, (key, ''))
            t = dict(spec, n=n, note=note)
            if spec['kind'] == 'cannon':
                t.update(gun='32-pdr Long Gun', range=145)
            towers.append(t)
        self._hd = {'ships': sorted(ships, key=lambda x: x['n']),
                    'cannons': [{k: c.get(k) for k in ('n', 'pen', 'min', 'max', 'reload', 'splash', 'scatter', 'mortar', 'cls', 'feature', 'mount')} for c in d['cannons'] if c.get('pen')],
                    'ammo': [{'n': a['n'], 'pen': a.get('pen') or 0, 'df': a.get('df') or 1, 'min': a.get('min') or 0, 'sail': a.get('sail'), 'crew': a.get('crew'),
                              'reload': a.get('reload') or 1, 'fx': a.get('fx') or ''} for a in d['ammo']],
                    'calib': {'calibrated': bool(cal.get('calibrated')), 'armor_weight': cal.get('armor_weight', 1), 'scale': cal.get('scale', 1), 'samples': cal.get('samples', 0)},
                    'towers': towers,
                    'pb': {'base': {1: [12100, 26400], 2: [10000, 21700], 3: [9100, 20000], 4: [7700, 16700], 5: [6600, 14500]}, 'base_low': [4500, 10000],
                           'team': {5: 0.5, 7: 0.6, 10: 0.7, 15: 0.85, 20: 1, 40: 1.15}, 'level': [1, 1, 1.04, 1.08, 1.12, 1.16, 1.2, 1.24],
                           'capture_r': 30, 'capture_s': 30, 'fort_board_s': 25, 'tower_armor': 3}}
        return self._hd

    def _hit_tools(self, hitboxes, crumbs):
        """Hit analysis, towers/forts/mortars and fire calculator: data in assets/hit-data.js, logic in viewer/*.js."""
        data = self._hit_data(hitboxes)
        viewer = Path(__file__).resolve().parent / 'viewer'
        self._write('assets/hit-data.js', 'window.HIT_DATA=' + json.dumps(data, separators=(',', ':')) + ';\n')
        for f in ('hit_analysis.js', 'defenses.js', 'fire_tool.js'):
            self._write('assets/' + f, (viewer / f).read_text(encoding='utf-8'))
        scripts = lambda f: f'<script src="../assets/hit-data.js"></script><script src="../assets/{f}"></script>'
        body = ('<p>Where a ship can be hurt and from which direction, with every gun and ammo. Built from each ship\'s real hull hitbox and the game\'s own '
                'table of hull surface directions: a pointed bow, curved shoulders, flat sides and a wide flat stern.</p><div id="ha"></div>' + scripts('hit_analysis.js') +
                '<script>HitAnalysis.mount(document.getElementById("ha"),{ship:new URLSearchParams(location.search).get("ship")})</script>'
                '<h2>How hits work</h2><ul><li>The game tests the ball\'s path against invisible boxes, not the visible model: the hull box first, then the '
                'masts, then up to three sails (each sail slows the ball).</li><li>Where the path crosses the hull box decides the zone: <b style="color:#2e9650">bow</b> is only the '
                'middle of the front face; <b style="color:#d23737">stern</b> is the whole back face plus the last ~11% of each side; everything else is <b style="color:#e18c28">side</b>.</li>'
                '<li>Hitting at an angle makes the armor count thicker. Past a certain angle a ball does nothing: a glancing blow.</li>'
                '<li>Height on the hull box makes no difference.</li><li>A stern hit, a mortar or a keg sinks a ship that is already sinking.</li></ul>'
                '<p>See also <a href="../wiki/damage-formula.html">Damage formula</a>, <a href="defenses.html">Towers, forts &amp; mortars</a>, <a href="hitboxes.html">Hitbox viewer</a>.</p>')
        self._write('tools/hit-analysis.html', _page('Hit analysis', body, depth=1, crumbs=crumbs, tab='Tool'))
        body = ('<p>Port-battle towers and forts, their reach and strength, and how mortars and the keg launcher spread their damage.</p><div id="df"></div>' +
                scripts('defenses.js') + '<script>Defenses.mount(document.getElementById("df"))</script>'
                '<h2>Capturing and storming</h2><ul><li>Stay within <b>30</b> of a tower for <b>30 s</b> to capture it (at most half the towers can be captured).</li>'
                '<li>Boarding the guild fort takes <b>25 s</b>. Towers start attacking 15 s after you come into range.</li>'
                '<li>Each destroyed tower adds <b>10 minutes</b> to the battle (up to 90). Ships respawn instantly from the team\'s respawn pool.</li></ul>'
                '<p>See also <a href="../guide/port-battle-rules.html">Port battle rules</a> and the <a href="battle-simulator.html?preset=pbfleet">port battle simulator</a>.</p>')
        self._write('tools/defenses.html', _page('Towers, forts & mortars', body, depth=1, crumbs=crumbs, tab='Tool'))
        body = ('<p>How minor fires turn into a large fire on your ship, and what changes the odds. These are the game\'s own rules; the chance per hit to start a fire is '
                'decided on the game\'s servers, so it is an estimate you can adjust.</p><img class="infographic" src="../assets/fire-infographic.png" alt="Fire mechanics infographic" loading="lazy">'
                '<div id="ft"></div>' + scripts('fire_tool.js') + '<script>FireTool.mount(document.getElementById("ft"))</script>'
                '<p>Full explanation: <a href="../wiki/large-and-minor-fires.html">Large and minor fires</a>.</p>')
        self._write('tools/fire-calculator.html', _page('Fire calculator', body, depth=1, crumbs=crumbs, tab='Tool'))
        self._ship_viewer(hitboxes, crumbs)
        info = viewer / 'fire_infographic.png'
        if info.is_file():
            dst = self.out / 'assets' / 'fire-infographic.png'; dst.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(info, dst)

    def _ship_viewer(self, hitboxes, crumbs):
        """3D ship viewer: model pack + hitboxes + heatmap + firing + in-game designs."""
        import battle_sim
        d = battle_sim.catalog_data(self.db, build=self.build)
        ref = next((hitboxes.get(s_['model'], {}).get('half') for s_ in d['ships'] if str(s_.get('sid')) == '4' and s_.get('model')), None)
        ships = []
        for s_ in d['ships']:
            hb = hitboxes.get(s_.get('model')) or {}
            ships.append({'n': s_['n'], 'model': s_.get('model'), 'zones': hb.get('zones') or [], 'fig': hb.get('fig'), 'half': hb.get('half'), 'sailmap': hb.get('sailmap') or {},
                          'armor': s_['armor'], 'hp': s_['hp'], 'rank': s_['rank']})
        try:
            designs = battle_sim.design_catalog(self.db, self.build)
        except Exception:
            designs = {}
        data = {'ships': sorted(ships, key=lambda x: x['n']), 'designs': designs, 'refHalf': ref or 8, 'pack': '../pack/'}
        self._write('assets/ship-view.js', 'window.SHIP_VIEW=' + json.dumps(data, separators=(',', ':')) + ';\n')
        self._write('assets/ship_viewer.js', (Path(__file__).resolve().parent / 'viewer' / 'ship_viewer.js').read_text(encoding='utf-8'))
        body = ('<p>Every ship\'s real model with the game\'s invisible hitboxes. Paint the hull with the damage or impact angle from any direction, '
                'fire a ball at any spot (click the ship), and try the in-game skins, sails, emblems, flags and figureheads. Drag to turn, '
                'right-drag or Shift-drag to move, scroll to zoom.</p><div id="sv"></div>'
                '<script src="../assets/hit-data.js"></script><script src="../assets/hit_analysis.js"></script><script src="../assets/ship-view.js"></script>'
                '<script src="../assets/ship_viewer.js"></script><script>ShipViewer.mount(document.getElementById("sv"),{ship:new URLSearchParams(location.search).get("ship")})</script>'
                '<h2>Reading it</h2><ul><li>The blue box is the hull hitbox; it decides every hull hit and also the ship\'s collisions. Brown boxes are masts, orange ones sails.</li>'
                '<li>Coloured hull: what a ball fired from the chosen direction does where it lands. Dark blue = it glances off; grey = that side faces away.</li>'
                '<li>Zones come from where the ball crosses the hull box: bow is only the middle of the front face, stern is the whole back face plus the last ~11% of each side.</li>'
                '<li>Sails and masts are tested separately; a ball can pass through up to three sails.</li></ul>'
                '<p>See also <a href="hit-analysis.html">Hit analysis</a> and <a href="../wiki/damage-formula.html">Damage formula</a>.</p>')
        self._write('tools/ship-viewer.html', _page('3D ship viewer', body, depth=1, crumbs=crumbs, tab='Tool'))

    def _cannon_vs_ships(self, rec):
        """What this gun can hurt: per-ship damage per ball square on the side, raking the stern, and the glancing limit."""
        d = getattr(self, '_hd', None)
        if not d:
            return []
        gun = next((c for c in d['cannons'] if c['n'] == rec.get('_title')), None)
        if not gun:
            return []
        cal = d['calib']; w = cal.get('armor_weight') or 1; sc = cal.get('scale') or 1
        ball = next((a for a in d['ammo'] if 'cast-iron' in (a['n'] or '').lower()), {'pen': 0, 'df': 1, 'min': 0})
        pen = (gun['pen'] or 0) + (ball.get('pen') or 0)
        rows, top = [], 1
        for sh in sorted((x for x in d['ships'] if x['hp']), key=lambda x: -(x['armor'] or 0)):
            arm = sh['armor'] or 0
            if gun['mortar']:
                side = stern = max(0, pen - w * arm) * sc; lim = None
            else:
                side = max(ball.get('min') or 0, pen - w * arm) * (ball.get('df') or 1) * sc
                stern = max(ball.get('min') or 0, pen - w * arm * 0.5) * (ball.get('df') or 1) * sc
                lim = math.degrees(math.acos(min(1, w * arm / pen))) if pen > w * arm else 0
            top = max(top, side, stern); rows.append((sh, arm, side, stern, lim))
        def link(n):
            u = self.urls.get(('ship', n.casefold()))
            return f'<a href="../{u}">{_e(n)}</a>' if u else _e(n)
        trs = ''.join(f'<tr><td>{link(sh["n"])}</td><td>{arm:.1f}</td>' + _bar(side, top, fmt='{:.1f}') +
                      ('' if gun['mortar'] else _bar(stern, top, fmt='{:.1f}', cls='warm') + f'<td>{"none" if not lim else f"{lim:.0f}°"}</td>') +
                      f'<td><a href="../tools/hit-analysis.html?ship={_e(sh["n"])}">map</a></td></tr>' for sh, arm, side, stern, lim in rows)
        head = ('<th>Ship</th><th>Armor</th><th>Direct hit</th><th></th>' if gun['mortar'] else
                '<th>Ship</th><th>Armor</th><th>Side, square on</th><th>Stern rake</th><th>Glancing limit</th><th></th>')
        intro = ('Damage at the centre of the burst against every ship (it falls off toward the edge of the splash; see <a href="../tools/defenses.html">Towers, forts &amp; mortars</a>).'
                 if gun['mortar'] else 'Damage per cast-iron ball against every ship, strongest armor first. "Glancing limit" is how far off square a side hit can be and still do damage.')
        return [f'<h2>What it can damage</h2><p>{intro} Estimates until calibrated.</p>'
                '<input class="tfilter" type="search" placeholder="Filter ships…" oninput="wikiFilter(this)">'
                f'<table class="wikitable sortable"><thead><tr>{head}</tr></thead><tbody>{trs}</tbody></table>']

    def _sim_tools(self):
        """Battle and boarding simulators: full-screen pages sharing assets/wosb_sim.js (no meshes published)."""
        import battle_sim
        back = ('<a href="../index.html" style="position:fixed;left:10px;top:64px;z-index:5;color:#8fd3ff;'
                'font:12px Segoe UI,sans-serif;background:rgba(8,19,31,.8);padding:3px 8px;border-radius:4px">← Wiki</a>')
        pack = {}
        if self.model_pack and self.recovery_dir:
            try:   # lighter LOD and 512 px textures for the public site; rebuilt only for models that changed
                pack = battle_sim.build_model_pack(self.db, self.out / 'pack', recovery_dir=self.recovery_dir, game_roots=self.game_roots,
                                                   lod='low', tex_size=512, build=self.build, progress=self.progress, designs=True)
            except Exception:
                pack = {}
        self.pack_info = pack
        try:
            battle_sim.build_page(self.db, self.out / 'tools' / 'battle-simulator.html', hitboxes_dir=self.hitboxes_dir,
                                  forts_root=self.recovery_dir, include_models=False, inline_lib=False, build=self.build,
                                  pack_base='../pack/' if pack.get('models') else None, damage_calibration=self.damage_calibration)
            battle_sim.build_boarding_page(self.db, self.out / 'tools' / 'boarding-simulator.html', inline_lib=False, build=self.build)
            self.pages += 2
            for name in ('battle-simulator.html', 'boarding-simulator.html'):
                f = self.out / 'tools' / name
                html = f.read_text(encoding='utf-8')
                html = html.replace('<body>', '<body>' + (back if 'battle' in name else back.replace('left:10px;top:64px', 'right:12px;top:8px')), 1)
                f.write_text(html, encoding='utf-8')
        except Exception as exc:  # a missing dataset should not break the site
            self._write('tools/battle-simulator.html', _page('Battle simulator', f'<p class="note">Not available in this build ({_e(type(exc).__name__)}).</p>', depth=1))


HITBOX_JS = r'''
(function(){
function draw(cv,zones){const ctx=cv.getContext('2d');let yaw=-0.7,pitch=0.35,zoom=1,drag=null;
 const all=zones.flatMap(z=>[z.b.min,z.b.max]);const c=[0,1,2].map(i=>(Math.min(...all.map(p=>p[i]))+Math.max(...all.map(p=>p[i])))/2);
 const span=Math.max(...[0,1,2].map(i=>Math.max(...all.map(p=>p[i]))-Math.min(...all.map(p=>p[i]))));
 function proj(p){let x=p[0]-c[0],y=p[1]-c[1],z=p[2]-c[2];const cy=Math.cos(yaw),sy=Math.sin(yaw);[x,z]=[x*cy-z*sy,x*sy+z*cy];
  const cp=Math.cos(pitch),sp=Math.sin(pitch);[y,z]=[y*cp-z*sp,y*sp+z*cp];const s=zoom*cv.height*0.9/span;return [cv.width/2+x*s,cv.height/2-y*s,z]}
 const E=[[0,1],[1,3],[3,2],[2,0],[4,5],[5,7],[7,6],[6,4],[0,4],[1,5],[2,6],[3,7]];
 function render(){ctx.clearRect(0,0,cv.width,cv.height);const items=zones.map(z=>{const mn=z.b.min,mx=z.b.max;
   const v=[];for(const X of [mn[0],mx[0]])for(const Y of [mn[1],mx[1]])for(const Z of [mn[2],mx[2]])v.push(proj([X,Y,Z]));
   return {z,v,d:v.reduce((a,p)=>a+p[2],0)/8}}).sort((a,b)=>a.d-b.d);
  for(const it of items){const t=it.z.t;ctx.strokeStyle=t==='hull'?'#1f6fb2':t==='mast'?'#7a4b1d':'rgba(230,120,20,'+(0.35+Math.min(0.6,(it.z.w||0)*6))+')';
   ctx.lineWidth=t==='hull'?2:1;ctx.beginPath();for(const [a,b] of E){ctx.moveTo(it.v[a][0],it.v[a][1]);ctx.lineTo(it.v[b][0],it.v[b][1])}ctx.stroke()}}
 cv.onmousedown=e=>drag=[e.clientX,e.clientY,yaw,pitch];window.addEventListener('mouseup',()=>drag=null);
 cv.onmousemove=e=>{if(!drag)return;yaw=drag[2]+(e.clientX-drag[0])/200;pitch=Math.max(-1.4,Math.min(1.4,drag[3]+(e.clientY-drag[1])/200));render()};
 cv.onwheel=e=>{e.preventDefault();zoom*=e.deltaY<0?1.1:0.9;render()};render();return render}
document.querySelectorAll('canvas.hitbox[data-zones]').forEach(cv=>draw(cv,JSON.parse(cv.dataset.zones)));
const sel=document.getElementById('hbship'),cv=document.getElementById('hbcanvas');
if(sel&&cv&&window.HITBOXES){const go=()=>draw(cv,window.HITBOXES[sel.value]);sel.onchange=go;go()}
})();
'''

DAMAGE_TOOL = r'''
<p>Applies hits to a ship using the game's rules for HP, sinking, sails, fire and flooding. Enter how much each hit does;
exact cannonball damage is decided by the game server, so use values you have measured (see <a href="../wiki/damage-formula-calibration.html">calibration</a>).</p>
<div class="tool"><label>Ship <select id="ship"></select></label><label>Max HP <input id="hp" type="number" value="5000" style="width:90px"></label>
<label>Sails <input id="sails" type="number" value="6" min="1" style="width:60px"></label></div>
<div class="tool"><b>Hits</b> (one per line: <code>type damage</code> plus optional words: <code>stern</code>, <code>sail=N amount</code>, <code>allsails amount</code>, <code>fire</code>, <code>breach</code>)<br>
Types: cannonball, mortar, keg, ram, fire, other<textarea id="hits" rows="7">cannonball 1800
cannonball 1800
cannonball 1500 sail=2 0.25
ram 100
mortar 50</textarea><button id="run">Simulate</button></div>
<div id="out"></div>
<script>
const SHIPS=__SHIPS__;const sel=document.getElementById('ship');sel.innerHTML='<option value="">(custom)</option>'+SHIPS.map((s,i)=>'<option value="'+i+'">'+s.n.replace(/</g,'&lt;')+'</option>').join('');
const q=new URLSearchParams(location.search);if(q.get('hp'))document.getElementById('hp').value=q.get('hp');
sel.onchange=()=>{if(sel.value!=='')document.getElementById('hp').value=SHIPS[sel.value].hp};
function sim(){const max=+document.getElementById('hp').value||1,n=Math.max(1,+document.getElementById('sails').value||1);
 let hp=max,sinkMs=0,offset=0,destroyed=false,sails=Array(n).fill(1),w=Array(n).fill(1/n),fire=false;const rows=[];
 const ff=()=>(sinkMs-offset)/13000;
 for(const raw of document.getElementById('hits').value.split('\n')){const p=raw.trim().split(/\s+/);if(!p[0])continue;
  const type=p[0].toLowerCase(),dmg=parseFloat(p[1])||0;const before=hp,ev=[];if(destroyed){rows.push([raw,before,hp,'already sunk']);continue}
  if(sinkMs===0){const rm=Math.min(dmg,hp);hp=(hp-rm<0.5)?0:hp-rm;if(hp<=0){sinkMs=0.01;hp=1;ev.push('starts sinking (13 s)')}}
  if(ff()>0&&ev.length===0||ff()>0&&type!=='cannonball'){
   if(type==='mortar'||type==='keg'||(type==='fire'&&fire)||p.includes('stern')){destroyed=true;hp=0;ev.push('sunk instantly')}
   else if(type==='ram'){const nw=Math.min(12999,sinkMs+800);offset=nw-sinkMs;sinkMs=nw;ev.push('ram: sinking +0.8 s')}}
  for(let i=2;i<p.length;i++){const t=p[i];if(t.startsWith('sail=')){const k=Math.min(n,Math.max(1,parseInt(t.slice(5))))-1,a=parseFloat(p[i+1])||0;sails[k]=Math.max(0,sails[k]-a/(w[k]*n));ev.push('sail '+(k+1)+' hit');i++}
   else if(t==='allsails'){const a=parseFloat(p[i+1])||0;for(let k=0;k<n;k++)sails[k]=Math.max(0,sails[k]-a/(w[k]*n));ev.push('all sails hit');i++}
   else if(t==='fire'){fire=true;ev.push('large fire')}else if(t==='breach')ev.push('hull breach')}
  rows.push([raw,before,hp,ev.join('; ')])}
 const sailHp=sails.reduce((a,s,i)=>a+s*w[i],0);
 const bar=v=>'<span class="barwrap"><span class="bar" style="width:'+Math.round(160*Math.max(0,v))+'px"></span></span>';
 document.getElementById('out').innerHTML='<table class="wikitable"><tr><th>Hit</th><th>HP before</th><th>HP after</th><th>Hull</th><th>Events</th></tr>'+
  rows.map(r=>'<tr><td>'+r[0].replace(/</g,'&lt;')+'</td><td>'+r[1].toFixed(0)+'</td><td>'+r[2].toFixed(0)+'</td><td>'+bar(r[2]/max)+'</td><td>'+r[3]+'</td></tr>').join('')+
  '</table><p><b>Result:</b> '+(destroyed?'sunk':(sinkMs>0?'sinking':'afloat'))+' · sails '+(sailHp*100).toFixed(1)+'%'+(sailHp<0.95?' (maneuverability reduced)':'')+'</p>'}
document.getElementById('run').onclick=sim;sim();
</script>
<h2>Rules used</h2><ul><li>Below 0.5 HP the ship is at zero and begins a 13-second sinking timeline (HP held at 1; further hits do no HP damage).</li>
<li>While sinking: mortars, powder kegs, fire during a large fire and stern hits sink the ship instantly; a ram pushes the timeline 0.8 s.</li>
<li>Sail damage is divided by the sail's share of total sail size; this tool assumes equal sails.</li></ul>
'''

WIND_TOOL = r'''
<p>How much of the wind a ship can use at each heading: the game's wind-effectiveness rule, with the regular or the
<b>unique</b> wind rose, and the ship's <b>hardness</b> (heavy ships lose less speed at poor angles). See <a href="../wiki/sailing-and-wind.html">Sailing and wind</a>.</p>
<div class="tool"><label>Ship <select id="wship"><option value="">(custom)</option></select></label>
<label><input type="checkbox" id="uniq"> unique wind rose</label>
<label>Hardness <input id="hard" type="range" min="0" max="1" step="0.01" value="0"> <span id="hardv"></span></label>
<label>Angle off the wind <input id="ang" type="range" min="0" max="180" value="45"> <span id="angv"></span>° (0 = wind behind)</label>
<div id="readout"></div></div><canvas id="polar" width="560" height="560"></canvas>
<script src="../assets/wosb_sim.js"></script>
<script>
const ROSES=__ROSES__;const SHIPS=__SHIPS__;const S=window.WoSBSim;const sel=document.getElementById('wship');
sel.innerHTML+=SHIPS.filter(s=>s.weight).map((s,i)=>'<option value="'+SHIPS.indexOf(s)+'">'+s.n.replace(/</g,'&lt;')+'</option>').join('');
sel.onchange=()=>{const s=SHIPS[sel.value];if(!s)return;const h=S.hull(s.weight,s.sid);document.getElementById('hard').value=h.hardness.toFixed(2);document.getElementById('uniq').checked=S.UNIQUE_IDS.has(s.sid);draw()};
function eff(a,tack){return S.windEff(a,{unique:document.getElementById('uniq').checked,hardness:+document.getElementById('hard').value,tack})}
function draw(){const cv=document.getElementById('polar'),c=cv.getContext('2d'),R=250,cx=280,cy=280;c.clearRect(0,0,560,560);
 c.strokeStyle='#ccc';c.fillStyle='#666';c.font='11px sans-serif';for(let k=1;k<=4;k++){c.beginPath();c.arc(cx,cy,R*k/4,0,7);c.stroke();c.fillText((k*25)+'%',cx+3,cy-R*k/4+12)}
 // 0° (wind behind) at the top, starboard tack on the right, port tack on the left
 const plot=(tack,col,side)=>{c.strokeStyle=col;c.lineWidth=2.5;c.beginPath();for(let a=0;a<=180;a+=1){const v=eff(a,tack),t=(side*a-90)*Math.PI/180;const x=cx+Math.cos(t)*R*v,y=cy+Math.sin(t)*R*v;a?c.lineTo(x,y):c.moveTo(x,y)}c.stroke()};
 plot('right','#1d4e6f',1);plot('left',document.getElementById('uniq').checked?'#c0392b':'#1d4e6f',-1);c.lineWidth=1;
 const ang=+document.getElementById('ang').value;document.getElementById('angv').textContent=ang;document.getElementById('hardv').textContent=(+document.getElementById('hard').value).toFixed(2);
 for(const [tack,side] of [['right',1],['left',-1]]){const v=eff(ang,tack),t=(side*ang-90)*Math.PI/180;c.fillStyle='#d33';c.beginPath();c.arc(cx+Math.cos(t)*R*v,cy+Math.sin(t)*R*v,5,0,7);c.fill()}
 c.fillStyle='#333';c.fillText('0° · wind behind',cx-40,14);c.fillText('180° · into the wind',cx-52,552);c.fillText('port tack',18,cy);c.fillText('starboard tack',470,cy);
 const r=eff(ang,'right'),l=eff(ang,'left');
 document.getElementById('readout').innerHTML='At '+ang+'° off the wind: <b>'+(r*100).toFixed(1)+'%</b> of top speed'+(Math.abs(r-l)>0.001?' on the starboard tack, <b>'+(l*100).toFixed(1)+'%</b> on the port tack (unique rose)':'')}
for(const id of ['uniq','hard','ang'])document.getElementById(id).oninput=draw;draw();
</script>
<p class="note">Wind effectiveness multiplies the ship's base speed; sail damage and upgrades also apply. The unique rose rotates one tack by about 17° when beating upwind and narrows the downwind penalty.</p>
'''

COMPARE_TOOL = r'''
<p>Pick up to four ships to compare side by side. Bars are scaled to the best ship in the comparison.</p>
<div class="tool" id="pick"></div><div id="cmp"></div>
<script>
const SHIPS=__SHIPS__;const pick=document.getElementById('pick');
pick.innerHTML=[0,1,2,3].map(i=>'<label>Ship '+(i+1)+' <select data-i="'+i+'"><option value="">-</option>'+SHIPS.map((s,k)=>'<option value="'+k+'">'+s.n.replace(/</g,'&lt;')+'</option>').join('')+'</select></label>').join('');
const F=[['hp','Hull HP'],['armor','Armor'],['speed','Speed'],['mob','Mobility'],['crew','Crew'],['cargo','Cargo'],['rank','Rank']];
function render(){const chosen=[...pick.querySelectorAll('select')].map(s=>s.value).filter(v=>v!=='').map(v=>SHIPS[v]);if(!chosen.length){document.getElementById('cmp').innerHTML='';return}
 let h='<table class="wikitable"><tr><th>Stat</th>'+chosen.map(s=>'<th>'+s.n.replace(/</g,'&lt;')+'</th>').join('')+'</tr>';
 for(const [k,l] of F){const mx=Math.max(...chosen.map(s=>+s[k]||0))||1;h+='<tr><th>'+l+'</th>'+chosen.map(s=>'<td><span class="barwrap" style="width:90px"><span class="bar" style="background:#1d4e6f;width:'+Math.round(90*(+s[k]||0)/mx)+'px"></span></span>'+(s[k]??'')+'</td>').join('')+'</tr>'}
 document.getElementById('cmp').innerHTML=h+'</table>'}
pick.addEventListener('change',render);
</script>
'''


def _version_assets(out):
    """Add ?v=<content hash> to every page's links to assets/*.css and *.js, so a new publish is never mixed with the
    browser's saved copy of an older stylesheet or script."""
    import hashlib
    out = Path(out); ver = {}
    for f in (out / 'assets').rglob('*'):
        if f.is_file() and f.suffix in ('.css', '.js'):
            ver[f.relative_to(out / 'assets').as_posix()] = hashlib.sha1(f.read_bytes()).hexdigest()[:10]
    rx = re.compile(r'((?:src|href)="(?:\.\./)*assets/)([^"?#]+\.(?:css|js))"')
    n = 0
    for f in out.rglob('*.html'):
        if f.relative_to(out).parts[0] == 'pack':
            continue
        s = f.read_text(encoding='utf-8')
        t = rx.sub(lambda m: f'{m.group(1)}{m.group(2)}?v={ver[m.group(2)]}"' if m.group(2) in ver else m.group(0), s)
        if t != s:
            f.write_text(t, encoding='utf-8'); n += 1
    return n


def build_site(db, out, **kw):
    return SiteBuilder(db, out, **kw).build_site()


# ---------------------------------------------------------------- data overview pages
def fx_label(token):
    """'PReduceFireAreaDamage +25' -> ('Reduce fire area damage', '+25%');  B-flags -> ('…', 'yes')."""
    m = re.match(r'\s*([PMBC](?=[A-Z]))([A-Za-z]+)\s*(.*)$', token or '')
    if not m:
        return (token or '').strip(), ''
    kind, name, val = m.groups()
    words = re.sub(r'(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])', ' ', name).lower().replace('cballs', 'cannonballs').replace('sailes', 'sails')
    words = words[:1].upper() + words[1:]
    val = val.strip()
    if kind == 'B':
        return words, 'yes'
    if ',' in val:
        vals = [v.strip() for v in val.split(',') if v.strip()]
        val = (vals[0] + ' … ' + vals[-1] + ' by rank') if len(set(vals)) > 1 else vals[0]
    return words, (val + '%' if kind == 'P' and val else val)


def _bar(value, top, *, fmt='{:,.0f}', cls=''):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return '<td></td>'
    w = max(0.0, min(100.0, 100.0 * v / top)) if top else 0
    return f'<td><div class="vbar {cls}"><i style="width:{w:.0f}%"></i><b>{fmt.format(v)}</b></div></td>'


CANNON_CLASS_TEXT = {
    'LiteCannon': ('Cannons', 'All-round broadside guns: balanced range, penetration and reload.'),
    'HeavyCannon': ('Carronades', 'Short-range, heavy-hitting guns: high penetration, short reach.'),
    'DistanceCannon': ('Long guns', 'Long-range guns: more reach, usually less penetration per ball.'),
    'Bombardier': ('Bow & stern guns', 'Chase guns fitted at the bow or stern, including special multi-shot weapons.'),
    'Mortar': ('Mortars', 'Indirect fire with splash damage, long reload, and a minimum range.'),
    'Special': ('Special weapons', 'Unique weapons with their own firing rules.'),
}


class _Overviews:
    """Readable, data-first pages built from the catalog (ranks, guns, upgrades, port battles)."""

    def __init__(self, site):
        import battle_sim
        self.site = site
        self.d = battle_sim.catalog_data(site.db, build=site.build)

    def link(self, kind, name):
        url = self.site.urls.get((kind, str(name).casefold()))
        return f'<a href="../{url}">{_e(name)}</a>' if url else _e(name)

    def pages(self):
        out = []
        for slug, title, blurb, fn in (
                ('ships-by-rank', 'Ships by rank', 'Every ship side by side within its rank: hull, armor, speed and turning.', self.ships_by_rank),
                ('cannons-compared', 'Cannons compared', 'Penetration, damage per ball and per minute, range and reload, grouped by gun type.', self.cannons),
                ('upgrades-by-effect', 'Upgrades by effect', 'What each ship upgrade actually changes, grouped by slot and by effect.', self.upgrades),
                ('port-battle-rules', 'Port battle rules', 'Tower and fort HP, battle clock, respawn points, capture rules in tables.', self.port_battles)):
            try:
                body = fn()
            except Exception:
                continue
            if body:
                out.append((slug, title, blurb, body))
        return out

    def ships_by_rank(self):
        ships = [s for s in self.d['ships'] if s.get('hp')]
        if not ships:
            return ''
        top = {k: max(s[k] or 0 for s in ships) for k in ('hp', 'armor', 'speed', 'mob')}
        html = ['<div class="keyfacts">Rank 1 is the largest class. Bars compare each value with the best ship in the game. '
                'Click a column heading to sort.</div>']
        summ = []
        for rank in sorted({s['rank'] for s in ships if s['rank']}):
            grp = [s for s in ships if s['rank'] == rank]
            avg = lambda k: sum(s[k] or 0 for s in grp) / len(grp)
            summ.append(f'<tr><td><a href="#rank-{rank}">Rank {rank}</a></td><td>{len(grp)}</td>' + _bar(avg('hp'), top['hp']) +
                        _bar(avg('armor'), top['armor'], fmt='{:.1f}', cls='warm') + _bar(avg('speed'), top['speed'], fmt='{:.1f}', cls='green') + _bar(avg('mob'), top['mob']) + '</tr>')
        html.append('<h2>Average by rank</h2><table class="wikitable"><tr><th>Rank</th><th>Ships</th><th>HP</th><th>Armor</th><th>Speed</th><th>Turn (°/10 s)</th></tr>' + ''.join(summ) + '</table>')
        for rank in sorted({s['rank'] for s in ships if s['rank']}):
            rows = []
            for s in sorted((s for s in ships if s['rank'] == rank), key=lambda s: -(s['hp'] or 0)):
                rows.append(f'<tr><td>{self.link("ship", s["n"])}</td><td>{_e(_camel(s["cls"] or ""))}</td>' + _bar(s['hp'], top['hp']) +
                            _bar(s['armor'], top['armor'], fmt='{:.1f}', cls='warm') + _bar(s['speed'], top['speed'], fmt='{:.1f}', cls='green') +
                            _bar(s['mob'], top['mob']) + f'<td>{_e(int(s["crew"] or 0))}</td><td>{_e(s["places"] or "")}</td></tr>')
            html.append(f'<h2 id="rank-{rank}">Rank {rank}</h2><table class="wikitable sortable"><tr><th>Ship</th><th>Type</th><th>HP</th><th>Armor</th>'
                        f'<th>Speed</th><th>Turn</th><th>Crew</th><th>Crew places</th></tr>' + ''.join(rows) + '</table>')
        return ''.join(html)

    def cannons(self):
        guns = [c for c in self.d['cannons'] if c.get('pen')]
        if not guns:
            return ''
        ball = next((a for a in self.d['ammo'] if re.search('cast-iron', a['n'], re.I)), {'pen': 0, 'df': 1})
        per = lambda c, arm=0: max(0.0, (c['pen'] + (ball.get('pen') or 0) - 2.1 - arm) * (ball.get('df') or 1))
        dpm = lambda c: max(0.0, (c['pen'] - 2) * 60 / c['reload']) if c.get('reload') else 0
        top = {'pen': max(c['pen'] for c in guns if not c.get('mortar')), 'max': max(c['max'] or 0 for c in guns),
               'dpm': max(dpm(c) for c in guns if not c.get('mortar')), 'per': max(per(c) for c in guns if not c.get('mortar'))}
        html = ['<div class="keyfacts">Damage per ball is the in-game figure with cast-iron shot: (penetration − 2.1) × ammo factor, before the target\'s armor. '
                'Against armor A, subtract A (more at an angle). Per minute = (penetration − 2) × 60 ÷ reload, per gun. '
                'Try them on real ships in the <a href="../tools/battle-simulator.html">battle simulator</a>.</div>']
        for cls in ['LiteCannon', 'HeavyCannon', 'DistanceCannon', 'Bombardier', 'Special', 'Mortar']:
            grp = [c for c in guns if c['cls'] == cls]
            if not grp:
                continue
            name, text = CANNON_CLASS_TEXT.get(cls, (_camel(cls), ''))
            rows = []
            for c in sorted(grp, key=lambda c: (c['pen'] or 0)):
                feat = '' if c.get('feature') in (None, '', 'Default') else _camel(c['feature'])
                if c.get('mortar'):
                    rows.append(f'<tr><td>{self.link("cannon", c["n"])}</td><td>{c["pen"]:.0f}</td><td>{c.get("splash") or ""}</td><td>{(c.get("min") or 0):.0f}–{(c["max"] or 0):.0f}</td><td>{c["reload"]:.0f} s</td><td>{_e(feat)}</td></tr>')
                else:
                    rows.append(f'<tr><td>{self.link("cannon", c["n"])}</td>' + _bar(c['pen'], top['pen'], fmt='{:.1f}', cls='warm') + _bar(per(c), top['per'], fmt='{:.1f}') +
                                _bar(per(c, 6), top['per'], fmt='{:.1f}') + _bar(dpm(c), top['dpm'], fmt='{:.0f}', cls='green') + _bar(c['max'], top['max']) +
                                f'<td>{c["reload"]:.1f} s</td><td>±{c.get("angle") or 0:.0f}°</td><td>{_e(feat)}</td></tr>')
            head = ('<tr><th>Mortar</th><th>Damage</th><th>Splash</th><th>Range</th><th>Reload</th><th>Feature</th></tr>' if cls == 'Mortar' else
                    '<tr><th>Gun</th><th>Penetration</th><th>Dmg / ball</th><th>vs armor 6</th><th>Per minute</th><th>Range</th><th>Reload</th><th>Arc</th><th>Feature</th></tr>')
            html.append(f'<h2>{_e(name)}</h2><p>{_e(text)}</p><table class="wikitable sortable">{head}{"".join(rows)}</table>')
        return ''.join(html)

    def upgrades(self):
        ups = [u for u in self.d['upgrades'] if u.get('fx')]
        if not ups:
            return ''
        by_slot = defaultdict(list); by_fx = defaultdict(list)
        for u in ups:
            effects = [fx_label(t) for t in re.split(r';', u['fx']) if t.strip()]
            by_slot[_camel(u.get('slot') or 'Other').replace('Sailes', 'Sails')].append((u['n'], effects))
            for lab, val in effects:
                by_fx[lab].append((u['n'], val))
        html = ['<div class="keyfacts">Percent effects add together across upgrades, crew, skills and items; flat effects add directly. '
                'Effects listed "by rank" scale with the ship\'s rank.</div><h2>By slot</h2>']
        for slot in sorted(by_slot):
            rows = ''.join(f'<tr><td>{self.link("upgrade", n)}</td><td>' + '<br>'.join(f'{_e(l)} <b>{_e(v)}</b>' for l, v in eff) + '</td></tr>' for n, eff in sorted(by_slot[slot]))
            html.append(f'<h3>{_e(slot)}</h3><table class="wikitable"><tr><th>Upgrade</th><th>Effects</th></tr>{rows}</table>')
        html.append('<h2>By effect</h2><table class="wikitable sortable"><tr><th>Effect</th><th>Upgrades</th></tr>' + ''.join(
            f'<tr><td>{_e(lab)}</td><td>' + ', '.join(f'{self.link("upgrade", n)} ({_e(v)})' for n, v in sorted(items)) + '</td></tr>'
            for lab, items in sorted(by_fx.items())) + '</table>')
        return ''.join(html)

    def port_battles(self):
        base = {1: (12100, 26400), 2: (10000, 21700), 3: (9100, 20000), 4: (7700, 16700), 5: (6600, 14500), 6: (4500, 10000)}
        teams = [(40, 1.15), (20, 1.0), (15, 0.85), (10, 0.7), (7, 0.6), (5, 0.5)]
        lvl = [1, 1, 1.04, 1.08, 1.12, 1.16, 1.2, 1.24]
        rnd = lambda v: int(round(v / 100) * 100)
        t1 = ''.join(f'<tr><td>Rank {r}+</td>' + ''.join(f'<td>{rnd(t * base[r][0]):,} / {rnd(t * base[r][1]):,}</td>' for _, t in teams) + '</tr>' for r in sorted(base))
        cost = lambda r, cls: ({5: 3, 4: 4, 3: 5, 2: 6, 1: 7}.get(r, 2) + ((1 if r >= 4 else 2) if cls == 'Hardship' else 0) + (1 if cls == 'Battleship' else 0))
        t3 = ''.join(f'<tr><td>Rank {r}</td>' + ''.join(f'<td>{cost(r, c)}</td>' for c in ('CargoShip', 'Destroyer', 'Battleship', 'Hardship')) + '</tr>' for r in range(1, 8))
        return ('<div class="keyfacts">These are the game\'s port-battle rules. See them play out in the '
                '<a href="../tools/battle-simulator.html?preset=pbfleet">battle simulator</a>, or pick a site on the <a href="../map.html">world map</a>.</div>'
                '<h2>Tower and fort HP (city level 1)</h2><p>Tower / fort strength by the shallows rank limit and the team limit.</p>'
                '<table class="wikitable"><tr><th>Ships allowed</th>' + ''.join(f'<th>{n} v {n}</th>' for n, _ in teams) + '</tr>' + t1 + '</table>'
                '<p>Higher city levels multiply this: ' + ', '.join(f'level {i} ×{lvl[i]:.2f}' for i in range(2, 8)) + '.</p>'
                '<h2>Battle clock</h2><table class="wikitable"><tr><th>Event</th><th>Effect</th></tr>'
                '<tr><td>Start</td><td>25 minutes</td></tr><tr><td>Tower destroyed</td><td>+10 minutes</td></tr>'
                '<tr><td>Ship sunk</td><td>1–2 minutes of extra time</td></tr><tr><td>Maximum</td><td>90 minutes</td></tr></table>'
                '<h2>Respawn points</h2><p>Each side starts with 25 + (team size − 1) × 2.5 × the cost of a cargo ship of the allowed rank; defenders get 85% of that. '
                'Respawns are instant while points last. Each sinking costs:</p><table class="wikitable"><tr><th></th><th>Cargo</th><th>Destroyer</th><th>Battleship</th><th>Heavy</th></tr>' + t3 + '</table>'
                '<h2>Towers and the fort</h2><table class="wikitable"><tr><th>Rule</th><th>Value</th></tr>'
                '<tr><td>Attack timer</td><td>15 s inside a tower\'s range before it can be damaged</td></tr>'
                '<tr><td>Capture a destroyed tower</td><td>stay within 30 for 30 s</td></tr>'
                '<tr><td>Towers you can capture</td><td>at most half of them</td></tr>'
                '<tr><td>Board the fort</td><td>25 s, once the fort is at 0 and no tower stands</td></tr>'
                '<tr><td>Mortar tower</td><td>120 damage every 15 s, 50–190 range</td></tr>'
                '<tr><td>Fire (Prometheus) tower</td><td>30 damage every 0.5 s, ±45°, 14–115 range</td></tr>'
                '<tr><td>Unique ships per team</td><td>1 per 10 players</td></tr></table>')
