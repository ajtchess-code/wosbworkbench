"""Evidence-based WoSB economy research and planning.

This module deliberately distinguishes a client statement from a verified live rule.
Crafting-time *credit* balances are not elapsed crafting duration, and modifiers
are not automatically combined without a proven stacking formula.
"""
from __future__ import annotations

import json
import math

RESEARCH_SLUGS = {
    'craft_time': 'research-crafting-time-optimization',
    'warehouses': 'research-workshops-warehouses-dangerous-waters',
    'factories': 'research-mines-manufactories',
    'recipes': 'research-recipe-crafting-time',
}


def records(db, dataset, source='Game'):
    """Use one client build consistently; never silently mix versions."""
    rows=db.conn.execute('SELECT raw_json,source_root FROM records WHERE dataset=? ORDER BY CASE source_root WHEN ? THEN 0 WHEN \'Steam\' THEN 1 ELSE 2 END,id',
                         (dataset, source)).fetchall()
    # The preferred build may be absent (some Steam builds have fewer decoded tables).
    available={r['source_root'] for r in rows}
    selected=source if source in available else ('Steam' if 'Steam' in available else (rows[0]['source_root'] if rows else ''))
    return [json.loads(r['raw_json']) for r in rows if r['source_root']==selected]


def named(rows, key, value):
    return next((r for r in rows if str(r.get(key,''))==value),None)


def source_note(row, dataset, source='Game'):
    if not row: return f'[{dataset}: not yet found in {source} client]'
    return f"`{source}/{dataset}` · `{str(row.get('Source','unspecified')).replace('`','')}` · record `{row.get('SourceRecord',row.get('Name',row.get('FactoryTypeID','?')))}`"


def _one_line(row, label, field='EnglishDescription'):
    if not row:return f'- **{label}:** no decoded record found.'
    return f'- **{label}:** {row.get(field) or "No description in source."}  \n  Source: `{row.get("Source", "unknown")}`'


