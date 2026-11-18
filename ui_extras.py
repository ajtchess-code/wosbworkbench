"""Reusable Tk components for WoSB Workbench (v4.3.6 UX work).

Toasts, Activity panel, error dialog, first-run setup wizard, JSON result
viewer with sortable tables, global search, Markdown preview, wiki history and
the Protocol message browser with a field-schema editor.
"""
from __future__ import annotations

import json
import os
import re
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import theme


def _open_path(path):
    path = Path(path)
    if os.name == 'nt' and path.exists():
        os.startfile(str(path))   # noqa: S606
        return True
    return False


def _text(parent, colors, **kw):
    kw.setdefault('wrap', 'word')
    return tk.Text(parent, bg=colors['PANEL'], fg=colors['TEXT'], insertbackground=colors['TEXT'],
                   selectbackground=colors['TEXT_SELECT'], relief='flat', borderwidth=8,
                   font=theme.mono(10), **kw)


def _scrolled_tree(parent, columns, *, show='headings', height=12):
    frame = ttk.Frame(parent)
    tree = ttk.Treeview(frame, columns=columns, show=show, height=height)
    bar = ttk.Scrollbar(frame, orient='vertical', command=tree.yview)
    tree.configure(yscrollcommand=bar.set)
    tree.pack(side='left', fill='both', expand=True); bar.pack(side='right', fill='y')
    return frame, tree


def make_sortable(tree, columns):
    """Click a heading to sort; numbers sort numerically."""
    def sort(col, reverse):
        rows = [(tree.set(k, col), k) for k in tree.get_children('')]
        def key(item):
            value = item[0]
            try:
                return (0, float(str(value).replace(',', '')))
            except ValueError:
                return (1, str(value).casefold())
        rows.sort(key=key, reverse=reverse)
        for index, (_, k) in enumerate(rows):
            tree.move(k, '', index)
        tree.heading(col, command=lambda: sort(col, not reverse))
    for col in columns:
        tree.heading(col, text=col.replace('_', ' ').title(), command=lambda c=col: sort(c, False))


# ------------------------------------------------------------------ toasts

class Toasts:
    """Non-blocking notifications stacked at the bottom-right of the window."""
    def __init__(self, root, colors, *, history=None):
        self.root = root; self.colors = colors; self.active = []
        self.history = history if history is not None else []

    def show(self, title, message, *, kind='info', seconds=7, action=None):
        self.history.append({'time': time.strftime('%H:%M:%S'), 'title': str(title), 'message': str(message), 'kind': kind})
        del self.history[:-300]
        c = self.colors
        accent = {'info': c['ACCENT'], 'success': c['GREEN'], 'warning': c['WARN'], 'error': c['DANGER']}.get(kind, c['ACCENT'])
        frame = tk.Frame(self.root, bg=c['PANEL'], highlightthickness=1, highlightbackground=accent)
        tk.Frame(frame, bg=accent, width=5).pack(side='left', fill='y')
        body = tk.Frame(frame, bg=c['PANEL']); body.pack(side='left', fill='both', expand=True, padx=12, pady=9)
        tk.Label(body, text=str(title), bg=c['PANEL'], fg=c['TEXT'], font=theme.font(10, bold=True),
                 anchor='w', justify='left').pack(fill='x')
        text = str(message)
        tk.Label(body, text=text[:420] + ('…' if len(text) > 420 else ''), bg=c['PANEL'], fg=c['MUTED'],
                 font=theme.font(9), wraplength=360, anchor='w', justify='left').pack(fill='x')
        buttons = tk.Frame(body, bg=c['PANEL']); buttons.pack(fill='x', pady=(4, 0))
        if action:
            label, callback = action
            tk.Button(buttons, text=label, command=lambda: (callback(), self._close(frame)), bg=c['PANEL2'], fg=c['TEXT'],
                      relief='flat', bd=0, padx=8, pady=2, cursor='hand2').pack(side='left')
        tk.Button(buttons, text='Dismiss', command=lambda: self._close(frame), bg=c['PANEL'], fg=c['MUTED'],
                  relief='flat', bd=0, padx=8, pady=2, cursor='hand2').pack(side='right')
        self.active.append(frame); self._layout()
        if seconds:
            self.root.after(int(seconds * 1000), lambda: self._close(frame))
        return frame

    def _close(self, frame):
        if frame in self.active:
            self.active.remove(frame)
            try:
                frame.destroy()
            except tk.TclError:
                pass
            self._layout()

    def _layout(self):
        y = -18
        for frame in reversed(self.active[-4:]):
            frame.place(relx=1.0, rely=1.0, x=-18, y=y, anchor='se', width=410)
            frame.update_idletasks()
            y -= max(70, frame.winfo_reqheight()) + 10
        for frame in self.active[:-4]:
            frame.place_forget()


# ------------------------------------------------------------ error dialog

def show_error_dialog(root, colors, title, details, path=None):
    win = tk.Toplevel(root); win.title('WoSB Workbench — something went wrong'); win.configure(bg=colors['NAVY'])
    win.geometry('720x460'); win.transient(root)
    ttk.Label(win, text='An unexpected error occurred', style='Section.TLabel').pack(anchor='w', padx=18, pady=(16, 4))
    ttk.Label(win, text=str(title)[:300], wraplength=660).pack(anchor='w', padx=18)
    ttk.Label(win, text='Your data is safe. The details were saved' + (f' to {path}' if path else ' to the log') +
              '. Please include them when reporting the problem.', style='Muted.TLabel', wraplength=660).pack(anchor='w', padx=18, pady=(6, 8))
    box = _text(win, colors, height=12); box.pack(fill='both', expand=True, padx=18)
    box.insert('1.0', details); box.configure(state='disabled')
    row = ttk.Frame(win); row.pack(fill='x', padx=18, pady=12)

    def copy():
        win.clipboard_clear(); win.clipboard_append(details)
    ttk.Button(row, text='Copy details', command=copy).pack(side='left')
    ttk.Button(row, text='Open logs folder', command=lambda: __import__('applog').open_log_folder()).pack(side='left', padx=8)
    ttk.Button(row, text='Close', style='Accent.TButton', command=win.destroy).pack(side='right')
    return win


