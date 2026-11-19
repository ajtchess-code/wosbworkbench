"""WoSB Workbench entrypoint.

--worker NAME ...   frozen PyInstaller child processes (analysis / extraction / recovery)
--self-test [PATH]  import every module and check bundled resources; writes a JSON
                    report (default: %LOCALAPPDATA%\\WoSBWorkbench\\Diagnostics) and
                    exits non-zero on failure. Used by CI on the built .exe.
"""
import importlib
import json
import sys
from workbench_db import bundled_path

WORKERS = {'analyze_one', 'extract_wosb', 'full_recovery'}
SELF_TEST_MODULES = [
    'workbench_db', 'workbench_import', 'offline_updates', 'workbench_updates', 'update_signing', 'applog',
    'app_settings', 'install_detect', 'win_proc', 'github_updates', 'secret_store', 'jobs', 'theme', 'wiki_engine', 'wiki_server', 'wiki_expanded', 'wiki_next',
    'network_lab', 'protocol_lab', 'protocol_schema', 'game_watcher', 'gameplay_capture', 'datamine',
    'ship_viewer', 'model_lab', 'appearance_lab', 'gltf_export', 'discovery_center', 'research_suite',
    'advanced_network', 'advanced_assets', 'advanced_catalog', 'advanced_release', 'workbench_ui', 'ui_extras',
    'battle_sim', 'model_pack', 'combat_sim', 'ball_damage', 'damage_fit', 'wiki_site', 'wiki_publish', 'mechanics_pages',
    'mechanics_reference', 'hitbox_recovery', 'damage_model',
]
ENGINE_MODULES = ['full_recovery', 'extract_wosb', 'analyze_one', 'protocol_extract', 'xnb_geometry', 'client_metadata']
BUNDLED = ['Starter-Catalog.sqlite3', 'Research-Ballistics-Catalog.json', 'Research-Ship-Designs.json',
           'viewer/ship_viewer.html', 'viewer/battle_sim.html', 'viewer/boarding_sim.html', 'viewer/wosb_sim.js', 'viewer/hit_analysis.js', 'viewer/defenses.js', 'viewer/fire_tool.js', 'viewer/fire_infographic.png', 'wiki_site/app.js', 'wiki_site/style.css', 'assets/wosb-workbench.png', 'engine']


def self_test(dest=None):
    report = {'python': sys.version.split()[0], 'frozen': bool(getattr(sys, 'frozen', False)), 'modules': {}, 'files': {}}
    sys.path.insert(0, str(bundled_path('engine')))
    for name in SELF_TEST_MODULES + ENGINE_MODULES:
        try:
            importlib.import_module(name)
            report['modules'][name] = 'ok'
        except Exception as exc:   # report everything, then fail
            report['modules'][name] = f'{type(exc).__name__}: {exc}'
    for rel in BUNDLED:
        report['files'][rel] = bundled_path(rel).exists()
    try:
        import tempfile
        from workbench_db import CatalogDB
        with tempfile.TemporaryDirectory() as tmp:
            db = CatalogDB(tmp + '/selftest.sqlite3')
            db.upsert_article('self-test', 'Self test', 'Test', 'Hello [[World]]\nTags: test')
            import wiki_engine
            report['wiki_search'] = bool(wiki_engine.search(db.conn, 'hello'))
            db.close()
    except Exception as exc:
        report['wiki_search'] = f'{type(exc).__name__}: {exc}'
    report['ok'] = (all(v == 'ok' for v in report['modules'].values()) and all(report['files'].values())
                    and report.get('wiki_search') is True)
    if dest is None:
        from workbench_db import home
        dest = home() / 'Diagnostics' / 'Self-Test.json'
    from pathlib import Path
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    Path(dest).write_text(json.dumps(report, indent=2), encoding='utf-8')
    if sys.stdout is not None:
        print(json.dumps({'ok': report['ok'], 'report': str(dest)}))
    return 0 if report['ok'] else 1


def main():
    # GUI build: child processes (PowerShell, TShark, FFmpeg, workers) must not pop up console windows.
    import win_proc
    win_proc.hide_console_windows()
    if len(sys.argv) >= 3 and sys.argv[1] == '--worker':
        worker = sys.argv[2]
        if worker not in WORKERS:
            raise SystemExit('Unknown worker: ' + worker)
        sys.path.insert(0, str(bundled_path('engine')))
        sys.argv = [worker + '.py', *sys.argv[3:]]
        target = importlib.import_module(worker)
        target.main()
        return
    if len(sys.argv) >= 2 and sys.argv[1] == '--self-test':
        raise SystemExit(self_test(sys.argv[2] if len(sys.argv) >= 3 else None))
    from workbench_ui import run
    run()


if __name__ == '__main__':
    main()