def build_research_articles(db, source='Game'):
    """Regenerate derivative wiki guides, preserving all hand-edited content."""
    guild=records(db,'GuildBonuses',source)
    skills=records(db,'CaptainSkills',source)
    facilities=records(db,'Factory_Levels',source)
    recipes=records(db,'Crafting_Recipes',source)
    guild_by_type={r.get('Type'):r for r in guild}
    skill_by_id={r.get('Name'):r for r in skills}

    crafting = [
        '# Crafting Time — limits, recovery and maximization',
        '',
        '**Status: client-sourced bonuses, stacking/optimization under investigation.**',
        'This article concerns the **crafting-time resource/credit** and its recovery. It is distinct from a recipe\'s craft-time charge and from real-time facility production cycles.',
        '',
        '## Confirmed client descriptions and bonus values',
    ]
    for label,code in [
        ('Shared Workshops (guild, +300 limit)','MCraftTimeLimitBonus'),
        ('Hire Workers (guild, +30 recovery-speed stat)','MCraftTimeRecoverySpeed'),
        ('Mutual Aid Contract (guild, tavern missions)','BCraftForMissionsBonus'),
    ]:
        r=guild_by_type.get(code)
        crafting.append(_one_line(r,label))
        if r:crafting.append(f'  Client level values: `{r.get("LevelValues")}`; duration days: `{r.get("DurationDays")}`.')
    for label,sid in [
        ('Apprentice','skill_3'),('Master','skill_4'),('Workforce Management','skill_20'),
        ('Helping Hand','skill_61'),('Secret Hall','skill_50')
    ]:
        r=skill_by_id.get(sid);crafting.append(_one_line(r,label))
        if r:crafting.append(f'  Effect: `{r.get("Effect")}`; prerequisites: `{r.get("DependsTo") or "none stated"}`; rank: `{r.get("RequiredRank") or "none stated"}`.')
    crafting += [
        '', '## Scenario planning',
        '- Choose **Apprentice** or **Master** for the client-described base limit and recovery. Whether either is available without prerequisite skills depends on character progression.',
        '- The guild **Shared Workshops** benefit adds a stated +300 limit. **Workforce Management** adds +5 limit for each Specialty Workshop in a *different port*, not each workshop in one port.',
        '- **Secret Hall** allows two Specialty Workshops in dangerous-water ports without a warehouse requirement. This can conserve limited warehouse placements, but two workshops in the same port should not be counted as two distinct-port bonuses.',
        '- **Hire Workers** in the guild provides a `+30` recovery-speed value. The precise interaction with the Apprentice/Master 40/50-per-hour descriptions is not yet verified.',
        '- The tool\'s **Economy planner** can show an *illustrative additive capacity scenario* and clearly marks it as an assumption, not established server arithmetic.',
        '', '## Optimization questions that remain open',
        '- Which ports are considered dangerous waters in the current client/server build? Identify with map-zone evidence rather than assuming from port names or `Type` alone.',
        '- Are there Personal Island decorations that increase the capacity, recharge speed, or available crafting time? Extract their exact effects and stacking rules.',
        '- Is there a maximum cap on additive crafting-time bonuses? What happens when a skill or guild benefit expires?',
        '- Are there passive effects from upgraded warehouses, port benefits, consumables, titles, and equipment?',
        '- Do tavern mission rewards and quest rewards obey the current crafting-time cap?',
        '', '## Evidence provenance',
        f'- Build: `{source}`; tables: `GuildBonuses`, `CaptainSkills`, `Benefit_Levels`.',
        '- This page quotes exported English client descriptions; server behavior is not independently verified.',
    ]

    wh=[
        '# Workshop placement, warehouses and dangerous-water ports','',
        '**Status: client descriptions found; port-by-port classification and optimal allocation not yet verified.**','',
        '## Relevant captain skills',
    ]
    for label,sid in [('Workforce Management','skill_20'),('Secret Hall','skill_50'),('Storekeeper','skill_6'),('Patrician','skill_7')]:
        r=skill_by_id.get(sid);wh.append(_one_line(r,label))
        if r:wh.append(f'  Effect: `{r.get("Effect")}`; depends on `{r.get("DependsTo") or "none"}`.')
    wh += ['','## Planning dependencies',
            '- Warehouses and Specialty Workshops must be modeled separately: a warehouse count is not a workshop count.',
            '- Count distinct ports with Specialty Workshops for Workforce Management, including free eligible hazardous-water ports, **only when the workshop is actually built**.',
            '- A port with two workshops contributes one distinct-port count if the client description is literal.',
            '- Allocate limited upgraded warehouses to ports where they enable useful workshops, production or storage; consider the warehouse-free dangerous-water opportunity from Secret Hall.',
            '- Check whether warehouse level, ownership, port facilities, and shipbuilding workshop type change eligibility.',
            '','## Port classification gap',
            '- `Port_Definitions` includes port names, types and flags, but the available table does **not independently establish** which ports are in dangerous waters.',
            '- Do not publish a complete dangerous-waters port list until map zones or verified observations support the classification.',
            '','## Live-world worksheet',
            '| Port | In dangerous waters? (evidence) | Warehouse level | Workshops | Distinct-port count | Production strategic value |',
            '|---|---|---|---|---|---|',
            '| *To be mapped* | Unknown | Unknown | Unknown | Unknown | Unknown |',
            '','## Sources',f'- `CaptainSkills` ({source}) · `Port_Definitions` · `WorldPorts`.']

    fm=[
        '# Mines, manufactories, supply, storage and throughput','',
        '**Status: per-production-operation values are decoded; elapsed production time and bonus stacking remain to be verified.**','',
        '## Bonuses affecting resource facilities',
    ]
    for label,sid in [('Logistician','skill_33'),('Quick Delivery','skill_36'),('Self-Supply','skill_15'),
                      ('Hire Workers (captain skill)','skill_13'),('Construction Expertise','skill_14'),('Magnate','skill_60')]:
        fm.append(_one_line(skill_by_id.get(sid),label))
    for code in ['PFactoriesStorageCapacity','PWoodProductionBonus','PIronProductionBonus','PCopperProductionBonus','PCoalProductionBonus','PRumProductionBonus','PLacquerProductionBonus','PAnimalProductionBonus']:
        r=guild_by_type.get(code)
        if r: fm.append(f'- **{r.get("EnglishName")}** (`{code}`): {r.get("EnglishDescription")} · levels: `{r.get("LevelValues")}`; duration `{r.get("DurationDays")}` days. Source: `{r.get("Source")}`')
    fm += ['', '## Per-operation production and base hold capacity',
           'The values below are decoded for a **single client production operation**, not items per hour. Rations and other inputs are shown as defined in client data.',
           '', '| Facility | Level | Produced per operation | Consumed per operation | Base hold capacity |',
           '|---|---:|---|---|---:|']
    def compact(obj):
        if not isinstance(obj,dict):return str(obj)
        return ', '.join(f'{k}: {v}' for k,v in obj.items()) or '—'
    for r in sorted(facilities,key=lambda r:(str(r.get('EnglishName','')),int(r.get('Level') or 0))):
        fm.append('| {n} | {lvl} | {prod} | {con} | {cap:g} |'.format(n=str(r.get('EnglishName','?')).replace('|','/'),lvl=r.get('Level','?'),
            prod=compact(r.get('ProduceEnglish')),con=compact(r.get('ConsumeEnglish')),cap=float(r.get('BaseHoldCapacity') or 0)))
    fm += ['','## Missing rate and stacking evidence',
           '- Determine the in-game time for one production operation and how pauses, offline time, ration shortages and zone speed affect cycles.',
           '- Determine whether +25% hazardous-water speed multiplies, adds to, or replaces guild production bonuses.',
           '- Identify whether hold capacity scales additively or multiplicatively with Logistician and Resource Warehouses.',
           '- Calculate time-to-full only after a verified cycle interval and storage-formula are available.',
           '','## Sources',f'- `Factory_Levels` ({source}), `CaptainSkills`, `GuildBonuses`.']

    rc=[
        '# Recipe crafting time, cost and production planning','',
        '**Status: decoded recipe charges; elapsed completion time and processing parallelism are separate.**','',
        '| Recipe | Context | Output per batch | Craft-hour charge | Required factory |',
        '|---|---|---:|---:|---|',
    ]
    for r in recipes:
        rc.append(f"| {str(r.get('EnglishName','?')).replace('|','/')} | {r.get('Context','?')} | {r.get('OutputQuantity','?')} | {r.get('CraftHours','?')} | {r.get('RequiredFactoryID') or '—'} |")
    rc += ['','## Computing recipe budgets',
           'For a single recipe with a known output quantity, **batches = ceil(requested quantity / output per batch)**.',
           'Then **nominal craft-time charge = batches × recipe `CraftHours`**. This is a planning calculation for the *resource charge*; it is **not** necessarily the real-world elapsed time to finish.',
           'Total raw resources and any prerequisite recipes require the `Recipe_Ingredients` and `Resource_Chain_*` tables, including alternative recipe selection.',
           '','## Open questions',
           '- How do any crafting cost discounts and port benefits affect time charges?',
           '- Do recipes consume all available crafting time at once or progress over multiple cycles?',
           '- How do specialty workshop requirements interact with upgraded warehouses and free dangerous-water slots?',
           '','## Sources',f'- `Crafting_Recipes` ({source}) · `Recipe_Ingredients` · `Resource_Chain_Plans`.']

    pages = [
        (RESEARCH_SLUGS['craft_time'],'Crafting Time: limits, recovery & maximization','Crafting & production chains','\n'.join(crafting)),
        (RESEARCH_SLUGS['warehouses'],'Workshop and warehouse placement optimization','Ports, warehouses & infrastructure','\n'.join(wh)),
        (RESEARCH_SLUGS['factories'],'Mines and manufactories: rates, storage & upgrades','Resource gathering, mines & facilities','\n'.join(fm)),
        (RESEARCH_SLUGS['recipes'],'Recipe crafting-time budgets and production','Crafting & production chains','\n'.join(rc)),
    ]
    for slug,title,section,body in pages:
        db.upsert_article(slug,title,section,body,'derived-research',f'{source} client catalog', 'source-only' if (guild or skills or facilities or recipes) else 'research-outline',preserve_edited=True)
    db.conn.commit()
    return {'pages':len(pages),'source':source,'skills':len(skills),'guild_bonuses':len(guild),'facility_levels':len(facilities),'recipes':len(recipes)}


