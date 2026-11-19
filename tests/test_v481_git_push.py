import shutil
import subprocess

import pytest

import git_push


def _site(tmp_path):
    s = tmp_path / 'site'
    (s / 'a' / 'b').mkdir(parents=True); (s / 'a-b').mkdir(); (s / '.git').mkdir()
    (s / 'index.html').write_text('<h1>hi</h1>'); (s / 'a' / 'b' / 'c.txt').write_text('x' * 5000)
    (s / 'a-b' / 'd.bin').write_bytes(bytes(range(256)) * 40); (s / 'a.txt').write_text('sorts between a-b and a/')
    (s / '.git' / 'junk').write_text('skip me')
    return s


def test_repo_url():
    assert git_push.repo_url('https://github.com/ajtchess-code/wosbwiki') == 'https://github.com/ajtchess-code/wosbwiki.git'
    assert git_push.repo_url('git@github.com:o/r.git') == 'https://github.com/o/r.git'
    with pytest.raises(git_push.PushError):
        git_push.repo_url('not a url')


@pytest.mark.skipif(not shutil.which('git'), reason='git needed to check the pack')
def test_pack_matches_git(tmp_path):
    site = _site(tmp_path)
    objects, commit = git_push.build(site, message='m', when=1700000000)
    with open(tmp_path / 'p.pack', 'wb') as fh:
        git_push.write_pack(objects, fh)
    repo = tmp_path / 'repo'
    subprocess.run(['git', 'init', '-q', '--bare', str(repo)], check=True)
    subprocess.run(['git', '-C', str(repo), 'index-pack', '--stdin', '--strict'], input=(tmp_path / 'p.pack').read_bytes(), check=True, capture_output=True)
    subprocess.run(['git', '-C', str(repo), 'update-ref', 'refs/heads/main', commit], check=True)
    subprocess.run(['git', '-C', str(repo), 'fsck', '--strict', '--no-dangling'], check=True, capture_output=True)
    # git's own tree for the same files gives the same tree id
    work = tmp_path / 'work'; shutil.copytree(site, work, ignore=shutil.ignore_patterns('.git'))
    subprocess.run(['git', 'init', '-q', str(work)], check=True); subprocess.run(['git', '-C', str(work), 'add', '-A'], check=True)
    tree = subprocess.run(['git', '-C', str(work), 'write-tree'], capture_output=True, text=True, check=True).stdout.strip()
    ours = subprocess.run(['git', '-C', str(repo), 'rev-parse', commit + '^{tree}'], capture_output=True, text=True, check=True).stdout.strip()
    assert ours == tree
    files = subprocess.run(['git', '-C', str(repo), 'ls-tree', '-r', '--name-only', 'main'], capture_output=True, text=True).stdout.split()
    assert '.git/junk' not in files and 'a/b/c.txt' in files
