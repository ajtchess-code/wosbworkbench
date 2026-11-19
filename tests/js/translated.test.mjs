import assert from 'node:assert/strict';
const W = (await import(process.argv[2])).default;
const page = '<!doctype html><html lang="en"><head><title>Lanterns</title><link rel="stylesheet" href="../assets/site.css"></head><body data-base="../"><main id="content">'
  + Array.from({ length: 60 }, (_, i) => `<p>Sentence number ${i} about lanterns</p>`).join('') + '</main></body></html>';
// Workers assets / Pages: /guide/lanterns.html redirects to /guide/lanterns
const ASSETS = { fetch: async (req) => {
  const u = new URL(req.url);
  if (u.pathname === '/guide/lanterns.html') return new Response(null, { status: 307, headers: { location: '/guide/lanterns' } });
  if (u.pathname === '/guide/lanterns') return new Response(page, { headers: { 'content-type': 'text/html', etag: '"a"' } });
  return new Response('', { status: 404 });
} };
const later = [];
const kv = new Map(); let calls = 0;
const env = { ASSETS, TRANSLATE_FIRST: 5,
  AI: { run: async (m, o) => { calls++; await new Promise((r) => setTimeout(r, 5)); return { translated_text: `[es] ${o.text}` }; } },
  TRANSLATIONS: { get: async (k) => (kv.has(k) ? JSON.parse(kv.get(k)) : null), put: async (k, v) => { kv.set(k, v); } } };
const ctx = { waitUntil: (p) => later.push(p) };
for (const path of ['/es/guide/lanterns.html', '/es/guide/lanterns']) {
  const r = await W.fetch(new Request('https://wosbwiki.org' + path), env, ctx);
  assert.equal(r.status, 200, path);
  const h = await r.text();
  assert.match(h, /<main id="content"><p class="tr-wait"/);       // served at once, with the notice
  assert.match(h, /lang="es"/); assert.match(h, /href="\/assets\/site.css"/);
}
assert.ok(later.length >= 1);
await Promise.all(later);                                          // background pass finishes the page
const r = await W.fetch(new Request('https://wosbwiki.org/es/guide/lanterns'), env, ctx);
const h = await r.text();
assert.doesNotMatch(h, /tr-wait/); assert.match(h, /\[es\] Sentence number 59 about lanterns/);
const red = await W.fetch(new Request('https://wosbwiki.org/es'), env, ctx);
assert.equal(red.status, 301);
console.log('translated tests passed');