# --------------------------------------------------------------- activity

class ActivityPanel:
    """Window listing background jobs (progress, cancel, output, log) and notifications."""
    def __init__(self, root, colors, jobs, notifications):
        self.root = root; self.colors = colors; self.jobs = jobs; self.notifications = notifications
        self.win = None

    def open(self):
        if self.win is not None and self.win.winfo_exists():
            self.win.deiconify(); self.win.lift(); return
        self.win = win = tk.Toplevel(self.root); win.title('Activity'); win.geometry('980x520')
        win.configure(bg=self.colors['NAVY'])
        notebook = ttk.Notebook(win); notebook.pack(fill='both', expand=True, padx=12, pady=12)
        jobs_tab = ttk.Frame(notebook); notes_tab = ttk.Frame(notebook)
        notebook.add(jobs_tab, text='Background jobs'); notebook.add(notes_tab, text='Notifications')
        cols = ('job', 'status', 'progress', 'elapsed', 'message')
        frame, self.tree = _scrolled_tree(jobs_tab, cols, height=14)
        for col, width in zip(cols, (240, 90, 80, 70, 420)):
            self.tree.heading(col, text=col.title()); self.tree.column(col, width=width, stretch=col == 'message')
        frame.pack(fill='both', expand=True)
        buttons = ttk.Frame(jobs_tab); buttons.pack(fill='x', pady=(8, 0))
        ttk.Button(buttons, text='Cancel selected', command=self._cancel).pack(side='left')
        ttk.Button(buttons, text='Open output', command=self._output).pack(side='left', padx=8)
        ttk.Button(buttons, text='Show log / error', command=self._log).pack(side='left')
        ncols = ('time', 'kind', 'title', 'message')
        nframe, self.notes = _scrolled_tree(notes_tab, ncols, height=16)
        for col, width in zip(ncols, (80, 70, 220, 560)):
            self.notes.heading(col, text=col.title()); self.notes.column(col, width=width, stretch=col == 'message')
        nframe.pack(fill='both', expand=True)
        self._refresh()

    def _selected(self):
        sel = self.tree.selection() if self.win else ()
        return self.jobs.get(int(sel[0])) if sel else None

    def _cancel(self):
        job = self._selected()
        if job:
            self.jobs.cancel(job.id)

    def _output(self):
        job = self._selected()
        if job and job.output and not _open_path(job.output):
            messagebox.showinfo('Output', job.output, parent=self.win)

    def _log(self):
        job = self._selected()
        if not job:
            return
        win = tk.Toplevel(self.win); win.title(job.name); win.geometry('760x420')
        box = _text(win, self.colors); box.pack(fill='both', expand=True)
        box.insert('1.0', '\n'.join(job.log) + ('\n\n' + job.traceback if job.traceback else '') or 'No log lines.')

    def _refresh(self):
        if self.win is None or not self.win.winfo_exists():
            return
        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for row in self.jobs.snapshot():
            progress = '—' if row['progress'] is None else f"{row['progress'] * 100:.0f}%"
            self.tree.insert('', 'end', iid=str(row['id']), values=(row['name'], row['status'], progress,
                             f"{row['elapsed']:.0f}s", row['error'] or row['message']))
        for iid in selected:
            if self.tree.exists(iid):
                self.tree.selection_set(iid)
        self.notes.delete(*self.notes.get_children())
        for i, n in enumerate(reversed(self.notifications[-300:])):
            self.notes.insert('', 'end', iid=str(i), values=(n['time'], n['kind'], n['title'], n['message'][:300]))
        self.win.after(900, self._refresh)


# ------------------------------------------------------------ setup wizard

