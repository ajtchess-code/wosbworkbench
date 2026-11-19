import { DatabaseSync } from 'node:sqlite';
import assert from 'node:assert/strict';
const W = (await import(process.argv[2])).default;
// D1-like wrapper over node:sqlite
const sq = new DatabaseSync(':memory:');
const D1 = { prepare(sql) { const st = { args: [], bind(...a) { st.args = a; return st; },
  run: async () => { sq.prepare(sql).run(...st.args); return { success: true }; },
  all: async () => ({ results: sq.prepare(sql).all(...st.args) }),
  first: async () => sq.prepare(sql).get(...st.args) ?? null }; return st; } };
const env = { DB: D1, DISCORD_CLIENT_ID: 'cid', DISCORD_CLIENT_SECRET: 'csec', SESSION_SECRET: 'x'.repeat(40), ADMIN_DISCORD_IDS: '111, 222',
  TURNSTILE_SITE_KEY: 'site', TURNSTILE_SECRET: 'tsec', ASSETS: { fetch: async (r) => new Response('asset:' + new URL(r.url).pathname) } };
// fake Discord + Turnstile
globalThis.fetch = async (u, o = {}) => {
  u = String(u);
  if (u.includes('oauth2/token')) { assert.match(String(o.body), /client_secret=csec/); return new Response(JSON.stringify({ access_token: 'tok' })); }
  if (u.includes('users/@me')) return new Response(JSON.stringify({ id: o.headers.authorization === 'Bearer tok' ? '111' : '0', username: 'cap', global_name: 'Captain <b>', avatar: 'abc' }));
  if (u.includes('turnstile')) return new Response(JSON.stringify({ success: String(o.body).includes('response=good') }));
  throw new Error('unexpected fetch ' + u);
};
const O = 'https://wosbwiki.org';
const call = (path, init = {}) => W.fetch(new Request(O + path, init), env);
const jget = async (r) => [r.status, await r.json()];

