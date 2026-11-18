/* WoSB Codex v4.3, entirely local player research workspaces. No telemetry. */
'use strict';
(()=>{
const el=id=>document.getElementById(id), num=(x,fallback=0)=>{let n=Number(x);return Number.isFinite(n)?n:fallback;},
  label=r=>String(r?.EnglishName||r?.NameEnglish||r?.Name||r?.ID||'Unknown'),
  key='wosb-research-v43', safeParse=s=>{try{return JSON.parse(s)}catch{return null}},
  load=k=>safeParse(localStorage.getItem(k))||[],
  store=(k,v)=>{try{localStorage.setItem(k,JSON.stringify(v));}catch(e){/* private browsing */}},
  plain=(tag,text,cls)=>{const n=document.createElement(tag);n.textContent=String(text);if(cls)n.className=cls;return n;};
function download(name,text,mime='application/json'){
 const blob=new Blob([text],{type:mime}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;
 document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),2000);
}
async function catalog(){const r=await fetch('/api/catalog');if(!r.ok)throw Error('Game catalog unavailable');return (await r.json()).datasets||{};}
function setOptions(node,rows){if(!node)return;node.replaceChildren();(rows||[]).forEach((entry,i)=>{
 const option=document.createElement('option');option.value=String(i);option.textContent=label(entry);node.append(option)});}
function canvasText(ctx,text,x,y,color='#d8e7f1'){ctx.fillStyle=color;ctx.fillText(text,x,y)}
function blank(ctx,width,height){ctx.clearRect(0,0,width,height);ctx.fillStyle='#102439';ctx.fillRect(0,0,width,height)}
function line(ctx,x,y,X,Y,color='#75cdd9',thick=2){ctx.strokeStyle=color;ctx.lineWidth=thick;ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(X,Y);ctx.stroke()}
function table(target,heads,rows){target?.replaceChildren();if(!target)return;
 const t=document.createElement('table');t.className='comparison';const thead=document.createElement('thead'),tr=document.createElement('tr');
 heads.forEach(x=>tr.append(plain('th',x)));thead.append(tr);t.append(thead);
 const tbody=document.createElement('tbody');rows.forEach(r=>{const row=document.createElement('tr');r.forEach((v,i)=>row.append(plain(i===0?'th':'td',v)));tbody.append(row)});t.append(tbody);target.append(t);}
function dataUrl(file){return new Promise((res,rej)=>{if(!file||file.size>30*1024*1024)return rej(Error('Choose an image smaller than 30 MB'));
 const reader=new FileReader();reader.onload=()=>res(reader.result);reader.onerror=()=>rej(Error('Cannot read image'));reader.readAsDataURL(file);});}
function imageFrom(data){return new Promise((res,rej)=>{const image=new Image();image.onload=()=>res(image);image.onerror=()=>rej(Error('Could not decode local image'));image.src=data;});}
function parseCSV(raw){if(raw.length>8*1024*1024)throw Error('CSV is too large');let cells=[],row=[],text='',quoted=false;
 for(let i=0;i<raw.length;i++){let c=raw[i];if(c==='"'){if(quoted&&raw[i+1]==='"'){text+='"';i++;}else quoted=!quoted;}
 else if(c===','&&!quoted){row.push(text);text=''}else if((c==='\n'||c==='\r')&&!quoted){if(c==='\r'&&raw[i+1]==='\n')i++;row.push(text);if(row.some(v=>v!==''))cells.push(row);row=[];text='';}
 else text+=c;}if(quoted)throw Error('Unclosed quote in CSV');row.push(text);if(row.some(v=>v!==''))cells.push(row);
 if(!cells.length)return [];
 const heads=cells.shift().map((s,i)=>i===0?s.replace(/^\ufeff/,'').trim():s.trim());
 return cells.slice(0,50000).map(x=>Object.fromEntries(heads.map((h,i)=>[h,x[i]||''])));}
function toCSV(rows,columns){const quote=x=>'"'+String(x??'').replace(/"/g,'""')+'"';return columns.join(',')+'\r\n'+rows.map(x=>columns.map(k=>quote(x[k])).join(',')).join('\r\n')+'\r\n'}
function loadResearch(){const data=load(key);return Array.isArray(data)?data:[];}

// Ship appearance and fitting notebook, scoped by currently selected ship.
(async()=>{if(!el('studioShip'))return;try{const d=await catalog();let ships=d.ShipsToPlay||[];
 const selection=el('studioShip');// Normalize the server-rendered ID options to array indices before binding selection.
 setOptions(selection,ships);
 const map=['outfitUpgrade','outfitCrew','outfitSkill','outfitDesign'];
 const sources=['ShipUpgradesNew','Crew_Special','CaptainSkills','ShipDesingElements'];
 map.forEach((id,i)=>setOptions(el(id),d[sources[i]]));
 const saved=JSON.parse(localStorage.getItem('wosb-current-ship-v43')||'null');
 if(saved!==null){const idx=ships.findIndex(v=>String(v.ID)===String(saved));if(idx>=0)selection.selectedIndex=idx;}
 let build=load('wosb-fitting-v43');if(!Array.isArray(build))build=[];
 function selectedShip(){return ships[selection.selectedIndex]||ships[0]||{}}
 function matchDesigns(){let ship=selectedShip(),designs=(d.ShipDesingElements||[]).filter(x=>
    String(x.ShipId||x.ShipID||x.ShipIdForDesign||'')===String(ship.ID)||
    (x.ShipId==null&&String(x.Category||'').toLowerCase()!=='shipfulldesign'));
    setOptions(el('outfitDesign'),designs);el('outfitDesign')._data=designs;}
 function show(){const ship=selectedShip();el('studioShipName').textContent=label(ship);
   el('studioShipStats').textContent=`${ship.Health??'Unknown'} hull HP · catalog armor ${ship.Armor??'Unknown'} · rank ${ship.ShipRank??ship.Rank??'Unknown'}`;
   el('studioShipIcon').src='/assets/shipIcon'+encodeURIComponent(ship.ID)+'.png';
   el('studioShipArticle').href='/ship/'+encodeURIComponent(ship.ID);
   const rows=build.filter(x=>String(x.ship_id)===String(ship.ID));
   const node=el('outfitSelected');node.replaceChildren();
   if(!rows.length)node.append(plain('p','No build items selected for this ship.'));
   else rows.forEach(x=>{const item=plain('p',`${x.category}: ${x.name} · ${x.effect||'See catalog for details'}`);node.append(item)});
   localStorage.setItem('wosb-current-ship-v43',JSON.stringify(ship.ID));}
 selection.addEventListener('change',()=>{matchDesigns();show()});matchDesigns();show();
 el('outfitAdd').onclick=()=>{const ship=selectedShip();map.forEach((id,i)=>{const node=el(id),collection=node._data||d[sources[i]]||[];
   const item=collection[node.selectedIndex];if(!item)return;
   build.push({ship_id:String(ship.ID),category:sources[i],name:label(item),id:item.ID||item.Name,
               effect:String(item.EffectsBoost||item.Effect||item.EnglishDescription||item.Texture||'').slice(0,500),
               source:item.Source||'Game client catalog',verified_compatibility:false});});
   build=build.slice(-300);store('wosb-fitting-v43',build);show()};
 el('outfitSave').onclick=()=>download('WoSB-Fitting-'+String(selectedShip().ID)+'.json',JSON.stringify({format:'wosb-fitting-v43',
  ship:selectedShip(),choices:build.filter(v=>v.ship_id===String(selectedShip().ID)),
  warning:'Compatibility, slots, effects and stacking not confirmed'},null,2));
 el('outfitClear').onclick=()=>{build=build.filter(v=>v.ship_id!==String(selectedShip().ID));store('wosb-fitting-v43',build);show()};
}catch(e){el('outfitSelected').textContent='Could not load local catalog: '+String(e)}})();

// Controlled experiments and honest per-region statistics.
(()=>{if(!el('expRecord'))return;let plan=[];
 const fields={'shooter_ship':'expAttacker','target_ship':'expTarget','weapon':'expWeapon','ammo':'expAmmo',
  'shot_type':'expType','range_m':'expDistance','target_armor_region':'expArea','impact_angle_deg':'expAngle',
  'target_hp_before':'expBefore','target_hp_after':'expAfter','game_version':'expBuild','notes':'expNotes'};
 function all(){return loadResearch()}
 function graph(){const rs=all();let target=el('expMeasurements'),recent=rs.slice(-24).reverse();
 table(target,['Target','Weapon','Area','Shot','HP lost','Angle'],recent.map(x=>[x.target_ship,x.weapon,x.target_armor_region,
       x.shot_type,x.observed_hp_damage,x.impact_angle_deg+'°']));
 const cv=el('expPlot'),ctx=cv.getContext('2d');blank(ctx,cv.width,cv.height);ctx.font='14px system-ui';
 const zones=['bow','side','stern','sails','mast'],summary=zones.map(z=>{const vals=rs.filter(x=>x.target_armor_region===z).map(x=>num(x.observed_hp_damage));
   return {name:z,n:vals.length,avg:vals.length>=3?vals.reduce((a,b)=>a+b,0)/vals.length:null};});
 const max=Math.max(1,...summary.filter(x=>x.avg!==null).map(x=>x.avg));
 summary.forEach((z,i)=>{const x=40+i*155,height=z.avg===null?0:z.avg/max*215;
  if(z.avg!==null){ctx.fillStyle='#49bac2';ctx.fillRect(x,255-height,95,height)}
  canvasText(ctx,z.name,x,278);canvasText(ctx,z.n>=3?`${z.avg.toFixed(1)} HP · n=${z.n}`:`n=${z.n} · untested`,x,35,'#d5e7ee')});}
 function record(){let row={};Object.entries(fields).forEach(([k,id])=>row[k]=el(id).value.trim());
 const before=Number(row.target_hp_before),after=Number(row.target_hp_after),angle=Number(row.impact_angle_deg);
 if(!row.target_hp_before||!row.target_hp_after||!Number.isFinite(before)||!Number.isFinite(after)||after>before||after<0||!row.weapon||!row.target_ship||!Number.isFinite(angle)||angle<0||angle>90){
 el('expFeedback').textContent='Enter valid target HP before and after the shot; the after value cannot exceed the before value.';return}
 row.observed_hp_damage=before-after;row.timestamp_utc=new Date().toISOString();row.trial_id='trial-'+Date.now();
 row.provenance='user_observed_gameplay';row.authenticated_by_game_server=false;
 let rs=all();rs.push(row);store(key,rs.slice(-5000));el('expFeedback').textContent=`Recorded ${row.observed_hp_damage} observed HP lost. No exact formula inferred.`;graph();}
 el('expRecord').onclick=record;
 el('expExport').onclick=()=>download('WoSB-Gameplay-Trials.json',JSON.stringify({format:'wosb-trial-notebook-v43',observations:all(),
    authoritative_damage_formula:false},null,2));
 el('expCSV').onclick=()=>download('WoSB-Blank-Combat-Trial.csv',toCSV([],Object.keys(fields).concat('observed_hp_damage','trial_id','timestamp_utc')),'text/csv');
 el('expPlan').onclick=()=>{const rs=all();plan=[];for(const zone of ['bow','side','stern','sails'])for(const angle of [0,30,60]){
 const count=rs.filter(x=>x.target_ship.toLowerCase()===el('expTarget').value.toLowerCase()&&
  x.weapon.toLowerCase()===el('expWeapon').value.toLowerCase()&&x.ammo.toLowerCase()===el('expAmmo').value.toLowerCase()&&
  x.target_armor_region===zone&&Math.abs(num(x.impact_angle_deg)-angle)<=7.5).length;
 plan.push({target:el('expTarget').value,weapon:el('expWeapon').value,ammo:el('expAmmo').value,region:zone,angle,
  recorded:count,remaining:Math.max(0,5-count),instruction:'Change only the target area or angle; hold range and bonuses constant'});}
 table(el('expPlanTable'),['Region','Angle','Completed','Needed'],plan.map(v=>[v.region,v.angle+'°',v.recorded,v.remaining]));};
 el('expPlanExport').onclick=()=>download('WoSB-Controlled-Trial-Plan.json',JSON.stringify({format:'wosb-controlled-trials-v43',
  plan,exact_server_formula_verified:false},null,2));graph();})();

// Geometry-based research trajectory: deliberately independent of the real game model.
(()=>{if(!el('aimTop'))return;let last=null;
 function run(){const yaw=num(el('aimBearing').value),elev=num(el('aimElevation').value),speed=num(el('aimSpeed').value),g=num(el('aimGravity').value),range=num(el('aimRange').value);
 el('aimBearingValue').textContent=yaw+'°';el('aimElevationValue').textContent=elev+'°';
 const radians=yaw*Math.PI/180,raise=elev*Math.PI/180;
 let cv=el('aimTop'),ctx=cv.getContext('2d');blank(ctx,cv.width,cv.height);ctx.font='15px system-ui';
 const cx=cv.width/2,cy=cv.height/2;ctx.strokeStyle='#476779';ctx.lineWidth=2;ctx.beginPath();ctx.ellipse(cx,cy,180,75,Math.PI/2,0,Math.PI*2);ctx.stroke();
 const ax=cx-Math.sin(radians)*190,ay=cy+Math.cos(radians)*110;
 ctx.fillStyle='#6bd4db';ctx.beginPath();ctx.arc(ax,ay,8,0,Math.PI*2);ctx.fill();line(ctx,ax,ay,cx,cy,'#edc77a',3);
 canvasText(ctx,'Attacker',ax+12,ay-4);canvasText(ctx,'Target hull (schematic)',cx-85,cy+22);
 const n=70,pts=[],vx=speed*Math.cos(raise),vy=speed*Math.sin(raise);
 const flight=Math.min(60,range/Math.max(0.01,Math.abs(vx)));for(let i=0;i<=n;i++){
 const t=flight*i/n;pts.push([vx*t,vy*t-g*t*t/2]);}
 cv=el('aimPath');ctx=cv.getContext('2d');blank(ctx,cv.width,cv.height);
 const minY=Math.min(0,...pts.map(x=>x[1])),maxY=Math.max(1,...pts.map(x=>x[1])),span=maxY-minY;
 const transform=x=>[40+x[0]/range*(cv.width-90),cv.height-35-(x[1]-minY)/span*(cv.height-75)];
 ctx.strokeStyle='#e8bd77';ctx.lineWidth=3;ctx.beginPath();pts.forEach((p,i)=>{let q=transform(p);if(!i)ctx.moveTo(...q);else ctx.lineTo(...q)});ctx.stroke();
 canvasText(ctx,'Illustrative trajectory – user-specified gravity / muzzle speed',28,25);
 const rise=pts.at(-1)[1];const front=Math.max(0,Math.cos(raise));
 el('aimAnswer').textContent=`Arrival bearing ${yaw}°, elevation ${elev}°. Example shot travels ${range} research units; height change ${rise.toFixed(2)} units. A surface's incidence depends on its true 3D normal. This is geometry research, not WoSB projectile physics or HP prediction.`;
 last={bearing:yaw,elevation:elev,initial_speed:speed,gravity:g,range,example_endpoint:pts.at(-1),
  status:'illustrative_not_verified_game_model'};}
 for(const id of ['aimBearing','aimElevation','aimSpeed','aimGravity','aimRange'])el(id).addEventListener('input',run);
 el('aimRun').onclick=run;el('aimExport').onclick=()=>download('WoSB-Aim-Geometry.json',JSON.stringify(last,null,2));run();})();

// Visual parity screenshot lab. Images never leave browser.
(()=>{if(!el('visualCanvas'))return;let first=null,second=null;
 async function imageInput(fileId){const file=el(fileId).files[0];if(!file)return null;
 try{return await imageFrom(await dataUrl(file))}catch(e){el('visualNote').textContent=e.message;return null}}
 function draw(){const cv=el('visualCanvas'),ctx=cv.getContext('2d');blank(ctx,cv.width,cv.height);
 const ratio=num(el('visualRatio').value)/100,mode=el('visualMode').value;el('visualRatioValue').textContent=Math.round(ratio*100)+'%';
 if(!(first&&second))return;
 const W=cv.width,H=cv.height,c1=document.createElement('canvas'),c2=document.createElement('canvas');c1.width=c2.width=W;c1.height=c2.height=H;
 const a=c1.getContext('2d'),b=c2.getContext('2d');a.drawImage(first,0,0,W,H);b.drawImage(second,0,0,W,H);
 if(mode==='split'){ctx.drawImage(c1,0,0,W/2,H,0,0,W/2,H);ctx.drawImage(c2,W/2,0,W/2,H,W/2,0,W/2,H)}
 else if(mode==='blend'){ctx.drawImage(c1,0,0);ctx.globalAlpha=ratio;ctx.drawImage(c2,0,0);ctx.globalAlpha=1}
 else{const x=a.getImageData(0,0,W,H),y=b.getImageData(0,0,W,H);for(let i=0;i<x.data.length;i+=4){
  for(let k=0;k<3;k++)x.data[i+k]=Math.abs(x.data[i+k]-y.data[i+k]);x.data[i+3]=255;}ctx.putImageData(x,0,0)}
 el('visualNote').textContent='Visual comparison only: differences can be caused by camera position, antialiasing, animation, materials, lighting or missing geometry.';}
 el('visualGame').onchange=async()=>{first=await imageInput('visualGame');draw()};
 el('visualWorkbench').onchange=async()=>{second=await imageInput('visualWorkbench');draw()};
 el('visualRatio').oninput=draw;el('visualMode').onchange=draw;})();

// Empirical damage heatmap from user-imported CSV; grey until sample threshold.
(()=>{if(!el('damageMap'))return;let observations=[];
 function draw(){const cv=el('damageMap'),ctx=cv.getContext('2d');blank(ctx,cv.width,cv.height);ctx.font='14px system-ui';
 const filters=[['damageWeapon','weapon'],['damageTarget','target_ship'],['damageShotType','shot_type']];
 const entries=observations.filter(v=>filters.every(([id,k])=>!el(id)?.value||v[k]===el(id).value));
 const regions=['bow','port','starboard','side','stern','sails','mast','other'],cells=[];
 for(const [index,region] of regions.entries())for(let j=0;j<6;j++){
 const items=entries.filter(v=>String(v.target_armor_region||v.region||'').toLowerCase()===region&&Math.floor(num(v.impact_angle_deg||v.angle)/15)===j);
 const values=items.map(x=>num(x.observed_hp_damage||x.damage,-1)).filter(n=>n>=0);
 cells.push({i:index,j,n:values.length,mean:values.length>=3?values.reduce((a,b)=>a+b,0)/values.length:null});}
 const max=Math.max(1,...cells.filter(x=>x.mean!==null).map(x=>x.mean));
 canvasText(ctx,'Actual observed HP lost · cells with fewer than 3 readings remain grey',130,28);
 cells.forEach(z=>{const x=145+z.j*130,y=55+z.i*51,intensity=z.mean===null?null:z.mean/max;
 ctx.fillStyle=intensity===null?'#344b5a':`rgb(${Math.round(55+180*intensity)},${Math.round(165-95*intensity)},${Math.round(180-115*intensity)})`;
 ctx.fillRect(x,y,125,45);canvasText(ctx,z.mean===null?`n=${z.n}`:`${z.mean.toFixed(1)} HP`,x+9,y+26,'#ffffff');});
 regions.forEach((z,i)=>canvasText(ctx,z,18,85+51*i));for(let i=0;i<6;i++)canvasText(ctx,`${i*15}–${i*15+15}°`,157+i*130,49);
 table(el('damageDetails'),['Region','Obliquity','Samples','Mean HP'],cells.filter(z=>z.n).map(z=>[regions[z.i],`${z.j*15}–${z.j*15+15}°`,z.n,z.mean===null?'Not enough trials':z.mean.toFixed(2)]));}
 function opts(){const kinds=[['damageWeapon','weapon'],['damageTarget','target_ship'],['damageShotType','shot_type']];
 kinds.forEach(([id,k])=>{const node=el(id);node.replaceChildren();let all=document.createElement('option');all.value='';all.textContent='All';node.append(all);
 const vals=[...new Set(observations.map(x=>x[k]).filter(Boolean))].sort();vals.forEach(x=>{const option=document.createElement('option');option.value=x;option.textContent=x;node.append(option)});node.onchange=draw});}
 el('damageCSV').onchange=async()=>{try{
 const file=el('damageCSV').files[0];observations=parseCSV(await file.text());el('damageLoaded').textContent=observations.length+' rows loaded locally.';opts();draw();
 }catch(e){el('damageLoaded').textContent='Could not parse CSV: '+e.message;}};opts();draw();})();

// UTC event/packet bin correlation from sanitized local files only.
(()=>{if(!el('captureCorrelate'))return;let markers=[],bins=[],results=[];
 const readFile=async(file)=>{if(!file||file.size>8*1024*1024)throw Error('File missing or too large');return file.text()};
 const seconds=x=>{if(x===null||x===undefined)return NaN;if(typeof x==='number')return x;const numeric=Number(x);return Number.isFinite(numeric)?numeric:Date.parse(x)/1000};
 el('captureCorrelate').onclick=async()=>{try{
 const mt=await readFile(el('markersFile').files[0]),pt=await readFile(el('timelineFile').files[0]);
 const parsed=safeParse(mt);markers=Array.isArray(parsed)?parsed:(parsed?.events||mt.split(/\r?\n/).filter(Boolean).map(s=>safeParse(s)).filter(Boolean));
 bins=parseCSV(pt);if(!Array.isArray(markers)||!markers.length)throw Error('No readable event markers');
 const win=num(el('captureWindow').value,2.5),offset=num(el('captureOffset').value);
 if(win<=0||win>30||Math.abs(offset)>120)throw Error('Bad window/offset');
 results=markers.slice(0,2000).map(m=>{const t=seconds(m.utc||m.timestamp_utc||m.time)+offset;
   const candidates=bins.filter(b=>Math.abs(seconds(b.unix_seconds||b.utc||b.timestamp_utc)-t)<=win);
   return {kind:m.kind||m.type||'unknown',utc:m.utc||m.timestamp_utc||m.time||'—',
   client:candidates.reduce((a,b)=>a+num(b.client_segments),0),server:candidates.reduce((a,b)=>a+num(b.server_segments),0),
   fortyfive:candidates.reduce((a,b)=>a+num(b.client_45_bytes),0),classification:'Candidate time overlap only'};});
 table(el('captureTable'),['Marker','UTC','Client segments','Server segments','45-byte segments','Confidence'],results.map(r=>[r.kind,r.utc,r.client,r.server,r.fortyfive,r.classification]));
 }catch(e){el('captureTable').textContent='Cannot analyze those files: '+String(e.message)}};
 el('captureSave').onclick=()=>download('WoSB-Timing-Correlations.json',JSON.stringify({format:'wosb-timing-correlations-v43',
  events:results,warning:'Temporal coincidence does not decode game messages or prove damage'},null,2));})();

// All cross-page selection is local and opt-in, never written into the game.
})();

// Additional v4.3 comparisons, sailing readings and protocol hypothesis notebook.
(()=>{
 const $=id=>document.getElementById(id),number=v=>Number.isFinite(Number(v))?Number(v):0;
 function get(k){try{return JSON.parse(localStorage.getItem(k)||'[]')}catch{return []}}
 function put(k,v){try{localStorage.setItem(k,JSON.stringify(v))}catch{}}
 function down(filename,data){const file=new Blob([JSON.stringify(data,null,2)],{type:'application/json'}),url=URL.createObjectURL(file);
  const a=document.createElement('a');a.download=filename;a.href=url;a.click();setTimeout(()=>URL.revokeObjectURL(url),1500)}
 function tab(id,head,records){const root=$(id);if(!root)return;root.replaceChildren();const t=document.createElement('table');t.className='comparison';
 let tr=document.createElement('tr');head.forEach(x=>{const c=document.createElement('th');c.textContent=x;tr.appendChild(c)});const top=document.createElement('thead');top.append(tr);t.append(top);
 const body=document.createElement('tbody');records.forEach(arr=>{const tr=document.createElement('tr');arr.forEach(x=>{const cell=document.createElement('td');cell.textContent=String(x);tr.append(cell)});body.append(tr)});t.append(body);root.append(t)}
 if($('sailChart')){
   const key='wosb-sail-observations-v43';let data=[];
   function show(){const a=number($('sailAngle').value);$('sailAngleValue').textContent=a+'°';const rose=$('sailRose').value;
    const rows=get(key).filter(x=>x.rose===rose);let cv=$('sailChart'),ctx=cv.getContext('2d'),w=cv.width,h=cv.height;
    ctx.fillStyle='#102439';ctx.fillRect(0,0,w,h);ctx.font='14px system-ui';
    const max=Math.max(1,...rows.map(x=>number(x.speed)))*1.1;
    ctx.strokeStyle='#56788a';ctx.beginPath();ctx.moveTo(44,20);ctx.lineTo(44,h-45);ctx.lineTo(w-20,h-45);ctx.stroke();
    for(const r of rows){const x=44+(r.angle+180)/360*(w-67),y=h-45-r.speed/max*(h-75);
      ctx.fillStyle='#62d5cb';ctx.beginPath();ctx.arc(x,y,5,0,Math.PI*2);ctx.fill()}
    ctx.fillStyle='#a7cbd7';ctx.fillText('-180°',44,h-22);ctx.fillText('0°',w/2,h-22);ctx.fillText('180°',w-58,h-22);
    $('sailValue').textContent=`${rows.length} measured observations for this wind rose. Relative angle ${a}°. Values are observations, not a recovered ship-speed formula.`;
    tab('sailReadings',['Wind rose','Angle','Speed','Recorded'],rows.slice(-100).map(x=>[x.rose,x.angle+'°',x.speed,x.time]));}
   $('sailAngle').addEventListener('input',show);$('sailRose').addEventListener('change',show);
   $('sailRecord').onclick=()=>{const speed=number($('sailObservedSpeed').value);
    if(!$('sailObservedSpeed').value||speed<0)return alert('Enter a valid measured speed');
    const records=get(key);records.push({rose:$('sailRose').value,angle:number($('sailAngle').value),speed,time:new Date().toISOString(),status:'user_observation'});
    put(key,records.slice(-5000));show()};
   $('sailExport').onclick=()=>down('WoSB-Wind-Measurements.json',{format:'wosb-sail-observations-v43',observations:get(key),game_formula_verified:false});show();
 }
 if($('protoAdd')){
  const key='wosb-protocol-research-v43';
  function show(){tab('protoTable',['Family','Direction','Length','Visible event','Evidence'],get(key).map(x=>[x.name,x.direction,x.bytes,x.related_event,x.evidence]));}
  $('protoAdd').onclick=()=>{const name=$('protoLabel').value.trim().slice(0,140);
   if(!name)return alert('Describe the message family');const value=$('protoLength').value;
   if(value&&!Number.isFinite(Number(value)))return alert('Invalid length');
   const data=get(key);data.push({name,direction:$('protoDirection').value,bytes:value?number(value):null,
    related_event:$('protoEvent').value.slice(0,130),evidence:$('protoStatus').value,
    notes:$('protoNotes').value.slice(0,500),created_utc:new Date().toISOString()});
   put(key,data.slice(-2000));show()};
  $('protoExport').onclick=()=>down('WoSB-Protocol-Research.json',{format:'wosb-protocol-notebook-v43',
    entries:get(key),warning:'Message classifications are hypotheses; no authentication details or game server compatibility'});show();
 }
})();
