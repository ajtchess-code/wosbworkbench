"""WoSB Workbench local ZIP updates.

Standalone stdlib-only module so an external helper can patch closed .exe files.
The package format is a tightly validated file patch, not an arbitrary ZIP extraction.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

MANIFEST = 'wosb-update.json'
PREFIX = 'payload/'
MAX_FILES = 50000
MAX_ARCHIVE_BYTES = 3 * 1024**3
MAX_UNPACKED_BYTES = 6 * 1024**3
MAX_FILE_BYTES = 2 * 1024**3
MAX_MANIFEST_BYTES = 4 * 1024**2
SUPPORTED_FORMAT = 1
WINDOWS_RESERVED = re.compile(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$', re.I)


def version_tuple(version: str) -> tuple[int, ...]:
    if not re.fullmatch(r'\d+(?:\.\d+){1,3}', str(version)):
        raise ValueError('Invalid version (expected e.g. 3.2.1)')
    return tuple(map(int, str(version).split('.')))


def validate_path(value: str) -> str:
    """Check ZIP paths without ever using an unchecked archive extraction function."""
    if not isinstance(value, str) or not value or len(value) > 360:
        raise ValueError('Invalid file path')
    if '\\' in value or value.startswith('/') or ':' in value or '\x00' in value:
        raise ValueError('Absolute, drive-qualified, or backslash ZIP entry rejected')
    pieces = value.split('/')
    if any(not p or p in ('.', '..') or p.rstrip(' .') != p for p in pieces):
        raise ValueError('Unsafe path component: '+value)
    if any(WINDOWS_RESERVED.match(p) for p in pieces):
        raise ValueError('Reserved Windows filename: '+value)
    if any(any(ord(c) < 32 for c in p) for p in pieces):
        raise ValueError('Control characters not permitted in file paths')
    return value


def _sha256_stream(handle) -> str:
    digest = hashlib.sha256()
    while True:
        chunk = handle.read(1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    min_version: str
    description: str
    files: tuple[tuple[str, int, str], ...]
    archive_sha256: str
    signed: bool = False
    remove: tuple[str, ...] = ()

    @property
    def size(self):
        return sum(entry[1] for entry in self.files)


def _check_signature(data, public_key, require_signature):
    """Ed25519 over the canonical manifest (which includes every file hash)."""
    if public_key is None:
        if require_signature:
            raise ValueError('This build requires signed updates, but no publisher key is configured')
        return False  # no publisher key configured: package is not verified as signed
    import update_signing
    key = bytes.fromhex(public_key) if isinstance(public_key, str) else bytes(public_key)
    if not data.get('signature'):
        raise ValueError('Update is not signed by the publisher; refusing to install')
    if not update_signing.verify_manifest(data, key):
        raise ValueError('Update signature is invalid (wrong publisher key or modified package)')
    return True


def inspect_update_zip(zip_path: str | Path, current_version: str, *, allow_equal=False,
                       public_key=None, require_signature=False) -> UpdateInfo:
    archive = Path(zip_path).resolve(strict=True)
    if not archive.is_file() or archive.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError('Update archive missing or exceeds size limit')
    with zipfile.ZipFile(archive, 'r', allowZip64=True) as z:
        members = z.infolist()
        if len(members) > MAX_FILES + 1:
            raise ValueError('Too many update archive entries')
        all_names = set()
        for item in members:
            validate_path(item.filename)
            if item.is_dir():
                raise ValueError('Directory entries are not allowed')
            if item.filename.casefold() in all_names:
                raise ValueError('Duplicate or case-colliding archive entries')
            all_names.add(item.filename.casefold())
            mode = (item.external_attr >> 16) & 0o170000
            if mode in (stat.S_IFLNK, stat.S_IFDIR):
                raise ValueError('Symlinks and directories are not allowed')
            if item.file_size > MAX_FILE_BYTES:
                raise ValueError('Update file exceeds per-file safety limit')
        if sum(item.file_size for item in members) > MAX_UNPACKED_BYTES:
            raise ValueError('Update exceeds expanded size safety limit')
        if MANIFEST not in z.namelist():
            raise ValueError('Missing wosb-update.json')
        mf = z.getinfo(MANIFEST)
        if mf.file_size > MAX_MANIFEST_BYTES:
            raise ValueError('Manifest too large')
        data = json.loads(z.read(MANIFEST).decode('utf-8'))
        if not isinstance(data, dict) or data.get('format') != SUPPORTED_FORMAT or data.get('type') != 'wosb-workbench-update':
            raise ValueError('Not a WoSB Workbench update')
        ver = str(data.get('version', ''))
        minimum = str(data.get('min_version', ''))
        if version_tuple(ver) < version_tuple(current_version) or (not allow_equal and version_tuple(ver) == version_tuple(current_version)):
            raise ValueError('Update version must be newer than installed version')
        if version_tuple(minimum) > version_tuple(current_version):
            raise ValueError('This update requires Workbench version '+minimum+' or newer')
        rows = data.get('files')
        if not isinstance(rows, list) or not rows or len(rows) > MAX_FILES:
            raise ValueError('Missing or invalid file list')
        expected_names = {MANIFEST.casefold()}
        verified = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError('Invalid file entry')
            rel = validate_path(row.get('path'))
            if rel.casefold() in {'wosb-update.json', 'workbench.sqlite3'} or rel.casefold().startswith(('data/','reports/','updates/')):
                raise ValueError('Update would overwrite protected app data')
            name = PREFIX + rel
            if name.casefold() in expected_names:
                raise ValueError('Duplicate file manifest entries')
            expected_names.add(name.casefold())
            size = row.get('size')
            sha = row.get('sha256')
            if not isinstance(size, int) or isinstance(size, bool) or size < 0 or size > MAX_FILE_BYTES:
                raise ValueError('Invalid file size')
            if not isinstance(sha, str) or not re.fullmatch(r'[a-fA-F0-9]{64}', sha):
                raise ValueError('Invalid SHA-256 digest')
            if name not in z.namelist() or z.getinfo(name).file_size != size:
                raise ValueError('Missing file or mismatched size: '+rel)
            with z.open(name) as stream:
                actual = _sha256_stream(stream)
            if actual.lower() != sha.lower():
                raise ValueError('SHA-256 mismatch in '+rel)
            verified.append((rel, size, sha.lower()))
        if all_names != expected_names:
            raise ValueError('Archive contains unexpected files')
        signed = _check_signature(data, public_key, require_signature)
        removals = data.get('remove') or []
        if not isinstance(removals, list) or len(removals) > MAX_FILES:
            raise ValueError('Invalid removal list')
        remove = []
        updated = {r[0].casefold() for r in verified}
        for rel in removals:
            rel = validate_path(rel)
            if rel.casefold() in {'wosb-update.json', 'workbench.sqlite3'} or rel.casefold().startswith(('data/','reports/','updates/')):
                raise ValueError('Update would remove protected app data')
            if rel.casefold() in updated:
                raise ValueError('File is both updated and removed: '+rel)
            remove.append(rel)
    with archive.open('rb') as stream:
        archive_hash = _sha256_stream(stream)
    return UpdateInfo(ver, minimum, str(data.get('notes', ''))[:1000], tuple(verified), archive_hash,
                      signed, tuple(remove))


def _reject_symlink_ancestors(install_dir: Path, rel: str):
    current = install_dir
    for part in rel.split('/'):
        current = current / part
        if current.is_symlink():
            raise ValueError('Refusing to replace path containing a symlink: '+rel)


def _replace_with_retry(source: Path, target: Path, attempts: int = 8, delay: float = 0.5):
    """os.replace with a short retry: on Windows, antivirus scanners and the
    search indexer briefly hold files that a just-exited process used."""
    import time
    for attempt in range(attempts):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)


def _copy_stream(source, target: Path):
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('wb') as output:
        shutil.copyfileobj(source, output, 1024 * 1024)


def apply_verified_update(zip_path: str | Path, install_dir: str | Path, backup_dir: str | Path,
                          current_version: str, *, require_executable=False, log=None,
                          public_key=None, require_signature=False) -> UpdateInfo:
    """Reverify, stage, backup modified files, replace; rollback changed files on error.

    Runs in an external process AFTER the GUI has exited. Keeps unrelated files.
    """
    root = Path(install_dir).resolve(strict=True)
    if not root.is_dir():
        raise ValueError('Not an installed Workbench directory')
    if not ((root/'WoSBWorkbench.exe').is_file() or (root/'desktop_main.py').is_file()):
        raise ValueError('Selected directory does not contain WoSB Workbench')
    if require_executable and not (root/'WoSBWorkbench.exe').is_file():
        raise ValueError('Windows executable not found')
    backup = Path(backup_dir).resolve()
    if backup == root or root in backup.parents or backup in root.parents:
        raise ValueError('Backup directory must be separate from application files')
    if backup.exists():
        raise ValueError('Backup directory already exists; refusing to overwrite')
    info = inspect_update_zip(zip_path, current_version, public_key=public_key,
                              require_signature=require_signature)
    for rel, _, _ in info.files:
        _reject_symlink_ancestors(root, rel)
    for rel in info.remove:
        _reject_symlink_ancestors(root, rel)
    # The stage directory must reside outside the install tree.
    with tempfile.TemporaryDirectory(prefix='wosb-stage-') as tmp:
        stage = Path(tmp)
        with zipfile.ZipFile(zip_path, 'r') as archive:
            for rel, _, digest in info.files:
                target = stage.joinpath(*rel.split('/'))
                with archive.open(PREFIX + rel) as source:
                    _copy_stream(source, target)
                with target.open('rb') as stream:
                    if _sha256_stream(stream) != digest:
                        raise ValueError('Staged file validation failed: '+rel)
        backup.mkdir(parents=True)
        originally = {}
        for rel, _, _ in info.files:
            target = root.joinpath(*rel.split('/'))
            if target.exists() and not target.is_file():
                raise ValueError('Destination is not a file: '+rel)
            originally[rel] = target.is_file()
            if target.is_file():
                out = backup/'original'/Path(*rel.split('/'))
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, out)
        removed_present = []
        for rel in info.remove:
            target = root.joinpath(*rel.split('/'))
            if target.is_file():
                out = backup/'original'/Path(*rel.split('/'))
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, out)
                removed_present.append(rel)
        (backup/'backup-manifest.json').write_text(json.dumps({'removed':removed_present,
            'from_version':current_version,'to_version':info.version,
            'archive_sha256':info.archive_sha256,'files':originally,
            'timestamp':datetime.now(timezone.utc).isoformat()
        },indent=2),encoding='utf-8')
        changed = [];deleted = []
        try:
            for rel, _, _ in info.files:
                target = root.joinpath(*rel.split('/'))
                _reject_symlink_ancestors(root, rel)
                target.parent.mkdir(parents=True,exist_ok=True)
                tempfile_target = target.parent/(target.name+'.wosb-new')
                if tempfile_target.exists():
                    raise ValueError('Stale staged application file: '+str(tempfile_target))
                shutil.copy2(stage.joinpath(*rel.split('/')), tempfile_target)
                try:
                    _replace_with_retry(tempfile_target, target)
                finally:
                    if tempfile_target.exists():tempfile_target.unlink()
                changed.append(rel)
                if log:log('Updated '+rel)
            # Files the new build no longer ships (stale PyInstaller libraries can
            # break the frozen app). They were backed up above.
            for rel in removed_present:
                root.joinpath(*rel.split('/')).unlink()
                deleted.append(rel)
                if log:log('Removed stale '+rel)
        except Exception as original:
            errors=[]
            for rel in reversed(deleted):
                try:shutil.copy2(backup/'original'/Path(*rel.split('/')), root.joinpath(*rel.split('/')))
                except Exception as exc:errors.append(f'{rel}: {exc}')
            for rel in reversed(changed):
                target=root.joinpath(*rel.split('/'))
                try:
                    if originally[rel]:
                        shutil.copy2(backup/'original'/Path(*rel.split('/')), target)
                    else:
                        target.unlink(missing_ok=True)
                except Exception as exc:
                    errors.append(f'{rel}: {exc}')
            if errors:
                raise RuntimeError('Update failed and rollback also failed: '+'; '.join(errors)) from original
            raise
    return info
