"""Local-only, read-only web encyclopedia and mechanics notebook.

No public bind, external CDN, cookies, telemetry or game-server requests.
Source articles and images remain in the Workbench catalog/install.
"""
from __future__ import annotations
import html
from contextlib import closing
import json
import math
import mimetypes
import re
import sqlite3
import threading
import webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

from workbench_db import bundled_path, home, VERSION
from sailing_lab import wind_speed_component

ROOT = Path(__file__).resolve().parent
STATIC = bundled_path('wiki_site')


def esc(value):return html.escape(str(value if value is not None else ''),quote=True)


def _num(value,default=0.0):
    """Catalog numbers can be strings, blanks or junk; never let one crash a page."""
    try:
        number=float(value)
        return number if math.isfinite(number) else default
    except (TypeError,ValueError):
        return default


def _rank(value):
    try:return int(float(value))
    except (TypeError,ValueError):return 99


def _readonly(db_path):
    """Open the catalog read-only. Path.as_uri() percent-encodes characters such as
    '#', '?' or '%' in Windows user names, which broke the raw 'file:' + path form."""
    return sqlite3.connect(Path(db_path).resolve().as_uri()+'?mode=ro',uri=True)
def select_rows(conn, dataset, limit=1000):
    return [dict(x) for x in conn.execute('''SELECT name,source_root,raw_json FROM records
              WHERE dataset=? ORDER BY CASE source_root WHEN 'Game' THEN 0 ELSE 1 END,name LIMIT ?''',(dataset,limit))]

def rows(conn,dataset):
    seen=set();out=[]
    for row in select_rows(conn,dataset):
        rec=json.loads(row['raw_json']);k=str(rec.get('ID',rec.get('Name',rec.get('SourceRecord',row['name']))))
        if k in seen:continue
        seen.add(k);rec['_build']=row['source_root'];out.append(rec)
    return out

def ship_list(conn):
    result=rows(conn,'ShipsToPlay')
    result.sort(key=lambda x:(_rank(x.get('ShipRank') or x.get('Rank') or 0),str(x.get('EnglishName','')).casefold()))
    return result

def image_for_ship(ship):
    # The ID-to-icon correspondence needs game-code confirmation, so never use
    # it as proof of an official shipyard node/icon assignment.
    try: n=int(ship.get('ID'))
    except (TypeError,ValueError):return '/assets/shipyard_background.png'
    return f'/assets/shipIcon{n}.png'

def markdown_safe(src):
    """Safe wiki markdown (shared renderer in wiki_engine; no embedded HTML/scripts)."""
    import wiki_engine
    return wiki_engine.render_markdown(src)


