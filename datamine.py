"""Datamining helpers that close coverage gaps. All read-only on the game folder.

* coverage_report()    every file type in an install, which decoder handles it,
                       recovery-ledger outcomes and what is still undecoded
* fingerprint() / track_version() / changes_article()
                       detect client updates (Game, Steam, launcher), diff file
                       inventories between versions and write a
                       "datamined changes" wiki page
* decompile_assemblies() / build_source_index() / search_sources()
                       optional full C# decompile with ILSpy (ilspycmd) into a
                       full-text searchable index. Uses ILSpy's static
                       decompiler; no game code is executed.
* extract_wave_bank()  XACT .xwb audio banks -> WAV (PCM and MS-ADPCM written
                       with proper headers; xWMA/XMA listed for ffmpeg)
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import sqlite3
import struct
import subprocess
from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

HANDLERS = {
    '.xnb': ('XNB content', 'Full Recovery: textures, models, fonts, effects (see AssetLedger)'),
    '.wosb': ('WoSB data archive', 'Catalog extractor (Client scans / Full Recovery catalog phase)'),
    '.dll': ('.NET / native library', 'Managed IL index, protocol extractor, optional ILSpy decompile'),
    '.exe': ('Executable', 'Managed IL index / protocol extractor when .NET'),
    '.lang': ('Localization', 'Catalog extractor (English text)'),
    '.json': ('Structured data', 'Client scan structured inspector'), '.xml': ('Structured data', 'Client scan structured inspector'),
    '.txt': ('Text', 'Client scan structured inspector'), '.csv': ('Table', 'Client scan structured inspector'),
    '.ini': ('Config', 'Client scan structured inspector'), '.cfg': ('Config', 'Client scan structured inspector'),
    '.png': ('Image', 'Direct'), '.jpg': ('Image', 'Direct'), '.jpeg': ('Image', 'Direct'), '.bmp': ('Image', 'Direct'),
    '.dds': ('DDS texture', 'texture2ddecoder via XNB/texture path'), '.tga': ('Image', 'Pillow'),
    '.xwb': ('XACT wave bank', 'datamine.extract_wave_bank'), '.xsb': ('XACT sound bank', 'Indexed only (cue names)'),
    '.xgs': ('XACT settings', 'Indexed only'), '.wav': ('Audio', 'Direct'), '.ogg': ('Audio', 'Direct'),
    '.mp3': ('Audio', 'Direct'), '.fx': ('Shader source', 'Shader recovery'), '.fxo': ('Compiled shader', 'Shader recovery'),
    '.mgfx': ('MonoGame effect', 'Shader recovery'), '.ttf': ('Font', 'Direct'), '.otf': ('Font', 'Direct'),
    '.pdb': ('Debug symbols', 'Use with ILSpy for names'), '.config': ('.NET config', 'Structured inspector'),
}
SKIP_DIRS = {'$recycle.bin', '__pycache__'}


def _entropy(data):
    if not data:
        return 0.0
    counts = Counter(data); n = len(data)
    return -sum(c / n * math.log2(c / n) for c in counts.values())


def _is_managed(path):
    try:
        with open(path, 'rb') as fh:
            head = fh.read(2 * 1024 * 1024)
        return head[:2] == b'MZ' and b'BSJB' in head
    except OSError:
        return False


def coverage_report(root, *, ledger=None, file_limit=400_000):
    """Classify every file under ``root`` and point at the remaining gaps."""
    root = Path(root).resolve(strict=True)
    by_ext = defaultdict(lambda: {'files': 0, 'bytes': 0, 'magic': Counter(), 'samples': [], 'entropy': []})
    managed = native = 0; count = 0
    for current, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d.casefold() not in SKIP_DIRS]
        for name in files:
            count += 1
            if count > file_limit:
                raise ValueError('Too many files; choose the game folder, not a whole drive')
            path = Path(current) / name
            ext = path.suffix.casefold() or '(none)'
            try:
                size = path.stat().st_size
                with path.open('rb') as fh:
                    head = fh.read(4096)
            except OSError:
                continue
            row = by_ext[ext]; row['files'] += 1; row['bytes'] += size
            row['magic'][head[:4].hex()] += 1
            if len(row['samples']) < 5:
                row['samples'].append(path.relative_to(root).as_posix())
            if len(row['entropy']) < 40 and head:
                row['entropy'].append(_entropy(head))
            if ext in ('.dll', '.exe'):
                if _is_managed(path):
                    managed += 1
                else:
                    native += 1
    ledger_counts = Counter(); ledger_reasons = Counter()
    if ledger and Path(ledger).is_file():
        with Path(ledger).open(encoding='utf-8') as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                status = str(rec.get('status', 'unknown'))
                ledger_counts[status] += 1
                if status not in ('decoded', 'indexed', 'preserved', 'complete', 'ok'):
                    ledger_reasons[str(rec.get('reason') or rec.get('error_type') or rec.get('kind') or status)[:120]] += 1
    rows = []; gaps = []
    for ext, row in sorted(by_ext.items(), key=lambda kv: -kv[1]['bytes']):
        kind, handler = HANDLERS.get(ext, ('Unknown', None))
        mean_entropy = round(sum(row['entropy']) / len(row['entropy']), 2) if row['entropy'] else 0
        item = {'extension': ext, 'files': row['files'], 'megabytes': round(row['bytes'] / 1048576, 2),
                'kind': kind, 'handler': handler or 'NONE — not decoded yet',
                'common_magic': [m for m, _ in row['magic'].most_common(3)], 'header_entropy': mean_entropy,
                'samples': row['samples']}
        rows.append(item)
        if handler is None and row['bytes'] > 64 * 1024:
            gaps.append({'extension': ext, 'files': row['files'], 'megabytes': item['megabytes'],
                         'hint': ('high entropy: probably compressed or encrypted container — look for the loader in the client code'
                                  if mean_entropy > 7.5 else 'structured binary: inspect samples in a hex editor (ImHex) and search the decompiled client for the extension'),
                         'samples': row['samples'][:3]})
    if ledger_reasons:
        gaps.append({'extension': '.xnb', 'files': sum(ledger_reasons.values()), 'megabytes': None,
                     'hint': 'XNB assets that failed or are unsupported in the last Full Recovery',
                     'top_reasons': ledger_reasons.most_common(12)})
    if native:
        gaps.append({'extension': '.dll/.exe (native)', 'files': native, 'megabytes': None,
                     'hint': 'native binaries are not analyzed by the .NET tools; use Ghidra for these if needed'})
    return {'format': 'wosb-decode-coverage-v1', 'root': str(root), 'generated_utc': _utc(),
            'files': count, 'managed_assemblies': managed, 'native_binaries': native,
            'by_extension': rows, 'xnb_ledger': dict(ledger_counts), 'gaps': gaps}


def _utc():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


# ------------------------------------------------------------ versions

SNAPSHOT_EXTENSIONS = ('.xnb', '.dll', '.exe', '.wosb', '.lang', '.json', '.xml', '.txt', '.png', '.xwb', '.xsb', '.fx', '.fxo', '.mgfx')
KEY_FILES = ('WorldOfSeaBattleClient.exe', 'Common.dll', 'TheraEngine.dll', '_lzcommon.wosb', 'en-US.lang')


def fingerprint(root, *, max_depth=4):
    """Hash the files that change with every client build (bounded search)."""
    root = Path(root)
    found = {}
    for current, dirs, files in os.walk(root):
        depth = len(Path(current).relative_to(root).parts)
        if depth >= max_depth:
            dirs[:] = []
        for name in files:
            if name in KEY_FILES and name not in found:
                path = Path(current) / name
                digest = hashlib.sha256()
                with path.open('rb') as fh:
                    for chunk in iter(lambda: fh.read(1 << 20), b''):
                        digest.update(chunk)
                found[name] = {'path': path.relative_to(root).as_posix(), 'bytes': path.stat().st_size,
                               'sha256': digest.hexdigest()}
    combined = hashlib.sha256(json.dumps(found, sort_keys=True).encode()).hexdigest()[:16]
    return {'root': str(root), 'fingerprint': combined, 'files': found, 'taken_utc': _utc()}


def track_version(root, history_file, *, label=''):
    """Record the fingerprint; returns (is_new_version, previous, current)."""
    history_file = Path(history_file)
    try:
        history = json.loads(history_file.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        history = {}
    current = fingerprint(root); current['label'] = label
    key = str(Path(root).resolve()).casefold()
    entries = history.setdefault(key, [])
    previous = entries[-1] if entries else None
    is_new = previous is None or previous['fingerprint'] != current['fingerprint']
    if is_new:
        try:
            from advanced_assets import inventory_tree
            snap_dir = history_file.parent / 'ClientSnapshots'; snap_dir.mkdir(parents=True, exist_ok=True)
            snap = snap_dir / f'{hashlib.sha1(key.encode()).hexdigest()[:8]}-{current["fingerprint"]}.json'
            snap.write_text(json.dumps(inventory_tree(root, extensions=SNAPSHOT_EXTENSIONS), indent=1), encoding='utf-8')
            current['inventory'] = str(snap)
        except Exception as exc:
            current['inventory_error'] = f'{type(exc).__name__}: {exc}'
        entries.append(current)
        history_file.parent.mkdir(parents=True, exist_ok=True)
        history_file.write_text(json.dumps(history, indent=2), encoding='utf-8')
    return is_new, previous, current


def changes_article(previous, current):
    """Markdown wiki page describing what changed between two client fingerprints."""
    lines = [f'# Datamined client changes — {current.get("label") or Path(current["root"]).name}', '',
             f'Detected {current["taken_utc"]}. Fingerprint `{previous["fingerprint"] if previous else "none"}` → `{current["fingerprint"]}`.',
             '', 'Tags: datamine, client-update', '', '## Key files', '',
             '| File | Before | After |', '|---|---|---|']
    before = (previous or {}).get('files', {})
    for name in sorted(set(before) | set(current['files'])):
        a = before.get(name, {}); b = current['files'].get(name, {})
        if a.get('sha256') != b.get('sha256'):
            lines.append(f'| `{name}` | {a.get("bytes", "—")} B | {b.get("bytes", "—")} B |')
    if previous and previous.get('inventory') and current.get('inventory'):
        try:
            from advanced_assets import diff_inventories
            old = json.loads(Path(previous['inventory']).read_text(encoding='utf-8'))
            new = json.loads(Path(current['inventory']).read_text(encoding='utf-8'))
            diff = diff_inventories(old, new)
            lines += ['', '## Asset changes', '']
            for key in ('added', 'removed', 'changed'):
                items = diff.get(key) or []
                lines.append(f'- **{key.title()}:** {len(items)}')
                for item in list(items)[:40]:
                    lines.append(f'  - `{item if isinstance(item, str) else item.get("path", item)}`')
        except Exception as exc:
            lines += ['', f'Asset diff unavailable: {exc}']
    lines += ['', '## Next steps', '', '- Re-run **Full Recovery** and **Extract message definitions** for this build.',
              '- Use **Compare definitions** to see protocol/opcode changes.',
              '- Compare catalogs (Advanced Research → Catalog client comparison).']
    return '\n'.join(lines)


# --------------------------------------------------------- decompilation

def find_ilspycmd(configured=None):
    candidates = [configured, shutil.which('ilspycmd'),
                  str(Path.home() / '.dotnet' / 'tools' / ('ilspycmd.exe' if os.name == 'nt' else 'ilspycmd'))]
    return next((c for c in candidates if c and Path(c).is_file()), None)


def decompile_assemblies(root, out_dir, *, ilspycmd=None, include=r'.*', timeout=900, progress=None, cancel=None):
    """Decompile every managed assembly under root to a C# project per assembly."""
    exe = find_ilspycmd(ilspycmd)
    if not exe:
        raise FileNotFoundError('ilspycmd not found. Install the .NET SDK, then: dotnet tool install --global ilspycmd')
    root = Path(root).resolve(strict=True); out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    pattern = re.compile(include, re.I)
    assemblies = [p for p in sorted(root.rglob('*')) if p.suffix.casefold() in ('.dll', '.exe') and p.is_file()
                  and pattern.search(p.name) and _is_managed(p)]
    results = []
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
    for i, asm in enumerate(assemblies, 1):
        if cancel is not None and cancel.is_set():
            break
        if progress:
            progress(i / max(1, len(assemblies)), f'Decompiling {asm.name} ({i}/{len(assemblies)})')
        dest = out / re.sub(r'[^\w.-]', '_', asm.stem)
        if dest.exists():
            shutil.rmtree(dest)
        cmd = [exe, '-p', '--nested-directories', '--disable-updatecheck', '-o', str(dest), str(asm)]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, creationflags=flags)
            ok = proc.returncode == 0
            results.append({'assembly': asm.relative_to(root).as_posix(), 'ok': ok, 'output': str(dest),
                            'files': sum(1 for _ in dest.rglob('*.cs')) if dest.exists() else 0,
                            'error': '' if ok else (proc.stderr or proc.stdout)[-800:]})
        except subprocess.TimeoutExpired:
            results.append({'assembly': asm.relative_to(root).as_posix(), 'ok': False, 'error': 'timeout'})
    summary = {'format': 'wosb-decompile-v1', 'root': str(root), 'output': str(out), 'generated_utc': _utc(),
               'assemblies': results, 'tool': exe,
               'note': 'Static decompilation of your local client for research; do not redistribute the output.'}
    (out / 'Decompile-Summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    return summary


DECL = re.compile(r'^\s*(?:\[[^\]]*\]\s*)*(?:(?:public|private|protected|internal|static|sealed|abstract|partial|readonly|unsafe|override|virtual|async|extern|new)\s+)*'
                  r'(class|struct|enum|interface|record)\s+(\w+)|^\s*(?:(?:public|private|protected|internal|static|override|virtual|abstract|sealed|async|extern|unsafe|new)\s+)+[\w<>\[\],.? ]+\s+(\w+)\s*\(', re.M)


def build_source_index(source_dir, index_path=None):
    """Index decompiled .cs files (full text + type/method declarations)."""
    source_dir = Path(source_dir)
    index_path = Path(index_path or source_dir / 'Source-Index.sqlite3')
    if index_path.exists():
        index_path.unlink()
    with closing(sqlite3.connect(index_path)) as conn:
        conn.execute('CREATE TABLE files (id INTEGER PRIMARY KEY, path TEXT, lines INTEGER)')
        conn.execute('CREATE TABLE symbols (file_id INTEGER, kind TEXT, name TEXT, line INTEGER)')
        conn.execute('CREATE INDEX ix_symbols ON symbols(name)')
        try:
            conn.execute("CREATE VIRTUAL TABLE source_fts USING fts5(path, body, tokenize='unicode61')")
            fts = True
        except sqlite3.OperationalError:
            conn.execute('CREATE TABLE source_fts (path TEXT, body TEXT)'); fts = False
        files = 0; symbols = 0
        for path in sorted(source_dir.rglob('*.cs')):
            try:
                body = path.read_text(encoding='utf-8', errors='replace')
            except OSError:
                continue
            rel = path.relative_to(source_dir).as_posix()
            cur = conn.execute('INSERT INTO files(path, lines) VALUES (?,?)', (rel, body.count('\n') + 1))
            for m in DECL.finditer(body):
                kind = m.group(1) or 'method'; name = m.group(2) or m.group(3)
                if name:
                    conn.execute('INSERT INTO symbols VALUES (?,?,?,?)', (cur.lastrowid, kind, name, body.count('\n', 0, m.start()) + 1))
                    symbols += 1
            conn.execute('INSERT INTO source_fts(path, body) VALUES (?,?)', (rel, body))
            files += 1
        conn.commit()
    return {'index': str(index_path), 'files': files, 'symbols': symbols, 'full_text': fts}


def search_sources(index_path, query, *, limit=50):
    with closing(sqlite3.connect(Path(index_path).resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        out = [{'kind': k, 'name': n, 'path': p, 'line': ln} for k, n, p, ln in conn.execute(
            'SELECT s.kind, s.name, f.path, s.line FROM symbols s JOIN files f ON f.id=s.file_id '
            'WHERE s.name LIKE ? ORDER BY length(s.name) LIMIT ?', (f'%{query}%', limit))]
        try:
            words = ' '.join('"' + w + '"' for w in re.findall(r'\w+', query)[:8])
            for path, snip in conn.execute("SELECT path, snippet(source_fts, 1, '[', ']', '…', 12) FROM source_fts "
                                           'WHERE source_fts MATCH ? LIMIT ?', (words, limit)):
                out.append({'kind': 'text', 'name': snip, 'path': path, 'line': None})
        except sqlite3.OperationalError:
            pass
    return out


# ------------------------------------------------------------ audio banks

def parse_wave_bank(data):
    """Parse an XACT (XNA 4, version 43-46) wave bank header and entry table."""
    if data[:4] not in (b'WBND', b'DNBW'):
        raise ValueError('Not an XACT wave bank')
    e = '<' if data[:4] == b'WBND' else '>'
    version, header_version = struct.unpack_from(e + 'II', data, 4)
    segments = [struct.unpack_from(e + 'II', data, 12 + 8 * i) for i in range(5)]
    bank_off, _ = segments[0]; meta_off, meta_len = segments[1]; names_off, names_len = segments[3]
    wave_off, _ = segments[4]
    flags, count = struct.unpack_from(e + 'II', data, bank_off)
    name = data[bank_off + 8:bank_off + 72].split(b'\0', 1)[0].decode('ascii', 'replace')
    meta_size, name_size, alignment = struct.unpack_from(e + 'III', data, bank_off + 72)
    compact = flags & 0x00020000
    entries = []
    for i in range(count):
        base = meta_off + i * (meta_size or 24)
        if compact:
            (packed,) = struct.unpack_from(e + 'I', data, base)
            fmt = struct.unpack_from(e + 'I', data, bank_off + 84)[0]
            offset = (packed & 0x1fffff) * (alignment or 1); length = None
        else:
            _flags_dur, fmt, offset, length = struct.unpack_from(e + 'IIII', data, base)
        tag = fmt & 0x3; channels = (fmt >> 2) & 0x7; rate = (fmt >> 5) & 0x3ffff
        block = (fmt >> 23) & 0xff; bits = 16 if (fmt >> 31) & 1 else 8
        entry_name = ''
        if names_len and name_size:
            entry_name = data[names_off + i * name_size:names_off + (i + 1) * name_size].split(b'\0', 1)[0].decode('ascii', 'replace')
        entries.append({'index': i, 'name': entry_name or f'wave_{i:04d}', 'codec': ['pcm', 'xma', 'adpcm', 'wma'][tag],
                        'channels': channels, 'rate': rate, 'block_align': block, 'bits': bits,
                        'offset': wave_off + offset, 'length': length})
    # Compact entries: length runs to the next entry.
    for i, entry in enumerate(entries):
        if entry['length'] is None:
            nxt = entries[i + 1]['offset'] if i + 1 < len(entries) else len(data)
            entry['length'] = nxt - entry['offset']
    return {'name': name, 'version': version, 'header_version': header_version, 'entries': entries, 'endian': e}


def _wav_pcm(entry, payload):
    block = entry['channels'] * entry['bits'] // 8
    fmt = struct.pack('<HHIIHH', 1, entry['channels'], entry['rate'], entry['rate'] * block, block, entry['bits'])
    return b'RIFF' + struct.pack('<I', 36 + len(payload)) + b'WAVEfmt ' + struct.pack('<I', 16) + fmt + b'data' + struct.pack('<I', len(payload)) + payload


def _wav_msadpcm(entry, payload):
    channels = entry['channels']; block = (entry['block_align'] + 22) * channels
    samples_per_block = (block - 7 * channels) * 8 // (4 * channels) + 2
    coefs = [(256, 0), (512, -256), (0, 0), (192, 64), (240, 0), (460, -208), (392, -232)]
    extra = struct.pack('<HH', samples_per_block, len(coefs)) + b''.join(struct.pack('<hh', a, b) for a, b in coefs)
    fmt = struct.pack('<HHIIHHH', 2, channels, entry['rate'], entry['rate'] * block // samples_per_block, block, 4, len(extra)) + extra
    return (b'RIFF' + struct.pack('<I', 4 + 8 + len(fmt) + 8 + len(payload)) + b'WAVEfmt ' + struct.pack('<I', len(fmt)) + fmt
            + b'data' + struct.pack('<I', len(payload)) + payload)


def extract_wave_bank(path, out_dir):
    data = Path(path).read_bytes()
    bank = parse_wave_bank(data)
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    written = []; skipped = []
    for entry in bank['entries']:
        payload = data[entry['offset']:entry['offset'] + entry['length']]
        name = re.sub(r'[^\w.-]', '_', entry['name'])[:80]
        if entry['codec'] == 'pcm':
            (out / f'{name}.wav').write_bytes(_wav_pcm(entry, payload)); written.append(name)
        elif entry['codec'] == 'adpcm':
            (out / f'{name}.wav').write_bytes(_wav_msadpcm(entry, payload)); written.append(name)
        else:
            (out / f'{name}.{entry["codec"]}.raw').write_bytes(payload)
            skipped.append({'name': name, 'codec': entry['codec'], 'hint': 'raw payload saved; decode with ffmpeg if supported'})
    summary = {'bank': bank['name'], 'entries': len(bank['entries']), 'wav_written': len(written), 'other': skipped,
               'output': str(out)}
    (out / 'WaveBank-Summary.json').write_text(json.dumps({**summary, 'entries_detail': bank['entries']}, indent=2), encoding='utf-8')
    return summary
