'use strict';
const $=id=>document.getElementById(id);
function clean(v){return String(v==null?'—':v)}
function label(v){return clean(v.EnglishName||v.Name||v.ID||'Unidentified')}
for(const img of document.querySelectorAll('img'))img.addEventListener('error',()=>{img.hidden=true;});
for(const control of document.querySelectorAll('input[data-filter]')){
 control.addEventListener('input',()=>{const sel=control.dataset.filter,q=control.value.toLocaleLowerCase();
 document.querySelectorAll(sel).forEach(el=>el.hidden=!el.textContent.toLocaleLowerCase().includes(q));});
}
for(const bar of document.querySelectorAll('.barfill'))bar.style.width=Number(bar.dataset.percent||0)+'%';
const heat=$('heatmap');
let selectedArea='broadside';
function drawHeat(){
 if(!heat)return;const c=heat.getContext('2d'),w=heat.width,h=heat.height;
 c.clearRect(0,0,w,h);c.fillStyle='#0b1b2e';c.fillRect(0,0,w,h);
 let deg=Number($('viewYaw')?.value||0),elev=Number($('viewElevation')?.value||0);
 $('viewDegrees').textContent=deg+'°';$('elevDegrees').textContent=elev+'°';
 c.save();c.translate(w/2,h/2);c.rotate(-Math.PI/2);
 // Flat schematic, not a projection of any game's actual collision mesh.
 const a=170,b=71,rad=deg*Math.PI/180;
 for(let i=0;i<144;i++){
   const t=(i+0.5)*Math.PI*2/144;
   const norm=[Math.cos(t)/a,Math.sin(t)/b];let n=Math.hypot(...norm);const unit=norm.map(x=>x/n);
   const ray=[Math.cos(rad)*Math.cos(elev*Math.PI/180),Math.sin(rad)*Math.cos(elev*Math.PI/180)];
   const cosine=Math.abs(unit[0]*ray[0]+unit[1]*ray[1]);
   c.strokeStyle=`hsl(${185-cosine*177} 78% ${42+cosine*10}%)`;c.lineWidth=23;
   c.beginPath();c.ellipse(0,0,a,b,0,t,t+Math.PI*2/144+.007);c.stroke();
 }
 c.fillStyle='#263c50';c.beginPath();c.ellipse(0,0,a-15,b-15,0,0,Math.PI*2);c.fill();
 c.fillStyle='#a9c7d3';c.font='bold 18px system-ui';c.textAlign='center';c.fillText('Schematic hull',0,5);
 c.strokeStyle='#f1c27a';c.lineWidth=3;c.beginPath();c.moveTo(0,0);c.lineTo(Math.cos(rad)*240,Math.sin(rad)*240);c.stroke();
 c.restore();c.fillStyle='#c6dbe9';c.font='15px system-ui';c.fillText('Camera direction sets incoming shot bearing',15,27);
 c.fillStyle='#61c7d0';c.fillText('Grazing',15,h-18);c.fillStyle='#f4795f';c.fillText('Perpendicular',w-142,h-18);
}
['viewYaw','viewElevation'].forEach(id=>$(id)?.addEventListener('input',()=>{drawHeat();scenario();}));
heat?.addEventListener('click',e=>{const r=heat.getBoundingClientRect(),x=(e.clientX-r.left)/r.width,y=(e.clientY-r.top)/r.height;
 selectedArea=y<.37?'starboard':y>.65?'port':x<.5?'stern':'bow';scenario();});
