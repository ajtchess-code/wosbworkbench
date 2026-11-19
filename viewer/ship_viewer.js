/* WoSB 3D ship viewer: real ship models from the Compendium's model pack, the client's invisible hitboxes,
   a damage/angle heatmap painted onto the hull, a cannonball you can fire at any point of the ship, and the
   in-game designs (skins, sail textures, sail emblems, flags and figureheads).
   Usage: ShipViewer.mount(element, {ship}) with window.SHIP_VIEW and window.HIT_DATA loaded and HitAnalysis available. */
(function(){
'use strict';
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
// The client's sail pattern slots: Decal1 (all sails by default), Decal2 and the premium extra slot Decal3
// (square/animated sails by default), each switched on or off per sail (Decal*SelectedSailesBits by SailStrengthIndex).
const PATS=[{label:'Paint',list:'Decal1',def:'all'},{label:'Pattern',list:'Decal2',def:'animated'},{label:'Extra pattern (premium)',list:'Decal2',def:'animated'}];
// A main flag can exist twice in a model (free-flying and the copy fixed to the frame); both carry the same slot.
const flagKey=m=>m.replace(/_?FixToFrame$/i,'');
const ZC={bow:[0.18,0.59,0.31],side:[0.88,0.55,0.16],stern:[0.82,0.22,0.22]};
const HEAT=[[0,[40,50,90]],[.25,[60,110,190]],[.5,[90,190,120]],[.75,[240,200,60]],[1,[220,50,40]]];
function heat(v){v=Math.max(0,Math.min(1,v));for(let i=1;i<HEAT.length;i++)if(v<=HEAT[i][0]){const [a,ca]=HEAT[i-1],[b,cb]=HEAT[i],t=(v-a)/(b-a);return ca.map((c,k)=>(c+(cb[k]-c)*t)/255)}return [0.86,0.2,0.16]}
// ---------------------------------------------------------------- tiny matrix helpers (column-major)
const M4={mul(a,b){const o=new Float32Array(16);for(let i=0;i<4;i++)for(let j=0;j<4;j++){let s=0;for(let k=0;k<4;k++)s+=a[k*4+j]*b[i*4+k];o[i*4+j]=s}return o},
 persp(f,asp,n,fa){const t=1/Math.tan(f/2);return new Float32Array([t/asp,0,0,0,0,t,0,0,0,0,(fa+n)/(n-fa),-1,0,0,2*fa*n/(n-fa),0])},
 look(e,c,u){const z=norm(sub(e,c)),x=norm(cross(u,z)),y=cross(z,x);return new Float32Array([x[0],y[0],z[0],0,x[1],y[1],z[1],0,x[2],y[2],z[2],0,-dot(x,e),-dot(y,e),-dot(z,e),1])},
 trs(t,s,ry){const c=Math.cos(ry||0),n=Math.sin(ry||0);return new Float32Array([c*s,0,-n*s,0,0,s,0,0,n*s,0,c*s,0,t[0],t[1],t[2],1])},
 inv(m){const a=m,o=new Float32Array(16);const b00=a[0]*a[5]-a[1]*a[4],b01=a[0]*a[6]-a[2]*a[4],b02=a[0]*a[7]-a[3]*a[4],b03=a[1]*a[6]-a[2]*a[5],b04=a[1]*a[7]-a[3]*a[5],b05=a[2]*a[7]-a[3]*a[6],
  b06=a[8]*a[13]-a[9]*a[12],b07=a[8]*a[14]-a[10]*a[12],b08=a[8]*a[15]-a[11]*a[12],b09=a[9]*a[14]-a[10]*a[13],b10=a[9]*a[15]-a[11]*a[13],b11=a[10]*a[15]-a[11]*a[14];
  const d=1/(b00*b11-b01*b10+b02*b09+b03*b08-b04*b07+b05*b06);
  o[0]=(a[5]*b11-a[6]*b10+a[7]*b09)*d;o[1]=(a[2]*b10-a[1]*b11-a[3]*b09)*d;o[2]=(a[13]*b05-a[14]*b04+a[15]*b03)*d;o[3]=(a[10]*b04-a[9]*b05-a[11]*b03)*d;
  o[4]=(a[6]*b08-a[4]*b11-a[7]*b07)*d;o[5]=(a[0]*b11-a[2]*b08+a[3]*b07)*d;o[6]=(a[14]*b02-a[12]*b05-a[15]*b01)*d;o[7]=(a[8]*b05-a[10]*b02+a[11]*b01)*d;
  o[8]=(a[4]*b10-a[5]*b08+a[7]*b06)*d;o[9]=(a[1]*b08-a[0]*b10-a[3]*b06)*d;o[10]=(a[12]*b04-a[13]*b02+a[15]*b00)*d;o[11]=(a[9]*b02-a[8]*b04-a[11]*b00)*d;
  o[12]=(a[5]*b07-a[4]*b09-a[6]*b06)*d;o[13]=(a[0]*b09-a[1]*b07+a[2]*b06)*d;o[14]=(a[13]*b01-a[12]*b03-a[14]*b00)*d;o[15]=(a[8]*b03-a[9]*b01+a[10]*b00)*d;return o}};
const sub=(a,b)=>[a[0]-b[0],a[1]-b[1],a[2]-b[2]],add=(a,b)=>[a[0]+b[0],a[1]+b[1],a[2]+b[2]],mulv=(a,s)=>[a[0]*s,a[1]*s,a[2]*s],dot=(a,b)=>a[0]*b[0]+a[1]*b[1]+a[2]*b[2];
const cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]],norm=a=>{const l=Math.hypot(...a)||1;return [a[0]/l,a[1]/l,a[2]/l]};
/** Ray/segment against an axis-aligned box: entry distance t (0..len) or null. */
function rayBox(o,d,b,len){let t0=0,t1=len;for(let i=0;i<3;i++){if(Math.abs(d[i])<1e-9){if(o[i]<b.min[i]||o[i]>b.max[i])return null;continue}
 let a=(b.min[i]-o[i])/d[i],c=(b.max[i]-o[i])/d[i];if(a>c)[a,c]=[c,a];t0=Math.max(t0,a);t1=Math.min(t1,c);if(t0>t1)return null}return t0}
