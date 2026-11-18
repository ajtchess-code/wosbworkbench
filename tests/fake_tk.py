"""Headless stand-in for tkinter used to smoke-test UI construction and flows.

Not a renderer: widgets accept any option and record calls; Treeview and Text
keep real state so refresh/selection logic runs. Install with ``install()``
BEFORE importing workbench_ui (do it in a subprocess).
"""
import itertools
import sys
import types

_ids = itertools.count(1)
CALLED_AFTER = []


class TclError(Exception):
    pass


class _Var:
    _default = ''

    def __init__(self, master=None, value=None, name=None):
        self._value = self._default if value is None else value
        self._traces = []

    def get(self):
        return self._value

    def set(self, value):
        self._value = value
        for callback in list(self._traces):
            callback('', '', 'write')

    def trace_add(self, mode, callback):
        self._traces.append(callback)
        return str(len(self._traces))


class StringVar(_Var):
    _default = ''


class BooleanVar(_Var):
    _default = False


class IntVar(_Var):
    _default = 0


class DoubleVar(_Var):
    _default = 0.0


class Widget:
    def __init__(self, master=None, *args, **kwargs):
        self.master = master
        self._options = dict(kwargs)
        self._children = []
        if isinstance(master, Widget):
            master._children.append(self)
        self.tk = types.SimpleNamespace(call=lambda *a, **k: None)

    # geometry / config
    def pack(self, *a, **k): pass
    def grid(self, *a, **k): pass
    def place(self, *a, **k): pass
    def pack_forget(self): pass
    def place_forget(self): pass
    def grid_columnconfigure(self, *a, **k): pass
    columnconfigure = rowconfigure = grid_columnconfigure
    def pack_propagate(self, *a): pass
    def configure(self, **k): self._options.update(k)
    config = configure
    def cget(self, key): return self._options.get(key, '')
    def __setitem__(self, key, value): self._options[key] = value
    def __getitem__(self, key): return self._options.get(key, '')
    def bind(self, *a, **k): pass
    def bind_all(self, *a, **k): pass
    def focus_set(self): pass
    def destroy(self): self._destroyed = True
    def winfo_exists(self): return not getattr(self, '_destroyed', False)
    def winfo_children(self): return list(self._children)
    def winfo_width(self): return 900
    def winfo_height(self): return 600
    def winfo_reqheight(self): return 80
    def winfo_fpixels(self, v): return 96.0
    def update_idletasks(self): pass
    def after(self, ms, func=None, *args):
        CALLED_AFTER.append(func)
        return 'after#' + str(next(_ids))
    def after_cancel(self, ident): pass
    def clipboard_clear(self): pass
    def clipboard_append(self, text): pass
    def title(self, *a): pass
    def geometry(self, *a): return '1430x890'
    def minsize(self, *a): pass
    def protocol(self, *a): pass
    def transient(self, *a): pass
    def lift(self): pass
    def deiconify(self): pass
    def iconphoto(self, *a): pass
    def iconbitmap(self, *a, **k): pass
    def mainloop(self): pass
    def invoke(self): pass
    def grab_set(self): pass
    def wait_window(self, *a): pass
    def state(self, *a): return ()
    # Entry-like text storage
    def insert(self, index, text, *a): self._entry = getattr(self, '_entry', '') + str(text)
    def get(self, *a):
        var = self._options.get('textvariable')
        return var.get() if var is not None else getattr(self, '_entry', '')
    def delete(self, *a): self._entry = ''
    def set(self, *a): pass
    def current(self, *a): return -1
    def select(self, *a): pass
    def add(self, *a, **k): pass
    def tab(self, *a, **k): return {}
    def index(self, *a): return 0
    def start(self, *a): pass
    def stop(self, *a): pass
    def step(self, *a): pass
    def yview(self, *a): pass
    def xview(self, *a): pass
    def coords(self, *a): pass


class Tk(Widget):
    pass


class Toplevel(Widget):
    pass


class Text(Widget):
    def __init__(self, *a, **k):
        super().__init__(*a, **k); self._text = ''

    def insert(self, index, text, *tags):
        self._text = (self._text + str(text)) if index in ('end', 'END') else (str(text) + self._text)

    def delete(self, *a):
        self._text = ''

    def get(self, *a):
        return self._text

    def see(self, *a): pass
    def tag_configure(self, *a, **k): pass
    def edit_modified(self, *a): return False


class Canvas(Widget):
    def __getattr__(self, name):
        if name.startswith('create_') or name in ('delete', 'coords', 'itemconfigure'):
            return lambda *a, **k: next(_ids)
        raise AttributeError(name)


