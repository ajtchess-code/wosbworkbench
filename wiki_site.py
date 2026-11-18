"""Build a public fan wiki website from the Workbench catalog and articles.

Layout follows classic game wikis (left navigation, top search, entity pages
with an infobox, category tables): our own name and styling.

Public-safe by design:
* No code, file paths, internal ids, decompiled source or message layouts.
  Articles in research sections are skipped.
* No game model files: ship pages show reconstructed hit *zones* (boxes),
  not meshes, unless ``include_models`` is set for a private/local build.
* Static files only: works from disk, GitHub Pages or any web host.
"""
from __future__ import annotations

import html
import json
import re
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

SITE_NAME = 'Sea Battle Compendium'
PRIVATE_SECTIONS = {'Research', 'Research backlog', 'Client metadata & research evidence', 'Networking and protocols'}
PRIVATE_SOURCE_KINDS = {'decompiled-client'}
HIDDEN_FIELDS = {'Source', 'SourceRecord', 'Name', 'IconName', 'IconTexture', 'IconTextureName', 'Icon', 'Texture',
                 'TexturePath', 'Model', 'StaticInfoID', 'ConstructionDataStatus', 'EnglishName', 'EnglishDescription',
                 'NameEnglish', 'PortName', 'PortNameEnglish', 'SubtypeEnglish', 'TypeEnglish', 'IDEnglish', 'PowerUpId',
                 'ID', 'Subtype', 'InternalBaseSpeed', 'GoldCostStatus', 'ConstructionStatus', 'Status'}

# entity kind -> (dataset, plural title, infobox fields [(field, label, fmt)], table columns)
ENTITIES = {
    'ship': ('ShipsToPlay', 'Ships', [
        ('Type', 'Class', 'camel'), ('SubtypeEnglish', 'Type', None), ('ShipRank', 'Rank', None),
        ('RequiredRank', 'Required rank', None), ('Coolness', 'Tier', 'tier'), ('Fraction', 'Faction', 'none'),
        ('Health', 'Hull HP', 'int'), ('Armor', 'Armor', None), ('BasicSpeed', 'Speed', None),
        ('BasicMobility', 'Mobility', None), ('BaseCrewPlaces', 'Crew', 'int'), ('CapacityCg', 'Cargo', 'int'),
        ('PlacesForUnitsCount', 'Unit slots', None), ('ExtraPlacesForUpgrades', 'Extra upgrade slots', None)],
        ['Type', 'Rank', 'Hull HP', 'Armor', 'Speed', 'Mobility', 'Crew', 'Cargo']),
    'cannon': ('Cannons', 'Cannons', [
        ('Category', 'Category', None), ('Poundage', 'Poundage', None), ('Penetration', 'Penetration', None),
        ('Distance', 'Range', None), ('Cooldown', 'Reload (s)', None), ('Angle', 'Vertical angle', None),
        ('Scatter', 'Scatter', 'first'), ('SpeedFactor', 'Ball speed', 'first'), ('SplashRadius', 'Splash radius', 'first'),
        ('Price', 'Price', 'int'), ('CraftingType', 'Obtained by', None), ('Extra', 'Notes', None)],
        ['Category', 'Poundage', 'Penetration', 'Range', 'Reload (s)', 'Price']),
    'ammo': ('CannonBalls', 'Ammunition', [
        ('DamageFactor', 'Damage factor', None), ('Penetration', 'Penetration bonus', None),
        ('DistanceFactor', 'Range factor', None), ('DamageToSailes', 'Sail damage', None),
        ('CrewDamage', 'Crew damage', None), ('ReloadFactor', 'Reload factor', None), ('Speed', 'Speed factor', None),
        ('MassKg', 'Mass (kg)', None), ('SingleCost', 'Cost per shot', None), ('IsRare', 'Rare', 'bool'),
        ('Effects', 'Effects', 'effects')],
        ['Damage factor', 'Penetration bonus', 'Range factor', 'Sail damage', 'Crew damage', 'Reload factor']),
    'upgrade': ('ShipUpgradesNew', 'Ship upgrades', [
        ('Category', 'Slot', 'category'), ('EffectsBoost', 'Effect', 'effects'), ('WearType', 'Wear', 'none'),
        ('LowCost', 'Budget version', 'bool')], ['Slot', 'Effect']),
    'crew': ('UnitsInfo', 'Crew', [
        ('TypeEnglish', 'Type', None), ('Cost', 'Cost', 'int'), ('DHealth', 'Health', None),
        ('DDamage', 'Damage', None), ('DCapacity', 'Capacity', None), ('Effect', 'Effect', 'effects')],
        ['Type', 'Cost', 'Health', 'Damage', 'Effect']),
    'skill': ('CaptainSkills', 'Captain skills', [
        ('Effect', 'Effect', 'effects'), ('CostPoints', 'Skill points', None), ('RequiredRank', 'Required rank', 'none')],
        ['Effect', 'Skill points']),
    'resource': ('Resources', 'Resources', [
        ('Mass', 'Mass', None), ('MediumCost', 'Typical price', 'int'), ('Effects', 'Effects', 'effects')],
        ['Mass', 'Typical price']),
    'port': ('WorldPorts', 'Ports', [
        ('Type', 'Type', 'camel'), ('Flags', 'Features', 'camel'), ('BuildShipRangs', 'Shipyard ranks', None)],
        ['Type', 'Shipyard ranks']),
    'achievement': ('Achievements', 'Achievements', [
        ('UiCategory', 'Category', None), ('CommonRatingWeight', 'Rating weight', None)], ['Category', 'Rating weight']),
}
NAV = [('Main page', 'index.html'), ('Ships', 'category/ships.html'), ('Cannons', 'category/cannons.html'),
       ('Ammunition', 'category/ammo.html'), ('Ship upgrades', 'category/upgrades.html'), ('Crew', 'category/crew.html'),
       ('Captain skills', 'category/skills.html'), ('Resources', 'category/resources.html'), ('Ports', 'category/ports.html'),
       ('Achievements', 'category/achievements.html'), ('Guides & mechanics', 'category/articles.html')]
TOOLS = [('Damage simulator', 'tools/damage-simulator.html'), ('Wind & sailing', 'tools/wind-rose.html'),
         ('Ship comparison', 'tools/compare-ships.html'), ('Hitbox viewer', 'tools/hitboxes.html')]
CATEGORY_FILE = {'ship': 'ships', 'cannon': 'cannons', 'ammo': 'ammo', 'upgrade': 'upgrades', 'crew': 'crew',
                 'skill': 'skills', 'resource': 'resources', 'port': 'ports', 'achievement': 'achievements'}
