"""SQLite-backed, provenance-aware offline encyclopedia and extraction archive."""
from __future__ import annotations

import csv
import hashlib
import html
import json
import os
import re
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

VERSION = '4.5.2'

def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')

def home():
    override = os.environ.get('WOSB_WORKBENCH_HOME')
    if override:
        return Path(override).expanduser().resolve()
    if os.name == 'nt':
        return Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'WoSBWorkbench'
    return Path.home() / '.local' / 'share' / 'WoSBWorkbench'

def bundled_path(filename):
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)) / filename

def slugify(value):
    slug = re.sub(r'[^a-z0-9]+', '-', value.casefold()).strip('-')
    return (slug or 'entry')[:130]

def record_key(record, index):
    for field in ('ID', 'Id', 'id', 'Key', 'Name', 'SourceRecord'):
        if field in record and record[field] not in (None, ''):
            return str(record[field])[:320]
    return f'row-{index}'

def record_name(record, identifier):
    for name in ('EnglishName', 'NameEnglish', 'Name', 'Title', 'IDEnglish', 'name'):
        val = record.get(name)
        if isinstance(val, (str, int, float)) and str(val).strip():
            return str(val).strip()[:300]
    return str(identifier)[:300]

class CatalogDB:
    def __init__(self, filename=None):
        self.path = Path(filename or (home() / 'Workbench.sqlite3'))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists() and filename is None:
            seed = bundled_path('Starter-Catalog.sqlite3')
            if seed.is_file():
                shutil.copy2(seed, self.path)
        self.conn = sqlite3.connect(str(self.path), timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.conn.execute('PRAGMA busy_timeout=30000')
        self.conn.execute('PRAGMA foreign_keys=ON')
        self.migrate()

    def migrate(self):
        self.conn.executescript('''
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY, dataset TEXT NOT NULL, source_root TEXT NOT NULL,
            external_id TEXT NOT NULL, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
            source_file TEXT NOT NULL DEFAULT '', raw_json TEXT NOT NULL,
            sha256 TEXT NOT NULL, imported_utc TEXT NOT NULL,
            UNIQUE(dataset, source_root, external_id)
        );
        CREATE INDEX IF NOT EXISTS ix_records_lookup ON records(dataset, name COLLATE NOCASE);
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY, slug TEXT UNIQUE NOT NULL, title TEXT NOT NULL,
            section TEXT NOT NULL DEFAULT 'General', body TEXT NOT NULL DEFAULT '',
            source_kind TEXT NOT NULL DEFAULT 'manual', source_ref TEXT NOT NULL DEFAULT '',
            review_status TEXT NOT NULL DEFAULT 'draft', is_user_edited INTEGER NOT NULL DEFAULT 0,
            created_utc TEXT NOT NULL, updated_utc TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_articles_section ON articles(section, title COLLATE NOCASE);
        CREATE TABLE IF NOT EXISTS combat_evidence (
            id INTEGER PRIMARY KEY, source_root TEXT NOT NULL, assembly TEXT NOT NULL,
            token TEXT NOT NULL, full_name TEXT NOT NULL, topics TEXT NOT NULL,
            evidence_json TEXT NOT NULL, source_file TEXT NOT NULL,
            UNIQUE(source_root, assembly, token)
        );
        CREATE INDEX IF NOT EXISTS ix_combat_search ON combat_evidence(full_name);
        CREATE TABLE IF NOT EXISTS ship_viewers (
            slug TEXT PRIMARY KEY, ship_name TEXT NOT NULL, ship_id TEXT NOT NULL,
            source_build TEXT NOT NULL DEFAULT '', html_path TEXT NOT NULL,
            created_utc TEXT NOT NULL, note TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS import_history (
            id INTEGER PRIMARY KEY, source TEXT NOT NULL, kind TEXT NOT NULL,
            new_rows INTEGER NOT NULL, updated_rows INTEGER NOT NULL,
            finished_utc TEXT NOT NULL, notes TEXT NOT NULL DEFAULT ''
        );
        ''')
        self.conn.execute('''CREATE TABLE IF NOT EXISTS discovery_findings (
          key TEXT PRIMARY KEY,category TEXT NOT NULL,severity TEXT NOT NULL,title TEXT NOT NULL,
          description TEXT NOT NULL,count INTEGER NOT NULL,evidence TEXT NOT NULL,action TEXT NOT NULL,
          source TEXT NOT NULL,sample_json TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'open',updated_utc TEXT NOT NULL)''')
        self.conn.execute('''CREATE TABLE IF NOT EXISTS discovery_runs
          (id INTEGER PRIMARY KEY,source TEXT NOT NULL,roots_json TEXT NOT NULL,
           finding_count INTEGER NOT NULL,run_utc TEXT NOT NULL)''')
        self.conn.commit()
        import wiki_engine
        wiki_engine.migrate(self.conn)

    def close(self):
        self.conn.close()

    def setting(self, key, default=''):
        row = self.conn.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return row['value'] if row else default

    def set_setting(self, key, value):
        self.conn.execute('INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, value))
        self.conn.commit()

    def register_ship_viewer(self,slug,ship_name,ship_id,source_build,html_path,note=''):
        self.conn.execute('''INSERT INTO ship_viewers(slug,ship_name,ship_id,source_build,html_path,created_utc,note)
            VALUES(?,?,?,?,?,?,?) ON CONFLICT(slug) DO UPDATE SET
            ship_name=excluded.ship_name,ship_id=excluded.ship_id,source_build=excluded.source_build,
            html_path=excluded.html_path,created_utc=excluded.created_utc,note=excluded.note''',
            (slug,ship_name,str(ship_id),source_build,str(html_path),utcnow(),note[:300]))
        self.conn.commit()

    def list_ship_viewers(self):
        return self.conn.execute('SELECT * FROM ship_viewers ORDER BY ship_name COLLATE NOCASE').fetchall()

    def stats(self):
        return {table:self.conn.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
                for table in ('records','articles','combat_evidence','import_history')}

    def categories(self):
        return [(r['dataset'],r['n']) for r in self.conn.execute(
            'SELECT dataset,count(*) n FROM records GROUP BY dataset ORDER BY dataset COLLATE NOCASE')]

    def upsert_record(self, dataset, source_root, record, index, source='', *, commit=False):
        if not isinstance(record, dict):
            return False
        key=record_key(record,index)
        name=record_name(record,key)
        description=str(record.get('EnglishDescription') or record.get('Description') or '')[:20000]
        src=str(record.get('Source') or source)[:600]
        raw=json.dumps(record,ensure_ascii=False,separators=(',',':'),sort_keys=True,default=str)
        hashval=hashlib.sha256(raw.encode('utf-8')).hexdigest()
        prior=self.conn.execute('SELECT sha256 FROM records WHERE dataset=? AND source_root=? AND external_id=?',
                  (dataset,source_root,key)).fetchone()
        if prior and prior['sha256']==hashval:
            return False
        self.conn.execute('''INSERT INTO records(dataset,source_root,external_id,name,description,source_file,raw_json,sha256,imported_utc)
              VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(dataset,source_root,external_id) DO UPDATE SET
              name=excluded.name,description=excluded.description,source_file=excluded.source_file,
              raw_json=excluded.raw_json,sha256=excluded.sha256,imported_utc=excluded.imported_utc''',
              (dataset,source_root,key,name,description,src,raw,hashval,utcnow()))
        if commit:self.conn.commit()
        if dataset=='Gamepedia':
            self._gamepedia_article(record,key,name,src)
        return True

    def _gamepedia_article(self,record,key,title,src):
        slug='gamepedia-'+slugify(key)
        desc=str(record.get('EnglishDescription') or '').strip()
        body=('## '+title+'\n\n'+desc if desc else '## '+title+'\n\n*Gamepedia entry imported from client data; explanatory text has not yet been recovered.*')
        body+='\n\n### Source\n\nClient record: `'+key.replace('`','')+'`\nFile: `'+src.replace('`','')+'`'
        self.upsert_article(slug,title,'Gamepedia',body,'client-gamepedia',src,'source-only', preserve_edited=True)

    def upsert_article(self, slug, title, section, body, source_kind='manual', source_ref='',
                       review_status='draft', preserve_edited=True, user_edit=False):
        row=self.conn.execute('SELECT id,is_user_edited FROM articles WHERE slug=?',(slug,)).fetchone()
        if row and preserve_edited and row['is_user_edited']:
            return row['id']
        self.conn.execute('''INSERT INTO articles(slug,title,section,body,source_kind,source_ref,review_status,is_user_edited,created_utc,updated_utc)
            VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(slug) DO UPDATE SET
            title=excluded.title, section=excluded.section, body=excluded.body,
            source_kind=excluded.source_kind, source_ref=excluded.source_ref,
            review_status=excluded.review_status, is_user_edited=excluded.is_user_edited,
            updated_utc=excluded.updated_utc''',
            (slug,title,section,body,source_kind,source_ref,review_status,int(user_edit),utcnow(),utcnow()))
        aid=self.conn.execute('SELECT id FROM articles WHERE slug=?',(slug,)).fetchone()[0]
        import wiki_engine
        wiki_engine.index_article(self.conn,aid,body)
        return aid

    def save_article(self, aid, title, section, body, review_status, note=''):
        import wiki_engine
        # Snapshot the previous version so every edit can be compared or restored.
        wiki_engine.save_revision(self.conn,aid,note or 'before edit')
        self.conn.execute('''UPDATE articles SET title=?,section=?,body=?,review_status=?,
            is_user_edited=1,updated_utc=? WHERE id=?''',(title,section,body,review_status,utcnow(),aid))
        wiki_engine.index_article(self.conn,aid,body)
        self.conn.execute('DELETE FROM article_drafts WHERE article_id=?',(aid,))
        self.conn.commit()

    def restore_revision(self, aid, revision_id):
        import wiki_engine
        rev=wiki_engine.revision(self.conn,revision_id)
        if rev is None or rev['article_id']!=aid:raise ValueError('Revision does not belong to this article')
        self.save_article(aid,rev['title'],rev['section'],rev['body'],rev['review_status'],note='before restore')

    def new_article(self,title,section='Guides'):
        base=slugify(title)
        slug=base
        i=2
        while self.conn.execute('SELECT 1 FROM articles WHERE slug=?',(slug,)).fetchone():
            slug=f'{base}-{i}';i+=1
        aid=self.upsert_article(slug,title,section,'# '+title+'\n\n',user_edit=True)
        self.conn.commit()
        return aid

    def article(self,aid):
        return self.conn.execute('SELECT * FROM articles WHERE id=?',(aid,)).fetchone()

    def list_articles(self, query='', section='', limit=500):
        criteria=['1=1']; vals=[]
        if query:
            criteria.append('(title LIKE ? OR body LIKE ? OR source_ref LIKE ?)')
            vals.extend(('%'+query+'%',)*3)
        if section:
            criteria.append('section=?'); vals.append(section)
        return self.conn.execute('SELECT id,title,section,review_status,source_kind FROM articles WHERE '
            +' AND '.join(criteria)+' ORDER BY section,title COLLATE NOCASE LIMIT ?',(*vals,limit)).fetchall()

    def list_records(self,query='',dataset='',limit=350):
        criteria=['1=1']; vals=[]
        if query:
            criteria.append('(name LIKE ? OR description LIKE ? OR external_id LIKE ?)'); vals.extend(('%'+query+'%',)*3)
        if dataset:
            criteria.append('dataset=?');vals.append(dataset)
        return self.conn.execute('SELECT id,dataset,name,source_root,external_id FROM records WHERE '
             +' AND '.join(criteria)+' ORDER BY dataset,name COLLATE NOCASE LIMIT ?',(*vals,limit)).fetchall()

    def record(self,rid):
        return self.conn.execute('SELECT * FROM records WHERE id=?',(rid,)).fetchone()

    def upsert_combat(self,source_root,record,source_file):
        name=str(record.get('full_name') or record.get('fullname') or record.get('method') or record.get('name') or '')
        if not name:return False
        asm=str(record.get('assembly') or record.get('source') or '')
        token=str(record.get('token') or record.get('method_token') or name)
        topics=record.get('topics', '')
        if isinstance(topics,list): topics=', '.join(map(str,topics))
        self.conn.execute('''INSERT INTO combat_evidence(source_root,assembly,token,full_name,topics,evidence_json,source_file)
            VALUES(?,?,?,?,?,?,?) ON CONFLICT(source_root,assembly,token) DO UPDATE SET
            full_name=excluded.full_name,topics=excluded.topics,evidence_json=excluded.evidence_json,
            source_file=excluded.source_file''',
            (source_root,asm,token,name,str(topics),json.dumps(record,ensure_ascii=False,default=str),source_file))
        return True

    def list_combat(self,query='',limit=300):
        return self.conn.execute('''SELECT id,full_name,topics,assembly,source_root FROM combat_evidence
            WHERE full_name LIKE ? OR topics LIKE ? ORDER BY
            CASE WHEN lower(full_name) LIKE '%serverburning%' THEN 0 ELSE 1 END, full_name LIMIT ?''',
            ('%'+query+'%','%'+query+'%',limit)).fetchall()

    def combat(self,rid):
        return self.conn.execute('SELECT * FROM combat_evidence WHERE id=?',(rid,)).fetchone()

    def log_import(self,source,kind,updated,notes=''):
        self.conn.execute('INSERT INTO import_history(source,kind,new_rows,updated_rows,finished_utc,notes) VALUES(?,?,?,?,?,?)',
                          (str(source)[:1000],kind,0,updated,utcnow(),notes))
        self.conn.commit()

    def backup(self,dest):
        dest=Path(dest);dest.parent.mkdir(parents=True,exist_ok=True)
        target=sqlite3.connect(str(dest))
        try:
            self.conn.backup(target)
        finally:
            target.close()
        return dest

    def export_json(self,path,include_raw=False):
        out={'version':VERSION,'exported_utc':utcnow(),
             'articles':[dict(row) for row in self.conn.execute('SELECT * FROM articles ORDER BY slug')],
             'datasets':[{ 'dataset':r[0],'count':r[1]} for r in self.categories()]}
        if include_raw:
            out['records']=[dict(row) for row in self.conn.execute('SELECT * FROM records ORDER BY id')]
            out['combat_evidence']=[dict(row) for row in self.conn.execute('SELECT * FROM combat_evidence ORDER BY id')]
        Path(path).write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
        return out

    def export_csv(self,folder):
        folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
        for name,columns in (('articles',('slug','title','section','body','review_status','source_kind','source_ref','updated_utc')),
                             ('records',('dataset','source_root','external_id','name','description','source_file','raw_json')),
                             ('combat_evidence',('source_root','assembly','token','full_name','topics','evidence_json','source_file'))):
            with (folder/(name+'.csv')).open('w',encoding='utf-8-sig',newline='') as handle:
                writer=csv.writer(handle);writer.writerow(columns)
                for row in self.conn.execute(f'SELECT {",".join(columns)} FROM {name}'):
                    writer.writerow([row[c] if row[c] is not None else '' for c in columns])

    def export_wiki(self,folder):
        """Static offline HTML with escaped content and no remote scripts."""
        folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
        articles=[dict(r) for r in self.conn.execute('SELECT slug,title,section,body,source_ref,review_status FROM articles ORDER BY section,title')]
        stylesheet='''<style>body{background:#0d1724;color:#e8f1fa;font:16px system-ui;max-width:960px;margin:auto;padding:35px}a{color:#7bcfff}header{border-bottom:1px solid #44566b;padding-bottom:16px}article{line-height:1.65}p,li{overflow-wrap:anywhere}.meta{color:#a7b8cd}input{width:100%;padding:12px;background:#1b2b3d;color:#fff;border:1px solid #4a657e}section{border-bottom:1px solid #33465b;padding:12px 0}code{background:#24374c;padding:2px 4px}</style>'''
        import wiki_engine
        known={wiki_engine.slugify(a['slug']):a['slug'] for a in articles}
        known.update({wiki_engine.slugify(a['title']):a['slug'] for a in articles})
        def link_for(target):
            slug=known.get(wiki_engine.slugify(target))
            safe=re.sub('[^a-zA-Z0-9_-]','-',slug or wiki_engine.slugify(target))
            return safe+'.html',bool(slug)
        def md2html(md):
            # Offline export: tag chips filter the exported index instead of a server route.
            return wiki_engine.render_markdown(md,link_for).replace('href="/tag/','href="index.html#')
        index=[]
        for a in articles:
            slug=re.sub('[^a-zA-Z0-9_-]','-',a['slug'])
            index.append((a['section'],a['title'],slug))
            page='<!doctype html><meta charset="utf-8">'+stylesheet+'<header><a href="index.html">← WoSB Workbench Wiki</a></header><article><h1>'+html.escape(a['title'])+'</h1>'+md2html(a['body'])+'<p class="meta">Status: '+html.escape(a['review_status'])+' · Source: '+html.escape(a['source_ref'])+'</p></article>'
            (folder/(slug+'.html')).write_text(page,encoding='utf-8')
        rows=''.join('<section data-search="'+html.escape((sec+' '+title).lower(),quote=True)+'"><a href="'+html.escape(slug,quote=True)+'.html">'+html.escape(title)+'</a> <span class="meta">'+html.escape(sec)+'</span></section>' for sec,title,slug in index)
        # Export registered self-contained viewers, never raw game binaries.
        viewers=self.list_ship_viewers()
        if viewers:
            child=folder/'interactive-ships';child.mkdir(exist_ok=True)
            for view in viewers:
                source=Path(view['html_path'])
                if not source.is_file():continue
                filename=re.sub(r'[^a-zA-Z0-9_-]','-',view['slug'])+'.html'
                shutil.copyfile(source,child/filename)
                rows += '<section data-search="'+html.escape(('ship 3d '+view['ship_name']).lower(),quote=True)+'"><a href="interactive-ships/'+filename+'">Interactive 3D: '+html.escape(view['ship_name'])+'</a> <span class="meta">Ship models &amp; hitboxes</span></section>'
        indexhtml='''<!doctype html><html lang="en"><meta charset="utf-8"><title>WoSB Workbench Wiki</title>'''+stylesheet+'''<header><h1>World of Sea Battle · Offline Wiki</h1><p>Exported from WoSB Workbench</p><input id="search" placeholder="Search articles" oninput="filter()"></header><main>'''+rows+'''</main><script>function filter(){let q=document.getElementById('search').value.toLowerCase();document.querySelectorAll('main section').forEach(x=>x.hidden=!x.dataset.search.includes(q))}
if(location.hash.length>1){document.getElementById('search').value=decodeURIComponent(location.hash.slice(1));filter()}</script></html>'''
        (folder/'index.html').write_text(indexhtml,encoding='utf-8')
        return folder/'index.html'
