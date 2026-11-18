"""Expanded, reader-first local Codex pages based on real extracted client records.

Never forges game unlock dependencies, slot restrictions or damage calculations.
All player-facing tables expose an optional source/evidence panel.
"""
from __future__ import annotations
import html, json, math


def esc(v):return html.escape(str('—' if v is None else v),quote=True)

def _float(item,key):
    try:
        x=float(item.get(key) or 0)
        return x if math.isfinite(x) else 0
    except (ValueError,TypeError):return 0


def _stat(item,key,label=None):
    val=item.get(key,'—');return f'<div class="stat"><small>{esc(label or key)}</small><b>{esc(val)}</b></div>'


def compare_page(conn,ship_list,shell,ids=()):
    ships=ship_list(conn)
    if not ships:
        return shell('Ship comparison','<p class="notice">No ships in the catalog yet. Import a client report in Workbench first.</p>',
                     'Shipyard','Choose up to three ships and explore their actual catalog values.')
    if not ids:ids=[str(x.get('ID')) for x in ships[:2]]
    selected=[next((x for x in ships if str(x.get('ID'))==str(id)),None) for id in ids[:3]]
    selected=[x for x in selected if x]
    fields={'Health':'Hull HP','Armor':'Catalog armor','BasicSpeed':'Base speed','BasicMobility':'Mobility',
            'CapacityCg':'Cargo','BaseCrewPlaces':'Crew places','PlacesForUnitsCount':'Unit slots'}
    form='<form class="compare-controls" method="get" action="/compare">'
    for i in range(3):
        current_id=ids[i] if i<len(ids) else ('none' if i==2 else str(ships[min(i,len(ships)-1)].get('ID','')))
        options=''.join(f'<option value="{esc(s.get("ID"))}"'+(' selected' if str(s.get('ID'))==current_id else '')+'>'+esc(s.get('EnglishName'))+'</option>' for s in ships)
        form+=f'<label>Ship {i+1} <select name="ship">'+('<option value="">None</option>' if i==2 else '')+options+'</select></label>'
    form+='<button class="button primary">Compare ships</button></form>'
    heads=''.join(f'<th><a href="/ship/{esc(s.get("ID"))}">{esc(s.get("EnglishName"))}</a><img src="/assets/shipIcon{esc(s.get("ID"))}.png" loading="lazy" onerror="this.hidden=true" alt=""></th>' for s in selected)
    trs=[]
    for key,label in fields.items():
        maxval=max([_float(s,key) for s in selected] or [1]) or 1
        tds=[]
        for s in selected:
            v=_float(s,key);width=max(0,min(100,round(v/maxval*100,1)))
            tds.append(f'<td><strong>{esc(s.get(key,"—"))}</strong><div class="bartrack"><div class="barfill" data-percent="{width}"></div></div></td>')
        trs.append('<tr><th>'+esc(label)+'</th>'+''.join(tds)+'</tr>')
    intro='<p>Compare the untouched catalog values before you equip upgrades or crew. A higher bar simply means a larger recorded number, not necessarily a better ship for your playstyle.</p>'
    body=intro+form+'<div class="table-wrap"><table class="comparison"><thead><tr><th>Attribute</th>'+heads+'</tr></thead><tbody>'+''.join(trs)+'</tbody></table></div>'
    body+='<p class="notice">Comparison values are raw client data. They do not include a live loadout, your skills, consumables or unverified server modifiers.</p>'
    return shell('Ship comparison',body,'Shipyard','Choose up to three ships and explore their actual catalog values.')


def shipyard_tree_page(conn,ship_list,shell):
    ships=ship_list(conn);groups={}
    for x in ships:groups.setdefault(str(x.get('ShipRank') or x.get('Rank') or 'Unknown'),[]).append(x)
    nodes=[]
    def rank_key(item):
        try:return int(float(item[0]))
        except ValueError:return 99
    for rank,members in sorted(groups.items(),key=rank_key):
        icons=''.join(f'<a class="fleet-node" href="/ship/{esc(s.get("ID"))}" title="{esc(s.get("EnglishName"))}"><img src="/assets/shipIcon{esc(s.get("ID"))}.png" onerror="this.hidden=true" loading="lazy" alt=""><span>{esc(s.get("EnglishName"))}</span></a>' for s in members)
        nodes.append(f'<section class="fleet-lane"><header><small>Game catalog</small><h2>Ship rank {esc(rank)}</h2><p>{len(members)} catalog entries</p></header><div class="fleet-nodes">{icons}</div></section>')
    body='''<section class="shipyard-banner"><h2>Shipyard atlas</h2><p>Browse the original ship roster by its in-game rank. This page uses extracted shipyard artwork and preserves the ship records, but is <b>not</b> a claim that the layout reproduces the exact in-game unlock graph.</p></section>
    <div class="notice">Unlock links are intentionally absent: progression dependencies and numeric icon assignments require confirmation against the client's shipyard interface and rules.</div>
    <label class="search"><span>Search the shipyard atlas</span><input data-filter=".fleet-node" placeholder="Find a ship"></label>'''+''.join(nodes)
    return shell('Shipyard atlas',body,'Shipyard','Explore recovered shipyard artwork and rank groupings.')


