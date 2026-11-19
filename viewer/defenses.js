/* WoSB defenses: port-battle towers and forts, mortars and the keg launcher.
   Usage: Defenses.mount(element) with window.HIT_DATA (ships, cannons, ammo, towers, pb) loaded. */
(function(){
'use strict';
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const COL=['#3c6ebe','#e18c28','#2e9650','#d23737','#8a5cc2','#1f9aa8','#b8860b','#c2185b','#555'];
function mortarF(d,r){const x=d-1;if(x<=0)return 1;if(x>r)return 0;return 0.1+0.9*Math.sqrt(1-x/r)}
const WS=0.3; // ship models are drawn at 0.3 scale in the world
function strength(pb,rank,team,level,tower){const base=pb.base[Math.max(1,rank)]||pb.base_low;const tf=pb.team[team]??1;const lf=pb.level[level]??1;
 return Math.round(base[tower?0:1]*tf*lf/100)*100}
function ballDmg(D,gun,armor){const a=D.ammo.find(x=>/cast-iron/i.test(x.n))||{};const cal=D.calib||{};return Math.max(a.min||0,(gun.pen||0)+(a.pen||0)-(cal.armor_weight??1)*armor)*(a.df||1)*(cal.scale??1)}

function rangeView(cv,st){const {tw,ship,dist,gun}=st;const ctx=cv.getContext('2d'),W=cv.width,H=cv.height;ctx.clearRect(0,0,W,H);
 const S=Math.min((W-70)/(dist+(gun.max||130)),(H-30)/(2*Math.max(tw.range||150,gun.max||130))),cx=40,cy=H/2;const X=x=>cx+x*S;
 ctx.fillStyle='#eaf2f8';ctx.fillRect(0,0,W,H);
 // tower reach (half-disc toward the ship is enough to read it)
 ctx.fillStyle='rgba(210,55,55,.16)';ctx.beginPath();ctx.arc(cx,cy,(tw.range||0)*S,-Math.PI/2,Math.PI/2);ctx.fill();
 ctx.fillStyle='rgba(90,100,110,.35)';ctx.beginPath();ctx.arc(cx,cy,(tw.dead||0)*S,-Math.PI/2,Math.PI/2);ctx.fill();
 ctx.strokeStyle='#d23737';ctx.lineWidth=2;ctx.beginPath();ctx.arc(cx,cy,(tw.range||0)*S,-Math.PI/2,Math.PI/2);ctx.stroke();
 ctx.setLineDash([6,4]);ctx.strokeStyle='#2e9650';ctx.beginPath();ctx.arc(cx,cy,st.pb.capture_r*S,-Math.PI/2,Math.PI/2);ctx.stroke();ctx.setLineDash([]);
 ctx.fillStyle='#5b4636';ctx.beginPath();ctx.arc(cx,cy,9,0,7);ctx.fill();
 // ship broadside reach
 const sx=X(dist);ctx.fillStyle='rgba(60,110,190,.14)';ctx.beginPath();ctx.arc(sx,cy,(gun.max||0)*S,0,7);ctx.fill();ctx.strokeStyle='#3c6ebe';ctx.beginPath();ctx.arc(sx,cy,(gun.max||0)*S,0,7);ctx.stroke();
 const b=ship.box||{min:[-25,0,-6],max:[25,8,6]};const hl=(b.max[0]-b.min[0])/2*WS*S,hw=(b.max[2]-b.min[2])/2*WS*S;
 ctx.save();ctx.translate(sx,cy);ctx.rotate(Math.PI/2);ctx.fillStyle='#223';ctx.beginPath();ctx.moveTo(hl,0);ctx.lineTo(hl*0.4,-hw);ctx.lineTo(-hl,-hw*0.8);ctx.lineTo(-hl,hw*0.8);ctx.lineTo(hl*0.4,hw);ctx.closePath();ctx.fill();ctx.restore();
 ctx.font='12px system-ui';ctx.fillStyle='#d23737';ctx.fillText(`tower reach ${tw.range}`,cx+(tw.range||0)*S*0.72+4,cy-(tw.range||0)*S*0.72);
 if(tw.dead){ctx.fillStyle='#555';ctx.fillText(`dead zone ${tw.dead}`,cx+4,cy+(tw.dead*S)+14)}
 ctx.fillStyle='#2e9650';ctx.fillText(`capture ring ${st.pb.capture_r}`,cx+4,cy-st.pb.capture_r*S-4);
 ctx.fillStyle='#3c6ebe';ctx.fillText(`your guns ${gun.max}`,sx+6,cy-(gun.max||0)*S*0.7);
 ctx.fillStyle='#223';ctx.fillText(`${dist} units`,sx-18,cy+hl+16)}

function mortarRanges(cv,list){const ctx=cv.getContext('2d'),W=cv.width,H=cv.height;ctx.clearRect(0,0,W,H);const mx=Math.max(...list.map(m=>m.max))+10;
 const L=150,S=(W-L-20)/mx,rh=(H-30)/list.length;ctx.font='12px system-ui';
 list.forEach((m,i)=>{const y=10+i*rh;ctx.fillStyle='#223';ctx.textAlign='right';ctx.fillText(m.n,L-8,y+rh*0.65);ctx.textAlign='left';
  ctx.fillStyle='rgba(90,100,110,.25)';ctx.fillRect(L,y+3,m.min*S,rh-6);ctx.fillStyle=m.tower?'#d23737':COL[i%COL.length];ctx.fillRect(L+m.min*S,y+3,(m.max-m.min)*S,rh-6);
  ctx.fillStyle='#fff';ctx.fillText(`${m.min}–${m.max}`,L+m.min*S+4,y+rh*0.65)});
 ctx.fillStyle='#555';for(let d=0;d<=mx;d+=25){ctx.fillRect(L+d*S,H-18,1,4);ctx.fillText(d,L+d*S-6,H-4)}}

function falloff(cv,list){const ctx=cv.getContext('2d'),W=cv.width,H=cv.height;ctx.clearRect(0,0,W,H);const mx=Math.max(...list.map(m=>m.splash))+2;
 const L=40,B=H-28,S=(W-L-10)/mx;ctx.strokeStyle='#ccc';ctx.font='11px system-ui';ctx.fillStyle='#555';
 for(let v=0;v<=1;v+=0.25){const y=B-v*(B-10);ctx.beginPath();ctx.moveTo(L,y);ctx.lineTo(W-10,y);ctx.stroke();ctx.fillText((v*100)+'%',4,y+4)}
 for(let d=0;d<=mx;d+=5)ctx.fillText(d,L+d*S-4,H-12);ctx.fillText('distance from the burst',W/2-50,H-1);
 list.forEach((m,i)=>{ctx.strokeStyle=COL[i%COL.length];ctx.lineWidth=2;ctx.beginPath();for(let d=0;d<=mx;d+=0.25){const x=L+d*S,y=B-mortarF(d,m.splash)*(B-10);d?ctx.lineTo(x,y):ctx.moveTo(x,y)}ctx.stroke()})}

function mount(el){const D=window.HIT_DATA;if(!D||!D.towers){el.innerHTML='<p class="note">No defense data in this build.</p>';return}
 const pb=D.pb,guns=D.cannons.filter(c=>!c.mortar),mortars=D.cannons.filter(c=>c.mortar);const opt=(l,c)=>l.map(x=>`<option${x.n===c?' selected':''}>${esc(x.n)}</option>`).join('');
 const ships=D.ships.filter(s=>s.hp);const defShip=(ships.find(s=>s.n==='Bellona')||ships[0]).n,defGun=(guns.find(c=>c.n==='32-pdr Long Gun')||guns[0]).n;
 el.innerHTML=`<div class="ha">
 <h2>Towers</h2><div class="ha-controls"><label>Tower <select data-k="tower">${D.towers.map((t,i)=>`<option value="${i}">${esc(t.n)}</option>`).join('')}</select></label>
  <label>Your ship <select data-k="ship">${opt(ships,defShip)}</select></label><label>Your guns <select data-k="gun">${opt(guns,defGun)}</select></label>
  <label>Distance <input type="range" min="10" max="250" value="120" data-k="dist"> <span class="dv">120</span></label></div>
 <div class="ha-grid"><canvas class="df-range" width="620" height="420"></canvas><div class="ha-side-col"><div class="df-verdict"></div><table class="wikitable df-duel"></table></div></div>
 <h2>Tower and fort strength</h2><div class="ha-controls"><label>Port level <select data-k="level">${[1,2,3,4,5,6,7].map(l=>`<option>${l}</option>`).join('')}</select></label><label>Attackers in the duel <input type="number" min="1" max="40" value="5" data-k="ships" style="width:60px"></label></div>
 <p class="ha-note">Hit points by the battle's minimum ship rank (rows) and team size (columns). Towers / guild fort. Bigger teams and higher port levels give stronger buildings.</p><table class="wikitable df-str"></table>
 <h2>Mortars and the keg launcher</h2><p class="ha-note">Mortars can't hit anything closer than their minimum range (grey). Damage falls off with distance from the burst: full at the centre, about 10% at the edge of the splash.</p>
 <div class="ha-grid"><canvas class="df-mr" width="620" height="${30+(mortars.length+1)*26}"></canvas><canvas class="df-fo" width="380" height="240"></canvas></div>
 <div class="ha-controls"><label>Against <select data-k="mship">${opt(ships,defShip)}</select></label></div><table class="wikitable df-mt"></table>
 <p class="ha-note">Tower weapons, ranges, capture times and building strength are from the game's port-battle tables. Ship-vs-building damage uses cast-iron shot against tower armor ${pb.tower_armor} (an estimate).</p></div>`;
 const st={tower:0,ship:defShip,gun:defGun,dist:120,level:1,ships:5,mship:defShip,pb};const q=k=>el.querySelector(`[data-k="${k}"]`);
 function render(){const tw=D.towers[st.tower],ship=D.ships.find(s=>s.n===st.ship),gun=D.cannons.find(c=>c.n===st.gun);el.querySelector('.dv').textContent=st.dist;
  rangeView(el.querySelector('.df-range'),{tw,ship,dist:st.dist,gun,pb});
  const towerGun=tw.gun?D.cannons.find(c=>c.n===tw.gun):null;const perHit=tw.dmg??(towerGun?ballDmg(D,towerGun,ship.armor||0):0),cd=tw.cd??(towerGun?towerGun.reload:15);
  const inT=st.dist>=(tw.dead||0)&&st.dist<=tw.range,inY=st.dist<=(gun.max||0);const tdpm=perHit*60/cd;
  const ports=(ship.ports&&ship.ports.left)||10;const yHit=ballDmg(D,gun,pb.tower_armor);const ydpm=yHit*ports*60/gun.reload;const thp=strength(pb,ship.rank||5,10,st.level,true);
  el.querySelector('.df-verdict').innerHTML=`<p><b>${inT?'The tower can hit you here.':st.dist<(tw.dead||0)?'Inside the dead zone: the tower can\'t hit you.':'Out of the tower\'s reach.'}</b> ${inY?'Your guns reach it.':'Your guns don\'t reach it.'}${!inT&&inY?' <b>Safe firing spot.</b>':''}</p>
   <p>${esc(tw.n)}: ${tw.note}</p>`;
  el.querySelector('.df-duel').innerHTML=`<tr><th></th><th>Tower → ${esc(ship.n)}</th><th>${esc(ship.n)} → tower</th></tr>
   <tr><td>Per hit</td><td>${perHit.toFixed(1)}${tw.dmg==null?' (est.)':''}</td><td>${yHit.toFixed(1)} per ball (est.)</td></tr>
   <tr><td>Per minute</td><td>${tdpm.toFixed(0)} per weapon</td><td>${ydpm.toFixed(0)} (${ports} guns)</td></tr>
   <tr><td>To finish</td><td>${ship.hp?(ship.hp/tdpm).toFixed(1)+' min, one weapon':''}</td><td>${(thp/(ydpm*st.ships)).toFixed(1)} min with ${st.ships} ships (tower ${thp.toLocaleString()} HP, 10 v 10, port level ${st.level})</td></tr>`;
  const teams=Object.keys(pb.team).map(Number).sort((a,b)=>a-b);
  el.querySelector('.df-str').innerHTML='<tr><th>Rank</th>'+teams.map(t=>`<th>${t} v ${t}</th>`).join('')+'</tr>'+[1,2,3,4,5,6].map(r=>`<tr><td>${r===6?'6–7':r}</td>`+teams.map(t=>`<td>${strength(pb,r,t,st.level,true).toLocaleString()} / ${strength(pb,r,t,st.level,false).toLocaleString()}</td>`).join('')+'</tr>').join('');
  const ml=[...mortars.map(m=>({n:m.n,min:m.min,max:m.max,splash:m.splash})),...D.towers.filter(t=>t.kind==='mortar').map(t=>({n:t.n,min:t.dead,max:t.range,splash:15,tower:true}))];
  mortarRanges(el.querySelector('.df-mr'),ml);falloff(el.querySelector('.df-fo'),mortars);
  const ms=D.ships.find(s=>s.n===st.mship);const cal=D.calib||{};
  el.querySelector('.df-mt').innerHTML='<tr><th>Weapon</th><th>Range</th><th>Reload</th><th>Splash / scatter</th><th>Penetration</th><th>Centre hit</th><th>Half-way out</th><th>Per minute</th><th></th></tr>'+mortars.map((m,i)=>{
   const b=Math.max(0,(m.pen||0)-(cal.armor_weight??1)*(ms.armor||0))*(cal.scale??1);return `<tr><td><span class="sw" style="background:${COL[i%COL.length]}"></span>${esc(m.n)}</td><td>${m.min}–${m.max}</td><td>${m.reload} s</td><td>${m.splash} / ${m.scatter}</td><td>${m.pen}</td><td><b>${b.toFixed(0)}</b></td><td>${(b*mortarF(m.splash/2,m.splash)).toFixed(0)}</td><td>${(b*60/m.reload).toFixed(0)}</td><td>${/keg/i.test(m.n)?'Fires powder kegs: biggest splash, lowest penetration':m.feature==='HeavyMortar'?'Tight scatter':''}</td></tr>`}).join('')}
 for(const k of Object.keys(st)){const e=q(k);if(e)e.addEventListener(e.tagName==='INPUT'?'input':'change',()=>{st[k]=e.type==='range'||e.type==='number'||k==='tower'||k==='level'?+e.value:e.value;render()})}
 render()}
window.Defenses={mount,strength,mortarF};
})();