let catalog={datasets:{}};
function makeOptions(id,records){const control=$(id);if(!control)return;control.replaceChildren();for(let i=0;i<records.length;i++){
 const option=document.createElement('option');option.value=String(i);option.textContent=label(records[i]);control.append(option);
}}
function records(name){return catalog.datasets?.[name]||[]}
function selected(id,type){return records(type)[Number($(id)?.value||0)]||{}}
function scenario(){if(!$('labResult'))return;
 let ship=selected('labShip','ShipsToPlay'),gun=selected('labCannon','Cannons'),ammo=selected('labAmmo','CannonBalls');
 let speed=$('shotRange')?.value||'—',bearing=$('viewYaw')?.value||0;
 let basic=Number(ship.Armor||0);let p=Number($('armorPercent')?.value||0),m=Number($('armorFlat')?.value||0);
 let armor=basic*(1+p)+m;
 let detail=`Target: ${label(ship)} · ${selectedArea} · range ${speed} (game scale) · bearing ${bearing}°\n`+
 `Cannon: ${label(gun)} — poundage ${clean(gun.Poundage)}, penetration ${clean(gun.Penetration)}\n`+
 `Ammunition: ${label(ammo)} — damage factor ${clean(ammo.DamageFactor)}, penetration ${clean(ammo.Penetration)}\n`+
 `Ship: ${clean(ship.Health)} HP · extracted armor ${clean(ship.Armor)}\n`+
 `Client getter (illustrative input): ${armor.toFixed(2)} armor, using catalog Armor as a PROXY for PatArmor\n`+
 `Damage and ricochet: UNKNOWN. The colored map is geometry-only, not an HP map.`;
 $('labResult').textContent=detail;
 const up=selected('labUpgrade','ShipUpgradesNew'),crew=selected('labCrew','Crew_Special'),skill=selected('labSkill','CaptainSkills'),design=selected('labDesign','ActiveShipDesigns');
 if($('loadoutResult'))$('loadoutResult').textContent=`${label(ship)} build notebook\nUpgrade: ${label(up)} ${clean(up.EffectsBoost||up.EnglishDescription||'')}\nSpecial crew: ${label(crew)} ${clean(crew.EnglishDescription||'')}\nCaptain skill: ${label(skill)} ${clean(skill.Effect||'')}\nShip design: ${label(design)}\nThese are catalog selections, not validated equip-slot legality or automatic combat modifiers.`;
}
(async()=>{
 if(!$('labShip'))return;
 try{const response=await fetch('/api/catalog');if(!response.ok)throw Error('Catalog unavailable');catalog=await response.json();
  for(const [id,key] of [['labShip','ShipsToPlay'],['labCannon','Cannons'],['labAmmo','CannonBalls'],['labUpgrade','ShipUpgradesNew'],['labCrew','Crew_Special'],['labSkill','CaptainSkills']])makeOptions(id,records(key));
  function designForShip(){const ship=selected('labShip','ShipsToPlay'),designs=records('ShipDesingElements').filter(d=>d.Category==='ShipFullDesign'&&String(d.ShipId)===String(ship.ID));
   catalog.datasets.ActiveShipDesigns=designs;makeOptions('labDesign',designs);
  }
  designForShip();$('labShip').addEventListener('change',()=>{designForShip();scenario();});
  const param=new URLSearchParams(location.search).get('ship');if(param){const i=records('ShipsToPlay').findIndex(x=>String(x.ID)===param);if(i>=0)$('labShip').value=String(i);}
  for(const ctrl of document.querySelectorAll('.inputs select,.inputs input'))ctrl.addEventListener('change',scenario);
  scenario();drawHeat();
 }catch(error){$('labResult').textContent='The local catalog could not be loaded: '+String(error);}
})();
(async()=>{if(!$('windChart'))return;try{
 const d=await(await fetch('/api/wind')).json(),svg=$('windChart'),ns='http://www.w3.org/2000/svg';svg.replaceChildren();
 const xs=d.map(v=>v.angle),ys=d.map(v=>v.component),min=Math.min(...ys),max=Math.max(...ys),span=max-min||1;
 let points=d.map(x=>[(x.angle+180)/360*620+10,260-(x.component-min)/span*235]).map(p=>p.join(',')).join(' ');
 const poly=document.createElementNS(ns,'polyline');poly.setAttribute('points',points);poly.setAttribute('fill','none');poly.setAttribute('stroke','#75d1d9');poly.setAttribute('stroke-width','3');svg.append(poly);
 function changed(){const a=Number($('windAngle').value);$('windDegrees').textContent=a+'°';let nearest=d.reduce((o,r)=>Math.abs(r.angle-a)<Math.abs(o.angle-a)?r:o,d[0]);$('windValue').textContent=`Wind component ${Number(nearest.component).toFixed(3)} at ${a}°. Not verified ship speed.`;}
 $('windAngle').addEventListener('input',changed);changed();
}catch(err){$('windValue').textContent='Wind chart unavailable: '+String(err);}})();

