"""v4.3 reader-first pages for the local Codex.

This is a local documentation/experiment UI, not a web connection to WoSB.
All catalog text is HTML escaped, all browser observations stay in localStorage
until explicitly exported, and numerical mechanics retain evidence labels.
"""
from __future__ import annotations
import html


def esc(value):return html.escape(str(value if value is not None else ''),quote=True)


def _section(title,text,link,cta,icon='◈'):
    return f'<a class="studio-card" href="{esc(link)}"><span class="studio-icon">{esc(icon)}</span><h3>{esc(title)}</h3><p>{esc(text)}</p><strong>{esc(cta)} →</strong></a>'


def studio_page(conn,shell,ship_list,rows):
    ships=ship_list(conn)
    weapons=rows(conn,'Cannons')
    lead=next((s for s in ships if (s.get('EnglishName') or '').lower()=='huracan'),ships[0] if ships else {})
    body=f'''<section class="studio-hero"><span class="eyebrow">Workbench Research Center · v4.3</span>
      <h2>Explore the ships. Test the mechanics. Keep the evidence.</h2>
      <p>A single starting point for game-file research and practical player tools. The original game data is used wherever recovered. Estimates and research gaps are always labeled.</p>
      <div class="actions"><a class="button primary" href="/experiments?ship={esc(lead.get('ID',''))}">Plan a combat experiment</a>
      <a class="button" href="/shipyard-atlas">Open shipyard</a><a class="button" href="/preflight">Check installation</a></div></section>
    <div class="metricgrid"><div><strong>{len(ships)}</strong><small>playable ship records</small></div>
    <div><strong>{len(weapons)}</strong><small>cannon records</small></div>
    <div><strong>3</strong><small>vulnerability evidence views</small></div>
    <div><strong>0</strong><small>authoritative server HP formulas proven</small></div></div>
    <section class="section"><h2>Choose a workshop</h2><div class="studio-grid">'''
    body+=''.join([
      _section('Shipyard & fitting','Browse recovered ship artwork, plan crew and upgrades, compare builds and preserve your selections.','/workshop','Open fitter','⚓'),
      _section('Weapon comparison','Compare cannon types and all recovered ammunition properties side by side.','/weapon-compare','Compare weapons','⊕'),
      _section('Wind performance','Chart your observed speed as you change the wind angle, alongside game wind-rose records.','/sailing-performance','View wind chart','≈'),
      _section('Protocol research','Build an evidence-led notebook of candidate game message families for future emulator work.','/protocol-library','Open protocol notes','⇄'),
      _section('Mechanics Lab','See what changes when you adjust wind, shot bearing, cannon type and ammo.','/mechanics','Explore mechanics','⌁'),
      _section('Ballistics Studio','Plot illustrative trajectories, aim from an attacker position, and inspect geometric impact angles.','/ballistics-studio','Aim a shot','◎'),
      _section('Combat Experiments','Design repeatable cannon, mortar, barrel and sailing experiments and collect observations.','/experiments','Plan experiments','◉'),
      _section('Damage Evidence','Build a measured HP atlas from genuine game observations. Nothing is guessed into untested cells.','/damage-research','Review HP evidence','◫'),
      _section('Capture & protocol','Bring video, manual shot markers and packet timing together—without calling unknown messages shots.','/capture-research','Review capture','▣'),
      _section('Visual parity','Compare real game screenshots with your recovered models and investigate missing materials and shaders.','/visual-parity','Compare images','◇'),
      _section('Recovery readiness','Check decoder coverage, missing assets, installation prerequisites, and what still needs testing.','/preflight','Check readiness','✓'),
      _section('Offline test world','Explore deterministic local ship-state experiments without contacting official servers.','/emulator','Research the emulator','⛯')])
    body+='</div></section><div class="notice">Evidence levels: <b>Client-verified</b> means recovered code/data; <b>Measured</b> means gameplay observations; <b>Illustrative</b> means research geometry/physics; <b>Unknown</b> means no defensible result yet.</div>'
    return shell('Research Center',body,'Research Center','A faster, more accessible starting point for all Workbench research.')


