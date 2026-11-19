/* WoSB Wiki planners: ship builder, Personal Island planner, chest simulator. Data comes from data/*.json built from the game files. */
(function () {
  'use strict';
  const fmt = (n, d = 0) => (n == null || isNaN(n) ? '–' : (+n).toLocaleString('en-US', { maximumFractionDigits: d }));
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const store = { get(k) { try { return JSON.parse(localStorage.getItem(k) || 'null'); } catch (e) { return null; } }, set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* private mode */ } } };
  const b64e = (s) => btoa(unescape(encodeURIComponent(s))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  const b64d = (s) => decodeURIComponent(escape(atob(s.replace(/-/g, '+').replace(/_/g, '/'))));
  const img = (src, size = 28) => (src ? `<img class="ticon" src="../${esc(src)}" alt="" width="${size}" height="${size}" loading="lazy">` : '');
  const load = (url) => fetch(url).then((r) => r.json());
  function loadShared(key) {
    const q = new URLSearchParams(location.search), h = location.hash.match(/[#&]p=([^&]+)/);
    if (h) { try { return Promise.resolve(JSON.parse(b64d(h[1]))); } catch (e) { /* bad link */ } }
    if (q.get('plan')) return fetch('/api/plans/' + encodeURIComponent(q.get('plan'))).then((r) => (r.ok ? r.json() : null)).then((j) => (j && j.plan) || store.get(key)).catch(() => store.get(key));
    return Promise.resolve(store.get(key));
  }
  function share(state, done) {
    const fallback = () => done(location.origin + location.pathname + '#p=' + b64e(JSON.stringify(state)));
    fetch('/api/plans', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ plan: state }) })
      .then((r) => (r.ok ? r.json() : Promise.reject())).then((j) => { history.replaceState(null, '', '?plan=' + j.id); done(location.origin + location.pathname + '?plan=' + j.id); }).catch(fallback);
  }
  const copy = (text, el) => { const ok = () => { el.textContent = 'Copied: ' + text; }; (navigator.clipboard ? navigator.clipboard.writeText(text).then(ok, () => { el.textContent = text; }) : (el.textContent = text)); };

  // ================================================================== ship builder
  function shipBuilder(el, url) {
    el.innerHTML = '<p class="note">Loading…</p>';
    Promise.all([load(url), loadShared('wosb-ship')]).then(([D, saved]) => {
      const byName = Object.fromEntries(D.ships.map((s) => [s.n, s]));
      const q = new URLSearchParams(location.search);
      let st = Object.assign({ ship: (q.get('ship') && byName[q.get('ship')]) ? q.get('ship') : D.ships[0].n, ups: [], crew: [], lantern: '', fig: '', elite: 0 }, saved || {});
      if (q.get('ship') && byName[q.get('ship')]) st.ship = q.get('ship');
      const opt = (list, cur, f = (x) => x.n) => list.map((x) => `<option value="${esc(f(x))}"${f(x) === cur ? ' selected' : ''}>${esc(x.n)}</option>`).join('');
      el.innerHTML = `<div class="pl"><div class="pl-row"><label>Ship <select data-k="ship">${D.ships.map((s) => `<option${s.n === st.ship ? ' selected' : ''}>${esc(s.n)}</option>`).join('')}</select></label>
        <label>Elite status <select data-k="elite">${[0, 1, 2, 3, 4, 5, 6].map((i) => `<option value="${i}"${+st.elite === i ? ' selected' : ''}>${i ? 'Level ' + i : 'None'}</option>`).join('')}</select></label></div>
        <div class="pl-cols"><div><h3>Upgrades</h3><div class="sb-ups"></div><h3>Special crew</h3><div class="sb-crew"></div>
        <h3>Lantern and figurehead</h3><label>Lantern <select data-k="lantern"><option value="">None</option>${opt(D.designs.filter((d) => d.slot === 'lantern'), st.lantern)}</select></label>
        <label>Figurehead <select data-k="fig"><option value="">None</option>${opt(D.designs.filter((d) => d.slot === 'figurehead'), st.fig)}</select></label></div>
        <div><h3>Result</h3><div class="sb-out"></div><div class="pl-tools"><button type="button" class="sb-share">Share build</button><button type="button" class="sb-clear">Clear</button><span class="pl-msg"></span></div></div></div></div>`;
      const $ = (s) => el.querySelector(s);
      const ship = () => byName[st.ship] || D.ships[0];
      function render() {
        store.set('wosb-ship', st);
        const s = ship(), slots = s.slots;
        st.ups = st.ups.slice(0, slots); while (st.ups.length < slots) st.ups.push('');
        const avail = D.upgrades;
        $('.sb-ups').innerHTML = st.ups.map((u, i) => `<label class="sb-slot">Slot ${i + 1}${i >= slots - 3 ? ' <span class="pl-sub">(unlocks with ship XP)</span>' : ''}
          <select data-up="${i}"><option value="">Empty</option>${['Sailes', 'Speed', 'Protection', 'Combat', 'Mortars', 'Support', 'Unique', 'Modification'].map((cat) => {
            const list = avail.filter((x) => x.cat === cat); if (!list.length) return '';
            return `<optgroup label="${esc({ Sailes: 'Sails' }[cat] || cat)}">${list.map((x) => `<option${x.n === u ? ' selected' : ''}>${esc(x.n)}</option>`).join('')}</optgroup>`; }).join('')}</select></label>`).join('');
        st.crew = st.crew.filter(Boolean);
        $('.sb-crew').innerHTML = `${st.crew.map((c, i) => `<div class="sb-slot">${esc(c)} <button type="button" data-cdel="${i}" aria-label="Remove">✕</button></div>`).join('')}
          <p><select class="sb-cadd">${['Sailors', 'Combats', 'Pirates', 'Adventurers'].map((g) => `<optgroup label="${esc({ Combats: 'Combat' }[g] || g)}">${D.crew.filter((x) => x.g === g).map((x) => `<option>${esc(x.n)}</option>`).join('')}</optgroup>`).join('')}</select>
          <button type="button" class="sb-caddb">Add</button></p><p class="pl-sub">Each special crew member takes one of the ship's ${fmt(s.crew)} crew places.</p>`;
        // ---- add up the effects
        const sum = {}; const add = (c, v) => { sum[c] = (sum[c] || 0) + (+v); };
        const used = st.ups.filter(Boolean); const dup = used.filter((u, i) => used.indexOf(u) !== i);
        for (const u of used) { const x = D.upgrades.find((y) => y.n === u); if (x) (x.fx[String(s.rank)] || []).forEach(([c, v]) => add(c, v)); }
        for (const c of st.crew.filter(Boolean)) { const x = D.crew.find((y) => y.n === c); if (x) x.fx.forEach(([k, v]) => add(k, v)); }
        for (const n of [st.lantern, st.fig].filter(Boolean)) { const x = D.designs.find((y) => y.n === n); if (x) x.fx.forEach(([k, v]) => add(k, v)); }
        if (+st.elite >= 3) add('PCapacity', 10);
        // the game's own order (ShipDynamicInfo): base x (1 + percent) + flat; speed is stored as knots x 2, so a flat speed bonus is half a knot per point
        const stat = (key, base) => { const [m, p] = D.stats[key]; let v = (+base || 0) * (1 + (p ? sum[p] || 0 : 0) / 100) + (m ? (sum[m] || 0) / (key === 'speed' ? 2 : 1) : 0); return v; };
        const rows = [['Speed (knots)', 'speed', 2], ['Defense (armor)', 'armor', 1], ['Durability (HP)', 'hp', 0], ['Maneuverability', 'mob', 1], ['Hold', 'cargo', 0], ['Crew', 'crew', 0]];
        const statCodes = new Set(Object.values(D.stats).flat().filter(Boolean));
        const other = Object.entries(sum).filter(([c, v]) => !statCodes.has(c) && v).map(([c, v]) => {
          const [lab, sign, unit] = D.labels[c] || [c, 1, c[0] === 'P' ? '%' : '']; const x = v * sign;
          return c[0] === 'B' ? lab : `${lab} ${x > 0 ? '+' : x < 0 ? '−' : ''}${fmt(Math.abs(x), 2)}${unit}`; });
        const elite = +st.elite ? Object.entries(D.elite).filter(([k]) => +k <= +st.elite).map(([, v]) => v) : [];
        $('.sb-out').innerHTML = `<p>${img(s.i, 40)}<b>${s.u ? `<a href="../${esc(s.u)}">${esc(s.n)}</a>` : esc(s.n)}</b> · rank ${s.rank} · ${esc(s.cls || '')} · ${slots} upgrade slots</p>
          <table class="wikitable"><thead><tr><th>Stat</th><th>Base</th><th>With this build</th></tr></thead><tbody>${rows.map(([n, k, d]) => {
            const base = s[k], v = stat(k, base), diff = v - (+base || 0);
            return `<tr><td>${n}</td><td>${fmt(base, d)}</td><td><b>${fmt(v, d)}</b>${Math.abs(diff) > 1e-6 ? ` <span class="pl-sub">(${diff > 0 ? '+' : ''}${fmt(diff, d || 1)})</span>` : ''}</td></tr>`; }).join('')}</tbody></table>
          ${other.length ? `<h4>Other effects</h4><ul>${other.map((o) => `<li>${esc(o)}</li>`).join('')}</ul>` : ''}
          ${elite.length ? `<h4>Elite status</h4><ul>${elite.map((o) => `<li>${esc(o)}</li>`).join('')}</ul>` : ''}
          ${dup.length ? `<p class="note">The same upgrade is fitted more than once: ${esc([...new Set(dup)].join(', '))}. The game may not allow that for every upgrade.</p>` : ''}
          ${st.crew.some((c) => { const x = D.crew.find((y) => y.n === c); return x && x.per.length; }) ? '<p class="pl-sub">Some crew effects grow with the number of sailors or boarders on board; those are listed on the Special Crew page.</p>' : ''}`;
      }
      el.addEventListener('change', (e) => {
        const d = e.target.dataset;
        if (d.k) { st[d.k] = e.target.value; if (d.k === 'ship') history.replaceState(null, '', '?ship=' + encodeURIComponent(st.ship)); }
        else if (d.up != null) st.ups[+d.up] = e.target.value;
        else return;
        render();
      });
      el.addEventListener('click', (e) => {
        if (e.target.classList.contains('sb-caddb')) { st.crew.push(el.querySelector('.sb-cadd').value); render(); }
        else if (e.target.dataset.cdel != null) { st.crew.splice(+e.target.dataset.cdel, 1); render(); }
      });
      $('.sb-share').onclick = () => share(st, (u) => copy(u, $('.pl-msg')));
      $('.sb-clear').onclick = () => { st = { ship: st.ship, ups: [], crew: [], lantern: '', fig: '', elite: 0 }; el.querySelector('[data-k=lantern]').value = ''; el.querySelector('[data-k=fig]').value = ''; el.querySelector('[data-k=elite]').value = '0'; render(); };
      render();
    }).catch(() => { el.innerHTML = '<p class="note">The ship data could not be loaded.</p>'; });
  }

  // ================================================================== Personal Island planner
  function buildingPrice(rank, built) {
    // PersonalIsleStatus.NextBuildingPrice: by captain rank and how many buildings the island already has
    const n = rank < 10 ? 20 : rank < 20 ? 50 : 100;
    if (built === 0) return { gold: n * 10, res: {} };
    const a = n * built * Math.max(1, built - 3), b = n * Math.max(1, built - 2);
    return { gold: Math.floor(a / 2) * 6 + Math.floor(b / 3) * 100, res: { Plate: Math.floor(a / 4), Wreckage: Math.floor(a / 2), Wood: a } };
  }
  function islandPlanner(el, url) {
    el.innerHTML = '<p class="note">Loading…</p>';
    Promise.all([load(url), loadShared('wosb-isle')]).then(([D, saved]) => {
      let st = Object.assign({ rank: 20, isles: [{ b: [], d: [] }] }, saved || {});
      el.innerHTML = `<div class="pl"><div class="pl-row"><label>Captain rank <input type="number" min="1" max="30" data-k="rank" value="${esc(st.rank)}"></label>
        <label>Islands <select data-k="n">${[1, 2, 3].map((i) => `<option value="${i}"${st.isles.length === i ? ' selected' : ''}>${i}</option>`).join('')}</select></label></div>
        <div class="ip-out"></div><div class="pl-tools"><button type="button" class="ip-share">Share plan</button><span class="pl-msg"></span></div></div>`;
      const $ = (s) => el.querySelector(s);
      function render() {
        store.set('wosb-isle', st);
        const rank = Math.max(1, Math.min(30, +st.rank || 1));
        let html = '';
        if (rank < D.min_rank) html += `<p class="note">You can found a Personal Island from captain rank ${D.min_rank}.</p>`;
        if (st.isles.length > 1) html += `<p class="pl-sub">A second island needs the captain skill <b>${esc(D.skills[0].n)}</b>${st.isles.length > 2 ? `, and a third needs <b>${esc(D.skills[1].n)}</b> (${esc(D.skills[1].d)})` : ''}.</p>`;
        let grandGold = 0, grandCoins = 0; const grandRes = {};
        st.isles.forEach((isle, ii) => {
          let gold = 0, coins = 0; const res = {}; let labor = D.labor_base, perHour = D.labor_per_hour, storage = D.storage[0];
          const rows = isle.b.map((id, k) => {
            const b = D.buildings.find((x) => x.id === id); const p = buildingPrice(rank, k);
            gold += p.gold; for (const [r, q] of Object.entries(p.res)) res[r] = (res[r] || 0) + q;
            if (b) { labor += b.labor; if (id === 'Pub') perHour += 1; if (id === 'BigStorage') storage = D.storage[1]; }
            return `<tr><td>${k + 1}</td><td>${esc(b ? b.n : id)}</td><td>${fmt(p.gold)} gold${Object.keys(p.res).length ? ', ' + Object.entries(p.res).map(([r, q]) => `${fmt(q)} ${r}`).join(', ') : ''}</td>
              <td><button type="button" data-up="${ii}:${k}" aria-label="Move up">↑</button> <button type="button" data-del="${ii}:${k}" aria-label="Remove">✕</button></td></tr>`; }).join('');
          const next = buildingPrice(rank, isle.b.length);
          const left = D.buildings.filter((b) => !isle.b.includes(b.id));
          const decoRows = isle.d.map((n, k) => { const d = D.decor.find((x) => x.n === n); if (!d) return '';
            if (d.cur === 'gold') gold += d.p || 0; else if (d.cur === 'coins') coins += d.p || 0;
            if (d.code === 'CCurrentIsleWorkLimit') labor += d.v; if (d.code === 'CCurrentIsleCraftTimePerHour') perHour += d.v; if (/CurrentIsleStorage$/.test(d.code)) storage += d.v / 1000;
            return `<tr><td>${img(d.i)}${esc(d.n)}</td><td>${d.p ? fmt(d.p) + (d.cur === 'coins' ? ' Coins' : ' gold') : 'not sold'}</td><td>${esc(d.bonus)}</td><td><button type="button" data-ddel="${ii}:${k}" aria-label="Remove">✕</button></td></tr>`; }).join('');
          grandGold += gold; grandCoins += coins; for (const [r, q] of Object.entries(res)) grandRes[r] = (grandRes[r] || 0) + q;
          html += `<section class="ip-isle"><h3>Island ${ii + 1}</h3>
            <table class="wikitable"><thead><tr><th>#</th><th>Building</th><th>Cost at rank ${rank}</th><th></th></tr></thead><tbody>${rows || '<tr><td colspan="4">No buildings yet.</td></tr>'}</tbody></table>
            ${left.length ? `<p><select data-addb="${ii}">${left.map((b) => `<option value="${esc(b.id)}" title="${esc(b.d)}">${esc(b.n)}</option>`).join('')}</select>
              <button type="button" data-addbb="${ii}">Build next</button> <span class="pl-sub">next one costs ${fmt(next.gold)} gold${Object.keys(next.res).length ? ', ' + Object.entries(next.res).map(([r, q]) => `${fmt(q)} ${r}`).join(', ') : ''}</span></p>` : ''}
            <h4>Decorations</h4><table class="wikitable"><thead><tr><th>Decoration</th><th>Price</th><th>Bonus</th><th></th></tr></thead><tbody>${decoRows || '<tr><td colspan="4">None yet.</td></tr>'}</tbody></table>
            <p><select data-addd="${ii}">${D.decor.map((d) => `<option>${esc(d.n)}</option>`).join('')}</select> <button type="button" data-adddd="${ii}">Add decoration</button></p>
            <p><b>This island:</b> ${fmt(gold)} gold, ${fmt(coins)} Coins${Object.keys(res).length ? ', ' + Object.entries(res).map(([r, q]) => `${fmt(q)} ${r}`).join(', ') : ''}.
              Labour limit <b>${fmt(labor)}</b>, labour back <b>${fmt(perHour, 1)}/hour</b>, warehouse <b>${fmt(storage)} t</b>.</p></section>`;
        });
        html += `<h3>All islands</h3><p><b>${fmt(grandGold)} gold</b>, <b>${fmt(grandCoins)} Coins</b>${Object.keys(grandRes).length ? ', ' + Object.entries(grandRes).map(([r, q]) => `<b>${fmt(q)}</b> ${r}`).join(', ') : ''}.</p>
          <details><summary>What each building does</summary><ul>${D.buildings.map((b) => `<li><b>${esc(b.n)}</b>: ${esc(b.d)}${b.labor ? ` <span class="pl-sub">(labour limit +${b.labor})</span>` : ''}</li>`).join('')}</ul></details>
          <p class="pl-sub">The first building on an island costs gold only; later ones also need Plates, Wreckage and Wood, and get dearer with every building. Abandoning an island does not refund building costs.</p>`;
        $('.ip-out').innerHTML = html;
      }
      el.addEventListener('change', (e) => {
        const d = e.target.dataset;
        if (d.k === 'rank') { st.rank = +e.target.value || 1; render(); }
        else if (d.k === 'n') { const n = +e.target.value; while (st.isles.length < n) st.isles.push({ b: [], d: [] }); st.isles = st.isles.slice(0, n); render(); }
      });
      el.addEventListener('click', (e) => {
        const d = e.target.dataset; const ix = (s) => s.split(':').map(Number);
        if (d.addbb != null) { const s = el.querySelector(`[data-addb="${d.addbb}"]`); st.isles[+d.addbb].b.push(s.value); }
        else if (d.adddd != null) { const s = el.querySelector(`[data-addd="${d.adddd}"]`); st.isles[+d.adddd].d.push(s.value); }
        else if (d.del) { const [i, k] = ix(d.del); st.isles[i].b.splice(k, 1); }
        else if (d.ddel) { const [i, k] = ix(d.ddel); st.isles[i].d.splice(k, 1); }
        else if (d.up) { const [i, k] = ix(d.up); if (k > 0) { const b = st.isles[i].b; [b[k - 1], b[k]] = [b[k], b[k - 1]]; } }
        else return;
        render();
      });
      $('.ip-share').onclick = () => share(st, (u) => copy(u, $('.pl-msg')));
      render();
    }).catch(() => { el.innerHTML = '<p class="note">The island data could not be loaded.</p>'; });
  }

  // ================================================================== chest simulator
  function pick(rewards, rnd) {
    const total = rewards.reduce((a, r) => a + r.w, 0); let x = rnd() * total;
    for (let i = 0; i < rewards.length; i++) { x -= rewards[i].w; if (x < 0) return i; }
    return rewards.length - 1;
  }
  function chestSim(el, url) {
    el.innerHTML = '<p class="note">Loading…</p>';
    load(url).then((D) => {
      const keys = Object.keys(D.chests);
      let cur = keys[0], log = [], counts = {}, pity = {}, opened = 0, owned = new Set();
      el.innerHTML = `<div class="pl"><div class="pl-row"><label>Chest <select class="cs-ch">${keys.map((k) => `<option value="${k}">${esc(D.chests[k].name)}</option>`).join('')}</select></label>
        <button type="button" data-n="1">Open 1</button><button type="button" data-n="10">Open 10</button><button type="button" data-n="100">Open 100</button><button type="button" data-n="1000">Open 1,000</button>
        <button type="button" class="cs-reset">Reset</button></div><div class="cs-sum"></div><div class="pl-cols"><div><h3>Last opens</h3><ol class="cs-log"></ol></div>
        <div><h3>Odds and results</h3><div class="cs-odds"></div></div></div></div>`;
      const $ = (s) => el.querySelector(s);
      const chest = () => D.chests[cur];
      function open(n) {
        const c = chest();
        for (let i = 0; i < n; i++) {
          // a reward with a guaranteed-within counter is given once its counter runs out
          let idx = -1;
          c.rewards.forEach((r, j) => { if (r.pity && idx < 0 && (pity[j] || 0) + 1 >= r.pity) idx = j; });
          if (idx < 0) {
            let tries = 0;
            do { idx = pick(c.rewards, Math.random); tries++; } while (c.rewards[idx].t === 'ship' && owned.has(c.rewards[idx].id) && tries < 50);
          }
          c.rewards.forEach((r, j) => { if (r.pity) pity[j] = j === idx ? 0 : (pity[j] || 0) + 1; });
          const r = c.rewards[idx]; if (r.t === 'ship') owned.add(r.id);
          counts[idx] = (counts[idx] || 0) + 1; opened++; log.unshift({ idx, tier: r.tier }); if (log.length > 30) log.pop();
        }
        render();
      }
      function cost(n) {
        const c = chest(); if (!c.price_key) return '';
        let p = D.prices[c.price_key] * (cur === 'newyear' ? D.newyear_price_multiplier : 1);
        const ten = Math.floor(n / 10), rest = n % 10;
        const total = ten * 10 * p * D.open10_discount + rest * p;
        return `${fmt(total)} Coins`;
      }
      function render() {
        const c = chest(), tierName = { 1: 'common', 2: 'rare', 3: 'very rare' };
        $('.cs-sum').innerHTML = `<p>Opened <b>${fmt(opened)}</b>${chest().price_key ? ` · would cost about <b>${cost(opened)}</b> (10 at once: 5% off)` : ''}${c.name === 'Altar offering' ? ' · altars are found around the world; offerings cost nothing here' : ''}.</p>`;
        $('.cs-log').innerHTML = log.map((l) => `<li class="cs-t${l.tier}">${esc(c.rewards[l.idx].label)}</li>`).join('') || '<li class="pl-sub">Nothing opened yet.</li>';
        $('.cs-odds').innerHTML = `<table class="wikitable sortable"><thead><tr><th>Reward</th><th>Chance</th><th>Got</th></tr></thead><tbody>${c.rewards.map((r, j) => `<tr class="cs-t${r.tier}"><td>${esc(r.label)}${r.pity ? ` <span class="pl-sub">(guaranteed within ${r.pity})</span>` : ''}${r.t === 'ship' ? ' <span class="pl-sub">(skipped if owned)</span>' : ''}</td>
          <td>${fmt(r.pct, r.pct < 1 ? 2 : 1)}%</td><td>${fmt(counts[j] || 0)}</td></tr>`).join('')}</tbody></table>
          <p class="pl-sub">${esc(D.notes.pity)} ${esc(D.notes.ships)} Rarity colours: ${Object.values(tierName).join(', ')}.</p>`;
      }
      $('.cs-ch').onchange = (e) => { cur = e.target.value; log = []; counts = {}; pity = {}; opened = 0; owned = new Set(); render(); };
      $('.cs-reset').onclick = () => { log = []; counts = {}; pity = {}; opened = 0; owned = new Set(); render(); };
      el.addEventListener('click', (e) => { if (e.target.dataset.n) open(+e.target.dataset.n); });
      render();
    }).catch(() => { el.innerHTML = '<p class="note">The chest data could not be loaded.</p>'; });
  }

  window.Planners = { shipBuilder, islandPlanner, chestSim, _test: { buildingPrice, pick } };
})();
