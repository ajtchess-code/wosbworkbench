/* WoSB Wiki world map: the game's own map with ports, port-battle sites, towers, forts, trading posts, resource nodes,
   typed trade routes and shallow waters. Drag to pan, wheel or pinch to zoom, click anything for details.
   Usage: WorldMap.mount(element, window.WORLD_MAP)   ?port=Name  ?route=id */
(function(){
'use strict';
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const LAYERS=[['ports','Ports',true],['labels','Port names',true],['pb','Port-battle sites',true],['towers','Towers',false],['forts','Imperial forts',true],
 ['villages','Trading posts & lighthouses',false],['mines','Resource nodes',false],['altars','Altars',false],['routes','Trade routes',true],['shallows','Shallow waters',false]];
const ROUTE_COL={Main:'#1f5fbf',Supply:'#2e8b57',Coastal:'#d4a017',Central:'#8e44ad',Smuggling:'#222'};
const PORT_COL={City:'#e8c05a',Bay:'#5aa9e8',NeutralBay:'#7dd87a',PirateBay:'#222'};
function mount(el,M){if(!M){el.innerHTML='<p class="note">No map data in this build.</p>';return}
 const rel=el.dataset.root||'',A=M.aspect,VH=1000/A;
 const types=[...new Set(M.routes.map(r=>r.type))].sort((a,b)=>Object.keys(ROUTE_COL).indexOf(a)-Object.keys(ROUTE_COL).indexOf(b));
 const layers=LAYERS.filter(l=>l[0]!=='shallows'||M.shallows);
 el.innerHTML=`<div class="wm">
  <div class="wm-bar"><input type="search" class="wm-find" placeholder="Find a port…" list="wm-ports"><datalist id="wm-ports">${M.ports.map(p=>`<option value="${esc(p.n)}">`).join('')}</datalist>
   <details class="wm-layers"><summary>Layers</summary>${layers.map(([k,l,on])=>`<label><input type="checkbox" data-layer="${k}"${on?' checked':''}> ${l}</label>`).join('')}</details>
   <span class="wm-rtypes">${types.map(t=>`<label class="wm-rt"><input type="checkbox" data-rtype="${t}" checked><i style="background:${ROUTE_COL[t]||'#555'}"></i>${t}</label>`).join('')}</span>
   <button type="button" class="wm-reset">Reset view</button></div>
  <div class="wm-view"><div class="wm-world"><img class="wm-img" src="${rel}${M.image}" alt="World of Sea Battle world map" draggable="false">
   ${M.shallows?`<img class="wm-shallow" src="${rel}${M.shallows}" alt="" draggable="false" hidden>`:''}
   <svg class="wm-routes" viewBox="0 0 1000 ${VH.toFixed(1)}" preserveAspectRatio="none">${M.routes.map((r,i)=>{const pts=r.pts.map(([u,v])=>`${(u*1000).toFixed(1)},${(v*VH).toFixed(1)}`).join(' ');
     return `<g data-i="${i}" data-type="${esc(r.type)}"><polyline class="wm-rhit" points="${pts}"/><polyline class="wm-rline" points="${pts}" style="stroke:${ROUTE_COL[r.type]||'#555'}"/></g>`}).join('')}</svg></div>
   <div class="wm-pins"></div><div class="wm-pop" hidden></div></div>
  ${M.shallows?`<p class="wm-legend" hidden>Shallow waters, largest ship allowed: <i class="lg lg-s2"></i>rank 2 <i class="lg lg-s3"></i>rank 3 <i class="lg lg-s4"></i>rank 4 <i class="lg lg-s5"></i>rank 5 <i class="lg lg-s6"></i>rank 6 (and smaller)</p>`:''}</div>`;
 const view=el.querySelector('.wm-view'),world=el.querySelector('.wm-world'),pins=el.querySelector('.wm-pins'),pop=el.querySelector('.wm-pop'),svg=el.querySelector('.wm-routes');
 const items=[];const add=(layer,p,cls,html,label,title)=>items.push({layer,u:p.u,v:p.v,cls,html,label,title,p});
 for(const p of M.ports)add('ports',p,'wm-port',`<b>${esc(p.n)}</b><span>${esc(p.info||p.type)}</span>${p.url?`<a href="${rel}${p.url}">Port page</a>`:''}`,p.n,p.n);
 for(const s of M.pb)add('pb',s,'wm-pb',`<b>Port battle: ${esc(s.n)}</b><span>${s.towers} towers · guild fort</span><a href="${rel}tools/battle-simulator.html?preset=pbfleet&site=${s.id}">Simulate the port battle</a><a href="${rel}tools/battle-simulator.html?preset=port&site=${s.id}">Towers only</a>`,'',`Port battle: ${s.n}`);
 for(const t of M.towers)add('towers',t,'wm-tower',`<b>${esc(t.n)}</b><a href="${rel}tools/defenses.html">Damage and range</a>`,'',t.n);
 for(const f of M.forts)add('forts',f,'wm-fort',`<b>Imperial fort</b>`,'','Imperial fort');
 for(const v of M.villages)add('villages',v,'wm-village',`<b>${esc(v.n)}</b>`,'',v.n);
 for(const m of M.mines)add('mines',m,'wm-mine',`<b>${esc(m.n)}</b>`,'',m.n);
 for(const a of M.altars)add('altars',a,'wm-altar',`<b>Altar</b>`,'','Altar');
 for(const it of items){const d=document.createElement('button');d.type='button';d.className='wm-pin '+it.cls;d.title=it.title;d.setAttribute('aria-label',it.title);
  if(it.cls==='wm-port')d.style.background=PORT_COL[it.p.type]||'#e8c05a';if(it.label){const s=document.createElement('span');s.textContent=it.label;d.appendChild(s)}
  d.addEventListener('click',e=>{e.stopPropagation();show(it)});it.el=d;pins.appendChild(d)}
 let W=0,H=0,s=1,x=0,y=0,sel=-1;const on=new Set(layers.filter(l=>l[2]).map(l=>l[0])),rt=new Set(types);
 function fit(){W=view.clientWidth;H=W/A;view.style.height=Math.min(H,window.innerHeight*0.78)+'px';world.style.width=W+'px';world.style.height=H+'px'}
 function clamp(){const vh=view.clientHeight;s=Math.max(1,Math.min(14,s));x=Math.min(0,Math.max(W-W*s,x));y=Math.min(0,Math.max(vh-H*s,y))}
 function draw(){clamp();world.style.transform=`translate(${x}px,${y}px) scale(${s})`;svg.style.display=on.has('routes')?'':'none';
  svg.style.setProperty('--sw',(2.4/s).toFixed(3)+'px');svg.style.setProperty('--sws',(4.5/s).toFixed(3)+'px');svg.style.setProperty('--hw',(14/s).toFixed(3)+'px');
  svg.querySelectorAll('g').forEach(g=>{g.style.display=rt.has(g.dataset.type)?'':'none';g.classList.toggle('sel',+g.dataset.i===sel)});
  const sh=el.querySelector('.wm-shallow');if(sh){sh.hidden=!on.has('shallows');el.querySelector('.wm-legend').hidden=!on.has('shallows')}
  for(const it of items){const vis=on.has(it.layer);it.el.style.display=vis?'':'none';if(!vis)continue;it.el.style.left=(x+it.u*W*s)+'px';it.el.style.top=(y+it.v*H*s)+'px'}
  pins.classList.toggle('wm-labels',on.has('labels'));pins.classList.toggle('wm-big',s>=2.2);
  if(pop.at){pop.style.left=(x+pop.at[0]*W*s)+'px';pop.style.top=(y+pop.at[1]*H*s)+'px'}}
 function openPop(html,at){pop.at=at;pop.innerHTML=html+'<button type="button" class="wm-close" aria-label="Close">×</button>';pop.hidden=false;
  pop.querySelector('.wm-close').onclick=()=>{pop.hidden=true;pop.at=null;sel=-1;draw()};draw()}
 function show(it){sel=-1;openPop(it.html,[it.u,it.v])}
 const cargo=r=>r.cargo&&r.cargo.length?(r.cargo[0]==='varies'?'Two of the nearby port\'s trade goods (they change)':r.cargo.join(', ')):'No fixed cargo';
 function showRoute(i,at){const r=M.routes[i];sel=i;
  openPop(`<b><i class="wm-dot" style="background:${ROUTE_COL[r.type]||'#555'}"></i>${esc(r.type)} route</b><span>${esc(r.from)}${r.to&&r.to!==r.from?' → '+esc(r.to):' (round trip)'}</span>
   <span>Cargo: ${esc(cargo(r))}</span><span>Length: ${r.len.toLocaleString()}${r.loop?' · loop':''}</span>${r.ships?`<span>Ships that fit: ${esc(r.ships)}</span>`:''}
   <span class="wm-small">${esc((M.route_text||{})[r.type]||'')}</span>`,at||r.pts[Math.floor(r.pts.length/2)])}
 svg.addEventListener('click',e=>{const g=e.target.closest('g[data-i]');if(!g)return;e.stopPropagation();const b=view.getBoundingClientRect();
  showRoute(+g.dataset.i,[(e.clientX-b.left-x)/(W*s),(e.clientY-b.top-y)/(H*s)])});
 function zoomAt(px,py,f){const ns=Math.max(1,Math.min(14,s*f));x=px-(px-x)*ns/s;y=py-(py-y)*ns/s;s=ns;draw()}
 function centre(u,v,z){s=z;x=view.clientWidth/2-u*W*s;y=view.clientHeight/2-v*H*s;draw()}
 view.addEventListener('wheel',e=>{e.preventDefault();const r=view.getBoundingClientRect();zoomAt(e.clientX-r.left,e.clientY-r.top,e.deltaY<0?1.25:0.8)},{passive:false});
 let drag=null,moved=false;const pts=new Map();
 view.addEventListener('pointerdown',e=>{if(e.target.closest('.wm-pin,.wm-pop'))return;pts.set(e.pointerId,[e.clientX,e.clientY]);drag={x,y,cx:e.clientX,cy:e.clientY,d:null};moved=false});
 view.addEventListener('pointermove',e=>{if(!pts.has(e.pointerId)||!drag)return;pts.set(e.pointerId,[e.clientX,e.clientY]);
  if(Math.abs(e.clientX-drag.cx)+Math.abs(e.clientY-drag.cy)>4&&!moved){moved=true;try{view.setPointerCapture(e.pointerId)}catch(_){}}
  if(pts.size===2){const [a,b]=[...pts.values()],d=Math.hypot(a[0]-b[0],a[1]-b[1]);if(drag.d){const r=view.getBoundingClientRect();zoomAt((a[0]+b[0])/2-r.left,(a[1]+b[1])/2-r.top,d/drag.d)}drag.d=d;return}
  if(moved){x=drag.x+e.clientX-drag.cx;y=drag.y+e.clientY-drag.cy;draw()}});
 view.addEventListener('click',e=>{if(moved){e.stopPropagation();e.preventDefault()}},true);
 const up=e=>{pts.delete(e.pointerId);if(!pts.size)drag=null;else if(drag)drag.d=null};view.addEventListener('pointerup',up);view.addEventListener('pointercancel',up);
 view.addEventListener('dblclick',e=>{const r=view.getBoundingClientRect();zoomAt(e.clientX-r.left,e.clientY-r.top,2)});
 el.querySelectorAll('[data-layer]').forEach(c=>c.addEventListener('change',()=>{c.checked?on.add(c.dataset.layer):on.delete(c.dataset.layer);draw()}));
 el.querySelectorAll('[data-rtype]').forEach(c=>c.addEventListener('change',()=>{c.checked?rt.add(c.dataset.rtype):rt.delete(c.dataset.rtype);draw()}));
 el.querySelector('.wm-reset').onclick=()=>{s=1;x=0;y=0;pop.hidden=true;pop.at=null;sel=-1;draw()};
 el.querySelector('.wm-find').addEventListener('change',e=>{const p=items.find(it=>it.layer==='ports'&&it.p.n.toLowerCase()===e.target.value.toLowerCase());if(!p)return;
  on.add('ports');el.querySelector('[data-layer="ports"]').checked=true;centre(p.u,p.v,4);show(p)});
 window.addEventListener('resize',()=>{fit();draw()});fit();draw();
 const q=new URLSearchParams(location.search);
 if(q.get('port')){const f=el.querySelector('.wm-find');f.value=q.get('port');f.dispatchEvent(new Event('change'))}
 else if(q.get('route')!=null){const i=M.routes.findIndex(r=>String(r.id)===q.get('route'));if(i>=0){const r=M.routes[i],us=r.pts.map(p=>p[0]),vs=r.pts.map(p=>p[1]);
  const span=Math.max(Math.max(...us)-Math.min(...us),(Math.max(...vs)-Math.min(...vs))/A);centre((Math.max(...us)+Math.min(...us))/2,(Math.max(...vs)+Math.min(...vs))/2,Math.max(1,Math.min(5,0.45/Math.max(span,0.01))));showRoute(i)}}}
window.WorldMap={mount};
})();