class SetupWizard:
    """First-run (and on-demand) setup: installs, helper tools, capture and look."""
    def __init__(self, root, colors, settings, *, on_saved=None):
        self.root = root; self.colors = colors; self.settings = settings; self.on_saved = on_saved

    def open(self):
        import install_detect
        win = tk.Toplevel(self.root); win.title('WoSB Workbench setup'); win.geometry('900x720')
        win.configure(bg=self.colors['NAVY']); win.transient(self.root)
        ttk.Label(win, text='Set up WoSB Workbench', style='Title.TLabel').pack(anchor='w', padx=22, pady=(18, 2))
        ttk.Label(win, text='Your installs were searched automatically (Steam libraries, registry and common folders). '
                  'Adjust anything below; you can rerun this from Settings at any time.',
                  style='Muted.TLabel', wraplength=840).pack(anchor='w', padx=22, pady=(0, 12))
        try:
            found = install_detect.detect_installs(extra=self.settings.game_roots())
        except Exception as exc:   # detection is a convenience, never fatal
            found = {'game': [], 'steam': [], 'launcher': []}
            ttk.Label(win, text='Detection failed: ' + str(exc), style='Warn.TLabel').pack(anchor='w', padx=22)
        box = ttk.LabelFrame(win, text='Game installations (read-only)', padding=12); box.pack(fill='x', padx=22, pady=6)
        self.vars = {}
        for row, (key, label) in enumerate((('game', 'Standalone client'), ('steam', 'Steam client'), ('launcher', 'Launcher'))):
            current = self.settings.get('installs.' + key) or (found.get(key) or [''])[0]
            var = tk.StringVar(value=current); self.vars[key] = var
            ttk.Label(box, text=label, width=18).grid(row=row, column=0, sticky='w', pady=4)
            combo = ttk.Combobox(box, textvariable=var, values=found.get(key, []), width=80)
            combo.grid(row=row, column=1, sticky='ew', padx=6)
            ttk.Button(box, text='Browse', style='Small.TButton',
                       command=lambda v=var: v.set(filedialog.askdirectory(parent=win) or v.get())).grid(row=row, column=2)
            hint = f'{len(found.get(key, []))} found' if found.get(key) else 'not found'
            ttk.Label(box, text=hint, style='Muted.TLabel').grid(row=row, column=3, padx=6)
        box.columnconfigure(1, weight=1)
        tools = ttk.LabelFrame(win, text='Helper tools', padding=12); tools.pack(fill='x', padx=22, pady=6)
        try:
            detected = install_detect.detect_tools()
        except Exception:
            detected = {}
        for row, (name, info) in enumerate(detected.items()):
            ok = info['found']
            ttk.Label(tools, text=('✔ ' if ok else '✖ ') + name, width=14,
                      style='TLabel' if ok else 'Warn.TLabel').grid(row=row, column=0, sticky='w')
            ttk.Label(tools, text=info['purpose'], style='Muted.TLabel').grid(row=row, column=1, sticky='w')
            if not ok:
                url = info['get_it'].split(' ')[0]
                ttk.Button(tools, text='Get it', style='Small.TButton',
                           command=lambda u=url: webbrowser.open(u)).grid(row=row, column=2, padx=6)
        cap = ttk.LabelFrame(win, text='Capture', padding=12); cap.pack(fill='x', padx=22, pady=6)
        self.port = tk.StringVar(value=str(self.settings.get('capture.port', 23771)))
        self.iface = tk.StringVar(value=str(self.settings.get('capture.interface', '')))
        self.auto = tk.BooleanVar(value=bool(self.settings.get('capture.auto_capture', False)))
        ttk.Label(cap, text='Game port').grid(row=0, column=0, sticky='w')
        ttk.Entry(cap, textvariable=self.port, width=8).grid(row=0, column=1, sticky='w', padx=6)
        ttk.Label(cap, text='Capture adapter # (blank = auto-detect)').grid(row=0, column=2, sticky='w', padx=(18, 0))
        ttk.Entry(cap, textvariable=self.iface, width=6).grid(row=0, column=3, sticky='w', padx=6)
        ttk.Checkbutton(cap, text='Automatically capture and analyze my game traffic while the game is connected '
                        '(passive, local only; needs TShark + Npcap)', variable=self.auto).grid(row=1, column=0, columnspan=4, sticky='w', pady=(8, 0))
        look = ttk.LabelFrame(win, text='Appearance', padding=12); look.pack(fill='x', padx=22, pady=6)
        self.theme = tk.StringVar(value=self.settings.get('ui.theme', 'dark'))
        for value in ('dark', 'light'):
            ttk.Radiobutton(look, text=value.title(), value=value, variable=self.theme).pack(side='left', padx=(0, 14))
        ttk.Label(look, text='Theme changes apply after restart.', style='Muted.TLabel').pack(side='left')
        actions = ttk.Frame(win); actions.pack(fill='x', padx=22, pady=16)
        ttk.Button(actions, text='Save and close', style='Accent.TButton', command=lambda: self._save(win)).pack(side='right')
        ttk.Button(actions, text='Skip for now', command=lambda: self._skip(win)).pack(side='right', padx=8)
        self.win = win
        return win

    def _skip(self, win):
        self.settings.set('first_run_complete', True); win.destroy()

    def _save(self, win):
        port = self.port.get().strip()
        if not port.isdigit() or not 1 <= int(port) <= 65535:
            return messagebox.showerror('Setup', 'Game port must be a number between 1 and 65535.', parent=win)
        iface = self.iface.get().strip()
        if iface and not iface.isdigit():
            return messagebox.showerror('Setup', 'Capture adapter must be a number from "List interfaces" or blank.', parent=win)
        self.settings.update({'installs.game': self.vars['game'].get().strip(), 'installs.steam': self.vars['steam'].get().strip(),
                              'installs.launcher': self.vars['launcher'].get().strip(), 'capture.port': int(port),
                              'capture.interface': iface, 'capture.auto_capture': bool(self.auto.get()),
                              'ui.theme': self.theme.get(), 'first_run_complete': True})
        win.destroy()
        if self.on_saved:
            self.on_saved()


# ------------------------------------------------------------ result viewer