def workshop_page(conn,shell,ship_list,rows):
    ships=ship_list(conn)
    options=''.join(f'<option value="{esc(s.get("ID"))}">{esc(s.get("EnglishName") or s.get("ID"))}</option>' for s in ships)
    body=f'''<section class="panel"><h2>Original ship-outfitting controls</h2><p>These icons are decoded from the game’s own port and equipment artwork. The fitting notebook uses catalog entries, but cannot claim the original equipment-slot rules until those rules are verified.</p>
    <div class="ui-icons"><div><img src="/assets/game_ui/portShipInfo_navIconCannons.png" alt="Game cannon equipment tab"><span>Cannons</span></div>
    <div><img src="/assets/game_ui/cannonSlot_emptyMortarIcon.png" alt="Game mortar slot"><span>Mortars</span></div>
    <div><img src="/assets/game_ui/portShipInfo_navIconUpgrades.png" alt="Game upgrades tab"><span>Upgrades</span></div>
    <div><img src="/assets/game_ui/upgradeWindow_sailSlotIcon.png" alt="Game sail upgrade slot"><span>Sail equipment</span></div></div></section>
    <div class="two"><section class="panel"><h2>Choose your ship</h2>
      <label>Ship <select id="studioShip">{options}</select></label>
      <div id="shipShowcase" class="ship-showcase"><img id="studioShipIcon" src="/assets/shipIcon1.png" alt="Candidate recovered ship icon"><div><h3 id="studioShipName">Choose a ship</h3><p id="studioShipStats">Client catalog data</p></div></div>
      <p><a id="studioShipArticle" class="button" href="/shipyard">View ship article</a> <a class="button" href="/shipyard-atlas">Shipyard atlas</a></p></section>
    <section class="panel"><h2>Plan your outfit</h2><p>Select real catalog entries. Slot restrictions, compatibility, and total bonus stacking are not automatically assumed.</p>
      <label>Upgrade <select id="outfitUpgrade"></select></label>
      <label>Special crew <select id="outfitCrew"></select></label>
      <label>Captain skill <select id="outfitSkill"></select></label>
      <label>Ship design <select id="outfitDesign"></select></label>
      <div class="btnrow"><button id="outfitAdd">Add selected items</button><button id="outfitSave">Export build</button><button id="outfitClear">Clear build</button></div>
      <div id="outfitSelected" class="result" aria-live="polite"></div></section></div>
    <section class="section panel"><h2>How to read a ship build</h2><p>The Build Notebook saves your decisions locally. Each item retains the original game description and effects in the export. A tooltip or catalog effect is not proof that it stacks with another item.</p>
    <details><summary>More detail for researchers</summary><p>Source catalogs include <code>ShipsToPlay</code>, <code>ShipUpgradesNew</code>, <code>Crew_Special</code>, <code>CaptainSkills</code> and <code>ShipDesingElements</code>. Missing equipment rules and artwork are tracked separately in recovery diagnostics.</p></details></section>'''
    return shell('Ship Outfitting Studio',body,'Shipyard','Build notebooks using recovered crew, upgrades and authentic design records.')


