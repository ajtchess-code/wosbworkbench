"""Turn sourced game records into linked, editable offline wiki drafts.

No synthesized game rules. Derived article pages are source-only, and existing
user-edited pages are never overwritten. The importer keeps build provenance.
"""
from __future__ import annotations
import json
from collections import defaultdict
from workbench_db import slugify

DOMAINS={
 'ShipsToPlay':'Ships, hulls & construction',
 'GuildBonuses':'Guild systems',
 'CaptainSkills':'Captain skills and progression',
 'Crafting_Recipes':'Crafting, production & economy',
 'Factory_Levels':'Resource gathering, mines & facilities',
 'WorldPorts':'Ports, towns & settlements',
 'WindRoses':'Sailing, weather & navigation',
 'Cannons':'Cannons, ammunition & ballistics',
 'Resources':'Items and resources',
 'Crew_Special':'Crew and specialists',
 'PortLevelBonuses':'Ports, towns & settlements',
 'ShipUpgradesNew':'Ship upgrades and modules',
 'Collectable_Definitions':'Exploration and collectible missions',
}


def _rows(db,dataset,build):
    return [json.loads(row['raw_json']) for row in db.conn.execute(
        'SELECT raw_json FROM records WHERE dataset=? AND source_root=?',(dataset,build))]


def _desc(r):
    return str(r.get('EnglishDescription') or r.get('Description') or '').strip()


def _scalar_fields(r):
    ignore={'EnglishName','EnglishDescription','Description','Source','SourceRecord','IDEnglish'}
    for k,v in r.items():
        if k not in ignore and isinstance(v,(str,int,float,bool)) and str(v).strip() and len(str(v))<450:
            yield k,v


def _source(r,build):
    return f'{build}: {str(r.get("Source") or r.get("SourceRecord") or "client catalog")} '


def ship_article(ship,basic,construction,materials,build):
    name=str(ship.get('EnglishName') or ship.get('Name') or ship.get('ID'))
    page=[f'# {name}', '',f'**Client build:** {build}', '**Evidence state:** extracted client data, not an independently verified gameplay guide.','']
    if _desc(ship):page.extend((_desc(ship),''))
    page+=['## Base ship statistics','']
    for key in ('ID','StaticInfoID','Type','SubtypeEnglish','Health','Armor','BasicSpeed','InternalBaseSpeed',
                'BasicMobility','BaseCrewPlaces','CapacityCg','ShipRank','RequiredRank','PlacesForUnitsCount'):
        if key in ship:page.append(f'- **{key}:** {ship[key]}')
    page+=['','## Linked ship model','']
    if basic:
        page.append(f'- **ModelName:** `{basic.get("ModelName") or "not recorded"}`')
        page.append(f'- Linked using `ShipsToPlay.StaticInfoID = ShipsBasics.ID = {ship.get("StaticInfoID")}`.')
        page.append(f'- Basics source: `{_source(basic,build)}`')
    else:page.append('- No matching ShipsBasics record was imported for this build.')
    page+=['','## Construction and resources','']
    if construction:
        for k in ('BaseGoldCost','BaseShipwaySeconds','ConstructionStatus','InstantFinishMinimum_Resource37'):
            if k in construction:page.append(f'- **{k}:** {construction[k]}')
        page.append('- Construction source: `'+_source(construction,build)+'`')
    else:page.append('- No source-derived construction row available for this build.')
    if materials:
        for r in materials:
            page.append(f'- {r.get("ResourceEnglishName") or r.get("ResourceID")}: '
                        f'{r.get("BaseQuantity","?")} units (base, before modifiers)')
    page+=['','## Mechanics and research connections','',
           '- Wind characteristics depend on sailing, wind roses, ship physics, and modifiers.',
           '- Damage calculations depend on armor, projectile penetration, active bonuses, and server-side rules.',
           '- 3D model file presence does not prove vulnerable hit locations.','',
           '## Evidence','',f'- Ship: `{_source(ship,build)}`']
    return '\n'.join(page)


def mechanics_dataset_page(r,dataset,build):
    title=str(r.get('EnglishName') or r.get('Name') or r.get('RecipeID') or r.get('ID') or r.get('SourceRecord') or 'Unnamed entry')
    lines=[f'# {title}', '',f'**Dataset:** `{dataset}`  ',f'**Client build:** `{build}`  ',
           '**Knowledge state:** extracted record; mechanics and server-side effects may be incomplete.','']
    if _desc(r):lines.extend((_desc(r),'','## Extracted fields',''))
    else:lines+=['## Extracted fields','']
    for k,v in _scalar_fields(r):lines.append(f'- **{k}:** {v}')
    if dataset=='Factory_Levels':
        lines.extend(['','**Production amounts are per operation, not verified hourly rates.**',
                      'Storage/production modifiers and cycle timing require separate tracing.'])
    if dataset=='Crafting_Recipes':
        lines.extend(['','**CraftHours is a source field, not validated wall-clock time.**',
                      'Player, guild, port and skill modifiers may change the actual cost.'])
    if dataset=='WindRoses':
        lines.append('\nThese angle boundaries are not the full ship speed curve.')
    lines.extend(['','## Source evidence','',f'- `{_source(r,build)}`'])
    return title,'\n'.join(lines)


def enrich_catalog(db,build='Game',*,include_heavy=False):
    """Write source-only wiki pages using exact source links and verified joins.

    Defaults to one game build; choosing Steam separately never merges values.
    """
    ship_basics={str(x.get('ID')):x for x in _rows(db,'ShipsBasics',build)}
    construction={str(x.get('ShipID')):x for x in _rows(db,'Ship_Construction',build)}
    materials=defaultdict(list)
    for r in _rows(db,'Ship_Materials',build):materials[str(r.get('ShipID'))].append(r)
    added=0;by_domain=defaultdict(int)
    for ship in _rows(db,'ShipsToPlay',build):
        key=str(ship.get('ID') or ship.get('SourceRecord'))
        if not key:continue
        doc=ship_article(ship,ship_basics.get(str(ship.get('StaticInfoID'))),
                         construction.get(key),materials.get(key,[]),build)
        title=str(ship.get('EnglishName') or key)
        db.upsert_article('source-'+slugify(build+'-ShipsToPlay-'+key),title,
                          DOMAINS['ShipsToPlay'],doc,'client-record',_source(ship,build),
                          'source-only',preserve_edited=True)
        added+=1;by_domain['ShipsToPlay']+=1
    for dataset,section in DOMAINS.items():
        if dataset=='ShipsToPlay':continue
        if not include_heavy and dataset in ('Resources','ShipUpgradesNew','Collectable_Definitions'):continue
        for pos,r in enumerate(_rows(db,dataset,build)):
            external=(r.get('ID') or r.get('Name') or r.get('RecipeID') or
                      r.get('SourceRecord') or (dataset=='Factory_Levels' and str(r.get('FactoryTypeID'))+'-'+str(r.get('Level'))) or str(pos))
            title,doc=mechanics_dataset_page(r,dataset,build)
            db.upsert_article('source-'+slugify(build+'-'+dataset+'-'+str(external)),
                             title,section,doc,'client-record',_source(r,build),
                             'source-only',preserve_edited=True)
            added+=1;by_domain[dataset]+=1
    db.conn.commit()
    return {'build':build,'created_or_examined':added,'by_dataset':dict(by_domain),
            'note':'Source-only drafts; existing manually edited pages preserved. No formulas inferred.'}
