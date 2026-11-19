/* WoSB Wiki admin dashboard: every "Report a problem" and "Tell us" message in one list. Admins only (ADMIN_DISCORD_IDS). */
(function(){
'use strict';
const app=document.getElementById('admin-app');if(!app)return;
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const KIND={wrong:'Something is wrong',missing:'Something is missing',suggestion:'Suggestion',other:'Other'};
const STATUS={open:'Open',resolved:'Resolved',wontfix:"Won't fix",all:'All'};
let state={status:'open',q:''};
const when=s=>{try{return new Date(s).toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'})}catch(e){return s}};
async function api(path,body){const r=await fetch(path,body?{method:'POST',credentials:'same-origin',headers:{'content-type':'application/json'},body:JSON.stringify(body)}:{credentials:'same-origin',cache:'no-store'});
 const j=await r.json().catch(()=>({}));if(!r.ok)throw new Error(j.error||('HTTP '+r.status));return j}
async function start(){
 if(!/^https?:$/.test(location.protocol)){app.innerHTML='<p class="note">The admin dashboard works on the live site (wosbwiki.org), not on a copy opened from disk.</p>';return}
 let m;try{m=await api('/api/me')}catch(e){app.innerHTML='<p class="note">The wiki server isn\'t answering, so the dashboard can\'t load here.</p>';return}
 if(!m.user){app.innerHTML=`<p>Log in with your Discord account to open the admin dashboard.</p><p><a class="acct-login big" href="/api/auth/login?return=/admin/">Log in with Discord</a></p>`;return}
 if(!m.admin){app.innerHTML=`<p class="note">You're logged in as <b>${esc(m.user.name)}</b>, but this Discord account isn't on the admin list. Ask a site admin to add your Discord user ID (<code>${esc(m.user.id)}</code>).</p>`;return}
 if(!m.reports){app.innerHTML='<p class="note">No database is connected yet. Add a D1 binding named <code>DB</code> to the Pages project (see the hosting guide).</p>';return}
 app.innerHTML=`<div class="ad-bar"><div class="ad-tabs" role="tablist"></div><input type="search" class="ad-q" placeholder="Search reports…" aria-label="Search reports">
  <a class="ad-csv" href="/api/admin/reports.csv?status=all">Download CSV</a><button type="button" class="ad-reload">Refresh</button></div><div class="ad-list" aria-live="polite">Loading…</div>`;
 let t=0;app.querySelector('.ad-q').addEventListener('input',e=>{clearTimeout(t);t=setTimeout(()=>{state.q=e.target.value.trim();load()},300)});
 app.querySelector('.ad-reload').onclick=load;load();
}
async function load(){
 const list=app.querySelector('.ad-list');let d;
 try{d=await api(`/api/admin/reports?status=${state.status}&q=${encodeURIComponent(state.q)}`)}catch(e){list.innerHTML=`<p class="note">${esc(e.message)}</p>`;return}
 const c=d.counts||{},total=Object.values(c).reduce((a,b)=>a+b,0);
 app.querySelector('.ad-tabs').innerHTML=Object.entries(STATUS).map(([k,v])=>`<button type="button" role="tab" aria-selected="${k===state.status}" data-s="${k}" class="${k===state.status?'on':''}">${v} <small>${k==='all'?total:(c[k]||0)}</small></button>`).join('');
 app.querySelectorAll('.ad-tabs button').forEach(b=>b.onclick=()=>{state.status=b.dataset.s;load()});
 if(!d.reports.length){list.innerHTML=`<p class="ad-empty">No ${state.status==='all'?'':STATUS[state.status].toLowerCase()+' '}reports${state.q?' matching “'+esc(state.q)+'”':''}.</p>`;return}
 list.innerHTML=d.reports.map(r=>`<article class="ad-item ad-${esc(r.status)}" data-id="${r.id}">
  <header><span class="ad-kind ad-k-${esc(r.kind)}">${esc(KIND[r.kind]||r.kind)}</span>
   ${r.page&&r.page!=='(general)'?`<a href="${esc(r.page)}" target="_blank" rel="noopener">${esc(r.page_title||r.page)}</a>`:'<b>Tell us (general)</b>'}
   <time datetime="${esc(r.created)}">${esc(when(r.created))}</time></header>
  <p class="ad-msg">${esc(r.message)}</p>
  <p class="ad-from">From: ${r.user_id?`<a href="https://discord.com/users/${esc(r.user_id)}" target="_blank" rel="noopener">${esc(r.user_name)}</a> (Discord)`:'Anonymous'}${r.contact?` · Contact: <b>${esc(r.contact)}</b>`:''}</p>
  ${r.handled_by?`<p class="ad-from">Last handled by ${esc(r.handled_by)}${r.updated?' · '+esc(when(r.updated)):''}</p>`:''}
  <div class="ad-act"><select aria-label="Status">${['open','resolved','wontfix'].map(s=>`<option value="${s}" ${s===r.status?'selected':''}>${STATUS[s]}</option>`).join('')}</select>
   <input class="ad-note" placeholder="Note for other admins" value="${esc(r.note||'')}" maxlength="2000"><button type="button" class="ad-save">Save</button><button type="button" class="ad-del">Delete</button></div></article>`).join('');
 list.querySelectorAll('.ad-item').forEach(el=>{const id=+el.dataset.id;
  el.querySelector('.ad-save').onclick=async()=>{try{await api('/api/admin/report',{id,status:el.querySelector('select').value,note:el.querySelector('.ad-note').value});load()}catch(e){alertLine(el,e.message)}};
  el.querySelector('.ad-del').onclick=async()=>{const b=el.querySelector('.ad-del');if(b.dataset.sure!=='1'){b.dataset.sure='1';b.textContent='Click again to delete';return}
   try{await api('/api/admin/report',{id,delete:true});load()}catch(e){alertLine(el,e.message)}}});
}
function alertLine(el,text){let p=el.querySelector('.ad-err');if(!p){p=document.createElement('p');p.className='ad-err';el.appendChild(p)}p.textContent=text}
start();
})();
