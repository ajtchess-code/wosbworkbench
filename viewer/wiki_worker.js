// WoSB Wiki on Cloudflare Pages (advanced mode). Runs only for /api/* and /pack/* (see _routes.json);
// every other page is plain static hosting.
//
//   /pack/*                      3D model pack, served only to the wiki's own pages
//   /api/auth/login|callback     "Log in with Discord" (OAuth2, scope identify)
//   /api/auth/logout             end the session
//   /api/me                      who is logged in, whether they are an admin, Turnstile site key
//   /api/reports           POST  a "Tell us" / "Report a problem" message (login optional; Turnstile for anonymous)
//   /api/admin/reports     GET   list reports (admins only)   ?status=open|resolved|wontfix|all  &q=text
//   /api/admin/reports.csv GET   the same as CSV
//   /api/admin/report      POST  {id, status?, note?, delete?}
//
// Settings (Pages project → Settings → Variables and Secrets; D1 under Bindings):
//   DB                     D1 database binding
//   DISCORD_CLIENT_ID      Discord application client ID
//   DISCORD_CLIENT_SECRET  (secret) Discord application client secret
//   SESSION_SECRET         (secret) long random text that signs login cookies
//   ADMIN_DISCORD_IDS      Discord user IDs allowed into /admin/, separated by commas
//   TURNSTILE_SITE_KEY     Cloudflare Turnstile site key (bot check for anonymous reports)
//   TURNSTILE_SECRET       (secret) Turnstile secret key

const SESSION = '__Host-wosb_session';
const STATE = '__Host-wosb_state';
const SESSION_DAYS = 30;
const KINDS = ['wrong', 'missing', 'suggestion', 'other'];
const STATUSES = ['open', 'resolved', 'wontfix'];
const LIMIT_USER = 10, LIMIT_ANON = 4;       // reports per hour
const enc = new TextEncoder();