class ResultViewer:
    """Show any JSON-able report as an expandable tree plus sortable tables."""
    def __init__(self, root, colors, data, *, title='Result', path=None):
        self.root = root; self.colors = colors; self.data = data; self.title = title; self.path = path

    @staticmethod
    def tables(data, prefix='', depth=0, out=None):
        """Find lists of dicts (records) anywhere in the result."""
        out = [] if out is None else out
        if depth > 4:
            return out
        if isinstance(data, list) and data and all(isinstance(x, dict) for x in data[:50]):
            out.append((prefix or 'records', data))
        elif isinstance(data, dict):
            for key, value in data.items():
                ResultViewer.tables(value, f'{prefix}.{key}' if prefix else str(key), depth + 1, out)
        return out

    def open(self):
        win = tk.Toplevel(self.root); win.title(self.title); win.geometry('1150x700'); win.configure(bg=self.colors['NAVY'])
        top = ttk.Frame(win); top.pack(fill='x', padx=12, pady=(12, 6))
        ttk.Label(top, text=self.title, style='Section.TLabel').pack(side='left')
        ttk.Button(top, text='Copy JSON', style='Small.TButton', command=lambda: (win.clipboard_clear(),
                   win.clipboard_append(json.dumps(self.data, indent=2, ensure_ascii=False, default=str)))).pack(side='right')
        if self.path:
            ttk.Button(top, text='Open file', style='Small.TButton', command=lambda: _open_path(self.path)).pack(side='right', padx=6)
            ttk.Button(top, text='Open folder', style='Small.TButton', command=lambda: _open_path(Path(self.path).parent)).pack(side='right')
        notebook = ttk.Notebook(win); notebook.pack(fill='both', expand=True, padx=12, pady=(0, 12))
        for name, rows in self.tables(self.data)[:12]:
            notebook.add(self._table_tab(notebook, rows), text=f'{name[:28]} ({len(rows)})')
        notebook.add(self._tree_tab(notebook), text='All data')
        return win

    def _table_tab(self, parent, rows):
        tab = ttk.Frame(parent)
        cols = []
        for row in rows[:200]:
            for key in row:
                if key not in cols and len(cols) < 14:
                    cols.append(key)
        filt = tk.StringVar()
        bar = ttk.Frame(tab); bar.pack(fill='x', pady=6)
        ttk.Label(bar, text='Filter').pack(side='left', padx=(0, 6))
        ttk.Entry(bar, textvariable=filt).pack(side='left', fill='x', expand=True)
        frame, tree = _scrolled_tree(tab, cols, height=20)
        for col in cols:
            tree.column(col, width=max(70, min(320, 9 * len(col) + 60)))
        make_sortable(tree, cols)
        frame.pack(fill='both', expand=True)

        def cell(value):
            if isinstance(value, (dict, list)):
                return json.dumps(value, ensure_ascii=False, default=str)[:200]
            return '' if value is None else str(value)[:200]

        def fill(*_):
            tree.delete(*tree.get_children())
            needle = filt.get().strip().casefold()
            shown = 0
            for row in rows:
                values = [cell(row.get(c)) for c in cols]
                if needle and not any(needle in v.casefold() for v in values):
                    continue
                tree.insert('', 'end', values=values); shown += 1
                if shown >= 5000:
                    break
        filt.trace_add('write', fill); fill()
        return tab

    def _tree_tab(self, parent):
        tab = ttk.Frame(parent)
        frame, tree = _scrolled_tree(tab, ('value',), show='tree headings', height=24)
        tree.heading('#0', text='Key'); tree.heading('value', text='Value')
        tree.column('#0', width=380); tree.column('value', width=700)
        frame.pack(fill='both', expand=True)

        def add(parent_id, key, value, depth=0):
            if isinstance(value, dict):
                node = tree.insert(parent_id, 'end', text=f'{key}  {{{len(value)}}}', open=depth < 1)
                for k, v in list(value.items())[:2000]:
                    add(node, k, v, depth + 1)
            elif isinstance(value, list):
                node = tree.insert(parent_id, 'end', text=f'{key}  [{len(value)}]', open=False)
                for i, v in enumerate(value[:2000]):
                    add(node, i, v, depth + 1)
            else:
                tree.insert(parent_id, 'end', text=str(key), values=(str(value)[:500],))
        add('', 'result', self.data)
        return tab


# ------------------------------------------------------------ global search

class GlobalSearch:
    """Ctrl+K: search wiki, catalog, combat methods, protocol definitions and decompiled source."""
    def __init__(self, root, colors, db, *, open_article, open_record, open_combat, extra=None):
        self.root = root; self.colors = colors; self.db = db
        self.open_article = open_article; self.open_record = open_record; self.open_combat = open_combat
        self.extra = extra or (lambda q: [])
        self.win = None; self._timer = None

    def open(self):
        if self.win is not None and self.win.winfo_exists():
            self.win.lift(); self.entry.focus_set(); return
        self.win = win = tk.Toplevel(self.root); win.title('Search everything'); win.geometry('900x560')
        win.configure(bg=self.colors['NAVY']); win.transient(self.root)
        self.query = tk.StringVar()
        self.entry = ttk.Entry(win, textvariable=self.query, font=theme.font(13))
        self.entry.pack(fill='x', padx=14, pady=14); self.entry.focus_set()
        cols = ('source', 'title', 'detail')
        frame, self.tree = _scrolled_tree(win, cols, height=18)
        for col, width in zip(cols, (110, 300, 440)):
            self.tree.heading(col, text=col.title()); self.tree.column(col, width=width, stretch=col == 'detail')
        frame.pack(fill='both', expand=True, padx=14, pady=(0, 14))
        self.items = {}
        self.query.trace_add('write', lambda *_: self._schedule())
        self.tree.bind('<Double-1>', lambda _e: self._activate())
        self.tree.bind('<Return>', lambda _e: self._activate())
        self.entry.bind('<Down>', lambda _e: (self.tree.focus_set(), self.tree.selection_set(self.tree.get_children()[:1])))
        win.bind('<Escape>', lambda _e: win.destroy())

    def _schedule(self):
        if self._timer:
            self.win.after_cancel(self._timer)
        self._timer = self.win.after(220, self._run)

    def results(self, q):
        import wiki_engine
        out = []
        for hit in wiki_engine.search(self.db.conn, q, limit=25):
            out.append(('Wiki', hit['title'], hit['snippet'], ('article', hit['id'])))
        for row in self.db.list_records(q, limit=25):
            out.append(('Catalog', row['name'], f"{row['dataset']} · {row['source_root']} · {row['external_id']}", ('record', row['id'])))
        for row in self.db.list_combat(q, limit=15):
            out.append(('Combat', row['full_name'], row['topics'][:120], ('combat', row['id'])))
        out += self.extra(q)
        return out

    def _run(self):
        q = self.query.get().strip()
        self.tree.delete(*self.tree.get_children()); self.items = {}
        if len(q) < 2:
            return
        try:
            results = self.results(q)
        except Exception as exc:
            results = [('Error', str(exc), '', None)]
        for i, (source, title, detail, target) in enumerate(results):
            self.tree.insert('', 'end', iid=str(i), values=(source, str(title)[:160], str(detail)[:300]))
            self.items[str(i)] = target

    def _activate(self):
        sel = self.tree.selection()
        target = self.items.get(sel[0]) if sel else None
        if not target:
            return
        kind, value = target[0], target[1]
        if kind == 'article':
            self.open_article(value)
        elif kind == 'record':
            self.open_record(value)
        elif kind == 'combat':
            self.open_combat(value)
        elif kind == 'path':
            _open_path(value)
        elif kind == 'callback':
            value()