SLOT_NAMES = {'Sailes': 'Sails', 'Corpus': 'Hull', 'Cannons': 'Cannons', 'Crew': 'Crew'}
EFFECT_WORDS = {'Hp': 'HP', 'Pvp': 'PvP', 'Npc': 'NPC', 'Sailes': 'Sails'}


def _slug(text):
    s = re.sub(r'[^a-z0-9]+', '-', str(text).casefold()).strip('-')
    return s or 'page'


def _camel(text):
    return re.sub(r'(?<=[a-z0-9])(?=[A-Z])', ' ', str(text)).strip()


def humanize_effect(text):
    """'PSightSpeed +50' -> 'Sight speed +50%'; 'MMarchingSpeed +4' -> 'Marching speed +4'."""
    parts = []
    for m in re.finditer(r'([PMB]?)([A-Z][A-Za-z]+)\s*([+-]?\d+(?:\.\d+)?)?', str(text or '')):
        prefix, name, value = m.groups()
        words = _camel(name).split()
        words = [EFFECT_WORDS.get(w, w) for w in words]
        label = ' '.join([words[0]] + [w.lower() if w not in EFFECT_WORDS.values() else w for w in words[1:]]) if words else name
        if value is None:
            parts.append(label)
        else:
            parts.append(f'{label} {value}{"%" if prefix == "P" else ""}')
    return '; '.join(parts) or str(text or '')


def _fmt(value, kind):
    if value is None or value == '':
        return None
    if kind == 'int':
        try:
            return f'{int(float(value)):,}'
        except (TypeError, ValueError):
            return str(value)
    if kind == 'first':
        return str(value).split('|')[0]
    if kind == 'bool':
        return 'Yes' if value in (True, 'true', 'True', 1) else 'No'
    if kind == 'none':
        return None if str(value) in ('None', '', '0') else _camel(value)
    if kind == 'tier':
        return ' · '.join(_camel(w) for w in str(value).split()).replace('Sailage Legend', 'Sailage legend')
    if kind == 'effects':
        return humanize_effect(value)
    if kind == 'camel':
        return _camel(value)
    if kind == 'category':
        return SLOT_NAMES.get(str(value), _camel(value))
    if isinstance(value, float):
        return f'{value:g}'
    return str(value)


def _e(text):
    return html.escape(str(text), quote=True)


def load_entities(db, *, build='Steam'):
    """{kind: [record dicts]} preferring one build, de-duplicated by English name."""
    out = {}
    descriptions = {}
    for raw, in db.conn.execute("SELECT raw_json FROM records WHERE dataset='English_Names'"):
        rec = json.loads(raw)
        if rec.get('Key') and rec.get('EnglishDescription'):
            descriptions.setdefault(rec['Key'], rec['EnglishDescription'])
    for kind, (dataset, _title, _fields, _cols) in ENTITIES.items():
        rows = db.conn.execute('SELECT raw_json, source_root, name FROM records WHERE dataset=?', (dataset,)).fetchall()
        builds = {r[1] for r in rows}
        chosen = build if build in builds else ('Game' if 'Game' in builds else next(iter(builds), None))
        seen = {}
        for raw, root, name in rows:
            if root != chosen:
                continue
            rec = json.loads(raw)
            title = (rec.get('EnglishName') or rec.get('NameEnglish') or rec.get('PortNameEnglish') or name or '').strip()
            if kind == 'crew':
                m = re.match(r'unit_([a-z]+)_(\d+)', str(rec.get('ID') or ''))
                if m:
                    english = (rec.get('EnglishName') or '').strip()
                    title = f"{m.group(1).capitalize()} unit {m.group(2)}" + (f' ({english})' if english and english.casefold() not in (m.group(1), 'special') else '')
            if not title or title.startswith('(') or 'test' in title.casefold() or (kind == 'ship' and title.isupper()):
                continue
            if kind == 'ship' and not rec.get('EnglishDescription'):
                rec['EnglishDescription'] = descriptions.get(f"ship_{rec.get('ID')}", '')
            rec['_title'] = title
            key = title.casefold()
            # Same name twice (e.g. flag vs decal): keep the first, suffix later ones by slot/category.
            if key in seen:
                extra = rec.get('Category') or rec.get('Type') or ''
                candidate = f'{title} ({_camel(extra)})' if extra else title
                n = 2
                while candidate.casefold() in seen:
                    candidate = f'{title} ({_camel(extra) + " " if extra else ""}{n})'; n += 1
                rec['_title'] = candidate; key = candidate.casefold()
            seen[key] = rec
        out[kind] = sorted(seen.values(), key=lambda r: r['_title'].casefold())
    return out


# --------------------------------------------------------------- page chrome

