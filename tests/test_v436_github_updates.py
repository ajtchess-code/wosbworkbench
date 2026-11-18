"""GitHub Releases update channel: release selection, safe downloads, manifest checks."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import github_updates as gu
import update_signing

RELEASES = [
    {'tag_name': 'v4.3.9', 'draft': False, 'prerelease': True, 'assets': [], 'name': 'beta'},
    {'tag_name': 'v4.3.8', 'draft': False, 'prerelease': False, 'html_url': 'https://github.com/x/y/releases/tag/v4.3.8',
     'body': 'Notes', 'published_at': '2026-12-01T00:00:00Z',
     'assets': [{'id': 1, 'name': 'wosb-release.json', 'url': 'https://api.github.com/repos/x/y/releases/assets/1', 'size': 10},
                {'id': 2, 'name': 'WoSBWorkbench-4.3.8-Update.zip', 'url': 'https://api.github.com/repos/x/y/releases/assets/2', 'size': 4}]},
    {'tag_name': 'v4.3.10', 'draft': True, 'prerelease': False, 'assets': []},
    {'tag_name': 'nightly', 'draft': False, 'prerelease': False, 'assets': []},
]


class ReleaseSelectionTests(unittest.TestCase):
    def test_latest_stable_skips_drafts_prereleases_and_bad_tags(self):
        with mock.patch.object(gu, '_api_json', return_value=RELEASES):
            rel = gu.latest_release('x/y')
            self.assertEqual(rel['version'], '4.3.8')
            self.assertIn('WoSBWorkbench-4.3.8-Update.zip', rel['assets'])
            self.assertEqual(gu.latest_release('x/y', include_prerelease=True)['version'], '4.3.9')
            info = gu.check('4.3.6', 'x/y')
            self.assertTrue(info['update_available'])
            self.assertFalse(gu.check('4.3.8', 'x/y')['update_available'])

    def test_repo_and_version_validation(self):
        with self.assertRaises(gu.UpdateError):
            gu.latest_release('not a repo')
        self.assertEqual(gu.version_tuple('v4.10.2'), (4, 10, 2))
        with self.assertRaises(gu.UpdateError):
            gu.version_tuple('v4.3-beta')

    def test_refuses_non_github_hosts(self):
        with self.assertRaisesRegex(gu.UpdateError, 'Refusing'):
            gu._request('https://evil.example/x')
        with self.assertRaisesRegex(gu.UpdateError, 'Refusing'):
            gu._request('http://api.github.com/x')


class FakeResponse:
    def __init__(self, status, body=b'', location=None):
        self.status = status; self._body = body; self._location = location; self._pos = 0

    def getheader(self, name, default=None):
        return {'Location': self._location, 'Content-Length': str(len(self._body))}.get(name, default)

    def read(self, n=-1):
        if n is None or n < 0:
            n = len(self._body)
        chunk = self._body[self._pos:self._pos + n]; self._pos += len(chunk)
        return chunk


class FakeConnection:
    log = []
    routes = {}

    def __init__(self, host, timeout=None, context=None):
        self.host = host

    def request(self, method, path, headers=None):
        FakeConnection.log.append((self.host, path, dict(headers or {})))
        self._resp = FakeConnection.routes[(self.host, path)]

    def getresponse(self):
        return self._resp

    def close(self):
        pass


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp, True)
        FakeConnection.log = []

    def release(self, payload, manifest):
        FakeConnection.routes = {
            ('api.github.com', '/repos/x/y/releases/assets/1'): FakeResponse(200, json.dumps(manifest).encode()),
            ('api.github.com', '/repos/x/y/releases/assets/2'): FakeResponse(302, location='https://objects.githubusercontent.com/signed?sig=abc'),
            ('objects.githubusercontent.com', '/signed?sig=abc'): FakeResponse(200, payload),
        }
        with mock.patch.object(gu, '_api_json', return_value=RELEASES):
            return gu.latest_release('x/y')

    def manifest(self, payload, **extra):
        return {'format': 'wosb-release-v1', 'version': '4.3.8', 'min_version': '3.4.0',
                'assets': [{'name': 'WoSBWorkbench-4.3.8-Update.zip', 'size': len(payload),
                            'sha256': hashlib.sha256(payload).hexdigest()}], **extra}

    def test_verified_download_and_token_never_leaves_api_host(self):
        payload = b'ZIP!'
        rel = self.release(payload, self.manifest(payload))
        with mock.patch.object(gu.http.client, 'HTTPSConnection', FakeConnection), \
             mock.patch('update_signing.bundled_public_key', return_value=None):
            result = gu.download(rel, 'update', self.tmp, token='secret-token')
        self.assertEqual(Path(result['path']).read_bytes(), payload)
        for host, path, headers in FakeConnection.log:
            if host != 'api.github.com':
                self.assertNotIn('Authorization', headers, 'token sent to ' + host)
            else:
                self.assertEqual(headers.get('Authorization'), 'Bearer secret-token')

    def test_checksum_mismatch_discards_file(self):
        rel = self.release(b'tampered', self.manifest(b'original'))
        with mock.patch.object(gu.http.client, 'HTTPSConnection', FakeConnection), \
             mock.patch('update_signing.bundled_public_key', return_value=None):
            with self.assertRaisesRegex(gu.UpdateError, 'SHA-256 mismatch'):
                gu.download(rel, 'update', self.tmp)
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_signature_required_when_key_bundled(self):
        secret, public = update_signing.generate_keypair()
        payload = b'ZIP!'
        rel = self.release(payload, self.manifest(payload))   # unsigned manifest
        with mock.patch.object(gu.http.client, 'HTTPSConnection', FakeConnection), \
             mock.patch('update_signing.bundled_public_key', return_value=public):
            with self.assertRaisesRegex(gu.UpdateError, 'signature'):
                gu.download(rel, 'update', self.tmp)
        signed = update_signing.sign_manifest(self.manifest(payload), secret)
        rel = self.release(payload, signed)
        with mock.patch.object(gu.http.client, 'HTTPSConnection', FakeConnection), \
             mock.patch('update_signing.bundled_public_key', return_value=public):
            self.assertTrue(gu.download(rel, 'update', self.tmp)['signed'])


class ToolingTests(unittest.TestCase):
    def test_release_manifest_script(self):
        tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, tmp, True)
        for suffix in ('Setup.exe', 'Update.zip', 'Portable.zip'):
            (tmp / f'WoSBWorkbench-9.9.9-{suffix}').write_bytes(suffix.encode())
        secret, public = update_signing.generate_keypair()
        key = tmp / 'k.txt'; key.write_text(secret.hex(),encoding='utf-8')
        subprocess.run([sys.executable, str(ROOT / 'packaging' / 'Make-Release-Manifest.py'), '--dist', str(tmp),
                        '--version', '9.9.9', '--sign-key', str(key)], check=True, capture_output=True)
        manifest = json.loads((tmp / 'wosb-release.json').read_text(encoding='utf-8'))
        self.assertEqual(len(manifest['assets']), 3)
        self.assertTrue(update_signing.verify_manifest(manifest, public))

    def test_secret_store_roundtrip(self):
        import secret_store
        with mock.patch.dict(os.environ, {'WOSB_WORKBENCH_HOME': tempfile.mkdtemp()}):
            secret_store.save('github_token', 'ghp_example')
            self.assertEqual(secret_store.load('github_token'), 'ghp_example')
            secret_store.save('github_token', '')
            self.assertEqual(secret_store.load('github_token'), '')

    def test_workflow_publishes_installer_on_tags(self):
        wf = (ROOT / '.github' / 'workflows' / 'build-and-release.yml').read_text(encoding='utf-8')
        for needle in ("tags: ['v*']", 'gh release create', '-Setup.exe', 'wosb-release.json', 'contents: write',
                       'does not match workbench_db.VERSION'):
            self.assertIn(needle, wf)


if __name__ == '__main__':
    unittest.main()


class ScriptEncodingTests(unittest.TestCase):
    def test_windows_scripts_are_ascii(self):
        """Windows PowerShell 5.1 and cmd read scripts as ANSI: a UTF-8 em dash in a .ps1
        becomes a stray closing quote and the build script fails to parse."""
        files = list((ROOT / 'packaging').glob('*.ps1')) + list(ROOT.glob('*.cmd')) + list((ROOT / 'packaging').glob('*.iss'))
        for path in files:
            data = path.read_bytes()
            self.assertTrue(all(b < 128 for b in data), f'{path.name} contains non-ASCII bytes')


class ConsoleWindowTests(unittest.TestCase):
    """The GUI must not flash console windows for background commands (user report)."""

    def test_children_get_create_no_window(self):
        import subprocess as sp
        import win_proc
        seen = {}
        original = sp.Popen.__init__

        def fake_init(self, *args, **kwargs):
            seen.update(kwargs)
        try:
            sp.Popen.__init__ = fake_init
            with mock.patch.object(win_proc.os, 'name', 'nt'), mock.patch.object(win_proc, '_patched', False):
                self.assertTrue(win_proc.hide_console_windows())
                sp.Popen(['powershell.exe', '-Command', 'x'])
                self.assertEqual(seen['creationflags'] & win_proc.CREATE_NO_WINDOW, win_proc.CREATE_NO_WINDOW)
                seen.clear()
                sp.Popen(['updater.exe'], creationflags=win_proc.CREATE_NEW_CONSOLE)   # explicit console kept
                self.assertEqual(seen['creationflags'], win_proc.CREATE_NEW_CONSOLE)
        finally:
            sp.Popen.__init__ = original

    def test_watcher_poll_uses_native_api_not_powershell(self):
        import gameplay_capture
        import win_proc
        native = [{'confirmed': True, 'pid': 42, 'port': 23771, 'process': 'WorldOfSeaBattleClient'}]
        with mock.patch.object(gameplay_capture.os, 'name', 'nt'), \
             mock.patch.object(win_proc, 'game_connections', return_value=native), \
             mock.patch.object(gameplay_capture.subprocess, 'run', side_effect=AssertionError('PowerShell started')):
            self.assertEqual(gameplay_capture.discover_game_ports(), native)
            self.assertTrue(gameplay_capture.game_process_connection(23771)['confirmed'])


class WindowsSharingViolationTests(unittest.TestCase):
    """User report: scan aborted with WinError 5 replacing CombinedStatus.json while the GUI read it."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp, True)
        sys.path.insert(0, str(ROOT / 'engine'))

    def test_transient_lock_is_retried(self):
        import v3_progress
        real = os.replace; calls = {'n': 0}

        def flaky(src, dst):
            calls['n'] += 1
            if calls['n'] < 3:
                raise PermissionError(5, 'Access is denied')
            return real(src, dst)
        with mock.patch.object(v3_progress.os, 'replace', flaky):
            v3_progress.atomic_json(self.tmp / 'CombinedStatus.json', {'ok': 1})
        self.assertEqual(json.loads((self.tmp / 'CombinedStatus.json').read_text(encoding='utf-8')), {'ok': 1})
        self.assertEqual(calls['n'], 3)

    def test_status_write_never_aborts(self):
        import v3_progress
        with mock.patch.object(v3_progress.os, 'replace', side_effect=PermissionError(5, 'Access is denied')), \
             mock.patch.object(v3_progress, 'replace_with_retry',
                               lambda s, d, attempts=12: (_ for _ in ()).throw(PermissionError(5, 'denied'))):
            self.assertFalse(v3_progress.status_json(self.tmp / 'CombinedStatus.json', {'ok': 1}))
        self.assertEqual(list(self.tmp.glob('*.tmp')), [])       # temp file cleaned up

    def test_app_writers_use_retry(self):
        import fsutil
        real = os.replace; calls = {'n': 0}

        def flaky(src, dst):
            calls['n'] += 1
            if calls['n'] == 1:
                raise PermissionError(32, 'in use')
            return real(src, dst)
        import app_settings
        with mock.patch.object(fsutil.os, 'replace', flaky):
            app_settings.Settings(self.tmp / 's.json').set('ui.theme', 'light')
        self.assertEqual(app_settings.Settings(self.tmp / 's.json').get('ui.theme'), 'light')


class ReportAuditLargeTreeTests(unittest.TestCase):
    def test_reports_folder_with_many_asset_files_is_accepted(self):
        import tempfile, discovery_center as dc
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'Scan1' / 'Analysis').mkdir(parents=True)
            (root / 'Scan1' / 'Analysis' / 'Summary.json').write_text('{}', encoding='utf-8')
            assets = root / 'Scan1' / 'Assets'; assets.mkdir()
            loose = root / 'Scan1' / 'Loose'; loose.mkdir()
            old = dc.MAX_REPORT_FILES; dc.MAX_REPORT_FILES = 50
            try:
                for i in range(120):
                    (assets / f'{i}.xnb').write_bytes(b'')
                    (loose / f'{i}.png').write_bytes(b'')
                src = dc.ReportSource(root)
                self.assertIn('Game/Analysis/Summary.json', src.names)
                self.assertEqual(len(src.names), 1)
            finally:
                dc.MAX_REPORT_FILES = old