# -------------------------------------------------------- markdown preview

def render_markdown_to_text(widget, source, colors):
    """Lightweight preview of wiki Markdown inside a Tk Text widget."""
    widget.configure(state='normal'); widget.delete('1.0', 'end')
    widget.tag_configure('h1', font=theme.font(18, bold=True), foreground=colors['TEXT'], spacing3=6)
    widget.tag_configure('h2', font=theme.font(15, bold=True), foreground=colors['ACCENT'], spacing1=8, spacing3=4)
    widget.tag_configure('h3', font=theme.font(12, bold=True), foreground=colors['TEXT'], spacing1=6)
    widget.tag_configure('body', font=theme.font(10), foreground=colors['TEXT'], spacing3=4)
    widget.tag_configure('bold', font=theme.font(10, bold=True))
    widget.tag_configure('code', font=theme.mono(10), background=colors['PANEL2'])
    widget.tag_configure('link', foreground=colors['ACCENT'], underline=True)
    widget.tag_configure('muted', foreground=colors['MUTED'])
    in_code = False
    for line in str(source).splitlines():
        stripped = line.strip()
        if stripped.startswith('```'):
            in_code = not in_code; continue
        if in_code:
            widget.insert('end', line + '\n', ('code',)); continue
        m = re.match(r'^(#{1,6})\s+(.*)', stripped)
        if m:
            widget.insert('end', m.group(2) + '\n', ('h' + str(min(3, len(m.group(1)))),)); continue
        bullet = re.match(r'^\s*([-*+]|\d+[.)])\s+(.*)', line)
        prefix = ''
        if bullet:
            prefix = '  • ' if not bullet.group(1)[0].isdigit() else '  ' + bullet.group(1) + ' '
            stripped = bullet.group(2)
        if stripped.startswith('>'):
            widget.insert('end', '│ ' + stripped[1:].strip() + '\n', ('muted', 'body')); continue
        widget.insert('end', prefix, ('body',))
        pos = 0
        for token in re.finditer(r'\*\*(.+?)\*\*|`([^`]+)`|\[\[([^\]|]+)(?:\|([^\]]+))?\]\]|\[([^\]]+)\]\(([^)]+)\)', stripped):
            widget.insert('end', stripped[pos:token.start()], ('body',))
            if token.group(1):
                widget.insert('end', token.group(1), ('body', 'bold'))
            elif token.group(2):
                widget.insert('end', token.group(2), ('code',))
            elif token.group(3):
                widget.insert('end', token.group(4) or token.group(3), ('body', 'link'))
            else:
                widget.insert('end', token.group(5), ('body', 'link'))
            pos = token.end()
        widget.insert('end', stripped[pos:] + '\n', ('body',))
    widget.configure(state='disabled')