/** Where a ball travelling (dx,dz) that would pass through (x,z) first crosses the hull box outline: the game decides the hit there. */
function entryPoint(M,x,z,dx,dz){x=Math.max(M.cx-M.hl,Math.min(M.cx+M.hl,x));z=Math.max(M.cz-M.hw,Math.min(M.cz+M.hw,z));
 const tx=dx>0?(x-(M.cx-M.hl))/dx:dx<0?(x-(M.cx+M.hl))/dx:1e9,tz=dz>0?(z-(M.cz-M.hw))/dz:dz<0?(z-(M.cz+M.hw))/dz:1e9;const t=Math.max(0,Math.min(tx,tz));return [x-dx*t,z-dz*t]}
const b64=(s,T)=>{const bin=atob(s),u=new Uint8Array(bin.length);for(let i=0;i<bin.length;i++)u[i]=bin.charCodeAt(i);return new T(u.buffer)};

const VS=`attribute vec3 p;attribute vec3 n;attribute vec2 uv;attribute vec3 col;uniform mat4 vp;uniform mat4 mdl;varying vec3 vn;varying vec2 vuv;varying vec3 vc;varying float vy;
void main(){vec4 w=mdl*vec4(p,1.0);vn=mat3(mdl)*n;vuv=uv;vc=col;vy=w.y;gl_Position=vp*w;}`;
const FS=`precision mediump float;varying vec3 vn;varying vec2 vuv;varying vec3 vc;varying float vy;uniform sampler2D tex;uniform sampler2D d1;uniform sampler2D d2;uniform sampler2D d3;
uniform float useTex,useCol,cut,alpha;uniform vec3 useDec;uniform vec3 base;uniform vec3 L;
void main(){vec4 c=useTex>0.5?texture2D(tex,vuv):vec4(base,1.0);if(c.a<cut)discard;
 if(useDec.x>0.5){vec4 d=texture2D(d1,vuv);c.rgb=mix(c.rgb,d.rgb,d.a);}
 if(useDec.y>0.5){vec4 d=texture2D(d2,vuv);c.rgb=mix(c.rgb,d.rgb,d.a);}
 if(useDec.z>0.5){vec4 d=texture2D(d3,vuv);c.rgb=mix(c.rgb,d.rgb,d.a);}
 if(useCol>0.5)c.rgb=mix(c.rgb*0.25,vc,0.88);
 float lam=0.5+0.6*abs(dot(normalize(vn),L));gl_FragColor=vec4(c.rgb*lam,c.a*alpha);}`;
const LVS=`attribute vec3 p;uniform mat4 vp;void main(){gl_Position=vp*vec4(p,1.0);}`,LFS=`precision mediump float;uniform vec4 col;void main(){gl_FragColor=col;}`;