CSS = r'''
:root{--link:#0645ad;--visited:#0b0080;--border:#a2a9b1;--side:#f6f6f6;--head:#eaecf0;--ink:#202122;--muted:#54595d;--accent:#1d4e6f}
*{box-sizing:border-box}html{background:#f6f6f6}body{margin:0;font:14px/1.6 "Segoe UI",system-ui,Arial,sans-serif;color:var(--ink)}
a{color:var(--link);text-decoration:none}a:hover{text-decoration:underline}a.new{color:#ba0000}
#top{display:flex;align-items:center;gap:16px;height:52px;padding:0 18px 0 196px;background:#fff;border-bottom:1px solid var(--border)}
#top .tabs a{display:inline-block;padding:14px 10px 12px;color:var(--muted);border-bottom:3px solid transparent}#top .tabs a.on{color:var(--ink);border-color:var(--accent)}
#search{margin-left:auto;position:relative}#search input{width:320px;padding:6px 10px;border:1px solid var(--border);border-radius:2px;font:inherit}
#results{position:absolute;right:0;top:34px;width:420px;max-height:420px;overflow:auto;background:#fff;border:1px solid var(--border);box-shadow:0 4px 14px rgba(0,0,0,.15);display:none;z-index:9}
#results a{display:block;padding:6px 10px;border-bottom:1px solid #eee}#results small{color:var(--muted);margin-left:6px}
#side{position:absolute;top:0;left:0;width:180px;padding:12px 10px}#logo{display:block;height:120px;margin-bottom:8px;text-align:center;color:var(--accent);font:700 17px/1.2 Georgia,serif}
#logo svg{display:block;margin:6px auto}#side h3{font-size:12px;color:var(--muted);font-weight:600;margin:14px 0 4px;padding-bottom:2px;border-bottom:1px solid #c8ccd1}
#side a{display:block;font-size:13px;padding:2px 0}
#content{margin-left:176px;background:#fff;border:1px solid var(--border);border-right:0;padding:16px 26px 32px;min-height:calc(100vh - 52px)}
h1{font:400 28px/1.3 Georgia,"Linux Libertine",serif;margin:0 0 4px;border-bottom:1px solid var(--border);padding-bottom:4px}
h2{font:400 21px/1.3 Georgia,serif;border-bottom:1px solid var(--border);margin:22px 0 8px}h3{font-size:16px;margin:16px 0 6px}
.crumbs{font-size:12px;color:var(--muted);margin-bottom:10px}
.infobox{float:right;clear:right;width:300px;margin:0 0 14px 18px;border:1px solid var(--border);background:#f8f9fa;font-size:13px;border-collapse:collapse}
.infobox caption{font-weight:700;font-size:15px;padding:6px;background:var(--accent);color:#fff}
.infobox th{text-align:left;padding:4px 8px;vertical-align:top;width:45%;background:var(--head)}.infobox td{padding:4px 8px}
table.wikitable{border-collapse:collapse;background:#f8f9fa;margin:10px 0;font-size:13px}
.wikitable th,.wikitable td{border:1px solid var(--border);padding:4px 8px}.wikitable th{background:var(--head);cursor:pointer;white-space:nowrap}
.wikitable th.sorted-asc:after{content:" ▲"}.wikitable th.sorted-desc:after{content:" ▼"}
.portal{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:12px;margin:12px 0}
.portal div{border:1px solid var(--border);background:#f8f9fa;padding:10px 12px}.portal h3{margin:0 0 4px;color:var(--accent)}
.welcome{border:1px solid #a3bfb1;background:#f5fffa;padding:12px 16px;margin-bottom:14px}
.note{border-left:4px solid #fc3;background:#fef6e7;padding:8px 12px;margin:10px 0}.toc{display:inline-block;border:1px solid var(--border);background:#f8f9fa;padding:8px 16px;margin:6px 0 10px;font-size:13px}
.toc b{display:block;text-align:center}.toc ul{margin:4px 0;padding-left:18px}
.tool{border:1px solid var(--border);background:#f8f9fa;padding:12px 14px;margin:10px 0}
.tool label{display:inline-block;margin:4px 12px 4px 0}.tool input,.tool select,.tool textarea{font:inherit;padding:4px 6px;border:1px solid var(--border)}
.tool button{background:var(--accent);color:#fff;border:0;padding:6px 14px;cursor:pointer;font:inherit}.tool textarea{width:100%;font-family:Consolas,monospace}
canvas{background:#fff;border:1px solid var(--border);max-width:100%}
.bar{height:10px;background:#d33;display:inline-block;vertical-align:middle}.barwrap{display:inline-block;width:160px;background:#eee;margin-right:8px}
code{background:#f8f9fa;border:1px solid #eaecf0;padding:1px 4px}footer{margin:30px 0 0 176px;padding:10px 26px;font-size:12px;color:var(--muted)}
.tag{display:inline-block;background:#eaf3ff;border:1px solid #c5d9f1;border-radius:2px;padding:0 6px;margin:2px;font-size:12px}
@media(max-width:820px){#side{position:static;width:auto}#content,footer{margin-left:0}#top{padding-left:12px}#search input{width:180px}.infobox{float:none;width:100%;margin:0 0 12px}}
'''

SITE_JS = r'''
(function(){
const base=document.body.dataset.base||'';
const box=document.querySelector('#search input'),res=document.getElementById('results');let idx=null;
async function load(){if(idx)return idx;try{idx=await (await fetch(base+'search.json')).json()}catch(e){idx=window.SEARCH_INDEX||[]}return idx}
if(box){box.addEventListener('input',async()=>{const q=box.value.trim().toLowerCase();if(!q){res.style.display='none';return}
 const items=(await load()).filter(x=>x.t.toLowerCase().includes(q)||x.k.toLowerCase().includes(q)).slice(0,40);
 res.innerHTML=items.map(x=>'<a href="'+base+x.u+'">'+x.t.replace(/</g,'&lt;')+'<small>'+x.c+'</small></a>').join('')||'<a>No matches</a>';res.style.display='block'});
 box.addEventListener('keydown',e=>{if(e.key==='Enter'){const a=res.querySelector('a[href]');if(a)location=a.href}});
 document.addEventListener('click',e=>{if(!e.target.closest('#search'))res.style.display='none'})}
document.querySelectorAll('table.sortable').forEach(t=>{t.querySelectorAll('th').forEach((th,i)=>th.addEventListener('click',()=>{
 const asc=!th.classList.contains('sorted-asc');t.querySelectorAll('th').forEach(h=>h.classList.remove('sorted-asc','sorted-desc'));th.classList.add(asc?'sorted-asc':'sorted-desc');
 const rows=[...t.tBodies[0].rows];const num=v=>{const n=parseFloat(String(v).replace(/[,%]/g,''));return isNaN(n)?null:n};
 rows.sort((a,b)=>{const x=a.cells[i].innerText,y=b.cells[i].innerText,nx=num(x),ny=num(y);const r=(nx!==null&&ny!==null)?nx-ny:x.localeCompare(y);return asc?r:-r});
 rows.forEach(r=>t.tBodies[0].appendChild(r))}))});
})();
'''

LOGO = ('<svg width="64" height="64" viewBox="0 0 64 64" aria-hidden="true"><circle cx="32" cy="32" r="30" fill="#1d4e6f"/>'
        '<path d="M32 10v34M20 22h24M32 44c-8 0-13-4-15-9l4 1M32 44c8 0 13-4 15-9l-4 1" stroke="#fff" stroke-width="3" fill="none" '
        'stroke-linecap="round"/><circle cx="32" cy="10" r="3" fill="#fff"/></svg>')


def _page(title, body, *, depth=0, crumbs=None, tab='Page'):
    base = '../' * depth
    side = [f'<a id="logo" href="{base}index.html">{LOGO}{_e(SITE_NAME)}</a>', '<h3>Navigation</h3>']
    side += [f'<a href="{base}{u}">{_e(t)}</a>' for t, u in NAV]
    side += ['<h3>Tools</h3>'] + [f'<a href="{base}{u}">{_e(t)}</a>' for t, u in TOOLS]
    side += ['<h3>Wiki</h3>', f'<a href="{base}recent.html">Recent changes</a>', f'<a href="{base}about.html">About</a>']
    crumb = ''
    if crumbs:
        crumb = '<div class="crumbs">' + ' › '.join(f'<a href="{base}{u}">{_e(t)}</a>' if u else _e(t) for t, u in crumbs) + '</div>'
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{_e(title)} · {_e(SITE_NAME)}</title><link rel="stylesheet" href="{base}assets/site.css"></head>'
            f'<body data-base="{base}"><div id="side">{"".join(side)}</div>'
            f'<div id="top"><span class="tabs"><a class="on">{_e(tab)}</a></span>'
            '<div id="search"><input type="search" placeholder="Search the compendium" aria-label="Search"><div id="results"></div></div></div>'
            f'<main id="content">{crumb}<h1>{_e(title)}</h1>{body}</main>'
            f'<footer>{_e(SITE_NAME)} is a fan-made reference for World of Sea Battle. Not affiliated with the game\'s developers. '
            'Game data is extracted from the public client; mechanics pages describe observed and client-side rules.</footer>'
            f'<script src="{base}assets/site.js"></script></body></html>')