def experiments_page(shell):
    body='''<section class="panel"><h2>Build a repeatable battle test</h2><p>Choose one variable to change. Keep your target, upgrades, distance and ammunition fixed while you measure HP lost. This helps distinguish armor, angle and weapon effects.</p>
    <div class="form-grid"><label>Attacker ship<input id="expAttacker" value="Huracan"></label><label>Target ship<input id="expTarget" value="Merchant's Grace"></label>
    <label>Weapon<input id="expWeapon" value="42-pound carronade"></label><label>Ammunition<input id="expAmmo" value="Round Shot"></label>
    <label>Shot type<select id="expType"><option value="single">Single shot</option><option value="broadside">Broadside</option><option value="mortar">Mortar</option><option value="heavy-mortar">Heavy mortar</option><option value="barrel">Barrel</option></select></label>
    <label>Distance (game units)<input id="expDistance" type="number" value="150" min="0"></label>
    <label>Target area<select id="expArea"><option value="stern">Stern</option><option value="side">Side</option><option value="bow">Bow</option><option value="sails">Sails</option></select></label>
    <label>Impact angle (degrees)<input id="expAngle" type="number" value="30" min="0" max="90"></label>
    <label>Target HP before<input id="expBefore" type="number" min="0" placeholder="Observed HP"></label>
    <label>Target HP after<input id="expAfter" type="number" min="0" placeholder="Observed HP"></label>
    <label>Game build/version<input id="expBuild" placeholder="Client version or source build"></label>
    <label>Notes<input id="expNotes" placeholder="Upgrades, consumables, speed"></label></div>
    <div class="btnrow"><button id="expRecord">Record observed shot</button><button id="expExport">Export all observations</button><button id="expCSV">Download blank CSV template</button></div>
    <p id="expFeedback" class="sub" role="status"></p></section>
    <section class="section panel"><h2>What should we test next?</h2><p>Experiment planner: vary angle or target region one at a time, repeat each condition, and keep records for real HP loss.</p>
    <div class="btnrow"><button id="expPlan">Generate balanced test plan</button><button id="expPlanExport">Export test plan</button></div><div id="expPlanTable" class="table-wrap"></div></section>
    <section class="section panel"><h2>Measured results</h2><div id="expMeasurements" class="table-wrap"></div><canvas id="expPlot" width="850" height="300" aria-label="Recorded HP damage by target region"></canvas>
    <p class="sub">Chart bars only show actual values you recorded. Damage may vary due to hidden bonuses; three measurements are a minimum for an illustrative summary, not proof of a damage formula.</p></section>'''
    return shell('Combat Experiment Builder',body,'Mechanics Lab','Controlled tests for cannonball, mortar, sail, bow, stern and barrel damage.')


def ballistics_page(shell):
    body='''<div class="two"><section class="panel"><h2>Set up an incoming shot</h2><p>Position your attacker relative to the target; for convenience, you can also use the camera's bearing.</p>
    <label>Attacker bearing (degrees) <strong id="aimBearingValue">0°</strong><input id="aimBearing" type="range" min="0" max="359" value="0"></label>
    <label>Elevation (degrees) <strong id="aimElevationValue">10°</strong><input id="aimElevation" type="range" min="-10" max="60" value="10"></label>
    <label>Shot range (research units)<input id="aimRange" type="number" value="150" min="1" max="10000"></label>
    <label>Illustrative launch speed (units/second)<input id="aimSpeed" type="number" value="80" min="1" max="10000"></label>
    <label>Illustrative gravity (units/second²)<input id="aimGravity" type="number" value="9.81" min="0" max="1000"></label>
    <div class="btnrow"><button id="aimRun">Draw example trajectory</button><button id="aimExport">Export geometry</button></div></section>
    <section class="panel"><h2>Impact direction</h2><canvas id="aimTop" width="650" height="330" aria-label="Overhead attacker direction"></canvas>
    <div id="aimAnswer" class="result"></div></section></div>
    <section class="section panel"><h2>Projectile path — illustrative, not game physics</h2><canvas id="aimPath" width="1100" height="330" aria-label="Side-view parabolic trajectory"></canvas>
    <p class="sub">This plots user-selected velocity and gravity. Exact in-game cannonball drag, gravity scaling, collision shapes, deflection, and HP resolution remain unverified. The 3D viewer remains the right place to inspect the recovered mesh and candidate hitboxes.</p></section>'''
    return shell('Ballistics Studio',body,'Mechanics Lab','Understand arrival direction and surface angles without inventing a damage number.')


def damage_page(shell):
    body='''<section class="panel"><h2>Measured damage atlas</h2><p>Import your existing <b>damage trial CSV</b> or use the Combat Experiment Builder to enter HP readings. The atlas groups shots by weapon, ammo, target, shot type and angle.</p>
    <input id="damageCSV" type="file" accept=".csv,text/csv"><p id="damageLoaded" role="status"></p><div class="inputs"><label>Weapon / loadout <select id="damageWeapon"></select></label>
    <label>Target ship <select id="damageTarget"></select></label><label>Type of shot <select id="damageShotType"></select></label></div>
    <canvas id="damageMap" width="1000" height="500" aria-label="Measured HP loss by region and impact angle"></canvas>
    <div id="damageDetails" class="table-wrap"></div></section>
    <section class="section panel"><h2>Three different heatmaps</h2><div class="studio-grid">
    <div class="card"><h3>Surface exposure</h3><p>Shows how directly a cannonball arrives against the recovered geometry. This can work without knowing HP damage.</p></div>
    <div class="card"><h3>Armor and candidate collision</h3><p>Shows recovered armor inputs and labeled collision-shape candidates—not proven weak points.</p></div>
    <div class="card"><h3>Measured HP loss</h3><p>Only colors areas with multiple actual recorded hits. Untested locations remain gray.</p></div></div></section>'''
    return shell('Damage Evidence Atlas',body,'Mechanics Lab','See what has actually been measured, without guessing where untested damage occurs.')