// login -> discord
let r = await call('/api/auth/login?return=/ship/bellona.html');
assert.equal(r.status, 302); const loc = new URL(r.headers.get('location'));
assert.equal(loc.host, 'discord.com'); assert.equal(loc.searchParams.get('scope'), 'identify');
assert.equal(loc.searchParams.get('redirect_uri'), O + '/api/auth/callback');
const stateCookie = r.headers.get('set-cookie').split(';')[0]; const state = loc.searchParams.get('state');
// open redirect blocked
r = await call('/api/auth/login?return=//evil.com'); const sc = r.headers.get('set-cookie'); assert.ok(sc.includes('__Host-wosb_state='));
// callback with wrong state
r = await call('/api/auth/callback?code=c&state=nope', { headers: { cookie: stateCookie } }); assert.equal(r.status, 400);
// good callback
r = await call(`/api/auth/callback?code=c&state=${state}`, { headers: { cookie: stateCookie } });
assert.equal(r.status, 302); assert.equal(r.headers.get('location'), '/ship/bellona.html');
const setc = r.headers.getSetCookie(); const sess = setc.find((c) => c.startsWith('__Host-wosb_session=')).split(';')[0];
assert.ok(setc.some((c) => c.includes('HttpOnly') && c.includes('Secure')));
// me
let [st, me] = await jget(await call('/api/me', { headers: { cookie: sess } }));
assert.equal(me.user.id, '111'); assert.equal(me.admin, true); assert.equal(me.turnstile, 'site');
[st, me] = await jget(await call('/api/me')); assert.equal(me.user, null);
// tampered cookie
[st, me] = await jget(await call('/api/me', { headers: { cookie: sess.slice(0, -2) + 'xx' } })); assert.equal(me.user, null);
// anonymous report needs turnstile
const post = (b, h = {}) => call('/api/reports', { method: 'POST', headers: { 'content-type': 'application/json', origin: O, 'cf-connecting-ip': '1.2.3.4', ...h }, body: JSON.stringify(b) });
[st] = await jget(await post({ message: 'The reload is wrong', page: '/cannon/x.html', kind: 'wrong' })); assert.equal(st, 403);
[st] = await jget(await post({ message: 'The reload is wrong', page: '/cannon/x.html', kind: 'wrong', turnstile: 'good' })); assert.equal(st, 200);
// cross-origin blocked
[st] = await jget(await post({ message: 'hello there' }, { origin: 'https://evil.com', cookie: sess })); assert.equal(st, 403);
// logged-in report, no turnstile
[st] = await jget(await post({ message: 'Missing the 3D model', page: '/ship/a.html', title: 'A', kind: 'missing', contact: 'cap#1' }, { cookie: sess })); assert.equal(st, 200);
// too short
[st] = await jget(await post({ message: 'x' }, { cookie: sess })); assert.equal(st, 400);
// anonymous rate limit (4/hour per IP)
for (let i = 0; i < 3; i++) await post({ message: 'spam message ' + i, turnstile: 'good' }, { 'cf-connecting-ip': '9.9.9.9' });
[st] = await jget(await post({ message: 'spam 4', turnstile: 'good' }, { 'cf-connecting-ip': '9.9.9.9' })); assert.equal(st, 200);
[st] = await jget(await post({ message: 'spam 5', turnstile: 'good' }, { 'cf-connecting-ip': '9.9.9.9' })); assert.equal(st, 429);
// admin list: anon 401, admin ok
[st] = await jget(await call('/api/admin/reports')); assert.equal(st, 401);
let list; [st, list] = await jget(await call('/api/admin/reports?status=all', { headers: { cookie: sess } }));
assert.equal(st, 200); assert.equal(list.reports.length, 6); assert.equal(list.counts.open, 6);
const mine = list.reports.find((x) => x.kind === 'missing'); assert.equal(mine.user_name, 'Captain <b>'); assert.equal(mine.contact, 'cap#1');
assert.ok(!('ip_hash' in mine), 'ip hash never leaves the database');
// search
[st, list] = await jget(await call('/api/admin/reports?status=all&q=reload', { headers: { cookie: sess } })); assert.equal(list.reports.length, 1);
// resolve + note
const upd = (b) => call('/api/admin/report', { method: 'POST', headers: { 'content-type': 'application/json', origin: O, cookie: sess }, body: JSON.stringify(b) });
[st] = await jget(await upd({ id: mine.id, status: 'resolved', note: 'Added' })); assert.equal(st, 200);
[st, list] = await jget(await call('/api/admin/reports?status=resolved', { headers: { cookie: sess } }));
assert.equal(list.reports[0].note, 'Added'); assert.equal(list.reports[0].handled_by, 'Captain <b>');
[st] = await jget(await upd({ id: mine.id, delete: true })); assert.equal(st, 200);
// csv
r = await call('/api/admin/reports.csv?status=all', { headers: { cookie: sess } }); const csv = await r.text();
assert.match(r.headers.get('content-type'), /text\/csv/); assert.equal(csv.split('\r\n').length, 6);
// csv formula injection guarded
await post({ message: '=HYPERLINK("x")', turnstile: 'good' }, { 'cf-connecting-ip': '5.5.5.5' });
assert.match(await (await call('/api/admin/reports.csv?status=all', { headers: { cookie: sess } })).text(), /"'=HYPERLINK/);
// non-admin
env.ADMIN_DISCORD_IDS = '999';
[st] = await jget(await call('/api/admin/reports', { headers: { cookie: sess } })); assert.equal(st, 403);
// logout
r = await call('/api/auth/logout', { method: 'POST', headers: { origin: O } }); assert.match(r.headers.get('set-cookie'), /Max-Age=0/);
// pack guard + passthrough
assert.equal((await call('/pack/index.js')).status, 403);
assert.equal(await (await call('/pack/index.js', { headers: { 'sec-fetch-site': 'same-origin' } })).text(), 'asset:/pack/index.js');
assert.equal((await call('/api/nope')).status, 404);
// not configured
const bare = { ASSETS: env.ASSETS };
assert.equal((await W.fetch(new Request(O + '/api/auth/login'), bare)).status, 503);
const m2 = await (await W.fetch(new Request(O + '/api/me'), bare)).json(); assert.equal(m2.login, false); assert.equal(m2.reports, false);
console.log('worker tests passed');
