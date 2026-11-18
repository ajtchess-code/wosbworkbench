"""Single source of design tokens for the desktop UI (dark and light themes).

workbench_ui used colour literals in ~200 places; they now come from here. The
theme is chosen at start-up from settings (ui.theme); switching asks for a restart
because classic Tk widgets do not restyle themselves live.
"""
from __future__ import annotations

PALETTES = {
    'dark': {
        'NAVY': '#0b1220', 'PANEL': '#152235', 'PANEL2': '#23364e', 'TEXT': '#eff7ff', 'MUTED': '#9fb2c7',
        'ACCENT': '#57d3d0', 'ACCENT_DARK': '#176b76', 'ACCENT_HOVER': '#238b94', 'GREEN': '#80deb0',
        'WARN': '#f7b966', 'DANGER': '#ff7b7b', 'SIDEBAR': '#101b2b', 'BORDER': '#2c3c50', 'HOVER': '#243a50',
        'SELECT': '#286876', 'GROUP': '#7192ad', 'INPUT': '#152235', 'TEXT_SELECT': '#267b92',
    },
    'light': {
        'NAVY': '#f4f7fb', 'PANEL': '#ffffff', 'PANEL2': '#e3ebf4', 'TEXT': '#0f1c2b', 'MUTED': '#52657a',
        'ACCENT': '#0f7f86', 'ACCENT_DARK': '#0f7f86', 'ACCENT_HOVER': '#12969e', 'GREEN': '#1d8a5a',
        'WARN': '#a85f00', 'DANGER': '#b42318', 'SIDEBAR': '#e9eff6', 'BORDER': '#c8d4e2', 'HOVER': '#dbe6f2',
        'SELECT': '#b9dfe2', 'GROUP': '#4f6780', 'INPUT': '#ffffff', 'TEXT_SELECT': '#bfe3ea',
    },
}

FONT = 'Segoe UI'
FONT_SEMIBOLD = 'Segoe UI Semibold'
MONO = 'Consolas'

SPACING = {'xs': 4, 'sm': 8, 'md': 12, 'lg': 18, 'xl': 28}


def palette(mode='dark'):
    return dict(PALETTES.get(mode, PALETTES['dark']))


def font(size=10, *, bold=False, scale=1.0):
    return (FONT_SEMIBOLD if bold else FONT, max(7, round(size * scale)))


def mono(size=10, *, scale=1.0):
    return (MONO, max(7, round(size * scale)))


def apply_ttk(style, colors, *, scale=1.0):
    """Configure every ttk style the app uses from one palette."""
    c = colors
    style.theme_use('clam')
    style.configure('.', font=font(10, scale=scale), background=c['NAVY'], foreground=c['TEXT'])
    for name, bg in (('TFrame', c['NAVY']), ('Card.TFrame', c['PANEL']), ('Panel.TFrame', c['PANEL'])):
        style.configure(name, background=bg)
    style.configure('TLabel', background=c['NAVY'], foreground=c['TEXT'])
    style.configure('Card.TLabel', background=c['PANEL'], foreground=c['TEXT'])
    style.configure('CardMuted.TLabel', background=c['PANEL'], foreground=c['MUTED'], font=font(9, scale=scale))
    style.configure('CardTitle.TLabel', background=c['PANEL'], foreground=c['TEXT'], font=font(12, bold=True, scale=scale))
    style.configure('CardValue.TLabel', background=c['PANEL'], foreground=c['ACCENT'], font=font(20, bold=True, scale=scale))
    style.configure('Muted.TLabel', background=c['NAVY'], foreground=c['MUTED'], font=font(10, scale=scale))
    style.configure('Title.TLabel', font=font(23, bold=True, scale=scale), foreground=c['TEXT'], background=c['NAVY'])
    style.configure('Section.TLabel', font=font(12, bold=True, scale=scale), foreground=c['ACCENT'], background=c['NAVY'])
    style.configure('Warn.TLabel', background=c['NAVY'], foreground=c['WARN'])
    style.configure('TButton', background=c['PANEL2'], foreground=c['TEXT'], borderwidth=0, padding=(15, 10),
                    font=font(10, bold=True, scale=scale))
    style.map('TButton', background=[('active', c['HOVER'])], foreground=[('disabled', c['MUTED'])])
    style.configure('Accent.TButton', background=c['ACCENT_DARK'], foreground='#ffffff')
    style.map('Accent.TButton', background=[('active', c['ACCENT_HOVER'])])
    style.configure('Small.TButton', padding=(8, 4), font=font(9, scale=scale))
    style.configure('TEntry', fieldbackground=c['INPUT'], foreground=c['TEXT'], insertcolor=c['TEXT'], padding=6)
    style.configure('TCombobox', fieldbackground=c['INPUT'], background=c['PANEL2'], foreground=c['TEXT'], arrowcolor=c['TEXT'])
    style.map('TCombobox', fieldbackground=[('readonly', c['INPUT'])], foreground=[('readonly', c['TEXT'])])
    style.configure('Treeview', background=c['PANEL'], foreground=c['TEXT'], fieldbackground=c['PANEL'],
                    rowheight=round(30 * scale), borderwidth=0, font=font(10, scale=scale))
    style.map('Treeview', background=[('selected', c['SELECT'])], foreground=[('selected', c['TEXT'] if c['NAVY'].startswith('#f') else '#ffffff')])
    style.configure('Treeview.Heading', background=c['PANEL2'], foreground=c['TEXT'], relief='flat',
                    font=font(10, bold=True, scale=scale), padding=(8, 8))
    style.configure('TNotebook', background=c['NAVY'], borderwidth=0)
    style.configure('TNotebook.Tab', background=c['PANEL'], foreground=c['MUTED'], padding=(17, 11))
    style.map('TNotebook.Tab', background=[('selected', c['PANEL2'])], foreground=[('selected', c['TEXT'])])
    style.configure('TCheckbutton', background=c['NAVY'], foreground=c['TEXT'])
    style.configure('Card.TCheckbutton', background=c['PANEL'], foreground=c['TEXT'])
    style.configure('TProgressbar', background=c['ACCENT'], troughcolor=c['PANEL'])
    style.configure('TLabelframe', background=c['NAVY'], foreground=c['TEXT'], bordercolor=c['BORDER'])
    style.configure('TLabelframe.Label', background=c['NAVY'], foreground=c['ACCENT'], font=font(10, bold=True, scale=scale))
    style.configure('TPanedwindow', background=c['NAVY'])
