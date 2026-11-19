"""Windows desktop GUI for the WoSB Workbench catalog, wiki, and analyzers."""
from __future__ import annotations
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import math
import webbrowser
import tkinter as tk
from pathlib import Path
from tkinter import ttk, filedialog, messagebox

from workbench_db import CatalogDB, VERSION, home, slugify, bundled_path
from workbench_import import Importer
from workbench_updates import fetch_manifest, download_verified, version_tuple
from offline_updates import inspect_update_zip
from mechanics_taxonomy import seed_mechanics_pages
from economy_research import build_research_articles
from sailing_lab import seed_sailing_pages, rose_records, winding_dot_at_angle, wind_speed_component
from ship_viewer import export_viewer, ship_catalog, seed_hitbox_pages
from ballistics_lab import load_ballistics_catalog
from model_lab import ModelLibrary, match_models, export_xnb_samples, recover_model_for_ship, locate_model_candidate, expected_model_for_ship
from discovery_center import scan_reports, audit_catalog, save_audit, list_findings, export_findings, export_relationships
from wiki_enrichment import enrich_catalog
from network_lab import (analyze_capture, init_db as init_network_db, save_session, list_sessions,
    get_summary, add_event, event_correlations, export_research, list_interfaces,
    find_tshark, start_capture, stop_capture)
from damage_evidence import generate_trial_dashboard,write_trial_template
from damage_hypotheses import lookup as damage_lookup, calculate as damage_hypotheses_calculate
from shader_recovery import audit_effects
from visual_reference import compare_screenshots
from game_hotkeys import CaptureHotkeys
from gameplay_capture import (GameplaySession, game_process_connection, discover_game_ports, find_ffmpeg,
    analyze_session as analyze_gameplay_session, export_sanitized_review, export_video_clips,
    detect_game_capture_interface, preview_interface_traffic, export_combat_evidence)
from mechanics_lab import (armor_effective, fire_damage_multiplier, microfire_threshold,
    crafting_capacity_scenario, crafting_spend, facility_output_per_operation,
    contextual_bonuses, load_catalog_rules, wind_lookup)

import theme
import applog
from app_settings import settings as app_settings
from jobs import JobManager
import ui_extras
try:
    _THEME_MODE=app_settings().get('ui.theme','dark')
except Exception:
    _THEME_MODE='dark'
COLORS=theme.palette(_THEME_MODE)
NAVY=COLORS['NAVY']; PANEL=COLORS['PANEL']; PANEL2=COLORS['PANEL2']; TEXT=COLORS['TEXT']; MUTED=COLORS['MUTED']
ACCENT=COLORS['ACCENT']; GREEN=COLORS['GREEN']; WARN=COLORS['WARN']
SIDEBAR=COLORS['SIDEBAR']; BORDER=COLORS['BORDER']; HOVER=COLORS['HOVER']
# Pages grouped into five work areas (plus Home and Settings) in the sidebar.
PAGE_GROUPS=[('HOME',['Overview']),
             ('RECOVER',['Full Recovery','Datamining','Client scans','Discovery Center']),
             ('CATALOG & WIKI',['Catalog','Wiki editor','Combat evidence','Mechanics Lab','Sailing & wind']),
             ('SHIP 3D',['Ship 3D']),
             ('CAPTURE & PROTOCOL',['Network Research Lab','Advanced Research']),
             ('SETTINGS',['Settings','Import & export','Updates'])]
GAME_PATHS=[r'C:\Games\World of Sea Battle\default\game',r'C:\Games\Wosb Launcher',r'C:\Program Files (x86)\Steam\steamapps\common\World of Sea Battle']

class SidebarNavigation:
    """Grouped, always-visible page navigation (replaces the hidden 'More tools' drawer)."""
    def __init__(self, host, sidebar, heading_var):
        self.host=host;self.sidebar=sidebar;self.heading_var=heading_var
        self.pages=[];self.buttons=[];self.current=-1;self._groups=set()
        self.on_select=None

    def add(self, frame, text, advanced=False, group=None):
        if group and group not in self._groups:
            self._groups.add(group)
            tk.Label(self.sidebar,text=group,bg=SIDEBAR,fg=COLORS['GROUP'],font=theme.font(8,bold=True),
                     anchor='w').pack(fill='x',padx=25,pady=(10 if self._groups else 0,2))
        self.pages.append((frame,text))
        idx=len(self.pages)-1
        btn=tk.Button(self.sidebar, text=text, anchor='w', justify='left',
            bg=SIDEBAR,fg=MUTED,activebackground=HOVER,activeforeground=TEXT,
            bd=0,highlightthickness=0,relief='flat',cursor='hand2',
            padx=18,pady=6,font=theme.font(10),
            command=lambda i=idx:self.select(i))
        btn.pack(fill='x',padx=9,pady=0)
        self.buttons.append(btn)

    def add_advanced_toggle(self):
        """Kept for compatibility; every page is now visible in its group."""

    def index_of(self,title):
        for i,(_frame,text) in enumerate(self.pages):
            if text==title:return i
        raise KeyError('Unknown page: '+str(title))

    def select_named(self,title):
        """Select a page by its sidebar title; robust to page reordering."""
        self.select(self.index_of(title))

    def select(self,index):
        if isinstance(index,str) and index.isdigit():index=int(index)
        if index < 0 or index >= len(self.pages):return
        if self.current>=0:self.pages[self.current][0].pack_forget()
        frame,title=self.pages[index]
        frame.pack(fill='both',expand=True)
        self.heading_var.set(title)
        for i,b in enumerate(self.buttons):
            b.configure(bg=PANEL2 if i==index else SIDEBAR,
                        fg=TEXT if i==index else MUTED,
                        font=theme.font(10,bold=i==index))
        self.current=index
        if self.on_select:
            try:self.on_select(title)
            except Exception:pass

