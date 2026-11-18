"""Evidence-aware quantitative research for the *whole* WoSB economy/combat.

Calculators report their assumptions and status. No numerical output here is
represented as an authoritative server-side damage/production formula.
"""
from __future__ import annotations
import json
import math
from decimal import Decimal, ROUND_HALF_EVEN


def _finite(number,name):
    x=float(number)
    if not math.isfinite(x) or abs(x)>1e12:raise ValueError(f'{name} must be finite')
    return x


def armor_effective(basic, percent_bonus, flat_bonus, *, percent_units='percent'):
    """Getter: BasicArmor * (1 + PArmor) + MArmor.

    UI accepts percent points, converts to fraction. This is effective armor,
    NOT automatically a hull-damage reduction percentage.
    """
    b=_finite(basic,'BasicArmor');p=_finite(percent_bonus,'PArmor');m=_finite(flat_bonus,'MArmor')
    if b<0:raise ValueError('Base armor cannot be negative')
    multiplier=p/100 if percent_units=='percent' else p
    return {'effective_armor':b*(1+multiplier)+m,
            'formula':'BasicArmor × (1 + PArmor) + MArmor',
            'status':'client getter expression; downstream penetration and final damage unverified',
            'source':'Common.dll armor getter IL reported by v3.1 combat analysis'}


def fire_damage_multiplier(big_fire_percent, fire_area_percent, microfire_speed_percent=0, big_fire_speed_percent=0):
    p=_finite(big_fire_percent,'PReduceBigFireDamage')/100
    a=_finite(fire_area_percent,'PReduceFireAreaDamage')/100
    micro=_finite(microfire_speed_percent,'PMicrofireFightingSpeed')/100
    bigspeed=_finite(big_fire_speed_percent,'PBigFireFightingSpeed')/100
    return {'large_fire_damage_factor':max(.001,1-p),'fire_area_damage_factor':max(.01,1-a),
            'microfire_duration_factor':max(.001,1-micro),
            'big_fire_fighting_speed_factor':1+bigspeed,
            'source':'Common.dll fire-related getters from v3.1 client evidence',
            'status':'individual getter outputs only; duration stacking and server behavior unverified'}


def microfire_threshold(max_hp):
    hp=_finite(max_hp,'MaxHP')
    if hp<=0:raise ValueError('MaxHP must be positive')
    # XNA/C# Math.Round defaults to midpoint-to-even; Python round implements same.
    return {'minimum_microfires':1+int(Decimal(str(hp/1000)).quantize(Decimal('1'),rounding=ROUND_HALF_EVEN)),
            'eligible_summary_hp_interval':[.05*hp,.95*hp],
            'formula':'1 + round(MaxHP/1000), with additional state checks',
            'source':'Common.Game.ShipFirstHp::ServerBurningCheck in Common.dll (0x0600274B)',
            'status':'possible large-fire escalation gate; not a complete ignition probability or sufficient condition'}


def crafting_capacity_scenario(base_capacity, guild_bonus=0, workshop_bonus_each=0, eligible_workshops=0):
    base=_finite(base_capacity,'Base crafting time')
    guild=_finite(guild_bonus,'Guild bonus')
    per=_finite(workshop_bonus_each,'Workshop bonus')
    count=int(_finite(eligible_workshops,'Eligible workshops'))
    if count<0 or count>500 or base<0:raise ValueError('Invalid crafting scenario')
    return {'scenario_capacity':base+guild+per*count,
            'formula':'base + guild flat bonus + per-workshop bonus × eligible workshop count',
            'assumptions':['Bonuses apply additively','All entered workshops qualify','No hidden cap or server modifier'],
            'status':'scenario, NOT verified stacking formula',
            'evidence':['Guild benefit Shared Workshops: +300 limit','Workforce Management: +5 limit per specialty workshop in different port']}


def crafting_spend(hours, reduction_percent=0, output_quantity=1):
    value=_finite(hours,'Craft hours');p=_finite(reduction_percent,'Reduction')
    qty=int(_finite(output_quantity,'Quantity'))
    if value<0 or not 0<=p<=100 or not 1<=qty<=100000:raise ValueError('Invalid crafting inputs')
    return {'nominal_hours':value*qty,'scenario_hours_after_reduction':value*qty*(1-p/100),
            'status':'what-if reduction; exact server application and batching are unverified'}


def facility_output_per_operation(base_qty, flat_bonus=0, percent_bonus=0, operations=1):
    base=_finite(base_qty,'Production quantity');flat=_finite(flat_bonus,'Flat bonus')
    pct=_finite(percent_bonus,'Percent bonus');ops=int(_finite(operations,'Operations'))
    if base<0 or ops<1 or ops>100000:raise ValueError('Invalid production scenario')
    return {'scenario_total':ops*(base*(1+pct/100)+flat),'base_per_operation':base,
            'status':'what-if production yield; cycle timing, rounding, stacking, and hourly rate unknown',
            'note':'Factory_Levels supplies output per operation, not production per hour'}


def wind_lookup(rose,angle_degrees):
    """Present extracted WindRose numeric fields without inventing a speed curve."""
    angle=_finite(angle_degrees,'Relative wind angle')%360
    mapped={k:v for k,v in rose.items() if k in ('GreenLeft','GreenRight','HeadwindLeft','HeadwindRight','FordewindFineEdge')}
    return {'angle_degrees':angle,'wind_rose_name':rose.get('Name') or rose.get('EnglishName') or 'unknown',
            'wind_rose_data':mapped,'status':'client angle boundary data; true speed/trim curve requires code path validation'}


def load_catalog_rules(db,build='Game'):
    """Expose raw-source values for calculators, preserving build provenance."""
    results={}
    for dataset in ('GuildBonuses','CaptainSkills','PortLevelBonuses','WindRoses','Factory_Levels','Crafting_Recipes','ShipsToPlay'):
        rows=db.conn.execute('SELECT name,source_file,raw_json FROM records WHERE dataset=? AND source_root=? LIMIT 1500',(dataset,build)).fetchall()
        results[dataset]=[{'name':r['name'],'source':r['source_file'],'raw':json.loads(r['raw_json'])} for r in rows]
    return results


def contextual_bonuses(db,build='Game'):
    """Source-linked bonuses affecting several mechanics, no inferred stacking."""
    data=load_catalog_rules(db,build)
    tokens=('craft','workshop','warehouse','factory','mine','fire','armor','sail','wind','ship','production','storage')
    matches=[]
    for dataset in ('GuildBonuses','CaptainSkills','PortLevelBonuses'):
        for item in data[dataset]:
            obj=item['raw'];fields=' '.join(str(obj.get(k,'')) for k in ('EnglishName','EnglishDescription','Type','Effect','Receiver'))
            if any(word in fields.casefold() for word in tokens):
                matches.append({'name':item['name'],'dataset':dataset,'build':build,
                                'effect':obj.get('Effect') or obj.get('Type') or '',
                                'levels':obj.get('LevelValues') or '',
                                'description':obj.get('EnglishDescription') or '',
                                'source':item['source']})
    return matches