class HistoryDialog:
    """Revision list for one article with preview and restore."""
    def __init__(self, root, colors, db, article_id, *, on_restored):
        self.root = root; self.colors = colors; self.db = db; self.article_id = article_id; self.on_restored = on_restored

    def open(self):
        import wiki_engine
        win = tk.Toplevel(self.root); win.title('Article history'); win.geometry('980x560'); win.configure(bg=self.colors['NAVY'])
        pane = ttk.PanedWindow(win, orient='horizontal'); pane.pack(fill='both', expand=True, padx=12, pady=12)
        left = ttk.Frame(pane); right = ttk.Frame(pane); pane.add(left, weight=2); pane.add(right, weight=5)
        cols = ('saved', 'title', 'size', 'note')
        frame, tree = _scrolled_tree(left, cols, height=18)
        for col, width in zip(cols, (150, 160, 60, 110)):
            tree.heading(col, text=col.title()); tree.column(col, width=width)
        frame.pack(fill='both', expand=True)
        preview = _text(right, self.colors); preview.pack(fill='both', expand=True)
        backlinks = wiki_engine.backlinks(self.db.conn, self.article_id)
        ttk.Label(right, text='Linked from: ' + (', '.join(b['title'] for b in backlinks[:20]) or 'no other article'),
                  style='Muted.TLabel', wraplength=600).pack(anchor='w', pady=6)
        for rid, title, saved, note, size in wiki_engine.revisions(self.db.conn, self.article_id):
            tree.insert('', 'end', iid=str(rid), values=(saved, title, size, note))

        def show(_e=None):
            sel = tree.selection()
            if sel:
                rev = wiki_engine.revision(self.db.conn, int(sel[0]))
                preview.delete('1.0', 'end'); preview.insert('1.0', rev['body'])
        tree.bind('<<TreeviewSelect>>', show)

        def restore():
            sel = tree.selection()
            if not sel:
                return
            if messagebox.askyesno('Restore revision', 'Replace the current article with this revision? '
                                   'The current text is kept as a new revision.', parent=win):
                self.db.restore_revision(self.article_id, int(sel[0]))
                win.destroy(); self.on_restored()
        ttk.Button(right, text='Restore this revision', style='Accent.TButton', command=restore).pack(anchor='e')
        if not tree.get_children():
            preview.insert('1.0', 'No earlier revisions yet. A revision is kept every time you save.')
        return win


# ---------------------------------------------------------- message browser

def hexdump(data, width=16):
    lines = []
    for off in range(0, len(data), width):
        chunk = data[off:off + width]
        hexes = ' '.join(f'{b:02x}' for b in chunk)
        text = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
        lines.append(f'{off:06x}  {hexes:<{width * 3}} {text}')
    return '\n'.join(lines)


