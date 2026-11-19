// WoSB simulation rules (browser port of combat_sim.py / damage_model.py).
// Ported from the game client's shared code; server-only values are inputs.
(function (root) {
  'use strict';
  const E = 2.71828182846, SQ3 = 1.73205080757;
  function i32(v) { return Number(BigInt.asIntN(32, typeof v === "bigint" ? v : BigInt(Math.trunc(v)))); }
  function fmod(a, b) { return a % b; }                      // JS % keeps the dividend's sign, like C#
  function hash01(h) { h = Math.trunc(h); const sq = i32(BigInt(h) * BigInt(h)); const inner = fmod(fmod(h * 24.232 + sq, E), SQ3); return fmod(h * inner, 1); }
  const SPREAD = Array.from({ length: 128 }, (_, i) => { const r = hash01(516515 + i); return [-0.1 + 0.2 * r, -0.125 + 0.25 * r]; });

  // ---- ballistics (Functions.GetData / GetBallHeight / GetCannonBallSpeedMultiplier)
  function shotData(maxDist, aimY, curveMul = 1, ammoDistFactor = 1) {
    const d = maxDist - 3, y = aimY - 0.1;
    const val = Math.pow(Math.max(0, (0.6 + y) * 2), 5);
    let dist = Math.max(20, d * 1.25 * Math.min(0.8, val));
    let h = (1 + Math.min(6, Math.max(0, (0.1 + y * 0.6) * 80))) * (dist / Math.max(100, d)) * curveMul;
    h = Math.max(0.2, h); dist = Math.min(dist, maxDist);
    return { dist: dist * ammoDistFactor, height: h };
  }
  function ballHeight(t, shot, y0) { const amount = Math.min(1, shot.dist / 35); const arc = (4 * t - 4 * t * t) * (0.5 + shot.height); const low = y0 - 25 * t / shot.dist; return low + (y0 + arc - low) * amount; }
  function speedMul(t, far) { const k = far / 140; return ((1 - t) * (1 - t) * 0.2 + 0.9) * k + (1 - k) * 0.9; }
  function scatterFactor(base, scatter, maxDist, ports, o = {}) {
    let f = base * (o.worse ? 1.4 : 1); const p = Math.max(0, Math.min(1, Math.floor(ports / 50)));
    f += scatter / maxDist * Math.PI * (1 - (o.reduce || 0)) * (0.6 + 0.6 * p);
    if (o.additional) f = Math.max(f, 0.25 + 0.15 * p); if (o.less) f *= 0.6; if (o.single) f *= 0.2; return f;
  }
  function gunDispersion(gun, factor, shot, maxDist, along = 0) {
    const [rx, ry] = SPREAD[gun % 128]; const k = Math.max(0, Math.min(1, (ry + 0.125) / 0.25)); const n2 = (-0.13 + 0.19 * k) * factor;
    return { yaw: rx * factor + 0.7 * along / maxDist, pitch: ry * factor, dist: shot.dist * (1 + 120 * n2 / (20 + maxDist)), height: shot.height * (1 + n2) };
  }
  function convergence(elapsed, convTime, ports, bonus = 0) {
    if (convTime <= 0) return 0; const prec = 0.85 - Math.min(70, ports) * 0.005; const f = 0.85 / prec / (1 + bonus);
    return 1 - Math.max(0, Math.min(1, elapsed / Math.max(0.001, convTime * f)));
  }

  // ---- sailing (ShipPhysics.ComputeWindEffectivity)
  const UNIQUE_IDS = new Set([13, 25, 41, 54, 56, 5, 63]);
  function windingDot(deg) { const t = deg * Math.PI / 180, x = Math.cos(t) + 0.75, y = Math.sin(t); return x / Math.hypot(x, y); }
  const a18 = d => (d * 0.5 + 0.5) * 1.8, NREG = a18(windingDot(180 - 40.95)), NUNI = a18(windingDot(180 - 40.4));
  function hull(weightTons, staticId) { let inert = 2 - Math.max(0, Math.min(1, (weightTons * 1000 - 30000) / 50000)); if (staticId === 56) inert = 1.6; return { inertion: inert, hardness: 2 - inert }; }
  function windEff(theta, o = {}) {
    let th = Math.abs(((theta + 180) % 360 + 360) % 360 - 180), eth = th;
    if (o.unique && th > 90 && o.tack === 'left') eth = Math.max(0, th - 0.3 * 180 / Math.PI);
    const dot = windingDot(eth); if (o.ignore) return 1;
    const band = o.unique ? 0.00445 : 0.01, fine = Math.max(0, dot - (1 - band)) / band;
    const n3 = a18(dot) / (o.unique ? NUNI : NREG), h = o.hardness || 0;
    const val = n3 + ((0.15 + 0.85 * n3) - n3) * h; const ffr = o.forewindReduce || 0;
    return Math.min(1, val) * ((1 - 0.3 * fine) + (0.3 * fine) * ffr);
  }

  // ---- damage application (Ship.MakeDamage / ShipFirstHp)
  function newShipState(maxHp, sails) { const n = Math.max(1, sails || 1); return { max: maxHp, hp: maxHp, sinkMs: 0, off: 0, destroyed: false, byFlood: false, sail: Array(n).fill(1), w: Array(n).fill(1 / n), fire: false, fireMs: 0, fireType: 0, mend: 0, micro: [], log: [] }; }
  function flood(s) { return s.byFlood ? 1 : (s.sinkMs - s.off) / 13000; }
  function applyHit(s, hit) {
    if (s.destroyed) return { ignored: true };
    const ev = []; const before = s.hp;
    if (s.sinkMs === 0) { const rm = Math.min(hit.damage || 0, s.hp); s.hp = (s.hp - rm < 0.5) ? 0 : s.hp - rm; if (s.hp <= 0) { s.sinkMs = 0.01; s.hp = 1; ev.push('starts sinking'); } }
    if (flood(s) > 0) {
      if (['mortar', 'keg'].includes(hit.source) || (hit.source === 'fire' && s.fire) || hit.stern) { s.destroyed = true; s.hp = 0; ev.push('sunk'); }
      else if (hit.source === 'ram' && hit.fromShip) { const nw = Math.min(12999, s.sinkMs + 800); s.off = nw - s.sinkMs; s.sinkMs = nw; ev.push('ram +0.8 s'); }
    }
    if (hit.sail != null && hit.sailDamage) { const k = Math.min(s.sail.length - 1, hit.sail); s.sail[k] = Math.max(0, s.sail[k] - hit.sailDamage); ev.push('sail ' + (k + 1)); }
    if (hit.micro) { s.micro.push({ left: 6 + 4 * hash01(s.micro.length + 7 * s.log.length) }); ev.push('micro-fire'); }
    if (hit.bigFire) { s.fire = true; s.fireMs = Math.max(1, s.fireMs); s.fireType = hit.fireType ?? 2; ev.push('large fire'); }
    s.log.push({ before, after: s.hp, ev }); return { before, after: s.hp, ev };
  }
  function tick(s, dt, o = {}) {
    if (s.destroyed) return;
    if (s.sinkMs > 0) { s.off = Math.max(0, s.off - dt * 2000); s.sinkMs += dt * 1000 * (o.inertion || 1); if (s.sinkMs > 13000) { s.sinkMs = 13000; s.byFlood = true; s.destroyed = true; s.hp = 0; } return; }
    s.micro = s.micro.filter(m => (m.left -= dt / Math.max(0.001, 1 - (o.microFightBonus || 0))) > 0);
    const microDmg = 4 * s.micro.length * dt;
    if (microDmg) applyHit(s, { source: 'fire', damage: microDmg });
    if (s.fireMs > 0) { s.fireMs += dt * 1000; s.mend = Math.max(0, s.mend - dt * 0.1); if (s.fireType === 2 && s.fireMs > 12000) { s.fireMs = 0; s.mend = 0; s.fire = false; } }
  }
  function sailsHp(s) { return s.sail.reduce((a, v, i) => a + v * s.w[i], 0); }

  // ---- damage per ball: fitted model when available, else an uncalibrated proxy
  function ballDamage(model, ctx) {
    if (model && model.terms) {
      const f = { log_poundage: Math.log(ctx.poundage), log_ammo_factor: Math.log(ctx.ammoFactor || 1),
        log_pen_ratio: Math.log((ctx.pen + (ctx.ammoPen || 0)) / (ctx.armor / Math.max(0.05, Math.cos(Math.min(85, Math.abs(ctx.angle || 0)) * Math.PI / 180)))),
        range_fraction: ctx.distance / ctx.maxRange, stern: ctx.zone === 'stern' ? 1 : 0, bow: ctx.zone === 'bow' ? 1 : 0, through_sail: ctx.throughSail ? 1 : 0 };
      let t = model.terms.intercept; for (const k in model.terms) if (k !== 'intercept') t += model.terms[k] * (f[k] ?? 0);
      return { damage: Math.exp(t), calibrated: true };
    }
    return { damage: ctx.poundage * (ctx.ammoFactor || 1) * 1.5, calibrated: false };
  }

  // ---- boarding (BoardingCombatInstance / BoardingCombatVisualGroup)
  function makeGroups(crew, types, places) {
    const size = 16 + Math.floor(places / 15), groups = []; let cur = {}, n = 0;
    const close = () => { if (!n) return; const idx = groups.length; let dmg = 0, hp = 0; for (const u in cur) { dmg += types[u].damage * cur[u]; hp += types[u].health * cur[u]; }
      groups.push({ i: idx, units: { ...cur }, dmg, hp, hp0: hp, n0: n, timer: 3 * (1 + 0.1 * (hash01(idx) - 0.5)) }); cur = {}; n = 0; };
    for (const u of Object.keys(crew).sort((a, b) => a - b)) { let c = crew[u]; while (c > 0) { const take = Math.min(size - n, c); cur[u] = (cur[u] || 0) + take; n += take; c -= take; if (n >= size) close(); } close(); }
    return { groups, size };
  }
  function board(A, B, o = {}) {
    const dur = o.duration || 30, dt = 0.05, log = []; let t = 0;
    const hp = s => s.groups.reduce((a, g) => a + g.hp, 0), alive = s => s.groups.reduce((a, g) => a + (g.hp > 0 ? Object.values(g.units).reduce((x, y) => x + y, 0) : 0), 0);
    for (const [s, e] of [[A, B], [B, A]]) if (!s.targets || !s.targets.length) s.targets = s.noTarget ? [e.groups[Math.floor(hash01(7) * e.groups.length)]?.i ?? 0] : e.groups.slice(0, 3).map(g => g.i);
    while (t < dur && hp(A) > 0 && hp(B) > 0) {
      t += dt;
      for (const [att, def] of [[A, B], [B, A]]) {
        att.targets = att.targets.filter(i => def.groups[i] && def.groups[i].hp > 0); if (!att.targets.length) att.targets = def.groups.filter(g => g.hp > 0).slice(0, 3).map(g => g.i);
        let dealt = 0, killed = 0;
        for (const g of att.groups) { if (g.hp <= 0) continue; g.timer -= dt; if (g.timer > 0) continue; g.timer += 3;
          const amount = g.dmg * Math.pow(g.hp / g.hp0, 0.7) * (att.protect?.has(g.i) ? 0.2 : 1); const live = att.targets.map(i => def.groups[i]).filter(x => x && x.hp > 0); if (!live.length) continue;
          for (const tg of live) { let d = amount / live.length; if (def.protect?.has(tg.i)) d *= 0.2; dealt += d; const before = Object.values(tg.units).reduce((x, y) => x + y, 0);
            tg.hp -= d; if (tg.hp <= 0) { tg.hp = 0; for (const k in tg.units) tg.units[k] = 0; killed += before; continue; }
            let cut = tg.n0 * d / tg.hp0, rm = Math.floor(cut) + (hash01(Math.floor(tg.hp * 1000) + tg.i) < cut - Math.floor(cut) ? 1 : 0);
            for (const k of Object.keys(tg.units).sort((a, b) => tg.units[b] - tg.units[a])) { const take = Math.min(tg.units[k], rm); tg.units[k] -= take; rm -= take; killed += take; if (rm <= 0) break; }
            if (Object.values(tg.units).every(v => v === 0)) { tg.units[Object.keys(tg.units)[0]] = 1; killed--; } } }
        if (dealt) log.push({ t: +t.toFixed(2), side: att.name, dealt, killed, a: hp(A), b: hp(B) });
      }
    }
    const sa = hp(A) * (1 + (A.weightBonus || 0)), sb = hp(B) * (1 + (B.weightBonus || 0));
    let winner = 'undecided'; if (hp(B) <= 0 && hp(A) > 0) winner = A.name; else if (hp(A) <= 0 && hp(B) > 0) winner = B.name; else if (sb > 0 && sa / sb >= 1.5) winner = A.name; else if (sa > 0 && sb / sa >= 1.5) winner = B.name;
    return { winner, seconds: t, log, hpA: hp(A), hpB: hp(B), unitsA: alive(A), unitsB: alive(B) };
  }

  // ---- fire
  const fire = {
    canStart(micro, hp, max) { const need = 1 + Math.round(max / 1000); if (micro < need) return [false, 'needs ' + need + ' micro-fires']; if (hp > max * 0.95 || hp < max * 0.05) return [false, 'HP must be 5–95%']; return [true, 'can ignite']; },
    flare(sec, type, mend = 0) { const a = sec * 1000; if (!a) return 0; if (type === 2) { const x = a / 12000; return x * (1 - x) * 2.4; } if (type === 0) return Math.min(1, a / 4000); return Math.min(Math.max(0.01, 1 - mend), Math.pow(a / 12000, 1.7) * 0.7 + (a < 12000 ? 0 : (a - 12000) / 2000)); },
    areaExtend(r) { return Math.min(14.5, r + 1.3 * Math.pow((14.5 - r) / 14.5, 1.4)); }
  };

  root.WoSBSim = { hash01, SPREAD, shotData, ballHeight, speedMul, scatterFactor, gunDispersion, convergence, UNIQUE_IDS, windingDot, windEff, hull,
    newShipState, applyHit, tick, flood, sailsHp, ballDamage, makeGroups, board, fire };
})(typeof window !== 'undefined' ? window : globalThis);