/* v4.1 local fitting and measurement notebooks. No game-server API is used. */
function localGet(key){try{return JSON.parse(localStorage.getItem(key)||'[]')}catch{return []}}
function localPut(key,val){try{localStorage.setItem(key,JSON.stringify(val))}catch{/* storage disabled */}}
function offerJSON(name,value){
 const blob=new Blob([JSON.stringify(value,null,2)],{type:'application/json'});
 const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();
 setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function fitKey(){let ship=selected('labShip','ShipsToPlay');return 'wosb-fit-v41-'+String(ship.ID||'unknown')}
function fitRows(){return localGet(fitKey())}
function paintFit(){let node=$('fittingItems');if(!node)return;node.replaceChildren();
 const items=fitRows();if(!items.length){let p=document.createElement('p');p.textContent='No equipment saved yet.';node.append(p);return;}
 for(const [index,item] of items.entries()){
  let row=document.createElement('div');row.className='fit-item';let txt=document.createElement('div');
  const name=document.createElement('strong');name.textContent=item.name;
  const sub=document.createElement('small');sub.textContent=item.type+' · '+(item.effect||'No effect text recorded').slice(0,200);
  txt.append(name,sub);let remove=document.createElement('button');remove.textContent='Remove';remove.onclick=()=>{
   let keep=fitRows();keep.splice(index,1);localPut(fitKey(),keep);paintFit();};row.append(txt,remove);node.append(row);
 }}
function addFit(type,id,catalogType){if(!$(id))return;
 const v=selected(id,catalogType);if(!Object.keys(v).length)return;
 let items=fitRows();items.push({type,name:label(v),id:v.ID||v.SourceRecord||null,
  effect:clean(v.EffectsBoost||v.Effect||v.EnglishDescription||''),source:v.Source||null,
  evidence:'catalog selection; equip eligibility and stacking not confirmed'});
 if(items.length>60)items=items.slice(-60);localPut(fitKey(),items);paintFit();}
for(const [button,type,selectId,category] of [['addCrew','Special crew','labCrew','Crew_Special'],
 ['addUpgrade','Upgrade','labUpgrade','ShipUpgradesNew'],['addSkill','Captain skill','labSkill','CaptainSkills']]){
 $(button)?.addEventListener('click',()=>addFit(type,selectId,category));
}
$('labShip')?.addEventListener('change',()=>{paintFit();paintShots();});
$('saveFitting')?.addEventListener('click',()=>offerJSON('WoSB-Fitting-'+String(selected('labShip','ShipsToPlay').ID||'ship')+'.json',
 {format:'wosb-fit-v41',ship:selected('labShip','ShipsToPlay'),items:fitRows(),
  warning:'Planning selections only: unverified equip slots and effects'}));
const shotKey='wosb-measured-shots-v41';
function paintShots(){let node=$('shotLog');if(!node)return;const ship=selected('labShip','ShipsToPlay');
 const entries=localGet(shotKey).filter(v=>v.ship_id===String(ship.ID));
 node.textContent=entries.length?entries.slice(-12).map(v=>`${v.cannon} / ${v.ammo} · ${v.area} · ${v.range} range · ${v.hp_lost} HP observed`).join('\n'):
 'No locally recorded shots for this ship.';}
$('recordShot')?.addEventListener('click',()=>{
 const hp=Number($('measuredHP')?.value),ship=selected('labShip','ShipsToPlay'),gun=selected('labCannon','Cannons'),ammo=selected('labAmmo','CannonBalls');
 if(!Number.isFinite(hp)||hp<0||!$('measuredHP').value.trim()){alert('Enter the actual observed HP loss, zero or greater.');return;}
 const row={ship_id:String(ship.ID),ship:label(ship),cannon_id:gun.ID,cannon:label(gun),
  ammo_id:ammo.ID,ammo:label(ammo),area:selectedArea,range:Number($('shotRange').value),
  bearing:Number($('viewYaw').value),elevation:Number($('viewElevation').value),hp_lost:hp,
  status:'measured_user_input',time:new Date().toISOString()};
 const all=localGet(shotKey);all.push(row);localPut(shotKey,all.slice(-2000));paintShots();});
$('exportShots')?.addEventListener('click',()=>offerJSON('WoSB-Measured-Shots.json',
 {format:'wosb-measured-shots-v41',observations:localGet(shotKey),
 warning:'Reported observations have not been independently validated'}));
const windKey='wosb-wind-observations-v41';
function paintWind(){const n=$('windLog');if(!n)return;const entries=localGet(windKey);
 n.textContent=entries.length?entries.slice(-10).map(v=>`${v.angle}° relative wind · ${v.speed} observed speed`).join('\n'):'No observed sailing measurements yet.';}
$('recordWind')?.addEventListener('click',()=>{
 const value=$('observedSpeed')?.value,sp=Number(value);if(!value||!Number.isFinite(sp)||sp<0){alert('Enter a valid nonnegative observed speed.');return;}
 const entries=localGet(windKey);entries.push({angle:Number($('windAngle').value),speed:sp,
  ship_id:String(selected('labShip','ShipsToPlay').ID||''),status:'measured_user_input',time:new Date().toISOString()});
 localPut(windKey,entries.slice(-2000));paintWind();});
$('exportWind')?.addEventListener('click',()=>offerJSON('WoSB-Sailing-Measurements.json',
 {format:'wosb-wind-measurements-v41',observations:localGet(windKey)}));
// The catalog fetch earlier is asynchronous; update as soon as options exist.
if($('labShip')){let tries=0;const sync=setInterval(()=>{if(records('ShipsToPlay').length||++tries>60){clearInterval(sync);paintFit();paintShots();paintWind();}},100);}
