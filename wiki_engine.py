"""Wiki engine: full-text search, [[wikilinks]], backlinks, tags, revisions, drafts
and one safe Markdown renderer shared by the desktop editor preview, the local
web Codex and the static HTML export.

Rendering never passes raw HTML through: all text is escaped and only a fixed
set of constructs is produced. Links are limited to http(s), relative paths and
in-wiki targets.
"""
from __future__ import annotations

import html
import re
import sqlite3
from datetime import datetime, timezone

WIKILINK = re.compile(r'\[\[([^\[\]|]{1,200})(?:\|([^\[\]]{1,200}))?\]\]')
TAG_LINE = re.compile(r'^\s*tags\s*:\s*(.+)$', re.I | re.M)


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def slugify(value):
    slug = re.sub(r'[^a-z0-9]+', '-', str(value).casefold()).strip('-')
    return (slug or 'entry')[:130]


# ------------------------------------------------------------------ schema

def fts_available(conn):
    try:
        conn.execute('CREATE VIRTUAL TABLE IF NOT EXISTS temp._fts_probe USING fts5(x)')
        conn.execute('DROP TABLE IF EXISTS temp._fts_probe')
        return True
    except sqlite3.OperationalError:
        return False


def migrate(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS article_revisions (
        id INTEGER PRIMARY KEY, article_id INTEGER NOT NULL, title TEXT NOT NULL, section TEXT NOT NULL,
        body TEXT NOT NULL, review_status TEXT NOT NULL, saved_utc TEXT NOT NULL, note TEXT NOT NULL DEFAULT '');
    CREATE INDEX IF NOT EXISTS ix_revisions_article ON article_revisions(article_id, id);
    CREATE TABLE IF NOT EXISTS article_links (from_id INTEGER NOT NULL, target TEXT NOT NULL,
        PRIMARY KEY(from_id, target));
    CREATE INDEX IF NOT EXISTS ix_links_target ON article_links(target);
    CREATE TABLE IF NOT EXISTS article_tags (article_id INTEGER NOT NULL, tag TEXT NOT NULL,
        PRIMARY KEY(article_id, tag));
    CREATE INDEX IF NOT EXISTS ix_tags_tag ON article_tags(tag);
    CREATE TABLE IF NOT EXISTS article_drafts (article_id INTEGER PRIMARY KEY, title TEXT NOT NULL,
        section TEXT NOT NULL, body TEXT NOT NULL, review_status TEXT NOT NULL, saved_utc TEXT NOT NULL);
    ''')
    if fts_available(conn):
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE name='articles_fts'").fetchone()
        conn.executescript('''
        CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(
            title, section, body, content='articles', content_rowid='id', tokenize='unicode61 remove_diacritics 2');
        CREATE TRIGGER IF NOT EXISTS articles_fts_ai AFTER INSERT ON articles BEGIN
            INSERT INTO articles_fts(rowid, title, section, body) VALUES (new.id, new.title, new.section, new.body);
        END;
        CREATE TRIGGER IF NOT EXISTS articles_fts_ad AFTER DELETE ON articles BEGIN
            INSERT INTO articles_fts(articles_fts, rowid, title, section, body) VALUES('delete', old.id, old.title, old.section, old.body);
        END;
        CREATE TRIGGER IF NOT EXISTS articles_fts_au AFTER UPDATE ON articles BEGIN
            INSERT INTO articles_fts(articles_fts, rowid, title, section, body) VALUES('delete', old.id, old.title, old.section, old.body);
            INSERT INTO articles_fts(rowid, title, section, body) VALUES (new.id, new.title, new.section, new.body);
        END;
        ''')
        if not exists:
            conn.execute("INSERT INTO articles_fts(articles_fts) VALUES('rebuild')")
            # Index links/tags for every existing article once.
            for row in conn.execute('SELECT id, body FROM articles').fetchall():
                index_article(conn, row[0], row[1])
    conn.commit()


# --------------------------------------------------------- links and tags

def wikilinks(body):
    return [m.group(1).strip() for m in WIKILINK.finditer(body or '')]


def tags(body):
    found = []
    for line in TAG_LINE.findall(body or ''):
        for tag in re.split(r'[,;]', line):
            tag = tag.strip().strip('#').casefold()
            if tag and len(tag) <= 60 and tag not in found:
                found.append(tag)
    return found


def index_article(conn, article_id, body):
    conn.execute('DELETE FROM article_links WHERE from_id=?', (article_id,))
    conn.executemany('INSERT OR IGNORE INTO article_links(from_id, target) VALUES (?,?)',
                     [(article_id, slugify(t)) for t in wikilinks(body)])
    conn.execute('DELETE FROM article_tags WHERE article_id=?', (article_id,))
    conn.executemany('INSERT OR IGNORE INTO article_tags(article_id, tag) VALUES (?,?)',
                     [(article_id, t) for t in tags(body)])


def resolve(conn, target):
    """Wikilink target (title or slug) -> article row or None."""
    slug = slugify(target)
    row = conn.execute('SELECT id, slug, title FROM articles WHERE slug=?', (slug,)).fetchone()
    if row:
        return row
    return conn.execute('SELECT id, slug, title FROM articles WHERE lower(title)=lower(?) LIMIT 1',
                        (str(target).strip(),)).fetchone()


def backlinks(conn, article_id):
    row = conn.execute('SELECT slug, title FROM articles WHERE id=?', (article_id,)).fetchone()
    if not row:
        return []
    targets = {row[0], slugify(row[1])}
    marks = ','.join('?' * len(targets))
    return conn.execute(f'''SELECT DISTINCT a.id, a.slug, a.title, a.section FROM article_links l
                            JOIN articles a ON a.id=l.from_id WHERE l.target IN ({marks}) AND a.id<>?
                            ORDER BY a.title''', (*targets, article_id)).fetchall()


def article_tags(conn, article_id):
    return [r[0] for r in conn.execute('SELECT tag FROM article_tags WHERE article_id=? ORDER BY tag', (article_id,))]


def tag_cloud(conn, limit=80):
    return conn.execute('SELECT tag, count(*) n FROM article_tags GROUP BY tag ORDER BY n DESC, tag LIMIT ?',
                        (limit,)).fetchall()


def articles_with_tag(conn, tag):
    return conn.execute('''SELECT a.id, a.slug, a.title, a.section FROM article_tags t JOIN articles a
                           ON a.id=t.article_id WHERE t.tag=? ORDER BY a.title''', (tag.casefold(),)).fetchall()


# ---------------------------------------------------------------- search

def _fts_query(text):
    words = re.findall(r'[\w][\w.-]*', text, re.UNICODE)
    return ' '.join('"' + w.replace('"', '') + '"*' for w in words[:12])


def search(conn, query, *, limit=50):
    """Ranked full-text search with snippets; LIKE fallback when FTS5 is missing."""
    query = (query or '').strip()
    if not query:
        return []
    has_fts = conn.execute("SELECT 1 FROM sqlite_master WHERE name='articles_fts'").fetchone()
    if has_fts and _fts_query(query):
        try:
            return [dict(id=r[0], slug=r[1], title=r[2], section=r[3], snippet=r[4]) for r in conn.execute(
                '''SELECT a.id, a.slug, a.title, a.section,
                          snippet(articles_fts, 2, '[', ']', ' … ', 14)
                   FROM articles_fts JOIN articles a ON a.id=articles_fts.rowid
                   WHERE articles_fts MATCH ? ORDER BY bm25(articles_fts, 8.0, 2.0, 1.0) LIMIT ?''',
                (_fts_query(query), limit))]
        except sqlite3.OperationalError:
            pass
    like = '%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
    return [dict(id=r[0], slug=r[1], title=r[2], section=r[3], snippet=(r[4] or '')[:160]) for r in conn.execute(
        "SELECT id, slug, title, section, body FROM articles WHERE title LIKE ? ESCAPE '\\' OR body LIKE ? ESCAPE '\\' "
        "ORDER BY title LIMIT ?", (like, like, limit))]


# --------------------------------------------------- revisions and drafts

def save_revision(conn, article_id, note=''):
    row = conn.execute('SELECT title, section, body, review_status FROM articles WHERE id=?', (article_id,)).fetchone()
    if not row:
        return None
    last = conn.execute('SELECT body, title FROM article_revisions WHERE article_id=? ORDER BY id DESC LIMIT 1',
                        (article_id,)).fetchone()
    if last and last[0] == row[2] and last[1] == row[0]:
        return None   # nothing changed since the last snapshot
    cur = conn.execute('INSERT INTO article_revisions(article_id, title, section, body, review_status, saved_utc, note) '
                       'VALUES (?,?,?,?,?,?,?)', (article_id, row[0], row[1], row[2], row[3], utcnow(), note[:200]))
    # Keep the newest 200 revisions per article.
    conn.execute('''DELETE FROM article_revisions WHERE article_id=? AND id NOT IN
                    (SELECT id FROM article_revisions WHERE article_id=? ORDER BY id DESC LIMIT 200)''',
                 (article_id, article_id))
    return cur.lastrowid


def revisions(conn, article_id):
    return conn.execute('SELECT id, title, saved_utc, note, length(body) FROM article_revisions '
                        'WHERE article_id=? ORDER BY id DESC', (article_id,)).fetchall()


def revision(conn, revision_id):
    return conn.execute('SELECT * FROM article_revisions WHERE id=?', (revision_id,)).fetchone()


def save_draft(conn, article_id, title, section, body, review_status):
    conn.execute('''INSERT INTO article_drafts(article_id, title, section, body, review_status, saved_utc)
                    VALUES (?,?,?,?,?,?) ON CONFLICT(article_id) DO UPDATE SET title=excluded.title,
                    section=excluded.section, body=excluded.body, review_status=excluded.review_status,
                    saved_utc=excluded.saved_utc''', (article_id, title, section, body, review_status, utcnow()))
    conn.commit()


def get_draft(conn, article_id):
    return conn.execute('SELECT * FROM article_drafts WHERE article_id=?', (article_id,)).fetchone()


def clear_draft(conn, article_id):
    conn.execute('DELETE FROM article_drafts WHERE article_id=?', (article_id,))
    conn.commit()


def recent_changes(conn, limit=30):
    return conn.execute('SELECT id, slug, title, section, updated_utc, review_status FROM articles '
                        'ORDER BY updated_utc DESC LIMIT ?', (limit,)).fetchall()


# --------------------------------------------------------------- markdown

def _esc(text):
    return html.escape(str(text), quote=True)


def _safe_href(url):
    url = url.strip()
    if re.match(r'^(https?://|/|\./|\.\./|#)[^\s"<>]*$', url) and not url.lower().startswith('//'):
        return url
    if re.match(r'^[\w./-]+$', url) and ':' not in url:
        return url
    return None


def render_inline(text, link_for=None):
    """Escape, then apply inline code, wikilinks, links, bold and italics."""
    placeholders = []

    def keep(fragment):
        placeholders.append(fragment)
        return f'\x00{len(placeholders) - 1}\x00'

    text = re.sub(r'`([^`]+)`', lambda m: keep('<code>' + _esc(m.group(1)) + '</code>'), str(text))

    def wiki(m):
        target, label = m.group(1).strip(), (m.group(2) or m.group(1)).strip()
        href, exists = (link_for(target) if link_for else ('/article/' + slugify(target), True))
        cls = '' if exists else ' class="missing"'
        return keep(f'<a href="{_esc(href)}"{cls}>{_esc(label)}</a>')
    text = WIKILINK.sub(wiki, text)

    def link(m):
        href = _safe_href(m.group(2))
        return keep(f'<a href="{_esc(href)}" rel="noopener">{_esc(m.group(1))}</a>') if href else keep(_esc(m.group(0)))
    text = re.sub(r'\[([^\]]{1,300})\]\(([^)\s]{1,800})\)', link, text)
    text = _esc(text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])', r'<em>\1</em>', text)
    text = re.sub(r'~~(.+?)~~', r'<del>\1</del>', text)
    return re.sub('\x00(\\d+)\x00', lambda m: placeholders[int(m.group(1))], text)


def render_markdown(src, link_for=None, *, heading_offset=1):
    """Headings, paragraphs, lists (bulleted, numbered, task), blockquotes, fenced code,
    tables, rules and inline formatting. Returns HTML."""
    out = []; lines = str(src or '').splitlines(); i = 0
    para = []

    def flush_para():
        if para:
            out.append('<p>' + render_inline(' '.join(para), link_for) + '</p>'); para.clear()

    while i < len(lines):
        line = lines[i].rstrip(); stripped = line.strip()
        if stripped.startswith('```'):
            flush_para()
            lang = re.sub(r'[^\w-]', '', stripped[3:])[:20]
            code = []; i += 1
            while i < len(lines) and not lines[i].strip().startswith('```'):
                code.append(lines[i]); i += 1
            out.append(f'<pre><code class="lang-{lang}">' + _esc('\n'.join(code)) + '</code></pre>' if lang
                       else '<pre><code>' + _esc('\n'.join(code)) + '</code></pre>')
            i += 1; continue
        if not stripped:
            flush_para(); i += 1; continue
        if TAG_LINE.match(line):
            flush_para()
            found = tags(line)
            out.append('<p class="tags">' + ' '.join(f'<a class="tag" href="/tag/{_esc(t)}">#{_esc(t)}</a>' for t in found) + '</p>')
            i += 1; continue
        heading = re.match(r'^(#{1,6})\s+(.+?)\s*#*$', stripped)
        if heading:
            flush_para()
            level = min(6, len(heading.group(1)) + heading_offset)
            anchor = slugify(heading.group(2))
            out.append(f'<h{level} id="{anchor}">' + render_inline(heading.group(2), link_for) + f'</h{level}>')
            i += 1; continue
        if re.match(r'^(-{3,}|\*{3,}|_{3,})$', stripped):
            flush_para(); out.append('<hr>'); i += 1; continue
        if stripped.startswith('|') and i + 1 < len(lines) and re.match(r'^\|?\s*:?-{2,}', lines[i + 1].strip()):
            flush_para()
            def cells(row):
                return [c.strip() for c in row.strip().strip('|').split('|')]
            head = cells(stripped); i += 2; body = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                body.append(cells(lines[i])); i += 1
            table = '<div class="table-wrap"><table><thead><tr>' + ''.join('<th>' + render_inline(c, link_for) + '</th>' for c in head) + '</tr></thead><tbody>'
            table += ''.join('<tr>' + ''.join('<td>' + render_inline(c, link_for) + '</td>' for c in row) + '</tr>' for row in body)
            out.append(table + '</tbody></table></div>'); continue
        if stripped.startswith('>'):
            flush_para(); quote = []
            while i < len(lines) and lines[i].strip().startswith('>'):
                quote.append(lines[i].strip()[1:].lstrip()); i += 1
            out.append('<blockquote>' + render_markdown('\n'.join(quote), link_for, heading_offset=heading_offset) + '</blockquote>')
            continue
        bullet = re.match(r'^\s*([-*+]|\d+[.)])\s+(.*)$', line)
        if bullet:
            flush_para()
            ordered = bullet.group(1)[0].isdigit()
            items = []
            while i < len(lines):
                m = re.match(r'^\s*([-*+]|\d+[.)])\s+(.*)$', lines[i])
                if not m or m.group(1)[0].isdigit() != ordered:
                    break
                text = m.group(2)
                task = re.match(r'^\[( |x|X)\]\s+(.*)$', text)
                if task:
                    box = '☑' if task.group(1).lower() == 'x' else '☐'
                    items.append(f'<li class="task">{box} ' + render_inline(task.group(2), link_for) + '</li>')
                else:
                    items.append('<li>' + render_inline(text, link_for) + '</li>')
                i += 1
            tag = 'ol' if ordered else 'ul'
            out.append(f'<{tag}>' + ''.join(items) + f'</{tag}>'); continue
        para.append(stripped); i += 1
    flush_para()
    return '\n'.join(out)


def table_of_contents(src):
    """[(level, text, anchor)] for headings, used for article sidebars."""
    toc = []
    for line in str(src or '').splitlines():
        m = re.match(r'^(#{1,4})\s+(.+?)\s*#*$', line.strip())
        if m:
            toc.append((len(m.group(1)), m.group(2), slugify(m.group(2))))
    return toc


def link_resolver(conn, *, prefix='/article/'):
    """Return a link_for(target) closure that marks missing articles."""
    cache = {}

    def link_for(target):
        if target not in cache:
            row = resolve(conn, target)
            cache[target] = ((prefix + row[1]) if row else (prefix + slugify(target)), bool(row))
        return cache[target]
    return link_for