class Treeview(Widget):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._items = {}; self._order = {'': []}; self._selection = ()

    def heading(self, *a, **k): pass
    def column(self, *a, **k): pass

    def insert(self, parent, index, iid=None, **k):
        iid = str(iid) if iid is not None else 'I' + str(next(_ids))
        if iid in self._items:
            raise TclError('Item ' + iid + ' already exists')
        self._items[iid] = dict(k, parent=parent)
        self._order.setdefault(parent, [])
        if index == 0:
            self._order[parent].insert(0, iid)
        else:
            self._order[parent].append(iid)
        self._order.setdefault(iid, [])
        return iid

    def get_children(self, item=''):
        return tuple(self._order.get(item, []))

    def delete(self, *items):
        for iid in items:
            if iid in self._items:
                parent = self._items.pop(iid)['parent']
                self._order[parent].remove(iid)
                for child in list(self._order.pop(iid, [])):
                    self.delete(child)
        self._selection = tuple(i for i in self._selection if i in self._items)

    def exists(self, iid):
        return str(iid) in self._items

    def selection(self):
        return self._selection

    def selection_set(self, items):
        if isinstance(items, (list, tuple)):
            self._selection = tuple(str(i) for i in items)
        else:
            self._selection = (str(items),)

    def see(self, *a): pass
    def focus(self, *a): return self._selection[0] if self._selection else ''

    def set(self, iid, column=None, value=None):
        values = list(self._items[iid].get('values', ()))
        return values[0] if values and column is not None and value is None else ''

    def move(self, *a): pass
    def item(self, iid, **k): return self._items.get(iid, {})
    def yview(self, *a): pass


class Combobox(Widget):
    def current(self, index=None):
        values = list(self._options.get('values') or [])
        if index is None:
            var = self._options.get('textvariable')
            return values.index(var.get()) if var is not None and var.get() in values else -1
        if index < len(values) and self._options.get('textvariable') is not None:
            self._options['textvariable'].set(values[index])


class Listbox(Widget):
    def __init__(self, *a, **k):
        super().__init__(*a, **k); self._rows = []; self._sel = ()
    def insert(self, index, *items): self._rows.extend(items)
    def delete(self, *a): self._rows = []
    def curselection(self): return self._sel
    def get(self, i, *a): return self._rows[i]
    def size(self): return len(self._rows)
    def selection_set(self, i): self._sel = (i,)
    def selection_clear(self, *a): self._sel = ()
    def see(self, *a): pass


class Style:
    def __init__(self, *a, **k): pass
    def theme_use(self, *a): pass
    def configure(self, *a, **k): pass
    def map(self, *a, **k): pass


class PhotoImage:
    def __init__(self, *a, **k): pass


def install():
    tk = types.ModuleType('tkinter')
    for name, value in dict(Tk=Tk, Toplevel=Toplevel, Frame=Widget, Label=Widget, Button=Widget, Text=Text,
                            Canvas=Canvas, Entry=Widget, Scrollbar=Widget, Checkbutton=Widget, Radiobutton=Widget,
                            Listbox=Listbox, PhotoImage=PhotoImage, StringVar=StringVar, BooleanVar=BooleanVar, IntVar=IntVar,
                            DoubleVar=DoubleVar, TclError=TclError, END='end', Widget=Widget).items():
        setattr(tk, name, value)
    ttk = types.ModuleType('tkinter.ttk')
    for name in ('Frame', 'Label', 'Button', 'Entry', 'Checkbutton', 'Radiobutton', 'Scale', 'Separator', 'Progressbar',
                 'LabelFrame', 'Labelframe', 'PanedWindow', 'Panedwindow', 'Notebook', 'Scrollbar', 'Spinbox',
                 'Sizegrip', 'Menubutton', 'OptionMenu'):
        setattr(ttk, name, type(name, (Widget,), {'add': lambda self, *a, **k: None}))
    ttk.Treeview = Treeview; ttk.Combobox = Combobox; ttk.Style = Style
    filedialog = types.ModuleType('tkinter.filedialog')
    for name in ('askopenfilename', 'asksaveasfilename', 'askdirectory'):
        setattr(filedialog, name, lambda *a, **k: '')
    filedialog.askopenfilenames = lambda *a, **k: ()
    messagebox = types.ModuleType('tkinter.messagebox')
    messagebox.LOG = []
    for name in ('showinfo', 'showerror', 'showwarning'):
        setattr(messagebox, name, lambda *a, _n=name, **k: messagebox.LOG.append((_n, a)))
    messagebox.askyesno = lambda *a, **k: messagebox.LOG.append(('askyesno', a)) or False
    messagebox.askyesnocancel = lambda *a, **k: messagebox.LOG.append(('askyesnocancel', a)) or None
    tk.ttk = ttk; tk.filedialog = filedialog; tk.messagebox = messagebox
    sys.modules.update({'tkinter': tk, 'tkinter.ttk': ttk, 'tkinter.filedialog': filedialog,
                        'tkinter.messagebox': messagebox, '_tkinter': types.ModuleType('_tkinter')})
    return tk
