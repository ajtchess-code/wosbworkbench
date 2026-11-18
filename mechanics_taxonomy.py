"""Broad, source-aware WoSB wiki ontology. A topic is a research target, not a gameplay claim.

The catalog is intentionally game-mechanics-wide. Combat is one domain among many.
Unrecognized tables remain browsable under the Unclassified sources domain.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Tuple

@dataclass(frozen=True)
class Domain:
    key: str
    title: str
    description: str
    datasets: Tuple[str, ...]
    topics: Tuple[str, ...]

DOMAINS = (
 Domain('getting-started','Getting started & Gamepedia',
  'Introductory systems, interface guidance, progression, reputation and client-authored game encyclopedia.',
  ('Gamepedia','Achievements','RangInfo','Rules_and_Limitations'),
  ('First voyage and onboarding','Controls and interface','Progression and ranks','Reputation and faction systems','Achievements and milestones','Daily and recurring systems')),
 Domain('ships','Ships, hulls & construction',
  'Every playable hull, progression requirement, capacity, building cost, materials, customization and ship statistics.',
  ('ShipsToPlay','ShipsBasics','Ship_Construction','Ship_Materials','ShipUpgradesNew','ShipDesingElements'),
  ('Ship classes and rates','Hull statistics and durability','Ship construction and blueprints','Ship upgrade slots','Ship equipment and modules','Gun ports and loadouts','Ship customization and appearances','Ship progression and unlocks')),
 Domain('sailing','Sailing, weather & navigation',
  'Speed, wind, maneuvering, sail damage, ocean movement, map travel and environmental factors.',
  ('WindRoses','World','WorldPorts','StartMap','ShipDesingElements','Gamepedia'),
  ('Sailing speed calculation','Wind angles and points of sail','Maneuverability and acceleration','Sail condition and repairs','Sea conditions and weather','Navigation and travel','Ship handling modifiers')),
 Domain('weapons','Cannons, projectiles & ballistics',
  'Weapons, cannonballs, ammunition effects, artillery costs and firing parameters.',
  ('Cannons','CannonBalls','Cannon_Crafting','Cannon_Materials','PowderKegs','UnitsInfo'),
  ('Cannon classes and caliber','Ammo types and effects','Reload and rate of fire','Range and accuracy','Penetration and overpenetration','Projectile trajectory and velocity','Crew damage and sail damage','Barrels and powder kegs','Gun construction and production')),
 Domain('damage','Damage, armor & mitigation',
  'Research static damage formulas and validate them against live gameplay observations.',
  ('Cannons','CannonBalls','ShipsToPlay','ShipUpgradesNew','CaptainSkills','GuildBonuses','Gameplay_Methods','Game_Enums'),
  ('Base projectile damage','Hitbox impact and body parts','Armor and effective armor','Damage resistance and reduction','Penetration and deflection','Critical hits and damage bonuses','Sail and mast damage','Crew losses and injury','Damage stacking and order of operations','Repair and regeneration')),
 Domain('status','Fires, flooding & status effects',
  'Fire initiation, microfires, large fires, firespread, flooding, extinguishing and timed effects.',
  ('CannonBalls','PowderKegs','ShipUpgradesNew','CaptainSkills','GuildBonuses','Gameplay_Methods','Game_Enums'),
  ('Microfire ignition','Large-fire escalation thresholds','Large-fire periodic damage','Fire areas and spread','Firefighting and duration','Flooding and leaks','Status stacking and immunities','Status effect cleanup and timers','Server authority versus client prediction')),
 Domain('crew','Crew, officers & boarding',
  'Crew roles, crew capacity, sailors, unique personnel, boarding and combat perks.',
  ('Crew_Sailors','Crew_Special','Crew_Boarding','CaptainSkills','UnitsInfo'),
  ('Crew types and hiring','Crew capacity and assignments','Special crew and officers','Captain skill trees','Boarding and melee','Morale and crew casualties','Crew bonuses and stacking','Crew progression and maintenance')),
 Domain('crafting','Crafting & production chains',
  'Recipes, ingredient graph, processing stages, crafting time, output and cost.',
  ('Crafting_Recipes','Recipe_Ingredients','Resource_Chain_Plans','Resource_Chain_Steps','Resource_Chain_Raw_Totals','Factory_Levels','Resources','Cannon_Crafting','Cannon_Materials','Ship_Construction'),
  ('All crafting recipes','Raw resource acquisition','Intermediate products','Crafting dependency graphs','Production time and throughput','Factory and workshop tiers','Shipbuilding production chains','Cannon and ammunition production','Material costs and total inputs')),
 Domain('resources','Resource gathering, mines & facilities',
  'Nodes, mines, processing facilities, gathering locations, upgrading costs and yield.',
  ('Resources','Mines_and_Nodes_Map_References','Factory_Levels','EnvDesingElements','World','Other_Villages_Map_References'),
  ('Raw resources and rarity','Mine and deposit locations','Mine and node levels','Gathering prerequisites','Workshop and factory upgrades','Production output and efficiency','Resource depletion and respawn')),
 Domain('economy','Economy, markets & trading',
  'Prices, merchant limits, storage, commodities, trade routes and currency systems.',
  ('Market_Price_Limits','TradingRoutesInfo','Resources','Port_Definitions','WorldPorts','GuildBonuses'),
  ('Trading House prices and limits','Trade routes and profitability','Supply and demand','Commodity pricing and currencies','Port storage and warehouse','Ship hold and cargo','Buying, selling and restrictions','Economic bonuses and taxes')),
 Domain('ports','Ports, towns & settlements',
  'Port location, city levels, services, ownership, production and settlement bonuses.',
  ('Port_Definitions','WorldPorts','PortLevelBonuses','Factory_Levels','World','InterestPoints'),
  ('Port locations and attributes','City levels and development','Port buildings and production','Port ownership and capture','Port services and repair','Port level bonuses','Trade and supply rates','Harbors and spawn locations')),
 Domain('guilds','Guilds, diplomacy & territory',
  'Guild progression, member roles, benefits, diplomacy, territorial holdings and warfare.',
  ('GuildBonuses','GuildTitles','Benefit_Levels','Forts_Map_References','Port_Definitions','PortLevelBonuses'),
  ('Guild creation and membership','Guild titles and permissions','Guild bonuses and levels','Guild upgrades and costs','Diplomacy and alliances','Territorial control','Forts and siege systems','Port battles and ownership','Guild economy and rewards')),
 Domain('world','World map, locations & discovery',
  'The playable world, settlements, geographic references, markers, islands and map activities.',
  ('World','Map_Objects','WorldPorts','StartMap','InterestPoints','Marker_Definitions','Forts_Map_References','Altar_Map_References','Mines_and_Nodes_Map_References','Other_Villages_Map_References','Fishing_Villages_Map_References'),
  ('World geography and islands','Ports and fast travel','Forts and contested regions','Map markers and points of interest','Environmental landmarks','Altars and special locations','Resource markers and gathering sites','Villages and outposts','Discovery and exploration')),
 Domain('npc','NPC ships, encounters & PvE',
  'NPC hulls, enemy behavior, encounter rules, mission waves, loot and creature combat.',
  ('NPC_Types','NPC_Mission_Waves','UnitsInfo','Whale_Rules','ShipsBasics','Mode_Definitions'),
  ('NPC ship variants and stats','NPC behavior and combat AI','NPC difficulty scaling','NPC combat rewards and drops','PvE mission waves','Enemy factions and fleets','Sea creatures and whale encounters','Elite and boss encounters')),
 Domain('missions','Missions, quests & collectibles',
  'Tasks, unlocks, collectibles, treasure, achievements, rewards and activity prerequisites.',
  ('Collectable_Definitions','Chest_Item_Definitions','Achievements','Altar_Map_References','Mode_Definitions','NPC_Mission_Waves','Gamepedia'),
  ('Missions and quests','Collectibles and collectibles sets','Chests and treasure rewards','Dig sites and altars','Achievements and achievements rewards','Unlock conditions and prerequisites','Daily and repeatable activities','Quest rewards and currency')),
 Domain('modes','Arena, tournaments & game modes',
  'Arena, raids, hunts, tournament formats, match rewards, restrictions and map pools.',
  ('Mode_Definitions','MapsArena','MapsForPassing','ArenaUpgrades','NPC_Mission_Waves','Rules_and_Limitations'),
  ('Arena modes and matchmaking','Arena upgrade shop','Tournaments and rankings','Hunt events','Pirate raids and escorts','Cooperative and solo activities','Mode rules and ship rank limits','Activity rewards and currency')),
 Domain('villages','Villages, fishing & wildlife',
  'Fishing villages, other villages, aquatic encounters, gathering and local services.',
  ('Fishing_Villages_Map_References','Other_Villages_Map_References','Whale_Rules','World','Resources'),
  ('Fishing and catch systems','Fishing villages and services','Village exchanges and production','Whales and sea wildlife','Fishing equipment and resources','Special village locations')),
 Domain('bonuses','Bonuses, perks & progression',
  'Modifiers across ships, officers, guilds, ports, game modes, progression and account systems.',
  ('Benefit_Levels','CaptainSkills','GuildBonuses','ShipUpgradesNew','PortLevelBonuses','ArenaUpgrades','RangInfo','Achievements'),
  ('Bonus stacking order','Temporary and permanent buffs','Captain perks','Ship upgrades and modifiers','Guild and port bonuses','Status effect resistance','Rank rewards and progression','Upgrade and unlock prerequisites')),
 Domain('art','Game assets, images & visual reference',
  'Images, icon associations, ship models, sprite atlases and cosmetics. Artifacts are not mechanics facts.',
  ('Images','Asset_Inventory','ShipDesingElements','EnvDesingElements','Code_Asset_References','Archive_Coverage'),
  ('Ship reference artwork','Item icons and textures','Cannon and equipment icons','Sprite atlases and composites','World map artwork','Asset decoding status and missing images')),
 Domain('source','Client metadata & research evidence',
  'Raw tables, code methods, enum values, schema fields, localization and extraction diagnostics.',
  ('Gameplay_Methods','Gameplay_Code_Constants','Game_Enums','Game_Schemas','All_Data_Fields','English_Text','System_English_Text','English_Names','Named_Entities','Explicit_Chance_Fields','Extraction_Issues','Archive_Index','Archive_Coverage','ProceduralPresets','Code_Asset_References'),
  ('Client/server responsibility','Data tables and schemas','Enumerations and identifiers','Code method and call evidence','Explicit probabilities and chance fields','English localization and naming','Unresolved references','Extractor coverage and diagnostics','Client version differences')),
)

ALL_DATASETS=tuple(sorted({ds for domain in DOMAINS for ds in domain.datasets}))

# Primary section for a table. Cross-domain use is preserved in each domain's references.
PRIMARY = {}
for _domain in DOMAINS:
    for _dataset in _domain.datasets:
        PRIMARY.setdefault(_dataset, _domain.key)


def domain_for_dataset(dataset):
    # .partN source tables are equivalent to their base table.
    base=re.sub(r'\.part\d+$','',dataset,flags=re.I)
    return PRIMARY.get(base,'unclassified')


def domains_for_dataset(dataset):
    base=re.sub(r'\.part\d+$','',dataset,flags=re.I)
    return tuple(d.key for d in DOMAINS if base in d.datasets)


def domains():
    return DOMAINS


def coverage(db):
    """Real inventory counts only. No inference of completeness or server mechanics."""
    present=dict(db.categories())
    ret=[]
    for domain in DOMAINS:
        sets=[]
        for ds in domain.datasets:
            n=present.get(ds,0)
            sets.append({'dataset':ds,'count':n,'available':n>0})
        ret.append({'key':domain.key,'title':domain.title,'description':domain.description,
                    'topics':list(domain.topics),'datasets':sets,
                    'total_records_across_tables':sum(x['count'] for x in sets),
                    'tables_present':sum(1 for x in sets if x['count']),
                    'tables_expected':len(sets)})
    unmapped=[{'dataset':n,'count':count} for n,count in present.items() if domain_for_dataset(n)=='unclassified']
    if unmapped:
        ret.append({'key':'unclassified','title':'Unclassified sources','description':'New or unknown game tables; review and assign to wiki domains.',
                    'topics':['Classification needed'],'datasets':unmapped,
                    'total_records_across_tables':sum(x['count'] for x in unmapped),
                    'tables_present':len(unmapped),'tables_expected':len(unmapped)})
    return ret


def seed_mechanics_pages(db):
    """Add navigational research scaffolding; never overwrite manually edited wiki pages."""
    from workbench_db import slugify
    result={'domains':0,'topics':0}
    for domain in DOMAINS:
        slug='atlas-'+domain.key
        body=('# '+domain.title+'\n\n'+domain.description+'\n\n'
              '## Areas to research\n\n'+''.join('- '+s+'\n' for s in domain.topics)
              +'\n## Client data sources\n\n'+''.join('- `'+s+'`\n' for s in domain.datasets)
              +'\n## Evidence policy\n\nThis is an organizing page, **not a verified explanation**. '
              'Use extracted source records, code references, test results and game versions to substantiate claims. '
              'Some rules may be server-authoritative or absent from the client.\n')
        db.upsert_article(slug,domain.title,'Mechanics atlas',body,'ontology','taxonomy:'+domain.key,
                          'research-outline',preserve_edited=True)
        result['domains']+=1
        for topic in domain.topics:
            tslug='topic-'+domain.key+'-'+slugify(topic)
            tbody=('# '+topic+'\n\n**Research status: not yet verified.**\n\n'
                   '## What to document\n\n'+domain.description+'\n\n'
                   '## Candidate client sources\n\n'+''.join('- `'+s+'`\n' for s in domain.datasets)
                   +'\n## Findings and formulas\n\n*Add verified findings here, including conditions, units and game version.*\n\n'
                   '## Verification and open questions\n\n*Document tests, uncertainties and server-side unknowns.*\n')
            db.upsert_article(tslug,topic,domain.title,tbody,'ontology','taxonomy:'+domain.key,
                              'research-outline',preserve_edited=True)
            result['topics']+=1
    db.conn.commit()
    return result