// ---------------------------------------------------------------- helpers
const b64u = (bytes) => { let s = ''; const b = new Uint8Array(bytes); for (let i = 0; i < b.length; i++) s += String.fromCharCode(b[i]); return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, ''); };
const unb64u = (s) => { s = s.replace(/-/g, '+').replace(/_/g, '/'); while (s.length % 4) s += '='; const bin = atob(s); const out = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i); return out; };
const hex = (buf) => [...new Uint8Array(buf)].map((x) => x.toString(16).padStart(2, '0')).join('');
async function hmac(secret, data) {
  const key = await crypto.subtle.importKey('raw', enc.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  return b64u(await crypto.subtle.sign('HMAC', key, enc.encode(data)));
}
function safeEqual(a, b) { if (a.length !== b.length) return false; let r = 0; for (let i = 0; i < a.length; i++) r |= a.charCodeAt(i) ^ b.charCodeAt(i); return r === 0; }
function cookies(req) { const out = {}; for (const part of (req.headers.get('Cookie') || '').split(';')) { const i = part.indexOf('='); if (i > 0) out[part.slice(0, i).trim()] = part.slice(i + 1).trim(); } return out; }
const cookie = (name, value, maxAge) => `${name}=${value}; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=${maxAge}`;
const BASE_HEADERS = { 'cache-control': 'no-store', 'x-content-type-options': 'nosniff', 'x-frame-options': 'DENY', 'referrer-policy': 'strict-origin-when-cross-origin', 'x-robots-tag': 'noindex, nofollow' };
function json(data, status = 200, extra = {}) { return new Response(JSON.stringify(data), { status, headers: { ...BASE_HEADERS, 'content-type': 'application/json; charset=utf-8', ...extra } }); }
const fail = (msg, status = 400) => json({ error: msg }, status);
function redirect(location, extraHeaders = []) { const h = new Headers({ ...BASE_HEADERS, location }); for (const [k, v] of extraHeaders) h.append(k, v); return new Response(null, { status: 302, headers: h }); }
const safeReturn = (p) => (typeof p === 'string' && /^\/(?!\/)[^\s\\]*$/.test(p) && p.length < 300 ? p : '/');
const admins = (env) => new Set(String(env.ADMIN_DISCORD_IDS || '').split(/[\s,;]+/).filter(Boolean));
const clip = (v, n) => String(v == null ? '' : v).replace(/\u0000/g, '').trim().slice(0, n);

async function readSession(req, env) {
  const raw = cookies(req)[SESSION]; if (!raw || !env.SESSION_SECRET) return null;
  const [body, sig] = raw.split('.'); if (!body || !sig) return null;
  if (!safeEqual(sig, await hmac(env.SESSION_SECRET, body))) return null;
  try { const s = JSON.parse(new TextDecoder().decode(unb64u(body))); return s.exp > Date.now() / 1000 ? s : null; } catch (e) { return null; }
}
async function makeSession(env, user) {
  const body = b64u(enc.encode(JSON.stringify({ ...user, exp: Math.floor(Date.now() / 1000) + SESSION_DAYS * 86400 })));
  return `${body}.${await hmac(env.SESSION_SECRET, body)}`;
}
function sameOrigin(req, url) { const o = req.headers.get('Origin'); return !o || o === url.origin; }

let schemaReady = false;
async function db(env) {
  if (!env.DB) return null;
  if (!schemaReady) {
    await env.DB.prepare(`CREATE TABLE IF NOT EXISTS reports (id INTEGER PRIMARY KEY AUTOINCREMENT, created TEXT NOT NULL, page TEXT, page_title TEXT, kind TEXT,
      message TEXT NOT NULL, contact TEXT, user_id TEXT, user_name TEXT, ip_hash TEXT, status TEXT NOT NULL DEFAULT 'open', note TEXT, updated TEXT, handled_by TEXT)`).run();
    await env.DB.prepare('CREATE INDEX IF NOT EXISTS reports_status ON reports(status, created)').run();
    schemaReady = true;
  }
  return env.DB;
}
const nowIso = () => new Date().toISOString().replace(/\.\d+Z$/, 'Z');

// ---------------------------------------------------------------- handlers
async function login(req, env, url) {
  if (!env.DISCORD_CLIENT_ID || !env.DISCORD_CLIENT_SECRET || !env.SESSION_SECRET) return fail('Discord login is not set up on this site yet.', 503);
  const state = b64u(crypto.getRandomValues(new Uint8Array(18)));
  const ret = safeReturn(url.searchParams.get('return') || '/');
  const auth = new URL('https://discord.com/oauth2/authorize');
  auth.search = new URLSearchParams({ response_type: 'code', client_id: env.DISCORD_CLIENT_ID, scope: 'identify', redirect_uri: `${url.origin}/api/auth/callback`, state, prompt: 'none' }).toString();
  return redirect(auth.toString(), [['set-cookie', cookie(STATE, `${state}~${b64u(enc.encode(ret))}`, 600)]]);
}

async function callback(req, env, url) {
  const [state, retB64] = (cookies(req)[STATE] || '').split('~');
  const clear = ['set-cookie', cookie(STATE, '', 0)];
  let ret = '/'; try { ret = safeReturn(new TextDecoder().decode(unb64u(retB64 || ''))); } catch (e) { /* default */ }
  if (url.searchParams.get('error')) return redirect(ret, [clear]);                    // the reader pressed Cancel
  if (!state || !safeEqual(state, url.searchParams.get('state') || '')) return fail('Login expired. Please try again.', 400);
  const tok = await fetch('https://discord.com/api/oauth2/token', { method: 'POST', headers: { 'content-type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ grant_type: 'authorization_code', code: url.searchParams.get('code') || '', redirect_uri: `${url.origin}/api/auth/callback`,
      client_id: env.DISCORD_CLIENT_ID, client_secret: env.DISCORD_CLIENT_SECRET }) });
  if (!tok.ok) return fail('Discord did not accept the login. Please try again.', 502);
  const { access_token } = await tok.json();
  const me = await fetch('https://discord.com/api/users/@me', { headers: { authorization: `Bearer ${access_token}` } });
  if (!me.ok) return fail('Could not read your Discord account.', 502);
  const u = await me.json();
  const user = { id: String(u.id), name: clip(u.global_name || u.username, 64), avatar: u.avatar ? `https://cdn.discordapp.com/avatars/${u.id}/${u.avatar}.png?size=64` : '' };
  return redirect(ret, [clear, ['set-cookie', cookie(SESSION, await makeSession(env, user), SESSION_DAYS * 86400)]]);
}

async function me(req, env) {
  const s = await readSession(req, env);
  return json({ user: s ? { id: s.id, name: s.name, avatar: s.avatar } : null, admin: !!(s && admins(env).has(s.id)),
    login: !!(env.DISCORD_CLIENT_ID && env.DISCORD_CLIENT_SECRET && env.SESSION_SECRET), reports: !!env.DB, turnstile: env.TURNSTILE_SITE_KEY || '' });
}