def capture_page(shell):
    body='''<section class="panel"><h2>Align video and game traffic</h2><p>Capture Studio records both locally. Use a synchronized flash and manually mark firing, HP change and sinking. Here you can compare those markers with a sanitized packet timeline without uploading raw credentials or packets.</p>
    <div class="form-grid"><label>Event-marker JSON <input type="file" accept=".json,.jsonl" id="markersFile"></label>
    <label>Sanitized packet timeline CSV <input type="file" accept=".csv" id="timelineFile"></label>
    <label>Clock offset (seconds)<input id="captureOffset" type="number" min="-120" max="120" step="0.1" value="0"></label>
    <label>Matching window (seconds)<input id="captureWindow" type="number" min="0.1" max="30" step="0.5" value="2.5"></label></div>
    <div class="btnrow"><button id="captureCorrelate">Compare timeline</button><button id="captureSave">Export matching notes</button></div><div id="captureTable" class="table-wrap"></div></section>
    <div class="notice">Packet timing correlation does not establish message identities. Game login tokens, chat and private details may appear in raw PCAP/video; the review ZIP should continue excluding them by default.</div>
    <section class="section panel"><h2>Recording checklist</h2><p>Connect to the game, confirm that the connection belongs to WorldOfSeaBattleClient, start video + passive packets, press Sync flash, then mark single shots, broadsides, regions and HP changes. Do not rely on guessed timestamps without alignment.</p></section>'''
    return shell('Capture & Protocol Research',body,'Research Center','Player-friendly timeline analysis with privacy preserved.')


def visual_page(shell):
    body='''<section class="panel"><h2>Compare the real game with your reconstructed model</h2><p>Capture the in-game ship and the Workbench model at the same camera angle and zoom. Both images remain in this browser for comparison.</p>
    <div class="form-grid"><label>In-game screenshot <input type="file" accept="image/png,image/jpeg,image/webp" id="visualGame"></label>
    <label>Workbench screenshot <input type="file" accept="image/png,image/jpeg,image/webp" id="visualWorkbench"></label>
    <label>Blend ratio <strong id="visualRatioValue">50%</strong><input type="range" id="visualRatio" min="0" max="100" value="50"></label>
    <label>Comparison mode<select id="visualMode"><option value="blend">Blend</option><option value="difference">Pixel difference</option><option value="split">Side by side</option></select></label></div>
    <canvas id="visualCanvas" width="1000" height="540" aria-label="Visual parity comparison"></canvas>
    <p id="visualNote" class="sub">Select two local images. Differences may come from camera alignment, resolution, lighting, animation timing, textures, or shaders—not necessarily missing mesh triangles.</p></section>
    <section class="section panel"><h2>Visual recovery checklist</h2><div class="checklist"><label><input type="checkbox"> Complete source geometry and UVs</label><label><input type="checkbox"> Correct mesh-to-material matching</label>
    <label><input type="checkbox"> Real design replacement textures applied</label><label><input type="checkbox"> Alpha and blended materials correct</label>
    <label><input type="checkbox"> Original animations/attachment points verified</label><label><input type="checkbox"> Matching game camera, lighting and screenshot</label></div></section>'''
    return shell('Visual Fidelity Lab',body,'Research Center','Game-file fidelity means matching WoSB’s own models, textures and rendering—not historical ship plans.')