def safe_nonnegative_int(value,maximum=10000):
    n=int(str(value).strip())
    if n<0 or n>maximum:raise ValueError(f'Value must be between 0 and {maximum}')
    return n


def craft_time_scenario(tier='master',shared_workshops=False,hire_workers=False,
                        workforce_management=False,distinct_workshop_ports=0,
                        secret_hall=False,dangerous_water_ports=0,
                        warehouse_skill='patrician'):
    """Scenario, explicitly NOT a reconstructed server formula."""
    if tier not in ('none','apprentice','master'):raise ValueError('Invalid tier')
    if warehouse_skill not in ('base','storekeeper','patrician'):raise ValueError('Invalid warehouse skill')
    distinct=safe_nonnegative_int(distinct_workshop_ports,200)
    hazard=safe_nonnegative_int(dangerous_water_ports,200)
    if hazard>distinct:
        raise ValueError('Dangerous-water workshop ports cannot exceed all distinct workshop ports')
    base={'none':(None,None),'apprentice':(600,40),'master':(1000,50)}[tier]
    base_cap,base_regen=base
    guild_cap=300 if shared_workshops else 0
    workshop_cap=5*distinct if workforce_management else 0
    theoretical_cap=base_cap+guild_cap+workshop_cap if base_cap is not None else None
    warehouse_limit={'base':2,'storekeeper':6,'patrician':11}[warehouse_skill]
    return {
      'base_crafting_time_cap':base_cap,
      'base_recovery_per_hour':base_regen,
      'guild_crafting_cap_addition':guild_cap,
      'distinct_workshop_port_cap_addition':workshop_cap,
      'illustrative_additive_cap':theoretical_cap,
      'guild_recovery_stat_addition':30 if hire_workers else 0,
      'final_recovery_per_hour':None, # intentionally unknown: stacking has not been proven
      'warehouse_limit_from_skill_descriptions':warehouse_limit,
      'warehouse_free_hazard_workshop_slots':2*hazard if secret_hall else 0,
      'warehouse_free_distinct_ports':hazard if secret_hall else 0,
      'assumptions':['+300 and +5/port are treated as additive for capacity planning, NOT verified server stacking',
                     '+30 guild recovery is a client stat value, not proven +30 units/hour',
                     'Dangerous-water classification and actual built workshop counts are user-entered',
                     'Two workshops in one port only count as one distinct port',
                     'Warehouse limits come from captain skill descriptions; other constraints may apply']}


def recipe_budget(recipe,quantity):
    quantity=safe_nonnegative_int(quantity,1000000000)
    output=float(recipe.get('OutputQuantity') or 0)
    hours=float(recipe.get('CraftHours') or 0)
    if output<=0 or hours<0:raise ValueError('Invalid recipe output or craft-hour charge')
    batches=math.ceil(quantity/output)
    return {'requested_quantity':quantity,'batches':batches,
            'output_quantity':batches*output,'nominal_craft_hours':batches*hours,
            'note':'Nominal recipe craft-time charge, not elapsed real-world production time.'}