def guide_page(conn,rows,shell,slug):
    outlines={
      'cannons':('Cannons and penetration','A cannon describes how the shot begins. Damage after impact involves the projectile, the target and game rules that are not fully recovered.',[
        ('Choosing a cannon','The extracted cannon catalog records poundage, penetration, cooldown, range, scatter and sometimes a mortar splash radius. These are distinct properties—not one single “damage” number.'),
        ('What penetration means','Penetration is recorded in the client, but the complete rule that converts it into hull HP loss or deflection has not been recovered. Avoid comparing a cannon’s penetration directly with a ship’s armor as though the units were confirmed identical.'),
        ('Special weapons','Mortars and special cannon classes can behave differently. The separate splash fields should be displayed, but not turned into HP estimates without the actual impact rules.')],('Cannons',('Poundage','Penetration','Distance','Cooldown','Scatter','SplashRadius'))),
      'ammunition':('Ammunition and damage effects','The projectile matters as much as the gun. Choose a round for the effect you need, then test it against the specific target.',[
        ('What ammo changes','The game catalog records DamageFactor, Penetration, DamageToSailes, CrewDamage, Speed, MassKg and special Effects. Those are inputs and named effects; they do not expose the complete final damage equation.'),
        ('Sail and crew damage','Sail and crew properties are kept separate from hull damage. The damage simulator should keep those outcomes separate too.'),
        ('Special cases','Overpenetration and burning-related effects need their own eligibility and stacking rules before we can say when they trigger.')],('CannonBalls',('DamageFactor','Penetration','DamageToSailes','CrewDamage','Speed','Effects'))),
      'armor':('Armor, angles and vulnerability','A ship’s armor is only one of the variables that determines a successful hit.',[
        ('Recovered armor calculation','The client getter computes BasicArmor × (1 + percentage armor bonus) + flat armor bonus. For a player ship, BasicArmor also has a recovered relation to PatArmor and AllStatFine.'),
        ('Where the ball hits','A shot arriving almost perpendicular to a surface and one arriving along it have different geometric impact angles. Whether the game uses that angle for ricochet, penetration or damage still needs proof.'),
        ('Why maps have different labels','The 3D viewer can draw a verified geometry-angle map right now. A true HP vulnerability map needs the exact hitboxes and damage rules or controlled in-game measurements.')],(None,())),
      'wind':('Sailing and wind','Wind direction matters, but the client’s wind component should not be mistaken for the ship’s final speed.',[
        ('Reading the wind','A relative wind angle measures the direction of the wind compared with the ship’s heading. The recovered WindRoses records contain angle boundaries for different handling profiles.'),
        ('Why ships behave differently','Base speed, mobility, sail trim, upgrades and temporary effects may all change the result. Compare the ship’s raw catalog numbers before drawing conclusions.'),
        ('A controlled test','Hold ship, sail setting and upgrades constant. Change the wind angle and record actual speed; the lab can chart observations and compare them with the recovered component.')],('WindRoses',('GreenLeft','GreenRight','HeadwindLeft','HeadwindRight','FordewindFineEdge'))),
      'equipment':('Fitting ships: crew, upgrades and designs','Build experiments around specific equipment and record which bonuses you have enabled.',[
        ('Upgrades','Upgrade entries carry effects and category metadata. Choosing an item in the Codex does not establish that a particular ship can equip it or that it occupies a particular slot.'),
        ('Special crew','Crew descriptions and effect fields are recovered. Whether two specific crew members stack or can be installed together must be checked.'),
        ('Appearances','Ship designs can replace particular material textures. That is an appearance relationship; a design may also have a separate effect field, but the two should not be confused.')],('ShipUpgradesNew',('Category','EffectsBoost','WearType'))),
      'hitboxes':('Ship collision and damage zones','Collision geometry is often different from the artwork players see.',[
        ('What the game records','The client distinguishes Corpus, Mast and Sail hitboxes, and some assets contain candidate helper meshes or external collision models.'),
        ('Why a box may appear','A bounding box can accelerate broad-phase collision detection without representing the exact surface a cannonball strikes. The viewer must label such shapes as candidates until we recover their exact role.'),
        ('What to verify','Trace the original model-node transforms into the collision test and check that the same shape is used by the projectile hit-resolution path.')],(None,()))}
    item=outlines.get(slug)
    if not item:return None
    title,lede,sections,table=item
    body='<div class="guide-lede">'+esc(lede)+'</div>'
    body+=''.join('<section class="section panel"><h2>'+esc(t)+'</h2><p>'+esc(p)+'</p></section>' for t,p in sections)
    if table[0]:
        dataset,keys=table;entries=rows(conn,dataset)
        body+='<section class="section"><h2>Compare the actual game records</h2><p>Use these extracted values as a reference. They are not final server-calculated outcomes.</p><div class="table-wrap"><table class="comparison"><thead><tr><th>Name</th>'+''.join('<th>'+esc(k)+'</th>' for k in keys)+'</tr></thead><tbody>'
        for r in entries[:120]:
            body+='<tr><th>'+esc(r.get('EnglishName') or r.get('Name') or r.get('ID'))+'</th>'+''.join('<td>'+esc(str(r.get(k,''))[:95])+'</td>' for k in keys)+'</tr>'
        body+='</tbody></table></div></section>'
    body+='<div class="notice">Source: recovered local WoSB client catalog and selected client-code evidence. Where mechanics depend on server-only behavior, the guide says so rather than supplying invented values.</div>'
    body+='<a class="button" href="/guides">Browse more mechanics guides</a>'
    return shell(title,body,'Guides','Readable explanation first, with original extracted fields available for comparison.')