def preflight_page(shell,setup,readiness=None):
    checks=setup.get('tools',{})
    rows=[]
    for name,v in checks.items():
        found=v.get('found');rows.append(f'<tr><th>{esc(name)}</th><td>{"Available" if found else "Missing"}</td><td>{esc(v.get("version") or ("Ready" if found else "Install before using its feature"))}</td></tr>')
    status=readiness or {}
    body='<section class="panel"><h2>Your local Workbench setup</h2><p>The checks below are advisory. Missing video tools do not prevent offline wiki, catalog or damage-note analysis.</p>'
    body+='<div class="table-wrap"><table class="comparison"><thead><tr><th>Tool</th><th>Status</th><th>Notes</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table></div>'
    body+='<p>Free disk space: <b>'+esc(setup.get('disk_free_gb'))+' GB</b>. Live capture requires Windows, FFmpeg, TShark and Npcap. GPU rendering requires a graphical Windows test.</p></section>'
    body+='<section class="section panel"><h2>What remains unverified?</h2><div class="studio-grid">'+''.join([
       '<div class="card"><h3>Visual parity</h3><p>Full shader equivalence, animations and every skin combination still need side-by-side game checks.</p></div>',
       '<div class="card"><h3>Damage resolution</h3><p>Final cannon, mortar, barrel, sail, penetration and ricochet formulas remain unverified.</p></div>',
       '<div class="card"><h3>Server compatibility</h3><p>The local sandbox deliberately does not pretend to implement the official game server protocol.</p></div>'])+'</div></section>'
    body+='<section class="section panel"><h2>What to send for investigation</h2><p>Use Workbench → Full Recovery → Review-only ZIP for decoder errors. Use Gameplay Capture Studio for a sanitized timeline and optional short clips. Original PCAP and full video remain local unless you explicitly choose to share them.</p></section>'
    return shell('Setup & Recovery Readiness',body,'Research Center','One place to check the dependencies and remaining evidence gaps.')


def weapon_compare_page(conn,rows,shell,ids=()):
    cannons=rows(conn,'Cannons');ammo=rows(conn,'CannonBalls')
    if not cannons:return shell('Weapon comparison','<p>Import the game catalog to compare cannons.</p>','Weapons')
    picks=[]
    for item in ids[:3]:
        found=next((x for x in cannons if str(x.get('ID'))==str(item)),None)
        if found:picks.append(found)
    if not picks:picks=cannons[:2]
    def option(current):return ''.join(f'<option value="{esc(x.get("ID"))}"'+(' selected' if str(x.get('ID'))==str(current) else '')+f'>{esc(x.get("EnglishName") or x.get("ID"))}</option>' for x in cannons)
    form='<form class="compare-controls" action="/weapon-compare" method="get">'
    for i in range(3):
        selected=picks[i].get('ID') if i<len(picks) else ''
        form+='<label>Cannon '+str(i+1)+'<select name="gun">'+('<option value="">None</option>' if i==2 else '')+option(selected)+'</select></label>'
    form+='<button class="button primary">Compare weapons</button></form>'
    fields=[('Poundage','Cannon weight class'),('Penetration','Recorded penetration'),('Distance','Recorded distance'),
            ('Cooldown','Reload cooldown'),('Scatter','Spread / scatter'),('Angle','Firing arc'),('SplashRadius','Recorded splash radius')]
    def numeric(x):
        try:return float(x)
        except (TypeError,ValueError):return 0.
    headers=''.join('<th>'+esc(x.get('EnglishName'))+'</th>' for x in picks)
    table_rows=''
    for name,title in fields:
        upper=max([numeric(s.get(name)) for s in picks] or [1]) or 1
        cells=''
        for s in picks:
            val=s.get(name,'Not recorded');number=numeric(s.get(name));pct=max(0,min(100,number/upper*100))
            cells+='<td><strong>'+esc(val)+'</strong><div class="bartrack"><div class="barfill" data-percent="'+str(pct)+'"></div></div></td>'
        table_rows+='<tr><th>'+esc(title)+'</th>'+cells+'</tr>'
    body='<div class="notice">These bars compare raw game properties. Poundage, penetration, distance and reload are NOT interchangeable with final hull HP damage; higher is not always better.</div>'
    body+=form+'<div class="table-wrap"><table class="comparison"><thead><tr><th>Recorded property</th>'+headers+'</tr></thead><tbody>'+table_rows+'</tbody></table></div>'
    body+='<section class="section panel"><h2>Which ammunition changes the result?</h2><p>The client provides separate ammo damage factors, sail damage and special effects. The ultimate HP reduction still depends on unverified game combat rules.</p><div class="table-wrap"><table class="comparison"><thead><tr><th>Ammo</th><th>Damage factor</th><th>Penetration</th><th>Sail damage field</th><th>Special effect</th></tr></thead><tbody>'
    for a in ammo:
        body+='<tr><th>'+esc(a.get('EnglishName'))+'</th><td>'+esc(a.get('DamageFactor'))+'</td><td>'+esc(a.get('Penetration'))+'</td><td>'+esc(a.get('DamageToSailes'))+'</td><td>'+esc(str(a.get('Effects') or '')[:110])+'</td></tr>'
    body+='</tbody></table></div></section>'
    body+='<div class="actions"><a class="button" href="/experiments">Build a controlled damage test</a><a class="button" href="/guide/cannons">Read the cannon guide</a></div>'
    return shell('Cannon & ammunition comparison',body,'Weapons','Compare every extracted property without inventing final damage numbers.')