def shell(title,body,active='',subtitle=''):
    links=[('Home','/'),('Shipyard','/shipyard'),('Research Center','/studio'),('Mechanics Lab','/mechanics'),('Guides','/guides'),('Wiki Articles','/articles')]
    nav=''.join(f'<a class="{"active" if active==label else ""}" href="{url}">{label}</a>' for label,url in links)
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} · WoSB Codex</title><link rel="stylesheet" href="/static/style.css"></head>
<body><header class="topbar"><a class="brand" href="/">⚓ WoSB <b>CODEX</b></a><nav>{nav}</nav><small>LOCAL · v{VERSION}</small></header>
<main><div class="pagehead"><div><span class="eyebrow">World of Sea Battle · local encyclopedia</span><h1>{esc(title)}</h1><p>{esc(subtitle)}</p></div></div>{body}</main>
<footer>Fan-made offline research • Original client files determine content • Measurements are distinguished from unverified estimates • No game servers contacted</footer>
<script src="/static/app.js"></script><script src="/static/next.js"></script></body></html>'''


def home_page(conn):
    count=len(ship_list(conn));article_count=conn.execute('SELECT COUNT(*) FROM articles').fetchone()[0]
    body=f'''<section class="hero"><div><span class="eyebrow">Explore the game, not its guesswork</span>
    <h2>Every ship. Every system. One place.</h2><p>Browse ships using recovered game artwork, compare their equipment, explore wind and combat research, and read clear articles with original source evidence when available.</p>
    <div class="actions"><a class="button primary" href="/shipyard">Explore the shipyard</a><a class="button" href="/mechanics">Open Mechanics Lab</a><a class="button" href="/compare">Compare ships</a><a class="button" href="/studio">Research Center</a></div></div></section>
    <div class="metricgrid"><div><strong>{count}</strong><small>cataloged playable ships</small></div><div><strong>{article_count}</strong><small>local wiki articles</small></div><div><strong>42</strong><small>cannon records in research catalog</small></div><div><strong>21</strong><small>ammunition types in research catalog</small></div></div>
    <section class="section"><h2>Explore the codex</h2><div class="cards">
    <a class="card" href="/shipyard"><h3>Shipyard and loadouts</h3><p>Choose a ship and inspect its stats, appearances, cannon and equipment options.</p></a>
    <a class="card" href="/mechanics"><h3>Mechanics Lab</h3><p>Understand wind angles, ship handling and shot-angle research with interactive charts.</p></a>
    <a class="card" href="/articles"><h3>Game encyclopedia</h3><p>Readable guides, definitions and mechanics articles with citations to the extracted client.</p></a>
    <a class="card" href="/studio"><h3>Research Center</h3><p>See which mechanics are documented and which still need evidence or testing.</p></a></div></section>'''
    return shell('Your World of Sea Battle Codex',body,'Home','The game’s actual recovered artwork and data — organized for players.')


def shipyard_page(conn):
    ships=ship_list(conn);groups={}
    for s in ships:groups.setdefault(str(s.get('ShipRank',s.get('Rank','Unranked'))),[]).append(s)
    sections=[]
    for rank,items in sorted(groups.items(),key=lambda x:_rank(x[0])):
        cards=[]
        for ship in items:
            shipid=ship.get('ID','');name=ship.get('EnglishName') or f'Ship {shipid}'
            cards.append(f'''<a class="ship" href="/ship/{esc(shipid)}"><img loading="lazy" onerror="this.style.display='none'" src="{image_for_ship(ship)}" alt="Candidate ship icon for {esc(name)}"><strong>{esc(name)}</strong><small>{esc(ship.get('SubtypeEnglish') or ship.get('Type') or 'Ship')} · {esc(ship.get('Health'))} HP</small></a>''')
        sections.append(f'<section class="section"><h2>Ship rank {esc(rank)}</h2><div class="shipgrid">{"".join(cards)}</div></section>')
    body='''<section class="shipyard-banner"><h2>Choose your vessel</h2><p>Ship ranks and categories come from the game catalog. The original shipyard background is used here. Unlock links are intentionally absent until verified from game files.</p></section>
    <div class="notice">Artwork with matching numeric icon names is a candidate association; exact in-game shipyard icon mapping and unlock links still require validation.</div>
    <p><a class="button" href="/shipyard-atlas">Browse shipyard atlas</a> <a class="button" href="/compare">Compare ships</a><a class="button" href="/studio">Research Center</a></p><label class="search"><span>Find a ship</span><input placeholder="Filter by ship name or type" data-filter=".ship"></label>'''+''.join(sections)
    return shell('Shipyard',body,'Shipyard',f'{len(ships)} ships from the extracted catalog, organized by rank')


def ship_page(conn,ship_id):
    ship=next((s for s in ship_list(conn) if str(s.get('ID'))==str(ship_id)),None)
    if ship is None:return None
    basics=next((b for b in rows(conn,'ShipsBasics') if str(b.get('ID'))==str(ship.get('StaticInfoID'))),{})
    name=ship.get('EnglishName') or ('Ship '+str(ship_id));stats=['Health','Armor','BasicSpeed','BasicMobility','CapacityCg','BaseCrewPlaces','PlacesForUnitsCount','Rank']
    details=''.join(f'<div><small>{esc(k.replace("Cg",""))}</small><strong>{esc(ship.get(k,"Unknown"))}</strong></div>' for k in stats)
    intro=esc(ship.get('EnglishDescription') or 'This ship has a catalog entry. A descriptive play guide can be written as additional mechanics become verified.')
    same_rank=[s for s in ship_list(conn) if str(s.get('ShipRank',s.get('Rank'))) == str(ship.get('ShipRank',ship.get('Rank')))]
    peers_health=[_num(s.get('Health')) for s in same_rank];peers_armor=[_num(s.get('Armor')) for s in same_rank]
    comparison=''
    for key,values in [('Health',peers_health),('Armor',peers_armor)]:
        top=max(values or [1]) or 1
        value=_num(ship.get(key))
        pct=min(100,max(0,100*value/top))
        comparison+=f'<div class="statbar"><strong>{esc(key)}: {value:g}</strong><div class="bartrack"><div class="barfill" data-percent="{pct:.1f}"></div></div><small>Compared with the highest {esc(key.lower())} in this ship rank ({top:g}); not a combat ranking</small></div>'

    try:viewer_row=conn.execute('SELECT html_path FROM ship_viewers WHERE ship_id=? ORDER BY created_utc DESC LIMIT 1',(str(ship_id),)).fetchone()
    except sqlite3.OperationalError:viewer_row=None
    registered=Path(viewer_row['html_path']).resolve() if viewer_row else None
    viewer_available=bool(registered and (home()/'Viewers').resolve() in registered.parents and registered.is_file())
    viewer_link=(f'<a class="button primary" href="/viewer/{esc(ship_id)}/index.html">Open recovered 3D model</a>'
                 if viewer_available else '<p>No recovered model registered yet. Export one from Workbench → Ship 3D.</p>')
    body=f'''<a class="back" href="/shipyard">← Back to shipyard</a><div class="shiphead"><img onerror="this.style.display='none'" src="{image_for_ship(ship)}" alt="Candidate game ship icon"><div><h2>{esc(name)}</h2><p>{intro}</p><p><span class="tag">{esc(ship.get('SubtypeEnglish',ship.get('Type','Ship')))}</span> <span class="tag">Build: {esc(ship.get('_build'))}</span></p></div></div>
    <section class="section"><h2>At a glance</h2><div class="metricgrid">{details}</div><div class="notice">Stats are actual extracted client fields, not adjusted values for a particular player or loadout.</div></section>
    <section class="section"><h2>How its stats compare</h2><div class="panel">{comparison}</div></section>
    <section class="section two"><div class="panel"><h2>Appearance and structure</h2><p>Client model: <code>{esc(basics.get('ModelName','Not linked'))}</code></p><p>Original hull bounds: <code>{esc(basics.get('CorpusHitboxSize','Unknown'))}</code></p><p>Use the desktop Ship 3D viewer for detailed textured models and mesh inspection.</p></div>
    <div class="panel"><h2>Build this ship</h2><p>Select real cannon and ammunition types; inspect actual upgrade and skill descriptions. The calculator does not pretend an HP result is verified.</p><a class="button primary" href="/mechanics?ship={esc(ship_id)}">Open loadout and ballistics</a> <a class="button" href="/compare?ship={esc(ship_id)}">Compare this ship</a></div></section>
    <section class="section"><h2>Local 3D model</h2><p>To explore the real decoded model and camera-directed impact-angle map, first export a viewer for this ship from Workbench's Ship 3D page. If one is registered it appears below.</p><div id="ship-viewer-link">{viewer_link}</div></section>
    <section class="section"><h2>How to use this ship</h2><p>Compare the ship's armor, health, handling and carrying capacity with other vessels of the same rank. Equipment and crew can change the result; the numbers above are the unmodified values preserved in the client catalog.</p><p>Open the Mechanics Lab to build a tentative fitting and explore shot angles. Look for the evidence labels before treating a damage prediction as exact.</p></section>
    <section class="section"><h2>Catalog details</h2><details><summary>All recovered ship properties</summary><pre>{esc(json.dumps({k:v for k,v in ship.items() if k!='_build'},indent=2,ensure_ascii=False))}</pre></details></section>'''
    return shell(name,body,'Shipyard','Ship specifications, appearance and equipment research')


def weapon_page(conn):
    guns=rows(conn,'Cannons');ammo=rows(conn,'CannonBalls')
    def card(item,isammo=False):
        keys=['DamageFactor','Penetration','DamageToSailes','CrewDamage'] if isammo else ['Poundage','Penetration','Distance','Cooldown']
        props=''.join(f'<span>{esc(k)}: <b>{esc(item.get(k,"—"))}</b></span>' for k in keys)
        return f'<div class="weapon"><h3>{esc(item.get("EnglishName","Unidentified"))}</h3><div class="specs">{props}</div><p>{esc(str(item.get("EnglishDescription") or "")[:340])}</p></div>'
    body='<label class="search"><span>Find weapons or ammunition</span><input data-filter=".weapon" placeholder="Filter the catalog"></label>'
    body+='<section class="section"><h2>Cannons and mortars</h2><div class="cards">'+''.join(card(g) for g in guns)+'</div></section>'
    body+='<section class="section"><h2>Ammunition</h2><div class="cards">'+''.join(card(a,True) for a in ammo)+'</div></section>'
    kegs=rows(conn,'PowderKegs')
    if kegs:body+='<section class="section"><h2>Powder kegs and area effects</h2><p>These are extracted per-item values; they do not prove final HP damage after armor, distance or effects.</p><div class="cards">'+''.join('<div class="weapon"><h3>'+esc(k.get('EnglishName') or k.get('ID') or 'Keg')+'</h3><p>Base damage field: '+esc(k.get('Damage','Unknown'))+' · Radius: '+esc(k.get('DamageRadius','Unknown'))+' · Trigger radius: '+esc(k.get('TriggerRadius','Unknown'))+'</p><p>'+esc(str(k.get('EnglishDescription') or ''))+'</p></div>' for k in kegs)+'</div></section>'
    return shell('Weapons and ammunition',body,'Weapons',f'{len(guns)} cannon records and {len(ammo)} ammunition types')


def mechanics_page():
    body='''<div class="tabs"><a href="#ballistics">Damage &amp; ballistics</a><a href="#loadout">Ship fitting</a><a href="#sailing">Sailing &amp; wind</a><a href="#sources">What the data proves</a></div>
    <section class="section panel" id="ballistics"><h2>Shot-angle research</h2><p>Choose equipment and aim around the target. The colored map displays the <b>geometric angle of approach</b>; it is not an in-game HP damage heatmap until we validate the hit-resolution formula.</p>
    <div class="two"><div><canvas id="heatmap" width="750" height="360" aria-label="Ship-region angle exposure map"></canvas><p class="sub">Rotate the camera to change where the incoming shot originates. Darker bands indicate more oblique approach to an illustrative hull surface.</p></div>
    <div class="inputs"><label>Target ship<select id="labShip"></select></label><label>Cannon<select id="labCannon"></select></label><label>Ammunition<select id="labAmmo"></select></label>
    <label>Camera direction around ship: <strong id="viewDegrees">0°</strong><input type="range" min="0" max="359" value="0" id="viewYaw"></label>
    <label>Elevation: <strong id="elevDegrees">0°</strong><input type="range" min="-40" max="70" value="0" id="viewElevation"></label>
    <label>Range (game-scale): <input id="shotRange" type="number" min="0" value="150"></label>
    <label>Experimental percentage armor input (0.1 = +10%):<input id="armorPercent" type="number" step="0.01" value="0"></label>
    <label>Experimental flat armor input:<input id="armorFlat" type="number" step="0.1" value="0"></label>
    <p class="sub">Click a marked region to select a target and inspect the angle.</p></div></div>
    <div class="result" id="labResult">Select a target region to inspect extracted cannon and ship values.</div>
    <div class="panel"><h3>Record an actual in-game shot</h3><p>Enter the HP lost during a controlled test. It will be saved in this browser as a measured result, never substituted for the game’s missing formula.</p>
    <div class="compare-controls"><label>Measured hull HP lost<input id="measuredHP" type="number" min="0" step="0.01" placeholder="For example: 150"></label><button id="recordShot" type="button">Record observation</button><button id="exportShots" type="button">Export measured shots</button></div><pre id="shotLog" class="result">No local observations yet.</pre></div>
    <div class="notice">Only client-property armor calculations are verified. Penetration resolution, shot HP damage, ricochet, mortar splash, fire and barrel damage still require additional game code or controlled measurements.</div></section>
    <section class="section panel" id="loadout"><h2>Ship fitting notebook</h2><p>Choose special crew, ship upgrades, captain skills and designs from the real extracted catalog. The choices are a planning notebook and do not assert installation eligibility or hidden stacking rules.</p>
    <div class="two"><div class="inputs"><label>Special crew<select id="labCrew"></select></label><label>Ship upgrade<select id="labUpgrade"></select></label><label>Captain skill<select id="labSkill"></select></label><label>Appearance design<select id="labDesign"></select></label></div>
    <div><div class="result" id="loadoutResult">Select items to compare their extracted descriptions and effects.</div>
    <div class="panel"><h3>Saved fitting notebook</h3><p>Collect several crew, upgrades and skills for the chosen ship, then export the plan. Slot legality and stacking are not assumed.</p>
    <div class="btnrow"><button id="addCrew" type="button">Add crew</button><button id="addUpgrade" type="button">Add upgrade</button><button id="addSkill" type="button">Add skill</button><button id="saveFitting" type="button">Export fitting</button></div><div id="fittingItems" class="fitting-items"></div></div></div></div></section>
    <section class="section panel" id="sailing"><h2>Wind and sailing laboratory</h2><p>Explore the recovered wind-rose component as the direction changes. This is a dimensionless internal calculation, not actual ship speed in knots.</p>
    <div class="two"><svg viewBox="0 0 640 280" role="img" aria-label="Recovered wind component by relative wind angle" id="windChart"></svg>
    <div><label>Relative wind angle: <strong id="windDegrees">0°</strong><input id="windAngle" type="range" min="-180" max="180" step="5" value="0"></label><div class="result" id="windValue"></div>
    <div class="panel"><h3>Actual sailing measurements</h3><p>Keep the ship and sails constant, record the in-game speed you observe at this relative wind angle, and compare later.</p><label>Observed speed (in-game units)<input type="number" id="observedSpeed" min="0" step="0.1"></label><button id="recordWind" type="button">Record speed</button> <button id="exportWind" type="button">Export sailing data</button><pre class="result" id="windLog"></pre></div>
    <p class="sub">Original client methods: <code>WindingDotAtAngle</code> and <code>SpeedByWind</code>. Actual ship movement also depends on sails, physics, effects and server behavior.</p></div></div></section>
    <section class="section panel" id="sources"><h2>Where these numbers come from</h2><p>Weapon and ship values come from the mined game data. The recovered armor getter is <code>BasicArmor × (1 + Bonus 5) + Bonus 13</code>; basic armor for player ships is <code>PatArmor × (1 − AllStatFine)</code>.</p><p>Click-to-impact 3D aiming is available in the desktop model viewer. The camera direction determines the incoming ray; it does not establish a hidden game damage multiplier.</p>
    <details><summary>Technical evidence for researchers</summary><p><code>Common.dll</code> tokens <code>0x06001f6f</code>, <code>0x06001ee8</code>. Further validation must check the appropriate game build.</p></details></section>'''
    return shell('Mechanics Lab',body,'Mechanics Lab','One place for ballistics, armor, aiming, sailing and wind.')


def _has_table(conn,name):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE name=?",(name,)).fetchone() is not None


def articles_page(conn,query=''):
    import wiki_engine
    form=('<form method="get" class="search" action="/articles"><input name="q" placeholder="Search guides, mechanics, ships, protocol and more" value="'
          +esc(query)+'"><button class="button primary">Search</button></form>')
    side=''
    if _has_table(conn,'article_tags'):
        cloud=wiki_engine.tag_cloud(conn,40)
        if cloud:side='<p class="tags">'+' '.join(f'<a class="tag" href="/tag/{esc(t)}">#{esc(t)} <small>{n}</small></a>' for t,n in cloud)+'</p>'
    side+='<p><a class="button" href="/recent">Recently changed</a></p>'
    if query:
        hits=wiki_engine.search(conn,query,limit=200)
        items=''.join(f'<a href="/article/{esc(h["slug"])}"><strong>{esc(h["title"])}</strong><small>{esc(h["section"])} · '
                      +esc(h["snippet"]).replace('[','<mark>').replace(']','</mark>')+'</small></a>' for h in hits)
        body=form+side+'<section class="section"><div class="articles">'+(items or '<p>No matches.</p>')+'</div></section>'
        return shell('The encyclopedia',body,'Wiki Articles',f'{len(hits)} articles matched (ranked by relevance).')
    results=conn.execute("SELECT slug,title,section,review_status,substr(body,1,210) abstract FROM articles ORDER BY section,title LIMIT 2000").fetchall()
    groups={}
    for row in results:groups.setdefault(row['section'],[]).append(row)
    sections=''.join('<section class="section"><h2>'+esc(group)+'</h2><div class="articles">'+''.join(f'<a href="/article/{esc(r["slug"])}"><strong>{esc(r["title"])}</strong><small>{esc(r["review_status"])} · {esc((r["abstract"] or "")[:120])}</small></a>' for r in records)+'</div></section>' for group,records in sorted(groups.items()))
    return shell('The encyclopedia',form+side+sections,'Wiki Articles',f'{len(results)} articles. Content may include source-only or needs-review pages.')


def article_page(conn,slug):
    import wiki_engine
    row=conn.execute('SELECT * FROM articles WHERE slug=?',(slug,)).fetchone()
    if not row:return None
    rendered=wiki_engine.render_markdown(row['body'],wiki_engine.link_resolver(conn))
    toc=wiki_engine.table_of_contents(row['body'])
    toc_html=('<nav class="toc"><strong>Contents</strong>'+''.join(f'<a class="lvl{lvl}" href="#{esc(a)}">{esc(t)}</a>' for lvl,t,a in toc)+'</nav>') if len(toc)>2 else ''
    extra=''
    if _has_table(conn,'article_links'):
        back=wiki_engine.backlinks(conn,row['id'])
        if back:extra+='<section class="section"><h2>Pages linking here</h2><p>'+' · '.join(f'<a href="/article/{esc(b["slug"])}">{esc(b["title"])}</a>' for b in back)+'</p></section>'
        revs=len(wiki_engine.revisions(conn,row['id']))
        extra+=f'<p class="sub">Last updated {esc(row["updated_utc"])} · {revs} earlier revision(s) kept in Workbench</p>'
    body=(f'<a class="back" href="/articles">← All articles</a>{toc_html}<article class="article">{rendered}'
          f'<details class="sources"><summary>Source and review information</summary><p>Review status: {esc(row["review_status"])}<br>Source: {esc(row["source_kind"])}<br>Reference: {esc(row["source_ref"])}</p></details></article>'+extra)
    return shell(row['title'],body,'Wiki Articles',row['section'])


def tag_page(conn,tag):
    import wiki_engine
    rows=wiki_engine.articles_with_tag(conn,tag) if _has_table(conn,'article_tags') else []
    items=''.join(f'<a href="/article/{esc(r["slug"])}"><strong>{esc(r["title"])}</strong><small>{esc(r["section"])}</small></a>' for r in rows)
    return shell('#'+tag,'<a class="back" href="/articles">← All articles</a><div class="articles">'+(items or '<p>No articles with this tag.</p>')+'</div>','Wiki Articles',f'{len(rows)} tagged articles')


def recent_page(conn):
    import wiki_engine
    rows=wiki_engine.recent_changes(conn,60)
    items=''.join(f'<a href="/article/{esc(r["slug"])}"><strong>{esc(r["title"])}</strong><small>{esc(r["updated_utc"])} · {esc(r["section"])} · {esc(r["review_status"])}</small></a>' for r in rows)
    return shell('Recently changed','<div class="articles">'+items+'</div>','Wiki Articles','The newest edits and generated pages')


def research_page():
    body='''<div class="cards"><div class="card"><h3>Recover Everything</h3><p>Use the desktop Workbench button to scan local clients, decode supported models and textures, preserve original source assets, index readable client methods, and build an audit ledger.</p></div>
    <div class="card"><h3>Review-only ZIPs</h3><p>After a recovery, Workbench creates small <code>WoSB-Review-Part-*.zip</code> archives with unresolved issues and decoder errors—without resending successfully decoded images.</p></div>
    <div class="card"><h3>Network Research Lab</h3><p>Analyze user-captured packet captures and record game-event observations. Keep transport decoding and evidence separate from speculative game state. No active server interception or login bypass is performed.</p></div>
    <div class="card"><h3>Offline server emulator research</h3><p>Develop an independent, local simulation from verified gameplay data, protocol observations and deterministic fixtures. Start with navigation, inventories and test combat, and label any unknown mechanics. <a href="/emulator">See the sandbox research page</a>.</p></div></div>
    <section class="section panel"><h2>What counts as complete?</h2><p>A successful file read does not prove that its model, shader, hitbox, or gameplay rule is understood. Each recovered object should have its own status: decoded, referenced, visually compared, experimentally validated, or unresolved.</p><p>Scans never need to send all recovered images again. The review bundle prioritizes unknown formats, failed meshes and missing evidence.</p></section>'''
    return shell('Research and recovery',body,'Research','What Workbench has verified—and what we are still finding out.')


class WikiHandler(BaseHTTPRequestHandler):
    server_version='WoSBCodex/4.3'
    def log_message(self, fmt,*args):pass
    def send(self,blob,ctype='text/html; charset=utf-8',status=200):
        self.send_response(status);self.send_header('Content-Type',ctype);self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Cache-Control','no-store');self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'")
        self.send_header('Content-Length',str(len(blob)));self.end_headers();self.wfile.write(blob)
    def _host_allowed(self):
        """DNS-rebinding guard: only answer requests addressed to this loopback server."""
        host=(self.headers.get('Host') or '').strip().lower()
        if not host:return True
        name=host.split(']')[0]+']' if host.startswith('[') else host.rsplit(':',1)[0]
        return name in ('127.0.0.1','localhost','[::1]')

    def do_GET(self):
        if not self._host_allowed():
            return self.send(b'Forbidden host','text/plain',403)
        try:
            return self._get()
        except (BrokenPipeError,ConnectionResetError):
            return None
        except Exception as exc:
            # Previously an exception dropped the connection and the browser showed a blank page.
            try:return self.send(('Internal error: '+type(exc).__name__).encode('utf-8'),'text/plain; charset=utf-8',500)
            except OSError:return None

    def _get(self):
        route=urlparse(self.path);path=unquote(route.path)
        if path.startswith('/viewer/'):
            # Serve only exact registered viewers from Workbench's own Viewers folder.
            # Prevent arbitrary file:// access, path traversal, and escape from local data root.
            bits=path.strip('/').split('/')
            if len(bits)<3 or not re.fullmatch(r'[0-9]{1,10}',bits[1]):
                return self.send(b'Not found','text/plain',404)
            with closing(_readonly(self.server.db_path)) as conn:
                try:row=conn.execute('SELECT html_path FROM ship_viewers WHERE ship_id=? ORDER BY created_utc DESC LIMIT 1',(bits[1],)).fetchone()
                except sqlite3.OperationalError:row=None
            if not row:return self.send(b'No saved 3D viewer for this ship; export one in Workbench first.','text/plain',404)
            registered=Path(row[0]).resolve()
            safe_root=(home()/'Viewers').resolve()
            if safe_root not in registered.parents or registered.suffix.casefold()!='.html':
                return self.send(b'Unsupported viewer location','text/plain',403)
            if len(bits)==3 and bits[2]=='index.html':target=registered
            elif len(bits)==4 and bits[2]==registered.stem+'-assets' and re.fullmatch(r'[a-zA-Z0-9_.-]+',bits[3]):
                target=registered.parent/bits[2]/bits[3]
            else:return self.send(b'Not found','text/plain',404)
            target=target.resolve()
            if safe_root not in target.parents or not target.is_file() or target.stat().st_size>150*1024*1024:
                return self.send(b'Not found or oversized','text/plain',404)
            return self.send(target.read_bytes(),mimetypes.guess_type(target.name)[0] or 'application/octet-stream')
        if path.startswith('/static/') or path.startswith('/assets/'):
            prefix='/assets/' if path.startswith('/assets/') else '/static/'
            relative=path[len(prefix):]
            target=(STATIC/('assets' if prefix=='/assets/' else '')/relative).resolve()
            if STATIC.resolve() not in target.parents or not target.is_file():return self.send(b'Not found','text/plain',404)
            return self.send(target.read_bytes(),mimetypes.guess_type(target.name)[0] or 'application/octet-stream')
        if path=='/api/catalog':
            catalog=json.loads(bundled_path('Research-Ballistics-Catalog.json').read_text(encoding='utf-8'))
            names=('Cannons','CannonBalls','ShipsToPlay','ShipUpgradesNew','CaptainSkills','Crew_Special','ShipDesingElements','PowderKegs','ShipsBasics')
            with closing(_readonly(self.server.db_path)) as conn:
                conn.row_factory=sqlite3.Row
                for name in names:
                    values=rows(conn,name)
                    if values:catalog.setdefault('datasets',{})[name]=values
            # The curated ship-design catalog has verified catalog ShipId links.
            # The general SQLite ShipDesingElements records do not retain ShipId,
            # so prefer the curated mapping for full-ship design eligibility.
            try:
                designs=json.loads(bundled_path('Research-Ship-Designs.json').read_text(encoding='utf-8'))
                catalog.setdefault('datasets',{})['ShipDesingElements']=designs.get('records',[])
            except (OSError,ValueError,TypeError):pass
            return self.send(json.dumps({'datasets':{k:catalog.get('datasets',{}).get(k,[]) for k in names},
                        'damage_verified':False,'ship_designs_evidence':'curated client ShipId mappings'}).encode('utf-8'),'application/json')
        if path=='/api/wind':
            data=[{'angle':a,'component':wind_speed_component(a)} for a in range(-180,181,5)]
            return self.send(json.dumps(data).encode(),'application/json')
        if path not in ('/','/shipyard','/shipyard-atlas','/compare','/guides','/equipment','/mechanics','/weapons','/articles','/research','/emulator','/studio','/workshop','/experiments','/ballistics-studio','/damage-research','/capture-research','/visual-parity','/preflight','/weapon-compare','/sailing-performance','/protocol-library','/recent') and not path.startswith(('/ship/','/article/','/guide/','/tag/')):
            return self.send(b'Not found','text/plain',404)
        with closing(_readonly(self.server.db_path)) as conn:
            conn.row_factory=sqlite3.Row
            if path=='/':out=home_page(conn)
            elif path=='/studio':
                from wiki_next import studio_page
                out=studio_page(conn,shell,ship_list,rows)
            elif path=='/workshop':
                from wiki_next import workshop_page
                out=workshop_page(conn,shell,ship_list,rows)
            elif path=='/experiments':
                from wiki_next import experiments_page
                out=experiments_page(shell)
            elif path=='/ballistics-studio':
                from wiki_next import ballistics_page
                out=ballistics_page(shell)
            elif path=='/damage-research':
                from wiki_next import damage_page
                out=damage_page(shell)
            elif path=='/capture-research':
                from wiki_next import capture_page
                out=capture_page(shell)
            elif path=='/visual-parity':
                from wiki_next import visual_page
                out=visual_page(shell)
            elif path=='/weapon-compare':
                from wiki_next import weapon_compare_page
                out=weapon_compare_page(conn,rows,shell,parse_qs(route.query).get('gun',[]))
            elif path=='/sailing-performance':
                from wiki_next import sailing_performance_page
                out=sailing_performance_page(conn,rows,shell)
            elif path=='/protocol-library':
                from wiki_next import protocol_library_page
                out=protocol_library_page(shell)
            elif path=='/preflight':
                from wiki_next import preflight_page
                from research_suite import setup_report
                out=preflight_page(shell,setup_report())
            elif path=='/shipyard':out=shipyard_page(conn)
            elif path.startswith('/ship/'):
                shipid=path[6:]
                if not re.fullmatch('[0-9]{1,10}',shipid):return self.send(b'Not found','text/plain',404)
                out=ship_page(conn,shipid)
            elif path=='/shipyard-atlas':
                from wiki_expanded import shipyard_tree_page
                out=shipyard_tree_page(conn,ship_list,shell)
            elif path=='/compare':
                from wiki_expanded import compare_page
                out=compare_page(conn,ship_list,shell,parse_qs(route.query).get('ship',[]))
            elif path=='/equipment':
                from wiki_expanded import equipment_page
                out=equipment_page(conn,rows,shell)
            elif path=='/guides':
                from wiki_expanded import guide_index_page
                out=guide_index_page(shell)
            elif path.startswith('/guide/'):
                from wiki_expanded import guide_page
                out=guide_page(conn,rows,shell,path[7:])
            elif path=='/emulator':
                from wiki_expanded import emulator_page
                out=emulator_page(shell)
            elif path=='/mechanics':out=mechanics_page()
            elif path=='/weapons':out=weapon_page(conn)
            elif path=='/articles':out=articles_page(conn,parse_qs(route.query).get('q',[''])[0][:100])
            elif path.startswith('/article/'):out=article_page(conn,path[9:])
            elif path.startswith('/tag/'):out=tag_page(conn,path[5:][:60])
            elif path=='/recent':out=recent_page(conn)
            else:out=research_page()
        return self.send(out.encode('utf-8') if out is not None else b'Not found',status=200 if out is not None else 404)


def serve(db_path=None,port=0,open_browser=True):
    path=Path(db_path or (home()/'Workbench.sqlite3')).resolve()
    if not path.is_file():raise FileNotFoundError('Wiki catalog not found: '+str(path))
    server=ThreadingHTTPServer(('127.0.0.1',port),WikiHandler)
    server.db_path=str(path)
    address=f'http://127.0.0.1:{server.server_port}/'
    threading.Thread(target=server.serve_forever,daemon=True).start()
    if open_browser:webbrowser.open(address)
    return server,address

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--db');parser.add_argument('--port',type=int,default=0)
    options=parser.parse_args()
    server,url=serve(options.db,options.port,open_browser=False);print('Open '+url,flush=True)
    try:threading.Event().wait()
    except KeyboardInterrupt:server.shutdown()
