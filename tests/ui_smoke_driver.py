"""Headless UI smoke driver (run by tests/test_v436_platform.py in a subprocess)."""
import os, sys, json, tempfile, time
root_dir = sys.argv[1]
os.environ['WOSB_WORKBENCH_HOME'] = tempfile.mkdtemp()
sys.path[:0] = [root_dir, root_dir + '/tests', root_dir + '/engine']
import fake_tk; fake_tk.install()
import workbench_ui as w
import tkinter as tk
root = tk.Tk()
app = w.App(root)
app._apply_settings_to_pages()
print('App constructed; pages:', [t for _, t in app.tabs.pages])
for _, title in app.tabs.pages:
    app.tabs.select_named(title)
app._refresh_dashboard()
print('dashboard:', {k: v[0].get() for k, v in app.dash_vars.items()})
app._notice('Hello', 'world', kind='success', action=('Do', lambda: None))
app.activity.open(); app.activity._refresh()
app._open_search()
gs = None
# drive search directly
import ui_extras
s = ui_extras.GlobalSearch(root, w.COLORS, app.db, open_article=lambda a: None, open_record=lambda r: None, open_combat=lambda c: None)
s.open(); s.query.set('ship'); s._run(); print('search results:', len(s.items))
ui_extras.SetupWizard(root, w.COLORS, app.settings).open()
ui_extras.ResultViewer(root, w.COLORS, {'rows': [{'a': 1, 'b': 'x'}, {'a': 2, 'b': 'y'}], 'n': {'k': [1, 2]}}, title='T').open()
# wiki editor flows
aid = app.db.new_article('Smoke test'); app.refresh_all(); app._select_article(aid)
app.article_body.delete('1.0', 'end'); app.article_body.insert('1.0', '# Hi\n**bold** [[Other]]\nTags: a')
print('dirty after edit:', app._article_dirty())
app._autosave_draft(); app._toggle_preview(); app._toggle_preview()
app._save_article(); print('dirty after save:', app._article_dirty())
app._article_history()
# message browser with a synthetic log
import test_v436_fixes_and_protocol as t, protocol_lab
work = tempfile.mkdtemp(); fr, mk = t.synthetic_session(); t.write_pcapng(work + '/s.pcapng', fr)
protocol_lab.export_message_log([work + '/s.pcapng'], work + '/s.jsonl', server_port=t.PORT)
mb = ui_extras.MessageBrowser(root, w.COLORS); mb.open(work + '/s.jsonl')
mb.types.selection_set('client:0x1'); mb._show_type(); mb._suggest()
mb.list.selection_set(mb.list.get_children()[0]); mb._show_message()
print('decoded preview:', mb.decoded.get()[:80].replace('\n', ' '))
# watcher events
app._watcher_event('capture-started', {'session': '/tmp/x', 'port': 23771})
app._watcher_event('analysis-finished', {'session': '/tmp/Auto-1', 'summary': {'messages': 5, 'types': 2, 'framing': 'f', 'report': '/tmp/r.json'}})
app._watcher_event('error', {'error': 'boom'})
# async job round trip through the poll loop
job = app._run_async(lambda ctx: ctx.progress(0.5, 'half') or 42, lambda r: print('job done ->', r), 'Smoke job')
app.jobs.wait(job, 5); app._drain_events()
app._poll_events()
app._check_setup(); time.sleep(0.5); app._drain_events()
app._dm_track_versions  # attribute exists
# auto-resolved folders: one saved install is used directly, no dialog
inst = tempfile.mkdtemp(); app.settings.update({'installs.game': inst, 'installs.steam': '', 'installs.launcher': ''})
assert app._pick_install('x') == inst, 'single install should resolve without a dialog'
inst2 = tempfile.mkdtemp(); app.settings.update({'installs.steam': inst2})
ch = ui_extras.Chooser(root, w.COLORS, 'T', 'p', [(inst, inst, 'Game'), (inst2, inst2, 'Steam')]); print('chooser default:', ch.show())
sess = w.home() / 'GameplaySessions' / 'WoSB-1'; sess.mkdir(parents=True); (sess / 'a.pcapng').write_bytes(b'')
assert app._pick_session('s') == str(sess), 'single session should resolve directly'
print('session captures:', [o[2] for o in app._session_captures()])
print('AUTOPICK OK')
app._close()
print('messagebox log:', [x[0] for x in fake_tk.sys.modules['tkinter.messagebox'].LOG][:10])
print('SMOKE OK')