def sailing_performance_page(conn,rows,shell):
    windroses=rows(conn,'WindRoses')
    selects=''.join('<option value="'+esc(x.get('Name') or x.get('ID') or x.get('SourceRecord'))+'">'+esc(x.get('EnglishName') or x.get('Name') or 'Unknown wind rose')+'</option>' for x in windroses)
    body='''<section class="two"><div class="panel"><h2>Angle and wind rose</h2><p>Explore the recovered wind component, then add the speed you actually observed at the helm. Real ship speed depends on more factors than the component alone.</p>
    <label>Wind rose from game files<select id="sailRose">'''+selects+'''</select></label>
    <label>Relative wind angle <strong id="sailAngleValue">45°</strong><input id="sailAngle" type="range" min="-180" max="180" step="5" value="45"></label>
    <label>Observed in-game ship speed<input id="sailObservedSpeed" type="number" min="0" step="0.1" placeholder="Enter a measured value"></label>
    <button id="sailRecord" type="button">Record sailing speed</button> <button id="sailExport" type="button">Export observations</button>
    <div id="sailValue" class="result"></div></div>
    <div class="panel"><h2>Measured speed by angle</h2><canvas id="sailChart" width="650" height="380" aria-label="Sailing speed observations"></canvas><p class="sub">Actual readings are plotted as points. No interpolation is claimed to be the original game speed formula.</p></div></section>
    <section class="section panel"><h2>How to make a meaningful comparison</h2><p>Use the same ship, sails, upgrades and crew. Record relative wind angle and displayed speed after the ship stabilizes. Repeat enough times to see whether current, steering and buffs alter the result.</p>
    <div id="sailReadings" class="table-wrap"></div></section>'''
    return shell('Sailing & Wind Performance',body,'Mechanics Lab','Chart real player observations alongside the recovered game wind rose.')


def protocol_library_page(shell):
    body='''<section class="panel"><h2>Make a protocol research notebook</h2><p>Keep distinct observations separate: packet segment size, timing, direction and the visible gameplay event. A matching timestamp does not prove that a specific message means “fire” or “damage.”</p>
    <div class="form-grid"><label>Observed message family<input id="protoLabel" placeholder="Example: repeated 45-byte client segments"></label>
    <label>Direction<select id="protoDirection"><option>client to server</option><option>server to client</option><option>unknown</option></select></label>
    <label>Observed length (bytes)<input id="protoLength" type="number" min="0"></label>
    <label>Related visible event<input id="protoEvent" placeholder="Shot / movement / unknown"></label>
    <label>Evidence rating<select id="protoStatus"><option value="candidate">Candidate</option><option value="repeated_timing_correlation">Repeated timing correlation</option><option value="schema_supported_by_client_code">Client-code schema evidence</option></select></label>
    <label>Notes<input id="protoNotes" placeholder="Recording, frame, game build"></label></div>
    <div class="btnrow"><button id="protoAdd">Add observation</button><button id="protoExport">Export protocol notebook</button></div><div id="protoTable" class="table-wrap"></div></section>
    <div class="notice">Only your locally recorded traffic and authorized test observations belong in this notebook. Avoid sharing raw payloads, tokens or unrelated addresses. No server-compatibility claim is made from traffic shape alone.</div>'''
    return shell('Protocol Message Research',body,'Research Center','A local, searchable notebook for evidence toward an independent test server.')
