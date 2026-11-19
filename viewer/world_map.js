/* Interactive world map: the game's own map texture with ports, port-battle sites, towers, forts, villages,
   mines and trade routes placed from the client's world data. Drag to pan, wheel or pinch to zoom.
   Usage: WorldMap.mount(element, window.WORLD_MAP) */
(function(){
'use strict';
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const LAYERS=[['ports','Ports',true],['pb','Port-battle sites',true],['towers','Towers',false],['forts','Imperial forts',true],
 ['villages','Villages & lighthouses',false],['mines','Mines & resource nodes',false],['altars','Altars',false],['routes','Trade routes',true]];
const PORT_COL={City:'#e8c05a',Bay:'#5aa9e8',NeutralBay:'#7dd87a',PirateBay:'#222'};
function mount(el,M){if(!M){el.innerHTML='<p class="note">No map data in this build.</p>';return}
 const rel=el.dataset.root||'';
 el.innerHTML=`<div class="wm">
  <div class="wm-bar"><input type="search" class="wm-find" placeholder="Find a port…" list="wm-ports"><datalist id="wm-ports">${M.ports.map(p=>`<option value="${esc(p.n)}">`).join('')}</datalist>
   ${LAYERS.map(([k,l,on])=>`<label><input type="checkbox" data-layer="${k}"${on?' checked':''}> ${l}</label>`).join('')}
   <button type="button" class="wm-reset">Reset view</button></div>
  <div class="wm-view"><div class="wm-world"><img class="wm-img" src="${rel}${M.image}" alt="World of Sea Battle world map" draggable="false">
   <svg class="wm-routes" viewBox="0 0 1000 ${(1000/M.aspect).toFixed(1)}" preserveAspectRatio="none">${M.routes.map(r=>`<polyline points="${r.map(([u,v])=>`${(u*1000).toFixed(1)},${(v*1000/M.aspect).toFixed(1)}`).join(' ')}"/>`).join('')}</svg></div>
   <div class="wm-pins"></div><div class="wm-pop" hidden></div></div>
  <p class="ha-note">${esc(M.note)}</p></div>`;
 const view=el.querySelector('.wm-view'),world=el.querySelector('.wm-world'),pins=el.querySelector('.wm-pins'),pop=el.querySelector('.wm-pop');
 const items=[];const add=(layer,p,cls,html,label,title)=>items.push({layer,u:p.u,v:p.v,cls,html,label,title,p});
 for(const p of M.ports)add('ports',p,'wm-port',`<b>${esc(p.n)}</b><span>${esc(p.type)}${p.ranks?` · builds up to rate ${p.ranks}`:''}${p.flags?` · ${esc(p.flags)}`:''}</span>${p.url?`<a href="${rel}${p.url}">Port page</a>`:''}`,p.n,p.n);
 for(const s of M.pb)add('pb',s,'wm-pb',`<b>Port battle: ${esc(s.n)}</b><span>${s.towers} towers · guild fort</span><a href="${rel}tools/battle-simulator.html?preset=pbfleet&site=${s.id}">Simulate the port battle</a><a href="${rel}tools/battle-simulator.html?preset=port&site=${s.id}">Towers only</a><a href="${rel}tools/defenses.html">Tower strength &amp; reach</a>`,'',`Port battle: ${s.n}`);
 for(const t of M.towers)add('towers',t,'wm-tower',`<b>${esc(t.n)}</b>`,'',t.n);
 for(const f of M.forts)add('forts',f,'wm-fort',`<b>Imperial fort</b><span>${esc(f.n)}</span>`,'','Imperial fort');
 for(const v of M.villages)add('villages',v,'wm-village',`<b>${esc(v.n)}</b>`,'',v.n);
 for(const m of M.mines)add('mines',m,'wm-mine',`<b>${esc(m.n)}</b>`,'',m.n);
 for(const a of M.altars)add('altars',a,'wm-altar',`<b>Altar</b>`,'','Altar');
 for(const it of items){const d=document.createElement('button');d.type='button';d.className='wm-pin '+it.cls;d.title=it.title;
  if(it.cls==='wm-port')d.style.background=PORT_COL[it.p.type]||'#e8c05a';if(it.label){const s=document.createElement('span');s.textContent=it.label;d.appendChild(s)}
  d.addEventListener('click',e=>{e.stopPropagation();show(it)});it.el=d;pins.appendChild(d)}
 let W=0,H=0,s=1,x=0,y=0;const on=new Set(LAYERS.filter(l=>l[2]).map(l=>l[0]));
 function fit(){W=view.clientWidth;H=W/M.aspect;view.style.height=Math.min(H,window.innerHeight*0.78)+'px';world.style.width=W+'px';world.style.height=H+'px'}
 function clamp(){const vh=view.clientHeight;s=Math.max(1,Math.min(12,s));x=Math.min(0,Math.max(W-W*s,x));y=Math.min(0,Math.max(vh-H*s,y))}
 function draw(){clamp();world.style.transform=`translate(${x}px,${y}px) scale(${s})`;el.querySelector('.wm-routes').style.display=on.has('routes')?'':'none';
  for(const it of items){const vis=on.has(it.layer);it.el.style.display=vis?'':'none';if(!vis)continue;it.el.style.left=(x+it.u*W*s)+'px';it.el.style.top=(y+it.v*H*s)+'px'}
  pins.classList.toggle('wm-labels',s>=1.8);if(pop.it){pop.style.left=(x+pop.it.u*W*s)+'px';pop.style.top=(y+pop.it.v*H*s)+'px'}}
 function show(it){pop.it=it;pop.innerHTML=it.html+'<button type="button" class="wm-close" aria-label="Close">×</button>';pop.hidden=false;pop.querySelector('.wm-close').onclick=()=>{pop.hidden=true;pop.it=null};draw()}
 function zoomAt(px,py,f){const ns=Math.max(1,Math.min(12,s*f));x=px-(px-x)*ns/s;y=py-(py-y)*ns/s;s=ns;draw()}
 view.addEventListener('wheel',e=>{e.preventDefault();const r=view.getBoundingClientRect();zoomAt(e.clientX-r.left,e.clientY-r.top,e.deltaY<0?1.25:0.8)},{passive:false});
 let drag=null;const pts=new Map();
 view.addEventListener('pointerdown',e=>{if(e.target.closest('.wm-pin,.wm-pop'))return;view.setPointerCapture(e.pointerId);pts.set(e.pointerId,[e.clientX,e.clientY]);drag={x,y,cx:e.clientX,cy:e.clientY,d:null}});
 view.addEventListener('pointermove',e=>{if(!pts.has(e.pointerId)||!drag)return;pts.set(e.pointerId,[e.clientX,e.clientY]);
  if(pts.size===2){const [a,b]=[...pts.values()],d=Math.hypot(a[0]-b[0],a[1]-b[1]);if(drag.d){const r=view.getBoundingClientRect();zoomAt((a[0]+b[0])/2-r.left,(a[1]+b[1])/2-r.top,d/drag.d)}drag.d=d;return}
  x=drag.x+e.clientX-drag.cx;y=drag.y+e.clientY-drag.cy;draw()});
 const up=e=>{pts.delete(e.pointerId);if(!pts.size)drag=null;else if(drag)drag.d=null};view.addEventListener('pointerup',up);view.addEventListener('pointercancel',up);
 view.addEventListener('dblclick',e=>{const r=view.getBoundingClientRect();zoomAt(e.clientX-r.left,e.clientY-r.top,2)});
 el.querySelectorAll('[data-layer]').forEach(c=>c.addEventListener('change',()=>{c.checked?on.add(c.dataset.layer):on.delete(c.dataset.layer);draw()}));
 el.querySelector('.wm-reset').onclick=()=>{s=1;x=0;y=0;draw()};
 el.querySelector('.wm-find').addEventListener('change',e=>{const p=items.find(it=>it.layer==='ports'&&it.p.n.toLowerCase()===e.target.value.toLowerCase());if(!p)return;
  on.add('ports');el.querySelector('[data-layer="ports"]').checked=true;s=4;x=view.clientWidth/2-p.u*W*s;y=view.clientHeight/2-p.v*H*s;show(p)});
 window.addEventListener('resize',()=>{fit();draw()});fit();draw();
 const q=new URLSearchParams(location.search).get('port');if(q){const f=el.querySelector('.wm-find');f.value=q;f.dispatchEvent(new Event('change'))}}
window.WorldMap={mount};
})();