async function turnstileOk(env, token, ip) {
  if (!env.TURNSTILE_SECRET) return null;          // not configured
  if (!token) return false;
  const r = await fetch('https://challenges.cloudflare.com/turnstile/v0/siteverify', { method: 'POST', body: new URLSearchParams({ secret: env.TURNSTILE_SECRET, response: token, remoteip: ip || '' }) });
  return r.ok && (await r.json()).success === true;
}

// ---- shared planner links (crafting calculator and other planners): kept while used, removed after 30 days unused
async function plansTable(env) {
  await env.DB.prepare('CREATE TABLE IF NOT EXISTS plans (id TEXT PRIMARY KEY, data TEXT NOT NULL, created TEXT NOT NULL, used TEXT NOT NULL)').run();
}
async function savePlan(req, env, url) {
  if (!env.DB) return fail('Share links need the site database.', 503);
  if (!sameOrigin(req, url)) return fail('Bad origin.', 403);
  const text = await req.text();
  if (text.length > 20000) return fail('That plan is too large to share.', 413);
  let body; try { body = JSON.parse(text); } catch (e) { return fail('Bad plan.', 400); }
  if (!body || typeof body.plan !== 'object') return fail('Bad plan.', 400);
  await plansTable(env);
  await env.DB.prepare("DELETE FROM plans WHERE used < datetime('now', '-30 days')").run();
  const bytes = new Uint8Array(6); crypto.getRandomValues(bytes);
  const id = Array.from(bytes, (x) => 'abcdefghijkmnopqrstuvwxyz23456789'[x % 33]).join('') + Date.now().toString(36).slice(-3);
  await env.DB.prepare("INSERT INTO plans (id, data, created, used) VALUES (?, ?, datetime('now'), datetime('now'))").bind(id, JSON.stringify(body.plan)).run();
  return json({ id });
}
async function getPlan(env, id) {
  if (!env.DB) return fail('Share links need the site database.', 503);
  if (!/^[a-z0-9]{6,16}$/.test(id)) return fail('Not found.', 404);
  await plansTable(env);
  const row = await env.DB.prepare("SELECT data FROM plans WHERE id = ? AND used >= datetime('now', '-30 days')").bind(id).first();
  if (!row) return fail('This link has expired or does not exist.', 404);
  await env.DB.prepare("UPDATE plans SET used = datetime('now') WHERE id = ?").bind(id).run();
  return json({ plan: JSON.parse(row.data) });
}

async function submit(req, env, url) {
  if (!sameOrigin(req, url)) return fail('Bad origin.', 403);
  const D = await db(env); if (!D) return fail('Reports are not set up on this site yet.', 503);
  let b; try { b = await req.json(); } catch (e) { return fail('Bad request.'); }
  const message = clip(b.message, 4000);
  if (message.length < 5) return fail('Please describe the problem in a few words.');
  const kind = KINDS.includes(b.kind) ? b.kind : 'other';
  const s = await readSession(req, env);
  const ip = req.headers.get('CF-Connecting-IP') || '';
  const ipHash = hex(await crypto.subtle.digest('SHA-256', enc.encode(`${ip}|${env.SESSION_SECRET || 'wosb'}`))).slice(0, 32);
  if (!s) {
    const ok = await turnstileOk(env, b.turnstile, ip);
    if (ok === false) return fail('Please complete the robot check, or log in with Discord.', 403);
  }
  const recent = await D.prepare("SELECT COUNT(*) AS n FROM reports WHERE (ip_hash = ?1 OR (?2 <> '' AND user_id = ?2)) AND created > ?3")
    .bind(ipHash, s ? s.id : '', new Date(Date.now() - 3600e3).toISOString()).first();
  if ((recent && recent.n) >= (s ? LIMIT_USER : LIMIT_ANON)) return fail('Thanks, we have your earlier reports. Please try again in an hour.', 429);
  await D.prepare('INSERT INTO reports (created, page, page_title, kind, message, contact, user_id, user_name, ip_hash) VALUES (?,?,?,?,?,?,?,?,?)')
    .bind(nowIso(), clip(b.page, 300), clip(b.title, 200), kind, message, clip(b.contact, 200), s ? s.id : null, s ? s.name : null, ipHash).run();
  return json({ ok: true });
}

