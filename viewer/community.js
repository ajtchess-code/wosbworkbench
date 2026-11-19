/* WoSB Wiki: Discord login button, "Report a problem with this page" and "Tell us" forms.
   Talks to the site's Worker (/api/*). On a copy opened from disk, or a host without the Worker, it stays hidden. */
(function(){
'use strict';
if(!/^https?:$/.test(location.protocol))return;
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const here=location.pathname+location.search;
let ME=null;
async function me(){if(ME)return ME;try{const r=await fetch('/api/me',{credentials:'same-origin',cache:'no-store'});if(!r.ok)throw 0;ME=await r.json()}catch(e){ME={off:true}}return ME}

function account(m){
 const box=document.getElementById('acct');if(!box||m.off||!m.login)return;
 if(m.user){
  box.innerHTML=`<button type="button" class="acct-btn" aria-haspopup="true" aria-expanded="false">${m.user.avatar?`<img src="${esc(m.user.avatar)}" alt="" width="26" height="26">`:`<i class="acct-init">${esc((m.user.name||'?').slice(0,1).toUpperCase())}</i>`}<span>${esc(m.user.name)}</span></button>
   <div class="acct-menu" hidden>${m.admin?'<a href="/admin/">Admin dashboard</a>':''}<button type="button" data-logout>Log out</button></div>`;
  const b=box.querySelector('.acct-btn'),menu=box.querySelector('.acct-menu');
  b.addEventListener('click',()=>{menu.hidden=!menu.hidden;b.setAttribute('aria-expanded',String(!menu.hidden))});
  document.addEventListener('click',e=>{if(!box.contains(e.target))menu.hidden=true});
  box.querySelector('[data-logout]').addEventListener('click',async()=>{await fetch('/api/auth/logout',{method:'POST',credentials:'same-origin'});location.reload()});
 }else box.innerHTML=`<a class="acct-login" href="/api/auth/login?return=${encodeURIComponent(here)}"><svg viewBox="0 0 24 20" width="18" height="15" aria-hidden="true"><path fill="currentColor" d="M20 2a19 19 0 0 0-5-2l-.6 1.3a18 18 0 0 0-4.8 0L9 0a19 19 0 0 0-5 2C1 7 0 12 1 17a20 20 0 0 0 6 3l1-2-2-1 1-.5a16 16 0 0 0 10 0l1 .5-2 1 1 2a20 20 0 0 0 6-3c1-5 0-10-3-15ZM8 13c-1 0-2-1-2-2s1-2 2-2 2 1 2 2-1 2-2 2Zm8 0c-1 0-2-1-2-2s1-2 2-2 2 1 2 2-1 2-2 2Z"/></svg><span>Log in</span></a>`;
 box.hidden=false;
}

let tsLoaded=null;
function turnstile(){if(tsLoaded)return tsLoaded;tsLoaded=new Promise((ok,no)=>{const s=document.createElement('script');s.src='https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';s.async=true;s.onload=()=>ok(window.turnstile);s.onerror=no;document.head.appendChild(s)});return tsLoaded}

async function openForm(general){
 const m=await me();if(m.off||!m.reports)return false;
 const title=document.querySelector('main h1')?.textContent||document.title;
 const dlg=document.createElement('div');dlg.className='rp-wrap';dlg.innerHTML=`<form class="rp" role="dialog" aria-modal="true" aria-labelledby="rp-h">
  <button type="button" class="rp-x" aria-label="Close">×</button>
  <h2 id="rp-h">${general?'Tell us':'Report a problem with this page'}</h2>
  <p class="rp-page">${general?'Ideas, corrections or anything else about the WoSB Wiki.':'Page: <b>'+esc(title)+'</b>'}</p>
  <label>What kind of problem?<select name="kind">${general?'<option value="suggestion">Suggestion</option><option value="wrong">Something is wrong</option><option value="missing">Something is missing</option><option value="other" selected>Other</option>'
   :'<option value="wrong">Something is wrong</option><option value="missing">Something is missing</option><option value="suggestion">Suggestion</option><option value="other">Other</option>'}</select></label>
  <label>Details<textarea name="message" rows="5" maxlength="4000" required placeholder="${general?'What would you like to tell us?':'What is wrong or missing? The right value, and where you saw it in game, help a lot.'}"></textarea></label>
  <label>How can we reach you? <small>(optional)</small><input name="contact" maxlength="200" value="${esc(m.user?m.user.name:'')}" placeholder="Discord name or email, if you'd like a reply"></label>
  ${m.user?`<p class="rp-who">Sending as <b>${esc(m.user.name)}</b> (Discord).</p>`:`<div class="rp-ts"></div><p class="rp-who"><a href="/api/auth/login?return=${encodeURIComponent(here)}">Log in with Discord</a> to skip the robot check and let us reply to you.</p>`}
  <p class="rp-msg" role="status"></p><div class="rp-actions"><button type="submit" class="rp-send">Send</button><button type="button" class="rp-cancel">Cancel</button></div></form>`;
 document.body.appendChild(dlg);document.body.classList.add('rp-open');
 const f=dlg.querySelector('form'),msg=f.querySelector('.rp-msg');let widget=null;
 const close=()=>{dlg.remove();document.body.classList.remove('rp-open')};
 f.querySelector('.rp-x').onclick=close;f.querySelector('.rp-cancel').onclick=close;dlg.addEventListener('click',e=>{if(e.target===dlg)close()});
 document.addEventListener('keydown',function k(e){if(e.key==='Escape'){close();document.removeEventListener('keydown',k)}});
 f.querySelector('textarea').focus();
 if(!m.user&&m.turnstile)turnstile().then(ts=>{widget=ts.render(f.querySelector('.rp-ts'),{sitekey:m.turnstile})}).catch(()=>{msg.textContent='The robot check could not load. Log in with Discord to send a report.'});
 f.addEventListener('submit',async e=>{e.preventDefault();const d=Object.fromEntries(new FormData(f));
  if(!m.user&&m.turnstile){d.turnstile=window.turnstile&&widget!=null?window.turnstile.getResponse(widget):'';if(!d.turnstile){msg.textContent='Please complete the robot check first.';return}}
  d.page=general?'(general)':here;d.title=general?'Tell us':title;const btn=f.querySelector('.rp-send');btn.disabled=true;msg.textContent='Sending…';
  try{const r=await fetch('/api/reports',{method:'POST',credentials:'same-origin',headers:{'content-type':'application/json'},body:JSON.stringify(d)});const j=await r.json().catch(()=>({}));
   if(!r.ok){msg.textContent=j.error||'Could not send. Please try again.';btn.disabled=false;if(window.turnstile&&widget!=null)window.turnstile.reset(widget);return}
   f.innerHTML='<button type="button" class="rp-x" aria-label="Close">×</button><h2>Thank you!</h2><p>The wiki team will take a look. Corrections usually go live with the next wiki update.</p><div class="rp-actions"><button type="button" class="rp-send">Close</button></div>';
   f.querySelectorAll('button').forEach(b=>b.onclick=close)}
  catch(err){msg.textContent='Could not send. Please check your connection and try again.';btn.disabled=false}});
 return true;
}

me().then(m=>{
 account(m);
 if(m.off||!m.reports)return;
 document.querySelectorAll('.report-bar').forEach(b=>b.hidden=false);
 document.addEventListener('click',async e=>{const a=e.target.closest('[data-report]');if(!a)return;e.preventDefault();if(!(await openForm(a.dataset.report==='general'))&&a.href)location.href=a.href});
});
window.WikiCommunity={me,openForm};
})();
