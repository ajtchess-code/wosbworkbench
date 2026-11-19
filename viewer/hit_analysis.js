/* WoSB hit analysis: where a ship is vulnerable, from its real hull box and the client's hull-direction table.
   Usage: HitAnalysis.mount(element, {ship:'12 Apostolov', compact:false}) with window.HIT_DATA loaded. */
(function(){
'use strict';
// Hull surface directions around the hull outline (client shared physics: ProjectedShipNormals), bow → stern, one side.
const N=[[1,0],[0.70710677,0.70710677],[0.7269121,0.6867306],[0.3794607,0.9252079],[0.00884719,0.9999609],[0.04054236,0.9991779],[-0.02138744,0.9997712],
 [-0.04306768,0.9990721],[-0.281508,0.9595589],[-0.2177823,0.9759973],[-0.1870278,0.9823547],[-0.4435308,0.8962591],[-0.4962481,0.8681807],[-0.7269121,0.6867306],
 [-0.9873866,0.158328],[-0.9873866,0.158328],[-0.9999427,0.01071631],[-1,0],[-1,0],[-1,0]];
const ZC={bow:'#2e9650',side:'#e18c28',stern:'#d23737'};
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function heat(v){const st=[[0,[40,50,90]],[.25,[60,110,190]],[.5,[90,190,120]],[.75,[240,200,60]],[1,[220,50,40]]];v=Math.max(0,Math.min(1,v));
 for(let i=1;i<st.length;i++)if(v<=st[i][0]){const [a,ca]=st[i-1],[b,cb]=st[i],t=(v-a)/(b-a);return `rgb(${ca.map((c,k)=>Math.round(c+(cb[k]-c)*t)).join(',')})`}return 'rgb(220,50,40)'}
function model(box){const cx=(box.min[0]+box.max[0])/2,cz=(box.min[2]+box.max[2])/2,hl=(box.max[0]-box.min[0])/2,hw=(box.max[2]-box.min[2])/2;
 const idx=(x,z)=>Math.min(19,Math.atan2(Math.abs(z-cz)/hw,(x-cx)/hl)/(2*Math.PI)*38);
 const zone=f=>f<2.5?'bow':f>13.5?'stern':'side';
 const normal=(x,z)=>{const f=idx(x,z),i0=Math.floor(f),i1=Math.min(19,i0+1),k=f-i0;let nx=N[i0][0]+(N[i1][0]-N[i0][0])*k,nz=(N[i0][1]+(N[i1][1]-N[i0][1])*k)*(z>=cz?1:-1);const l=Math.hypot(nx,nz)||1;return [nx/l,nz/l,f]};
 const entry=(dx,dz)=>{const t=Math.min(dx?hl/Math.abs(dx):1e9,dz?hw/Math.abs(dz):1e9);return [cx-dx*t,cz-dz*t]};
 return {cx,cz,hl,hw,idx,zone,normal,entry,box}}
function damageAt(M,x,z,dx,dz,p){const [nx,nz,f]=M.normal(x,z);const zn=M.zone(f);const c=Math.min(1,Math.max(1e-3,-(dx*nx+dz*nz)));const ang=Math.acos(c)*180/Math.PI;
 const arm=(p.armor+p.armorBonus)*(zn==='stern'?p.sternMul:zn==='bow'?p.bowMul:1);const eff=arm/Math.max(0.05,Math.cos(Math.min(85,ang)*Math.PI/180));
 const base=Math.max(p.minDmg,p.pen-p.armorWeight*eff);return {dmg:Math.max(0,base*p.df*p.scale),ang,zone:zn,eff}}
function fromBearing(M,b,p){const dx=-Math.cos(b*Math.PI/180),dz=-Math.sin(b*Math.PI/180);const [ex,ez]=M.entry(dx,dz);return damageAt(M,ex,ez,dx,dz,p)}

function draw(cv,M,p,ship){const ctx=cv.getContext('2d'),W=cv.width,H=cv.height;ctx.clearRect(0,0,W,H);
 const cxp=W/2,cyp=H/2,R1=Math.min(W,H)/2-44,R0=R1-30;const S=Math.min((R0-40)/M.hl,(R0-40)/(M.hw*3.2));
 const ring=[];for(let b=0;b<360;b+=2)ring.push([b,fromBearing(M,b,p)]);const rmax=Math.max(1,...ring.map(r=>r[1].dmg));
 for(const [b,r] of ring){const a0=(b-1.2)*Math.PI/180,a1=(b+1.2)*Math.PI/180;ctx.fillStyle=heat(r.dmg/rmax);ctx.beginPath();
  ctx.arc(cxp,cyp,R1,-a1,-a0);ctx.arc(cxp,cyp,R0,-a0,-a1,true);ctx.closePath();ctx.fill()}
 // perimeter: average damage over every direction that can reach that point of the box
 const P=(x,z)=>[cxp+(x-M.cx)*S,cyp-(z-M.cz)*S];let pmax=0;const pts=[];
 for(let k=0;k<720;k++){const th=k/720*2*Math.PI,c=Math.cos(th),s=Math.sin(th),t=1/Math.max(Math.abs(c)/M.hl,Math.abs(s)/M.hw),x=M.cx+c*t,z=M.cz+s*t;
  const onEnd=Math.abs(c)/M.hl>=Math.abs(s)/M.hw,fx=onEnd?Math.sign(c):0,fz=onEnd?0:Math.sign(s);let sum=0,n=0;
  for(let b=0;b<360;b+=6){const dx=-Math.cos(b*Math.PI/180),dz=-Math.sin(b*Math.PI/180);if(dx*fx+dz*fz>=0)continue;sum+=damageAt(M,x,z,dx,dz,p).dmg;n++}
  const v=n?sum/n:0;pmax=Math.max(pmax,v);pts.push([x,z,v,M.zone(M.idx(x,z))])}
 ctx.fillStyle='#e8eef4';const a=P(M.box.min[0],M.box.max[2]),b2=P(M.box.max[0],M.box.min[2]);ctx.fillRect(a[0],a[1],b2[0]-a[0],b2[1]-a[1]);
 // simple hull outline inside the box (pointed bow, flat stern)
 ctx.fillStyle='#9aa3ab';ctx.beginPath();const L=M.hl,Wd=M.hw*0.92;const hp=[[-L*0.97,-Wd*0.8],[L*0.45,-Wd],[L*0.98,0],[L*0.45,Wd],[-L*0.97,Wd*0.8]];
 hp.forEach(([x,z],i)=>{const q=P(M.cx+x,M.cz+z);i?ctx.lineTo(q[0],q[1]):ctx.moveTo(q[0],q[1])});ctx.closePath();ctx.fill();
 for(const [x,z,v,zn] of pts){const q=P(x,z);ctx.fillStyle=heat(v/(pmax||1));ctx.beginPath();ctx.arc(q[0],q[1],4.5,0,7);ctx.fill()}
 for(const [x,z,v,zn] of pts.filter((_,i)=>i%2==0)){const [nx,nz]=[x-M.cx,z-M.cz],l=Math.hypot(nx/M.hl,nz/M.hw)||1;const q=P(M.cx+(x-M.cx)*1.0,M.cz+(z-M.cz)*1.0);
  const out=[q[0]+(x-M.cx)/M.hl/l*12,q[1]-(z-M.cz)/M.hw/l*12];ctx.fillStyle=ZC[zn];ctx.fillRect(out[0]-2,out[1]-2,4,4)}
 ctx.fillStyle='#223';ctx.font='bold 13px system-ui,sans-serif';ctx.textAlign='center';
 const lab=(b,t)=>{const r=R1+14,an=b*Math.PI/180;ctx.fillText(t,cxp+Math.cos(an)*r,cyp-Math.sin(an)*r+4)};
 lab(0,'bow-on');lab(180,'stern');lab(90,'abeam');lab(270,'abeam');lab(45,'45°');lab(135,'135°');lab(315,'45°');lab(225,'135°');ctx.textAlign='left';
 return {ring,rmax}}

function sideView(cv,M){const ctx=cv.getContext('2d'),W=cv.width,H=cv.height;ctx.clearRect(0,0,W,H);const S=(W-120)/(2*M.hl),y0=H*0.62;
 const bx=x=>60+(x-M.box.min[0])*S;const top=y0-M.box.max[1]*S,bot=y0-M.box.min[1]*S;
 for(let x=M.box.min[0];x<M.box.max[0];x+=(M.box.max[0]-M.box.min[0])/240){const zn=M.zone(M.idx(x,M.box.max[2]));ctx.fillStyle=ZC[zn];ctx.globalAlpha=0.55;ctx.fillRect(bx(x),top,S*(M.box.max[0]-M.box.min[0])/240+1,bot-top)}
 ctx.globalAlpha=1;ctx.strokeStyle='#2878c8';ctx.lineWidth=2;ctx.strokeRect(bx(M.box.min[0]),top,(M.box.max[0]-M.box.min[0])*S,bot-top);
 ctx.strokeStyle='#4682b4';ctx.beginPath();ctx.moveTo(10,y0);ctx.lineTo(W-10,y0);ctx.stroke();ctx.fillStyle='#4682b4';ctx.font='12px system-ui';ctx.fillText('waterline',12,y0+14);
 ctx.fillStyle='#d23737';ctx.font='bold 13px system-ui';ctx.fillText('◄ stern',8,top-6);ctx.fillStyle='#2e9650';ctx.textAlign='right';ctx.fillText('bow ►',W-8,top-6);ctx.textAlign='left'}

function params(D,sel){const c=D.cannons.find(x=>x.n===sel.cannon)||D.cannons[0],a=D.ammo.find(x=>x.n===sel.ammo)||D.ammo[0],s=D.ships.find(x=>x.n===sel.ship);const cal=D.calib||{};
 return {pen:(c.pen||0)+(a.pen||0)+(+sel.penBonus||0),df:a.df||1,minDmg:a.min||0,armor:s?s.armor||0:0,armorBonus:+sel.armorBonus||0,
  sternMul:D.sternMul??0.5,bowMul:D.bowMul??1.3,armorWeight:cal.armor_weight??1,scale:cal.scale??1}}

const NOT_SHOT=/mortar|keg|rocket|firework|smoke|snow|phosphor|percussion/i;
function bar(v,top,col){const w=top>0?Math.max(0,Math.min(100,v/top*100)):0;return `<td class="ha-bar"><span style="width:${w.toFixed(0)}%;background:${col||'#3c6ebe'}"></span><b>${v.toFixed(1)}</b></td>`}
function glance(p,arm){return p.pen>arm*p.armorWeight?Math.acos(Math.min(1,arm*p.armorWeight/p.pen))*180/Math.PI:0}
function mortarF(d,r){const x=d-1;if(x<=0)return 1;if(x>r)return 0;return 0.1+0.9*Math.sqrt(1-x/r)}
const WS=0.3; // hull boxes are model units; ships sit in the world at 0.3 scale
function splashView(cv,M0,c){const M={hl:M0.hl*WS,hw:M0.hw*WS};const ctx=cv.getContext('2d'),W=cv.width,H=cv.height;ctx.clearRect(0,0,W,H);const R=c.splash||10;
 const S=Math.min((W-30)/(2*Math.max(M.hl,R+c.scatter)),(H-30)/(2*Math.max(M.hw,R+c.scatter)));const P=(x,z)=>[W/2+x*S,H/2-z*S];
 for(let k=40;k>=1;k--){const r=R*k/40;ctx.fillStyle=heat(mortarF(r,R));ctx.globalAlpha=0.55;ctx.beginPath();ctx.arc(W/2,H/2,r*S,0,7);ctx.fill()}ctx.globalAlpha=1;
 ctx.strokeStyle='#2878c8';ctx.lineWidth=2;const a=P(-M.hl,M.hw);ctx.strokeRect(a[0],a[1],2*M.hl*S,2*M.hw*S);
 ctx.setLineDash([5,4]);ctx.strokeStyle='#223';ctx.beginPath();ctx.arc(W/2,H/2,(c.scatter||0)*S,0,7);ctx.stroke();ctx.setLineDash([]);
 ctx.fillStyle='#223';ctx.font='12px system-ui';ctx.fillText(`splash radius ${R} · dashed = scatter ${c.scatter}`,8,H-8);ctx.fillStyle='#2e9650';ctx.textAlign='right';ctx.fillText('bow ►',W-8,16);ctx.textAlign='left'}
function mount(el,opts){const D=window.HIT_DATA;if(!D||!D.ships.length){el.innerHTML='<p class="note">No ship data in this build.</p>';return}
 const compact=!!opts.compact;const start=D.ships.find(s=>s.n===opts.ship)||D.ships.find(s=>s.box)||D.ships[0];
 const guns=D.cannons.filter(c=>!c.mortar&&(!c.mount||c.mount==='broadside')),mortars=D.cannons.filter(c=>c.mortar),shots=D.ammo.filter(a=>!NOT_SHOT.test(a.n));
 const defCannon=(guns.find(c=>c.n==='32-pdr Cannon')||guns[0]).n,defAmmo=(shots.find(a=>/cast-iron/i.test(a.n))||shots[0]).n,defMortar=(mortars.find(m=>/^8-inch/.test(m.n))||mortars[0]||{}).n;
 const opt=(list,cur)=>list.map(x=>`<option${x.n===cur?' selected':''}>${esc(x.n)}</option>`).join('');
 const det=(t,body)=>compact?`<details class="ha-more"><summary>${t}</summary>${body}</details>`:`<h3>${t}</h3>${body}`;
 el.innerHTML=`<div class="ha">
  <div class="ha-stats"></div>
  <div class="ha-controls">${compact?'':`<label>Target ship <select data-k="ship">${opt(D.ships,start.n)}</select></label>`}
   <label>Shooting with <select data-k="cannon">${opt(guns,defCannon)}</select></label>
   <label>Ammo <select data-k="ammo">${opt(shots,defAmmo)}</select></label>
   <label>Target armor + <input type="number" step="0.5" value="0" data-k="armorBonus" style="width:60px"></label><label>Penetration + <input type="number" step="0.5" value="0" data-k="penBonus" style="width:60px"></label></div>
  <div class="ha-grid"><div><canvas class="ha-top" width="${compact?460:600}" height="${compact?460:600}"></canvas>
   <div class="ha-legend"><span>0</span><i></i><span class="ha-max"></span> damage per ball · ring = firing from that direction at the centre · dots = average over every direction that can reach that spot</div></div>
  <div class="ha-side-col"><canvas class="ha-side" width="${compact?360:520}" height="${compact?150:190}"></canvas><p class="ha-note">Side view: the zone you hit when firing square-on from the side. Height on the box makes no difference.</p>
   <table class="wikitable ha-table"></table><div class="ha-cards"></div></div></div>
  ${det('Every ammo against this ship','<p class="ha-note">With the gun picked above. Side = square-on broadside; glancing limit = how far off square a side hit still does damage.</p><table class="wikitable ha-ammo"></table>')}
  ${det('Every broadside gun against this ship','<p class="ha-note">With the ammo picked above. Per minute = one side\'s guns firing continuously, square-on, every ball hitting.</p><table class="wikitable ha-guns"></table>')}
  ${mortars.length?det('Mortars and the keg launcher','<p class="ha-note">Shells fall from above, so angle and zone don\'t apply: damage depends on how close the burst is to the ship (the splash falls off from the centre). A mortar or keg hit sinks a ship that is already sinking.</p><label>Mortar <select data-k="mortar">'+opt(mortars,defMortar)+'</select></label><div class="ha-grid"><canvas class="ha-splash" width="420" height="220"></canvas><table class="wikitable ha-mortars"></table></div>'):''}
  <p class="ha-note ha-src"></p></div>`;
 const q=k=>el.querySelector(`[data-k="${k}"]`);const sel={ship:start.n,cannon:defCannon,ammo:defAmmo,armorBonus:0,penBonus:0,mortar:defMortar};
 function render(){const s=D.ships.find(x=>x.n===sel.ship);const box=s.box||{min:[-25,-4,-6],max:[25,8,6]};const M=model(box);const p=params(D,sel);
  const r=draw(el.querySelector('.ha-top'),M,p,s);sideView(el.querySelector('.ha-side'),M);el.querySelector('.ha-max').textContent=r.rmax.toFixed(1);
  const pt=s.ports||{};const card=(k,v)=>v==null||v===''?'':`<div><span>${k}</span><b>${v}</b></div>`;
  el.querySelector('.ha-stats').innerHTML=card('Rank',s.rank)+card('Class',s.cls)+card('Hull HP',s.hp?Math.round(s.hp).toLocaleString():'')+card('Armor',s.armor!=null?(+s.armor).toFixed(1):'')+
   card('Gun ports per side',pt.left!=null?pt.left:'')+card('Bow / stern',pt.bow!=null||pt.stern!=null?`${pt.bow||0} / ${pt.stern||0}`:'')+card('Swivels',pt.swivel||'')+card('Mortars',pt.mortar||'')+
   card('Masts / sails',s.masts!=null?`${s.masts} / ${s.sails}`:'')+card('Crew',s.crew?Math.round(s.crew):'')+card('Speed',s.speed?(+s.speed).toFixed(1):'')+
   card('Hull box',s.box?`${(box.max[0]-box.min[0]).toFixed(0)} × ${(box.max[2]-box.min[2]).toFixed(0)} × ${(box.max[1]-box.min[1]).toFixed(0)}`:'');
  const rows=[[90,'Broadside, square on'],[60,'30° off the beam'],[45,'From the bow quarter'],[15,'Nearly bow-on'],[0,'Bow-on'],[135,'From the stern quarter'],[165,'Nearly stern-on'],[180,'Stern rake']];
  el.querySelector('.ha-table').innerHTML='<tr><th>Firing from</th><th>Hits</th><th>Angle</th><th>Damage</th></tr>'+rows.map(([b,t])=>{const d=fromBearing(M,b,p);
   return `<tr><td>${t}</td><td style="color:${ZC[d.zone]};font-weight:600">${d.zone}</td><td>${d.ang.toFixed(0)}°</td><td><b>${d.dmg.toFixed(1)}</b></td></tr>`}).join('');
  const dead=r.ring.filter(([b,d])=>d.dmg<=0.05).map(([b])=>b);const deadTxt=dead.length?`Dead zone (no damage): ${dead.length*2}° of the circle, mostly ${dead.some(b=>b<90||b>270)?'off the bow quarters':'astern'}.`:'Every direction does some damage with this gun.';
  const arm=(s.armor||0)+p.armorBonus,lim=glance(p,arm);
  el.querySelector('.ha-cards').innerHTML=`<p>${p.pen>arm*p.armorWeight?`Side hits more than <b>${lim.toFixed(0)}°</b> off square do nothing (glancing).`:`This gun can't get through the side at any angle; aim for the stern.`} ${deadTxt}</p>`;
  // every ammo
  const cn=D.cannons.find(c=>c.n===sel.cannon)||guns[0];const am=shots.map(a=>{const pp=params(D,{...sel,ammo:a.n});return {a,side:fromBearing(M,90,pp).dmg,bow:fromBearing(M,0,pp).dmg,stern:fromBearing(M,180,pp).dmg,lim:glance(pp,arm)}});
  const top=Math.max(1,...am.map(x=>Math.max(x.side,x.stern)));
  el.querySelector('.ha-ammo').innerHTML='<tr><th>Ammo</th><th>Side</th><th>Bow-on</th><th>Stern rake</th><th>Glancing limit</th><th>Sail dmg</th><th>Crew dmg</th><th>Reload</th></tr>'+
   am.sort((x,y)=>y.side-x.side).map(x=>`<tr${x.a.n===sel.ammo?' class="ha-cur"':''}><td>${esc(x.a.n)}</td>${bar(x.side,top,'#e18c28')}${bar(x.bow,top,'#2e9650')}${bar(x.stern,top,'#d23737')}<td>${x.lim?x.lim.toFixed(0)+'°':'none'}</td><td>${x.a.sail??''}</td><td>${x.a.crew??''}</td><td>×${(x.a.reload||1).toFixed(2)}</td></tr>`).join('');
  // every gun
  const side=pt.left||0;const gs=guns.map(c=>{const pp=params(D,{...sel,cannon:c.n});const d=fromBearing(M,90,pp).dmg;const am0=D.ammo.find(a=>a.n===sel.ammo)||{};const rl=(c.reload||10)*(am0.reload||1);
   return {c,side:d,stern:fromBearing(M,180,pp).dmg,lim:glance(pp,arm),pm:side?d*side*60/rl:d*60/rl}});const tg=Math.max(1,...gs.map(x=>Math.max(x.side,x.stern))),tm=Math.max(1,...gs.map(x=>x.pm));
  el.querySelector('.ha-guns').innerHTML=`<tr><th>Gun</th><th>Range</th><th>Reload</th><th>Side</th><th>Stern rake</th><th>Glancing limit</th><th>${side?'Broadside per minute ('+side+' guns)':'Per gun per minute'}</th></tr>`+
   gs.sort((x,y)=>y.pm-x.pm).map(x=>`<tr${x.c.n===sel.cannon?' class="ha-cur"':''}><td>${esc(x.c.n)}</td><td>${x.c.max??''}</td><td>${x.c.reload??''} s</td>${bar(x.side,tg,'#e18c28')}${bar(x.stern,tg,'#d23737')}<td>${x.lim?x.lim.toFixed(0)+'°':'none'}</td>${bar(x.pm,tm,'#3c6ebe')}</tr>`).join('');
  // mortars
  const mc=el.querySelector('.ha-splash');if(mc){const m=mortars.find(x=>x.n===sel.mortar)||mortars[0];splashView(mc,M,m);
   const base=c=>Math.max(0,(c.pen||0)-arm*p.armorWeight)*p.scale;const corner=Math.hypot(M.hl,M.hw);
   el.querySelector('.ha-mortars').innerHTML='<tr><th>Mortar</th><th>Range</th><th>Reload</th><th>Splash</th><th>Centre hit</th><th>At bow/stern tip</th><th>Per minute</th></tr>'+
    mortars.map(c=>{const b=base(c);return `<tr${c.n===sel.mortar?' class="ha-cur"':''}><td>${esc(c.n)}</td><td>${c.min}–${c.max}</td><td>${c.reload} s</td><td>${c.splash}</td><td><b>${b.toFixed(0)}</b></td><td>${(b*mortarF(M.hl*WS,c.splash)).toFixed(0)}</td><td>${(b*60/c.reload).toFixed(0)}</td></tr>`}).join('')}
  el.querySelector('.ha-src').textContent=(s.box?'Hull box rebuilt from the game model; ':'No rebuilt hull box for this ship, so typical proportions are used; ')+'zones from the client\'s hull-direction table. '+
   (D.calib&&D.calib.calibrated?`Damage calibrated from ${D.calib.samples} measured hits.`:'Damage is an estimate: penetration − armor ÷ cos(angle), stern armor ×0.5, bow ×1.3; mortar = penetration − armor with the splash fall-off (the server decides exact numbers).')}
 for(const k of Object.keys(sel)){const e=q(k);if(e)e.addEventListener(e.tagName==='INPUT'?'input':'change',()=>{sel[k]=e.type==='number'?+e.value:e.value;render()})}
 render()}
window.HitAnalysis={mount,model,fromBearing,damageAt,params};
})();