class MessageBrowser:
    """Browse a private message log by type, inspect hex and build a decoding schema."""
    FIELD_TYPES = ['uint8', 'int8', 'uint16', 'int16', 'uint32', 'int32', 'uint64', 'int64', 'float32', 'float64',
                   'bool', 'varint', 'string8', 'string16', 'dotnet_string', 'uint16_be', 'uint32_be', 'bytes:4',
                   'bytes:8', 'rest']

    def __init__(self, root, colors, *, jobs=None, entity_db=None, notify=None):
        self.root = root; self.colors = colors; self.jobs = jobs; self.entity_db = entity_db
        self.notify = notify or (lambda title, message: None)
        self.messages = []; self.header = {}; self.schema = None; self.schema_path = None; self.log_path = None

    def open(self, log_path=None):
        win = tk.Toplevel(self.root); win.title('Protocol message browser'); win.geometry('1400x820')
        win.configure(bg=self.colors['NAVY']); self.win = win
        bar = ttk.Frame(win); bar.pack(fill='x', padx=12, pady=10)
        ttk.Button(bar, text='Open message log…', style='Accent.TButton', command=self._choose_log).pack(side='left')
        ttk.Button(bar, text='Open schema…', command=self._choose_schema).pack(side='left', padx=6)
        ttk.Button(bar, text='Save schema', command=self._save_schema).pack(side='left')
        ttk.Button(bar, text='Decode all → SQLite/JSONL', command=self._export_decoded).pack(side='left', padx=6)
        ttk.Button(bar, text='Export Wireshark / ImHex / Kaitai', command=self._export_tools).pack(side='left')
        self.status = tk.StringVar(value='Open a message log created with “Export private message log”.')
        ttk.Label(bar, textvariable=self.status, style='Muted.TLabel').pack(side='left', padx=12)
        pane = ttk.PanedWindow(win, orient='horizontal'); pane.pack(fill='both', expand=True, padx=12, pady=(0, 12))
        left = ttk.Frame(pane); mid = ttk.Frame(pane); right = ttk.Frame(pane)
        pane.add(left, weight=2); pane.add(mid, weight=4); pane.add(right, weight=4)
        frame, self.types = _scrolled_tree(left, ('type', 'name', 'count'), height=30)
        for col, width in (('type', 110), ('name', 130), ('count', 60)):
            self.types.heading(col, text=col.title()); self.types.column(col, width=width)
        frame.pack(fill='both', expand=True)
        self.types.bind('<<TreeviewSelect>>', lambda _e: self._show_type())
        frame, self.list = _scrolled_tree(mid, ('i', 't', 'dir', 'len'), height=14)
        for col, width in (('i', 70), ('t', 90), ('dir', 70), ('len', 60)):
            self.list.heading(col, text=col.upper()); self.list.column(col, width=width)
        frame.pack(fill='both', expand=True)
        self.list.bind('<<TreeviewSelect>>', lambda _e: self._show_message())
        self.hex = _text(mid, self.colors, height=16, wrap='none'); self.hex.pack(fill='both', expand=True, pady=(8, 0))
        ttk.Label(right, text='Message type schema', style='Section.TLabel').pack(anchor='w')
        row = ttk.Frame(right); row.pack(fill='x', pady=4)
        ttk.Label(row, text='Name').pack(side='left')
        self.type_name = tk.StringVar(); ttk.Entry(row, textvariable=self.type_name).pack(side='left', fill='x', expand=True, padx=6)
        ttk.Button(row, text='Apply', style='Small.TButton', command=self._apply_name).pack(side='left')
        frame, self.fields = _scrolled_tree(right, ('name', 'type', 'inferred'), height=10)
        for col, width in (('name', 160), ('type', 120), ('inferred', 110)):
            self.fields.heading(col, text=col.title()); self.fields.column(col, width=width)
        frame.pack(fill='both', expand=True)
        edit = ttk.Frame(right); edit.pack(fill='x', pady=4)
        self.field_name = tk.StringVar(value='field'); self.field_type = tk.StringVar(value='uint32')
        ttk.Entry(edit, textvariable=self.field_name, width=16).pack(side='left')
        ttk.Combobox(edit, textvariable=self.field_type, values=self.FIELD_TYPES, width=14).pack(side='left', padx=4)
        ttk.Button(edit, text='Add', style='Small.TButton', command=self._add_field).pack(side='left')
        ttk.Button(edit, text='Remove', style='Small.TButton', command=self._remove_field).pack(side='left', padx=4)
        ttk.Button(edit, text='▲', style='Small.TButton', command=lambda: self._move(-1)).pack(side='left')
        ttk.Button(edit, text='▼', style='Small.TButton', command=lambda: self._move(1)).pack(side='left', padx=4)
        ttk.Button(right, text='Suggest fields from samples', command=self._suggest).pack(anchor='w', pady=4)
        ttk.Label(right, text='Decoded selected message', style='Section.TLabel').pack(anchor='w', pady=(8, 2))
        self.decoded = _text(right, self.colors, height=12); self.decoded.pack(fill='both', expand=True)
        if log_path:
            self.load_log(log_path)
        return win

    # data
    def load_log(self, path):
        import protocol_schema
        self.messages = []; self.header = {}
        for header, row in protocol_schema.read_message_log(path):
            self.header = header or {}
            self.messages.append(row)
            if len(self.messages) >= 500_000:
                break
        self.log_path = path
        if self.schema is None:
            self.schema = protocol_schema.new_schema(self.header.get('framing'), self.header.get('opcode_width', 1))
        self._fill_types()
        self.status.set(f'{len(self.messages):,} messages · framing: {self.header.get("framing", {}).get("description", "?")}')

    def _header_len(self):
        f = self.header.get('framing') or {}
        return int(f.get('offset', 0)) + int(f.get('size', 2)) + int(self.header.get('opcode_width', 1))

    def _fill_types(self):
        from collections import Counter
        counts = Counter(m['type'] for m in self.messages)
        self.types.delete(*self.types.get_children())
        for type_id, n in counts.most_common():
            name = self.schema.get('types', {}).get(type_id, {}).get('name', '')
            self.types.insert('', 'end', iid=type_id, values=(type_id, name, n))

    def _current_type(self):
        sel = self.types.selection()
        return sel[0] if sel else None

    def _spec(self, type_id):
        return self.schema.setdefault('types', {}).setdefault(type_id, {'name': '', 'fields': []})

    def _show_type(self):
        type_id = self._current_type()
        if not type_id:
            return
        self.list.delete(*self.list.get_children())
        for m in [m for m in self.messages if m['type'] == type_id][:3000]:
            self.list.insert('', 'end', iid=str(m['i']), values=(m['i'], m['t'], m['dir'], m['len']))
        spec = self._spec(type_id); self.type_name.set(spec.get('name', ''))
        self._fill_fields(spec)

    def _fill_fields(self, spec):
        self.fields.delete(*self.fields.get_children())
        for i, f in enumerate(spec.get('fields', [])):
            self.fields.insert('', 'end', iid=str(i), values=(f['name'], f['type'], f.get('inferred', '')))

    def _selected_message(self):
        sel = self.list.selection()
        if not sel:
            return None
        index = int(sel[0])
        return next((m for m in self.messages if m['i'] == index), None)

    def _show_message(self):
        import protocol_schema
        msg = self._selected_message()
        if not msg:
            return
        raw = bytes.fromhex(msg['hex'])
        self.hex.delete('1.0', 'end'); self.hex.insert('1.0', hexdump(raw))
        body = raw[self._header_len():]
        spec = self._spec(msg['type'])
        fields, error = protocol_schema.decode_fields(body, spec.get('fields') or [{'name': 'payload', 'type': 'rest'}])
        self.decoded.delete('1.0', 'end')
        self.decoded.insert('1.0', json.dumps(fields, indent=2, ensure_ascii=False) + (f'\n\nDECODE ERROR: {error}' if error else ''))

    # schema editing
    def _apply_name(self):
        type_id = self._current_type()
        if type_id:
            self._spec(type_id)['name'] = re.sub(r'[^\w]', '', self.type_name.get())[:60]
            self.types.set(type_id, 'name', self._spec(type_id)['name'])

    def _add_field(self):
        type_id = self._current_type()
        if not type_id:
            return
        name = re.sub(r'[^\w]', '_', self.field_name.get().strip())[:60] or 'field'
        self._spec(type_id)['fields'].append({'name': name, 'type': self.field_type.get().strip()})
        self._fill_fields(self._spec(type_id)); self._show_message()

    def _remove_field(self):
        type_id = self._current_type(); sel = self.fields.selection()
        if type_id and sel:
            del self._spec(type_id)['fields'][int(sel[0])]
            self._fill_fields(self._spec(type_id)); self._show_message()

    def _move(self, delta):
        type_id = self._current_type(); sel = self.fields.selection()
        if not (type_id and sel):
            return
        fields = self._spec(type_id)['fields']; i = int(sel[0]); j = i + delta
        if 0 <= j < len(fields):
            fields[i], fields[j] = fields[j], fields[i]
            self._fill_fields(self._spec(type_id)); self.fields.selection_set(str(j)); self._show_message()

    def _suggest(self):
        import protocol_schema
        type_id = self._current_type()
        if not type_id:
            return
        start = self._header_len()
        bodies = [bytes.fromhex(m['hex'])[start:] for m in self.messages if m['type'] == type_id][:400]
        fields = protocol_schema.suggest_fields(protocol_schema.infer_fields(bodies))
        if self._spec(type_id)['fields'] and not messagebox.askyesno('Replace fields', 'Replace the current field list with suggestions?', parent=self.win):
            return
        self._spec(type_id)['fields'] = fields
        self._fill_fields(self._spec(type_id)); self._show_message()

    # files
    def _choose_log(self):
        path = filedialog.askopenfilename(title='Message log', filetypes=[('Message log', '*.jsonl')], parent=self.win)
        if path:
            self.load_log(path)

    def _choose_schema(self):
        import protocol_schema
        path = filedialog.askopenfilename(title='Protocol schema', filetypes=[('Schema', '*.json')], parent=self.win)
        if path:
            try:
                self.schema = protocol_schema.load_schema(path); self.schema_path = path
                self._fill_types(); self.status.set('Schema loaded: ' + path)
            except Exception as exc:
                messagebox.showerror('Schema', str(exc), parent=self.win)

    def _save_schema(self):
        import protocol_schema
        if self.schema is None:
            return
        path = self.schema_path or filedialog.asksaveasfilename(title='Save schema', defaultextension='.json',
                                                                initialfile='WoSB-Protocol-Schema.json', parent=self.win)
        if path:
            self.schema['framing'] = self.schema.get('framing') or self.header.get('framing')
            self.schema['opcode_width'] = self.header.get('opcode_width', self.schema.get('opcode_width', 1))
            protocol_schema.save_schema(self.schema, path); self.schema_path = path
            self.status.set('Schema saved: ' + path)

    def _export_decoded(self):
        import protocol_schema
        if not (self.log_path and self.schema):
            return messagebox.showinfo('Decode', 'Open a message log first.', parent=self.win)
        folder = filedialog.askdirectory(title='Folder for decoded output', parent=self.win)
        if not folder:
            return
        schema = dict(self.schema); log = self.log_path; db = self.entity_db

        def task(ctx=None):
            names = protocol_schema.entity_tables_from_catalog(db) if db else None
            return protocol_schema.export_decoded(log, schema, folder, entity_names=names)
        if self.jobs:
            self.jobs(task, lambda r: self.notify('Decoded messages', f"{r['messages']:,} messages → {r['output_dir']}"),
                      'Decoding messages with your schema…')
        else:
            result = task(); self.notify('Decoded messages', str(result))

    def _export_tools(self):
        import protocol_schema
        if not self.schema:
            return
        folder = filedialog.askdirectory(title='Folder for Wireshark / ImHex / Kaitai files', parent=self.win)
        if folder:
            files = protocol_schema.export_tools(self.schema, folder, port=int((self.header or {}).get('server_port') or 23771))
            self.notify('Tool exports written', '\n'.join(files))


