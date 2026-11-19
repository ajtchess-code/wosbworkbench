import assert from 'node:assert/strict';
const W = (await import(process.argv[2])).default;
const { tokenize, translatePage, localise } = W._test;
const page = `<!doctype html><html lang="en"><head><meta name="description" content="Ships and guns of the wiki"><title>Port Nevis · WoSB Wiki</title>
<link rel="stylesheet" href="../assets/site.css?v=1"><link rel="canonical" href="https://wosbwiki.org/port/port-nevis.html"></head>
<body data-base="../"><nav id="side"><a href="../index.html">Main Page</a></nav><header id="top"><input placeholder="Search the WoSB Wiki"></header>
<main id="content"><h1>Port Nevis</h1><p><b>Faction:</b> a Kai &amp; Severia port.</p><p>1,925</p><code>keep this</code><span translate="no">WoSB Wiki</span>
<img src="../assets/icons/x.webp" alt="Map of the waters"><script>var t="do not touch"</script></main></body></html>`;
const { items } = tokenize(page);
const kv = new Map(); let calls = 0;
const env = {
  AI: { run: async (m, o) => { calls++; assert.equal(m, '@cf/meta/m2m100-1.2b'); assert.equal(o.target_lang, 'es'); return { translated_text: `[es] ${o.text}` }; } },
  TRANSLATIONS: { get: async (k) => (kv.has(k) ? JSON.parse(kv.get(k)) : null), put: async (k, v) => { kv.set(k, v); } },
};
let r = await translatePage(page, 'es', env, '/port/port-nevis.html');
assert.equal(r.missing, 0);
const h = r.html;
assert.match(h, /<h1>\[es\] Port Nevis<\/h1>/);
assert.match(h, /<b>\[es\] Faction:<\/b> \[es\] a Kai &amp; Severia port\./);
assert.match(h, /<p>1,925<\/p>/);                                    // numbers untouched
assert.match(h, /<code>keep this<\/code>/); assert.match(h, /<span translate="no">WoSB Wiki<\/span>/);
assert.match(h, /var t="do not touch"/);
assert.match(h, /alt="\[es\] Map of the waters"/); assert.match(h, /placeholder="\[es\] Search the WoSB Wiki"/);
assert.match(h, /<meta name="description" content="\[es\] Ships and guns of the wiki">/);
assert.ok(kv.has('es:_common') && kv.has('es:/port/port-nevis.html'));
assert.ok(JSON.stringify(JSON.parse(kv.get('es:_common'))).includes('Main Page'));   // menu text shared by all pages
// second page reuses the shared menu translations
const before = calls;
r = await translatePage(page.replace('Port Nevis', 'Port Aruba'), 'es', env, '/port/port-aruba.html');
assert.ok(calls - before <= 3, 'only the new text is translated: ' + (calls - before));
// budget: unfinished pages report what is left
const many = '<html lang="en"><head></head><body><main>' + Array.from({ length: 30 }, (_, i) => `<p>Sentence number ${'abcdefghijklmnopqrstuvwxyz'[i % 26]}${i}</p>`).join('') + '</main></body></html>';
r = await translatePage(many, 'es', { ...env, TRANSLATE_BUDGET: 10 }, '/many.html');
assert.equal(r.missing, 20);
// localise: language, direction, root assets, canonical
const loc = localise(page, 'ar', '/port/port-nevis.html', 'https://wosbwiki.org');
assert.match(loc, /<html lang="ar" dir="rtl"/); assert.match(loc, /href="\/assets\/site.css\?v=1"/); assert.match(loc, /src="\/assets\/icons\/x.webp"/);
assert.match(loc, /canonical" href="https:\/\/wosbwiki.org\/ar\/port\/port-nevis.html"/); assert.match(loc, /href="\.\.\/index.html"/);
console.log('translate tests passed');