class App:
    def __init__(self,root):
        self.root=root;self.settings=app_settings();self.log=applog.get('ui')
        self.jobs=JobManager(logger=applog.get('jobs'));self.notifications=[]
        self.toasts=ui_extras.Toasts(root,COLORS,history=self.notifications)
        self.activity=ui_extras.ActivityPanel(root,COLORS,self.jobs,self.notifications)
        self.watcher=None;self._loaded_article=None;self._draft_timer=None
        self.db=CatalogDB();self.importer=Importer(self.db)
        seed_mechanics_pages(self.db)
        seed_hitbox_pages(self.db)
        seed_sailing_pages(self.db)
        build_research_articles(self.db)
        self.running=False;self.cancel_event=None;self.status_events=queue.Queue();self.last_manifest=None;self.downloaded_installer=None
        self.selected_article=None;self.selected_record=None;self.selected_combat=None;self.search_timer=None
        self.offline_update_path=None;self.offline_update_info=None
        self.model_library=ModelLibrary()
        self.ship_build='Game'
        init_network_db(self.db.conn);self.network_proc=None;self.network_sid=None;self.network_capture_path=None;self.network_pending_events=[]
        self.gameplay_session=None;self.gameplay_overlay=None;self.last_gameplay_dir=None;self.gameplay_hotkeys=None
        self.root.title('WoSB Workbench v'+VERSION+' — Research Center')
        self.root.geometry(self.settings.get('ui.geometry','1430x890') or '1430x890');self.root.minsize(1120,700)
        self.root.configure(bg=NAVY)
        self._styles();self._layout();self.refresh_all();self._poll_events()
        self.root.protocol('WM_DELETE_WINDOW',self._close)
        self._bind_shortcuts()
        last=self.settings.get('ui.last_page','Overview')
        try:self.tabs.select_named(last)
        except KeyError:pass
        self.tabs.on_select=lambda title:self.settings.set('ui.last_page',title)
        if self.settings.get('capture.auto_capture',False):self.root.after(1500,self._start_watcher)
        if not self.settings.get('first_run_complete',False):self.root.after(700,self._open_setup_wizard)
        self.root.after(900,self._repair_saved_installs)
        self.root.after(1200,self._refresh_dashboard)
        if self.settings.get('updates.check_on_startup',True):self.root.after(4000,lambda:self._github_check(silent=True))

    def _styles(self):
        s=ttk.Style(self.root)
        theme.apply_ttk(s,COLORS,scale=float(self.settings.get('ui.font_scale',1.0) or 1.0))

    def _text(self,parent,**kwargs):
        return tk.Text(parent,bg=PANEL,fg=TEXT,insertbackground=TEXT,selectbackground=COLORS['TEXT_SELECT'],
            relief='flat',borderwidth=8,font=('Consolas',10),wrap='word',**kwargs)

    def _layout(self):
        # Application shell: sidebar navigation, persistent page context and spacious work area.
        shell=tk.Frame(self.root,bg=NAVY);shell.pack(fill='both',expand=True)
        side=tk.Frame(shell,bg=SIDEBAR,width=232);side.pack(side='left',fill='y');side.pack_propagate(False)
        tk.Label(side,text='WoSB',bg=SIDEBAR,fg=ACCENT,
                 font=('Segoe UI Semibold',25),anchor='w').pack(fill='x',padx=24,pady=(27,0))
        tk.Label(side,text='WORKBENCH  ·  RESEARCH CENTER',bg=SIDEBAR,fg=MUTED,
                 font=theme.font(9),anchor='w').pack(fill='x',padx=25,pady=(0,12))
        main=tk.Frame(shell,bg=NAVY);main.pack(side='left',fill='both',expand=True)
        titlebar=tk.Frame(main,bg=NAVY);titlebar.pack(fill='x',padx=30,pady=(22,6))
        self.page_heading=tk.StringVar(value='Overview')
        tk.Label(titlebar,textvariable=self.page_heading,bg=NAVY,fg=TEXT,
                 font=('Segoe UI Semibold',15)).pack(side='left')
        tk.Label(titlebar,text='v'+VERSION,bg=NAVY,fg=MUTED,font=theme.font(10)).pack(side='right')
        self.activity_button=ttk.Button(titlebar,text='Activity',style='Small.TButton',command=self.activity.open)
        self.activity_button.pack(side='right',padx=(0,10))
        ttk.Button(titlebar,text='🔍  Search everything   Ctrl+K',style='Small.TButton',command=self._open_search).pack(side='right',padx=(0,8))
        ttk.Separator(main,orient='horizontal').pack(fill='x',padx=28,pady=(4,12))
        content=tk.Frame(main,bg=NAVY);content.pack(fill='both',expand=True,padx=28,pady=(0,12))
        self.tabs=SidebarNavigation(content,side,self.page_heading)
        builders={'Overview':self._overview,'Client scans':self._scans,'Full Recovery':self._full_recovery_page,
                  'Datamining':self._datamining_page,'Catalog':self._catalog,'Wiki editor':self._wiki,
                  'Discovery Center':self._discovery,'Combat evidence':self._combat,'Sailing & wind':self._sailing,
                  'Ship 3D':self._ship_3d,'Import & export':self._import_export,'Updates':self._updates,
                  'Mechanics Lab':self._mechanics_lab,'Network Research Lab':self._network_lab,
                  'Advanced Research':self._advanced_research,'Settings':self._settings_page}
        # Build in the original order (some pages reference widgets created by earlier ones),
        # then add to the sidebar in grouped order.
        build_order=['Overview','Client scans','Full Recovery','Datamining','Catalog','Wiki editor','Discovery Center',
                     'Combat evidence','Sailing & wind','Ship 3D','Import & export','Updates','Mechanics Lab',
                     'Network Research Lab','Advanced Research','Settings']
        pages={}
        for name in build_order:
            page=ttk.Frame(content);pages[name]=page;builders[name](page)
        for group,names in PAGE_GROUPS:
            for name in names:self.tabs.add(pages[name],name,group=group)
        tk.Frame(side,bg=BORDER,height=1).pack(fill='x',padx=20,pady=(12,10))
        self.watcher_var=tk.StringVar(value='Auto-capture: off')
        tk.Label(side,textvariable=self.watcher_var,bg=SIDEBAR,fg=MUTED,justify='left',
                 font=theme.font(9)).pack(anchor='w',padx=23)
        tk.Label(side,text='Everything stays on this computer',bg=SIDEBAR,fg=MUTED,
                 justify='left',font=theme.font(9)).pack(anchor='w',padx=23,pady=(4,0))
        self.tabs.select(0)
        bottom=ttk.Frame(main);bottom.pack(fill='x',padx=28,pady=(0,14))
        self.status_var=tk.StringVar(value='Ready · Local, read-only game scanning')
        ttk.Label(bottom,textvariable=self.status_var,style='Muted.TLabel').pack(side='left')
        ttk.Label(bottom,text='Database: '+str(self.db.path),style='Muted.TLabel').pack(side='right')
        self.jobs_var=tk.StringVar(value='')
        ttk.Label(bottom,textvariable=self.jobs_var,style='Section.TLabel').pack(side='right',padx=16)

    def _advanced_research(self,parent):
        """Usable opt-in UI for evidence-only advances, all game paths read-only."""
        self._heading(parent,'Advanced Research & Release QA',
                      'Geometry raycasts, packet continuity, recovery triage, controlled HP observations and client catalog comparison. Game physics remains evidence-gated.')
        tk.Label(parent,text='Choose an operation. Source files are never modified. JSON reports and experiment data are written outside the game installation.',
                 bg=NAVY,fg=MUTED,wraplength=980,justify='left').pack(anchor='w',pady=(0,12))
        bar=ttk.Frame(parent);bar.pack(fill='x',pady=6)
        buttons=[('Audit mesh + raycaster', 'geometry'),('Classify recovery failures','recovery'),
                 ('Inspect PCAP continuity','network'),('Audit local release','release'),
                 ('Catalog client comparison','catalog'),('Video event candidates','video'),('CPU benchmark','benchmark')]
        for title,action in buttons:
            ttk.Button(bar,text=title,command=lambda a=action:self._advanced_action(a)).pack(side='left',padx=(0,6))
        ttk.Button(bar,text='Open last result as table',command=lambda:self._show_result(getattr(self,'_last_advanced_result',{}) or {},
                   'Advanced research result')).pack(side='left',padx=(12,0))
        self.advanced_output=self._text(parent,height=14)
        self.advanced_output.pack(fill='both',expand=True,pady=(9,13))
        self.advanced_output.insert('1.0','The existing Ship 3D, Mechanics Lab, and Combat Evidence tools remain available.\n'
            'This page adds independently auditable, nonauthoritative research reports.\n'
            'For guided command-line workflows run: py -3.13 advanced_research_cli.py --help\n')
        form=ttk.LabelFrame(parent,text='Record an observed HP trial (local, opt-in)',padding=12)
        form.pack(fill='x',pady=(5,8))
        self.advanced_fields={}
        names=[('ship','Ship'),('target','Target'),('weapon','Weapon'),('ammo','Ammo'),
               ('before','HP before'),('after','HP after'),('hits','Hits')]
        for i,(key,title) in enumerate(names):
            cell=ttk.Frame(form);cell.grid(row=0,column=i,padx=(0,8),sticky='ew');form.grid_columnconfigure(i,weight=1)
            ttk.Label(cell,text=title).pack(anchor='w')
            field=ttk.Entry(cell,width=16);field.pack(fill='x')
            if key=='hits':field.insert(0,'1')
            self.advanced_fields[key]=field
        ttk.Button(form,text='Save measured observation',command=self._advanced_record_trial).grid(row=1,column=0,columnspan=3,sticky='w',pady=(12,0))
        ttk.Button(form,text='Export experiment evidence ZIP',command=self._advanced_export_trials).grid(row=1,column=3,columnspan=3,sticky='w',pady=(12,0))

    def _advanced_display(self,result):
        self._last_advanced_result=result
        text=json.dumps(result,indent=2,ensure_ascii=False,default=str)
        self.advanced_output.delete('1.0','end')
        self.advanced_output.insert('1.0',text[:100000]+('\n... output truncated' if len(text)>100000 else ''))
        self._status('Advanced research complete; view saved local report')

    def _advanced_action(self,action):
        import advanced_geometry,advanced_assets,advanced_network,advanced_release,advanced_catalog
        if action=='release':
            source=bundled_path('.')
            dest=home()/'Diagnostics'/'Advanced-Release-Readiness.json'
            task=(lambda:advanced_release.audit_frozen_runtime(source,version=VERSION)) if getattr(sys,'frozen',False) else (lambda:advanced_release.make_manifest(source,version=VERSION))
        elif action=='benchmark':
            from advanced_performance import benchmark_geometry
            dest=home()/'Diagnostics'/'CPU-Geometry-Benchmark.json'
            task=lambda:benchmark_geometry()
        elif action=='catalog':
            dest=home()/'Research'/'Client-Catalog-Diff.json'
            def task():
                import sqlite3
                from contextlib import closing
                with closing(sqlite3.connect(str(self.db.path))) as conn:
                    conn.row_factory=sqlite3.Row
                    a=advanced_catalog.dataset_snapshot(conn,'Steam')
                    b=advanced_catalog.dataset_snapshot(conn,'Game')
                    return advanced_catalog.compare_catalogs(a,b)
        else:
            extensions={'geometry':[('Wavefront OBJ','*.obj')],
                        'recovery':[('Asset ledger','*.jsonl')],
                        'network':[('PCAP / PCAPNG','*.pcap *.pcapng')],
                        'video':[('Video files','*.mp4 *.mov *.mkv *.avi')]}
            source=filedialog.askopenfilename(title='Choose source for '+action,
                 filetypes=extensions[action]+[('All files','*.*')],parent=self.root)
            if not source:return
            dest=home()/'Research'/('Advanced-'+action.title()+'-'+Path(source).stem+'.json')
            if action=='geometry':
                def task():
                    from ship_viewer import read_obj
                    from model_quality import inspect_mesh
                    mesh=read_obj(source)
                    caster=advanced_geometry.MeshRaycaster(mesh)
                    return {'mesh_quality':inspect_mesh(mesh), 'mesh_bounds':caster.bounds(),
                            'rendered_triangle_count':caster.size,
                            'raycast_ready':True,'verified_game_hitboxes':False,
                            'next_step':'Run advanced_research_cli.py geometry with --rays and optional --armor for measured impact research'}
            elif action=='recovery':task=lambda:advanced_assets.recovery_triage(source)
            elif action=='video':
                from advanced_video import candidate_events
                task=lambda:candidate_events(source)
            else:task=lambda:advanced_network.analyze_stream_continuity(source)
        self._status('Analyzing '+action+' · read-only')
        def worker():
            try:
                report=task()
                dest.parent.mkdir(parents=True,exist_ok=True)
                from advanced_io import write_json_atomic
                write_json_atomic(dest,report)
                self.status_events.put(('finished',self._advanced_display,{'report':report,'saved_to':str(dest)}))
            except Exception as exc:self.status_events.put(('error',str(exc)))
        threading.Thread(target=worker,daemon=True).start()

    def _advanced_record_trial(self):
        from advanced_experiments import open_db,add_experiment,add_observation
        from contextlib import closing
        try:
            data={k:v.get().strip() for k,v in self.advanced_fields.items()}
            before=float(data['before']);after=float(data['after']);hits=int(data['hits'])
            if not (math.isfinite(before) and math.isfinite(after)) or before<0 or after<0:
                raise ValueError('HP values must be non-negative numbers')
            if hits<1:raise ValueError('Hits must be at least 1')
            if after>before:raise ValueError('HP after is larger than HP before; check the values (healing is not a damage sample)')
            with closing(open_db(home()/'Research'/'Combat-Experiments.sqlite3')) as conn:
                experiment_id=add_experiment(conn,ship=data['ship'],target=data['target'],
                                              weapon=data['weapon'],ammunition=data['ammo'])
                observation_id=add_observation(conn,experiment_id,hp_before=float(data['before']),
                                                hp_after=float(data['after']),hits=int(data['hits']),
                                                source='GUI manually entered HP',human_verified=False)
            self._advanced_display({'saved':True,'experiment_id':experiment_id,'observation_id':observation_id,
                                    'measured_hp_per_hit':(float(data['before'])-float(data['after']))/int(data['hits']),
                                    'status':'observed HP, not verified exact server formula'})
        except Exception as exc:self._error('Combat observation',exc)

    def _advanced_export_trials(self):
        from advanced_experiments import open_db,export_experiments
        from contextlib import closing
        try:
            target=filedialog.asksaveasfilename(title='Export experiment evidence',defaultextension='.zip',
                   filetypes=[('ZIP','*.zip')],parent=self.root)
            if not target:return
            with closing(open_db(home()/'Research'/'Combat-Experiments.sqlite3')) as conn:
                result=export_experiments(conn,target)
            self._advanced_display(result)
        except Exception as exc:self._error('Export experiment evidence',exc)

    def _open_local_wiki(self, route='/'):
        try:
            import wiki_server
            server=getattr(self,'_wiki_http_server',None)
            if server is None:
                server,address=wiki_server.serve(self.db.path,port=0,open_browser=False)
                self._wiki_http_server=server;self._wiki_http_address=address
            webbrowser.open(self._wiki_http_address.rstrip('/')+('/'+str(route).lstrip('/')))
            self._status('Local web wiki: '+self._wiki_http_address)
        except Exception as exc:
            self._error('Local web wiki',exc)

    def _check_setup(self):
        roots=self.settings.game_roots() or [self.full_game_var.get() if hasattr(self,'full_game_var') else GAME_PATHS[0]]
        def task():
            from research_suite import setup_report
            report=setup_report(roots=roots)
            dest=home()/'Diagnostics'/'Setup-Check.json';dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_text(json.dumps(report,indent=2),encoding='utf-8')
            return report,str(dest)
        def done(value):
            report,dest=value
            missing=[k for k,v in report['tools'].items() if not v.get('found')]
            self._notice('Setup check',('Missing: '+', '.join(missing) if missing else 'All helper tools found')+
                         f" · {report['disk_free_gb']} GB free",kind='warning' if missing else 'success',
                         action=('Details',lambda:self._show_result(report,'Setup check',dest)))
        self._run_async(task,done,'Checking dependencies and disk space…')

    def _check_release(self):
        try:
            from research_suite import release_audit
            report=release_audit(bundled_path('.'),source_db=self.db.path)
            dest=home()/'Diagnostics'/'Release-Readiness-v4.3.json';dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_text(json.dumps(report,indent=2),encoding='utf-8')
            messagebox.showinfo('Release Readiness',str(report['passed'])+' checks passed; '+str(report['failed'])+
                ' require attention.\nLive Windows recording and server formulas are not certified.\nSaved: '+str(dest),parent=self.root)
        except Exception as exc:self._error('Release audit',exc)

    def _open_hp_video_tool(self):
        try:
            from hp_bar_ui import open_hp_video_tool
            open_hp_video_tool(self.root)
        except Exception as exc:self._error('Video HP measurement',exc)

    def _heading(self,parent,title,desc=None):
        ttk.Label(parent,text=title,style='Title.TLabel').pack(anchor='w',pady=(8,3))
        if desc:ttk.Label(parent,text=desc,style='Muted.TLabel',wraplength=1060).pack(anchor='w',pady=(0,14))

    # ================================================================ Overview dashboard
    def _overview(self,parent):
        self._heading(parent,'Your WoSB Research Center','Recover the client, search the catalog and wiki, and capture and decode game traffic — everything stays on this computer.')
        self.stat_var=tk.StringVar()
        ttk.Label(parent,textvariable=self.stat_var,style='Muted.TLabel').pack(anchor='w',pady=(0,10))
        self.dash_cards=ttk.Frame(parent);self.dash_cards.pack(fill='x')
        for col in range(3):self.dash_cards.columnconfigure(col,weight=1)
        self.dash_vars={}
        cards=[('installs','Game installs','Settings'),('catalog','Catalog & wiki','Catalog'),('recovery','Last Full Recovery','Full Recovery'),
               ('protocol','Protocol definitions','Network Research Lab'),('capture','Latest capture','Network Research Lab'),('watcher','Auto-capture','Settings')]
        for i,(key,title,page) in enumerate(cards):
            card=ttk.Frame(self.dash_cards,style='Card.TFrame',padding=14)
            card.grid(row=i//3,column=i%3,sticky='nsew',padx=(0,10),pady=(0,10))
            ttk.Label(card,text=title,style='CardMuted.TLabel').pack(anchor='w')
            value=tk.StringVar(value='…');detail=tk.StringVar(value='')
            ttk.Label(card,textvariable=value,style='CardValue.TLabel').pack(anchor='w',pady=(2,0))
            ttk.Label(card,textvariable=detail,style='CardMuted.TLabel',wraplength=330,justify='left').pack(anchor='w',pady=(2,6))
            ttk.Button(card,text='Open',style='Small.TButton',command=lambda p=page:self.tabs.select_named(p)).pack(anchor='w')
            self.dash_vars[key]=(value,detail)
        ttk.Label(parent,text='Suggested next steps',style='Section.TLabel').pack(anchor='w',pady=(14,6))
        self.next_steps=ttk.Frame(parent);self.next_steps.pack(fill='x')
        ttk.Label(parent,text='Local web Codex',style='Section.TLabel').pack(anchor='w',pady=(16,6))
        tools=ttk.Frame(parent);tools.pack(fill='x',pady=(0,10))
        for i,(title,route) in enumerate([('Open Research Center','/studio'),('Shipyard & fitting','/workshop'),
                            ('Ballistics Studio','/ballistics-studio'),('Combat experiments','/experiments'),
                            ('Measured damage atlas','/damage-research'),('Video + packet correlation','/capture-research'),
                            ('Visual fidelity lab','/visual-parity'),('Wiki articles','/articles')]):
            ttk.Button(tools,text=title,style='Accent.TButton' if title=='Open Research Center' else 'TButton',
                command=lambda path=route:self._open_local_wiki(path)).grid(row=i//4,column=i%4,sticky='ew',padx=4,pady=4)
        for col in range(4):tools.columnconfigure(col,weight=1)
        toolkit=ttk.Frame(parent);toolkit.pack(fill='x',pady=(6,10))
        ttk.Button(toolkit,text='Check dependencies & disk space',command=self._check_setup).pack(side='left',padx=(0,8))
        ttk.Button(toolkit,text='Validate current release',command=self._check_release).pack(side='left',padx=(0,8))
        ttk.Button(toolkit,text='Measure HP from recorded video',command=self._open_hp_video_tool).pack(side='left',padx=(0,8))

    def _latest(self,folder,pattern):
        try:
            items=[p for p in Path(folder).glob(pattern)]
            return max(items,key=lambda p:p.stat().st_mtime) if items else None
        except OSError:return None

    def _refresh_dashboard(self):
        if not hasattr(self,'dash_vars'):return
        try:
            roots=self.settings.game_roots()
            installs=self.settings.get('installs',{}) or {}
            self.dash_vars['installs'][0].set(str(len(roots)))
            self.dash_vars['installs'][1].set('\n'.join(f'{k.title()}: {v}' for k,v in installs.items() if v) or 'None configured yet — run setup.')
            stats=self.db.stats()
            self.dash_vars['catalog'][0].set(f"{stats['records']:,}")
            self.dash_vars['catalog'][1].set(f"catalog records · {stats['articles']:,} wiki pages · {stats['combat_evidence']:,} combat methods")
            status=self._latest(home()/'FullRecovery','*/Recovery-Status.json')
            if status:
                rec=json.loads(status.read_text(encoding='utf-8'))
                self.dash_vars['recovery'][0].set(str(rec.get('result') or rec.get('status') or 'saved'))
                self.dash_vars['recovery'][1].set('Updated '+__import__('datetime').datetime.fromtimestamp(status.stat().st_mtime).strftime('%Y-%m-%d %H:%M'))
            else:
                self.dash_vars['recovery'][0].set('—');self.dash_vars['recovery'][1].set('Not run yet.')
            latest=home()/'Research'/'Protocol'/'Protocol-Definitions-latest.json'
            if latest.is_file():
                d=json.loads(latest.read_text(encoding='utf-8'))
                self.dash_vars['protocol'][0].set(str(len(d.get('message_types',[]))))
                self.dash_vars['protocol'][1].set(f"message classes · {len(d.get('opcode_enums',[]))} opcode enums · {d.get('label','')}")
            else:
                self.dash_vars['protocol'][0].set('—');self.dash_vars['protocol'][1].set('Extract message definitions from your client.')
            sessions=[x for x in (self._latest(home()/'GameplaySessions','*'),self._latest(home()/'AutoCaptures','*')) if x]
            if sessions:
                newest=max(sessions,key=lambda p:p.stat().st_mtime)
                self.dash_vars['capture'][0].set(newest.name[:22])
                self.dash_vars['capture'][1].set(str(newest.parent.name))
            else:
                self.dash_vars['capture'][0].set('—');self.dash_vars['capture'][1].set('No sessions recorded yet.')
            state=self.watcher.status()['state'] if self.watcher else 'off'
            self.dash_vars['watcher'][0].set(state.title())
            self.dash_vars['watcher'][1].set('Records and analyzes automatically while you play.' if self.watcher else 'Enable in Settings (passive, local).')
            steps=[]
            if not roots:steps.append(('Run setup to find your game installs','setup'))
            if not stats['records']:steps.append(('Run Full Recovery to build the catalog','Full Recovery'))
            if not latest.is_file():steps.append(('Extract message definitions from the client','Datamining'))
            if not sessions:steps.append(('Record a gameplay session or turn on auto-capture','Network Research Lab'))
            steps.append(('Check what is still undecoded (coverage report)','Datamining'))
            for child in self.next_steps.winfo_children():child.destroy()
            for text,target in steps[:5]:
                ttk.Button(self.next_steps,text='→  '+text,command=(self._open_setup_wizard if target=='setup' else
                           (lambda t=target:self.tabs.select_named(t)))).pack(anchor='w',pady=2)
        except Exception as exc:
            self.log.warning('Dashboard refresh failed: %s',exc)
        self.root.after(15000,self._refresh_dashboard)

    # ================================================================ Settings page
    def _settings_page(self,parent):
        self._heading(parent,'Settings','Game folders, helper tools, capture, appearance and logs. Saved automatically.')
        row=ttk.Frame(parent);row.pack(fill='x',pady=(0,10))
        ttk.Button(row,text='Run setup wizard',style='Accent.TButton',command=self._open_setup_wizard).pack(side='left')
        ttk.Button(row,text='Open logs folder',command=applog.open_log_folder).pack(side='left',padx=8)
        ttk.Button(row,text='Open data folder',command=lambda:self._open_path(home())).pack(side='left')
        cap=ttk.LabelFrame(parent,text='Automatic capture',padding=12);cap.pack(fill='x',pady=6)
        self.auto_capture_var=tk.BooleanVar(value=bool(self.settings.get('capture.auto_capture',False)))
        ttk.Checkbutton(cap,text='Capture and analyze my game traffic automatically while the game is connected',
                        variable=self.auto_capture_var,command=self._toggle_auto_capture).pack(anchor='w')
        ttk.Label(cap,text='Passive and local: TShark records only the game port of your own connection; when you disconnect, '
                  'Protocol Lab catalogs the session and a summary appears in Activity. Needs TShark + Npcap.',
                  style='Muted.TLabel',wraplength=980).pack(anchor='w',pady=(4,0))
        rec=ttk.LabelFrame(parent,text='After Full Recovery',padding=12);rec.pack(fill='x',pady=6)
        self.after_protocol_var=tk.BooleanVar(value=bool(self.settings.get('recovery.extract_protocol_after_recovery',True)))
        self.after_version_var=tk.BooleanVar(value=bool(self.settings.get('recovery.track_client_versions',True)))
        ttk.Checkbutton(rec,text='Extract protocol message definitions from the recovered client',variable=self.after_protocol_var,
                        command=lambda:self.settings.set('recovery.extract_protocol_after_recovery',bool(self.after_protocol_var.get()))).pack(anchor='w')
        ttk.Checkbutton(rec,text='Track client versions and write a “datamined changes” wiki page when the client updates',variable=self.after_version_var,
                        command=lambda:self.settings.set('recovery.track_client_versions',bool(self.after_version_var.get()))).pack(anchor='w')
        look=ttk.LabelFrame(parent,text='Appearance',padding=12);look.pack(fill='x',pady=6)
        self.theme_var=tk.StringVar(value=self.settings.get('ui.theme','dark'))
        for value in ('dark','light'):
            ttk.Radiobutton(look,text=value.title(),value=value,variable=self.theme_var,
                            command=lambda:(self.settings.set('ui.theme',self.theme_var.get()),
                                            self._notice('Theme','The new theme applies the next time Workbench starts.'))).pack(side='left',padx=(0,14))
        ttk.Label(look,text='Text size').pack(side='left',padx=(20,6))
        self.scale_var=tk.StringVar(value=str(self.settings.get('ui.font_scale',1.0)))
        ttk.Combobox(look,textvariable=self.scale_var,values=['0.9','1.0','1.1','1.25','1.5'],width=6,state='readonly').pack(side='left')
        self.scale_var.trace_add('write',lambda *_:self.settings.set('ui.font_scale',float(self.scale_var.get())))
        self.toasts_var=tk.BooleanVar(value=bool(self.settings.get('ui.toasts',True)))
        ttk.Checkbutton(look,text='Show notifications as toasts (instead of dialogs)',variable=self.toasts_var,
                        command=lambda:self.settings.set('ui.toasts',bool(self.toasts_var.get()))).pack(side='left',padx=20)
        tools=ttk.LabelFrame(parent,text='Helper tools',padding=12);tools.pack(fill='x',pady=6)
        self.tools_text=tk.StringVar(value='Checking…')
        ttk.Label(tools,textvariable=self.tools_text,justify='left').pack(anchor='w')
        ttk.Button(tools,text='Re-check tools',style='Small.TButton',command=self._refresh_tools).pack(anchor='w',pady=(6,0))
        self.root.after(900,self._refresh_tools)

    def _refresh_tools(self):
        def task():
            import install_detect
            return install_detect.detect_tools()
        def done(tools):
            self.tools_text.set('\n'.join(('✔ ' if t['found'] else '✖ ')+f"{name:<9} {t['purpose']}"+('' if t['found'] else '  — '+t['get_it'])
                                          for name,t in tools.items()))
        self._run_async(task,done,'Checking helper tools…',name='Check helper tools')

    def _open_setup_wizard(self):
        def saved():
            self._apply_settings_to_pages();self._refresh_dashboard()
            if self.settings.get('capture.auto_capture'):self._start_watcher()
            else:self._stop_watcher()
            self._notice('Setup saved','Your folders and preferences were saved. Theme changes apply after restart.',kind='success')
        ui_extras.SetupWizard(self.root,COLORS,self.settings,on_saved=saved).open()

    def _apply_settings_to_pages(self):
        installs=self.settings.get('installs',{}) or {}
        if hasattr(self,'full_game_var') and (installs.get('game') or installs.get('steam')):
            self.full_game_var.set(installs.get('game') or installs.get('steam'))
        if hasattr(self,'path_vars'):
            import install_detect
            for var,key in zip(self.path_vars,('game','launcher','steam')):
                if installs.get(key):var.set(installs[key])
                elif install_detect.is_workbench_dir(var.get().strip() or '.'):var.set('')
        if hasattr(self,'gameplay_port'):self.gameplay_port.set(str(self.settings.get('capture.port',23771)))
        if hasattr(self,'auto_capture_var'):self.auto_capture_var.set(bool(self.settings.get('capture.auto_capture',False)))

    # ================================================================ shortcuts / search
    def _bind_shortcuts(self):
        self.root.bind_all('<Control-k>',lambda _e:self._open_search())
        self.root.bind_all('<Control-K>',lambda _e:self._open_search())
        self.root.bind_all('<Control-s>',lambda _e:self._save_article() if self.tabs.pages[self.tabs.current][1]=='Wiki editor' else None)
        self.root.bind_all('<Control-Shift-A>',lambda _e:self.activity.open())
        self.root.bind_all('<F1>',lambda _e:self._open_local_wiki('/guides'))

    def _open_search(self):
        def open_article(aid):
            self.tabs.select_named('Wiki editor');self._select_article(aid)
        def open_record(rid):
            self.tabs.select_named('Catalog')
            if not self.record_table.exists(str(rid)):
                self.record_search.set('');self.category.set('All');self.refresh_records()
            if self.record_table.exists(str(rid)):
                self.record_table.selection_set(str(rid));self.record_table.see(str(rid))
        def open_combat(cid):
            self.tabs.select_named('Combat evidence')
            if not self.combat_table.exists(str(cid)):
                self.combat_search.set('');self.refresh_combat()
            if self.combat_table.exists(str(cid)):
                self.combat_table.selection_set(str(cid));self.combat_table.see(str(cid))
        def extra(q):
            out=[];needle=q.casefold()
            latest=home()/'Research'/'Protocol'/'Protocol-Definitions-latest.json'
            if latest.is_file():
                try:
                    d=json.loads(latest.read_text(encoding='utf-8'))
                    for m in d.get('message_types',[]):
                        if needle in m['type'].casefold():
                            out.append(('Protocol',m['type'],'message class · '+', '.join(f['name'] for f in m.get('fields',[])[:8]),('path',str(latest))))
                    for e in d.get('opcode_enums',[]):
                        for name,value in e.get('members',{}).items():
                            if needle in name.casefold():out.append(('Opcode',f"{e['name']}.{name}",f'value {value}',('path',str(latest))))
                except (OSError,ValueError):pass
            index=home()/'Research'/'Decompiled'/'Source-Index.sqlite3'
            if index.is_file():
                try:
                    import datamine
                    for hit in datamine.search_sources(index,q,limit=20):
                        target=home()/'Research'/'Decompiled'/hit['path']
                        out.append(('Source',hit['name'] if hit['kind']!='text' else hit['path'],
                                    (hit['kind']+' · '+hit['path']+(f":{hit['line']}" if hit['line'] else '')) if hit['kind']!='text' else hit['name'],
                                    ('path',str(target))))
                except Exception:pass
            return out[:60]
        ui_extras.GlobalSearch(self.root,COLORS,self.db,open_article=open_article,open_record=open_record,
                               open_combat=open_combat,extra=extra).open()

    def _show_result(self,data,title,path=None):
        ui_extras.ResultViewer(self.root,COLORS,data,title=title,path=path).open()

    # ================================================================ auto-capture watcher
    def _toggle_auto_capture(self):
        on=bool(self.auto_capture_var.get())
        if on and os.name!='nt':
            self.auto_capture_var.set(False)
            return self._notice('Auto-capture','Automatic capture needs Windows (game connection detection uses Windows networking).',kind='warning')
        self.settings.set('capture.auto_capture',on)
        self._start_watcher() if on else self._stop_watcher()

    def _start_watcher(self):
        if self.watcher is not None:return
        try:
            from game_watcher import GameWatcher
            iface=str(self.settings.get('capture.interface','') or '') or None
            self.watcher=GameWatcher(home()/'AutoCaptures',interface=iface,
                on_event=lambda kind,info:self.status_events.put(('watcher',kind,info)))
            self.watcher.start_background()
            self.watcher_var.set('Auto-capture: watching for the game')
        except Exception as exc:
            self.watcher=None;self._error('Auto-capture',exc)

    def _stop_watcher(self):
        if self.watcher is None:return
        watcher=self.watcher;self.watcher=None
        self.jobs.submit('Stop auto-capture',lambda ctx:watcher.stop_background(finish=True))
        self.watcher_var.set('Auto-capture: off')

    def _watcher_event(self,kind,info):
        if kind=='capture-started':
            self.watcher_var.set('● Auto-capture: recording (port '+str(info.get('port'))+')')
            self._notice('Auto-capture started','Recording your game traffic passively to '+info['session'],kind='success')
        elif kind=='capture-stopped':
            self.watcher_var.set('Auto-capture: analyzing session…')
        elif kind=='analysis-finished':
            self.watcher_var.set('Auto-capture: watching for the game')
            summary=info.get('summary',{})
            text=f"{summary.get('messages',0):,} messages · {summary.get('types',0)} types · {summary.get('framing') or 'no framing found'}"
            if summary.get('warning'):text+='\n'+summary['warning']
            self._notice('Session analyzed',text,kind='success',
                         action=('Open report',lambda p=summary.get('report'):self._open_path(Path(p).parent) if p else None))
            try:
                body=('# Auto-capture '+Path(info['session']).name+'\n\nTags: capture, protocol\n\n'
                      f"- Messages: {summary.get('messages',0):,}\n- Message types: {summary.get('types',0)}\n"
                      f"- Framing hypothesis: {summary.get('framing')}\n- Report: `{summary.get('report')}`\n\n"
                      'Automatically recorded while the game was connected. Associations are hypotheses until verified.\n')
                self.db.upsert_article('capture-'+slugify(Path(info['session']).name),'Auto-capture '+Path(info['session']).name,
                                       'Networking and protocols',body,'auto-capture',info['session'],'source-only')
                self.db.conn.commit();self.refresh_articles()
            except Exception as exc:self.log.warning('Could not write capture wiki page: %s',exc)
        elif kind=='error':
            self.watcher_var.set('Auto-capture: problem (see Activity)')
            self.notifications.append({'time':__import__('time').strftime('%H:%M:%S'),'title':'Auto-capture','message':info.get('error',''),'kind':'error'})
        self._refresh_dashboard_soon()

    def _refresh_dashboard_soon(self):
        try:self.root.after(300,lambda:None)
        except tk.TclError:pass

    # ================================================================ Datamining page
    def _datamining_page(self,parent):
        self._heading(parent,'Datamining','Close the gaps: see what is still undecoded, decompile the client to searchable C#, extract message definitions and audio, and track client updates.')
        grid=ttk.Frame(parent);grid.pack(fill='x')
        actions=[('Decode coverage report','Every file type in an install, which decoder handles it, and what is still undecoded.',self._dm_coverage),
                 ('Extract message definitions','Message classes, wire field order and opcode enums from client / Steam / launcher assemblies.',self._protocol_extract),
                 ('Decompile client to C# (ILSpy)','Full C# projects per assembly plus a searchable source index (needs .NET SDK + ilspycmd).',self._dm_decompile),
                 ('Search decompiled source','Find classes, methods and text across the decompiled client.',self._dm_search_source),
                 ('Track client version','Fingerprint an install; when it changed, diff assets and write a “datamined changes” wiki page.',self._dm_track_versions),
                 ('Extract audio bank (.xwb)','XACT wave banks to WAV files (PCM / ADPCM); other codecs saved raw.',self._dm_wave_bank),
                 ('Compare definitions between builds','Added/removed message classes, field changes and renumbered opcodes.',self._protocol_diff),
                 ('Protocol message browser','Hex view per message type, field inference and schema editing; exports Wireshark/ImHex/Kaitai.',self._open_message_browser),
                 ('Recover ALL installations','Run Full Recovery on every configured Game/Steam/launcher folder.',self._start_all_recovery),
                 ('Rebuild ship hitboxes','Corpus, sail and mast hitboxes for every recovered ship, built with the client\'s own hitbox rules.',self._dm_hitboxes),
                 ('Damage model reference','How the client applies hull, sail, crew, fire and flooding damage, with a hit simulator.',self._dm_damage_model),
                 ('Unpack launcher code (app.asar)','Extract the Electron launcher\'s JavaScript so it can be read and searched.',self._dm_asar),
                 ('Free disk space','Remove duplicate Catalog-2, Catalog-3… exports (about 2.3 GB each), keeping the newest.',self._dm_cleanup),
                 ('Calibrate cannonball damage','Log measured hits (cannon, ammo, target, HP before/after) and fit the simulators\' damage to them.',self._dm_calibrate),
                 ('Battle & boarding simulators','3D battles with the real ship, tower and fort models: fleets, port battles, orders, scripts, batch runs; plus the boarding fight.',self._open_simulators),
                 ('Publish wiki to Band of Misfits','Upload the built wiki to bandofmisfits.org (needs an upload token from Dashboard → Wiki → Compendium).',self._publish_bom),
                 ('Publish wiki to wosbwiki.org','Push the built wiki to its private GitHub repository; Cloudflare Pages deploys it to wosbwiki.org (docs/WOSBWIKI-HOSTING.md).',self._publish_cloudflare),
                 ('Publish wiki to GitHub Pages','Push the built wiki folder to a gh-pages branch so the community can use it at <you>.github.io.',self._publish_wiki),
                 ('Build wiki website','A public fan wiki: ship/cannon/item pages, categories, guides, battle/boarding/damage simulators, wind and comparison tools.',self._build_wiki_site)]
        for i,(title,desc,cmd) in enumerate(actions):
            card=ttk.Frame(grid,style='Card.TFrame',padding=12);card.grid(row=i//3,column=i%3,sticky='nsew',padx=(0,10),pady=(0,10))
            ttk.Label(card,text=title,style='CardTitle.TLabel').pack(anchor='w')
            ttk.Label(card,text=desc,style='CardMuted.TLabel',wraplength=320,justify='left').pack(anchor='w',pady=(4,8))
            ttk.Button(card,text='Run',style='Small.TButton',command=cmd).pack(anchor='w')
        for col in range(3):grid.columnconfigure(col,weight=1)
        ttk.Label(parent,text='Results open in a sortable table view and are saved under your data folder → Research. '
                  'Nothing in the game folder is modified and no game code is executed.',style='Muted.TLabel',wraplength=1000).pack(anchor='w',pady=8)

    def _repair_saved_installs(self):
        """Earlier builds could save the Workbench's own folder as the game install."""
        try:cleared=self.settings.repair_installs()
        except Exception:return
        if not (self.settings.get('installs.game') or '').strip():
            try:
                import install_detect
                found=install_detect.detect_installs().get('game') or []
                if found:self.settings.update({'installs.game':found[0]});cleared=cleared or []
            except Exception:pass
        self._apply_settings_to_pages()
        if not cleared:return
        roots=self._known_installs()
        self._notice('Fixed install settings',
                     'Your saved '+'/'.join(cleared)+' install pointed at WoSB Workbench itself, so scans of it were '
                     'scanning this app. '+(('Now using: '+', '.join(roots)+'. ') if roots else '')+
                     'Re-run Full Recovery / Client scans to replace those results.',kind='warning',
                     action=('Open settings',lambda:self.tabs.select_named('Settings')))

    def _known_installs(self):
        """Saved installs; if none are saved, auto-detect and remember them."""
        roots=self.settings.game_roots()
        if roots:return roots
        try:
            import install_detect
            found=install_detect.detect_installs()
        except Exception:
            found={}
        changes={}
        for key in ('game','steam','launcher'):
            if found.get(key):changes['installs.'+key]=found[key][0]
        if changes:
            try:self.settings.update(changes)
            except Exception:pass
            roots=self.settings.game_roots()
            if roots:self._notice('Installs found','Using '+', '.join(roots)+'. Change them in Settings.',kind='success')
        return roots

    def _install_label(self,root):
        names={}
        for key,label in (('game','Game client'),('steam','Steam client'),('launcher','Launcher')):
            v=(self.settings.get('installs.'+key) or '').strip()
            if v:names.setdefault(str(Path(v)),label)
        return names.get(str(Path(root)),'Other folder')

    def _pick_install(self,title,*,ask_if_one=False):
        """Return an install folder without a file dialog whenever possible.

        One saved install is used directly; several open a one-click chooser;
        none offers the setup wizard (or browsing) instead."""
        roots=self._known_installs()
        if len(roots)==1 and not ask_if_one:return roots[0]
        if not roots:
            if messagebox.askyesno(title,'No World of Sea Battle installs are saved or detected.\n\n'
                                   'Open the setup wizard to set them now? (Choose No to browse for a folder.)',parent=self.root):
                self._open_setup_wizard();return None
            return filedialog.askdirectory(title=title,parent=self.root) or None
        options=[(r,r,self._install_label(r)) for r in roots]
        return ui_extras.Chooser(self.root,COLORS,title,'Pick the install to use. Double-click or press Enter.',options).show()

    def _sessions(self):
        items=[]
        for base in (home()/'GameplaySessions',home()/'AutoCaptures'):
            try:items+=[p for p in base.iterdir() if p.is_dir()]
            except OSError:pass
        return sorted(items,key=lambda p:p.stat().st_mtime,reverse=True)

    def _pick_session(self,title,*,prefer=None):
        """Use the current/most recent session; offer a chooser when several exist."""
        if prefer and Path(prefer).is_dir():return str(prefer)
        sessions=self._sessions()
        if not sessions:
            self._notice('No sessions yet','Record one in Gameplay Capture Studio, or turn on auto capture in Settings.',kind='warning')
            return None
        if len(sessions)==1:return str(sessions[0])
        from datetime import datetime as _dt
        options=[(p.name,str(p),p.parent.name+' · '+_dt.fromtimestamp(p.stat().st_mtime).strftime('%Y-%m-%d %H:%M')) for p in sessions[:200]]
        return ui_extras.Chooser(self.root,COLORS,title,'Newest first. The top session is preselected.',options).show()

    def _pick_files(self,title,options,*,filetypes,multiple=False,prompt='Newest first.'):
        if not options:
            if multiple:return list(filedialog.askopenfilenames(title=title,filetypes=filetypes,parent=self.root)) or None
            return filedialog.askopenfilename(title=title,filetypes=filetypes,parent=self.root) or None
        return ui_extras.Chooser(self.root,COLORS,title,prompt,options,browse='files' if multiple else 'file',filetypes=filetypes).show()

    def _session_captures(self):
        """Capture files from the newest sessions, as chooser options (value = sorted file list)."""
        out=[]
        for folder in self._sessions()[:100]:
            files=sorted(str(f) for f in folder.rglob('*') if f.suffix.lower() in ('.pcap','.pcapng'))
            if files:out.append((folder.name,files,f'{len(files)} capture file(s) · {folder.parent.name}'))
        return out

    def _dm_coverage(self):
        root=self._pick_install('Install folder to check (Game, Steam or launcher)')
        if not root:return
        def task(ctx):
            import datamine
            from advanced_io import write_json_atomic
            ledger=datamine.find_ledger(home(),root)
            ctx.progress(None,'Classifying files…')
            report=datamine.coverage_report(root,ledger=ledger)
            dest=home()/'Research'/'Coverage'/('Coverage-'+slugify(Path(root).name)+'.json')
            write_json_atomic(dest,report);ctx.set_output(dest)
            return report,str(dest)
        self._run_async(task,lambda r:self._show_result(r[0],'Decode coverage — '+Path(root).name,r[1]),'Building decode coverage report…')

    def _dm_decompile(self):
        roots=[r for r in self._known_installs() if self._install_label(r)!='Launcher']
        if len(roots)==1:root=roots[0]
        else:root=self._pick_install('Game client to decompile (the launcher has no .NET code)')
        if not root:return
        if not messagebox.askyesno('Decompile client','Decompile every .NET assembly in this folder to C# with ILSpy?\n\n'
                                   'This can take several minutes and a few hundred MB. The output is for your own research; do not redistribute it.',parent=self.root):return
        out=home()/'Research'/'Decompiled'
        configured=self.settings.get('tools.ilspycmd','') or None
        def task(ctx):
            import datamine
            summary=datamine.decompile_assemblies(root,out,ilspycmd=configured,progress=ctx.progress,cancel=ctx.cancel_event,
                                                  label=slugify(self._install_label(root)+'-'+Path(root).name))
            ctx.progress(None,'Indexing decompiled source…')
            summary['index']=datamine.build_source_index(out,out/'Source-Index.sqlite3')
            ctx.progress(None,'Extracting message layouts…')
            try:
                import source_schemas
                schemas=source_schemas.extract_from_index(out/'Source-Index.sqlite3')
                source_schemas.write_schemas(schemas,home()/'Research'/'Protocol'/'Message-Schemas.json')
                summary['schemas']=schemas
            except Exception as exc:
                summary['schemas_error']=str(exc)
            ctx.set_output(out)
            return summary
        def done(summary):
            ok=sum(1 for a in summary['assemblies'] if a.get('ok'))
            if summary.get('schemas'):
                import mechanics_reference
                mechanics_reference.seed_message_pages(self.db,summary['schemas']);self.refresh_articles()
            self._notice('Decompile finished',f"{ok}/{len(summary['assemblies'])} game assemblies ({summary.get('skipped_framework',0)} .NET runtime DLLs skipped) · {summary['index']['files']:,} source files indexed. "
                         'Use Search everything (Ctrl+K) to search the code.',kind='success',action=('Open folder',lambda:self._open_path(out)))
        self._run_async(task,done,'Decompiling client assemblies with ILSpy…')

    def _dm_hitboxes(self):
        import hitbox_recovery
        dirs=hitbox_recovery.find_models_dirs(home())
        if not dirs:
            self._notice('No recovered ships','Run Full Recovery on the game client first; it decodes the ship models.',kind='warning',
                         action=('Full Recovery',lambda:self.tabs.select_named('Full Recovery')));return
        src=dirs[0]
        if len(dirs)>1:
            src=ui_extras.Chooser(self.root,COLORS,'Recovered models','Newest recovery first.',
                                  [(str(d.parents[4].name),d,str(d)) for d in dirs]).show()
            if not src:return
        out=home()/'Research'/'Hitboxes'
        def task(ctx):
            ctx.set_output(out)
            return hitbox_recovery.batch(src,out,progress=ctx.progress)
        def done(res):
            import mechanics_reference
            mechanics_reference.seed_damage_pages(self.db);mechanics_reference.seed_hitbox_summary(self.db,res)
            self.refresh_articles()
            ok=sum(1 for s in res['ships'] if 'error' not in s)
            self._notice('Hitboxes rebuilt',f'{ok}/{len(res["ships"])} ships. The Ship 3D viewer now shows these zones; see the "Ship hitbox table" wiki page.',
                         kind='success',action=('Open folder',lambda:self._open_path(out)))
        self._run_async(task,done,'Rebuilding ship hitboxes…')

    def _dm_damage_model(self):
        import mechanics_reference
        mechanics_reference.seed_damage_pages(self.db);self.refresh_articles()
        win=tk.Toplevel(self.root);win.title('Damage simulator');win.geometry('760x560');win.configure(bg=COLORS['NAVY'])
        ttk.Label(win,text='Damage simulator',style='Section.TLabel').pack(anchor='w',padx=16,pady=(14,2))
        ttk.Label(win,text='Applies hits with the client\'s own HP, sinking, sail and fire rules. Hit amounts are your inputs '
                  '(the server decides those).',style='Muted.TLabel',wraplength=720).pack(anchor='w',padx=16)
        form=ttk.Frame(win);form.pack(fill='x',padx=16,pady=10)
        hp=tk.StringVar(value='5000');sails=tk.StringVar(value='6')
        ttk.Label(form,text='Max HP').grid(row=0,column=0,sticky='w');ttk.Entry(form,textvariable=hp,width=10).grid(row=0,column=1,padx=6)
        ttk.Label(form,text='Sails').grid(row=0,column=2,sticky='w');ttk.Entry(form,textvariable=sails,width=6).grid(row=0,column=3,padx=6)
        ttk.Label(win,text='Hits, one per line:  source damage [flags]   e.g.  CannonBall 800   ·   MortarShot 50   ·   CannonBall 0 SingleSailDamage sail=2 0.3',
                  style='Muted.TLabel',wraplength=720).pack(anchor='w',padx=16)
        box=tk.Text(win,height=8,bg=COLORS['PANEL'],fg=COLORS['TEXT'],insertbackground=COLORS['TEXT'],relief='flat')
        box.insert('1.0','CannonBall 1800\nCannonBall 1800\nCannonBall 1800\nCollision 100\n');box.pack(fill='x',padx=16)
        result=tk.Text(win,height=12,bg=COLORS['PANEL'],fg=COLORS['TEXT'],relief='flat');result.pack(fill='both',expand=True,padx=16,pady=10)
        def run():
            import damage_model as dm
            try:
                n=max(1,int(sails.get()));state=dm.ShipState(max_hp=float(hp.get()),sail_weights=[1/n]*n)
                lines=[]
                for raw in box.get('1.0','end').splitlines():
                    parts=raw.split()
                    if not parts:continue
                    data=dm.DamageData(source=dm.DamageID[parts[0]],health_damage=float(parts[1]) if len(parts)>1 else 0,source_uid=1)
                    for extra in parts[2:]:
                        if extra.startswith('sail='):data.collision_node_id=int(extra[5:])
                        elif extra in dm.Flags.__members__:data.flags|=dm.Flags[extra]
                        else:data.damage_to_sails=float(extra)
                    r=dm.apply_damage(state,data,source_ship_uid=data.source_uid)
                    lines.append(f"{raw.strip():<38} HP {r.get('hp_before',0):>8.1f} → {r.get('hp_after',0):>8.1f}   sails {r.get('sails_after',1)*100:5.1f}%"
                                 +('   SINKING' if r.get('sinking') else '')+('   DESTROYED' if r.get('destroyed') else '')
                                 +(('   '+'; '.join(r['events'])) if r.get('events') else ''))
                result.delete('1.0','end');result.insert('1.0','\n'.join(lines) or 'No hits.')
            except (KeyError,ValueError,IndexError) as exc:
                result.delete('1.0','end');result.insert('1.0',f'Could not read that line: {exc}\nSources: '+', '.join(dm.DamageID.__members__))
        row=ttk.Frame(win);row.pack(fill='x',padx=16,pady=(0,12))
        ttk.Button(row,text='Simulate',style='Accent.TButton',command=run).pack(side='left')
        ttk.Button(row,text='Damage rules (wiki)',command=lambda:self._open_article_by_slug('damage-and-sinking')).pack(side='left',padx=8)
        run()

    def _open_article_by_slug(self,slug):
        row=self.db.conn.execute('SELECT id FROM articles WHERE slug=?',(slug,)).fetchone()
        if row:
            self.tabs.select_named('Wiki editor');self._select_article(row[0])

    def _dm_asar(self):
        candidates=[]
        for root in self._known_installs():
            try:candidates+=[p for p in Path(root).rglob('app.asar') if p.is_file()]
            except OSError:pass
        if not candidates:
            path=filedialog.askopenfilename(title='Electron app.asar',filetypes=[('Electron archive','*.asar')],parent=self.root)
            if not path:return
            candidates=[Path(path)]
        archive=candidates[0]
        out=home()/'Research'/'Launcher'/'app'
        def task(ctx):
            import datamine
            ctx.set_output(out)
            return datamine.extract_asar(archive,out)
        self._run_async(task,lambda r:self._notice('Launcher unpacked',f"{r['files_written']:,} files from {archive.name}.",kind='success',
                        action=('Open folder',lambda:self._open_path(out))),'Unpacking launcher…')

    def _dm_cleanup(self):
        reports=home()/'Reports'
        dupes=[];promote=[]   # newest export becomes 'Catalog' so importers use it
        if reports.is_dir():
            for scan in reports.iterdir():
                cats=[p for p in scan.glob('Catalog*') if p.is_dir() and (p.name in ('Catalog','Catalog-previous')
                      or p.name.split('-',1)[-1].isdigit())]
                if len(cats)<2:continue
                cats.sort(key=lambda p:p.stat().st_mtime)
                newest=cats[-1]
                dupes+=cats[:-1]
                if newest.name!='Catalog':promote.append((newest,scan/'Catalog'))
        if not dupes:
            self._notice('Nothing to clean','No duplicate catalog exports found.',kind='success');return
        def size(p):
            return sum(f.stat().st_size for f in p.rglob('*') if f.is_file())
        total=sum(size(p) for p in dupes)
        if not messagebox.askyesno('Free disk space',f'Delete {len(dupes)} older catalog export(s), {total/1e9:.1f} GB?\n\n'
                                   'The newest catalog in each scan is kept (and renamed to Catalog, so imports use it). This cannot be undone.',parent=self.root):return
        def task(ctx):
            for i,p in enumerate(dupes):
                ctx.progress(i/len(dupes),'Deleting '+p.name);shutil.rmtree(p,ignore_errors=True)
            for newest,target in promote:
                if not target.exists():newest.rename(target)
            return total
        self._run_async(task,lambda t:self._notice('Disk space freed',f'{t/1e9:.1f} GB removed.',kind='success'),'Removing old catalogs…')

    def _dm_calibrate(self):
        import damage_fit,battle_sim
        path=home()/'Research'/'Damage-Trials.csv';path.parent.mkdir(parents=True,exist_ok=True)
        if not path.exists():
            damage_fit.save_trials(path,[])
            self._notice('Damage trials sheet created','Fill one row per measured hit (cannon, ammo, target ship or armor, HP before and after; '
                         'distance, angle and zone if known), save, then run this again. HP readings from the HP-bar tool help.',kind='info',
                         action=('Open sheet',lambda:webbrowser.open(path.as_uri())))
            return
        res=battle_sim.calibration_from_trials(self.db,path)
        if not res.get('calibrated'):
            self._notice('Not enough measurements',str(res.get('reason')),kind='warning',action=('Open sheet',lambda:webbrowser.open(path.as_uri())));return
        out=home()/'Research'/'Damage-Calibration.json';out.write_text(json.dumps(res,indent=1),encoding='utf-8')
        self._notice('Damage calibrated',f"{res['samples']} hits · armor weight {res['armor_weight']} · scale {res['scale']} · mean error ±{res['mape']}%. "
                     'Rebuild the simulators or the wiki to use it.',kind='success')

    def _open_simulators(self):
        out=home()/'Simulators'
        installs=self._known_installs()
        def task(ctx):
            import battle_sim
            hb=battle_sim.ensure_hitboxes(home(),progress=lambda f,name:ctx.progress(f,f'Rebuilding hitboxes: {name}')) or home()/'Research'/'Hitboxes'
            rec=battle_sim.latest_recovery(home())
            ctx.set_output(out)
            prog=lambda i,n,name:ctx.progress(i/max(1,n),f'Packing model {i+1}/{n}: {name}')
            db=CatalogDB(self.db.path)   # SQLite connections can't cross threads: this job gets its own
            try:
                return battle_sim.build_simulators(db,out,hitboxes_dir=hb if hb.is_dir() else None,recovery_dir=rec,
                                                   game_roots=installs,progress=prog,damage_calibration=battle_sim.load_calibration(home()))
            finally:db.close()
        def done(m):
            pk=m.get('pack') or {}
            note=(f"{pk.get('models',0)} real models · {pk.get('textures',0)} textures" if pk.get('models') else
                  'No recovered models yet (run Full Recovery), so ships are drawn from their hull dimensions')
            self._notice('Simulators ready',f"{m['ships']} ships · {m['with_hitboxes']} with hitboxes · {m.get('port_sites',0)} port-battle sites · {note}.",
                         kind='success',action=('Open battle simulator',lambda:webbrowser.open((out/'battle_sim.html').as_uri())))
            try:webbrowser.open((out/'battle_sim.html').as_uri())
            except Exception:pass
        self._run_async(task,done,'Building simulators…')

    def _publish_wiki(self):
        import wiki_publish
        from tkinter import simpledialog
        site=home()/'WikiSite'
        remote=(self.settings.get('wiki.remote') or '').strip()
        if not remote:
            remote=(simpledialog.askstring('Publish wiki','GitHub repository URL for the wiki (it will get a gh-pages branch):\n'
                                           'e.g. https://github.com/you/wosb-wiki.git',parent=self.root) or '').strip()
            if not remote:return
            self.settings.update({'wiki.remote':remote})
        def task():return wiki_publish.publish(site,remote)
        def done(m):
            url=wiki_publish.pages_url(remote)
            self._notice('Wiki published',f"Pushed {m['commit']} to {m['branch']}. "+(f'Turn on GitHub Pages (Settings → Pages → branch gh-pages) once; then it is live at {url}' if url else ''),
                         kind='success',action=('Open site',lambda:webbrowser.open(url)) if url else None)
        self._run_async(task,done,'Publishing wiki…')

    def _publish_cloudflare(self):
        import wiki_publish
        from tkinter import simpledialog
        site=home()/'WikiSite'
        if not (site/'index.html').is_file():
            return self._notice('Build the wiki first','Run “Build wiki website”, then publish.',kind='warning')
        remote=(self.settings.get('wiki.cloudflare_remote') or 'https://github.com/ajtchess-code/wosbwiki.git').strip()
        if not remote:
            remote=(simpledialog.askstring('Publish to wosbwiki.org','URL of the PRIVATE GitHub repository that Cloudflare Pages deploys from:\n'
                                           'e.g. https://github.com/ajtchess-code/wosbwiki-site.git',parent=self.root) or '').strip()
            if not remote:return
            self.settings.update({'wiki.cloudflare_remote':remote})
        import git_push,secret_store
        token=None
        if not git_push.find_git():
            # No Git on this PC: push straight to GitHub with an access token instead.
            token=secret_store.load('wiki_publish_token')
            if not token:
                token=(simpledialog.askstring('Publish to wosbwiki.org',
                    'Git isn\'t installed, so Workbench uploads to GitHub directly. Paste a GitHub access token for this repository:\n\n'
                    'GitHub → Settings → Developer settings → Fine-grained tokens → Generate new token\n'
                    '• Repository access: Only select repositories → the wiki repository\n'
                    '• Permissions → Contents: Read and write\n\nThe token is stored encrypted for your Windows account.',parent=self.root,show='•') or '').strip()
                if not token:return
                secret_store.save('wiki_publish_token',token)
        def task(ctx=None):
            if token:
                try:return git_push.push(site,remote,token,branch='main',progress=(lambda msg:ctx.progress(None,msg)) if ctx else None)
                except git_push.PushError as e:
                    if 'refused the token' in str(e) or 'HTTP 404' in str(e):secret_store.save('wiki_publish_token','')
                    raise
            return wiki_publish.publish(site,remote,branch='main',snapshot=True)
        def done(m):
            live=(self.settings.get('wiki.site_url') or 'https://wosbwiki.org/')
            self._notice('Wiki sent to Cloudflare',f"Pushed {m['commit']} to {m['branch']}. Cloudflare Pages deploys it in a minute or two; then it is live at {live}",
                         kind='success',action=('Open site',lambda:webbrowser.open(live)))
        self._run_async(task,done,'Publishing to wosbwiki.org…')

    def _publish_bom(self):
        import bom_publish
        from tkinter import simpledialog
        site=home()/'WikiSite'
        if not (site/'index.html').is_file():
            return self._notice('Build the wiki first','Run “Build wiki website”, then publish.',kind='warning')
        url=(self.settings.get('bom.url') or bom_publish.DEFAULT_URL).strip()
        token=(self.settings.get('bom.token') or '').strip()
        if not token:
            token=(simpledialog.askstring('Publish to Band of Misfits','Paste the upload token from the dashboard\n(Dashboard → Wiki → Compendium → Create upload token):',
                                          parent=self.root,show='•') or '').strip()
            if not token:return
            self.settings.update({'bom.token':token,'bom.url':url})
        def task(ctx):
            return bom_publish.publish(site,token,url,progress=lambda msg:ctx.progress(None,msg))
        def done(m):
            live=url.rstrip('/')+'/'
            self._notice('Wiki published to Band of Misfits',f"Release {m.get('release','')} is live ({m.get('files',0):,} files).",kind='success',
                         action=('Open site',lambda:webbrowser.open(live)))
        self._run_async(task,done,'Publishing to Band of Misfits…')

    def _build_wiki_site(self):
        out=home()/'WikiSite'
        installs=self._known_installs()
        def task(ctx):
            import wiki_site,mechanics_reference,battle_sim
            db=CatalogDB(self.db.path)   # SQLite connections can't cross threads: this job gets its own
            try:
                mechanics_reference.seed_damage_pages(db)
                ctx.set_output(out)
                hb=battle_sim.ensure_hitboxes(home(),progress=lambda f,name:ctx.progress(f,f'Rebuilding hitboxes: {name}')) or home()/'Research'/'Hitboxes'
                return wiki_site.build_site(db,out,hitboxes_dir=hb if hb.is_dir() else None,recovery_dir=battle_sim.latest_recovery(home()),
                                            damage_calibration=battle_sim.load_calibration(home()),game_roots=installs,
                                            site_url=(self.settings.get('wiki.site_url') or 'https://wosbwiki.org/'),
                                            hosting={'ad_client':self.settings.get('wiki.ad_client'),'donate_url':self.settings.get('wiki.donate_url'),
                                                     'discord_url':self.settings.get('wiki.discord_url'),'contact_email':self.settings.get('wiki.contact_email'),
                                                     'standalone':self.settings.get('wiki.standalone',True)},
                                            progress=lambda i,n,name:ctx.progress(i/max(1,n),f'Packing model {i+1}/{n}: {name}'))
            finally:db.close()
        def done(m):
            self._notice('Wiki website built',f"{m['pages']:,} pages · {m['entities'].get('ship',0)} ships · {m['articles']} guides · "
                         f"{m['ships_with_hitboxes']} ships with hit zones · {m.get('models',0)} 3D models. Open index.html, or run “Publish wiki to wosbwiki.org”.",
                         kind='success',action=('Open site',lambda:webbrowser.open((out/'index.html').as_uri())))
        self._run_async(task,done,'Building wiki website…')

    def _dm_search_source(self):
        index=home()/'Research'/'Decompiled'/'Source-Index.sqlite3'
        if not index.is_file():
            return self._notice('No source index','Run “Decompile client to C#” first.',kind='warning')
        self._open_search()

    def _dm_track_versions(self):
        roots=self._known_installs()
        if not roots:
            root=self._pick_install('Install folder to fingerprint')
            if not root:return
            roots=[root]
        self._track_versions(roots,announce=True)

    def _track_versions(self,roots,*,announce=False):
        history=home()/'Research'/'ClientVersions'/'history.json'
        def task(ctx):
            import datamine
            changes=[]
            for i,root in enumerate(roots,1):
                ctx.progress((i-1)/len(roots),'Fingerprinting '+str(root))
                new,previous,current=datamine.track_version(root,history,label=Path(root).name)
                if new:changes.append((root,previous,current,datamine.changes_article(previous,current)))
            return changes
        def done(changes):
            for root,previous,current,body in changes:
                slug='datamined-changes-'+slugify(Path(root).name)+'-'+current['fingerprint']
                self.db.upsert_article(slug,'Datamined changes — '+Path(root).name+' '+current['taken_utc'][:10],
                                       'Client updates',body,'client-fingerprint',str(root),'source-only')
            self.db.conn.commit();self.refresh_articles()
            if changes:
                self._notice('Client update detected' if any(c[1] for c in changes) else 'Client versions recorded',
                             f'{len(changes)} install(s) recorded; see Wiki → Client updates.',kind='success')
            elif announce:
                self._notice('No client changes','All tracked installs match their last fingerprint.')
        self._run_async(task,done,'Checking client versions…')

    def _dm_wave_bank(self):
        roots=self._known_installs()
        banks=[]
        for root in roots:
            try:banks+=[p for p in Path(root).rglob('*.xwb') if p.is_file()]
            except OSError:pass
        banks=list(dict.fromkeys(banks))
        if not banks:
            path=filedialog.askopenfilename(title='No .xwb found in your installs — choose a wave bank',
                                            filetypes=[('Wave bank','*.xwb'),('All files','*.*')],parent=self.root)
            if not path:return
            banks=[Path(path)]
        base=home()/'Research'/'Audio'
        def task(ctx):
            import datamine
            ctx.set_output(base)
            total={'banks':0,'wav_written':0,'other':0,'failed':[]}
            for i,bank in enumerate(banks):
                ctx.progress(i/len(banks),'Extracting '+bank.name)
                if ctx.cancel_event.is_set():break
                try:
                    r=datamine.extract_wave_bank(str(bank),base/bank.stem)
                    total['banks']+=1;total['wav_written']+=r['wav_written'];total['other']+=len(r['other'])
                except Exception as exc:
                    total['failed'].append(f'{bank.name}: {exc}')
            return total
        def done(t):
            msg=f"{t['banks']} bank(s) · {t['wav_written']} WAV files · {t['other']} other codec entries"
            if t['failed']:msg+='\nFailed: '+'; '.join(t['failed'][:5])
            self._notice('Audio banks extracted',msg,kind='warning' if t['failed'] else 'success',action=('Open folder',lambda:self._open_path(base)))
        self._run_async(task,done,f'Extracting {len(banks)} audio bank(s)…')

    def _open_message_browser(self):
        ui_extras.MessageBrowser(self.root,COLORS,jobs=lambda task,done,desc:self._run_async(task,done,desc),
                                 entity_db=str(self.db.path),notify=lambda t,m:self._notice(t,m,kind='success')).open()

    def _after_full_recovery(self,game_root):
        """Optional follow-ups chained after a successful Full Recovery."""
        if self.settings.get('recovery.track_client_versions',True):
            self._track_versions([str(game_root)])
        if self.settings.get('recovery.extract_protocol_after_recovery',True):
            self._protocol_extract(root=str(game_root))

    def _scans(self,parent):
        self._heading(parent,'Analyze and extract','Configure locations, then run analysis and catalog extraction concurrently. Existing extraction engine and checkpoints are retained.')
        paths=ttk.Frame(parent);paths.pack(fill='x',pady=6)
        self.path_vars=[];self.path_checks=[]
        for idx,value in enumerate(GAME_PATHS):
            line=ttk.Frame(paths);line.pack(fill='x',pady=4)
            enabled=tk.BooleanVar(value=True);entry=tk.StringVar(value=value)
            ttk.Checkbutton(line,variable=enabled).pack(side='left',padx=(0,9))
            ttk.Entry(line,textvariable=entry).pack(side='left',fill='x',expand=True)
            ttk.Button(line,text='Browse',command=lambda x=entry:self._browse_dir(x)).pack(side='left',padx=(6,0))
            self.path_vars.append(entry);self.path_checks.append(enabled)
        options=ttk.Frame(parent);options.pack(fill='x',pady=(13,8))
        self.no_images=tk.BooleanVar(value=False)
        self.broad=tk.BooleanVar(value=False)
        ttk.Checkbutton(options,text='Skip image export (faster)',variable=self.no_images).pack(side='left',padx=(0,20))
        ttk.Checkbutton(options,text='Expanded schema catalog',variable=self.broad).pack(side='left')
        cmds=ttk.Frame(parent);cmds.pack(fill='x',pady=8)
        self.scan_start=ttk.Button(cmds,text='Start all selected scans',style='Accent.TButton',command=self.start_scan)
        self.scan_start.pack(side='left')
        self.scan_stop=ttk.Button(cmds,text='Stop safely',state='disabled',command=self.stop_scan)
        self.scan_stop.pack(side='left',padx=8)
        ttk.Button(cmds,text='Open reports folder',command=lambda:self._open_path(home()/'Reports')).pack(side='left',padx=8)
        self.scan_table=self._table(parent,('target','job','status','stage','detail'),height=13)
        self.scan_table.pack(fill='both',expand=True,pady=12)
        self.scan_table.heading('target',text='Target');self.scan_table.column('target',width=90)
        self.scan_table.heading('job',text='Job');self.scan_table.column('job',width=100)
        self.scan_table.heading('status',text='Status');self.scan_table.column('status',width=105)
        self.scan_table.heading('stage',text='Stage');self.scan_table.column('stage',width=250)
        self.scan_table.heading('detail',text='Details');self.scan_table.column('detail',width=380)

    def _full_recovery_page(self,parent):
        self._heading(parent,'Full Client Recovery — one-button scan',
            'Read your installed WoSB game, decode supported XNB models/textures, '
            'preserve original content and decompressed payloads, index managed IL, '
            'build catalog tables and generate a resumable evidence report.')
        line=ttk.Frame(parent);line.pack(fill='x',pady=7)
        ttk.Label(line,text='Game folder:').pack(side='left',padx=(0,8))
        self.full_game_var=tk.StringVar(value=GAME_PATHS[0])
        ttk.Entry(line,textvariable=self.full_game_var).pack(side='left',fill='x',expand=True)
        ttk.Button(line,text='Browse',command=lambda:self._browse_dir(self.full_game_var)).pack(side='left',padx=8)
        self.full_preserve=tk.BooleanVar(value=True)
        self.full_payloads=tk.BooleanVar(value=True)
        self.full_code=tk.BooleanVar(value=True)
        self.full_catalog=tk.BooleanVar(value=True)
        self.full_force=tk.BooleanVar(value=False)
        options=ttk.Frame(parent);options.pack(fill='x',pady=7)
        for name,var in [('Retain original assets (disk-intensive)',self.full_preserve),
                         ('Save decompressed payloads',self.full_payloads),
                         ('Index all readable .NET IL',self.full_code),
                         ('Export complete client catalog',self.full_catalog),
                         ('Recheck unchanged XNB assets (slower)',self.full_force)]:
            ttk.Checkbutton(options,text=name,variable=var).pack(anchor='w',pady=2)
        actions=ttk.Frame(parent);actions.pack(fill='x',pady=10)
        self.full_start=ttk.Button(actions,text='Recover Everything',style='Accent.TButton',command=self._start_full_recovery)
        self.full_start.pack(side='left')
        ttk.Button(actions,text='Recover ALL installations',style='Accent.TButton',command=self._start_all_recovery).pack(side='left',padx=(8,0))
        self.full_stop=ttk.Button(actions,text='Stop at checkpoint',state='disabled',command=self._stop_full_recovery)
        self.full_stop.pack(side='left',padx=8)
        ttk.Button(actions,text='Open recovery folder',command=self._open_full_recovery).pack(side='left',padx=8)
        self.full_status_var=tk.StringVar(value='Ready. The scan reads game files only; no game process or DLL is executed.')
        ttk.Label(parent,textvariable=self.full_status_var,wraplength=1050).pack(anchor='w',pady=(12,5))
        self.full_progress=ttk.Progressbar(parent,orient='horizontal',mode='determinate',maximum=100)
        self.full_progress.pack(fill='x',pady=(0,12))
        ttk.Label(parent,text='Recovery reports distinguish decoded, indexed, unsupported, and failed assets. '
           'An indexed client method is not a verified server-side damage formula.',
           wraplength=1000,style='Muted.TLabel').pack(anchor='w',pady=8)
        self.full_cancel=None;self.full_running=False;self.full_output=None

    def _start_full_recovery(self):
        if self.running or self.full_running:
            return self._notice('Scan already active','Finish or stop the current scan before starting Full Recovery.')
        from hashlib import sha256
        engine_path=str(bundled_path('engine'))
        if engine_path not in sys.path:sys.path.insert(0,engine_path)
        from full_recovery import Recovery
        from extract_wosb import locate_game
        try:
            game=locate_game(self.full_game_var.get().strip())
        except Exception as exc:
            return self._notice('Cannot locate game assets',str(exc))
        fingerprint=sha256(str(game).casefold().encode('utf-8')).hexdigest()[:10]
        self._full_recovery_root=game
        self.full_output=home()/'FullRecovery'/fingerprint
        self.full_cancel=threading.Event();self.full_running=True
        self.full_start.configure(state='disabled');self.full_stop.configure(state='normal')
        self.full_status_var.set('Scanning '+str(game)+' — output: '+str(self.full_output))
        # Tk variables are not thread-safe: read every option on the main thread.
        options=dict(preserve=self.full_preserve.get(),payloads=self.full_payloads.get(),
                     code=self.full_code.get(),catalog=self.full_catalog.get(),force=self.full_force.get())
        output=self.full_output;cancel=self.full_cancel
        def task():
            try:
                # All output is external to the read-only game directory.
                report=Recovery(game,output,cancel=cancel,**options).run()
                self.status_events.put(('full-finished',report.get('result','unknown')))
            except Exception as exc:
                self.status_events.put(('full-error',str(exc)))
        threading.Thread(target=task,daemon=True).start()


    def _start_all_recovery(self):
        """One click: scan known installs, compare builds and export review-only ZIPs."""
        if self.running or self.full_running:
            return self._notice('Scan already active','Finish the current scan before starting another.')
        engine_path=str(bundled_path('engine'))
        if engine_path not in sys.path:sys.path.insert(0,engine_path)
        from recover_everything import run_all,discover
        configured=[self.full_game_var.get().strip()]+[r for r in self.settings.game_roots() if r!=self.full_game_var.get().strip()]
        candidates=discover(configured)
        if not candidates:
            return self._notice('No installed clients found','Choose a game folder or check the installation paths.')
        self.full_output=home()/'FullRecovery-AllClients'
        self.full_cancel=threading.Event();self.full_running=True
        self.full_start.configure(state='disabled');self.full_stop.configure(state='normal')
        self.full_status_var.set('Recovering '+str(len(candidates))+' client installation(s) and preparing small review ZIPs…')
        # Read Tk variables here on the main thread, not in the worker.
        sources=configured
        options=dict(recheck=self.full_force.get(),preserve=self.full_preserve.get(),
                     payloads=self.full_payloads.get(),code=self.full_code.get(),
                     catalog=self.full_catalog.get())
        output=self.full_output;cancel=self.full_cancel
        def task():
            try:
                summary=run_all(output,sources=sources,cancel=cancel,**options)
                self.status_events.put(('full-finished',str(summary['completed'])+' client(s) completed; '+
                    str(summary['failed'])+' failed · review-only ZIPs in FullRecovery-AllClients'))
            except Exception as exc:self.status_events.put(('full-error',str(exc)))
        threading.Thread(target=task,daemon=True).start()

    def _stop_full_recovery(self):
        if self.full_cancel:
            self.full_cancel.set()
            self.full_status_var.set('Stop requested; finishing current asset or assembly checkpoint…')

    def _open_full_recovery(self):
        target=self.full_output or home()/'FullRecovery'
        target.mkdir(parents=True,exist_ok=True)
        self._open_path(target)

    def _poll_full_recovery(self):
        if not getattr(self,'full_running',False) or not self.full_output:return
        status=self.full_output/'Recovery-Status.json'
        if not status.exists() and (self.full_output/'Combined-Recovery-Status.json').exists():
            try:
                summary=json.loads((self.full_output/'Combined-Recovery-Status.json').read_text(encoding='utf-8'))
                self.full_status_var.set('Clients completed: '+str(summary.get('completed',0))+'; needing attention: '+str(summary.get('failed',0)))
            except (OSError,ValueError):pass
            return
        if not status.exists():return
        try:
            record=json.loads(status.read_text(encoding='utf-8'))
        except (OSError,ValueError):return
        p=record.get('progress',{});done=p.get('done',0);total=p.get('total',0)
        self.full_progress.configure(value=(100*done/total) if total else 0)
        self.full_status_var.set(f"{p.get('phase','working')}: {done:,}/{total:,} — {p.get('current','')} · "
            f"phases: "+', '.join(k+':'+v.get('status','') for k,v in record.get('phases',{}).items()))

    def _table(self,parent,cols,height=16):
        tree=ttk.Treeview(parent,columns=cols,show='headings',height=height,selectmode='browse')
        for c in cols:tree.heading(c,text=c.title());tree.column(c,width=170)
        return tree

    def _catalog(self,parent):
        self._heading(parent,'Game data catalog','Search imported ships, cannons, ammunition, recipes, resources, ports, skills, and other original client records.')
        controls=ttk.Frame(parent);controls.pack(fill='x',pady=(0,9))
        ttk.Label(controls,text='Dataset').pack(side='left',padx=(0,8))
        self.category=tk.StringVar(value='All')
        self.category_select=ttk.Combobox(controls,state='readonly',textvariable=self.category,width=27)
        self.category_select.pack(side='left',padx=(0,14));self.category_select.bind('<<ComboboxSelected>>',lambda _e:self.refresh_records())
        self.record_search=tk.StringVar()
        search=ttk.Entry(controls,textvariable=self.record_search)
        search.pack(side='left',expand=True,fill='x');search.bind('<KeyRelease>',lambda _e:self._schedule(self.refresh_records))
        pane=ttk.PanedWindow(parent,orient='horizontal');pane.pack(fill='both',expand=True)
        left=ttk.Frame(pane);right=ttk.Frame(pane);pane.add(left,weight=3);pane.add(right,weight=4)
        self.record_table=self._table(left,('name','dataset','source'),height=18)
        self.record_table.column('name',width=230);self.record_table.column('dataset',width=140);self.record_table.column('source',width=75)
        self.record_table.pack(fill='both',expand=True)
        self.record_table.bind('<<TreeviewSelect>>',self._show_record)
        self.record_info=ttk.Label(right,text='Select a record',style='Muted.TLabel',wraplength=500)
        self.record_info.pack(anchor='w',padx=12,pady=8)
        self.record_text=self._text(right);self.record_text.pack(fill='both',expand=True,padx=12,pady=8)
        ttk.Button(right,text='Create wiki article from selected record',command=self._record_article).pack(anchor='e',padx=12,pady=8)

    def _wiki(self,parent):
        self._heading(parent,'Wiki editor','Curate your knowledge without changing the underlying extracted data. Gamepedia entries are seeded from your client reports.')
        tools=ttk.Frame(parent);tools.pack(fill='x',pady=(0,8))
        ttk.Button(tools,text='+ New article',style='Accent.TButton',command=self._new_article).pack(side='left')
        ttk.Button(tools,text='Save changes',command=self._save_article).pack(side='left',padx=7)
        ttk.Button(tools,text='Export wiki HTML',command=self._export_wiki).pack(side='left',padx=7)
        self.preview_button=ttk.Button(tools,text='Preview',command=self._toggle_preview);self.preview_button.pack(side='left',padx=7)
        ttk.Button(tools,text='History…',command=self._article_history).pack(side='left',padx=7)
        ttk.Button(tools,text='Open in web Codex',command=self._article_in_codex).pack(side='left',padx=7)
        self.article_search=tk.StringVar()
        box=ttk.Entry(tools,textvariable=self.article_search)
        box.pack(side='right',fill='x',expand=True,padx=(20,0))
        box.bind('<KeyRelease>',lambda _e:self._schedule(self.refresh_articles))
        panes=ttk.PanedWindow(parent,orient='horizontal');panes.pack(fill='both',expand=True)
        listframe=ttk.Frame(panes);editor=ttk.Frame(panes)
        panes.add(listframe,weight=2);panes.add(editor,weight=5)
        self.article_table=self._table(listframe,('article','section','status'),height=17)
        self.article_table.column('article',width=210);self.article_table.column('section',width=130);self.article_table.column('status',width=90)
        self.article_table.pack(fill='both',expand=True)
        self.article_table.bind('<<TreeviewSelect>>',self._show_article)
        fields=ttk.Frame(editor);fields.pack(fill='x',padx=10)
        ttk.Label(fields,text='Title').grid(row=0,column=0,sticky='w')
        self.article_title=tk.StringVar();ttk.Entry(fields,textvariable=self.article_title).grid(row=0,column=1,columnspan=3,sticky='ew',padx=6,pady=4)
        ttk.Label(fields,text='Section').grid(row=1,column=0,sticky='w')
        self.article_section=tk.StringVar();ttk.Entry(fields,textvariable=self.article_section).grid(row=1,column=1,sticky='ew',padx=6,pady=4)
        ttk.Label(fields,text='Review').grid(row=1,column=2,sticky='w')
        self.article_review=tk.StringVar(value='draft')
        ttk.Combobox(fields,textvariable=self.article_review,state='readonly',values=['draft','source-only','needs-review','reviewed','verified'],width=16).grid(row=1,column=3,sticky='ew',padx=6)
        fields.columnconfigure(1,weight=1);fields.columnconfigure(3,weight=1)
        self.article_source=ttk.Label(editor,text='Source: ',style='Muted.TLabel',wraplength=650)
        self.article_source.pack(anchor='w',padx=12,pady=(5,0))
        self.article_body=self._text(editor);self.article_body.pack(fill='both',expand=True,padx=12,pady=10)
        self.article_preview=self._text(editor);self._previewing=False
        ttk.Label(editor,text='Markdown: # headings, **bold**, `code`, [[Wiki link]], [text](url), tables, - [ ] tasks, “Tags: a, b”. '
                  'Ctrl+S saves · drafts autosave every few seconds · every save keeps a revision.',style='Muted.TLabel',wraplength=760).pack(anchor='w',padx=12)

    def _discovery(self,parent):
        self._heading(parent,'Game Data Discovery Center',
            'Find gaps across all mechanics, compare client versions, and turn diagnostic evidence into research tasks.')
        controls=ttk.Frame(parent);controls.pack(fill='x',pady=(0,12))
        ttk.Button(controls,text='Audit report ZIP / folder',style='Accent.TButton',
                   command=self._audit_reports_dialog).pack(side='left')
        ttk.Button(controls,text='Audit my saved scans',command=self._audit_saved_scans).pack(side='left',padx=(8,0))
        ttk.Button(controls,text='Audit local catalog',command=self._audit_local).pack(side='left',padx=(8,0))
        ttk.Button(controls,text='Inspect compiled shaders',command=self._shader_audit_dialog).pack(side='left',padx=(8,0))
        ttk.Button(controls,text='Export findings JSON',command=self._export_discovery).pack(side='left',padx=(8,0))
        ttk.Button(controls,text='Export mechanics graph',command=self._export_relations).pack(side='left',padx=(8,0))
        ttk.Button(controls,text='Refresh',command=self.refresh_discovery).pack(side='right')
        summary=ttk.Frame(parent);summary.pack(fill='x',pady=(0,12))
        self.audit_summary=tk.StringVar(value='No audit run yet. Import or audit your v3 reports.')
        ttk.Label(summary,textvariable=self.audit_summary,style='Section.TLabel').pack(anchor='w')
        ttk.Label(summary,text='Counts refer to observed data and attempted decodes, not total game completeness.',
                  style='Muted.TLabel').pack(anchor='w',pady=(3,0))
        filtering=ttk.Frame(parent);filtering.pack(fill='x',pady=(0,8))
        ttk.Label(filtering,text='Search findings').pack(side='left',padx=(0,8))
        self.discovery_search=tk.StringVar()
        discover_entry=ttk.Entry(filtering,textvariable=self.discovery_search)
        discover_entry.pack(side='left',fill='x',expand=True)
        discover_entry.bind('<KeyRelease>',lambda _e:self._schedule(self.refresh_discovery))
        self.audit_show_reviewed=tk.BooleanVar(value=False)
        ttk.Checkbutton(filtering,text='Show reviewed',variable=self.audit_show_reviewed,
                        command=self.refresh_discovery).pack(side='left',padx=(12,0))
        panes=ttk.PanedWindow(parent,orient='horizontal');panes.pack(fill='both',expand=True)
        left=ttk.Frame(panes);right=ttk.Frame(panes);panes.add(left,weight=3);panes.add(right,weight=4)
        self.audit_table=self._table(left,('priority','finding','affected'),height=17)
        self.audit_table.column('priority',width=76,stretch=False)
        self.audit_table.column('finding',width=330)
        self.audit_table.column('affected',width=95,stretch=False)
        self.audit_table.pack(fill='both',expand=True)
        self.audit_table.bind('<<TreeviewSelect>>',self._show_finding)
        self.audit_detail=self._text(right)
        self.audit_detail.pack(fill='both',expand=True,padx=(12,0),pady=(0,10))
        actions=ttk.Frame(right);actions.pack(anchor='e')
        ttk.Button(actions,text='Create wiki research task',style='Accent.TButton',
                   command=self._finding_article).pack(side='left',padx=5)
        ttk.Button(actions,text='Mark reviewed / reopen',command=self._toggle_finding).pack(side='left',padx=5)
        self.selected_finding=None

    def _shader_audit_dialog(self):
        root=self._pick_install('Install for read-only shader inspection')
        if not root:return
        output=home()/'Research'/'ShaderAudit'
        def worker():
            return audit_effects(root,output,export_compiled=True)
        def done(result):
            filename,report=result
            self._notice('Compiled-effect audit',
                f"Inspected {report['files_considered']} shader candidates; saved {filename}.\n"
                'Saved compiled effects for local research. Original HLSL techniques and accurate rendering are not yet reconstructed.')
        self._run_async(worker,done,'Extracting and inspecting compiled client effects…')

    def _audit_reports_dialog(self):
        options=[]
        reports=home()/'Reports'
        if reports.is_dir():options.append(('Saved scans (Reports folder)',str(reports),str(reports)))
        for z in sorted(home().glob('*Report*.zip'),key=lambda p:p.stat().st_mtime,reverse=True)[:20]:
            options.append((z.name,str(z),'report ZIP'))
        if len(options)==1:return self._audit_reports_path(options[0][1])
        path=self._pick_files('Reports to audit',options,filetypes=[('WoSB reports ZIP','*.zip')])
        if path:self._audit_reports_path(path)

    def _audit_saved_scans(self):
        folder=home()/'Reports'
        if not folder.is_dir():return self._notice('No saved scans','No saved Reports folder found at '+str(folder))
        self._audit_reports_path(str(folder))

    def _audit_reports_path(self,path):
        def worker():
            db=CatalogDB(self.db.path)
            try:
                result=scan_reports(path);save_audit(db,result)
                return len(result['findings']),result['roots']
            finally:db.close()
        self._run_async(worker,lambda result:(self.refresh_discovery(),self._notice('Audit complete',
            f'{result[0]} findings across {", ".join(result[1])}. Findings are saved in your wiki database.')),
            'Auditing report contents (read-only)…')

    def _audit_local(self):
        def worker():
            db=CatalogDB(self.db.path)
            try:
                result=audit_catalog(db);save_audit(db,result)
                return len(result['findings'])
            finally:db.close()
        self._run_async(worker,lambda count:(self.refresh_discovery(),self._notice('Catalog audit',
            f'{count} research findings saved. Source-table absence is not proof a mechanic is absent.')),
            'Auditing catalog references and coverage…')

    def refresh_discovery(self):
        if not hasattr(self,'audit_table'):return
        for item in self.audit_table.get_children():self.audit_table.delete(item)
        rows=list_findings(self.db,self.discovery_search.get().strip(),self.audit_show_reviewed.get())
        for row in rows:
            self.audit_table.insert('','end',iid=row['key'],values=(row['severity'].upper(),row['title'],
                                    f'{row["count"]:,}' if row['count'] else '—'))
        counts=self.db.conn.execute("SELECT severity,count(*) n FROM discovery_findings WHERE status='open' GROUP BY severity").fetchall()
        total=sum(r['n'] for r in counts)
        parts=[f'{r["n"]} {r["severity"]}' for r in counts]
        self.audit_summary.set(f'{total} open investigations'+('  ·  '+', '.join(parts) if parts else ' · run an audit to get started'))

    def _show_finding(self,_event=None):
        sel=self.audit_table.selection()
        if not sel:return
        row=self.db.conn.execute('SELECT * FROM discovery_findings WHERE key=?',(sel[0],)).fetchone()
        if row is None:return
        self.selected_finding=row['key']
        examples='\n'.join(str(x) for x in json.loads(row['sample_json']))
        details=(f'{row["title"]}\n\nPriority: {row["severity"].upper()}\n'
                 f'Category: {row["category"]}\nAffected: {row["count"]:,}\n'
                 f'Status: {row["status"]}\n\n{row["description"]}\n\n'
                 f'NEXT STEP\n{row["action"]}\n\nEVIDENCE\n{row["evidence"]}\n\n'
                 f'EXAMPLES\n{examples}')
        self.audit_detail.delete('1.0','end')
        self.audit_detail.insert('1.0',details)

    def _finding_article(self):
        if not self.selected_finding:
            return self._notice('Discovery','Select an issue first.')
        row=self.db.conn.execute('SELECT * FROM discovery_findings WHERE key=?',(self.selected_finding,)).fetchone()
        items='\n'.join('- `'+str(x).replace('`','')+'`' for x in json.loads(row['sample_json']))
        body=(f'# {row["title"]}\n\n**Open research question — NOT verified gameplay behavior.**\n\n'
              f'## Why flagged\n\n{row["description"]}\n\n'
              f'## Investigation plan\n\n{row["action"]}\n\n'
              f'## Source evidence\n\n`{row["evidence"].replace(chr(96), "")}`\n\n'
              f'## Example unresolved files or IDs\n\n{items}\n')
        aid=self.db.upsert_article('discovery-'+row['key'],row['title'],'Research backlog',body,
            'discovery-audit',row['evidence'],'needs-review',preserve_edited=True)
        self.db.conn.commit()
        self.refresh_all()
        self.tabs.select_named('Wiki editor')
        self._select_article(aid)

    def _toggle_finding(self):
        if not self.selected_finding:return
        row=self.db.conn.execute('SELECT status FROM discovery_findings WHERE key=?',(self.selected_finding,)).fetchone()
        if not row:return
        next_status='reviewed' if row['status']=='open' else 'open'
        self.db.conn.execute('UPDATE discovery_findings SET status=? WHERE key=?',(next_status,self.selected_finding))
        self.db.conn.commit();self.refresh_discovery()

    def _export_discovery(self):
        path=filedialog.asksaveasfilename(defaultextension='.json',filetypes=[('JSON','*.json')])
        if path:
            try:self._notice('Findings exported',str(export_findings(self.db,path)))
            except Exception as e:self._error('Discovery export',e)

    def _export_relations(self):
        path=filedialog.asksaveasfilename(defaultextension='.json',filetypes=[('JSON','*.json')])
        if path:
            try:self._notice('Mechanics graph exported',str(export_relationships(self.db,path)))
            except Exception as e:self._error('Graph export',e)

    def _combat(self,parent):
        self._heading(parent,'Combat evidence explorer','Method candidates and IL signals are research leads, not automatically verified damage or fire formulas.')
        filterbox=ttk.Frame(parent);filterbox.pack(fill='x',pady=(0,9))
        ttk.Label(filterbox,text='Find method, effect, or topic').pack(side='left',padx=(0,9))
        self.combat_search=tk.StringVar(value='fire')
        ttk.Entry(filterbox,textvariable=self.combat_search).pack(side='left',fill='x',expand=True)
        ttk.Button(filterbox,text='Search',command=self.refresh_combat).pack(side='left',padx=6)
        panes=ttk.PanedWindow(parent,orient='horizontal');panes.pack(fill='both',expand=True)
        a=ttk.Frame(panes);b=ttk.Frame(panes);panes.add(a,weight=3);panes.add(b,weight=4)
        self.combat_table=self._table(a,('method','topics','source'),height=16)
        self.combat_table.column('method',width=320);self.combat_table.column('topics',width=130);self.combat_table.column('source',width=80)
        self.combat_table.pack(fill='both',expand=True);self.combat_table.bind('<<TreeviewSelect>>',self._show_combat)
        self.combat_info=ttk.Label(b,text='All findings require source verification.',style='Muted.TLabel',wraplength=500)
        self.combat_info.pack(anchor='w',padx=12,pady=8)
        self.combat_text=self._text(b);self.combat_text.pack(fill='both',expand=True,padx=12,pady=8)
        ttk.Button(b,text='Create research page from method',command=self._combat_article).pack(anchor='e',padx=12)

    def _sailing(self,parent):
        self._heading(parent,'Sailing and wind laboratory','A reproducible wind-rose code component from Common.dll. NOT the complete sailing-speed formula or server-verified knots.')
        controls=ttk.Frame(parent);controls.pack(fill='x',pady=(4,10))
        self.wind_angle=tk.DoubleVar(value=45)
        ttk.Label(controls,text='Relative wind angle').pack(side='left',padx=(0,10))
        ttk.Scale(controls,from_=0,to=360,variable=self.wind_angle,orient='horizontal',command=lambda _v:self._draw_wind()).pack(side='left',fill='x',expand=True)
        self.wind_value=tk.StringVar()
        ttk.Label(controls,textvariable=self.wind_value,font=('Consolas',12)).pack(side='left',padx=14)
        ttk.Button(controls,text='Open wind research wiki',command=lambda:self._open_research('research-sailing-wind-physics')).pack(side='left')
        lower=ttk.PanedWindow(parent,orient='horizontal');lower.pack(fill='both',expand=True)
        polar=ttk.Frame(lower);data=ttk.Frame(lower);lower.add(polar,weight=3);lower.add(data,weight=2)
        self.wind_canvas=tk.Canvas(polar,bg=PANEL,highlightthickness=0,height=490)
        self.wind_canvas.pack(fill='both',expand=True,padx=(0,10),pady=8)
        self.wind_canvas.bind('<Configure>',lambda _e:self._draw_wind())
        ttk.Label(data,text='Recovered wind-rose table',style='Section.TLabel').pack(anchor='w',pady=8)
        self.wind_text=self._text(data);self.wind_text.pack(fill='both',expand=True,pady=(0,12))
        self.wind_text.insert('1.0','Import v3.1 reports to compare regular and unique wind-rose values.\n')
        self.wind_text.configure(state='disabled')
        self.root.after(300,self._refresh_sailing)

    def _refresh_sailing(self):
        if not hasattr(self,'wind_text'):return
        self.wind_text.configure(state='normal');self.wind_text.delete('1.0','end')
        rows=rose_records(self.db)
        if rows:
            for row in rows:
                self.wind_text.insert('end',json.dumps(row,ensure_ascii=False,indent=2)+'\n\n')
        else:self.wind_text.insert('end','No WindRoses records yet. Import the reports ZIP.\n')
        self.wind_text.insert('end','\nSource methods:\nCommon.dll 0x060027B4, 0x060027B5, 0x060027B6, 0x06002764\n\n')
        self.wind_text.insert('end','This curve is a dimensionless code component. Do not apply it directly to ship base speed.\n')
        self.wind_text.configure(state='disabled')
        self._draw_wind()

    def _draw_wind(self):
        if not hasattr(self,'wind_canvas'):return
        c=self.wind_canvas;w=max(300,c.winfo_width());h=max(300,c.winfo_height());c.delete('all')
        mid=(w/2,h/2);r=min(w,h)*0.4
        for fraction in (.25,.5,.75,1):
            z=r*fraction;c.create_oval(mid[0]-z,mid[1]-z,mid[0]+z,mid[1]+z,outline='#37526b')
        c.create_line(mid[0]-r,mid[1],mid[0]+r,mid[1],fill='#45647f')
        c.create_line(mid[0],mid[1]-r,mid[0],mid[1]+r,fill='#45647f')
        for angle,text in [(0,'0°'),(90,'90°'),(180,'180°'),(270,'270°')]:
            theta=math.radians(angle)
            c.create_text(mid[0]+(r+22)*math.cos(theta),mid[1]-(r+18)*math.sin(theta),text=text,fill=MUTED)
        curve=[]
        for angle in range(0,361,2):
            radius=r*(wind_speed_component(angle)/1.8)
            theta=math.radians(angle)
            curve.extend((mid[0]+radius*math.cos(theta),mid[1]-radius*math.sin(theta)))
        if len(curve)>3:c.create_line(*curve,fill=ACCENT,width=3,smooth=True)
        angle=self.wind_angle.get()
        factor=wind_speed_component(angle);wdot=winding_dot_at_angle(angle)
        theta=math.radians(angle);q=r*(factor/1.8)
        c.create_oval(mid[0]+q*math.cos(theta)-6,mid[1]-q*math.sin(theta)-6,
                      mid[0]+q*math.cos(theta)+6,mid[1]-q*math.sin(theta)+6,fill=WARN,outline='')
        c.create_text(mid[0],h-18,text='Client WindRose component only · not final ship speed',fill=MUTED)
        self.wind_value.set(f'{angle:.0f}°  |  dot {wdot:.3f}  |  component {factor:.3f}')

    def _ship_3d(self,parent):
        ttk.Button(parent,text='Compare with actual in-game screenshot',
                   command=self._compare_ship_screenshots).pack(anchor='e',padx=5,pady=(4,5))
        self._heading(parent,'Ship 3D — Appearance & Damage Lab','Recover ship geometry with material IDs, locate installed textures, select real ship designs and analyze measured cannon hits.')
        self.ship_choice=tk.StringVar(value='Select a ship')
        row=ttk.Frame(parent);row.pack(fill='x',pady=7)
        ttk.Label(row,text='Game build').pack(side='left',padx=(0,8))
        self.ship_build_choice=tk.StringVar(value='Game')
        self.ship_build_box=ttk.Combobox(row,textvariable=self.ship_build_choice,state='readonly',width=12)
        self.ship_build_box.pack(side='left',padx=(0,18))
        self.ship_build_box.bind('<<ComboboxSelected>>',lambda _e:self._refresh_viewer_sources())
        ttk.Label(row,text='Ship').pack(side='left',padx=(0,12))
        self.ship_select=ttk.Combobox(row,textvariable=self.ship_choice,state='readonly',width=60)
        self.ship_select.pack(side='left',fill='x',expand=True)
        self.ship_select.bind('<<ComboboxSelected>>',self._ship_selected)
        self.ship_models=[]
        from appearance_lab import detect_local_asset_root
        self.mesh_var=tk.StringVar();self.zones_var=tk.StringVar();self.texture_var=tk.StringVar();self.asset_root_var=tk.StringVar(value=detect_local_asset_root() or '');self.trials_csv_var=tk.StringVar()
        for label,variable,filter_spec in [
            ('OBJ model (optional)',self.mesh_var,[('Wavefront OBJ','*.obj')]),
            ('Hitbox zones JSON (optional)',self.zones_var,[('Zone annotations','*.json')]),
            ('Local texture image / XNB (optional)',self.texture_var,[('Textures','*.png *.jpg *.jpeg *.webp *.xnb')])]:
            line=ttk.Frame(parent);line.pack(fill='x',pady=7)
            ttk.Label(line,text=label,width=29).pack(side='left')
            ttk.Entry(line,textvariable=variable).pack(side='left',fill='x',expand=True)
            ttk.Button(line,text='Browse',command=lambda v=variable,f=filter_spec:self._browse_viewer_file(v,f)).pack(side='left',padx=8)
        line=ttk.Frame(parent);line.pack(fill='x',pady=7)
        ttk.Label(line,text='Game Data or research ZIP parts folder',width=29).pack(side='left')
        ttk.Entry(line,textvariable=self.asset_root_var).pack(side='left',fill='x',expand=True)
        ttk.Button(line,text='Browse',command=lambda:self.asset_root_var.set(filedialog.askdirectory(title='WoSB installed game Data / WOSB-Upload-Parts directory') or self.asset_root_var.get())).pack(side='left',padx=8)
        line=ttk.Frame(parent);line.pack(fill='x',pady=7)
        ttk.Label(line,text='Measured combat shots CSV (optional)',width=29).pack(side='left')
        ttk.Entry(line,textvariable=self.trials_csv_var).pack(side='left',fill='x',expand=True)
        ttk.Button(line,text='Browse',command=lambda:self._browse_viewer_file(self.trials_csv_var,[('CSV files','*.csv')])).pack(side='left',padx=8)
        buttons=ttk.Frame(parent);buttons.pack(anchor='w',pady=(17,10))
        ttk.Button(buttons,text='Open visualizer + damage lab',style='Accent.TButton',command=self._launch_ship_viewer).pack(side='left')
        ttk.Button(buttons,text='Save OBJ for this ship',command=self._save_ship_mesh).pack(side='left',padx=8)
        ttk.Button(buttons,text='Export textured GLB',command=self._export_ship_glb).pack(side='left',padx=8)
        ttk.Button(buttons,text='Blank hitbox template',command=self._save_zones_template).pack(side='left',padx=8)
        ttk.Button(buttons,text='Export XNB samples',command=self._export_model_samples).pack(side='left',padx=8)
        ttk.Button(buttons,text='Inspect XNB / sample ZIP',command=self._inspect_xnb).pack(side='left',padx=8)
        ttk.Button(buttons,text='Recover XNB → OBJ',style='Accent.TButton',command=self._recover_ship_xnb).pack(side='left',padx=8)

        secondary=ttk.Frame(parent);secondary.pack(anchor='w',pady=(0,10))
        ttk.Button(secondary,text='Link selected XNB candidate to ship',command=self._link_selected_xnb).pack(side='left',padx=(0,8))
        ttk.Button(secondary,text='Create model research wiki page',command=self._create_model_wiki).pack(side='left')
        ttk.Button(secondary,text='Open hitbox research wiki',command=lambda:self._open_research('research-ship-model-hitboxes')).pack(side='left',padx=8)
        self.viewer_info=tk.StringVar(value='Choose a ship and recover its matching local XNB, or import an OBJ. Damage overlays require actual sourced hitbox rules.')
        ttk.Label(parent,textvariable=self.viewer_info,style='Muted.TLabel',wraplength=1040).pack(anchor='w',pady=10)
        ttk.Label(parent,text='Client-model extraction diagnostics',style='Section.TLabel').pack(anchor='w',pady=(14,8))
        self.model_table=self._table(parent,('asset','decoding','source'),height=13)
        self.model_table.column('asset',width=450);self.model_table.column('decoding',width=300)
        self.model_table.pack(fill='both',expand=True)
        self.root.after(300,self._refresh_viewer_sources)

    def _refresh_viewer_sources(self):
        if not hasattr(self,'ship_select'):return
        source_roots={r[0] for r in self.db.conn.execute("SELECT DISTINCT source_root FROM records WHERE dataset='ShipsToPlay'")}
        choices=sorted(source_roots,key=lambda x:(0 if x=='Game' else 1 if x=='Steam' else 2,x))
        self.ship_build_box['values']=choices
        requested=self.ship_build_choice.get()
        self.ship_build=requested if requested in choices else (choices[0] if choices else 'Imported')
        self.ship_build_choice.set(self.ship_build)
        self.ship_models=ship_catalog(self.db,build=self.ship_build)
        names=[f"{s.get('EnglishName',s.get('Name','Unknown'))} (ID {s.get('ID','?')})" for s in self.ship_models]
        prior=self.ship_choice.get();self.ship_select['values']=names
        if names and prior not in names:self.ship_select.current(0)
        for item in self.model_table.get_children():self.model_table.delete(item)
        rows=self.db.conn.execute('SELECT raw_json,source_root FROM records WHERE dataset=? AND source_root=? ORDER BY name LIMIT 1500',('ModelAssetCandidates',self.ship_build)).fetchall()
        self.model_candidate_rows=[]
        failures=0
        for i,r in enumerate(rows):
            data=json.loads(r['raw_json']);self.model_candidate_rows.append((data,r['source_root']))
            state=data.get('DecodeStatus') or ('Reader discovered' if data.get('ContentReaders') else 'Unclassified')
            if 'failed' in state.lower():failures+=1
            self.model_table.insert('','end',iid=str(i),values=(data.get('RelativePath',''),state,r['source_root']))
        self.viewer_info.set(f'{len(rows)} asset candidates shown ({failures} failed decoders). Asset paths are research leads, not decoded geometry or proven damage zones.')
        self._ship_selected()

    def _configured_game_roots(self):
        """Game folders the user has typed or browsed to, so model lookup is not
        limited to the default C:\\ install locations."""
        roots=[]
        for var in list(getattr(self,'path_vars',[]))+[getattr(self,'full_game_var',None),getattr(self,'asset_root_var',None)]:
            try:value=var.get().strip() if var is not None else ''
            except Exception:value=''
            if value and value not in roots and Path(value).is_dir():roots.append(value)
        return roots

    def _selected_ship(self):
        if not self.ship_models:return None
        idx=self.ship_select.current()
        if idx<0:return None
        return self.ship_models[idx]

    def _selected_candidates(self,ship):
        rows=self.db.conn.execute("SELECT raw_json FROM records WHERE dataset='ModelAssetCandidates' AND source_root=? LIMIT 1000",(self.ship_build,)).fetchall()
        expected=expected_model_for_ship(self.db,ship,self.ship_build)
        candidates=match_models(ship,[json.loads(row['raw_json']) for row in rows],
                                expected_model_name=expected['model_name'] if expected else None)
        linked=self.model_library.linked_candidate(ship,self.ship_build)
        if linked and not any(x['path']==linked['path'] for x in candidates):
            candidates.insert(0,{'path':linked['path'],'status':'manually linked candidate',
                                 'score':100,'assessment':'User-selected path; not verified geometry'})
        return candidates

    def _ship_selected(self,_event=None):
        ship=self._selected_ship()
        if not ship:return
        stored=self.model_library.lookup(ship,self.ship_build)
        candidates=self._selected_candidates(ship)
        if stored:
            self.mesh_var.set(stored['mesh_path']);self.zones_var.set(stored['zones_path'])
            self.viewer_info.set('Saved OBJ loaded for this ship ('+str(stored['vertices'])+' vertices). '
              'Model origin and damage-zone rules must still be verified. '+str(len(candidates))+' client asset filename candidates indexed.')
        else:
            self.mesh_var.set('');self.zones_var.set('')
            label='; '.join(Path(x['path'].replace('\\','/')).name for x in candidates[:3])
            expected=expected_model_for_ship(self.db,ship,self.ship_build)
            exact='Known model mapping: '+expected['model_name']+' (StaticInfoID → ShipsBasics). ' if expected else ''
            self.viewer_info.set(exact+(('Client asset filename candidates: '+label) if label else
               'No candidate XNB model has been linked to this ship. This is not proof no game model exists.'))
            self.viewer_info.set(self.viewer_info.get()+
              ' These are NOT decoded meshes. Import a verified OBJ once to save it for this ship.')

    def _save_ship_mesh(self):
        ship=self._selected_ship()
        if not ship:return self._notice('Ship 3D','Import a catalog and select a ship first.')
        source=self.mesh_var.get().strip()
        if not source:return self._notice('Ship 3D','Browse to an OBJ file before saving it in your library.')
        if not messagebox.askyesno('Associate model with ship',
            'Save the selected OBJ as a model for '+str(ship.get('EnglishName') or ship.get('Name'))+'?\n'
            'This saves a local copy, but does NOT verify that it was recovered from the client.',parent=self.root):return
        try:
            entry=self.model_library.import_obj(ship,self.ship_build,source,self.zones_var.get().strip() or None)
            self._ship_selected();self._status('Saved ship OBJ in the persistent user model library ('+str(entry['vertices'])+' vertices)')
        except Exception as exc:self._error('Import OBJ',exc)

    def _link_selected_xnb(self):
        ship=self._selected_ship()
        selected=self.model_table.selection()
        if not ship:return self._notice('Ship models','Select a ship first.')
        if not selected:return self._notice('Ship models','Select an XNB asset row first. You can use any candidate, even if its name differs.')
        try:
            row=self.model_candidate_rows[int(selected[0])]
            data,source=row
            candidate=str(data.get('RelativePath') or data.get('source') or '')
            if not messagebox.askyesno('Associate filename candidate',
                'Associate '+candidate+' with this ship as a research lead?\n'
                'This does not confirm that the mesh or hitbox belongs to the selected ship.',parent=self.root):return
            self.model_library.link_candidate(ship,self.ship_build,candidate,source)
            self._ship_selected()
        except (ValueError,IndexError) as exc:self._error('Link model candidate',exc)

    def _recover_ship_xnb(self,open_after=False,preferred=None):
        ship=self._selected_ship()
        if not ship:return self._notice('Ship model recovery','Import a game catalog and select a ship.')
        selected=self.model_table.selection()
        if preferred:
            relative=str(preferred['path']);source=self.ship_build
            located=locate_model_candidate(relative,source,self._configured_game_roots())
        elif selected:
            data,source=self.model_candidate_rows[int(selected[0])]
            relative=str(data.get('RelativePath') or data.get('source') or '')
            located=locate_model_candidate(relative,source,self._configured_game_roots())
        else:
            linked=self.model_library.linked_candidate(ship,self.ship_build)
            relative=linked['path'] if linked else ''
            located=locate_model_candidate(relative,self.ship_build,self._configured_game_roots()) if relative else None
        if not located:
            pick=filedialog.askopenfilename(title='Select an original XNB model or debug ZIP',
                filetypes=[('WoSB model or samples','*.xnb *.zip'),('XNB model','*.xnb'),('Debug ZIP','*.zip')])
            if not pick:return
            located=Path(pick)
            relative=str(located)
        message=('Recover the actual vertex and triangle buffers from this XNB?\n\n'
                 +str(located)+'\n\n'
                 'This associates the model with '+str(ship.get('EnglishName') or ship.get('Name'))+
                 ' for LOCAL browsing. The association is user-selected, not verified by the game.\n'
                 'The converter will NOT infer weak spots or ship damage multipliers.')
        if not messagebox.askyesno('Recover ship geometry',message,parent=self.root):return
        ship_copy=dict(ship);build=self.ship_build
        expected=expected_model_for_ship(self.db,ship,build)
        expected_name=expected['model_name'] if expected else None
        def worker():
            return recover_model_for_ship(ship_copy,build,located,
                ModelLibrary(root=self.model_library.root),source_label=relative,expected_model_name=expected_name)
        def done(result):
            self._ship_selected()
            self._status('Recovered '+str(result['triangles'])+' actual triangles; ready in Ship 3D.')
            self._notice('Mesh recovered',
                f"Recovered {result['vertices']:,} vertices and {result['triangles']:,} triangles.\n"
                f"Source evidence: {result['recovery_report']}\n\n"
                'Open 3D viewer to inspect. Materials and damage overlays remain unverified.')
            if open_after:self._launch_ship_viewer()
        self._run_async(worker,done,'Recovering actual XNB vertices and indices (read-only)…')

    def _inspect_xnb(self):
        source=filedialog.askopenfilename(title='Inspect a raw XNB model or debug sample ZIP',
            filetypes=[('XNB models or sample ZIP','*.xnb *.zip'),('XNB file','*.xnb'),('ZIP file','*.zip')])
        if not source:return
        def worker():
            from datetime import datetime
            import sys
            engine=str(bundled_path('engine'))
            if engine not in sys.path:sys.path.insert(0,engine)
            from xnb_model_probe import inspect_asset,inspect_sample_zip
            if Path(source).suffix.lower()=='.zip':result=inspect_sample_zip(source)
            else:result={'tool':'WoSB model analysis','samples':[inspect_asset(Path(source).read_bytes(),source)]}
            out=home()/'Reports'/'ModelProbes';out.mkdir(parents=True,exist_ok=True)
            dest=out/('XNB-Probe-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.json')
            dest.write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
            return result,str(dest)
        def done(value):
            result,dest=value
            summary=[]
            for item in result['samples']:
                m=item.get('model',{})
                summary.append(str(item.get('source','sample'))+' — '+
                    (str(m.get('bone_count',0))+' bones, '+str(m.get('mesh_count','?'))+' mesh records; '+
                     str(m.get('model_metadata_status','unknown'))+'; '+
                     str(m.get('geometry_status','not checked')) if not item.get('error') else str(item['error'])))
            self._notice('XNB inspection', '\n'.join(summary[:6])+'\n\nFull reader evidence saved at '+dest+
                '\nUse Recover XNB → OBJ to export supported geometry. Damage weak points are not inferred.')
        self._run_async(worker,done,'Inspecting XNB type readers and model hierarchy…')

    def _export_model_samples(self):
        ship=self._selected_ship()
        if not ship:return self._notice('Model samples','Select a ship first.')
        candidates=self._selected_candidates(ship)
        # Permit exporting a user-selected unassigned model: numeric asset IDs
        # often differ from gameplay ship IDs, and no filename match is proof.
        if not candidates and self.model_table.selection():
            selected=self.model_candidate_rows[int(self.model_table.selection()[0])]
            data,src=selected
            if src==self.ship_build:
                path=str(data.get('RelativePath') or data.get('source') or '')
                if path:candidates=[{'path':path,'score':0,'status':'manually selected sample'}]
        if not candidates:return self._notice('Model samples',
            'No name-matched candidate. Select any XNB row in the model asset table, then choose Export XNB samples.')
        want='steam' if self.ship_build!='Game' else 'game'
        root=(self.settings.get('installs.'+want) or '').strip()
        if not Path(root or '.').is_dir() or not root:
            suggested=GAME_PATHS[0] if self.ship_build=='Game' else GAME_PATHS[-1]
            root=suggested if Path(suggested).is_dir() else self._pick_install('Install the model came from')
        if not root:return
        save=filedialog.asksaveasfilename(title='Save optional original-XNB debug sample ZIP',
            defaultextension='.zip',initialfile='WoSB-Ship-Model-Debug-Samples.zip',
            filetypes=[('ZIP archive','*.zip')])
        if not save:return
        if not messagebox.askyesno('Review raw game assets before sharing',
          'This will place a few original game XNB files in an archive for decompression troubleshooting. '
          'These files may be copyrighted. Review the resulting archive and only share where permitted. Continue?',
          parent=self.root):return
        try:
            paths=[c['path'] for c in candidates]
            result=export_xnb_samples(root,paths,save)
            self._notice('Model samples',f"Saved {result['files']} XNB sample(s) to {save}. Review before sharing.")
        except Exception as exc:self._error('XNB sample export',exc)

    def _create_model_wiki(self):
        ship=self._selected_ship()
        if not ship:return self._notice('Wiki','Select a ship first.')
        title=str(ship.get('EnglishName') or ship.get('Name') or ship.get('ID'))
        candidates=self._selected_candidates(ship)
        body=['# '+title+' — model and hitbox research','',
          '**Status: candidate assets only; model geometry and hitbox vulnerability unverified.**','',
          '## Model filename candidates', '']
        body.extend('- `'+str(c['path'])+'` — '+str(c['status'])+' (score '+str(c['score'])+')' for c in candidates)
        if not candidates:body.append('_No candidate model paths indexed._')
        body.extend(['','## Validation needed','','1. Decode client XNB using verified LZX and content readers.',
          '2. Reconstruct mesh, materials, coordinate system and pivots.',
          '3. Decode associated external hitbox content and map coordinates.',
          '4. Verify actual damage modifiers against game-code conditions or controlled trials.',
          '', '## Evidence source', self.ship_build+' / ModelAssetCandidates'])
        slug='ship-model-'+slugify(self.ship_build+'-'+str(ship.get('ID') or title))
        aid=self.db.upsert_article(slug,title+' — model and hitboxes','Ships, hulls & construction',
           '\n'.join(body),'extracted-asset-index',self.ship_build+'/ModelAssetCandidates',
           'needs-review',preserve_edited=True)
        self.db.conn.commit();self.refresh_all();self.tabs.select_named('Wiki editor');self._select_article(aid)

    def _browse_viewer_file(self,var,spec):
        path=filedialog.askopenfilename(filetypes=spec+[('All files','*.*')])
        if path:var.set(path)

    def _launch_ship_viewer(self):
        if not self.ship_models:return self._notice('Ship 3D','Import the WoSB reports ZIP to populate the ship list.')
        ship=self._selected_ship()
        if not ship:return self._notice('Ship 3D','Select a ship first.')
        if not self.mesh_var.get().strip():
            candidates=self._selected_candidates(ship)
            expected=expected_model_for_ship(self.db,ship,self.ship_build)
            exact=[x for x in candidates if expected and Path(x['path'].replace('\\','/')).stem.casefold()==expected['model_name'].casefold()]
            if exact and locate_model_candidate(exact[0]['path'],self.ship_build,self._configured_game_roots()):
                return self._recover_ship_xnb(open_after=True,preferred=exact[0])
            return self._notice('No decoded ship mesh',
               'This ship has no saved OBJ yet. Use Recover XNB → OBJ to convert a compatible local model. '
               'You may also import a verified OBJ. '
               'The viewer will remember a saved model for this ship.')
        try:
            # Include build and ID: ships sharing a display name (or the same ship in
            # Game vs Steam builds) used to overwrite each other's viewer and wiki link.
            viewer_slug='ship-'+slugify('-'.join(str(x) for x in (ship.get('EnglishName') or ship.get('Name') or 'ship',
                                                                   self.ship_build,ship.get('ID','x'))))
            out=home()/'Viewers'/(viewer_slug+'.html')
            export_viewer(out,ship,self.mesh_var.get().strip() or None,self.zones_var.get().strip() or None,
                          template=bundled_path('viewer/ship_viewer.html'),
                          texture_path=self.texture_var.get().strip() or None,
                          ballistics=load_ballistics_catalog(self.db),
                          game_assets_root=self.asset_root_var.get().strip() or None,db=self.db,
                          observations_csv=self.trials_csv_var.get().strip() or None)
            self.db.register_ship_viewer(viewer_slug,
                 str(ship.get('EnglishName') or ship.get('Name') or 'Unknown ship'),
                 str(ship.get('ID','?')),self.ship_build,out,
                 'Mesh: '+(self.mesh_var.get() or 'none')+' | Zones: '+(self.zones_var.get() or 'none')+' | Texture: '+(self.texture_var.get() or 'none'))
            webbrowser.open(out.resolve().as_uri())
            self._status('Opened offline viewer; registered for future wiki HTML exports: '+str(out))
        except Exception as e:self._error('Ship 3D',e)

    def _export_ship_glb(self):
        ship=self._selected_ship()
        mesh_path=self.mesh_var.get().strip()
        if not ship:return self._notice('GLB export','Select a ship first.')
        if not mesh_path or not Path(mesh_path).is_file():
            return self._notice('GLB export','Recover the ship XNB to OBJ, or select a verified OBJ first.')
        output=filedialog.asksaveasfilename(defaultextension='.glb',
            initialfile=slugify(ship.get('EnglishName') or str(ship.get('ID')))+'.glb',
            filetypes=[('glTF binary model','*.glb')])
        if not output:return
        source_dir=self.asset_root_var.get().strip() or None
        ship_copy=dict(ship)
        def task():
            from ship_viewer import read_obj
            from appearance_lab import prepare_appearance
            from gltf_export import export_glb
            mesh=read_obj(mesh_path)
            sidecar=Path(output).parent/(Path(output).stem+'-assets') if source_dir else None
            appearance=prepare_appearance(ship_copy,mesh,game_assets_root=source_dir,db=None,
                                          texture_output_dir=sidecar)
            return export_glb(mesh,appearance,output,asset_dir=Path(output).parent)
        def done(report):
            self._status('GLB saved: '+report['path'])
            self._notice('Textured GLB exported',
                'Visual triangles: '+str(report['visual_triangles'])+'\n'+
                'Original material IDs: '+str(report['materials'])+'\n'+
                'Embedded original textures: '+str(report['embedded_textures'])+'\n'+
                'Unmatched material labels: '+str(len(report['missing_texture_materials']))+'\n\n'+
                'Game custom shaders, animation and damage hitboxes are not verified. '+
                ('The source OBJ was sampled for display.' if report['sampled'] else 'Complete display mesh exported.'))
        self._run_async(task,done,'Exporting recovered ship geometry and matched original textures…')

    def _save_zones_template(self):
        f=filedialog.asksaveasfilename(defaultextension='.json',initialfile='ship-zones.json',filetypes=[('JSON','*.json')])
        if f:
            Path(f).write_text(json.dumps({'zones':[],'note':'Add only zones with known mesh-coordinate hitboxes and provenance. Do not invent vulnerabilities.'},indent=2),encoding='utf-8')
            self.zones_var.set(f);self._status('Created empty zone annotations template')

    def _open_research(self,slug):
        row=self.db.conn.execute('SELECT id FROM articles WHERE slug=?',(slug,)).fetchone()
        if not row:return self._notice('Wiki','This research article is not yet available.')
        self.tabs.select_named('Wiki editor');self.article_search.set('');self.refresh_articles();self._select_article(row['id'])

    def _import_export(self,parent):
        self._heading(parent,'Import and export','Import your existing v3.1 results or your current wiki export. Export editable content and raw catalogs when needed.')
        self.all_datasets=tk.BooleanVar(value=False)
        ttk.Checkbutton(parent,text='Include huge diagnostics datasets (slower, larger DB)',variable=self.all_datasets).pack(anchor='w',pady=6)
        actions=ttk.Frame(parent);actions.pack(anchor='w',pady=(10,20))
        for title,callback in [
            ('Import v3 report ZIP',self._import_zip),('Import saved Scan1/2/3 reports',self._import_saved_reports),
            ('Import extracted report folder',self._import_folder),
            ('Import existing wiki files',self._import_wiki),('Export static HTML wiki',self._export_wiki),
            ('Export JSON catalog',self._export_json),('Export CSV tables',self._export_csv),
            ('Back up local database',self._backup)]:
            ttk.Button(actions,text=title,command=callback).pack(anchor='w',fill='x',pady=3)
        self.import_log=self._text(parent,height=14);self.import_log.pack(fill='both',expand=True,pady=6)
        self._log('Starter knowledge base is loaded from the Gamepedia and catalog tables in your existing reports.\n')

    def _mechanics_lab(self,parent):
        self._heading(parent,'Mechanics Lab & wiki enrichment',
            'Compare source-backed effects across the whole game. A calculated scenario is not evidence of server-side stacking, penetration, or ignition probability.')
        bar=ttk.Frame(parent);bar.pack(fill='x',pady=(0,12))
        self.lab_build=tk.StringVar(value='Game')
        ttk.Label(bar,text='Game build').pack(side='left',padx=(0,8))
        ttk.Combobox(bar,textvariable=self.lab_build,state='readonly',values=['Game','Steam'],width=13).pack(side='left')
        ttk.Button(bar,text='Enrich wiki from this build',style='Accent.TButton',command=self._enrich_wiki).pack(side='left',padx=(12,8))
        ttk.Button(bar,text='Refresh source evidence',command=self._lab_sources).pack(side='left')
        ttk.Button(bar,text='Measured HP atlas',command=self._measured_hp_atlas).pack(side='left',padx=6)
        ttk.Button(bar,text='Shot CSV template',command=self._measured_hp_template).pack(side='left',padx=6)
        ballistics=load_ballistics_catalog(self.db).get('datasets',{})
        weaponline=ttk.Frame(parent);weaponline.pack(fill='x',pady=(0,8))
        ttk.Label(weaponline,text='Experimental damage cannon:').pack(side='left')
        self.damage_cannon=tk.StringVar(value='42-pdr Carronade')
        ttk.Combobox(weaponline,textvariable=self.damage_cannon,state='readonly',width=27,
            values=[str(r.get('EnglishName')) for r in ballistics.get('Cannons',[]) if r.get('EnglishName')]).pack(side='left',padx=7)
        ttk.Label(weaponline,text='Ammunition:').pack(side='left')
        self.damage_ammo=tk.StringVar(value='Round Shot')
        ttk.Combobox(weaponline,textvariable=self.damage_ammo,state='readonly',width=24,
            values=[str(r.get('EnglishName')) for r in ballistics.get('CannonBalls',[]) if r.get('EnglishName')]).pack(side='left',padx=7)
        ttk.Label(weaponline,text='Hypothesis only: not authoritative HP damage.',style='Muted.TLabel').pack(side='left',padx=6)
        pane=ttk.PanedWindow(parent,orient='horizontal');pane.pack(fill='both',expand=True)
        left=ttk.Frame(pane);right=ttk.Frame(pane)
        pane.add(left,weight=3);pane.add(right,weight=5)
        ttk.Label(left,text='Mechanics scenario',style='Section.TLabel').pack(anchor='w',pady=(8,8))
        self.lab_topic=tk.StringVar(value='Crafting capacity')
        box=ttk.Combobox(left,textvariable=self.lab_topic,state='readonly',width=35,
            values=['Crafting capacity','Recipe craft-time cost','Mine / manufactory yield',
                    'Effective armor','Combat damage hypotheses','Fire & microfire threshold','Wind rose boundaries'])
        box.pack(fill='x',pady=(0,12));box.bind('<<ComboboxSelected>>',lambda _e:self._lab_topic_refresh())
        self.lab_fields=[]
        for _ in range(5):
            line=ttk.Frame(left);line.pack(fill='x',pady=5)
            label=ttk.Label(line,text='',width=23);label.pack(side='left')
            var=tk.StringVar(value='0')
            inp=ttk.Entry(line,textvariable=var,width=22);inp.pack(side='left',fill='x',expand=True)
            self.lab_fields.append((label,var,inp))
        ttk.Button(left,text='Calculate scenario',style='Accent.TButton',command=self._lab_calculate).pack(anchor='w',pady=(15,10))
        ttk.Label(left,text='Known evidence / extracted bonuses',style='Section.TLabel').pack(anchor='w',pady=(14,7))
        self.lab_sources=self._text(left,height=10);self.lab_sources.pack(fill='both',expand=True)
        ttk.Label(right,text='Result · Assumptions · Evidence',style='Section.TLabel').pack(anchor='w',pady=(8,8))
        self.lab_result=self._text(right)
        self.lab_result.pack(fill='both',expand=True,padx=(10,0))
        self._lab_topic_refresh();self._lab_sources()

    def _measured_hp_template(self):
        file=filedialog.asksaveasfilename(title='Create a controlled combat-test spreadsheet',
            defaultextension='.csv',initialfile='WoSB-Measured-Shots.csv',filetypes=[('CSV','*.csv')])
        if file:
            try:write_trial_template(file);self._notice('Trial sheet created','Record each actual HP change, including weapon, ammunition, impact location, angle and range. Mixed broadside/single-shot trials are deliberately separated.')
            except Exception as exc:self._error('Trial sheet',exc)

    def _measured_hp_atlas(self):
        file=filedialog.askopenfilename(title='Load recorded in-game damage trials',filetypes=[('CSV measured shots','*.csv')])
        if not file:return
        target=home()/'DamageTrials'/'Measured-Damage-Atlas.html'
        def worker():return generate_trial_dashboard(file,target)
        def done(path):
            webbrowser.open(Path(path).as_uri())
            self._notice('Measured HP evidence atlas',
                'The atlas shows measured damage only, with untested cells blank and three or more observations required for a colored result.\n'+str(path))
        self._run_async(worker,done,'Analyzing controlled combat trials…')

    def _compare_ship_screenshots(self):
        actual=filedialog.askopenfilename(title='Choose a screenshot from the actual WoSB game',filetypes=[('Image','*.png *.jpg *.jpeg')])
        if not actual:return
        viewer=filedialog.askopenfilename(title='Choose the Workbench ship viewer screenshot',filetypes=[('Image','*.png *.jpg *.jpeg')])
        if not viewer:return
        output=home()/'VisualComparisons'/('WoSB-Comparison-'+__import__('datetime').datetime.now().strftime('%Y%m%d-%H%M%S')+'.png')
        def done(result):
            self._notice('WoSB visual comparison',result['output']+'\n\n'+result['alignment_warning'])
            if os.name=='nt':os.startfile(result['output'])
        self._run_async(lambda:compare_screenshots(actual,viewer,output),done,'Generating game-versus-Workbench visual comparison…')

    def _lab_topic_refresh(self):
        if not hasattr(self,'lab_fields'):return
        specs={
            'Crafting capacity':[('Base crafting-time limit','600'),('Guild flat capacity bonus','300'),('Bonus per workshop','5'),('Eligible workshops','4')],
            'Recipe craft-time cost':[('Recipe craft hours','5'),('Reduction percent','0'),('Output quantity','1')],
            'Mine / manufactory yield':[('Output per operation','6'),('Flat addition','0'),('Percent bonus','0'),('Number of operations','10')],
            'Effective armor':[('BasicArmor','8.8'),('PArmor (%)','0'),('MArmor','0')],
            'Combat damage hypotheses':[('Target basic armor','12'),('Impact obliquity (°)','0'),('Confirmed hit count','1'),('Attack bonus (%)','0'),('Bow reduction (%)','0')],
            'Fire & microfire threshold':[('Ship MaxHP','4000'),('Big-fire damage reduction (%)','0'),('Fire-area damage reduction (%)','0'),('Microfire fight bonus (%)','0'),('Big-fire fight bonus (%)','0')],
            'Wind rose boundaries':[('Wind-relative angle (°)','90')],
        }
        entries=specs.get(self.lab_topic.get(),[])
        for i,(label,var,inp) in enumerate(self.lab_fields):
            if i<len(entries):label.config(text=entries[i][0]);var.set(entries[i][1]);inp.config(state='normal')
            else:label.config(text='');var.set('');inp.config(state='disabled')
        self._lab_sources()

    def _lab_calculate(self):
        topic=self.lab_topic.get()
        try:
            values=[v.get() for _,v,_ in self.lab_fields if v.get().strip()]
            if topic=='Crafting capacity':result=crafting_capacity_scenario(*values)
            elif topic=='Recipe craft-time cost':result=crafting_spend(*values)
            elif topic=='Mine / manufactory yield':result=facility_output_per_operation(*values)
            elif topic=='Effective armor':result=armor_effective(*values)
            elif topic=='Combat damage hypotheses':
                data=load_ballistics_catalog(self.db)['datasets']
                cannon=damage_lookup(data['Cannons'],self.damage_cannon.get())
                ammo=damage_lookup(data['CannonBalls'],self.damage_ammo.get())
                result=damage_hypotheses_calculate(cannon,ammo,target_armor=float(values[0]),
                    angle_deg=float(values[1]),hit_count=int(values[2]),
                    damage_percent_bonus=float(values[3]),bow_protection_percent=float(values[4]),
                    direction='bow' if float(values[4]) else 'side')
            elif topic=='Fire & microfire threshold':
                fire=fire_damage_multiplier(*values[1:]);result={'large_fire_gate':microfire_threshold(values[0]),'fire_getters':fire}
            else:
                source=load_catalog_rules(self.db,self.lab_build.get())['WindRoses']
                rose=source[0]['raw'] if source else {'Name':'not imported'}
                result=wind_lookup(rose,values[0])
            self.lab_result.delete('1.0','end')
            self.lab_result.insert('1.0',json.dumps(result,indent=2,ensure_ascii=False)+
                '\n\nIMPORTANT: These are evidence-bounded expressions and WHAT-IF inputs. '
                'Live server damage, wind speed and crafting stacking are not automatically verified.')
        except Exception as exc:self._error('Calculator input',exc)

    def _lab_sources(self):
        if not hasattr(self,'lab_sources') or not hasattr(self,'lab_topic'):return
        topic=self.lab_topic.get().casefold()
        domain=('craft' if 'craft' in topic or 'recipe' in topic else
                'mine' if 'mine' in topic else 'armor' if 'armor' in topic or 'damage' in topic else
                'fire' if 'fire' in topic else 'wind')
        rows=contextual_bonuses(self.db,self.lab_build.get())
        subset=[r for r in rows if domain in (r['name']+' '+r['effect']+' '+r['description']).casefold()]
        output=[]
        for r in subset[:65]:
            output.append(f"{r['name']} [{r['dataset']}] — {r['effect']} / Levels: {r['levels']}\n  Source: {r['source']}")
        if not output:output=['No matching source bonuses imported for this build.']
        self.lab_sources.delete('1.0','end');self.lab_sources.insert('1.0','\n\n'.join(output))

    def _enrich_wiki(self):
        build=self.lab_build.get()
        if not messagebox.askyesno('Generate source-linked wiki pages',
            'Create/edit only unmodified, source-only wiki pages for '+build+'?\n'
            'Manually edited articles are preserved. This creates drafts, not verified rules.',parent=self.root):return
        def worker():
            db=CatalogDB(self.db.path)
            try:return enrich_catalog(db,build=build,include_heavy=False)
            finally:db.close()
        def done(result):
            self.refresh_all();self._notice('Wiki enrichment',
                f"Processed {result['created_or_examined']} source-backed pages for {build}. "
                'Manual edits were preserved. Open Wiki editor to review them.')
        self._run_async(worker,done,'Building source-backed wiki pages…')

    def _network_lab(self,parent):
        self._heading(parent,'Network Research Lab',
            'Passive PCAP/PCAPNG inspection, opt-in Wireshark capture, controlled gameplay event markers and privacy-safe wiki evidence.')
        outer=ttk.Frame(parent);outer.pack(fill='both',expand=True)
        buttons=ttk.Frame(outer);buttons.pack(fill='x',pady=(0,12))
        ttk.Button(buttons,text='Import PCAP / PCAPNG',style='Accent.TButton',command=self._network_import).pack(side='left',padx=(0,8))
        ttk.Button(buttons,text='Export redacted research',command=self._network_export).pack(side='left',padx=(0,8))
        ttk.Button(buttons,text='Create wiki research page',command=self._network_wiki).pack(side='left',padx=(0,8))
        proto=ttk.LabelFrame(outer,text='Protocol Lab · message framing, type catalog and client message definitions (offline, read-only)',padding=10)
        proto.pack(fill='x',pady=(0,10))
        ttk.Button(proto,text='Catalog messages: capture files…',style='Accent.TButton',command=self._protocol_catalog_files).pack(side='left',padx=(0,6))
        ttk.Button(proto,text='Catalog messages: gameplay session…',command=self._protocol_catalog_session).pack(side='left',padx=6)
        ttk.Button(proto,text='Extract message definitions from client/launcher…',command=self._protocol_extract).pack(side='left',padx=6)
        ttk.Button(proto,text='Compare definitions (build diff)…',command=self._protocol_diff).pack(side='left',padx=6)
        ttk.Button(proto,text='Export private message log…',command=self._protocol_message_log).pack(side='left',padx=6)
        control=ttk.Frame(outer);control.pack(fill='x',pady=(0,10))
        ttk.Label(control,text='Interface number:').pack(side='left')
        self.network_interface=tk.StringVar(value='')
        ttk.Entry(control,textvariable=self.network_interface,width=6).pack(side='left',padx=(6,10))
        ttk.Button(control,text='List Wireshark interfaces',command=self._network_interfaces).pack(side='left',padx=5)
        self.network_capture_start=ttk.Button(control,text='Start passive capture',command=self._network_start_capture)
        self.network_capture_start.pack(side='left',padx=5)
        self.network_capture_stop=ttk.Button(control,text='Stop capture',command=self._network_stop_capture,state='disabled')
        self.network_capture_stop.pack(side='left',padx=5)
        studio=ttk.LabelFrame(outer,text='Gameplay Capture Studio · video + packets + timed event markers',padding=12)
        studio.pack(fill='x',pady=(0,12))
        row=ttk.Frame(studio);row.pack(fill='x',pady=(0,6))
        ttk.Label(row,text='Video source').pack(side='left')
        self.gameplay_video_source=tk.StringVar(value='desktop')
        ttk.Entry(row,textvariable=self.gameplay_video_source,width=23).pack(side='left',padx=8)
        ttk.Label(row,text='desktop, or exact game window title').pack(side='left',padx=(0,10))
        self.gameplay_port=tk.StringVar(value='23771')
        ttk.Label(row,text='Verified WoSB TCP port').pack(side='left')
        ttk.Entry(row,textvariable=self.gameplay_port,width=7).pack(side='left',padx=8)
        ttk.Button(row,text='Detect game',command=self._gameplay_detect).pack(side='left',padx=4)
        ttk.Button(row,text='Auto-select network adapter',command=self._gameplay_auto_interface).pack(side='left',padx=4)
        fight=ttk.Frame(studio);fight.pack(fill='x',pady=(0,5))
        self.gameplay_fight_shooter=tk.StringVar(value='Huracan')
        self.gameplay_fight_target=tk.StringVar(value="Merchant's Grace")
        self.gameplay_fight_weapon=tk.StringVar(value='42-pound carronades')
        self.gameplay_fight_ammo=tk.StringVar(value='Round shot')
        for textlabel,var,width in [('Player ship',self.gameplay_fight_shooter,13),('Target',self.gameplay_fight_target,18),
                                    ('Weapon',self.gameplay_fight_weapon,20),('Ammo',self.gameplay_fight_ammo,12)]:
            ttk.Label(fight,text=textlabel).pack(side='left',padx=(4,3))
            ttk.Entry(fight,textvariable=var,width=width).pack(side='left',padx=(0,6))
        row=ttk.Frame(studio);row.pack(fill='x')
        self.gameplay_start=ttk.Button(row,text='● Start video + game packets',style='Accent.TButton',command=self._gameplay_start)
        self.gameplay_start.pack(side='left',padx=(0,6))
        self.gameplay_stop=ttk.Button(row,text='■ Stop & analyze',command=self._gameplay_stop,state='disabled')
        self.gameplay_stop.pack(side='left',padx=6)
        ttk.Button(row,text='Show marker overlay',command=self._gameplay_show_overlay).pack(side='left',padx=6)
        ttk.Button(row,text='Export review-only ZIP',command=self._gameplay_review_export).pack(side='left',padx=6)
        ttk.Button(row,text='Create short video clips',command=self._gameplay_clips_export).pack(side='left',padx=6)
        ttk.Button(row,text='Combat evidence ZIP',command=self._gameplay_evidence_export).pack(side='left',padx=6)
        ttk.Button(row,text='Open recording folder',command=self._gameplay_open_folder).pack(side='left',padx=6)
        ttk.Label(studio,text='Requires FFmpeg (video) and TShark/Npcap (passive packets). Audio is OFF. Overlay buttons and optional Ctrl+Alt+F1–F10 hotkeys mark shots, regions, HP, sinking and fires. A colored Sync flash helps align the video with packet time. Raw video/PCAP stays local unless you explicitly share it.',
                  style='Muted.TLabel',wraplength=980).pack(anchor='w',pady=(7,0))
        offsetrow=ttk.Frame(studio);offsetrow.pack(fill='x',pady=(3,1))
        ttk.Label(offsetrow,text='Video sync correction (seconds)').pack(side='left')
        self.gameplay_video_offset=tk.StringVar(value='0')
        ttk.Entry(offsetrow,textvariable=self.gameplay_video_offset,width=8).pack(side='left',padx=7)
        ttk.Label(offsetrow,text='Adjust after finding the yellow flash in the recording; timestamps are approximate until aligned.',style='Muted.TLabel').pack(side='left')
        ttk.Label(offsetrow,text='Evidence ZIP monitor').pack(side='left',padx=(14,4))
        self.gameplay_export_monitor=tk.StringVar(value='left')
        ttk.Combobox(offsetrow,textvariable=self.gameplay_export_monitor,values=['left','right','none'],
                     state='readonly',width=7).pack(side='left',padx=2)
        self.gameplay_status=tk.StringVar(value='No recording active · connects to verified WorldOfSeaBattleClient TCP port 23771')
        ttk.Label(studio,textvariable=self.gameplay_status,style='Muted.TLabel',wraplength=990).pack(anchor='w',pady=(3,0))
        ttk.Label(outer,text='Captures can include private data. Only capture your authorized traffic. Keep original PCAP files local; exported research removes payloads and full IP addresses.',
            style='Muted.TLabel',wraplength=1000).pack(anchor='w',pady=(0,10))
        split=ttk.Panedwindow(outer,orient='horizontal');split.pack(fill='both',expand=True)
        left=ttk.Frame(split);right=ttk.Frame(split);split.add(left,weight=1);split.add(right,weight=3)
        ttk.Label(left,text='Imported capture sessions',style='Section.TLabel').pack(anchor='w')
        self.network_sessions=tk.Listbox(left,bg=PANEL,fg=TEXT,selectbackground='#286876',height=11,exportselection=False,
                                         relief='flat',font=('Segoe UI',10))
        self.network_sessions.pack(fill='both',expand=True,pady=8)
        self.network_sessions.bind('<<ListboxSelect>>',self._network_selected)
        self.network_sessions_ids=[]
        ttk.Label(right,text='Session and traffic evidence',style='Section.TLabel').pack(anchor='w')
        self.network_text=self._text(right,height=15);self.network_text.pack(fill='both',expand=True,pady=8)
        evrow=ttk.Frame(right);evrow.pack(fill='x',pady=6)
        self.network_event_kind=tk.StringVar(value='cannon impact')
        self.network_event_options=ttk.Combobox(evrow,textvariable=self.network_event_kind,
            values=['cannon impact','ordinary fire','large fire','fire extinguished','flooding','sailing / wind','crafting','production','market trade','port event','other'],width=20)
        self.network_event_options.pack(side='left',padx=(0,8))
        self.network_event_time=tk.StringVar(value='')
        ttk.Entry(evrow,textvariable=self.network_event_time,width=24).pack(side='left',padx=(0,6))
        self.network_note=tk.StringVar()
        ttk.Entry(evrow,textvariable=self.network_note,width=36).pack(side='left',fill='x',expand=True,padx=6)
        ttk.Button(evrow,text='Mark event now',command=self._network_mark).pack(side='left',padx=6)
        ttk.Label(right,text='UTC timestamp field (optional): enter 2026-11-16T23:00:00+00:00 to mark historical events; blank = now. During capture markers are queued for import.',
            style='Muted.TLabel',wraplength=800).pack(anchor='w')

    def _gameplay_detect(self):
        try:
            connections=discover_game_ports()
            if connections:
                preferred=connections[0]
                self.gameplay_port.set(str(preferred['port']))
                self.gameplay_status.set('Confirmed WoSB PID '+str(preferred['pid'])+' · TCP '+
                     ', '.join(str(p['port']) for p in connections[:8])+' · selected '+str(preferred['port']))
                self._gameplay_auto_interface()
            else:
                self.gameplay_status.set('No established WorldOfSeaBattleClient TCP connection found. Open the game and connect before recording.')
        except Exception as exc:self._error('Game connection detection',exc)

    def _gameplay_auto_interface(self):
        try:
            port=int(self.gameplay_port.get())
            info=detect_game_capture_interface(port)
            if info:
                self.network_interface.set(info['interface'])
                self.gameplay_status.set('Game traffic route detected: '+info['label']+
                    ' · adapter '+info['interface']+' (recheck if your network changes)')
                return info
            self.gameplay_status.set('Could not map WoSB connection to one adapter. Select Wi-Fi/Ethernet via List Wireshark interfaces.')
            return None
        except Exception as exc:
            self._error('Capture adapter discovery',exc)
            return None

    def _gameplay_start(self):
        if self.gameplay_session and self.gameplay_session.started:return
        if os.name!='nt':return self._notice('Windows capture','Live gameplay recording requires Windows.')
        if not find_ffmpeg():return self._notice('FFmpeg required','Install FFmpeg or use the WinGet FFmpeg package.')
        if not find_tshark():return self._notice('TShark required','Install Wireshark with TShark/Npcap.')
        try:port=int(self.gameplay_port.get())
        except ValueError:return self._notice('Invalid game port','Enter a TCP port number, normally 23771.')
        own=game_process_connection(port)
        if not own.get('confirmed'):
            return self._notice('Game connection not confirmed','Connect to WoSB first. '+own.get('reason',''))
        # Do not reuse interface 1 because it happened to be the first adapter.
        suggested=detect_game_capture_interface(port)
        if suggested:self.network_interface.set(suggested['interface'])
        selected=self.network_interface.get().strip()
        if not selected.isdigit() or int(selected)<1:
            return self._notice('Select recording adapter',
                'Click Auto-select network adapter or List Wireshark interfaces first. '
                'Workbench will not guess adapter 1.')
        self.gameplay_start.configure(state='disabled')
        def probe():
            try:return preview_interface_traffic(selected,port=port,seconds=3)
            except Exception as exc:return {'active':False,'error':str(exc)}
        def done(check):
            if not check.get('active'):
                decision=messagebox.askyesno('No WoSB traffic detected on selected adapter',
                    'Adapter '+selected+' did not capture game packets during the brief test.\n'
                    'The game may be idle, or this may be the wrong interface.\n\n'
                    'Continue recording anyway? We recommend fixing this before a long combat session.\n\n'
                    +str(check.get('error','')),parent=self.root)
                if not decision:
                    self.gameplay_start.configure(state='normal')
                    return
            self._gameplay_begin_recording(own,port,selected)
        self._run_async(probe,done,'Checking the selected interface for WoSB packets…')

    def _gameplay_begin_recording(self,own,port,selected):
        if not messagebox.askyesno('Record gameplay and packets',
            'Record local gameplay video (no audio) and passive WoSB traffic on adapter '+selected+'?\n\n'
            'Raw PCAP and video may contain private data. Review exports before sharing.\n\nStart recording?',parent=self.root):
            self.gameplay_start.configure(state='normal')
            return
        from datetime import datetime
        folder=home()/'GameplaySessions'/datetime.now().strftime('WoSB-%Y%m%d-%H%M%S')
        try:
            session=GameplaySession(folder,interface=selected,port=port,
                video_source=self.gameplay_video_source.get().strip() or 'desktop')
            session.start(ownership=own)
            session.meta['fight']={'shooter_ship':self.gameplay_fight_shooter.get().strip()[:80],
                'target_ship':self.gameplay_fight_target.get().strip()[:80],
                'weapon':self.gameplay_fight_weapon.get().strip()[:80],
                'ammo':self.gameplay_fight_ammo.get().strip()[:80]}
            from gameplay_capture import _write_atomic
            _write_atomic(folder/'session.json',session.meta)
            self.gameplay_session=session;self.last_gameplay_dir=folder
            self.gameplay_start.configure(state='disabled');self.gameplay_stop.configure(state='normal')
            self.gameplay_status.set('Recording video + WoSB TCP traffic · '+folder.name+' · use overlay to mark shots')
            self._gameplay_show_overlay()
            self.gameplay_hotkeys=CaptureHotkeys(lambda event:self.status_events.put(('game-hotkey',event)))
            hotkeys_active=self.gameplay_hotkeys.start()
            if hotkeys_active:self.gameplay_status.set('Recording · Ctrl+Alt+F1 Single · F2 Broadside · F3 Stern · F4 Side · F5 Sails · F6 Sunk · F7 Sync · F8 Hit · F9 Minor fire · F10 Large fire')
            self._gameplay_mark('sync-flash','Recording start / visual alignment')
        except Exception as exc:
            self.gameplay_start.configure(state='normal')
            self._error('Gameplay capture start',exc)

    def _gameplay_show_overlay(self):
        if self.gameplay_overlay is not None:
            try:self.gameplay_overlay.lift();return
            except tk.TclError:self.gameplay_overlay=None
        win=tk.Toplevel(self.root);win.title('WoSB · Shot Markers');win.attributes('-topmost',True)
        try:win.attributes('-alpha',0.92)
        except tk.TclError:pass
        win.configure(bg='#10202a');win.geometry('480x320+80+100')
        def close():self.gameplay_overlay=None;win.destroy()
        win.protocol('WM_DELETE_WINDOW',close)
        tk.Label(win,text='⚓  WoSB CAPTURE  ·  MARK THE FIGHT',font=('Segoe UI Semibold',12),
                 bg='#10202a',fg='#e8f7ff').pack(fill='x',pady=(10,3))
        for items in ((('Single shot','single-shot'),('Broadside','broadside'),('Mortar','mortar'),('Barrel','barrel')),
                      (('Stern','stern'),('Side','side'),('Bow','bow'),('Sails','sails')),
                      (('Hit','hit'),('Miss','miss'),('HP reading','health'),('Target sunk','target-sunk')),
                      (('Minor fire','minor-fire'),('Large fire','large-fire'))):
            row=tk.Frame(win,bg='#10202a');row.pack(fill='x',padx=8,pady=3)
            for label,kind in items:
                tk.Button(row,text=label,command=lambda k=kind:self._gameplay_mark(k),
                      bg='#254055',fg='white',activebackground='#176b76',bd=0,
                      font=('Segoe UI',9),padx=6,pady=5,width=11).pack(side='left',expand=True,fill='x',padx=2)
        targetrow=tk.Frame(win,bg='#10202a');targetrow.pack(fill='x',padx=9,pady=(5,1))
        tk.Label(targetrow,text='Current target:',fg='#d4e7ee',bg='#10202a').pack(side='left')
        tk.Entry(targetrow,textvariable=self.gameplay_fight_target,bg='#23364e',fg='white',
                 insertbackground='white',relief='flat').pack(side='left',fill='x',expand=True,padx=5)
        row=tk.Frame(win,bg='#10202a');row.pack(fill='x',padx=9,pady=(6,2))
        self.gameplay_marker_note=tk.StringVar()
        tk.Entry(row,textvariable=self.gameplay_marker_note,bg='#23364e',fg='white',insertbackground='white',
                 relief='flat').pack(side='left',expand=True,fill='x',padx=4)
        tk.Button(row,text='Sync flash',command=self._gameplay_sync_flash,bg='#c47831',fg='white',bd=0).pack(side='left',padx=4)
        self.gameplay_overlay=win

    def _gameplay_sync_flash(self):
        self._gameplay_mark('sync-flash','Visible yellow flash for video alignment')
        if self.gameplay_overlay:
            w=self.gameplay_overlay;w.configure(bg='#f9d34d')
            w.after(650,lambda: w.winfo_exists() and w.configure(bg='#10202a'))

    def _gameplay_mark(self,kind,note=None):
        session=self.gameplay_session
        if not session or not session.started:
            return self._status('Start Gameplay Capture Studio before marking events')
        extra=self.gameplay_marker_note.get() if hasattr(self,'gameplay_marker_note') else ''
        try:
            event=session.mark(kind,note if note is not None else extra,
                target=self.gameplay_fight_target.get(),weapon=self.gameplay_fight_weapon.get(),
                ammo=self.gameplay_fight_ammo.get())
            self.gameplay_status.set('Recorded '+kind+' marker at '+event['utc']+' · '+str(session.meta['events_count'])+' markers')
            if hasattr(self,'gameplay_marker_note'):self.gameplay_marker_note.set('')
        except Exception as exc:self._error('Gameplay marker',exc)

    def _gameplay_stop(self):
        if not self.gameplay_session or not self.gameplay_session.started:return
        if getattr(self,'_gameplay_stopping',False):return
        self._gameplay_stopping=True
        session=self.gameplay_session;directory=session.folder
        if self.gameplay_hotkeys:self.gameplay_hotkeys.stop();self.gameplay_hotkeys=None
        self.gameplay_stop.configure(state='disabled')
        self.gameplay_status.set('Stopping recording tools (this can take a few seconds)…')
        def task(ctx):
            ctx.progress(None,'Stopping FFmpeg and TShark…')
            session.stop()
            ctx.progress(None,'Building video/packet event timeline…');ctx.set_output(directory)
            return analyze_gameplay_session(directory)
        def done(result):
            self._gameplay_stopping=False
            self.gameplay_start.configure(state='normal')
            health=result['traffic'].get('capture_status')
            if health!='traffic_recorded':
                self.gameplay_status.set('WARNING: No game packets found. Video and markers saved in '+str(directory))
                self._notice('Recording saved without usable game packets',
                    'The recording contains no WoSB TCP payloads. Check the capture adapter before another fight.\n\n'+str(directory),kind='warning')
            else:
                self.gameplay_status.set('Analyzed '+str(result['recorded_events'])+' markers · game packets recorded · '+str(directory))
                self._notice('Recording analyzed',str(result['recorded_events'])+' markers correlated with game packets.',kind='success',
                             action=('Catalog messages',lambda:self._protocol_catalog_session_path(str(directory))))
        job=self._run_async(task,done,'Stopping recording and analyzing…',name='Stop gameplay recording')
        def failed_reset():
            if not job.active and job.status!='done':
                self._gameplay_stopping=False;self.gameplay_start.configure(state='normal')
            elif job.active:self.root.after(1000,failed_reset)
        self.root.after(1000,failed_reset)

    def _gameplay_clips_export(self):
        folder=self.last_gameplay_dir
        if not folder:
            folder=self._pick_session('Pick a completed WoSB gameplay recording')
            if not folder:return
        if self.gameplay_session and self.gameplay_session.started:return self._notice('Still recording','Stop the recording before exporting video clips.')
        if not messagebox.askyesno('Export identifiable video clips',
            'Export up to 10 short clips around your marked events? These MP4 clips may reveal player names, chat, private UI, or other personal details. Review every clip before sharing it.',parent=self.root):return
        try:
            from gameplay_capture import load_session,_write_atomic
            meta=load_session(folder)
            meta['capture']['video_offset_seconds']=float(self.gameplay_video_offset.get())
            _write_atomic(Path(folder)/'session.json',meta)
        except Exception as exc:return self._error('Invalid video sync offset',exc)
        def worker():return export_video_clips(folder)
        def done(paths):self._notice('Video clips ready',
            ('Created '+str(len(paths))+' local gameplay clips. Review them before sharing.\n\n'+str(Path(folder)/'clips')) if paths else 'No marked single-shot, broadside, hit, sails or sinking events found.')
        self._run_async(worker,done,'Extracting marked video excerpts…')

    def _gameplay_review_export(self):
        folder=self.last_gameplay_dir
        if not folder:
            folder=self._pick_session('Pick a WoSB GameplaySessions recording')
            if not folder:return
        if self.gameplay_session and self.gameplay_session.started:return self._notice('Still recording','Stop recording before exporting a review ZIP.')
        try:offset=float(self.gameplay_video_offset.get())
        except ValueError:return self._notice('Invalid video offset','Enter an offset in seconds, e.g. 0 or -0.8.')
        def do_export():
            from gameplay_capture import load_session,_write_atomic
            meta=load_session(folder)
            meta['capture']['video_offset_seconds']=offset
            _write_atomic(Path(folder)/'session.json',meta)
            analyze_gameplay_session(folder,video_offset_seconds=offset)
            return export_sanitized_review(folder)
        self._run_async(do_export,lambda result:self._notice('Redacted gameplay review package',
            str(result)+'\n\nContains timing and event statistics only, not video or private packet payloads.'),'Exporting private-data-safe gameplay timeline…')

    def _gameplay_evidence_export(self):
        folder=self.last_gameplay_dir
        if not folder:
            folder=self._pick_session('Pick completed gameplay session')
            if not folder:return
        if self.gameplay_session and self.gameplay_session.started:
            return self._notice('Still recording','Stop recording before exporting combat evidence.')
        if not messagebox.askyesno('Shareable combat evidence',
            'Create a compact video and marked-event screenshot ZIP?\n\n'
            'The ZIP excludes raw packet payloads but DOES include gameplay video and '
            'screenshots which can show player names or chat. Review it before sharing.\n\nContinue?',
            parent=self.root):return
        try:offset=float(self.gameplay_video_offset.get())
        except ValueError:return self._notice('Invalid video offset','Enter a number of seconds for video alignment.')
        monitor=self.gameplay_export_monitor.get()
        def run_export():
            from gameplay_capture import load_session,_write_atomic
            meta=load_session(folder)
            meta['capture']['video_offset_seconds']=offset
            _write_atomic(Path(folder)/'session.json',meta)
            analyze_gameplay_session(folder,video_offset_seconds=offset)
            return export_combat_evidence(folder,monitor=monitor)
        def done(path):
            self._notice('Combat evidence ZIP ready',str(path)+
                '\n\nVideo and screenshot content is NOT automatically anonymized. Please review before uploading.')
        self._run_async(run_export,done,'Compressing gameplay and collecting marked-event snapshots…')

    def _gameplay_open_folder(self):
        folder=self.last_gameplay_dir or home()/'GameplaySessions'
        folder.mkdir(parents=True,exist_ok=True)
        if os.name=='nt':os.startfile(str(folder))
        else:self._notice('Recording folder',str(folder))

    def _network_refresh(self):
        if not hasattr(self,'network_sessions'):return
        old=self.network_sid
        sessions=list_sessions(self.db.conn)
        self.network_sessions.delete(0,'end');self.network_sessions_ids=[]
        for r in sessions:
            self.network_sessions_ids.append(r['id'])
            self.network_sessions.insert('end',f"{r['label']}  ·  {r['created_utc'][:16]}")
        if old in self.network_sessions_ids:
            index=self.network_sessions_ids.index(old)
            self.network_sessions.selection_set(index);self.network_sessions.activate(index)
        elif self.network_sessions_ids:
            self.network_sessions.selection_set(0);self.network_sid=self.network_sessions_ids[0]
        self._network_show()

    def _network_selected(self,_event=None):
        selection=self.network_sessions.curselection()
        if selection:self.network_sid=self.network_sessions_ids[selection[0]];self._network_show()

    def _network_show(self):
        if not hasattr(self,'network_text'):return
        self.network_text.delete('1.0','end')
        if not self.network_sid:return
        summary=get_summary(self.db.conn,self.network_sid)
        lines=[f"Session: {summary['label']}",f"Captured: {summary['first_utc']} — {summary['last_utc']}",
            f"Packets: {summary['packet_count']:,}  |  Flows: {len(summary['flows']):,}",
            f"Transport: {summary['protocols']}",f"Candidate protocols: {summary['classifications']}",
            f"Unsupported/fragmented: {summary['skipped']}", '', 'TOP CONVERSATIONS (IP prefixes, NOT complete addresses)']
        for flow in summary['flows'][:40]:
            lines.append(f"{flow['id']}  {flow['protocol']}  {flow['endpoint_a_prefix']}:{flow['port_a']} ↔ {flow['endpoint_b_prefix']}:{flow['port_b']} | {flow['packets']} pkts | {flow['bytes']:,} bytes | {flow['classifications']}")
        events=[dict(x) for x in self.db.conn.execute('SELECT event_utc,category,note FROM network_events WHERE session_id=? ORDER BY event_utc',(self.network_sid,))]
        lines+=['','EVENTS / TEMPORAL CORRELATIONS (NOT PROVEN PACKET DECODES)']
        for result in event_correlations(summary,events):
            lines.append(f"{result['event_utc']} {result['category']} | ±{result['window_seconds']}s {result['packets']} packets, {result['bytes']} bytes | {result['note']}")
        lines+=['','Decode confidence: unclassified / transport hints only. Encrypted traffic is NOT decrypted.']
        self.network_text.insert('end','\n'.join(lines))

    # ---------------------------------------------------------------- Protocol Lab
    def _protocol_definitions_hint(self):
        path=home()/'Research'/'Protocol'/'Protocol-Definitions-latest.json'
        try:return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else None
        except (OSError,ValueError):return None

    def _protocol_done(self,result):
        report,dest=result
        lines=[f"Saved: {dest}",'']
        if report.get('warning'):lines+=['WARNING: '+report['warning'],'']
        framing=report.get('framing')
        lines.append('Framing hypothesis: '+(framing['description'] if framing else 'none found'))
        lines.append(f"Messages: {report.get('messages',0):,} · unframed tail bytes: {report.get('unframed_tail_bytes',0):,} · payload entropy {report.get('payload_entropy_bits')} bits/byte")
        lines+=['','MESSAGE TYPE CANDIDATES (direction:opcode · count · size range · constant-byte mask)']
        for t in report.get('catalog',{}).get('types',[])[:60]:
            lines.append(f"{t['type_id']:<18} {t['count']:>7}  {t['size_min']}-{t['size_max']} B  {'periodic ' if t['periodic_hint'] else ''}{'OPAQUE ' if t['opaque_hint'] else ''}{t['constant_byte_mask'][:32]}")
        if report.get('marker_associations'):
            lines+=['','MARKER ASSOCIATIONS (lift = over-representation near your markers)']
            for a in report['marker_associations'][:40]:
                lines.append(f"{a['marker_kind']:<12} {a['type_id']:<18} lift {a['lift']} ({a['markers_with_type_nearby']}/{a['markers']} markers)")
        if report.get('definition_matches'):
            lines+=['','MATCHES WITH CLIENT OPCODE ENUMS']
            for d in report['definition_matches'][:10]:
                lines.append(f"{d['enum']}: {d['observed_overlap']} observed ids named ({d['coverage_of_observed']*100:.0f}% of observed)")
        self.network_text.delete('1.0','end');self.network_text.insert('1.0','\n'.join(lines))
        self._last_protocol_result=(report,dest)
        self._notice('Message catalog ready',f"{report.get('messages',0):,} messages · {len(report.get('catalog',{}).get('types',[]))} types",
                     kind='success',action=('Open as table',lambda:self._show_result(report,'Protocol catalog',dest)))

    def _protocol_catalog_files(self):
        files=self._pick_files('Captures to catalog',self._session_captures(),multiple=True,
            filetypes=[('Packet capture','*.pcap *.pcapng'),('All files','*.*')],prompt='Captures from your sessions, newest first. Other… picks files.')
        if not files:return
        port=self.gameplay_port.get().strip() if hasattr(self,'gameplay_port') else ''
        port=int(port) if port.isdigit() else None
        definitions=self._protocol_definitions_hint()
        def task():
            import protocol_lab
            report=protocol_lab.analyze(sorted(files),server_port=port,definitions=definitions)
            dest=protocol_lab.write_reports(report,home()/'Research'/'Protocol'/('Catalog-'+Path(files[0]).stem))
            return report,str(dest)
        self._run_async(task,self._protocol_done,'Reassembling TCP streams and cataloging message types…')

    def _protocol_catalog_session_path(self,folder):
        definitions=self._protocol_definitions_hint()
        def task():
            import protocol_lab
            report=protocol_lab.analyze_session_folder(folder,definitions=definitions)
            dest=protocol_lab.write_reports(report,Path(folder)/'Protocol')
            return report,str(dest)
        self.tabs.select_named('Network Research Lab')
        self._run_async(task,self._protocol_done,'Cataloging session messages and correlating your markers…')

    def _protocol_catalog_session(self):
        folder=self._pick_session('Session to catalog',prefer=self.last_gameplay_dir)
        if not folder:return
        definitions=self._protocol_definitions_hint()
        def task():
            import protocol_lab
            report=protocol_lab.analyze_session_folder(folder,definitions=definitions)
            dest=protocol_lab.write_reports(report,Path(folder)/'Protocol')
            return report,str(dest)
        self._run_async(task,self._protocol_done,'Cataloging session messages and correlating your markers…')

    def _protocol_extract(self,root=None):
        root=root or self._pick_install('Install to extract message definitions from')
        if not root:return
        label=Path(root).name
        def task():
            engine=str(bundled_path('engine'))
            if engine not in sys.path:sys.path.insert(0,engine)
            from protocol_extract import extract
            from advanced_io import write_json_atomic
            result=extract(root,label=label,progress=lambda m:self.status_events.put(('import-progress','Protocol extract '+m)))
            folder=home()/'Research'/'Protocol';folder.mkdir(parents=True,exist_ok=True)
            dest=folder/('Protocol-Definitions-'+slugify(label)+'.json')
            write_json_atomic(dest,result)
            write_json_atomic(folder/'Protocol-Definitions-latest.json',result)
            return result,str(dest)
        def done(value):
            result,dest=value
            lines=[f'Saved: {dest}',f"Assemblies read: {len(result['assemblies'])} · skipped/unsupported: {len(result['issues'])}",'',
                   'TOP MESSAGE-CLASS CANDIDATES']
            for m in result['message_types'][:40]:
                order=', '.join(w['type'] for s in m['serializers'][:1] for w in s['wire_order'][:12])
                lines.append(f"{m['score']:>3} {m['type']}  base={m['base']}  wire: {order or '—'}")
            lines+=['','OPCODE / MESSAGE-ID ENUMS']
            for e in result['opcode_enums'][:20]:lines.append(f"{e['name']} ({e['member_count']} members)")
            lines+=['','DISPATCH CANDIDATES']
            for d in result['dispatch_hints'][:15]:lines.append(f"{d['switch_cases']:>4} cases  {d['method']}")
            lines+=['','Static evidence only. The latest definitions are used automatically by the message catalog.']
            self.network_text.delete('1.0','end');self.network_text.insert('1.0','\n'.join(lines))
        self._run_async(task,done,'Reading .NET metadata and serializer IL (no game code executed)…')

    def _protocol_message_log(self):
        files=self._pick_files('Your session captures',self._session_captures(),multiple=True,
            filetypes=[('Packet capture','*.pcap *.pcapng')],prompt='Captures from your sessions, newest first.')
        if not files:return
        dest=filedialog.asksaveasfilename(title='Save private message log',defaultextension='.jsonl',
            initialfile='WoSB-Message-Log.jsonl',filetypes=[('JSON lines','*.jsonl')],parent=self.root)
        if not dest:return
        port=self.gameplay_port.get().strip()
        port=int(port) if port.isdigit() else None
        def task():
            import protocol_lab
            return protocol_lab.export_message_log(sorted(files),dest,server_port=port)
        self._run_async(task,lambda r:self._notice('Private message log',
            f"{r['messages']:,} messages written ({r['framing']}).\n{r['output']}\n\n"
            'Contains raw bytes of your own session (may include account/chat data). Keep it local.'),
            'Writing reassembled messages…')

    def _protocol_diff(self):
        from datetime import datetime as _dt
        saved=sorted((p for p in (home()/'Research'/'Protocol').glob('Protocol-Definitions-*.json') if p.stem!='Protocol-Definitions-latest'),
                     key=lambda p:p.stat().st_mtime,reverse=True) if (home()/'Research'/'Protocol').is_dir() else []
        opts=[(p.stem.replace('Protocol-Definitions-',''),str(p),_dt.fromtimestamp(p.stat().st_mtime).strftime('%Y-%m-%d %H:%M')) for p in saved]
        if len(saved)<2 and not messagebox.askyesno('Compare definitions',
            f'{len(saved)} saved extraction(s) found. Run “Extract message definitions” on each build you want to compare.\n\nBrowse for files instead?',parent=self.root):return
        ft=[('Protocol definitions','*.json')]
        old=self._pick_files('Older build definitions',opts[1:] or opts,filetypes=ft)
        if not old:return
        new=self._pick_files('Newer build definitions',[o for o in opts if o[1]!=old],filetypes=ft)
        if not new:return
        def task():
            engine=str(bundled_path('engine'))
            if engine not in sys.path:sys.path.insert(0,engine)
            from protocol_extract import diff_definitions
            from advanced_io import write_json_atomic
            result=diff_definitions(json.loads(Path(old).read_text(encoding='utf-8')),json.loads(Path(new).read_text(encoding='utf-8')))
            dest=home()/'Research'/'Protocol'/('Diff-'+Path(old).stem+'-vs-'+Path(new).stem+'.json')
            write_json_atomic(dest,result)
            return result,str(dest)
        def done(value):
            result,dest=value
            text=(f"Saved: {dest}\n\nAdded message types: {len(result['added_types'])}\nRemoved: {len(result['removed_types'])}\n"
                  f"Changed fields/wire order: {len(result['changed_types'])}\nOpcode enum changes: {len(result['opcode_enum_changes'])}\n\n"
                  +json.dumps(result,indent=2)[:60000])
            self.network_text.delete('1.0','end');self.network_text.insert('1.0',text)
        self._run_async(task,done,'Comparing protocol definitions…')

    def _network_import(self):
        file=filedialog.askopenfilename(title='Select capture file',filetypes=[('Packet capture','*.pcap *.pcapng'),('All files','*.*')])
        if not file:return
        self._run_async(lambda: (file,analyze_capture(file,progress=lambda n:self.status_events.put(('import-progress',f'Network packets processed: {n:,}')))),
            self._network_import_done,'Analyzing capture metadata; raw payload is not stored in the wiki...')

    def _network_import_done(self,result):
        file,summary=result
        self.network_sid=save_session(self.db.conn,summary,file)
        if self.network_capture_path and Path(file).resolve()==self.network_capture_path.resolve():
            for when,kind,note in self.network_pending_events:
                add_event(self.db.conn,self.network_sid,when,kind,note)
            self.network_pending_events=[]
        self._network_refresh()
        self._notice('Capture imported',f"{summary['packet_count']:,} packets, {len(summary['flows']):,} conversations. Capture remains local.")

    def _network_interfaces(self):
        try:self._notice('Available capture interfaces','\n'.join(list_interfaces()) or 'No interfaces found')
        except Exception as exc:self._error('Wireshark capture',exc)

    def _network_start_capture(self):
        if self.network_proc and self.network_proc.poll() is None:return
        if not messagebox.askyesno('Start passive capture',
            'Capture TCP/UDP metadata on your selected interface? Original packet files may contain private information.\n\nUse only on networks and traffic you are authorized to inspect. No interception, injection, or decryption is performed.',parent=self.root):return
        try:
            folder=home()/'NetworkCaptures';folder.mkdir(parents=True,exist_ok=True)
            name='WoSB-capture-'+__import__('datetime').datetime.now().strftime('%Y%m%d-%H%M%S')+'.pcapng'
            self.network_capture_path=folder/name
            self.network_pending_events=[]
            self.network_proc=start_capture(self.network_interface.get(),self.network_capture_path)
            self.network_capture_start.configure(state='disabled');self.network_capture_stop.configure(state='normal')
            self._status('Passive packet capture running. Use Stop capture before importing the file.')
        except Exception as exc:self._error('Capture failed',exc)

    def _network_stop_capture(self):
        try:stop_capture(self.network_proc)
        except Exception as exc:self._error('Stop capture',exc)
        self.network_proc=None
        self.network_capture_start.configure(state='normal');self.network_capture_stop.configure(state='disabled')
        self._status('Capture stopped. Import saved PCAPNG for analysis.')
        if self.network_capture_path:
            if self.network_capture_path.is_file():
                self._notice('Capture saved',str(self.network_capture_path)+'\n\nImport the saved capture to attach any queued event markers.')
            else:
                self._notice('No capture file','TShark did not write '+str(self.network_capture_path)+
                             '.\nCheck the interface number and that Npcap is installed.')

    def _network_mark(self):
        from datetime import datetime, timezone
        now=self.network_event_time.get().strip() or datetime.now(timezone.utc).isoformat(timespec='milliseconds')
        try:
            parsed=datetime.fromisoformat(now.replace('Z','+00:00'))
            if parsed.tzinfo is None:raise ValueError('Use UTC ISO timestamp with timezone offset')
            if self.network_proc and self.network_proc.poll() is None:
                self.network_pending_events.append((now,self.network_event_kind.get(),self.network_note.get()))
                self._status('Event marker queued for current live capture')
            elif self.network_sid:
                add_event(self.db.conn,self.network_sid,now,self.network_event_kind.get(),self.network_note.get())
                self._network_show();self._status('Research event marker recorded at '+now)
            else:self._notice('Research marker','Start capture or import a capture file first.')
            self.network_event_time.set('')
        except Exception as exc:self._error('Invalid event time',exc)

    def _network_export(self):
        if not self.network_sid:return self._notice('Export','Select an imported capture session first.')
        file=filedialog.asksaveasfilename(defaultextension='.json',initialfile='WoSB-Network-Research.json',
            filetypes=[('JSON research summary','*.json')])
        if not file:return
        try:export_research(self.db.conn,self.network_sid,file);self._notice('Export complete','Redacted research saved: '+file)
        except Exception as exc:self._error('Export failed',exc)

    def _network_wiki(self):
        if not self.network_sid:return self._notice('Research','Select a session first.')
        summary=get_summary(self.db.conn,self.network_sid)
        events=[dict(x) for x in self.db.conn.execute('SELECT event_utc,category,note FROM network_events WHERE session_id=?',(self.network_sid,))]
        body='# Network research: '+summary['label']+'\n\n**Evidence status:** traffic timing/size only; gameplay interpretations unverified.\n\n'
        body+='## Transport observations\n\n'+json.dumps(summary['protocols'],indent=2)+'\n\n'
        body+='## Candidate message classification\n\n'+json.dumps(summary['classifications'],indent=2)+'\n\n'
        body+='## Controlled trial markers\n\n'
        for e in event_correlations(summary,events):body+=f"- {e['event_utc']} — {e['category']}: {e['note']} ({e['packets']} packets nearby; not causal proof)\n"
        body+='\n## Further work\n\n- Confirm which flows belong to the game process.\n- Correlate with client protocol code and repeat controlled experiments.\n- Do not infer encrypted payload contents.\n'
        slug='network-'+slugify(self.network_sid)
        aid=self.db.upsert_article(slug,'Network research: '+summary['label'],'Networking and protocols',body,
            'pcap-metadata',self.network_sid,'needs-review',preserve_edited=True)
        self.db.conn.commit();self.refresh_articles();self.tabs.select_named('Wiki editor');self._select_article(aid)

    def _updates(self,parent):
        self._heading(parent,'Version and updates','Updates come from the project\'s GitHub Releases. Nothing installs without your confirmation; your wiki and data are never touched.')
        ttk.Label(parent,text='Installed version: '+VERSION+('' if getattr(sys,'frozen',False) else '  (running from source)'),style='Section.TLabel').pack(anchor='w',pady=8)
        gh=ttk.LabelFrame(parent,text='GitHub Releases',padding=12);gh.pack(fill='x',pady=(4,12))
        row=ttk.Frame(gh);row.pack(fill='x')
        ttk.Label(row,text='Repository').pack(side='left')
        self.gh_repo=tk.StringVar(value=self.settings.get('updates.github_repo','ajtchess-code/wosbworkbench'))
        ttk.Entry(row,textvariable=self.gh_repo,width=40).pack(side='left',padx=8)
        ttk.Label(row,text='Access token (private repo only)').pack(side='left',padx=(14,6))
        import secret_store
        self.gh_token=tk.StringVar(value='••••••••' if secret_store.exists('github_token') else '')
        ttk.Entry(row,textvariable=self.gh_token,width=28,show='•').pack(side='left')
        ttk.Button(row,text='Save',style='Small.TButton',command=self._github_save).pack(side='left',padx=8)
        opts=ttk.Frame(gh);opts.pack(fill='x',pady=(8,0))
        self.gh_startup=tk.BooleanVar(value=bool(self.settings.get('updates.check_on_startup',True)))
        self.gh_pre=tk.BooleanVar(value=bool(self.settings.get('updates.include_prerelease',False)))
        ttk.Checkbutton(opts,text='Check for updates when Workbench starts',variable=self.gh_startup,
                        command=lambda:self.settings.set('updates.check_on_startup',bool(self.gh_startup.get()))).pack(side='left')
        ttk.Checkbutton(opts,text='Include pre-releases',variable=self.gh_pre,
                        command=lambda:self.settings.set('updates.include_prerelease',bool(self.gh_pre.get()))).pack(side='left',padx=16)
        actions=ttk.Frame(gh);actions.pack(fill='x',pady=(10,0))
        ttk.Button(actions,text='Check GitHub now',style='Accent.TButton',command=lambda:self._github_check(silent=False)).pack(side='left')
        self.gh_install=ttk.Button(actions,text='Download and install update',state='disabled',command=self._github_install)
        self.gh_install.pack(side='left',padx=8)
        self.gh_setup=ttk.Button(actions,text='Download full installer',state='disabled',command=lambda:self._github_download('setup'))
        self.gh_setup.pack(side='left')
        self.gh_page=ttk.Button(actions,text='Open release page',state='disabled',command=lambda:webbrowser.open(self._gh_release['html_url']))
        self.gh_page.pack(side='left',padx=8)
        self.gh_status=tk.StringVar(value='Not checked yet.')
        ttk.Label(gh,textvariable=self.gh_status,wraplength=980,justify='left').pack(anchor='w',pady=(10,0))
        self._gh_release=None
        ttk.Label(parent,text='Advanced: custom release manifest URL',style='Muted.TLabel').pack(anchor='w',pady=(4,0))
        ttk.Label(parent,text='HTTPS update manifest URL (from your own future release host):').pack(anchor='w',pady=(12,5))
        self.feed_url=tk.StringVar(value=self.db.setting('update_manifest',''))
        ttk.Entry(parent,textvariable=self.feed_url,width=110).pack(anchor='w',fill='x',pady=(0,10))
        row=ttk.Frame(parent);row.pack(anchor='w',fill='x',pady=6)
        ttk.Button(row,text='Save update URL',command=self._save_feed).pack(side='left')
        ttk.Button(row,text='Check for updates',style='Accent.TButton',command=self._check_updates).pack(side='left',padx=9)
        self.download_button=ttk.Button(row,text='Download verified installer',state='disabled',command=self._download_update)
        self.download_button.pack(side='left',padx=9)
        self.install_button=ttk.Button(row,text='Open downloaded installer',state='disabled',command=self._run_installer)
        self.install_button.pack(side='left',padx=9)
        self.update_label=tk.StringVar(value='No release URL configured. The app works offline without one.')
        ttk.Label(parent,textvariable=self.update_label,wraplength=1000).pack(anchor='w',pady=15)
        ttk.Label(parent,text='Online installer updates require an HTTPS release manifest and a SHA-256 verified installer.',style='Muted.TLabel',wraplength=980).pack(anchor='w',pady=(15,10))
        ttk.Separator(parent,orient='horizontal').pack(fill='x',pady=(12,14))
        ttk.Label(parent,text='Offline ZIP updates',style='Section.TLabel').pack(anchor='w',pady=(0,7))
        ttk.Label(parent,text='Use a trusted WoSBWorkbench-x.y.z-Update.zip file. The updater checks every file hash, backs up replaced program files, closes the application, applies the patch, and restarts it.',style='Muted.TLabel',wraplength=970).pack(anchor='w',pady=(0,12))
        offline_row=ttk.Frame(parent);offline_row.pack(anchor='w',fill='x',pady=6)
        ttk.Button(offline_row,text='Choose update ZIP…',command=self._choose_offline_update,style='Accent.TButton').pack(side='left')
        self.offline_apply_button=ttk.Button(offline_row,text='Apply selected ZIP update',state='disabled',command=self._apply_offline_update)
        self.offline_apply_button.pack(side='left',padx=10)
        self.offline_label=tk.StringVar(value='No offline update selected. Your wiki database and reports are stored outside the program folder.')
        ttk.Label(parent,textvariable=self.offline_label,wraplength=980).pack(anchor='w',pady=8)
        ttk.Label(parent,text='Only install ZIP files from a source you trust. ZIP updates replace program files, not your local wiki data. For Windows installed-app metadata, the full installer remains available.',style='Muted.TLabel',wraplength=1000).pack(anchor='w',pady=(10,0))

    # ---------------------------------------------------------- GitHub updates
    def _github_token(self):
        import secret_store
        return secret_store.load('github_token') or None

    def _github_save(self):
        import secret_store
        repo=self.gh_repo.get().strip()
        try:
            import github_updates
            github_updates._check_repo(repo)
        except Exception as exc:return self._error('Repository',exc)
        self.settings.set('updates.github_repo',repo)
        token=self.gh_token.get().strip()
        if token and set(token)!={'•'}:
            secret_store.save('github_token',token);self.gh_token.set('••••••••')
        elif not token:
            secret_store.save('github_token','')
        self._notice('Update settings saved','Repository '+repo+(' · token stored encrypted for this Windows user' if self._github_token() else ''),kind='success')

    def _github_check(self,*,silent=False):
        repo=self.settings.get('updates.github_repo','ajtchess-code/wosbworkbench')
        token=self._github_token();pre=bool(self.settings.get('updates.include_prerelease',False))
        def task():
            import github_updates
            return github_updates.check(VERSION,repo,token=token,include_prerelease=pre)
        def done(info):
            self._gh_release=info
            self.settings.set('updates.last_check_utc',__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(timespec='seconds'))
            if hasattr(self,'gh_page'):self.gh_page.configure(state='normal')
            if info['update_available']:
                text=f"Version {info['version']} is available (you have {VERSION}). Published {str(info.get('published') or '')[:10]}."
                if hasattr(self,'gh_status'):
                    self.gh_status.set(text+'\n\n'+info['notes'][:1500])
                    self.gh_install.configure(state='normal' if getattr(sys,'frozen',False) else 'disabled')
                    self.gh_setup.configure(state='normal')
                if not (silent and self.settings.get('updates.skipped_version')==info['version']):
                    self._notice('Update available',text,kind='info',action=('Install',self._github_install_from_toast))
            else:
                if hasattr(self,'gh_status'):self.gh_status.set(f"You have the latest version ({VERSION}). Latest release: {info['version']}.")
                if not silent:self._notice('Up to date',f'WoSB Workbench {VERSION} is the latest release.',kind='success')
        def failed(message):
            if hasattr(self,'gh_status'):self.gh_status.set('Update check failed: '+message)
            if not silent:self._error('Update check',message)
        job=self.jobs.submit('Check GitHub for updates',lambda ctx:task(),
            on_done=lambda r:self.status_events.put(('finished',done,r)),
            on_error=lambda j:self.status_events.put(('finished',failed,j.error)))
        return job

    def _github_install_from_toast(self):
        self.tabs.select_named('Updates');self._github_install()

    def _github_download(self,kind,then=None):
        info=self._gh_release
        if not info:return self._notice('Updates','Check GitHub first.')
        token=self._github_token();folder=home()/'Updates'/'GitHub'
        def task(ctx):
            import github_updates
            def progress(n,total):
                ctx.progress((n/total) if total else None,f'Downloaded {n//1048576} MB'+(f' of {total//1048576} MB' if total else ''))
            result=github_updates.download(info,kind,folder,token=token,progress=progress)
            ctx.set_output(result['path'])
            return result
        def done(result):
            if then:return then(result)
            self._notice('Installer downloaded',('Signed and ' if result['signed'] else '')+'SHA-256 verified: '+result['path'],kind='success',
                         action=('Run installer',lambda:os.startfile(result['path']) if os.name=='nt' else None))
        self._run_async(task,done,'Downloading '+kind+' from GitHub…',name='Download '+info['version']+' '+kind)

    def _github_install(self):
        info=self._gh_release
        if not info:return self._github_check(silent=False)
        if not getattr(sys,'frozen',False):
            return self._notice('Running from source','In-app installs apply to the installed app. Download the full installer, or pull the new source from GitHub.',kind='warning')
        def apply(result):
            from update_signing import bundled_public_key
            key=bundled_public_key();require=bool(key) and bool(self.settings.get('updates.require_signature',True))
            try:
                update=inspect_update_zip(result['path'],VERSION,public_key=key,require_signature=require)
            except Exception as exc:return self._error('Update verification',exc)
            self.offline_update_path=Path(result['path']);self.offline_update_info=update
            self._apply_offline_update()
        self._github_download('update',then=apply)

    def _choose_offline_update(self):
        if self.running:
            return self._notice('Update blocked','Stop the current client scans before preparing a ZIP update.')
        path=filedialog.askopenfilename(title='Select trusted WoSB Workbench ZIP update',filetypes=[('WoSB updates','*.zip')])
        if not path:return
        self.offline_apply_button.configure(state='disabled')
        self.offline_label.set('Inspecting patch manifest, version, and all file hashes…')
        def done(info):
            self.offline_update_path=Path(path)
            self.offline_update_info=info
            self.offline_label.set(('Signed' if info.signed else 'UNSIGNED')+' update '+info.version+' · '+str(len(info.files))+' program files · '
                                   +str(round(info.size/1048576,1))+' MB uncompressed'+(f' · removes {len(info.remove)} stale files' if info.remove else '')
                                   +'. '+info.description+('' if info.signed else '  (This build has no publisher key; only install packages you built yourself.)'))
            self.offline_apply_button.configure(state='normal')
        from update_signing import bundled_public_key
        key=bundled_public_key();require=bool(key) and bool(self.settings.get('updates.require_signature',True))
        self._run_async(lambda:inspect_update_zip(path,VERSION,public_key=key,require_signature=require),done,'Validating update ZIP…')

    def _apply_offline_update(self):
        if self.running:
            return self._notice('Update blocked','Stop the current client scans before applying an update.')
        package=self.offline_update_path
        info=self.offline_update_info
        if not package or not info:return
        if os.name!='nt':
            return self._notice('Windows updates','The in-app patch launcher is supported on Windows. The portable update engine can be tested separately.')
        if not messagebox.askyesno('Apply offline ZIP update',
           'Apply WoSB Workbench '+info.version+' from this locally selected ZIP?\n\n'
           'The app will close, back up replaced program files, and restart. Your wiki database and scan reports will remain intact.\n\n'
           'Use only update archives from a trusted publisher.',parent=self.root):
            return
        try:
            import datetime
            install=Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent
            updates=home()/'Updates'
            helper=updates/('Helper-'+str(os.getpid()))
            helper.mkdir(parents=True,exist_ok=False)
            if getattr(sys,'frozen',False):
                original=install/'WoSBUpdater.exe'
                if not original.is_file():
                    raise FileNotFoundError('WoSBUpdater.exe is missing. Rebuild the Windows package with the new updater helper.')
                binary=helper/'WoSBUpdater.exe'
                shutil.copy2(original,binary)
                argv=[str(binary)]
                launch='WoSBWorkbench.exe'
            else:
                for file in ('updater_main.py','offline_updates.py','update_signing.py'):
                    shutil.copy2(install/file,helper/file)
                argv=[sys.executable,str(helper/'updater_main.py')]
                launch='desktop_main.py'
            timestamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
            backup=updates/'Backups'/('v'+VERSION+'-to-v'+info.version+'-'+timestamp)
            log=updates/('update-'+timestamp+'.log')
            argv.extend(['--zip',str(package.resolve()),'--install-dir',str(install),
                         '--backup-dir',str(backup),'--current-version',VERSION,
                         '--wait-pid',str(os.getpid()),'--launch',launch,'--log',str(log)])
            from update_signing import bundled_public_key
            key=bundled_public_key()
            if key:argv.extend(['--public-key',key.hex()])
            subprocess.Popen(argv,cwd=str(helper),creationflags=getattr(subprocess,'CREATE_NEW_CONSOLE',0),close_fds=True)
            self._stop_watcher()
            self.db.close()
            self.root.destroy()
        except Exception as exc:
            self._error('Offline update',exc)

    def _schedule(self,fn):
        if self.search_timer:self.root.after_cancel(self.search_timer)
        self.search_timer=self.root.after(250,fn)

    def _browse_dir(self,variable):
        value=filedialog.askdirectory(initialdir=variable.get() if Path(variable.get()).is_dir() else str(Path.home()))
        if value:variable.set(value)

    def _open_path(self,path):
        path=Path(path);path.mkdir(parents=True,exist_ok=True)
        if os.name=='nt':os.startfile(str(path))
        else:self._notice('Folder',str(path))

    def _notice(self,title,message,*,kind='info',action=None):
        """Non-blocking toast (also kept in Activity → Notifications)."""
        if self.settings.get('ui.toasts',True):
            try:return self.toasts.show(title,message,kind=kind,action=action,seconds=9 if len(str(message))>120 else 6)
            except tk.TclError:pass
        messagebox.showinfo(title,message,parent=self.root)
    def _error(self,title,e):
        self.log.warning('%s: %s',title,e)
        self.notifications.append({'time':__import__('time').strftime('%H:%M:%S'),'title':str(title),'message':str(e),'kind':'error'})
        messagebox.showerror(title,str(e),parent=self.root)
    def _status(self,message):self.status_var.set(message)
    def _log(self,message):
        self.import_log.insert('end',message.rstrip()+'\n');self.import_log.see('end')

    def refresh_all(self):
        stats=self.db.stats();self.stat_var.set(f"{stats['records']:,} catalog records     •     {stats['articles']:,} wiki pages     •     {stats['combat_evidence']:,} combat methods")
        self.category_select['values']=['All']+[a for a,_ in self.db.categories()]
        self.refresh_records();self.refresh_articles();self.refresh_combat()
        self._refresh_sailing();self._refresh_viewer_sources();self.refresh_discovery();self._network_refresh()

    def refresh_records(self):
        for id in self.record_table.get_children():self.record_table.delete(id)
        dataset='' if self.category.get()=='All' else self.category.get()
        for r in self.db.list_records(self.record_search.get().strip(),dataset):
            self.record_table.insert('','end',iid=str(r['id']),values=(r['name'],r['dataset'],r['source_root']))

    def _show_record(self,_event=None):
        sel=self.record_table.selection()
        if not sel:return
        row=self.db.record(int(sel[0]));self.selected_record=row['id']
        self.record_info.configure(text=f"{row['dataset']} · {row['source_root']} · {row['external_id']}\nSource: {row['source_file']}")
        self.record_text.delete('1.0','end');self.record_text.insert('1.0',json.dumps(json.loads(row['raw_json']),ensure_ascii=False,indent=2))

    def _record_article(self):
        if not self.selected_record:return self._notice('Select a record','Select a catalog entry first.')
        r=self.db.record(self.selected_record)
        data=json.loads(r['raw_json'])
        name=r['name'];body='# '+name+'\n\n'+(r['description'] or 'Description pending review.')
        body+='\n\n## Extracted fields\n\n'
        for key,value in data.items():
            if key in ('EnglishDescription','EnglishName'):continue
            body+=f'- **{key}:** {str(value)[:400]}\n'
        body+='\n## Source\n\nDataset: '+r['dataset']+'\nClient: '+r['source_root']+'\nFile: '+r['source_file']
        aid=self.db.upsert_article('catalog-'+slugify(r['dataset']+'-'+r['external_id']),name,r['dataset'],body,
                                  'catalog',r['source_root']+'/'+r['source_file'],'source-only',preserve_edited=True)
        self.db.conn.commit();self.refresh_all();self.tabs.select_named('Wiki editor');self._select_article(aid)

    def refresh_articles(self):
        for id in self.article_table.get_children():self.article_table.delete(id)
        for r in self.db.list_articles(self.article_search.get().strip()):
            self.article_table.insert('','end',iid=str(r['id']),values=(r['title'],r['section'],r['review_status']))

    def _select_article(self,aid):
        if aid is None:return
        if not self.article_table.exists(str(aid)) and self.article_search.get():
            # The search filter (or the 500-row limit) can hide the article just created.
            self.article_search.set('');self.refresh_articles()
        if not self.article_table.exists(str(aid)):
            row=self.db.article(int(aid))
            if row is None:return
            self.article_table.insert('',0,iid=str(row['id']),values=(row['title'],row['section'],row['review_status']))
        self.article_table.selection_set(str(aid));self.article_table.see(str(aid));self._show_article()

    def _toggle_preview(self):
        if self._previewing:
            self.article_preview.pack_forget();self.article_body.pack(fill='both',expand=True,padx=12,pady=10)
            self.preview_button.configure(text='Preview');self._previewing=False
        else:
            ui_extras.render_markdown_to_text(self.article_preview,self.article_body.get('1.0','end-1c'),COLORS)
            self.article_body.pack_forget();self.article_preview.pack(fill='both',expand=True,padx=12,pady=10)
            self.preview_button.configure(text='Edit');self._previewing=True

    def _article_history(self):
        if not self.selected_article:return self._notice('Wiki','Select an article first.')
        aid=self.selected_article
        def restored():
            self._loaded_article=None;self.refresh_articles();self._select_article(aid)
            self._notice('Revision restored','The previous text was kept as a revision too.',kind='success')
        ui_extras.HistoryDialog(self.root,COLORS,self.db,aid,on_restored=restored).open()

    def _article_in_codex(self):
        if not self.selected_article:return self._notice('Wiki','Select an article first.')
        row=self.db.article(self.selected_article)
        if row:self._open_local_wiki('/article/'+row['slug'])

    def _autosave_draft(self):
        self._draft_timer=None
        try:
            if self._article_dirty():
                import wiki_engine
                wiki_engine.save_draft(self.db.conn,self.selected_article,self.article_title.get(),self.article_section.get(),
                                       self.article_body.get('1.0','end-1c'),self.article_review.get())
                self._status('Draft autosaved')
        except Exception as exc:self.log.warning('Draft autosave failed: %s',exc)
        self._draft_timer=self.root.after(5000,self._autosave_draft)

    def _article_dirty(self):
        if not self.selected_article or not hasattr(self,'article_body'):return False
        loaded=getattr(self,'_loaded_article',None)
        if not loaded or loaded[0]!=self.selected_article:return False
        current=(self.article_title.get(),self.article_section.get(),self.article_review.get(),
                 self.article_body.get('1.0','end-1c'))
        return current!=loaded[1]

    def _show_article(self,_event=None):
        sel=self.article_table.selection()
        if not sel:return
        if self._article_dirty() and str(self.selected_article)==sel[0]:
            return  # re-selecting the article being edited must not reload (and discard) it
        if self._article_dirty() and str(self.selected_article)!=sel[0]:
            answer=messagebox.askyesnocancel('Unsaved wiki changes',
                'Save changes to the current article before opening another one?',parent=self.root)
            if answer is None:
                # Keep the user on the article they were editing.
                self.article_table.selection_set(str(self.selected_article))
                return
            if answer:
                previous=self.selected_article
                self._save_article()
                if self._article_dirty():  # save was refused (e.g. empty title): stay put
                    self.article_table.selection_set(str(previous))
                    return
                if self.article_table.exists(sel[0]):self.article_table.selection_set(sel[0])
        row=self.db.article(int(sel[0]))
        if row is None:return
        self.selected_article=row['id']
        self.article_title.set(row['title']);self.article_section.set(row['section']);self.article_review.set(row['review_status'])
        self.article_source.configure(text='Source: '+row['source_kind']+' · '+row['source_ref'])
        self.article_body.delete('1.0','end');self.article_body.insert('1.0',row['body'])
        self._loaded_article=(row['id'],(self.article_title.get(),self.article_section.get(),
                              self.article_review.get(),self.article_body.get('1.0','end-1c')))
        if self._previewing:self._toggle_preview()
        import wiki_engine
        draft=wiki_engine.get_draft(self.db.conn,row['id'])
        if draft and draft['body']!=row['body']:
            if messagebox.askyesno('Unsaved draft found','An autosaved draft from '+draft['saved_utc']+
                                   ' differs from the saved article. Restore the draft into the editor?',parent=self.root):
                self.article_title.set(draft['title']);self.article_section.set(draft['section'])
                self.article_review.set(draft['review_status'])
                self.article_body.delete('1.0','end');self.article_body.insert('1.0',draft['body'])
            else:wiki_engine.clear_draft(self.db.conn,row['id'])
        if self._draft_timer is None:self._draft_timer=self.root.after(5000,self._autosave_draft)

    def _save_article(self):
        if not self.selected_article:return self._notice('Wiki','Select or create an article.')
        title=self.article_title.get().strip()
        if not title:return self._error('Validation','Article title cannot be empty.')
        self.db.save_article(self.selected_article,title,self.article_section.get().strip() or 'Guides',
                             self.article_body.get('1.0','end-1c'),self.article_review.get())
        self._loaded_article=None  # saved: the editor is no longer dirty
        self.refresh_all();self._select_article(self.selected_article);self._status('Wiki article saved locally')

    def _new_article(self):
        aid=self.db.new_article('Untitled article');self.refresh_all();self._select_article(aid)

    def refresh_combat(self):
        for id in self.combat_table.get_children():self.combat_table.delete(id)
        for row in self.db.list_combat(self.combat_search.get().strip()):
            self.combat_table.insert('','end',iid=str(row['id']),values=(row['full_name'],row['topics'][:65],row['source_root']))

    def _show_combat(self,_event=None):
        sel=self.combat_table.selection()
        if not sel:return
        r=self.db.combat(int(sel[0]));self.selected_combat=r['id']
        self.combat_info.configure(text=f"UNVERIFIED METHOD CANDIDATE · {r['assembly']} · {r['token']} · {r['source_root']}")
        self.combat_text.delete('1.0','end');self.combat_text.insert('1.0',json.dumps(json.loads(r['evidence_json']),ensure_ascii=False,indent=2))

    def _combat_article(self):
        if not self.selected_combat:return self._notice('Combat','Select a method first.')
        r=self.db.combat(self.selected_combat)
        title=r['full_name'];body='# '+title+'\n\n**Status: unverified static candidate**\n\n'
        body+='## Investigate\n\n- Confirm calling context and input parameters.\n- Trace branches, arithmetic, and return values.\n- Determine whether live server logic differs.\n\n'
        body+='## Evidence\n\n```json\n'+r['evidence_json'][:14000]+'\n```\n\n'
        body+='Source: '+r['assembly']+' · '+r['token']+' · '+r['source_root']
        aid=self.db.upsert_article('combat-'+slugify(r['assembly']+'-'+r['token']),title,'Combat mechanics',body,'il-candidate',r['source_file'],'needs-review')
        self.db.conn.commit();self.refresh_all();self.tabs.select_named('Wiki editor');self._select_article(aid)

    def _run_async(self,task,done,desc,*,name=None):
        """Run task in the background via the job manager. A task that accepts one
        argument receives a JobContext (progress, log, cancel)."""
        import inspect
        self._status(desc)
        try:wants_ctx=len(inspect.signature(task).parameters)>=1
        except (TypeError,ValueError):wants_ctx=False
        def run(ctx):
            ctx.progress(None,desc)
            return task(ctx) if wants_ctx else task()
        return self.jobs.submit(name or desc.rstrip('…. '),run,
            on_done=lambda result:self.status_events.put(('finished',done,result)),
            on_error=lambda job:self.status_events.put(('error',job.error)))

    def _import_saved_reports(self):
        folder=home()/'Reports'
        if not folder.is_dir():return self._notice('No saved reports','No reports found at '+str(folder))
        self._run_import('catalog-folder',str(folder))

    def _import_zip(self):
        f=filedialog.askopenfilename(filetypes=[('ZIP archives','*.zip')]);
        if f:self._run_import('catalog-zip',f)

    def _import_folder(self):
        f=filedialog.askdirectory()
        if f:self._run_import('catalog-folder',f)

    def _import_wiki(self):
        f=filedialog.askopenfilename(filetypes=[('Wiki exports','*.zip *.xml *.md *.markdown *.html *.htm'),('All files','*.*')])
        if not f:f=filedialog.askdirectory(title='Select wiki export directory')
        if f:self._run_import('wiki',f)

    def _run_import(self,kind,source):
        # A separate SQLite connection avoids cross-thread connection sharing.
        include_heavy=self.all_datasets.get()
        def worker():
            separate=CatalogDB(self.db.path)
            try:
                imp=Importer(separate)
                if kind=='catalog-zip':
                    result=imp.catalog_zip(source,include_heavy,lambda x:self.status_events.put(('import-progress',x)))
                    seed_sailing_pages(separate);seed_hitbox_pages(separate)
                    build_research_articles(separate)
                    return result
                if kind=='catalog-folder':
                    result=imp.catalog_folder(source,include_heavy,lambda x:self.status_events.put(('import-progress',x)))
                    seed_sailing_pages(separate);seed_hitbox_pages(separate)
                    build_research_articles(separate)
                    return result
                if kind=='wiki':
                    return {'wiki_pages':imp.import_wiki(source)}
                raise ValueError('Unknown importer')
            finally:separate.close()
        self._run_async(worker,lambda result:(self.refresh_all(),self._log(f'Imported {source}: {result}')),f'Importing {source}')

    def _export_wiki(self):
        path=filedialog.askdirectory(title='Export HTML wiki to folder')
        if path:
            try:out=self.db.export_wiki(path);self._notice('Wiki exported','Open '+str(out))
            except Exception as exc:self._error('Export',exc)

    def _export_json(self):
        path=filedialog.asksaveasfilename(defaultextension='.json',filetypes=[('JSON','*.json')]);
        if path:
            try:self.db.export_json(path,include_raw=True);self._notice('Exported',path)
            except Exception as e:self._error('Export',e)

    def _export_csv(self):
        path=filedialog.askdirectory(title='Folder for CSV exports')
        if path:
            try:self.db.export_csv(path);self._notice('CSV exported',path)
            except Exception as e:self._error('Export',e)

    def _backup(self):
        path=filedialog.asksaveasfilename(defaultextension='.sqlite3',filetypes=[('SQLite database','*.sqlite3')]);
        if path:
            try:self.db.backup(path);self._notice('Database backup',path)
            except Exception as e:self._error('Backup',e)

    def start_scan(self):
        if self.running:return
        import install_detect
        paths=[v.get().strip() for v,check in zip(self.path_vars,self.path_checks) if check.get() and v.get().strip()]
        own=[p for p in paths if install_detect.is_workbench_dir(p)]
        paths=[p for p in paths if p not in own]
        if own:self._notice('Skipped a folder',own[0]+' is WoSB Workbench itself, not the game.',kind='warning')
        if not paths:return self._notice('Scans','Select at least one folder.')
        if not any(Path(p).is_dir() for p in paths):return self._notice('Scans','No selected folders exist on this computer.')
        self.running=True;self.cancel_event=threading.Event()
        self.scan_start.configure(state='disabled');self.scan_stop.configure(state='normal')
        self.scan_output=home()/'Reports';self.scan_output.mkdir(parents=True,exist_ok=True)
        self._status('Running selected client scans…')
        extra=(['--no-images'] if self.no_images.get() else [])+(['--broad'] if self.broad.get() else [])
        def worker():
            try:
                sys.path.insert(0,str(bundled_path('engine')))
                from multi_workflow import run
                result=run(self.scan_output,paths,extraction_extra=extra,
                           cancel_event=self.cancel_event)
                self.status_events.put(('scan-finished',result))
            except Exception as e:self.status_events.put(('scan-error',str(e)))
        threading.Thread(target=worker,daemon=True).start()

    def stop_scan(self):
        if self.cancel_event:self.cancel_event.set();self._status('Stopping workers and preserving completed output…')

    def _scan_progress(self):
        if not hasattr(self,'scan_output'):return
        file=self.scan_output/'CombinedStatus.json'
        if not file.exists():return
        try:data=json.loads(file.read_text(encoding='utf-8'))
        except (OSError,ValueError):return
        for x in self.scan_table.get_children():self.scan_table.delete(x)
        for row in data.get('targets',[]):
            self.scan_table.insert('','end',values=(row.get('label'),row.get('job'),row.get('status'),
                str(row.get('stage',''))[:75],str(row.get('detail',''))[:90]))

    def _save_feed(self):
        self.db.set_setting('update_manifest',self.feed_url.get().strip());self._status('Update feed saved')

    def _check_updates(self):
        url=self.feed_url.get().strip()
        if not url:return self._notice('Updates','Enter an HTTPS release manifest URL first.')
        self._save_feed()
        def done(info):
            self.last_manifest=info
            if version_tuple(info['version'])<=version_tuple(VERSION):
                self.update_label.set('You have the current version ('+VERSION+').')
                self.download_button.configure(state='disabled')
            else:
                self.update_label.set('Version '+info['version']+' available. '+str(info.get('notes',''))[:500])
                self.download_button.configure(state='normal')
        self._run_async(lambda:fetch_manifest(url),done,'Checking update feed…')

    def _download_update(self):
        if not self.last_manifest:return
        self.update_label.set('Downloading and verifying SHA-256…')
        def done(path):
            self.downloaded_installer=path
            self.update_label.set('Verified installer downloaded: '+str(path)+' · Review the publisher before executing.')
            self.install_button.configure(state='normal')
        self._run_async(lambda:download_verified(self.last_manifest,lambda now,total:self.status_events.put(('download-progress',(now,total)))),done,'Downloading verified installer…')

    def _run_installer(self):
        if not self.downloaded_installer or not self.downloaded_installer.is_file():return
        if os.name!='nt':return self._notice('Windows only','Installer runs on Windows.')
        if messagebox.askyesno('Launch installer','Run the downloaded update installer? Save your wiki changes first; you may need to close the Workbench to complete the update.',parent=self.root):
            os.startfile(str(self.downloaded_installer))

    def _poll_events(self):
        try:self._drain_events()
        except Exception as exc:  # never let one bad event stop the poll loop
            try:self._status('Background event error: '+str(exc)[:200])
            except Exception:pass
        finally:
            self.root.after(900,self._poll_events)

    def _drain_events(self):
        for _ in range(200):  # bounded so a flood of progress events can't block Tk
            try:event=self.status_events.get_nowait()
            except queue.Empty:break
            typ=event[0]
            if typ=='game-hotkey':
                if event[1]=='sync-flash':self._gameplay_sync_flash()
                else:self._gameplay_mark(event[1])
            elif typ=='error':self._error('Operation failed',event[1]);self._status('Operation failed; data remains intact')
            elif typ=='finished':
                try:event[1](event[2]);self._status('Operation completed')
                except Exception as e:self._error('Processing result',e)
            elif typ=='import-progress':self._status(event[1])
            elif typ=='scan-finished':
                self.running=False;self.scan_start.configure(state='normal');self.scan_stop.configure(state='disabled')
                self._status('Scan finished · '+('all successful' if event[1]==0 else 'some scans failed/cancelled; see reports'))
            elif typ=='full-finished':
                self.full_running=False;self.full_start.configure(state='normal');self.full_stop.configure(state='disabled')
                self._poll_full_recovery();self._status('Full Recovery: '+event[1]+' · See recovery reports')
                self._notice('Full Recovery', 'Recovery '+event[1]+'. Open its folder to review decode outcomes and source evidence.',
                             kind='success',action=('Open folder',self._open_full_recovery))
                root=getattr(self,'_full_recovery_root',None);self._full_recovery_root=None
                if root and 'fail' not in str(event[1]).lower() and 'cancel' not in str(event[1]).lower():
                    self._after_full_recovery(root)
            elif typ=='full-error':
                self.full_running=False;self.full_start.configure(state='normal');self.full_stop.configure(state='disabled')
                self._error('Full Recovery',event[1])
            elif typ=='scan-error':
                self.running=False;self.scan_start.configure(state='normal');self.scan_stop.configure(state='disabled');self._error('Scan',event[1])
            elif typ=='watcher':self._watcher_event(event[1],event[2])
            elif typ=='toast':self._notice(*event[1:])
            elif typ=='download-progress':
                n,total=event[1];self.update_label.set('Downloaded '+str(n//1048576)+' MB'+(' / '+str(total//1048576)+' MB' if total else ''))
        if self.gameplay_session and self.gameplay_session.started and not getattr(self,'_gameplay_stopping',False):
            proc=self.gameplay_session.proc_video
            pcap_proc=self.gameplay_session.proc_capture
            if (proc and proc.poll() is not None) or (pcap_proc and pcap_proc.poll() is not None):
                self._gameplay_stop()
                self.gameplay_status.set('Recording tool exited early. See FFmpeg/TShark logs in the session folder.')
        if self.running:self._scan_progress()
        if getattr(self,'full_running',False):self._poll_full_recovery()
        active=self.jobs.active()
        self.jobs_var.set(f'⟳ {len(active)} running: '+active[0].name[:40]+(f' ({active[0].progress*100:.0f}%)' if active[0].progress else '') if active else '')
        self.activity_button.configure(text=f'Activity ({len(active)})' if active else 'Activity')

    def _close(self):
        if self.gameplay_session and self.gameplay_session.started:
            if not messagebox.askyesno('Gameplay recording running','Stop video and packet recording before closing?',parent=self.root):return
            if self.gameplay_hotkeys:self.gameplay_hotkeys.stop();self.gameplay_hotkeys=None
            self.gameplay_session.stop()
        if self.network_proc and self.network_proc.poll() is None:
            if not messagebox.askyesno('Packet capture running','Stop passive capture and close?',parent=self.root):return
            self._network_stop_capture()
        if getattr(self,'full_running',False):
            if not messagebox.askyesno('Recovery running','Stop full recovery at the next checkpoint and close later?',parent=self.root):return
            self._stop_full_recovery()
            return
        if self.running:
            if not messagebox.askyesno('Scan running','Stop active scans and close? Completed report files will be preserved.',parent=self.root):return
            self.stop_scan()
            self._notice('Scans stopping','The scans are stopping. Close the window after workers have exited.')
            return
        if self._article_dirty():
            answer=messagebox.askyesnocancel('Unsaved wiki changes','Save the article you are editing before closing?',parent=self.root)
            if answer is None:return
            if answer:self._save_article()
        try:self.settings.set('ui.geometry',self.root.geometry())
        except Exception:pass
        if self.watcher is not None:
            try:self.watcher.stop_background(finish=True)
            except Exception as exc:self.log.warning('Watcher stop failed: %s',exc)
        if self.jobs.active() and not messagebox.askyesno('Background jobs running',
                f'{len(self.jobs.active())} background job(s) are still running. Close anyway?',parent=self.root):return
        server=getattr(self,'_wiki_http_server',None)
        if server is not None:
            server.shutdown();server.server_close()
        self.log.info('Workbench closed normally')
        self.db.close();self.root.destroy()

def run():
    applog.setup_logging()
    applog.enable_dpi_awareness()          # before Tk() so text is crisp on scaled displays
    _mutex,already=applog.acquire_single_instance()
    root=tk.Tk()
    applog.apply_tk_scaling(root)
    try:
        icon=bundled_path('assets/wosb-workbench.png')
        if icon.is_file():
            root._icon_image=tk.PhotoImage(file=str(icon));root.iconphoto(True,root._icon_image)
        ico=bundled_path('assets/wosb-workbench.ico')
        if os.name=='nt' and ico.is_file():root.iconbitmap(default=str(ico))
    except tk.TclError:pass
    applog.install_crash_handlers(root,show_dialog=lambda title,text,path:ui_extras.show_error_dialog(root,COLORS,title,text,path))
    if already and not messagebox.askyesno('WoSB Workbench is already running',
            'Another Workbench window is open. Opening a second one can cause database lock warnings. Open anyway?'):
        root.destroy();return
    app=App(root)
    app._apply_settings_to_pages()
    root.mainloop()
