/* WoSB Wiki item viewer: one mesh (a cannon, mortar or figurehead) from the wiki's model pack, with its texture.
   Usage: <div class="iv" data-model="weapons" data-mesh="Cannon_rust_small" data-pack="../pack/"></div> + ItemViewer.mountAll().
   Loads nothing until the reader presses "Show 3D model", so pages stay light. */
(function(){
'use strict';
const VS='attribute vec3 p;attribute vec3 n;attribute vec2 uv;uniform mat4 vp;varying vec3 vn;varying vec2 vuv;void main(){vn=n;vuv=uv;gl_Position=vp*vec4(p,1.0);}';
const FS='precision mediump float;varying vec3 vn;varying vec2 vuv;uniform sampler2D tex;uniform float useTex;uniform vec3 L;void main(){vec4 c=useTex>0.5?texture2D(tex,vuv):vec4(0.45,0.42,0.38,1.0);'+
 'if(c.a<0.3)discard;float d=abs(dot(normalize(vn),L));gl_FragColor=vec4(c.rgb*(0.35+0.75*d),1.0);}';
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
function model(n,cb,fail){if(P.models[n])return cb();const e=P.ix&&P.ix.models[n];if(!e||!e.file)return fail();(P.wait[n]=P.wait[n]||[]).push(cb);if(P.wait[n].length===1)script(P.base+e.file,fail)}
function texture(name,cb){const k=(name||'').toLowerCase();if(!k)return;if(P.tex[k])return cb(P.tex[k]);const e=P.ix&&P.ix.textures&&P.ix.textures[k];if(!e||!e.file)return;
 (P.texWait[k]=P.texWait[k]||[]).push(()=>cb(P.tex[k]));if(P.texWait[k].length===1)script(P.base+e.file)}

function mount(el){
 if(el._iv)return;el._iv=1;P.base=el.dataset.pack||P.base;
 el.innerHTML='<button type="button" class="iv-go">Show 3D model</button><canvas class="iv-gl" hidden></canvas><small class="iv-msg"></small>';
 const msg=el.querySelector('.iv-msg'),cv=el.querySelector('.iv-gl');
 el.querySelector('.iv-go').addEventListener('click',e=>{e.target.remove();msg.textContent='Loading model…';
  const fail=()=>{msg.textContent='The 3D model isn\'t in this build of the wiki.'};
  index(()=>model(el.dataset.model,()=>start(el,cv,msg),fail),fail)});
}
function start(el,cv,msg){
 const m=P.models[el.dataset.model],want=(el.dataset.mesh||'').toLowerCase();
 const ms=g=>(g.mesh||'').toLowerCase();
 let pick=m.groups.filter(g=>ms(g)===want);
 if(!pick.length)pick=m.groups.filter(g=>ms(g).startsWith(want+'_')&&!/_lod\d*$|_shape$/.test(ms(g)));
 if(!pick.length)pick=m.groups.filter(g=>ms(g).startsWith(want)&&!/_shape$/.test(ms(g)));
 if(!pick.length){msg.textContent='This item has no separate 3D model.';return}
 cv.hidden=false;msg.textContent='Drag to turn · scroll or pinch to zoom';
 const gl=cv.getContext('webgl',{antialias:true});if(!gl){msg.textContent='Your browser can\'t show 3D models.';return}
 const sh=(t,s)=>{const o=gl.createShader(t);gl.shaderSource(o,s);gl.compileShader(o);return o};
 const pr=gl.createProgram();gl.attachShader(pr,sh(gl.VERTEX_SHADER,VS));gl.attachShader(pr,sh(gl.FRAGMENT_SHADER,FS));gl.linkProgram(pr);gl.useProgram(pr);
 const mk=(d,t)=>{const b=gl.createBuffer();gl.bindBuffer(t||gl.ARRAY_BUFFER,b);gl.bufferData(t||gl.ARRAY_BUFFER,d,gl.STATIC_DRAW);return b};
 let lo=[1e9,1e9,1e9],hi=[-1e9,-1e9,-1e9];const ext=gl.getExtension('OES_element_index_uint');
 const parts=pick.map(g=>{const q=b64(g.p,Int16Array),pos=new Float32Array(q.length);for(let i=0;i<q.length;i++){const v=(q[i]+32767)*m.scale[i%3]+m.min[i%3];pos[i]=v;const a=i%3;if(v<lo[a])lo[a]=v;if(v>hi[a])hi[a]=v}
  const nr=b64(g.nr,Int8Array),nor=new Float32Array(nr.length);for(let i=0;i<nr.length;i++)nor[i]=nr[i]/127;
  let uv;if(g.uq){const u=b64(g.uq,Int16Array);uv=new Float32Array(u.length);for(let i=0;i<u.length;i++)uv[i]=(u[i]+32767)*g.usc[i%2]+g.umin[i%2]}else uv=new Float32Array(q.length/3*2);
  const idx=b64(g.i,g.i32?Uint32Array:Uint16Array);const part={bp:mk(pos),bn:mk(nor),bu:mk(uv),bi:mk(idx,gl.ELEMENT_ARRAY_BUFFER),n:idx.length,i32:!!g.i32&&!!ext,t:null};
  texture(g.tex||g.mat,im=>{const t=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D,t);gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,im);
   gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);part.t=t;draw()});
  return part});
 const c=[(lo[0]+hi[0])/2,(lo[1]+hi[1])/2,(lo[2]+hi[2])/2],r=Math.max(hi[0]-lo[0],hi[1]-lo[1],hi[2]-lo[2])||1;
 let yaw=0.8,pitch=0.35,dist=r*1.9,raf=0;
 const U=n=>gl.getUniformLocation(pr,n),A=n=>gl.getAttribLocation(pr,n);
 function draw(){if(!raf)raf=requestAnimationFrame(frame)}
 function frame(){raf=0;const w=cv.clientWidth,h=cv.clientHeight,d=window.devicePixelRatio||1;if(cv.width!==Math.round(w*d)){cv.width=Math.round(w*d);cv.height=Math.round(h*d)}
  gl.viewport(0,0,cv.width,cv.height);gl.clearColor(0.93,0.95,0.97,1);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);gl.enable(gl.DEPTH_TEST);
  const eye=[c[0]+Math.cos(pitch)*Math.cos(yaw)*dist,c[1]+Math.sin(pitch)*dist,c[2]+Math.cos(pitch)*Math.sin(yaw)*dist];
  gl.uniformMatrix4fv(U('vp'),false,new Float32Array(mul(persp(0.7,w/h,r*0.02,r*20),look(eye,c))));gl.uniform3fv(U('L'),nrm([0.4,0.9,0.5]));
  for(const p of parts){for(const [k,b,s] of [['p',p.bp,3],['n',p.bn,3],['uv',p.bu,2]]){const a=A(k);if(a<0)continue;gl.bindBuffer(gl.ARRAY_BUFFER,b);gl.enableVertexAttribArray(a);gl.vertexAttribPointer(a,s,gl.FLOAT,false,0,0)}
   gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,p.t);gl.uniform1i(U('tex'),0);gl.uniform1f(U('useTex'),p.t?1:0);
   gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,p.bi);gl.drawElements(gl.TRIANGLES,p.n,p.i32?gl.UNSIGNED_INT:gl.UNSIGNED_SHORT,0)}}
 let drag=null,pinch=0;const pts=new Map();
 cv.addEventListener('pointerdown',e=>{cv.setPointerCapture(e.pointerId);pts.set(e.pointerId,[e.clientX,e.clientY]);drag=[e.clientX,e.clientY]});
 cv.addEventListener('pointermove',e=>{if(!pts.has(e.pointerId))return;pts.set(e.pointerId,[e.clientX,e.clientY]);
  if(pts.size===2){const [a,b]=[...pts.values()],d=Math.hypot(a[0]-b[0],a[1]-b[1]);if(pinch)dist=Math.max(r*0.6,Math.min(r*8,dist*pinch/d));pinch=d;draw();return}
  if(!drag)return;yaw+=(e.clientX-drag[0])*0.01;pitch=Math.max(-1.4,Math.min(1.4,pitch+(e.clientY-drag[1])*0.01));drag=[e.clientX,e.clientY];draw()});
 const up=e=>{pts.delete(e.pointerId);if(pts.size<2)pinch=0;if(!pts.size)drag=null};cv.addEventListener('pointerup',up);cv.addEventListener('pointercancel',up);
 cv.addEventListener('wheel',e=>{e.preventDefault();dist=Math.max(r*0.6,Math.min(r*8,dist*(e.deltaY>0?1.12:0.89)));draw()},{passive:false});
 new ResizeObserver(draw).observe(cv);draw();
}
window.ItemViewer={mount,mountAll(){document.querySelectorAll('.iv[data-model]').forEach(mount)}};
if(document.readyState!=='loading')window.ItemViewer.mountAll();else document.addEventListener('DOMContentLoaded',()=>window.ItemViewer.mountAll());
})();
