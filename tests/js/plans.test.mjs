import assert from 'node:assert/strict';
const W = (await import(process.argv[2])).default;
// tiny stand-in for D1: just enough for the plans table
const rows = new Map(); let now = Date.now();
const DB = { prepare(sql) { let args = []; const st = {
  bind(...a) { args = a; return st; },
  async run() {
    if (/^DELETE FROM plans/.test(sql)) for (const [k, r] of rows) if (now - r.used > 30 * 864e5) rows.delete(k);
    if (/^INSERT INTO plans/.test(sql)) rows.set(args[0], { data: args[1], used: now });
    if (/^UPDATE plans/.test(sql)) rows.get(args[0]).used = now;
    return {};
  },
  async first() { const r = rows.get(args[0]); return r && now - r.used <= 30 * 864e5 ? { data: r.data } : null; } }; return st; } };
const env = { DB };
const post = (body, origin = 'https://wosbwiki.org') => W.fetch(new Request('https://wosbwiki.org/api/plans', { method: 'POST', headers: { origin, 'content-type': 'application/json' }, body }), env, {});
let r = await post(JSON.stringify({ plan: { targets: [{ k: 's:2', q: 1 }] } }));
assert.equal(r.status, 200); const { id } = await r.json(); assert.match(id, /^[a-z0-9]{6,16}$/);
r = await W.fetch(new Request('https://wosbwiki.org/api/plans/' + id), env, {}); assert.equal(r.status, 200);
assert.deepEqual((await r.json()).plan.targets[0], { k: 's:2', q: 1 });
assert.equal((await post('{"plan":{}}', 'https://evil.example')).status, 403);
assert.equal((await post('x'.repeat(30000))).status, 413);
now += 29 * 864e5; assert.equal((await W.fetch(new Request('https://wosbwiki.org/api/plans/' + id), env, {})).status, 200);   // opening it keeps it
now += 31 * 864e5; assert.equal((await W.fetch(new Request('https://wosbwiki.org/api/plans/' + id), env, {})).status, 404);   // 30 days unused: gone
assert.equal((await W.fetch(new Request('https://wosbwiki.org/api/plans/abc'), {}, {})).status, 503);
console.log('plans tests passed');