def _infobox(title, rows):
    cells = ''.join(f'<tr><th>{_e(k)}</th><td>{_e(v)}</td></tr>' for k, v in rows if v not in (None, ''))
    return f'<table class="infobox"><caption>{_e(title)}</caption>{cells}</table>'


def _table(headers, rows, *, cls='wikitable sortable'):
    head = ''.join(f'<th>{_e(h)}</th>' for h in headers)
    body = ''.join('<tr>' + ''.join(f'<td>{c}</td>' for c in r) + '</tr>' for r in rows)
    return f'<table class="{cls}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


# --------------------------------------------------------------- builder

class SiteBuilder:
    def __init__(self, db, out, *, hitboxes_dir=None, build='Steam', include_models=False):
        self.db = db; self.out = Path(out); self.hitboxes_dir = Path(hitboxes_dir) if hitboxes_dir else None
        self.build = build; self.include_models = include_models
        self.search = []; self.pages = 0
        self.entities = load_entities(db, build=build)
        self.urls = {}
        for kind, recs in self.entities.items():
            for r in recs:
                self.urls[(kind, r['_title'].casefold())] = f'{kind}/{_slug(r["_title"])}.html'
        self.articles = self._articles()
        self.article_urls = {a['slug']: f'wiki/{_slug(a["slug"])}.html' for a in self.articles}

    def _articles(self):
        rows = self.db.conn.execute('SELECT slug,title,section,body,source_kind,updated_utc FROM articles ORDER BY section,title').fetchall()
        return [dict(zip(('slug', 'title', 'section', 'body', 'source_kind', 'updated'), r)) for r in rows
                if r[2] not in PRIVATE_SECTIONS and r[4] not in PRIVATE_SOURCE_KINDS
                and not str(r[0]).startswith('research-') and 'research' not in str(r[2]).casefold()]

    def _write(self, rel, content):
        path = self.out / rel; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8'); self.pages += 1

    def _link(self, target):
        """Wiki-link resolver for article Markdown: articles, then entity pages."""
        import wiki_engine
        key = wiki_engine.slugify(target)
        for a in self.articles:
            if wiki_engine.slugify(a['slug']) == key or wiki_engine.slugify(a['title']) == key:
                return '../' + self.article_urls[a['slug']], True
        for (kind, name), url in self.urls.items():
            if wiki_engine.slugify(name) == key:
                return '../' + url, True
        for t, u in TOOLS:
            if wiki_engine.slugify(t) == key or (key == 'damage-simulator' and 'damage' in u):
                return '../' + u, True
        return '../wiki/' + _slug(target) + '.html', False

    def _scrub(self, body):
        """Drop code-ish lines and internal references from article bodies."""
        body = re.sub(r'```.*?```', '', body, flags=re.S)
        body = re.sub(r'`[^`]*(?:\.dll|\.cs|0x0[0-9a-fA-F]{7}|::)[^`]*`', '', body)
        body = re.sub(r'(?im)^.*(?:Common\.dll|decompiled|IL offset|token 0x|Client record:|File:\s|\.xnb|\.wosb|\.dll|\.jsonl?\b|AI-Data|Source:).*$\n?', '', body)
        body = re.sub(r'`[^`]*(?:\.xnb|\.wosb|_j\b|AI-Data|\.jsonl?)[^`]*`', '', body)
        return body

    # ---- pages
    def build_site(self):
        if self.out.exists():
            for child in ('ship', 'cannon', 'ammo', 'upgrade', 'crew', 'skill', 'resource', 'port', 'achievement',
                          'category', 'wiki', 'tools', 'assets', 'data'):
                shutil.rmtree(self.out / child, ignore_errors=True)
        self.out.mkdir(parents=True, exist_ok=True)
        self._write('assets/site.css', CSS); self._write('assets/site.js', SITE_JS)
        hitboxes = self._hitboxes()
        for kind, recs in self.entities.items():
            for r in recs:
                self._entity_page(kind, r, hitboxes)
            self._category_page(kind, recs)
        for a in self.articles:
            self._article_page(a)
        self._articles_category()
        self._tools(hitboxes)
        self._main_page()
        self._recent(); self._about()
        (self.out / 'search.json').write_text(json.dumps(self.search, separators=(',', ':')), encoding='utf-8')
        # Also inline the index so search works when opened straight from disk (file://).
        js = (self.out / 'assets' / 'site.js').read_text(encoding='utf-8')
        (self.out / 'assets' / 'site.js').write_text('window.SEARCH_INDEX=' + json.dumps(self.search, separators=(',', ':')) + ';\n' + js, encoding='utf-8')
        manifest = {'site': SITE_NAME, 'generated_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                    'pages': self.pages, 'entities': {k: len(v) for k, v in self.entities.items()},
                    'articles': len(self.articles), 'ships_with_hitboxes': len(hitboxes), 'build': self.build}
        (self.out / 'site.json').write_text(json.dumps(manifest, indent=1), encoding='utf-8')
        return manifest

    def _hitboxes(self):
        """{model name: compact zone list} from 'Rebuild ship hitboxes' output."""
        out = {}
        if not self.hitboxes_dir or not self.hitboxes_dir.is_dir():
            return out
        for f in self.hitboxes_dir.glob('*.hitboxes.json'):
            try:
                d = json.loads(f.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                continue
            zones = [{'t': 'hull', 'b': d['corpus']}]
            zones += [{'t': 'sail', 'b': b, 'w': round(s['weight'], 4), 'n': 1 + s['strength_index']}
                      for s in d['sails'] for b in s['levels'] if b]
            zones += [{'t': 'mast', 'b': m['box']} for m in d['masts']]
            for z in zones:
                z['b'] = {'min': [round(v, 3) for v in z['b']['min']], 'max': [round(v, 3) for v in z['b']['max']]}
            out[f.name.replace('.hitboxes.json', '')] = {'zones': zones, 'sails': len(d['sails']), 'masts': len(d['masts'])}
        return out

    def _model_for(self, ship):
        row = self.db.conn.execute("SELECT raw_json FROM records WHERE dataset='ShipsBasics' AND external_id=? LIMIT 1",
                                   (str(ship.get('StaticInfoID')),)).fetchone()
        if not row:
            for raw, in self.db.conn.execute("SELECT raw_json FROM records WHERE dataset='ShipsBasics'"):
                rec = json.loads(raw)
                if str(rec.get('ID')) == str(ship.get('StaticInfoID')):
                    return rec.get('ModelName')
            return None
        return json.loads(row[0]).get('ModelName')

    def _entity_page(self, kind, rec, hitboxes):
        dataset, plural, fields, _cols = ENTITIES[kind]
        title = rec['_title']
        rows = [(label, _fmt(rec.get(field), fmt)) for field, label, fmt in fields]
        body = [_infobox(title, rows)]
        desc = (rec.get('EnglishDescription') or '').replace('#', '')
        if desc:
            body.append(f'<p>{_e(desc)}</p>')
        else:
            body.append(f'<p><b>{_e(title)}</b> is {"an" if plural[0] in "AEIOU" else "a"} {_e(plural[:-1].lower() if plural.endswith("s") else plural.lower())} in World of Sea Battle.</p>')
        if kind == 'ship':
            body += self._ship_sections(rec, hitboxes)
        if kind in ('ammo', 'upgrade', 'skill', 'crew') and rec.get('Effects') or rec.get('EffectsBoost') or rec.get('Effect'):
            eff = rec.get('Effects') or rec.get('EffectsBoost') or rec.get('Effect')
            body.append('<h2>Effects</h2><ul>' + ''.join(f'<li>{_e(x.strip())}</li>' for x in humanize_effect(eff).split(';') if x.strip()) + '</ul>')
        cat = CATEGORY_FILE[kind]
        body.append(f'<p style="clear:both"><span class="tag"><a href="../category/{cat}.html">Category: {_e(plural)}</a></span></p>')
        url = self.urls[(kind, title.casefold())]
        self._write(url, _page(title, ''.join(body), depth=1, crumbs=[('Main page', 'index.html'), (plural, f'category/{cat}.html'), (title, None)]))
        self.search.append({'t': title, 'u': url, 'c': plural, 'k': ' '.join(str(v) for _, v in rows if v)})

    def _ship_sections(self, rec, hitboxes):
        out = []
        hp = rec.get('Health')
        out.append('<h2>Combat</h2><p>Hull HP and armor come from the ship\'s base stats; upgrades, skills and crew change them. '
                   f'When HP reaches zero the ship begins to sink (13 s) - see <a href="../{self.article_urls.get("damage-and-sinking", "wiki/damage-and-sinking.html")}">Damage and sinking</a>.</p>'
                   f'<p><a href="../tools/damage-simulator.html?hp={_e(hp)}">Simulate damage against this ship</a></p>')
        model = self._model_for(rec)
        hb = hitboxes.get(model) if model else None
        if hb:
            out.append(f'<h2>Hit zones</h2><p>{hb["sails"]} sails (each split into 4 slices) and {hb["masts"]} masts, plus the hull. '
                       'Drag to rotate; scroll to zoom.</p><canvas class="hitbox" width="640" height="360" '
                       f'data-zones="{_e(json.dumps(hb["zones"], separators=(",", ":")))}"></canvas>'
                       '<script src="../assets/hitboxes.js"></script>')
        out.append('<h2>Sailing</h2><p>Speed depends on the angle to the wind. See the '
                   '<a href="../tools/wind-rose.html">wind &amp; sailing calculator</a> for the regular and unique wind roses.</p>')
        return out

    def _category_page(self, kind, recs):
        dataset, plural, fields, cols = ENTITIES[kind]
        labels = {label: (field, fmt) for field, label, fmt in fields}
        rows = []
        for r in recs:
            cells = [f'<a href="../{self.urls[(kind, r["_title"].casefold())]}">{_e(r["_title"])}</a>']
            for c in cols:
                field, fmt = labels[c]
                cells.append(_e(_fmt(r.get(field), fmt) or ''))
            rows.append(cells)
        intro = f'<p>All {len(recs)} {_e(plural.lower())}. Click a column heading to sort.</p>'
        if kind == 'ship':
            groups = defaultdict(list)
            for r, cells in zip(recs, rows):
                groups[_fmt(r.get('Type'), 'camel') or 'Other'].append(cells)
            body = intro + ''.join(f'<h2>{_e(g)}</h2>' + _table(['Ship'] + cols, groups[g]) for g in sorted(groups))
        else:
            body = intro + _table([plural[:-1] if plural.endswith('s') else plural] + cols, rows)
        cat = CATEGORY_FILE[kind]
        self._write(f'category/{cat}.html', _page(f'Category: {plural}', body, depth=1,
                    crumbs=[('Main page', 'index.html'), (plural, None)]))
        self.search.append({'t': plural, 'u': f'category/{cat}.html', 'c': 'Category', 'k': plural})

    def _article_page(self, a):
        import wiki_engine
        md = self._scrub(a['body'])
        md = re.sub(r'^#\s+.*\n', '', md, count=1)       # title is rendered by the page chrome
        toc = wiki_engine.table_of_contents(md) if hasattr(wiki_engine, 'table_of_contents') else []
        html_body = wiki_engine.render_markdown(md, self._link).replace('href="/tag/', 'href="../category/articles.html#')
        toc_html = ''
        if toc and len(toc) >= 3:
            toc_html = '<div class="toc"><b>Contents</b><ul>' + ''.join(
                f'<li><a href="#{_e(t.get("anchor", ""))}">{_e(t.get("title", ""))}</a></li>' for t in toc if isinstance(t, dict)) + '</ul></div>'
        url = self.article_urls[a['slug']]
        body = toc_html + html_body + f'<p><span class="tag"><a href="../category/articles.html#{_e(_slug(a["section"]))}">{_e(a["section"])}</a></span></p>'
        self._write(url, _page(a['title'], body, depth=1, crumbs=[('Main page', 'index.html'), ('Guides & mechanics', 'category/articles.html'), (a['section'], None)]))
        self.search.append({'t': a['title'], 'u': url, 'c': a['section'], 'k': a['section']})

    def _articles_category(self):
        groups = defaultdict(list)
        for a in self.articles:
            groups[a['section']].append(a)
        body = [f'<p>{len(self.articles)} guides and mechanics articles.</p>']
        for sec in sorted(groups):
            body.append(f'<h2 id="{_e(_slug(sec))}">{_e(sec)}</h2><ul>' + ''.join(
                f'<li><a href="../{self.article_urls[a["slug"]]}">{_e(a["title"])}</a></li>' for a in groups[sec]) + '</ul>')
        self._write('category/articles.html', _page('Guides & mechanics', ''.join(body), depth=1, crumbs=[('Main page', 'index.html'), ('Guides & mechanics', None)]))

    def _main_page(self):
        counts = {k: len(v) for k, v in self.entities.items()}
        portals = [('Ships', 'category/ships.html', f'{counts.get("ship", 0)} ships with full stats, hit zones and sailing notes.'),
                   ('Cannons', 'category/cannons.html', f'{counts.get("cannon", 0)} cannons: poundage, penetration, range, reload.'),
                   ('Ammunition', 'category/ammo.html', f'{counts.get("ammo", 0)} ammo types and their effects.'),
                   ('Ship upgrades', 'category/upgrades.html', f'{counts.get("upgrade", 0)} upgrades by slot.'),
                   ('Crew', 'category/crew.html', f'{counts.get("crew", 0)} crew and boarding units.'),
                   ('Captain skills', 'category/skills.html', f'{counts.get("skill", 0)} skills.'),
                   ('Resources', 'category/resources.html', f'{counts.get("resource", 0)} goods and resources.'),
                   ('Ports', 'category/ports.html', f'{counts.get("port", 0)} ports and bays.'),
                   ('Achievements', 'category/achievements.html', f'{counts.get("achievement", 0)} achievements.'),
                   ('Guides & mechanics', 'category/articles.html', f'{len(self.articles)} articles on how the game works.')]
        tools = ''.join(f'<li><a href="{u}">{_e(t)}</a></li>' for t, u in TOOLS)
        body = (f'<div class="welcome"><b>Welcome to the {_e(SITE_NAME)}</b>, a fan reference for World of Sea Battle: every ship, cannon, '
                'ammo type and upgrade, plus interactive tools for damage, sailing and ship comparison.</div>'
                '<div class="portal">' + ''.join(f'<div><h3><a href="{u}">{_e(t)}</a></h3>{_e(d)}</div>' for t, u, d in portals) + '</div>'
                f'<h2>Tools</h2><ul>{tools}</ul>')
        self._write('index.html', _page('Main page', body, depth=0, tab='Main page'))

    def _recent(self):
        rows = sorted((a for a in self.articles if a.get('updated')), key=lambda a: a['updated'], reverse=True)[:50]
        body = '<ul>' + ''.join(f'<li>{_e(a["updated"][:10])} · <a href="{self.article_urls[a["slug"]]}">{_e(a["title"])}</a></li>' for a in rows) + '</ul>'
        self._write('recent.html', _page('Recent changes', body or '<p>No changes yet.</p>'))

    def _about(self):
        body = ('<p>This is a fan-made reference. Stats are extracted from the game client and refreshed when the game updates. '
                'Mechanics pages describe the client\'s rules; values the server decides (like exact cannonball damage) '
                'are marked as measured or estimated.</p><p>No game files, models or code are published here.</p>')
        self._write('about.html', _page('About', body))

    # ---- tools
    def _tools(self, hitboxes):
        ships = [{'n': r['_title'], 'hp': r.get('Health'), 'armor': r.get('Armor'), 'speed': r.get('BasicSpeed'),
                  'mob': r.get('BasicMobility'), 'crew': r.get('BaseCrewPlaces'), 'cargo': r.get('CapacityCg'),
                  'rank': r.get('ShipRank'), 'cls': r.get('TypeEnglish') or r.get('Type'),
                  'model': self._model_for(r)} for r in self.entities.get('ship', [])]
        roses = [json.loads(raw) for raw, in self.db.conn.execute(
            "SELECT raw_json FROM records WHERE dataset='WindRoses' ORDER BY CASE source_root WHEN ? THEN 0 ELSE 1 END", (self.build,))]
        seen = set(); rose_data = []
        for r in roses:
            key = (r.get('Name') or '').casefold()
            if key in seen:
                continue
            seen.add(key)
            rose_data.append({k: r.get(k) for k in ('Name', 'FordewindFineEdge', 'GreenLeft', 'GreenRight', 'HeadwindLeft', 'HeadwindRight')})
        self._write('data/ships.json', json.dumps(ships, separators=(',', ':')))
        self._write('assets/hitboxes.js', HITBOX_JS)
        crumbs = [('Main page', 'index.html'), ('Tools', None)]
        self._write('tools/damage-simulator.html', _page('Damage simulator', DAMAGE_TOOL.replace('__SHIPS__', json.dumps(ships, separators=(',', ':'))), depth=1, crumbs=crumbs, tab='Tool'))
        self._write('tools/wind-rose.html', _page('Wind & sailing', WIND_TOOL.replace('__ROSES__', json.dumps(rose_data)), depth=1, crumbs=crumbs, tab='Tool'))
        self._write('tools/compare-ships.html', _page('Ship comparison', COMPARE_TOOL.replace('__SHIPS__', json.dumps(ships, separators=(',', ':'))), depth=1, crumbs=crumbs, tab='Tool'))
        hb_ships = [s for s in ships if s['model'] in hitboxes]
        options = ''.join(f'<option value="{_e(s["model"])}">{_e(s["n"])}</option>' for s in hb_ships)
        payload = json.dumps({s['model']: hitboxes[s['model']]['zones'] for s in hb_ships}, separators=(',', ':'))
        hb_body = ('<p>Reconstructed hit zones: hull (blue), sail slices (orange, darker = larger share of sail health), masts (brown). '
                   'Drag to rotate, scroll to zoom.</p>' + (f'<div class="tool"><label>Ship <select id="hbship">{options}</select></label></div>'
                   '<canvas id="hbcanvas" class="hitbox" width="900" height="480"></canvas>'
                   f'<script>window.HITBOXES={payload};</script><script src="../assets/hitboxes.js"></script>'
                   if hb_ships else '<p class="note">No hit zones in this build yet. In WoSB Workbench run <b>Datamining → Rebuild ship hitboxes</b>, then rebuild the site.</p>'))
        self._write('tools/hitboxes.html', _page('Hitbox viewer', hb_body, depth=1, crumbs=crumbs, tab='Tool'))
        for t, u in TOOLS:
            self.search.append({'t': t, 'u': u, 'c': 'Tool', 'k': 'tool calculator'})


HITBOX_JS = r'''
(function(){
function draw(cv,zones){const ctx=cv.getContext('2d');let yaw=-0.7,pitch=0.35,zoom=1,drag=null;
 const all=zones.flatMap(z=>[z.b.min,z.b.max]);const c=[0,1,2].map(i=>(Math.min(...all.map(p=>p[i]))+Math.max(...all.map(p=>p[i])))/2);
 const span=Math.max(...[0,1,2].map(i=>Math.max(...all.map(p=>p[i]))-Math.min(...all.map(p=>p[i]))));
 function proj(p){let x=p[0]-c[0],y=p[1]-c[1],z=p[2]-c[2];const cy=Math.cos(yaw),sy=Math.sin(yaw);[x,z]=[x*cy-z*sy,x*sy+z*cy];
  const cp=Math.cos(pitch),sp=Math.sin(pitch);[y,z]=[y*cp-z*sp,y*sp+z*cp];const s=zoom*cv.height*0.9/span;return [cv.width/2+x*s,cv.height/2-y*s,z]}
 const E=[[0,1],[1,3],[3,2],[2,0],[4,5],[5,7],[7,6],[6,4],[0,4],[1,5],[2,6],[3,7]];
 function render(){ctx.clearRect(0,0,cv.width,cv.height);const items=zones.map(z=>{const mn=z.b.min,mx=z.b.max;
   const v=[];for(const X of [mn[0],mx[0]])for(const Y of [mn[1],mx[1]])for(const Z of [mn[2],mx[2]])v.push(proj([X,Y,Z]));
   return {z,v,d:v.reduce((a,p)=>a+p[2],0)/8}}).sort((a,b)=>a.d-b.d);
  for(const it of items){const t=it.z.t;ctx.strokeStyle=t==='hull'?'#1f6fb2':t==='mast'?'#7a4b1d':'rgba(230,120,20,'+(0.35+Math.min(0.6,(it.z.w||0)*6))+')';
   ctx.lineWidth=t==='hull'?2:1;ctx.beginPath();for(const [a,b] of E){ctx.moveTo(it.v[a][0],it.v[a][1]);ctx.lineTo(it.v[b][0],it.v[b][1])}ctx.stroke()}}
 cv.onmousedown=e=>drag=[e.clientX,e.clientY,yaw,pitch];window.addEventListener('mouseup',()=>drag=null);
 cv.onmousemove=e=>{if(!drag)return;yaw=drag[2]+(e.clientX-drag[0])/200;pitch=Math.max(-1.4,Math.min(1.4,drag[3]+(e.clientY-drag[1])/200));render()};
 cv.onwheel=e=>{e.preventDefault();zoom*=e.deltaY<0?1.1:0.9;render()};render();return render}
document.querySelectorAll('canvas.hitbox[data-zones]').forEach(cv=>draw(cv,JSON.parse(cv.dataset.zones)));
const sel=document.getElementById('hbship'),cv=document.getElementById('hbcanvas');
if(sel&&cv&&window.HITBOXES){const go=()=>draw(cv,window.HITBOXES[sel.value]);sel.onchange=go;go()}
})();
'''

DAMAGE_TOOL = r'''
<p>Applies hits to a ship using the game's rules for HP, sinking, sails, fire and flooding. Enter how much each hit does;
exact cannonball damage is decided by the game server, so use values you have measured (see <a href="../wiki/damage-formula-calibration.html">calibration</a>).</p>
<div class="tool"><label>Ship <select id="ship"></select></label><label>Max HP <input id="hp" type="number" value="5000" style="width:90px"></label>
<label>Sails <input id="sails" type="number" value="6" min="1" style="width:60px"></label></div>
<div class="tool"><b>Hits</b> (one per line: <code>type damage</code> plus optional words: <code>stern</code>, <code>sail=N amount</code>, <code>allsails amount</code>, <code>fire</code>, <code>breach</code>)<br>
Types: cannonball, mortar, keg, ram, fire, other<textarea id="hits" rows="7">cannonball 1800
cannonball 1800
cannonball 1500 sail=2 0.25
ram 100
mortar 50</textarea><button id="run">Simulate</button></div>
<div id="out"></div>
<script>
const SHIPS=__SHIPS__;const sel=document.getElementById('ship');sel.innerHTML='<option value="">(custom)</option>'+SHIPS.map((s,i)=>'<option value="'+i+'">'+s.n.replace(/</g,'&lt;')+'</option>').join('');
const q=new URLSearchParams(location.search);if(q.get('hp'))document.getElementById('hp').value=q.get('hp');
sel.onchange=()=>{if(sel.value!=='')document.getElementById('hp').value=SHIPS[sel.value].hp};
function sim(){const max=+document.getElementById('hp').value||1,n=Math.max(1,+document.getElementById('sails').value||1);
 let hp=max,sinkMs=0,offset=0,destroyed=false,sails=Array(n).fill(1),w=Array(n).fill(1/n),fire=false;const rows=[];
 const ff=()=>(sinkMs-offset)/13000;
 for(const raw of document.getElementById('hits').value.split('\n')){const p=raw.trim().split(/\s+/);if(!p[0])continue;
  const type=p[0].toLowerCase(),dmg=parseFloat(p[1])||0;const before=hp,ev=[];if(destroyed){rows.push([raw,before,hp,'already sunk']);continue}
  if(sinkMs===0){const rm=Math.min(dmg,hp);hp=(hp-rm<0.5)?0:hp-rm;if(hp<=0){sinkMs=0.01;hp=1;ev.push('starts sinking (13 s)')}}
  if(ff()>0&&ev.length===0||ff()>0&&type!=='cannonball'){
   if(type==='mortar'||type==='keg'||(type==='fire'&&fire)||p.includes('stern')){destroyed=true;hp=0;ev.push('sunk instantly')}
   else if(type==='ram'){const nw=Math.min(12999,sinkMs+800);offset=nw-sinkMs;sinkMs=nw;ev.push('ram: sinking +0.8 s')}}
  for(let i=2;i<p.length;i++){const t=p[i];if(t.startsWith('sail=')){const k=Math.min(n,Math.max(1,parseInt(t.slice(5))))-1,a=parseFloat(p[i+1])||0;sails[k]=Math.max(0,sails[k]-a/(w[k]*n));ev.push('sail '+(k+1)+' hit');i++}
   else if(t==='allsails'){const a=parseFloat(p[i+1])||0;for(let k=0;k<n;k++)sails[k]=Math.max(0,sails[k]-a/(w[k]*n));ev.push('all sails hit');i++}
   else if(t==='fire'){fire=true;ev.push('large fire')}else if(t==='breach')ev.push('hull breach')}
  rows.push([raw,before,hp,ev.join('; ')])}
 const sailHp=sails.reduce((a,s,i)=>a+s*w[i],0);
 const bar=v=>'<span class="barwrap"><span class="bar" style="width:'+Math.round(160*Math.max(0,v))+'px"></span></span>';
 document.getElementById('out').innerHTML='<table class="wikitable"><tr><th>Hit</th><th>HP before</th><th>HP after</th><th>Hull</th><th>Events</th></tr>'+
  rows.map(r=>'<tr><td>'+r[0].replace(/</g,'&lt;')+'</td><td>'+r[1].toFixed(0)+'</td><td>'+r[2].toFixed(0)+'</td><td>'+bar(r[2]/max)+'</td><td>'+r[3]+'</td></tr>').join('')+
  '</table><p><b>Result:</b> '+(destroyed?'sunk':(sinkMs>0?'sinking':'afloat'))+' · sails '+(sailHp*100).toFixed(1)+'%'+(sailHp<0.95?' (maneuverability reduced)':'')+'</p>'}
document.getElementById('run').onclick=sim;sim();
</script>
<h2>Rules used</h2><ul><li>Below 0.5 HP the ship is at zero and begins a 13-second sinking timeline (HP held at 1; further hits do no HP damage).</li>
<li>While sinking: mortars, powder kegs, fire during a large fire and stern hits sink the ship instantly; a ram pushes the timeline 0.8 s.</li>
<li>Sail damage is divided by the sail's share of total sail size; this tool assumes equal sails.</li></ul>
'''

WIND_TOOL = r'''
<p>How much of the wind a ship can use at each heading, and the regular and <b>unique</b> wind roses that some ships have.
The curve is the game's wind-angle component; the coloured sectors come from each wind rose (fast-sailing "green" arcs and headwind dead zones).</p>
<div class="tool"><label>Wind rose <select id="rose"></select></label><label>Angle off the wind <input id="ang" type="range" min="0" max="180" value="45"> <span id="angv"></span>° (0 = wind behind)</label>
<div id="readout"></div></div><canvas id="polar" width="520" height="520"></canvas>
<script>
const ROSES=__ROSES__;const sel=document.getElementById('rose');sel.innerHTML=ROSES.map((r,i)=>'<option value="'+i+'">'+(r.Name||'rose '+i)+'</option>').join('');
function dot(deg){const t=deg*Math.PI/180,x=Math.cos(t)+0.75,y=Math.sin(t);return x/Math.hypot(x,y)}
function comp(deg){return 1.8*(0.5+0.5*dot(deg))}
function inArc(a,arc){if(!arc)return false;let s=arc.Start,e=arc.End;return s<=e?a>=s&&a<=e:(a>=s||a<=e)}
function draw(){const cv=document.getElementById('polar'),c=cv.getContext('2d'),R=230,cx=260,cy=260,r=ROSES[sel.value]||{};c.clearRect(0,0,520,520);
 // headwind dead zones (bow = up)
 const sector=(a0,a1,col)=>{c.fillStyle=col;c.beginPath();c.moveTo(cx,cy);c.arc(cx,cy,R,(a0-90)*Math.PI/180,(a1-90)*Math.PI/180);c.closePath();c.fill()};
 // Angle convention: 0° = wind directly behind (downwind, top); 180° = sailing into the wind (bottom).
 if(r.HeadwindLeft)sector(180,180+r.HeadwindLeft,'rgba(210,40,40,.18)');if(r.HeadwindRight)sector(180-r.HeadwindRight,180,'rgba(210,40,40,.18)');
 if(r.GreenRight)sector(r.GreenRight.Start,r.GreenRight.End,'rgba(40,170,60,.25)');if(r.GreenLeft)sector(r.GreenLeft.Start-360,r.GreenLeft.End-360,'rgba(40,170,60,.25)');
 if(r.FordewindFineEdge){c.strokeStyle='rgba(40,120,200,.6)';c.setLineDash([4,4]);for(const a of [r.FordewindFineEdge,-r.FordewindFineEdge]){const t=(a-90)*Math.PI/180;c.beginPath();c.moveTo(cx,cy);c.lineTo(cx+Math.cos(t)*R,cy+Math.sin(t)*R);c.stroke()}c.setLineDash([])}
 c.strokeStyle='#ccc';for(let k=1;k<=4;k++){c.beginPath();c.arc(cx,cy,R*k/4,0,7);c.stroke()}
 c.strokeStyle='#1d4e6f';c.lineWidth=2;c.beginPath();for(let a=0;a<=360;a+=2){const v=comp(a)/1.8,t=(a-90)*Math.PI/180;const x=cx+Math.cos(t)*R*v,y=cy+Math.sin(t)*R*v;a?c.lineTo(x,y):c.moveTo(x,y)}c.stroke();c.lineWidth=1;
 const ang=+document.getElementById('ang').value;document.getElementById('angv').textContent=ang;const t=(ang-90)*Math.PI/180,v=comp(ang)/1.8;
 c.fillStyle='#d33';c.beginPath();c.arc(cx+Math.cos(t)*R*v,cy+Math.sin(t)*R*v,6,0,7);c.fill();c.fillStyle='#333';
 c.fillText('0° · wind behind (downwind)',cx-70,14);c.fillText('180° · into the wind',cx-50,512);
 const green=inArc(ang,r.GreenRight)||inArc(360-ang,r.GreenLeft),dead=ang>=180-(r.HeadwindRight||0);
 document.getElementById('readout').innerHTML='Wind component at '+ang+'°: <b>'+comp(ang).toFixed(3)+'</b> (max 1.8)'+(green?' · <b style="color:#282">fast-sailing arc</b>':'')+(dead?' · <b style="color:#c22">headwind zone</b>':'')+
 (r.FordewindFineEdge?' · downwind edge ±'+r.FordewindFineEdge.toFixed(1)+'°':'')}
sel.onchange=draw;document.getElementById('ang').oninput=draw;draw();
</script>
<p class="note">The wind component is one part of ship speed. The ship's base speed, sail health, upgrades and sea state also apply.</p>
'''

COMPARE_TOOL = r'''
<p>Pick up to four ships to compare side by side. Bars are scaled to the best ship in the comparison.</p>
<div class="tool" id="pick"></div><div id="cmp"></div>
<script>
const SHIPS=__SHIPS__;const pick=document.getElementById('pick');
pick.innerHTML=[0,1,2,3].map(i=>'<label>Ship '+(i+1)+' <select data-i="'+i+'"><option value="">-</option>'+SHIPS.map((s,k)=>'<option value="'+k+'">'+s.n.replace(/</g,'&lt;')+'</option>').join('')+'</select></label>').join('');
const F=[['hp','Hull HP'],['armor','Armor'],['speed','Speed'],['mob','Mobility'],['crew','Crew'],['cargo','Cargo'],['rank','Rank']];
function render(){const chosen=[...pick.querySelectorAll('select')].map(s=>s.value).filter(v=>v!=='').map(v=>SHIPS[v]);if(!chosen.length){document.getElementById('cmp').innerHTML='';return}
 let h='<table class="wikitable"><tr><th>Stat</th>'+chosen.map(s=>'<th>'+s.n.replace(/</g,'&lt;')+'</th>').join('')+'</tr>';
 for(const [k,l] of F){const mx=Math.max(...chosen.map(s=>+s[k]||0))||1;h+='<tr><th>'+l+'</th>'+chosen.map(s=>'<td><span class="barwrap" style="width:90px"><span class="bar" style="background:#1d4e6f;width:'+Math.round(90*(+s[k]||0)/mx)+'px"></span></span>'+(s[k]??'')+'</td>').join('')+'</tr>'}
 document.getElementById('cmp').innerHTML=h+'</table>'}
pick.addEventListener('change',render);
</script>
'''


def build_site(db, out, **kw):
    return SiteBuilder(db, out, **kw).build_site()
