/* WoSB Wiki crafting calculator. Data: data/crafting.json ({items, recipes}) built from the game's recipes.
   State (targets, per-item choices, prices, lots, stock) lives in the page, in localStorage when available,
   in a #p=… link, or in a short share link stored by the site (/api/plans, deleted after 30 days unused). */
(function () {
  'use strict';
  const fmt = (n) => (n == null || isNaN(n) ? '' : Math.round(n).toLocaleString('en-US'));
  const fmt1 = (n) => (n == null || isNaN(n) ? '' : (Math.round(n * 10) / 10).toLocaleString('en-US'));
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const b64e = (s) => btoa(unescape(encodeURIComponent(s))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  const b64d = (s) => decodeURIComponent(escape(atob(s.replace(/-/g, '+').replace(/_/g, '/'))));
  const store = { get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }, set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } } };

  function parseLots(text) {
    // "500@12, 2000@15"  ->  [[500,12],[2000,15]] sorted by price
    const out = [];
    for (const part of String(text || '').split(/[,;\n]+/)) {
      const m = part.replace(/[\s_]/g, '').replace(/(\d),(?=\d{3})/g, '$1').match(/^(\d+(?:\.\d+)?)[x×@*](\d+(?:\.\d+)?)$/i);
      if (m) out.push([+m[1], +m[2]]);
    }
    return out.sort((a, b) => a[1] - b[1]);
  }
  function lotCost(lots, qty, fallback) {
    let left = qty, cost = 0;
    for (const [q, p] of lots) { const t = Math.min(left, q); cost += t * p; left -= t; if (left <= 0) break; }
    if (left > 0) cost += left * (fallback == null ? NaN : fallback);
    return cost;
  }

  function mount(el, dataUrl) {
    el.innerHTML = '<p class="note">Loading recipes…</p>';
    fetch(dataUrl).then((r) => r.json()).then((D) => start(el, D)).catch(() => { el.innerHTML = '<p class="note">The recipe data could not be loaded.</p>'; });
  }

  function start(el, D) {
    const items = D.items, R = D.recipes;
    const byOut = {};
    R.forEach((r, i) => { (byOut[r.o] = byOut[r.o] || []).push(i); });
    const craftable = Object.keys(byOut).sort((a, b) => items[a].n.localeCompare(items[b].n));
    let st = { targets: [], opt: {}, raw: false, island: false };
    // ------------------------------------------------------------------ state in / out
    function load() {
      const q = new URLSearchParams(location.search), h = location.hash.match(/[#&]p=([^&]+)/);
      if (h) { try { st = Object.assign(st, JSON.parse(b64d(h[1]))); return Promise.resolve(); } catch (e) { /* bad link */ } }
      if (q.get('plan')) return fetch('/api/plans/' + encodeURIComponent(q.get('plan'))).then((r) => (r.ok ? r.json() : null)).then((j) => { if (j && j.plan) st = Object.assign(st, j.plan); }).catch(() => {});
      const saved = store.get('wosb-craft'); if (saved) { try { st = Object.assign(st, JSON.parse(saved)); } catch (e) { /* ignore */ } }
      const add = q.get('add');                      // links from item pages: ?add=s:12
      if (add && items[add] && !st.targets.some((t) => t.k === add)) st.targets.push({ k: add, q: Math.max(1, +q.get('q') || 1) });
      return Promise.resolve();
    }
    const save = () => store.set('wosb-craft', JSON.stringify(st));
    const O = (k) => (st.opt[k] = st.opt[k] || {});
    // ------------------------------------------------------------------ pricing
    const buyUnit = (k) => {
      const o = st.opt[k] || {}; const lots = parseLots(o.lots);
      if (o.price !== undefined && o.price !== '' && o.price !== null) return +o.price;
      if (lots.length) return lots[0][1];
      return items[k] && items[k].p != null ? items[k].p : null;
    };
    function recipeOf(k) {
      const list = byOut[k]; if (!list) return null;
      const o = st.opt[k] || {};
      if (o.r != null && list.includes(+o.r)) return R[+o.r];
      // default: the cheapest per unit at current prices; Personal Island first when the island option is on
      let best = null, bestCost = Infinity;
      for (const i of list) {
        const r = R[i]; let c = r.g;
        for (const [ik, q] of r.ins) c += q * (unitCost(ik, 1) ?? 1e6);
        c /= r.q; if (st.island && /Island/.test(r.c)) c *= 0.5;
        if (c < bestCost) { bestCost = c; best = r; }
      }
      return best;
    }
    const memo = new Map();
    function unitCost(k, depth) {
      const key = k; if (memo.has(key)) return memo.get(key);
      if (depth > 12) return buyUnit(k);
      memo.set(key, buyUnit(k));             // cycle guard
      const mode = (st.opt[k] || {}).m || 'auto';
      const buy = buyUnit(k); let craft = null;
      if (byOut[k] && mode !== 'buy') {
        let best = Infinity;
        for (const i of byOut[k]) {
          const r = R[i]; let c = r.g;
          for (const [ik, q] of r.ins) { const u = unitCost(ik, depth + 1); c += q * (u == null ? 0 : u); }
          best = Math.min(best, c / r.q);
        }
        craft = best;
      }
      const v = mode === 'buy' ? buy : mode === 'craft' || st.raw ? (craft ?? buy) : (buy == null ? craft : craft == null ? buy : Math.min(buy, craft));
      memo.set(key, v); return v;
    }
    function decide(k) {
      const mode = (st.opt[k] || {}).m || 'auto';
      if (!byOut[k] || mode === 'buy') return 'buy';
      if (mode === 'craft' || st.raw) return 'craft';
      const buy = buyUnit(k); if (buy == null) return 'craft';
      const r = recipeOf(k); let c = r.g; for (const [ik, q] of r.ins) c += q * (unitCost(ik, 1) ?? 0);
      return c / r.q < buy ? 'craft' : 'buy';
    }
    // ------------------------------------------------------------------ the plan
    function plan() {
      memo.clear();
      const order = [], seen = new Set(), onStack = new Set(), loops = [];
      function visit(k) {
        if (seen.has(k)) return; if (onStack.has(k)) { loops.push(k); return; }
        onStack.add(k);
        if (decide(k) === 'craft') for (const [ik] of recipeOf(k).ins) visit(ik);
        onStack.delete(k); seen.add(k); order.push(k);
      }
      st.targets.forEach((t) => items[t.k] && visit(t.k));
      order.reverse();                       // every item comes before what it is made from
      const need = {}, rows = {};
      st.targets.forEach((t) => { if (items[t.k]) need[t.k] = (need[t.k] || 0) + Math.max(0, +t.q || 0); });
      let gold = 0, hours = 0, buyCost = 0, unknown = [];
      const steps = [];
      for (const k of order) {
        const want = need[k] || 0; if (!want) continue;
        const have = Math.max(0, +((st.opt[k] || {}).have) || 0), fromStock = Math.min(have, want), net = want - fromStock;
        const row = rows[k] = { k, want, fromStock, net, how: decide(k), buy: 0, cost: 0, made: 0, left: 0 };
        if (!net) continue;
        if (row.how === 'craft') {
          const r = recipeOf(k), batches = Math.ceil(net / r.q);
          row.made = batches * r.q; row.left = row.made - net; row.r = r; row.batches = batches;
          gold += batches * r.g; hours += batches * r.h;
          for (const [ik, q] of r.ins) need[ik] = (need[ik] || 0) + q * batches;
          steps.push(row);
        } else {
          row.buy = net; const o = st.opt[k] || {};
          row.cost = lotCost(parseLots(o.lots), net, buyUnit(k));
          if (isNaN(row.cost)) unknown.push(k); else buyCost += row.cost;
        }
      }
      steps.reverse();                        // build order: materials first
      return { rows, order, steps, gold, hours, buyCost, unknown, loops };
    }
    // ------------------------------------------------------------------ UI
    el.innerHTML = `<div class="cc">
      <div class="cc-targets"><h3>What do you want to make?</h3><div class="cc-tlist"></div>
        <div class="cc-add"><input list="cc-items" class="cc-pick" placeholder="Search: ship, cannon, ammo, consumable, upgrade, material…" aria-label="Item">
        <input type="number" class="cc-q" value="1" min="1" aria-label="Quantity"><button type="button" class="cc-addb">Add</button></div>
        <datalist id="cc-items">${craftable.map((k) => `<option value="${esc(items[k].n)}">${esc(items[k].k)}</option>`).join('')}</datalist>
        <label><input type="checkbox" class="cc-raw"> Rawest materials (craft everything that can be crafted)</label>
        <label><input type="checkbox" class="cc-isl"> I have a Personal Island workshop (prefer its faster recipes)</label></div>
      <div class="cc-sum"></div>
      <div class="cc-tools"><button type="button" data-copy="list">Copy shopping list</button><button type="button" data-copy="steps">Copy steps</button>
        <button type="button" class="cc-share">Share link</button><button type="button" class="cc-card">Save as image</button>
        <button type="button" class="cc-reset">Clear</button><span class="cc-msg" role="status"></span></div>
      <h3>Materials and choices</h3><p class="note">Set how you get each part, what you pay, mixed lots (<code>500@12, 2000@15</code>) and what you already have.</p>
      <div class="cc-mats"></div><h3>Step by step</h3><ol class="cc-steps"></ol></div>`;
    const $ = (s) => el.querySelector(s);
    const nameToKey = {}; craftable.forEach((k) => { nameToKey[items[k].n.toLowerCase()] = k; });
    Object.keys(items).forEach((k) => { nameToKey[items[k].n.toLowerCase()] = nameToKey[items[k].n.toLowerCase()] || k; });
    const link = (k) => { const it = items[k]; const ic = it.i ? `<img class="ticon" src="../${esc(it.i)}" alt="" width="24" height="24" loading="lazy">` : '';
      return ic + (it.u ? `<a href="${it.u.startsWith('../') ? esc(it.u) : '../' + esc(it.u)}">${esc(it.n)}</a>` : esc(it.n)); };
    let last = null;
    function render() {
      save(); const P = last = plan();
      $('.cc-raw').checked = !!st.raw; $('.cc-isl').checked = !!st.island;
      $('.cc-tlist').innerHTML = st.targets.length ? st.targets.map((t, i) => items[t.k] ? `<div class="cc-t">${link(t.k)} <span class="cc-sub">${esc(items[t.k].k)}</span>
        × <input type="number" min="1" value="${esc(t.q)}" data-tq="${i}" aria-label="Quantity"> <button type="button" data-tdel="${i}" aria-label="Remove">✕</button></div>` : '').join('')
        : '<p class="note">Nothing yet: search above and press Add. You can plan several things at once.</p>';
      const total = P.buyCost + P.gold;
      $('.cc-sum').innerHTML = st.targets.length ? `<div class="cc-cards">
        <div><b>${fmt(total)}</b><span>gold in total${P.unknown.length ? ' (+ parts with no price)' : ''}</span></div>
        <div><b>${fmt(P.buyCost)}</b><span>buying materials</span></div><div><b>${fmt(P.gold)}</b><span>gold the recipes charge</span></div>
        <div><b>${fmt1(P.hours)} h</b><span>craft time (sum of batches)</span></div></div>
        ${P.unknown.length ? `<p class="note">No price for: ${P.unknown.map((k) => esc(items[k].n)).join(', ')}. Put one in, or say you have them.</p>` : ''}
        ${P.loops.length ? '<p class="note">Some recipes loop back on themselves; those parts are treated as bought.</p>' : ''}` : '';
      const rows = P.order.map((k) => P.rows[k]).filter(Boolean);
      $('.cc-mats').innerHTML = rows.length ? `<table class="wikitable cc-table"><thead><tr><th>Item</th><th>Needed</th><th>Get it by</th><th>Recipe</th><th>Price each</th><th>Lots</th><th>Have</th><th>Buy</th><th>Cost</th></tr></thead><tbody>${rows.map((r) => {
        const o = st.opt[r.k] || {}, list = byOut[r.k] || [], it = items[r.k];
        const mode = `<select data-m="${esc(r.k)}">${['auto', 'craft', 'buy'].filter((m) => m !== 'craft' || list.length).map((m) => `<option value="${m}"${(o.m || 'auto') === m ? ' selected' : ''}>${{ auto: 'Auto', craft: 'Craft', buy: 'Buy' }[m]}</option>`).join('')}</select>
          <span class="cc-sub">${r.how === 'craft' ? 'crafting' : 'buying'}</span>`;
        const rec = list.length > 1 ? `<select data-r="${esc(r.k)}">${list.map((i) => { const x = R[i]; return `<option value="${i}"${recipeOf(r.k) === x ? ' selected' : ''}>${esc(x.c)}: ${x.q} per batch${x.h ? ', ' + fmt1(x.h) + ' h' : ''}</option>`; }).join('')}</select>` : list.length ? esc(R[list[0]].c) : '<span class="cc-sub">not craftable</span>';
        const range = it.mn || it.mx ? ` title="Market range ${fmt(it.mn)}–${fmt(it.mx)}"` : '';
        return `<tr><td>${link(r.k)}</td><td>${fmt(r.want)}${r.left ? `<br><span class="cc-sub">+${fmt(r.left)} spare</span>` : ''}</td><td>${mode}</td><td>${rec}</td>
          <td><input type="number" min="0" step="any" data-p="${esc(r.k)}" value="${o.price != null ? esc(o.price) : ''}" placeholder="${it.p != null ? fmt(it.p) : '?'}"${range} aria-label="Price each"></td>
          <td><input type="text" data-l="${esc(r.k)}" value="${esc(o.lots || '')}" placeholder="qty@price" aria-label="Lots"></td>
          <td><input type="number" min="0" data-h="${esc(r.k)}" value="${o.have ? esc(o.have) : ''}" placeholder="0" aria-label="Have"></td>
          <td>${r.buy ? fmt(r.buy) : ''}</td><td>${r.buy ? (isNaN(r.cost) ? '?' : fmt(r.cost)) : ''}</td></tr>`; }).join('')}</tbody></table>` : '';
      $('.cc-steps').innerHTML = P.steps.map((s) => `<li><b>Craft ${fmt(s.batches)}× ${esc(items[s.k].n)}</b> at the ${esc(s.r.c)}${s.r.q > 1 ? ` (${s.r.q} per batch, ${fmt(s.made)} made)` : ''}:
        ${s.r.ins.map(([ik, q]) => `${fmt(q * s.batches)} ${esc(items[ik] ? items[ik].n : ik)}`).join(', ')}${s.r.g ? `, ${fmt(s.r.g * s.batches)} gold` : ''}${s.r.h ? `, ${fmt1(s.r.h * s.batches)} h` : ''}.</li>`).join('')
        || (st.targets.length ? '<li>Nothing to craft: everything is bought or already in stock.</li>' : '');
    }
    function textList() {
      const P = last; const out = ['WoSB shopping list — ' + st.targets.map((t) => `${t.q}× ${items[t.k] ? items[t.k].n : t.k}`).join(', ')];
      for (const k of P.order) { const r = P.rows[k]; if (r && r.buy) out.push(`${fmt(r.buy)} ${items[k].n}${isNaN(r.cost) ? '' : ` — ${fmt(r.cost)} gold`}`); }
      out.push(`Total: ${fmt(P.buyCost + P.gold)} gold (${fmt(P.gold)} recipe gold), ${fmt1(P.hours)} h crafting`); return out.join('\n');
    }
    function textSteps() {
      return last.steps.map((s, i) => `${i + 1}. Craft ${s.batches}× ${items[s.k].n} at the ${s.r.c}: ` + s.r.ins.map(([ik, q]) => `${fmt(q * s.batches)} ${items[ik] ? items[ik].n : ik}`).join(', ') + (s.r.g ? `, ${fmt(s.r.g * s.batches)} gold` : '')).join('\n');
    }
    const msg = (t) => { $('.cc-msg').textContent = t; setTimeout(() => { if ($('.cc-msg').textContent === t) $('.cc-msg').textContent = ''; }, 6000); };
    const copy = (t, what) => (navigator.clipboard ? navigator.clipboard.writeText(t).then(() => msg(what + ' copied.'), () => msg('Copy failed: select and copy by hand.')) : msg('Copy is not available here.'));
    function add() {
      const name = $('.cc-pick').value.trim().toLowerCase(); const k = nameToKey[name];
      if (!k) { msg('Pick an item from the list.'); return; }
      const q = Math.max(1, Math.round(+$('.cc-q').value || 1));
      const t = st.targets.find((x) => x.k === k); if (t) t.q = +t.q + q; else st.targets.push({ k, q });
      $('.cc-pick').value = ''; render();
    }
    $('.cc-addb').onclick = add; $('.cc-pick').addEventListener('keydown', (e) => { if (e.key === 'Enter') add(); });
    $('.cc-raw').onchange = (e) => { st.raw = e.target.checked; render(); };
    $('.cc-isl').onchange = (e) => { st.island = e.target.checked; render(); };
    $('.cc-reset').onclick = () => { st = { targets: [], opt: {}, raw: false, island: false }; history.replaceState(null, '', location.pathname); render(); };
    el.addEventListener('change', (e) => {
      const d = e.target.dataset;
      if (d.tq != null) st.targets[+d.tq].q = Math.max(1, Math.round(+e.target.value || 1));
      else if (d.m) O(d.m).m = e.target.value;
      else if (d.r) O(d.r).r = +e.target.value;
      else if (d.p) O(d.p).price = e.target.value === '' ? null : +e.target.value;
      else if (d.l != null) O(d.l).lots = e.target.value;
      else if (d.h) O(d.h).have = Math.max(0, +e.target.value || 0);
      else return;
      render();
    });
    el.addEventListener('click', (e) => {
      const d = e.target.dataset;
      if (d.tdel != null) { st.targets.splice(+d.tdel, 1); render(); }
      else if (d.copy === 'list') copy(textList(), 'Shopping list');
      else if (d.copy === 'steps') copy(textSteps(), 'Steps');
    });
    $('.cc-share').onclick = () => {
      const plan = JSON.stringify(st);
      const fallback = () => { const u = location.origin + location.pathname + '#p=' + b64e(plan); copy(u, 'Link'); };
      fetch('/api/plans', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ plan: st }) })
        .then((r) => (r.ok ? r.json() : Promise.reject())).then((j) => { const u = location.origin + location.pathname + '?plan=' + j.id; history.replaceState(null, '', '?plan=' + j.id); copy(u, 'Share link (kept while it is used; removed after 30 days unused)'); })
        .catch(fallback);
    };
    $('.cc-card').onclick = () => {
      const P = last; if (!P || !st.targets.length) { msg('Add something to make first.'); return; }
      const lines = [];
      for (const k of P.order) { const r = P.rows[k]; if (r && r.buy) lines.push([items[k].n, fmt(r.buy), isNaN(r.cost) ? '?' : fmt(r.cost)]); }
      const W = 760, H = 150 + 26 * (lines.length + P.steps.length) + 60, c = document.createElement('canvas'); c.width = W; c.height = H;
      const g = c.getContext('2d'); g.fillStyle = '#0f2847'; g.fillRect(0, 0, W, H); g.fillStyle = '#fff'; g.font = 'bold 22px Georgia, serif';
      g.fillText(st.targets.map((t) => `${t.q}× ${items[t.k].n}`).join(', ').slice(0, 60), 24, 40);
      g.font = '15px system-ui, sans-serif'; g.fillStyle = '#cfe0f5';
      g.fillText(`Total ${fmt(P.buyCost + P.gold)} gold · ${fmt(P.gold)} recipe gold · ${fmt1(P.hours)} h crafting`, 24, 68);
      let y = 104; g.fillStyle = '#fff'; g.font = 'bold 16px system-ui'; g.fillText('Buy', 24, y); y += 24; g.font = '15px system-ui';
      for (const [n, q, cst] of lines) { g.fillStyle = '#e8eef6'; g.fillText(`${q} ${n}`, 32, y); g.textAlign = 'right'; g.fillText(cst + ' gold', W - 24, y); g.textAlign = 'left'; y += 26; }
      y += 8; g.fillStyle = '#fff'; g.font = 'bold 16px system-ui'; g.fillText('Craft', 24, y); y += 24; g.font = '15px system-ui';
      P.steps.forEach((s, i) => { g.fillStyle = '#e8eef6'; g.fillText(`${i + 1}. ${s.batches}× ${items[s.k].n} (${s.r.c})`.slice(0, 90), 32, y); y += 26; });
      g.fillStyle = '#8fb3dd'; g.font = '13px system-ui'; g.fillText('wosbwiki.org · Crafting calculator', 24, H - 20);
      const a = document.createElement('a'); a.download = 'wosb-crafting-plan.png'; a.href = c.toDataURL('image/png'); a.click();
    };
    load().then(render);
  }

  window.Crafting = { mount, _test: { parseLots, lotCost } };
})();