# ----------------------------------------------------------------- chooser

class Chooser:
    """Modal one-click picker over known locations, with an 'Other…' browse fallback.

    options: [(label, value, detail)]. browse: None | 'dir' | 'file' | 'files'.
    Returns the chosen value (a list for 'files'), or None if cancelled.
    """
    def __init__(self, root, colors, title, prompt, options, *, browse='dir', filetypes=None, initial=0):
        self.root = root; self.colors = colors; self.title = title; self.prompt = prompt
        self.options = list(options); self.browse = browse; self.filetypes = filetypes or [('All files', '*.*')]
        self.initial = initial; self.result = None

    def show(self):
        win = tk.Toplevel(self.root); win.title(self.title); win.geometry('820x420'); win.configure(bg=self.colors['NAVY'])
        win.transient(self.root)
        ttk.Label(win, text=self.title, style='Section.TLabel').pack(anchor='w', padx=16, pady=(14, 2))
        ttk.Label(win, text=self.prompt, style='Muted.TLabel', wraplength=780).pack(anchor='w', padx=16, pady=(0, 8))
        frame, tree = _scrolled_tree(win, ('choice', 'detail'), height=9)
        tree.heading('choice', text='Location'); tree.heading('detail', text='Details')
        tree.column('choice', width=520); tree.column('detail', width=240)
        frame.pack(fill='both', expand=True, padx=16)
        for i, (label, _value, detail) in enumerate(self.options):
            tree.insert('', 'end', iid=str(i), values=(label, detail or ''))
        if self.options:
            tree.selection_set(str(min(self.initial, len(self.options) - 1)))

        def choose(_e=None):
            sel = tree.selection()
            if sel:
                self.result = self.options[int(sel[0])][1]; win.destroy()

        def other():
            if self.browse == 'dir':
                value = filedialog.askdirectory(title=self.title, parent=win)
            elif self.browse == 'files':
                value = list(filedialog.askopenfilenames(title=self.title, filetypes=self.filetypes, parent=win)) or None
            else:
                value = filedialog.askopenfilename(title=self.title, filetypes=self.filetypes, parent=win)
            if value:
                self.result = value; win.destroy()
        tree.bind('<Double-1>', choose); tree.bind('<Return>', choose)
        row = ttk.Frame(win); row.pack(fill='x', padx=16, pady=12)
        ttk.Button(row, text='Use selected', style='Accent.TButton', command=choose).pack(side='right')
        ttk.Button(row, text='Cancel', command=win.destroy).pack(side='right', padx=8)
        if self.browse:
            ttk.Button(row, text='Other…', command=other).pack(side='left')
        win.bind('<Escape>', lambda _e: win.destroy())
        try:
            win.grab_set()
        except tk.TclError:
            pass
        self.root.wait_window(win)
        return self.result
