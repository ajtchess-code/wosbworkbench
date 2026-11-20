/* WoSB Wiki item viewer: one mesh (a cannon, mortar or figurehead) from the wiki's model pack, with its texture.
   Usage: <div class="iv" data-model="weapons" data-mesh="Cannon_rust_small" data-pack="../pack/"></div> + ItemViewer.mountAll().
   Loads nothing until the reader presses "Show 3D model", so pages stay light. */
(function(){
'use strict';
const VS='attribute vec3 p;attribute vec3 n;attribute vec2 uv;uniform mat4 vp;varying vec3 vn;varying vec2 vuv;varying vec3 wp;void main(){vn=n;vuv=uv;wp=p;gl_Position=vp*vec4(p,1.0);}';
// ground (terrain) is blended from sand, grass and rock by height and slope, like the game's terrain shader
const FS='precision mediump float;varying vec3 vn;varying vec2 vuv;varying vec3 wp;uniform sampler2D tex,t1,t2;uniform float useTex,terr,sandH;uniform vec3 L,base;void main(){vec3 n=normalize(vn);vec4 c;'+
 'if(terr>0.5){vec2 w=wp.xz*0.16;vec4 sa=texture2D(tex,w),gr=texture2D(t1,w)*2.3,ro=texture2D(t2,w*0.6)*1.5;c=mix(mix(sa,gr,smoothstep(sandH,sandH+1.6,wp.y)),ro,smoothstep(0.82,0.55,n.y));c.a=1.0;}'+
 'else c=useTex>0.5?texture2D(tex,vuv):vec4(base,1.0);'+
 'if(c.a<0.3)discard;float k=max(dot(n,L),0.0),f=max(dot(n,normalize(vec3(-0.6,0.3,-0.5))),0.0),h=0.5+0.5*n.y;'+
 'gl_FragColor=vec4(c.rgb*(0.30+0.18*h+0.62*k+0.22*f),1.0);}';
const b64=(s,T)=>{const bin=atob(s),u=new Uint8Array(bin.length);for(let i=0;i<bin.length;i++)u[i]=bin.charCodeAt(i);return new T(u.buffer)};
const persp=(f,a,n,fa)=>{const t=1/Math.tan(f/2);return [t/a,0,0,0,0,t,0,0,0,0,(fa+n)/(n-fa),-1,0,0,2*fa*n/(n-fa),0]};
const mul=(a,b)=>{const o=new Array(16).fill(0);for(let i=0;i<4;i++)for(let j=0;j<4;j++)for(let k=0;k<4;k++)o[i*4+j]+=a[k*4+j]*b[i*4+k];return o};
function look(e,c){const z=nrm([e[0]-c[0],e[1]-c[1],e[2]-c[2]]),x=nrm([z[2],0,-z[0]]),y=[z[1]*x[2]-z[2]*x[1],z[2]*x[0]-z[0]*x[2],z[0]*x[1]-z[1]*x[0]];
 return [x[0],y[0],z[0],0,x[1],y[1],z[1],0,x[2],y[2],z[2],0,-(x[0]*e[0]+x[1]*e[1]+x[2]*e[2]),-(y[0]*e[0]+y[1]*e[1]+y[2]*e[2]),-(z[0]*e[0]+z[1]*e[1]+z[2]*e[2]),1]}
const nrm=a=>{const l=Math.hypot(a[0],a[1],a[2])||1;return [a[0]/l,a[1]/l,a[2]/l]};
// one shared pack loader for every viewer on the page
const P={ix:null,models:{},tex:{},wait:{},texWait:{},base:'../pack/',started:false};
function script(src,onerr){const s=document.createElement('script');s.src=src;if(onerr)s.onerror=onerr;document.head.appendChild(s)}
window.WOSB_PACK=ix=>{P.ix=ix;(P.wait._ix||[]).forEach(f=>f());delete P.wait._ix};
window.WOSB_MODEL=(n,m)=>{P.models[n]=m;(P.wait[n]||[]).forEach(f=>f());delete P.wait[n]};
window.WOSB_TEX=(n,uri)=>{const im=new Image();im.onload=()=>{P.tex[n]=im;(P.texWait[n]||[]).forEach(f=>f());delete P.texWait[n]};im.src=uri};
function index(cb,fail){if(P.ix)return cb();(P.wait._ix=P.wait._ix||[]).push(cb);if(!P.started){P.started=true;script(P.base+'index.js',fail)}}
function model(n,cb,fail){if(P.models[n])return cb();const [base,item]=n.split('@');const f=item?(P.ix&&P.ix.items&&P.ix.items[base]&&P.ix.items[base][item]):(P.ix&&P.ix.models[n]&&P.ix.models[n].file);
 if(!f)return fail();(P.wait[n]=P.wait[n]||[]).push(cb);if(P.wait[n].length===1)script(P.base+f,fail)}
function itemName(el){const b=el.dataset.model,w=(el.dataset.mesh||'').toLowerCase(),it=P.ix&&P.ix.items&&P.ix.items[b];if(!it)return b;
 if(it[w])return b+'@'+w;const k=Object.keys(it).find(k=>k===w.replace(/_part\d+$/,''))||Object.keys(it).find(k=>k.startsWith(w+'_')&&!/_lod\d*$|_shape$/.test(k))||Object.keys(it).find(k=>k.startsWith(w));return k?b+'@'+k:b}
function texture(name,cb){const k=(name||'').toLowerCase();if(!k)return;if(P.tex[k])return cb(P.tex[k]);const e=P.ix&&P.ix.textures&&P.ix.textures[k];if(!e||!e.file)return;
 (P.texWait[k]=P.texWait[k]||[]).push(()=>cb(P.tex[k]));if(P.texWait[k].length===1)script(P.base+e.file)}

function mount(el){
 if(el._iv)return;el._iv=1;P.base=el.dataset.pack||P.base;
 el.innerHTML='<button type="button" class="iv-go">'+(el.dataset.label||'Show 3D model')+'</button><canvas class="iv-gl" hidden></canvas><small class="iv-msg"></small>';
 const msg=el.querySelector('.iv-msg'),cv=el.querySelector('.iv-gl'),go=el.querySelector('.iv-go');
 const open=()=>{go.remove();msg.textContent='Loading model…';
  const fail=()=>{msg.textContent='The 3D model isn\'t in this build of the wiki.'};
  index(()=>{const n=itemName(el);model(n,()=>start(el,cv,msg,n),fail)},fail)};
 go.addEventListener('click',open);if(el.dataset.auto)open();
}
function start(el,cv,msg,name){
 const m=P.models[name||el.dataset.model],want=(el.dataset.mesh||'').toLowerCase(),isle=!!el.dataset.isle;
 const ms=g=>(g.mesh||'').toLowerCase(),lodish=g=>/_lod\d*(_part\d+)?$|_shape$/.test(ms(g));
 let pick;
 if(isle||(name||'').includes('@')||m.groups.length===1)pick=m.groups.filter(g=>!lodish(g));     // a whole item (all its material parts), or the whole island
 else{pick=m.groups.filter(g=>ms(g)===want||ms(g).replace(/_part\d+$/,'')===want);
  if(!pick.length)pick=m.groups.filter(g=>ms(g).startsWith(want+'_')&&!lodish(g));
  if(!pick.length)pick=m.groups.filter(g=>ms(g).startsWith(want)&&!lodish(g))}
 if(!pick.length){msg.textContent='This item has no separate 3D model.';return}
 cv.hidden=false;msg.textContent='Drag to turn · scroll or pinch to zoom';
 const gl=cv.getContext('webgl',{antialias:true});if(!gl){msg.textContent='Your browser can\'t show 3D models.';return}
 const sh=(t,s)=>{const o=gl.createShader(t);gl.shaderSource(o,s);gl.compileShader(o);return o};
 const pr=gl.createProgram();gl.attachShader(pr,sh(gl.VERTEX_SHADER,VS));gl.attachShader(pr,sh(gl.FRAGMENT_SHADER,FS));gl.linkProgram(pr);gl.useProgram(pr);
 const mk=(d,t)=>{const b=gl.createBuffer();gl.bindBuffer(t||gl.ARRAY_BUFFER,b);gl.bufferData(t||gl.ARRAY_BUFFER,d,gl.STATIC_DRAW);return b};
 let lo=[1e9,1e9,1e9],hi=[-1e9,-1e9,-1e9];const ext=gl.getExtension('OES_element_index_uint');
 function upload(im,clamp){const t=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D,t);
  const p2=v=>Math.min(2048,Math.pow(2,Math.round(Math.log2(Math.max(4,v))))),cw=p2(im.width),ch=p2(im.height);let src=im;
  if(cw!==im.width||ch!==im.height){src=document.createElement('canvas');src.width=cw;src.height=ch;const x=src.getContext('2d');x.imageSmoothingQuality='high';x.drawImage(im,0,0,cw,ch)}
  gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,src);gl.generateMipmap(gl.TEXTURE_2D);
  gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR_MIPMAP_LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);
  const an=gl.getExtension('EXT_texture_filter_anisotropic');if(an)gl.texParameterf(gl.TEXTURE_2D,an.TEXTURE_MAX_ANISOTROPY_EXT,4);
  const w=clamp?gl.CLAMP_TO_EDGE:gl.REPEAT;gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,w);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,w);return t}
 const parts=pick.map(g=>{const q=b64(g.p,Int16Array),pos=new Float32Array(q.length);for(let i=0;i<q.length;i++){const v=(q[i]+32767)*m.scale[i%3]+m.min[i%3];pos[i]=v;const a=i%3;if(v<lo[a])lo[a]=v;if(v>hi[a])hi[a]=v}
  const nr=b64(g.nr,Int8Array),nor=new Float32Array(nr.length);let sy=0;for(let i=1;i<nr.length;i+=3)sy+=nr[i];const fl=g.terrain&&sy<0?-1:1;for(let i=0;i<nr.length;i++)nor[i]=fl*nr[i]/127;   // ground meshes can come with inward normals
  let uv;if(g.uq){const u=b64(g.uq,Int16Array);uv=new Float32Array(u.length);for(let i=0;i<u.length;i++)uv[i]=(u[i]+32767)*g.usc[i%2]+g.umin[i%2]}else uv=new Float32Array(q.length/3*2);
  const idx=b64(g.i,g.i32?Uint32Array:Uint16Array);
  const part={mesh:ms(g).replace(/_part\d+$/,''),bp:mk(pos),bn:mk(nor),bu:mk(uv),bi:mk(idx,gl.ELEMENT_ARRAY_BUFFER),n:idx.length,i32:!!g.i32&&!!ext,t:null,terr:null};
  if(g.terrain&&g.terrain.length){part.terr=[null,null,null];g.terrain.slice(0,3).forEach((tn,j)=>texture(tn,im=>{part.terr[j]=upload(im,false);draw()}))}
  else{const key=g.tex||g.mat;texture(key,im=>{part.t=upload(im,String(key).includes('@'));draw()})}
  return part});
 const c=[(lo[0]+hi[0])/2,(lo[1]+hi[1])/2,(lo[2]+hi[2])/2],r=Math.max(hi[0]-lo[0],hi[1]-lo[1],hi[2]-lo[2])||1;
 let water=null;if(isle){const s=r*3,y=0.05;water={bp:mk(new Float32Array([c[0]-s,y,c[2]-s,c[0]+s,y,c[2]-s,c[0]+s,y,c[2]+s,c[0]-s,y,c[2]+s])),bn:mk(new Float32Array([0,1,0,0,1,0,0,1,0,0,1,0])),
  bu:mk(new Float32Array(8)),bi:mk(new Uint16Array([0,1,2,0,2,3]),gl.ELEMENT_ARRAY_BUFFER),n:6,i32:false,t:null,terr:null,water:true}}
 let yaw=isle?2.2:0.8,pitch=isle?0.6:0.35,dist=r*(isle?0.75:1.6),raf=0;
 const U=n=>gl.getUniformLocation(pr,n),A=n=>gl.getAttribLocation(pr,n);
 function draw(){if(!raf)raf=requestAnimationFrame(frame)}
 el.ivRedraw=draw;
 function frame(){raf=0;const w=cv.clientWidth,h=cv.clientHeight,d=window.devicePixelRatio||1;if(cv.width!==Math.round(w*d)){cv.width=Math.round(w*d);cv.height=Math.round(h*d)}
  gl.viewport(0,0,cv.width,cv.height);gl.clearColor(0.93,0.95,0.97,1);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);gl.enable(gl.DEPTH_TEST);
  const eye=[c[0]+Math.cos(pitch)*Math.cos(yaw)*dist,c[1]+Math.sin(pitch)*dist,c[2]+Math.cos(pitch)*Math.sin(yaw)*dist];
  gl.uniformMatrix4fv(U('vp'),false,new Float32Array(mul(persp(0.7,w/h,r*0.01,r*20),look(eye,c))));gl.uniform3fv(U('L'),nrm([0.5,0.8,0.6]));
  gl.uniform1i(U('tex'),0);gl.uniform1i(U('t1'),1);gl.uniform1i(U('t2'),2);gl.uniform1f(U('sandH'),isle?0.6:-1e4);
  const filt=el.ivFilter;
  for(const p of water?parts.concat([water]):parts){if(filt&&!p.water&&!filt(p.mesh))continue;
   for(const [k,b,s] of [['p',p.bp,3],['n',p.bn,3],['uv',p.bu,2]]){const a=A(k);if(a<0)continue;gl.bindBuffer(gl.ARRAY_BUFFER,b);gl.enableVertexAttribArray(a);gl.vertexAttribPointer(a,s,gl.FLOAT,false,0,0)}
   const T=p.terr&&p.terr.every(Boolean);
   if(T){p.terr.forEach((t,j)=>{gl.activeTexture(gl.TEXTURE0+j);gl.bindTexture(gl.TEXTURE_2D,t)})}else{gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,p.t)}
   gl.uniform1f(U('terr'),T?1:0);gl.uniform1f(U('useTex'),p.t?1:0);
   gl.uniform3fv(U('base'),p.water?[0.20,0.43,0.55]:p.terr?[0.42,0.50,0.30]:[0.45,0.42,0.38]);
   gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,p.bi);gl.drawElements(gl.TRIANGLES,p.n,p.i32?gl.UNSIGNED_INT:gl.UNSIGNED_SHORT,0)}}
 let drag=null,pinch=0;const pts=new Map(),zmin=r*(isle?0.12:0.5),zmax=r*(isle?3:8);
 cv.addEventListener('pointerdown',e=>{cv.setPointerCapture(e.pointerId);pts.set(e.pointerId,[e.clientX,e.clientY]);drag=[e.clientX,e.clientY]});
 cv.addEventListener('pointermove',e=>{if(!pts.has(e.pointerId))return;pts.set(e.pointerId,[e.clientX,e.clientY]);
  if(pts.size===2){const [a,b]=[...pts.values()],d=Math.hypot(a[0]-b[0],a[1]-b[1]);if(pinch)dist=Math.max(zmin,Math.min(zmax,dist*pinch/d));pinch=d;draw();return}
  if(!drag)return;yaw+=(e.clientX-drag[0])*0.01;pitch=Math.max(isle?0.08:-1.4,Math.min(1.4,pitch+(e.clientY-drag[1])*0.01));drag=[e.clientX,e.clientY];draw()});
 const up=e=>{pts.delete(e.pointerId);if(pts.size<2)pinch=0;if(!pts.size)drag=null};cv.addEventListener('pointerup',up);cv.addEventListener('pointercancel',up);
 cv.addEventListener('wheel',e=>{e.preventDefault();dist=Math.max(zmin,Math.min(zmax,dist*(e.deltaY>0?1.12:0.89)));draw()},{passive:false});
 new ResizeObserver(draw).observe(cv);draw();
}
window.ItemViewer={mount,mountAll(){document.querySelectorAll('.iv[data-model]').forEach(mount)}};
if(document.readyState!=='loading')window.ItemViewer.mountAll();else document.addEventListener('DOMContentLoaded',()=>window.ItemViewer.mountAll());
})();