async function requireAdmin(req, env) {
  const s = await readSession(req, env);
  if (!s) return [null, fail('Log in with Discord first.', 401)];
  if (!admins(env).has(s.id)) return [null, fail('Your Discord account is not on the admin list.', 403)];
  return [s, null];
}

async function listReports(req, env, url, csv) {
  const [, err] = await requireAdmin(req, env); if (err) return err;
  const D = await db(env); if (!D) return fail('No database is connected (binding "DB").', 503);
  const status = url.searchParams.get('status') || 'open', q = clip(url.searchParams.get('q'), 100);
  const where = [], args = [];
  if (STATUSES.includes(status)) { where.push('status = ?'); args.push(status); }
  if (q) { where.push('(message LIKE ? OR page LIKE ? OR page_title LIKE ? OR user_name LIKE ? OR contact LIKE ?)'); const like = `%${q}%`; args.push(like, like, like, like, like); }
  const sql = `SELECT id, created, page, page_title, kind, message, contact, user_id, user_name, status, note, updated, handled_by FROM reports ${where.length ? 'WHERE ' + where.join(' AND ') : ''} ORDER BY created DESC LIMIT 500`;
  const rows = (await D.prepare(sql).bind(...args).all()).results || [];
  if (csv) {
    const cols = ['id', 'created', 'status', 'kind', 'page', 'page_title', 'message', 'contact', 'user_name', 'user_id', 'note', 'handled_by', 'updated'];
    const cell = (v) => { let s = String(v == null ? '' : v); if (/^[=+\-@\t\r]/.test(s)) s = "'" + s; return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
    const text = [cols.join(','), ...rows.map((r) => cols.map((c) => cell(r[c])).join(','))].join('\r\n');
    return new Response(text, { headers: { ...BASE_HEADERS, 'content-type': 'text/csv; charset=utf-8', 'content-disposition': 'attachment; filename="wosb-wiki-reports.csv"' } });
  }
  const counts = {};
  for (const r of ((await D.prepare('SELECT status, COUNT(*) AS n FROM reports GROUP BY status').all()).results || [])) counts[r.status] = r.n;
  return json({ reports: rows, counts });
}

async function updateReport(req, env, url) {
  if (!sameOrigin(req, url)) return fail('Bad origin.', 403);
  const [s, err] = await requireAdmin(req, env); if (err) return err;
  const D = await db(env); if (!D) return fail('No database is connected (binding "DB").', 503);
  let b; try { b = await req.json(); } catch (e) { return fail('Bad request.'); }
  const id = Number(b.id); if (!Number.isInteger(id) || id <= 0) return fail('Bad report id.');
  if (b.delete) { await D.prepare('DELETE FROM reports WHERE id = ?').bind(id).run(); return json({ ok: true, deleted: id }); }
  const status = STATUSES.includes(b.status) ? b.status : null;
  await D.prepare('UPDATE reports SET status = COALESCE(?, status), note = COALESCE(?, note), updated = ?, handled_by = ? WHERE id = ?')
    .bind(status, b.note == null ? null : clip(b.note, 2000), nowIso(), s.name, id).run();
  return json({ ok: true });
}

// ---------------------------------------------------------------- 3D model pack guard
function fromOurPages(request, url) {
  const site = request.headers.get('Sec-Fetch-Site');
  if (site) return site === 'same-origin';
  const ref = request.headers.get('Referer') || '';
  try { return new URL(ref).host === url.host; } catch (e) { return false; }
}
async function pack(request, env, url) {
  if (request.method !== 'GET' && request.method !== 'HEAD') return new Response(null, { status: 405 });
  if (!fromOurPages(request, url)) {
    return new Response('The WoSB Wiki 3D model pack only loads inside the wiki itself.', { status: 403, headers: { 'content-type': 'text/plain; charset=utf-8', 'cache-control': 'no-store', 'x-robots-tag': 'noindex, nofollow' } });
  }
  const res = await env.ASSETS.fetch(request);
  const out = new Response(res.body, res);
  out.headers.set('Cross-Origin-Resource-Policy', 'same-origin');
  out.headers.set('X-Content-Type-Options', 'nosniff');
  out.headers.set('X-Robots-Tag', 'noindex, nofollow');
  out.headers.set('Cache-Control', 'private, max-age=86400');
  out.headers.set('Vary', 'Sec-Fetch-Site, Referer');
  return out;
}

// ---------------------------------------------------------------- translated pages (/es/..., /ja/..., ...)
// Pages are translated by Workers AI (binding "AI", model m2m100) the first time someone opens them. Every string is
// remembered (KV binding "TRANSLATIONS": one map per page plus one for the menus and footer shared by all pages), so a
// new publish only translates new or changed text. Finished pages are also kept in Cloudflare's cache.
const LANGS = { zh: 'Chinese', hi: 'Hindi', es: 'Spanish', ar: 'Arabic', fr: 'French', bn: 'Bengali', pt: 'Portuguese', ru: 'Russian',
  id: 'Indonesian', ur: 'Urdu', de: 'German', ja: 'Japanese', tr: 'Turkish', ko: 'Korean' };
const RTL = new Set(['ar', 'ur']);
const SKIP_TAGS = new Set(['script', 'style', 'code', 'pre', 'textarea', 'svg', 'kbd', 'samp']);
const ATTRS = /(\s(?:alt|title|placeholder|aria-label)=")([^"]*)(")/g;
const META = /(<meta\s+(?:name|property)="(?:description|og:title|og:description|twitter:title|twitter:description|og:image:alt)"\s+content=")([^"]*)(")/g;
const decode = (s) => s.replace(/&(#x[0-9a-f]+|#\d+|amp|lt|gt|quot|#39|apos|nbsp);/gi, (m, e) => ({ amp: '&', lt: '<', gt: '>', quot: '"', '#39': "'", apos: "'", nbsp: ' ' })[e.toLowerCase()]
  ?? String.fromCodePoint(e[1] === 'x' || e[1] === 'X' ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10)));
const encodeText = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const encodeAttr = (s) => encodeText(s).replace(/"/g, '&quot;');
const worth = (t) => /\p{L}{2,}/u.test(t) && t.length < 2000;
async function hashKey(t) { return hex(await crypto.subtle.digest('SHA-1', enc.encode(t))).slice(0, 20); }

/** Split a page into text pieces worth translating. Returns { parts, texts } where texts[i] = { text, shared }. */
function tokenize(html) {
  const parts = html.split(/(<script\b[\s\S]*?<\/script>|<style\b[\s\S]*?<\/style>|<!--[\s\S]*?-->|<[^>]+>)/i);
  const stack = []; let skip = 0, shared = 0;
  const out = [];
  for (let i = 0; i < parts.length; i++) {
    const s = parts[i];
    if (i % 2 === 1) {                               // a tag
      const m = /^<(\/?)([a-z0-9]+)/i.exec(s); if (!m) continue;
      const tag = m[2].toLowerCase(), close = m[1] === '/', selfClose = /\/>$/.test(s) || ['br', 'img', 'input', 'meta', 'link', 'hr', 'source', 'wbr'].includes(tag);
      if (close) { const top = stack.pop(); if (top) { if (top.skip) skip--; if (top.shared) shared--; } continue; }
      if (selfClose) { if (!skip) out.push({ i, attr: true }); continue; }
      const noTr = SKIP_TAGS.has(tag) || /\btranslate="no"|class="[^"]*\bnotranslate\b/.test(s);
      const sh = /\bid="(side|top|foot)"/.test(s);
      stack.push({ skip: noTr, shared: sh }); if (noTr) skip++; if (sh) shared++;
      if (!skip) out.push({ i, attr: true });
      continue;
    }
    const t = decode(s).trim();
    // menus, header, footer and short labels (headings, table headers, buttons) are shared by many pages
    if (!skip && t && worth(t)) out.push({ i, text: true, shared: shared > 0 || t.split(/\s+/).length <= 4 });
  }
  return { parts, items: out };
}

async function translateAll(env, lang, strings, budget) {
  const done = {};
  let n = 0;
  const queue = [...strings];
  async function one(t) {
    try {
      const r = await env.AI.run('@cf/meta/m2m100-1.2b', { text: t, source_lang: 'en', target_lang: lang });
      const tr = (r && (r.translated_text || r.response)) || '';
      if (tr && tr.trim()) done[t] = tr.trim();
    } catch (e) { /* leave it in English for now */ }
  }
  while (queue.length && n < budget) {
    const batch = queue.splice(0, Math.min(8, budget - n)); n += batch.length;
    await Promise.all(batch.map(one));
  }
  return { done, left: queue.length };
}

async function loadMap(env, key) { if (!env.TRANSLATIONS) return {}; try { return (await env.TRANSLATIONS.get(key, 'json')) || {}; } catch (e) { return {}; } }
async function saveMap(env, key, map) { if (env.TRANSLATIONS) { try { await env.TRANSLATIONS.put(key, JSON.stringify(map)); } catch (e) { /* daily write limit: try again next visit */ } } }

async function translatePage(html, lang, env, path) {
  const { parts, items } = tokenize(html);
  const want = new Map();                          // english -> shared?
  const piece = (s) => { const t = decode(s); const lead = t.match(/^\s*/)[0], tail = t.match(/\s*$/)[0]; return [lead, t.trim(), tail]; };
  for (const it of items) {
    if (it.text) { const [, t] = piece(parts[it.i]); want.set(t, (want.get(t) || false) || it.shared); }
    else for (const m of parts[it.i].matchAll(ATTRS)) { const t = decode(m[2]).trim(); if (worth(t)) want.set(t, want.get(t) || t.split(/\s+/).length <= 4); }
  }
  const head = html.slice(0, html.indexOf('<body') > 0 ? html.indexOf('<body') : 0);
  for (const m of head.matchAll(META)) { const t = decode(m[2]).trim(); if (worth(t)) want.set(t, false); }
  const common = await loadMap(env, `${lang}:_common`), page = await loadMap(env, `${lang}:${path}`);
  const known = async (t) => common[await hashKey(t)] ?? page[await hashKey(t)];
  const missing = [];
  for (const t of want.keys()) if ((await known(t)) == null) missing.push(t);
  const budget = Number(env.TRANSLATE_BUDGET || 150);
  const { done, left } = env.AI ? await translateAll(env, lang, missing, budget) : { done: {}, left: missing.length };
  let commonDirty = false, pageDirty = false;
  for (const [t, tr] of Object.entries(done)) {
    const k = await hashKey(t);
    if (want.get(t)) { common[k] = tr; commonDirty = true; } else { page[k] = tr; pageDirty = true; }
  }
  if (commonDirty) await saveMap(env, `${lang}:_common`, common);
  if (pageDirty) await saveMap(env, `${lang}:${path}`, page);
  const tr = async (t) => (await known(t)) ?? done[t] ?? null;
  for (const it of items) {
    if (it.text) {
      const [lead, t, tail] = piece(parts[it.i]); const x = await tr(t);
      if (x) parts[it.i] = encodeText(lead + x + tail);
    } else {
      let tag = parts[it.i]; const reps = [];
      for (const m of tag.matchAll(ATTRS)) { const x = await tr(decode(m[2]).trim()); if (x) reps.push([m[0], m[1] + encodeAttr(x) + m[3]]); }
      for (const [a, b] of reps) tag = tag.replace(a, b);
      parts[it.i] = tag;
    }
  }
  let out = parts.join('');
  const metaReps = [];
  for (const m of out.slice(0, out.indexOf('<body')).matchAll(META)) { const x = await tr(decode(m[2]).trim()); if (x) metaReps.push([m[0], m[1] + encodeAttr(x) + m[3]]); }
  for (const [a, b] of metaReps) out = out.replace(a, b);
  return { html: out, missing: left };
}

function localise(html, lang, path, origin) {
  const dir = RTL.has(lang) ? ' dir="rtl"' : '';
  let out = html.replace(/<html lang="en"/, `<html lang="${lang}"${dir}`);
  // assets live at the root; pages stay inside /<lang>/
  out = out.replace(/((?:src|href)=")((?:\.\.\/)*)(assets\/|pack\/|favicon\.ico|apple-touch-icon\.png|site\.webmanifest|search\.json)/g, '$1/$3');
  out = out.replace(/(<link rel="canonical" href=")[^"]*(")/, `$1${origin}/${lang}${path}$2`).replace(/(<meta property="og:url" content=")[^"]*(")/, `$1${origin}/${lang}${path}$2`);
  out = out.replace(/<body /, `<body data-lang="${lang}" `);
  return out;
}

const PAGE_EXT = /\.[a-z0-9]{2,5}$/i;
async function englishPage(request, env, url, rest) {
  // Pages and Workers assets may answer /x.html with a redirect to /x (or the reverse): follow it inside the language
  let r = await env.ASSETS.fetch(new Request(new URL(rest, url.origin), { headers: request.headers, redirect: 'manual' }));
  for (let hops = 0; hops < 3 && r.status >= 300 && r.status < 400 && r.headers.get('location'); hops++) {
    const to = new URL(r.headers.get('location'), url.origin);
    if (to.origin !== url.origin) break;
    r = await env.ASSETS.fetch(new Request(to, { headers: request.headers, redirect: 'manual' }));
  }
  return r;
}

async function translated(request, env, url, lang, ctx) {
  const rest = url.pathname.slice(lang.length + 1) || '/';
  if (rest !== '/' && !rest.endsWith('/') && PAGE_EXT.test(rest) && !/\.html?$/i.test(rest))
    return env.ASSETS.fetch(new Request(new URL(rest + url.search, url.origin), request));          // css, images, data
  const english = await englishPage(request, env, url, rest);
  if (!english.ok || !(english.headers.get('content-type') || '').includes('text/html')) return english;
  const tag = english.headers.get('etag') || '';
  const cacheKey = new Request(`${url.origin}/__tr/${lang}${rest}?v=${encodeURIComponent(tag)}`);
  const cache = typeof caches !== 'undefined' ? caches.default : null;
  if (cache) { const hit = await cache.match(cacheKey); if (hit) return hit; }
  const path = rest.endsWith('/') ? rest + 'index.html' : (PAGE_EXT.test(rest) ? rest : rest + '.html');
  const source = await english.text();
  // answer straight away with what is already translated (plus a small first batch); the rest is translated after
  // the page has been sent, so a first visit never sits on a blank screen
  const quick = Number(env.TRANSLATE_FIRST || 24), total = Number(env.TRANSLATE_BUDGET || 150);
  const { html, missing } = await translatePage(source, lang, { ...env, TRANSLATE_BUDGET: quick }, path);
  if (missing && ctx && ctx.waitUntil) ctx.waitUntil(translatePage(source, lang, { ...env, TRANSLATE_BUDGET: total }, path).catch(() => {}));
  let page = localise(html, lang, rest, url.origin);
  if (missing) page = page.replace(/(<main id="content">)/, `$1<p class="tr-wait" translate="no">${LANGS[lang]}: part of this page is still being translated. Refresh in a minute to see more.</p>`);
  const res = new Response(request.method === 'HEAD' ? null : page, { headers: { 'content-type': 'text/html; charset=utf-8', 'content-language': lang, 'x-frame-options': 'DENY',
    'content-security-policy': "frame-ancestors 'none'", 'x-content-type-options': 'nosniff', 'cache-control': missing ? 'no-store' : 'public, max-age=600' } });
  if (cache && !missing) { const put = cache.put(cacheKey, res.clone()); ctx && ctx.waitUntil ? ctx.waitUntil(put) : await put; }
  return res;
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url), p = url.pathname, m = request.method;
    try {
      const lang = p.split('/')[1];
      if (LANGS[lang] && p === `/${lang}`) return Response.redirect(`${url.origin}/${lang}/`, 301);
      if (LANGS[lang] && (m === 'GET' || m === 'HEAD')) return await translated(request, env, url, lang, ctx);
      if (p.startsWith('/pack/')) return await pack(request, env, url);
      if (p === '/api/auth/login' && m === 'GET') return await login(request, env, url);
      if (p === '/api/auth/callback' && m === 'GET') return await callback(request, env, url);
      if (p === '/api/auth/logout' && m === 'POST') { if (!sameOrigin(request, url)) return fail('Bad origin.', 403); return json({ ok: true }, 200, { 'set-cookie': cookie(SESSION, '', 0) }); }
      if (p === '/api/me' && m === 'GET') return await me(request, env);
      if (p === '/api/reports' && m === 'POST') return await submit(request, env, url);
      if (p === '/api/plans' && m === 'POST') return await savePlan(request, env, url);
      if (p.startsWith('/api/plans/') && m === 'GET') return await getPlan(env, p.slice(11));
      if (p === '/api/admin/reports' && m === 'GET') return await listReports(request, env, url, false);
      if (p === '/api/admin/reports.csv' && m === 'GET') return await listReports(request, env, url, true);
      if (p === '/api/admin/report' && m === 'POST') return await updateReport(request, env, url);
      if (p.startsWith('/api/')) return fail('Not found.', 404);
      return env.ASSETS.fetch(request);
    } catch (e) {
      return fail('Something went wrong on the wiki server. Please try again.', 500);
    }
  },
  _test: { tokenize, translatePage, localise, LANGS, translated },
};
