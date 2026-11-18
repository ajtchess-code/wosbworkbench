"""Create the publisher Ed25519 key pair for signed WoSB Workbench updates.

    py -3.13 packaging/Make-Signing-Key.py --secret C:\\Keys\\wosb-update-secret.txt

Writes the SECRET to the path you give (keep it private and backed up, never in
the repository) and the PUBLIC key to update-public-key.txt in the project root,
which the build bundles so installed apps only accept updates you signed.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from update_signing import generate_keypair  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--secret', required=True, help='Where to write the secret key (outside the repo)')
    ap.add_argument('--force', action='store_true')
    a = ap.parse_args()
    secret_path = Path(a.secret).resolve()
    project = Path(__file__).resolve().parents[1]
    if project in secret_path.parents:
        raise SystemExit('Refusing to write the secret key inside the project folder.')
    public_path = project / 'update-public-key.txt'
    if (secret_path.exists() or public_path.exists()) and not a.force:
        raise SystemExit('A key already exists. Use --force only if you intend to rotate keys '
                         '(installed apps will then reject updates signed with the old key).')
    secret, public = generate_keypair()
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    secret_path.write_text(secret.hex() + '\n', encoding='utf-8')
    public_path.write_text(public.hex() + '\n', encoding='utf-8')
    print('Secret key :', secret_path)
    print('Public key :', public_path, public.hex())
    print('Build with:  set WOSB_SIGNING_KEY=' + str(secret_path))


if __name__ == '__main__':
    main()
