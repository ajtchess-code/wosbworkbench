"""Cut a new release: bump the version, test, commit, tag and push.

    py -3.13 packaging/New-Release.py 4.3.7            # prepare, test, commit, tag
    py -3.13 packaging/New-Release.py 4.3.7 --push     # ...and push; GitHub then builds
                                                       #    Setup.exe and publishes the release

Pushing the tag vX.Y.Z starts .github/workflows/build-and-release.yml, which builds the
installer on GitHub's Windows machines and attaches it to a new GitHub Release. Installed
apps see the release on their next update check.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*cmd):
    print('>', ' '.join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('version', help='new version, e.g. 4.3.7')
    ap.add_argument('--push', action='store_true', help='push the commit and tag to origin')
    ap.add_argument('--skip-tests', action='store_true')
    a = ap.parse_args()
    if not re.fullmatch(r'\d+(\.\d+){1,3}', a.version):
        raise SystemExit('Version must look like 4.3.7')
    db = ROOT / 'workbench_db.py'
    text = db.read_text(encoding='utf-8')
    current = re.search(r"VERSION = '([0-9.]+)'", text).group(1)
    if tuple(map(int, a.version.split('.'))) <= tuple(map(int, current.split('.'))):
        raise SystemExit(f'{a.version} must be newer than the current {current}')
    if subprocess.run(['git', 'status', '--porcelain'], cwd=ROOT, capture_output=True, text=True).stdout.strip():
        print('Note: uncommitted changes will be included in the release commit.')
    db.write_text(text.replace(f"VERSION = '{current}'", f"VERSION = '{a.version}'"), encoding='utf-8')
    notes = ROOT / f'RELEASE-NOTES-v{a.version}.md'
    if not notes.exists():
        notes.write_text(f'# WoSB Workbench v{a.version}\n\n## Changes\n\n- \n', encoding='utf-8')
        print(f'Created {notes.name} — fill in the changes (it becomes the GitHub release text).')
    # The version-consistency test pins the expected version.
    test = ROOT / 'tests' / 'test_v431_startup.py'
    t = test.read_text(encoding='utf-8')
    test.write_text(re.sub(r"self\.assertEqual\(version,'[0-9.]+'\)", f"self.assertEqual(version,'{a.version}')", t), encoding='utf-8')
    if not a.skip_tests:
        run(sys.executable, '-m', 'pytest', '-q')
    run('git', 'add', '-A')
    run('git', 'commit', '-m', f'Release {a.version}')
    run('git', 'tag', '-a', f'v{a.version}', '-m', f'WoSB Workbench {a.version}')
    if a.push:
        run('git', 'push', 'origin', 'HEAD')
        run('git', 'push', 'origin', f'v{a.version}')
        print('Pushed. Watch the build under the repository Actions tab; the release appears when it finishes.')
    else:
        print(f'Ready. Push with: git push origin HEAD && git push origin v{a.version}')


if __name__ == '__main__':
    main()