function mount(el,opts){
 const V=window.SHIP_VIEW,D=window.HIT_DATA,HA=window.HitAnalysis;
 if(!V||!D||!HA){el.innerHTML='<p class="note">The 3D viewer needs this build\'s ship data.</p>';return}
 const ships=V.ships.filter(s=>s.model);if(!ships.length){el.innerHTML='<p class="note">No ship models in this build. Run Full Recovery and rebuild the wiki with models.</p>';return}
 const start=ships.find(s=>s.n===opts.ship)||ships.find(s=>s.n==='Bellona')||ships[0];
 const guns=D.cannons.filter(c=>!c.mortar&&(!c.mount||c.mount==='broadside')),shots=D.ammo.filter(a=>!/mortar|keg|rocket|firework|smoke|snow|phosphor|percussion/i.test(a.n));
 const opt=(l,c,f=x=>x.n)=>l.map(x=>`<option value="${esc(f(x))}"${f(x)===c?' selected':''}>${esc(x.n)}</option>`).join('');
 const des=V.designs||{skins:[],sails:[],decals:[],flags:[],figures:[]};
 el.innerHTML=`<div class="sv"><div class="sv-stage"><canvas class="sv-gl"></canvas><div class="sv-hud"></div><div class="sv-load">Loading model…</div></div>
 <div class="sv-side">
  <label>Ship <select data-k="ship">${opt(ships,start.n)}</select></label>
  <fieldset><legend>Show</legend><label><input type="checkbox" data-k="mdl" checked> Model</label><label><input type="checkbox" data-k="hull" checked> Hull hitbox</label>
   <label><input type="checkbox" data-k="masts"> Mast hitboxes</label><label><input type="checkbox" data-k="sailb"> Sail hitboxes</label><label><input type="checkbox" data-k="water" checked> Waterline</label></fieldset>
  <fieldset><legend>Hull colouring</legend><select data-k="paint"><option value="none">Textures</option><option value="dir" selected>Damage from the chosen direction</option><option value="avg">Average over every direction</option>
   <option value="angle">Impact angle from the chosen direction</option><option value="zone">Bow / side / stern zones</option></select>
   <label>Firing from <input type="range" min="0" max="360" step="2" value="90" data-k="bearing"> <b class="sv-b">90°</b></label>
   <div class="sv-legend"><span>no damage</span><i></i><span class="sv-max"></span></div></fieldset>
  <fieldset><legend>Gun</legend><label>Gun <select data-k="gun">${opt(guns,(guns.find(c=>c.n==='32-pdr Cannon')||guns[0]||{}).n)}</select></label>
   <label>Ammo <select data-k="ammo">${opt(shots,(shots.find(a=>/cast-iron/i.test(a.n))||shots[0]||{}).n)}</select></label>
   <label>Aim height <input type="range" min="-3" max="30" step="0.5" value="4" data-k="aimy"></label>
   <button type="button" class="sv-fire">Fire from the chosen direction</button><p class="ha-note">Or click on the ship to aim at that spot.</p></fieldset>
  <fieldset><legend>Designs</legend>
   <label>Skin <select data-k="skin"><option value="">Default</option></select></label>
   <label>Sail cloth (all sails) <select data-k="sail"><option value="">Default</option>${opt(des.sails,'',x=>x.prefix)}</select></label>
   ${PATS.map((P,k)=>`<div class="sv-pat"><label>${P.label} <select data-pat="${k}"><option value="">None</option>${opt(des.decals.filter(d=>d.slot===P.list),'',x=>x.tex)}</select></label>
    <button type="button" data-edit="${k}">Choose sails</button></div>`).join('')}
   <div class="sv-sails" hidden></div>
   <label>Flag <select data-k="flag"><option value="">Default</option>${opt(des.flags,'',x=>x.tex)}</select></label>
   <label class="sv-flag2">Second flag <select data-k="flag2"><option value="">Default</option>${opt(des.flags,'',x=>x.tex)}</select></label>
   <label>Figurehead <select data-k="fig"><option value="">Default</option>${opt(des.figures,'',x=>x.mesh)}</select></label>
   <p class="ha-note sv-dnote"></p></fieldset>
  <div class="sv-shots"></div></div></div>`;
 const cv=el.querySelector('.sv-gl'),gl=cv.getContext('webgl',{antialias:true,premultipliedAlpha:false});
 if(!gl){el.querySelector('.sv-load').textContent='WebGL is not available in this browser.';return}
 gl.getExtension('OES_element_index_uint');
 const prog=(vs,fs)=>{const p=gl.createProgram();for(const [t,s] of [[gl.VERTEX_SHADER,vs],[gl.FRAGMENT_SHADER,fs]]){const sh=gl.createShader(t);gl.shaderSource(sh,s);gl.compileShader(sh);gl.attachShader(p,sh)}gl.linkProgram(p);return p};
 const P=prog(VS,FS),LP=prog(LVS,LFS);const U=n=>gl.getUniformLocation(P,n),A=n=>gl.getAttribLocation(P,n);
 const st={ship:start.n,mdl:true,hull:true,masts:false,sailb:false,water:true,paint:'dir',bearing:90,gun:el.querySelector('[data-k=gun]').value,ammo:el.querySelector('[data-k=ammo]').value,aimy:4,skin:'',sail:'',flag:'',flag2:'',fig:'',pats:PATS.map(()=>({tex:'',on:new Set()})),edit:-1};
 const models={},textures={},pending={};let yaw=-0.9,pitch=0.32,dist=0,target=[0,8,0],shotsLog=[],ball=null,marks=[];
 const base=V.pack||'../pack/';
 window.WOSB_PACK=ix=>{V._ix=ix;loadShip()};
 window.WOSB_MODEL=(n,m)=>{models[n]=upload(m);(pending[n]||[]).forEach(f=>f());delete pending[n];draw()};
 window.WOSB_TEX=(n,uri)=>{const im=new Image();im.onload=()=>{const t=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D,t);gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL,false);
  gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,im);const pot=(im.width&(im.width-1))===0&&(im.height&(im.height-1))===0;
  gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,pot?gl.LINEAR_MIPMAP_LINEAR:gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);
  const wrap=pot?gl.REPEAT:gl.CLAMP_TO_EDGE;gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,wrap);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,wrap);if(pot)gl.generateMipmap(gl.TEXTURE_2D);
  textures[n]=t;draw()};im.src=uri};
 const script=src=>{const s=document.createElement('script');s.src=src;s.onerror=()=>{el.querySelector('.sv-load').textContent='The model pack is not published with this build.'};document.head.appendChild(s)};
 const loadedTex=new Set();function tex(name){if(!name)return null;const k=name.toLowerCase();if(textures[k])return textures[k];
  const e=V._ix&&V._ix.textures[k];if(e&&e.file&&!loadedTex.has(k)){loadedTex.add(k);script(base+e.file)}return null}
 function needModel(n,f){if(models[n])return f&&f();(pending[n]=pending[n]||[]).push(f||(()=>{}));if(pending[n].length===1){const e=V._ix&&V._ix.models[n];if(e&&e.file)script(base+e.file);else el.querySelector('.sv-load').textContent='This ship isn\'t in the model pack.'}}
 function upload(m){const groups=m.groups.map(g=>{const q=b64(g.p,Int16Array),nr=b64(g.nr,Int8Array),cnt=q.length/3;const pos=new Float32Array(q.length);
   for(let i=0;i<q.length;i++)pos[i]=(q[i]+32767)*m.scale[i%3]+m.min[i%3];const nor=new Float32Array(nr.length);for(let i=0;i<nr.length;i++)nor[i]=nr[i]/127;
   let uv;if(g.uq){const u=b64(g.uq,Int16Array);uv=new Float32Array(u.length);for(let i=0;i<u.length;i++)uv[i]=(u[i]+32767)*g.usc[i%2]+g.umin[i%2]}else uv=new Float32Array(cnt*2);
   const idx=b64(g.i,g.i32?Uint32Array:Uint16Array);const mk=(data,tgt=gl.ARRAY_BUFFER)=>{const b=gl.createBuffer();gl.bindBuffer(tgt,b);gl.bufferData(tgt,data,gl.STATIC_DRAW);return b};
   return {mesh:g.mesh,mat:g.mat,kind:g.kind,tex:g.tex,pos,nor,n:idx.length,i32:!!g.i32,bp:mk(pos),bn:mk(nor),bu:mk(uv),bc:mk(new Float32Array(cnt*3)),bi:mk(idx,gl.ELEMENT_ARRAY_BUFFER),col:new Float32Array(cnt*3)}});
  return {groups,bounds:m.bounds}}
 const ship=()=>ships.find(s=>s.n===st.ship);
 const hullBox=()=>{const z=(ship().zones||[]).find(z=>z.t==='hull');return z?z.b:null};
 function loadShip(){const s=ship();el.querySelector('.sv-load').hidden=false;el.querySelector('.sv-load').textContent='Loading model…';
  const sk=el.querySelector('[data-k=skin]');sk.innerHTML='<option value="">Default</option>';
  needModel(s.model,()=>{el.querySelector('.sv-load').hidden=true;const m=models[s.model];const mats=new Set(m.groups.map(g=>g.mat.toLowerCase()));
   const fits=des.skins.filter(d=>Object.keys(d.table).some(k=>mats.has(k.toLowerCase())));sk.innerHTML='<option value="">Default</option>'+fits.map(d=>`<option value="${esc(d.id)}">${esc(d.n)}</option>`).join('');
   const sm=s.sailmap||{};const all=Object.values(sm).map(v=>v[0]),anim=Object.values(sm).filter(v=>v[1]).map(v=>v[0]);
   st.pats.forEach((P,k)=>{P.on=new Set(PATS[k].def==='all'?all:anim)});st.flagMeshes=[...new Set(m.groups.filter(g=>g.kind==='flag').map(g=>flagKey(g.mesh)))].sort();
   el.querySelector('.sv-flag2').style.display=st.flagMeshes.length>1?'':'none';renderSails();
   const b=m.bounds;target=[(b[0][0]+b[1][0])/2,(b[0][1]+b[1][1])*0.35,(b[0][2]+b[1][2])/2];dist=Math.max(b[1][0]-b[0][0],b[1][1]-b[0][1])*1.35;yaw=st.bearing*Math.PI/180+0.55;pitch=0.28;marks=[];shotsLog=[];repaint();renderShots()});
  if(st.fig)needModel('BowFigures')}
 // ---------------------------------------------------------------- hull colouring
 function params(){return HA.params(D,{ship:st.ship,cannon:st.gun,ammo:st.ammo,armorBonus:0,penBonus:0})}
 function repaint(){const s=ship(),m=models[s.model],box=hullBox();if(!m)return;const max={v:1};
  if(!box||st.paint==='none'){for(const g of m.groups)g.useCol=false;draw();return}
  const M=HA.model(box),p=params(),b=st.bearing*Math.PI/180,dx=-Math.cos(b),dz=-Math.sin(b);const avgB=[];for(let k=0;k<360;k+=12)avgB.push([-Math.cos(k*Math.PI/180),-Math.sin(k*Math.PI/180)]);
  let top=1;if(st.paint==='dir'||st.paint==='avg'){for(let k=0;k<360;k+=4)top=Math.max(top,HA.fromBearing(M,k,p).dmg)}
  for(const g of m.groups){g.useCol=g.kind==='hull'||g.kind==='other';if(!g.useCol)continue;const pos=g.pos,nor=g.nor,col=g.col;
   for(let i=0;i<pos.length;i+=3){const x=pos[i],y=pos[i+1],z=pos[i+2];let c=[0.35,0.35,0.38];
    const inside=x>=box.min[0]-0.3&&x<=box.max[0]+0.3&&y>=box.min[1]-0.3&&y<=box.max[1]+0.3&&Math.abs(z-M.cz)<=M.hw+0.6;
    if(inside){if(st.paint==='zone'){const [ex,ez]=entryPoint(M,x,z,dx,dz);c=ZC[M.zone(M.idx(ex,ez))]}
     else if(st.paint==='avg'){let s2=0,n2=0;for(const [ax,az] of avgB){if(ax*(x-M.cx)/M.hl+az*(z-M.cz)/M.hw>0.15)continue;const [ex,ez]=entryPoint(M,x,z,ax,az);s2+=HA.damageAt(M,ex,ez,ax,az,p).dmg;n2++}c=n2?heat(s2/n2/top):c}
     else{const facing=dx*(x-M.cx)/M.hl+dz*(z-M.cz)/M.hw<0.15;if(facing){const [ex,ez]=entryPoint(M,x,z,dx,dz);const r=HA.damageAt(M,ex,ez,dx,dz,p);c=st.paint==='angle'?heat(1-Math.min(90,r.ang)/90):r.dmg<=0.05?[0.16,0.18,0.3]:heat(r.dmg/top)}}}
    col[3*(i/3)]=c[0];col[3*(i/3)+1]=c[1];col[3*(i/3)+2]=c[2]}
   gl.bindBuffer(gl.ARRAY_BUFFER,g.bc);gl.bufferData(gl.ARRAY_BUFFER,col,gl.DYNAMIC_DRAW)}
  el.querySelector('.sv-max').textContent=st.paint==='angle'?'square on':st.paint==='zone'?'':`${top.toFixed(1)} per ball`;
  el.querySelector('.sv-legend').style.display=st.paint==='zone'?'none':'';draw()}
 // ---------------------------------------------------------------- designs
 function groupTex(g){const lo=g.mat.toLowerCase();
  if(st.skin){const d=des.skins.find(x=>x.id===st.skin);const t=d&&Object.entries(d.table).find(([k])=>k.toLowerCase()===lo);if(t){const tt=tex(t[1]);if(tt)return tt}}
  if(st.sail&&g.kind==='sail'&&lo.startsWith('sail')){const part=lo.includes('_')?lo.slice(lo.indexOf('_')+1):'main';const tt=tex(st.sail+part)||tex(st.sail+'main');if(tt)return tt}
  if(g.kind==='flag'){const fi=(st.flagMeshes||[]).indexOf(flagKey(g.mesh));const want=fi>0?st.flag2:st.flag;if(want){const tt=tex(want);if(tt)return tt}}
  return g.tex?tex(g.tex):null}
 // ---------------------------------------------------------------- drawing
 const water=(()=>{const b=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,b);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-400,0,-400,400,0,-400,400,0,400,-400,0,-400,400,0,400,-400,0,400]),gl.STATIC_DRAW);return b})();
 const lineBuf=gl.createBuffer();
 function viewProj(){const w=cv.clientWidth,h=cv.clientHeight;const eye=[target[0]+Math.cos(pitch)*Math.cos(yaw)*dist,target[1]+Math.sin(pitch)*dist,target[2]+Math.cos(pitch)*Math.sin(yaw)*dist];
  return {vp:M4.mul(M4.persp(0.8,w/h,0.5,dist*8+500),M4.look(eye,target,[0,1,0])),eye}}
 function boxLines(b){const v=[];for(const x of [b.min[0],b.max[0]])for(const y of [b.min[1],b.max[1]])for(const z of [b.min[2],b.max[2]])v.push([x,y,z]);
  const E=[[0,1],[2,3],[4,5],[6,7],[0,2],[1,3],[4,6],[5,7],[0,4],[1,5],[2,6],[3,7]];return E.flatMap(([a,c])=>[...v[a],...v[c]])}
 function lines(vp,arr,col){if(!arr.length)return;gl.useProgram(LP);gl.bindBuffer(gl.ARRAY_BUFFER,lineBuf);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(arr),gl.DYNAMIC_DRAW);
  const a=gl.getAttribLocation(LP,'p');gl.enableVertexAttribArray(a);gl.vertexAttribPointer(a,3,gl.FLOAT,false,0,0);gl.uniformMatrix4fv(gl.getUniformLocation(LP,'vp'),false,vp);
  gl.uniform4fv(gl.getUniformLocation(LP,'col'),col);gl.drawArrays(gl.LINES,0,arr.length/3);gl.disableVertexAttribArray(a)}
 function drawGroups(m,mdl,vp,filter,forceTex){gl.useProgram(P);gl.uniformMatrix4fv(U('vp'),false,vp);gl.uniformMatrix4fv(U('mdl'),false,mdl);gl.uniform3fv(U('L'),norm([0.4,0.9,0.3]));gl.uniform1f(U('alpha'),1);
  for(const g of m.groups){if(filter&&!filter(g))continue;const t=forceTex||groupTex(g);
   const loc={p:A('p'),n:A('n'),uv:A('uv'),col:A('col')};for(const [k,b,sz] of [['p',g.bp,3],['n',g.bn,3],['uv',g.bu,2],['col',g.bc,3]]){if(loc[k]<0)continue;gl.bindBuffer(gl.ARRAY_BUFFER,b);gl.enableVertexAttribArray(loc[k]);gl.vertexAttribPointer(loc[k],sz,gl.FLOAT,false,0,0)}
   gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,t);gl.uniform1i(U('tex'),0);gl.uniform1f(U('useTex'),t?1:0);
   const si=g.kind==='sail'?(ship().sailmap||{})[g.mesh]:null;const on=[0,0,0];
   st.pats.forEach((P,k)=>{const dt=si&&P.tex&&P.on.has(si[0])?tex(P.tex):null;gl.activeTexture(gl.TEXTURE1+k);gl.bindTexture(gl.TEXTURE_2D,dt);gl.uniform1i(U('d'+(k+1)),1+k);on[k]=dt?1:0});gl.uniform3fv(U('useDec'),on);
   gl.uniform1f(U('useCol'),g.useCol&&st.paint!=='none'?1:0);gl.uniform1f(U('cut'),g.kind==='sail'||g.kind==='flag'||g.kind==='mast'?0.4:0.05);
   gl.uniform3fv(U('base'),g.kind==='sail'?[0.92,0.9,0.84]:g.kind==='mast'?[0.42,0.3,0.2]:[0.55,0.45,0.35]);
   gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,g.bi);gl.drawElements(gl.TRIANGLES,g.n,g.i32?gl.UNSIGNED_INT:gl.UNSIGNED_SHORT,0);
   for(const k in loc)if(loc[k]>=0)gl.disableVertexAttribArray(loc[k])}}
 let raf=0;function draw(){if(!raf)raf=requestAnimationFrame(frame)}
 function frame(t){raf=0;const w=cv.clientWidth,h=cv.clientHeight;if(cv.width!==w*devicePixelRatio){cv.width=w*devicePixelRatio;cv.height=h*devicePixelRatio}
  gl.viewport(0,0,cv.width,cv.height);gl.clearColor(0.78,0.86,0.92,1);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);gl.enable(gl.DEPTH_TEST);gl.disable(gl.CULL_FACE);
  const s=ship(),m=models[s.model];const {vp}=viewProj();const I=M4.trs([0,0,0],1);
  if(m&&st.mdl){drawGroups(m,I,vp,st.fig?g=>!/bowfigure|figure/i.test(g.mesh):null);
   if(st.fig&&models.BowFigures&&s.fig){const sc=0.15+0.6*(s.half||8)/(V.refHalf||8);drawGroups(models.BowFigures,M4.trs(s.fig,sc),vp,g=>g.mesh.toLowerCase().startsWith(st.fig.toLowerCase()+'_')||g.mesh.toLowerCase()===st.fig.toLowerCase())}}
  gl.enable(gl.BLEND);gl.blendFunc(gl.SRC_ALPHA,gl.ONE_MINUS_SRC_ALPHA);
  if(st.water){gl.useProgram(LP);gl.bindBuffer(gl.ARRAY_BUFFER,water);const a=gl.getAttribLocation(LP,'p');gl.enableVertexAttribArray(a);gl.vertexAttribPointer(a,3,gl.FLOAT,false,0,0);
   gl.uniformMatrix4fv(gl.getUniformLocation(LP,'vp'),false,vp);gl.uniform4fv(gl.getUniformLocation(LP,'col'),[0.16,0.42,0.6,0.45]);gl.depthMask(false);gl.drawArrays(gl.TRIANGLES,0,6);gl.depthMask(true);gl.disableVertexAttribArray(a)}
  gl.disable(gl.DEPTH_TEST);const zs=s.zones||[];
  if(st.hull)lines(vp,zs.filter(z=>z.t==='hull').flatMap(z=>boxLines(z.b)),[0.12,0.45,0.85,1]);
  if(st.masts)lines(vp,zs.filter(z=>z.t==='mast').flatMap(z=>boxLines(z.b)),[0.55,0.32,0.1,1]);
  if(st.edit>=0){const P=st.pats[st.edit];lines(vp,zs.filter(z=>z.t==='sail'&&P.on.has(z.n-1)).flatMap(z=>boxLines(z.b)),[0.1,0.75,0.3,1]);lines(vp,zs.filter(z=>z.t==='sail'&&!P.on.has(z.n-1)).flatMap(z=>boxLines(z.b)),[0.5,0.5,0.55,0.7])}
  else if(st.sailb)lines(vp,zs.filter(z=>z.t==='sail').flatMap(z=>boxLines(z.b)),[0.95,0.5,0.1,0.85]);
  for(const k of marks)lines(vp,cross3(k.p,1.2),k.col);
  if(ball){const now=performance.now(),f=Math.min(1,(now-ball.t0)/ball.ms),p=add(ball.o,mulv(ball.d,ball.len*f));lines(vp,[...ball.o,...p],[0.15,0.15,0.18,0.6]);lines(vp,cross3(p,0.9),[0.05,0.05,0.05,1]);
   if(f<1)draw();else{const done=ball;ball=null;done.end()}}
  gl.enable(gl.DEPTH_TEST);gl.disable(gl.BLEND);
  el.querySelector('.sv-hud').innerHTML=`<b>${esc(s.n)}</b> · HP ${Math.round(s.hp||0).toLocaleString()} · armor ${(s.armor??0).toFixed(1)}${hullBox()?'':' · no rebuilt hitbox for this ship'}`}
 const cross3=(p,r)=>[p[0]-r,p[1],p[2],p[0]+r,p[1],p[2],p[0],p[1]-r,p[2],p[0],p[1]+r,p[2],p[0],p[1],p[2]-r,p[0],p[1],p[2]+r];
 // ---------------------------------------------------------------- firing
 function fireAt(aim){const box=hullBox();if(!box)return;const b=st.bearing*Math.PI/180,dir=norm([-Math.cos(b),0,-Math.sin(b)]);const len=140;
  const o=sub(aim,mulv(dir,len*0.8));const s=ship(),zs=s.zones||[],M=HA.model(box),p=params();
  const hull=rayBox(o,dir,box,len);const sails=zs.filter(z=>z.t==='sail').map(z=>({z,t:rayBox(o,dir,z.b,len)})).filter(x=>x.t!=null).sort((a,c)=>a.t-c.t);
  const masts=zs.filter(z=>z.t==='mast').map(z=>({z,t:rayBox(o,dir,z.b,len)})).filter(x=>x.t!=null);
  const hitT=hull!=null?hull:len;const res={bearing:st.bearing,gun:st.gun,ammo:st.ammo};
  if(hull!=null){const e=add(o,mulv(dir,hull));const r=HA.damageAt(M,e[0],e[2],dir[0],dir[2],p);Object.assign(res,{zone:r.zone,ang:r.ang,dmg:r.dmg,p:e})}
  res.sails=sails.filter(x=>x.t<hitT).length;res.masts=masts.filter(x=>x.t<hitT).length;
  ball={o,d:dir,len:hitT,t0:performance.now(),ms:500+hitT*4,end(){if(res.p)marks.push({p:res.p,col:res.dmg>0.05?[0.85,0.15,0.1,1]:[0.2,0.3,0.8,1]});shotsLog.unshift(res);renderShots();draw()}};draw()}
 function renderSails(){const box=el.querySelector('.sv-sails');if(st.edit<0){box.hidden=true;return}box.hidden=false;const P=st.pats[st.edit],sm=ship().sailmap||{};
  const rows=Object.entries(sm).map(([mesh,[i,an]])=>({mesh,i,an})).sort((x,y)=>x.i-y.i);
  box.innerHTML=`<b>${PATS[st.edit].label}: which sails</b><p class="ha-note">Click sails in the view, or tick them here. Green boxes carry it.</p>
   <div class="sv-sbtn"><button type="button" data-all="all">All</button><button type="button" data-all="anim">Square sails</button><button type="button" data-all="none">None</button><button type="button" data-done>Done</button></div>`+
   rows.map(r=>`<label><input type="checkbox" data-sail="${r.i}"${P.on.has(r.i)?' checked':''}> Sail ${r.i+1} · ${r.an?'square':'fore-and-aft'} <small>${esc(r.mesh)}</small></label>`).join('');
  box.querySelectorAll('[data-sail]').forEach(c=>c.onchange=()=>{const i=+c.dataset.sail;c.checked?P.on.add(i):P.on.delete(i);draw()});
  box.querySelectorAll('[data-all]').forEach(b=>b.onclick=()=>{P.on=new Set(b.dataset.all==='none'?[]:rows.filter(r=>b.dataset.all==='all'||r.an).map(r=>r.i));renderSails();draw()});
  box.querySelector('[data-done]').onclick=()=>{st.edit=-1;renderSails();draw()}}
 el.querySelectorAll('[data-pat]').forEach(sel=>sel.addEventListener('change',()=>{st.pats[+sel.dataset.pat].tex=sel.value;draw()}));
 el.querySelectorAll('[data-edit]').forEach(b=>b.onclick=()=>{const k=+b.dataset.edit;st.edit=st.edit===k?-1:k;renderSails();draw()});
 function renderShots(){const box=el.querySelector('.sv-shots');if(!shotsLog.length){box.innerHTML='<p class="ha-note">Shots you fire appear here.</p>';return}
  box.innerHTML='<h4>Shots</h4>'+shotsLog.slice(0,8).map(r=>`<div class="sv-shot">${r.p?`<b style="color:rgb(${ZC[r.zone].map(v=>v*255|0)})">${r.zone}</b> at ${r.ang.toFixed(0)}° off square → <b>${r.dmg.toFixed(1)}</b>${r.dmg<=0.05?' (glanced off)':''}`:'<b>Missed the hull</b>'}
   <small>from ${r.bearing}° · ${esc(r.gun)} · ${esc(r.ammo)}${r.masts?` · hit ${r.masts} mast${r.masts>1?'s':''}`:''}${r.sails?` · through ${r.sails} sail box${r.sails>1?'es':''} (up to 3 count)`:''}</small></div>`).join('')+
   '<button type="button" class="sv-clear">Clear marks</button>';box.querySelector('.sv-clear').onclick=()=>{marks=[];shotsLog=[];renderShots();draw()}}
 // ---------------------------------------------------------------- input
 let drag=null;cv.addEventListener('pointerdown',e=>{drag={x:e.clientX,y:e.clientY,yaw,pitch,moved:false,pan:e.button===2||e.shiftKey,t:[...target]};cv.setPointerCapture(e.pointerId)});
 cv.addEventListener('pointermove',e=>{if(!drag)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;if(Math.abs(dx)+Math.abs(dy)>4)drag.moved=true;
  if(drag.pan){const s=dist/cv.clientHeight;target=[drag.t[0]+Math.sin(yaw)*dx*s,drag.t[1]+dy*s,drag.t[2]-Math.cos(yaw)*dx*s]}else{yaw=drag.yaw+dx*0.008;pitch=Math.max(-0.2,Math.min(1.45,drag.pitch+dy*0.006))}draw()});
 cv.addEventListener('pointerup',e=>{const d=drag;drag=null;if(d&&!d.moved&&!d.pan)aimClick(e)});cv.addEventListener('contextmenu',e=>e.preventDefault());
 cv.addEventListener('wheel',e=>{e.preventDefault();dist=Math.max(8,Math.min(400,dist*(e.deltaY>0?1.12:0.89)));draw()},{passive:false});
 function aimClick(e){const box=hullBox();if(!box)return;const r=cv.getBoundingClientRect(),x=(e.clientX-r.left)/r.width*2-1,y=1-(e.clientY-r.top)/r.height*2;const {vp,eye}=viewProj();const inv=M4.inv(vp);
  const un=(z)=>{const v=[x,y,z,1],o=[0,0,0,0];for(let i=0;i<4;i++)o[i]=inv[i]*v[0]+inv[4+i]*v[1]+inv[8+i]*v[2]+inv[12+i]*v[3];return [o[0]/o[3],o[1]/o[3],o[2]/o[3]]};
  const a=un(-1),b2=un(1),d=norm(sub(b2,a));
  if(st.edit>=0){let best=null;for(const z of (ship().zones||[]).filter(z=>z.t==='sail')){const t=rayBox(a,d,z.b,1e4);if(t!=null&&(!best||t<best.t))best={t,i:z.n-1}}
   if(best){const P=st.pats[st.edit];P.on.has(best.i)?P.on.delete(best.i):P.on.add(best.i);renderSails();draw()}return}
  const t=rayBox(a,d,box,1e4);if(t==null)return;const pt=add(a,mulv(d,t));
  // shoot from the side of the ship the camera is on
  st.bearing=Math.round(((Math.atan2(-d[2],-d[0])*180/Math.PI)+360)%360/2)*2%360;el.querySelector('[data-k=bearing]').value=st.bearing;el.querySelector('.sv-b').textContent=st.bearing+'°';
  repaint();fireAt(pt)}
 el.querySelector('.sv-fire').onclick=()=>{const box=hullBox();if(!box)return;const c=[(box.min[0]+box.max[0])/2,+st.aimy,(box.min[2]+box.max[2])/2];fireAt(c)};
 el.querySelectorAll('[data-k]').forEach(i=>i.addEventListener(i.type==='checkbox'?'change':i.type==='range'?'input':'change',()=>{const k=i.dataset.k;st[k]=i.type==='checkbox'?i.checked:i.type==='range'?+i.value:i.value;
  if(k==='bearing')el.querySelector('.sv-b').textContent=st.bearing+'°';if(k==='ship')loadShip();if(['bearing','paint','gun','ammo','ship'].includes(k))repaint();if(k==='fig'&&st.fig)needModel('BowFigures');
  const dn=[];if(st.pats.some(P=>P.tex))dn.push('Patterns are laid over each sail with the sail\'s own UVs, so their placement is approximate.');if(st.fig&&!ship().fig)dn.push('This ship has no figurehead mount in its hitbox data.');
  el.querySelector('.sv-dnote').textContent=dn.join(' ');draw()}));
 new ResizeObserver(draw).observe(cv);script(base+'index.js');renderShots();
 const api={view(o){if(o.yaw!=null)yaw=o.yaw;if(o.pitch!=null)pitch=o.pitch;if(o.dist)dist=o.dist;if(o.target)target=o.target;draw()},state:st};el.shipViewer=api;return api}
window.ShipViewer={mount,rayBox};
})();