def guide_index_page(shell):
    items=[('cannons','Cannons and penetration','What each cannon property measures and what remains unknown'),
           ('ammunition','Ammunition and damage effects','Hull, sail, crew, effects and special projectiles'),
           ('armor','Armor, angles and vulnerability','Recovered armor getter, collision geometry and impact maps'),
           ('wind','Sailing and wind','Compare wind roses, ship handling and observations'),
           ('equipment','Fitting and appearance','Crew, upgrades, designs and their stated effects'),
           ('hitboxes','Hitboxes and collision','What the client shapes mean and how they are used')]
    body='<section class="cards">'+''.join(f'<a class="card" href="/guide/{slug}"><h2>{esc(name)}</h2><p>{esc(desc)}</p></a>' for slug,name,desc in items)+'</section>'
    return shell('Game mechanics guides',body,'Guides','Understand the game using original client records, not guessed mechanics.')


def emulator_page(shell):
    body='''<section class="panel"><h2>An independent local game-research sandbox</h2><p>The sandbox can create vessels, step an idealized local world clock, record positions and replay damage values you enter from measured tests. It deliberately does <b>not</b> communicate with official WoSB servers or claim to implement the game's protocol.</p><div class="notice">World physics here are a test scaffold, not recovered WoSB sailing behavior. The authentic hit-resolution and networking requirements are unresolved.</div></section>
    <section class="section two"><div class="panel"><h2>Available now</h2><p>Versioned world snapshots, ship state, deterministic movement, observed-damage fixtures, build evidence and passive packet-capture analysis using user-provided recordings.</p></div><div class="panel"><h2>Needed before a real local server</h2><p>Reliable state transitions, message schemas derived from authorized observation, original sailing and combat rules, inventory, NPC behavior, and integration tests against authorized test clients.</p></div></section>'''
    return shell('Offline simulation research',body,'Research','The path toward a local test world, with evidence boundaries.')


def equipment_page(conn,rows,shell):
    categories=[('Crew_Special','Special crew','Recovered crew benefits, roles and descriptions',('TypeEnglish','Effect','EnglishDescription')),
                ('ShipUpgradesNew','Ship upgrades','Equipment and structural enhancements',('Category','EffectsBoost','EnglishDescription')),
                ('CaptainSkills','Captain skills','Skill effects and unlock descriptions',('Effect','EnglishDescription')),
                ('ShipDesingElements','Ship designs & decorations','Available appearance designs, flags, sails and decorative elements',('Category','ShipId','EnglishDescription'))]
    contents=['<div class="notice">Every item below is taken from the client catalog. This is an information library; fitting-slot restrictions, drop locations and additive effects may require validation.</div>',
              '<label class="search"><span>Filter names and descriptions</span><input data-filter=".equipment-entry" placeholder="Search special crew, upgrades, skills or designs"></label>']
    for dataset,title,summary,fields in categories:
        entries=rows(conn,dataset)
        cards=[]
        for item in entries:
            name=item.get('EnglishName') or item.get('Name') or str(item.get('ID','Unidentified'))
            desc=str(item.get('EnglishDescription') or '')[:700]
            metadata=' '.join(f'<span class="tag">{esc(k)}: {esc(str(item.get(k,"—"))[:90])}</span>' for k in fields if item.get(k) not in ('',None))
            detail=esc(json.dumps({k:v for k,v in item.items() if not k.startswith('_')},ensure_ascii=False,indent=2))
            cards.append(f'<article class="equipment-entry panel"><h3>{esc(name)}</h3><p>{esc(desc)}</p><div>{metadata}</div><details><summary>Original client record and source</summary><p>Build: {esc(item.get("_build"))} · Source: {esc(item.get("Source","unknown"))}</p><pre>{detail}</pre></details></article>')
        contents.append(f'<section class="section" id="{esc(dataset)}"><h2>{esc(title)}</h2><p>{esc(summary)} · {len(entries)} catalog entries</p><div class="equipment-grid">'+''.join(cards)+'</div></section>')
    return shell('Equipment & appearance library',''.join(contents),'Equipment','The actual recovered crew, upgrades, skills and designs in one searchable place.')
