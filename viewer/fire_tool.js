/* WoSB fire calculator: minor fires, the large-fire threshold, large-fire strength and an ignition-chance tally.
   Usage: FireTool.mount(element) with window.HIT_DATA (ships) loaded. Rules from the client (ShipFirstHp, MicroburningEffect). */
(function(){
'use strict';
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const roundEven=x=>{const f=Math.floor(x),d=x-f;return d>0.5?f+1:d<0.5?f:(f%2?f+1:f)}; // .NET Math.Round
const need=maxHp=>1+roundEven(maxHp/1000);
function poissonAtLeast(mean,k){let p=Math.exp(-mean),c=p;for(let i=1;i<k;i++){p*=mean/i;c+=p}return Math.max(0,1-c)}
function binomAtLeast(n,p,k){if(k>n)return 0;let s=0;for(let i=k;i<=n;i++){let c=1;for(let j=0;j<i;j++)c=c*(n-j)/(j+1);s+=c*Math.pow(p,i)*Math.pow(1-p,n-i)}return Math.min(1,s)}
function wilson(x,n,z=1.96){if(n<=0)return null;const p=Math.min(1,x/n),d=1+z*z/n,c=(p+z*z/(2*n))/d,h=z*Math.sqrt(p*(1-p)/n+z*z/(4*n*n))/d;return [p,Math.max(0,c-h),Math.min(1,c+h)]}
function flare(type,t,D){if(type==='finite'){if(t>12)return 0;const x=t/12;return x*(1-x)*4*0.6}if(type==='infinite')return Math.min(1,t/4);
 return Math.min(Math.max(0.01,1-D),Math.pow(t/12,1.7)*0.7+(t<12?0:(t-12)/2))}
function curve(cv,fightEvery,speed){const ctx=cv.getContext('2d'),W=cv.width,H=cv.height;ctx.clearRect(0,0,W,H);const L=36,B=H-26,T=20,S=(W-L-10)/20;
 ctx.font='11px system-ui';ctx.strokeStyle='#ddd';ctx.fillStyle='#555';for(let v=0;v<=1;v+=0.25){const y=B-v*(B-10);ctx.beginPath();ctx.moveTo(L,y);ctx.lineTo(W-10,y);ctx.stroke();ctx.fillText(v.toFixed(2),2,y+4)}
 for(let s=0;s<=20;s+=4)ctx.fillText(s+' s',L+s*S-6,H-8);ctx.setLineDash([3,3]);ctx.strokeStyle='#999';ctx.beginPath();ctx.moveTo(L+12*S,10);ctx.lineTo(L+12*S,B);ctx.stroke();ctx.setLineDash([]);
 const series=[['finite','#f2a33a'],['infinite','#8f1f12'],['mendable','#e0552b'],['fought','#2f7fbf']];
 for(const [k,col] of series){let D=0,last=-1e9;ctx.strokeStyle=col;ctx.lineWidth=2.2;ctx.beginPath();
  for(let t=0;t<=20;t+=0.05){if(k==='fought'&&fightEvery>0&&t>=2&&t-last>=fightEvery){D=Math.min(1,(D+0.24))*speed;D=Math.min(1,D);last=t}const y=B-flare(k==='fought'?'mendable':k,t,D)*(B-10);t?ctx.lineTo(L+t*S,y):ctx.moveTo(L+t*S,y);D=Math.max(0,D-0.1*0.05)}ctx.stroke()}
 const lab=[['Finite','#f2a33a'],['Infinite','#8f1f12'],['Mendable, left alone','#e0552b'],['Mendable, fought','#2f7fbf']];lab.forEach(([t,c],i)=>{ctx.fillStyle=c;ctx.fillRect(L+8,T+i*15-8,10,10);ctx.fillStyle='#223';ctx.fillText(t,L+22,T+i*15+1)})}

function mount(el){const D=window.HIT_DATA||{ships:[]};const ships=D.ships.filter(s=>s.hp).sort((a,b)=>a.hp-b.hp);const def=(ships.find(s=>s.n==='Bellona')||ships[0]||{n:'',hp:3000});
 el.innerHTML=`<div class="ha">
 <h2>Your ship</h2><div class="ha-controls"><label>Ship <select data-k="ship">${ships.map(s=>`<option${s.n===def.n?' selected':''}>${esc(s.n)}</option>`).join('')}</select></label>
  <label>Current HP <input type="range" min="1" max="100" value="60" data-k="hpPct"> <span class="v-hp"></span></label>
  <label><input type="checkbox" data-k="crew"> Special crew (minor fires +25%)</label><label><input type="checkbox" data-k="plates"> Large Plates (+50%)</label>
  <label>Other minor-fire bonus % <input type="number" value="0" min="0" max="95" data-k="extra" style="width:60px"></label></div>
 <div class="ha-stats fire-stats"></div>
 <h2>Under fire</h2><div class="ha-controls"><label>Enemy hits per broadside <input type="number" value="12" min="1" max="60" data-k="hits" style="width:60px"></label>
  <label>Broadsides per minute (all enemies) <input type="number" value="4" min="0.5" step="0.5" data-k="rate" style="width:60px"></label>
  <label>Ignition chance per hit % <input type="number" value="10" min="0" max="100" step="0.5" data-k="p" style="width:60px"></label></div>
 <p class="ha-note">The chance per hit is decided on the game's servers. 10% is a starting estimate: count your own below and enter it here.</p><div class="fire-out"></div>
 <h2>Large fire strength</h2><div class="ha-controls"><label>Fight it every <input type="number" value="2" min="0" step="0.5" data-k="every" style="width:60px"> s</label><label><input type="checkbox" data-k="bigcrew"> Special crew (large fires +40%)</label></div>
 <canvas class="fire-curve" width="620" height="260"></canvas>
 <p class="ha-note">Finite fires (12 s) come from some events and burn out by themselves. Mendable fires (burning rams) pass a point of no return at 12 s unless fought; repairs put them out. Infinite fires reach full strength in 4 s and repairs can't stop them.</p>
 <h2>Work out the ignition chance</h2><p class="ha-note">In your own battles, count your hits and the minor fires they start. About 150 hits pins it down to roughly ±5%.</p>
 <div class="ha-controls"><label>Hits <input type="number" value="0" min="0" data-k="th" style="width:80px"></label><label>Minor fires started <input type="number" value="0" min="0" data-k="tf" style="width:80px"></label></div><div class="fire-tally"></div></div>`;
 const st={ship:def.n,hpPct:60,crew:false,plates:false,extra:0,hits:12,rate:4,p:10,every:2,bigcrew:false,th:0,tf:0};const q=k=>el.querySelector(`[data-k="${k}"]`);
 function render(){const s=ships.find(x=>x.n===st.ship)||def;const k=need(s.hp);const bonus=Math.min(0.95,(st.crew?0.25:0)+(st.plates?0.5:0)+(+st.extra||0)/100);const f=1-bonus;
  const lo=6*f,hi=10*f,avg=8*f;el.querySelector('.v-hp').textContent=st.hpPct+'%';
  const can=st.hpPct>=5&&st.hpPct<=95,mult=1/(0.5+0.5*st.hpPct/100);
  const card=(a,b)=>`<div><span>${a}</span><b>${b}</b></div>`;
  el.querySelector('.fire-stats').innerHTML=card('Max HP',Math.round(s.hp).toLocaleString())+card('Minor fires for a large fire',k)+card('One minor fire burns',`${lo.toFixed(1)}–${hi.toFixed(1)} s`)+
   card('Damage per minor fire',`${(4*lo).toFixed(0)}–${(4*hi).toFixed(0)} HP`)+card('Large fire possible now',can?'yes':'no (HP outside 5–95%)')+card('Check speed vs full HP',can?'×'+mult.toFixed(2):'—');
  const p=Math.max(0,Math.min(1,st.p/100)),lam=st.hits*st.rate/60*p,mean=lam*avg;const burst=binomAtLeast(Math.round(st.hits),p,k);const steady=poissonAtLeast(mean,k);
  el.querySelector('.fire-out').innerHTML=`<table class="wikitable"><tr><td>New minor fires</td><td><b>${(lam*60).toFixed(1)}</b> per minute</td></tr>
   <tr><td>Burning at once, on average</td><td><b>${mean.toFixed(1)}</b> (needs ${k})</td></tr>
   <tr><td>Chance one broadside alone reaches ${k}</td><td><b>${(burst*100).toFixed(1)}%</b></td></tr>
   <tr><td>Share of time at or above ${k}</td><td><b>${(steady*100).toFixed(1)}%</b>${can?'':' (but no check runs at this HP)'}</td></tr>
   <tr><td>Minor-fire damage per minute</td><td><b>${(mean*4*60).toFixed(0)}</b> HP</td></tr></table>`;
  curve(el.querySelector('.fire-curve'),+st.every||0,st.bigcrew?1.4:1);
  const w=wilson(+st.tf||0,+st.th||0);el.querySelector('.fire-tally').innerHTML=w?`<p>Measured: <b>${(w[0]*100).toFixed(1)}%</b> per hit (95% range ${(w[1]*100).toFixed(1)}–${(w[2]*100).toFixed(1)}%).</p>`:'<p class="ha-note">Enter your counts to see the rate.</p>'}
 for(const k of Object.keys(st)){const e=q(k);if(!e)continue;e.addEventListener(e.type==='checkbox'?'change':e.tagName==='SELECT'?'change':'input',()=>{st[k]=e.type==='checkbox'?e.checked:e.tagName==='SELECT'?e.value:+e.value;render()})}
 render()}
window.FireTool={mount,need,wilson,flare,binomAtLeast,poissonAtLeast};
})();
