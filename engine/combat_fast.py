#!/usr/bin/env python3
"""Bounded, resumable static .NET combat indexing for WoSB.

Never imports or executes any game assembly. Findings are *candidate* evidence.
"""
from __future__ import annotations

import csv
import gc
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from combat_research import TOPICS, STRONG, topics
from v3_progress import atomic_json

CACHE_VERSION = 3
MAX_ASSEMBLY_SIZE = 100 * 1024 * 1024


def _write_csv(path, rows, columns):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        for record in rows:
            clean = {}
            for column in columns:
                val = record.get(column, '')
                if isinstance(val, (list, dict)):
                    val = json.dumps(val, ensure_ascii=False)
                if isinstance(val, str) and val.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')):
                    val = "'" + val
                clean[column] = val
            writer.writerow(clean)


def _list_managed_candidates(game):
    from client_probe import skip_path
    return sorted(p for p in game.rglob('*') if p.is_file() and p.suffix.lower() in ('.dll', '.exe')
                  and not skip_path(p, game))


def _index_assembly(path, relative, *, max_candidates=90, max_il_bytes=131072,
                    evidence_count=8, heartbeat=None):
    from client_metadata import Metadata
    from dncil.clr.token import Token

    results = []
    issues = []
    method_count = 0
    m = None
    try:
        # Explicitly suppress legacy eager string-table decoding, which used
        # to decode arbitrary IL and cache entire method bodies before scanning.
        m = Metadata(path, prepare_strings=False)
        if not getattr(m.pe, 'net', None) or not m.pe.net.mdtables:
            return {'managed': False, 'methods_total': 0, 'candidates': [], 'issues': []}
        rows = m.pe.net.mdtables.MethodDef.rows
        method_count = len(rows)
        ranked = []
        for rid, r in enumerate(rows, 1):
            if rid % 2000 == 0 and heartbeat:
                heartbeat(relative, rid, method_count)
            if not r.Rva:
                continue
            fullname = m.owners.get(id(r), '?') + '::' + str(r.Name)
            tags = topics(fullname)
            if not tags:
                continue
            normalized = fullname.lower().replace('_', '')
            strong = any(term in normalized for term in STRONG)
            ranked.append((12 * strong + 6 * len(tags), rid, fullname, tags))
        ranked.sort(key=lambda x: (-x[0], x[1]))
        # The limit applies to IL interpretation, not discovery of method names.
        for i, (score, rid, full, tags) in enumerate(ranked[:max_candidates]):
            if heartbeat and i % 10 == 0:
                heartbeat(relative, i, min(max_candidates, len(ranked)))
            try:
                body = m.body_limited(rid, max_il_bytes=max_il_bytes)
            except Exception as e:
                issues.append({'assembly': relative, 'token': f'0x{0x06000000|rid:08x}',
                               'error_type': type(e).__name__})
                continue
            numeric = []
            related_calls = []
            related_fields = []
            signals = []
            il_lines = []
            for instruction in body:
                op = instruction.opcode.name
                operand = instruction.operand
                if i < evidence_count and len(il_lines) < 9000:
                    # Avoid raw strings, file paths, or unrelated client data in IL evidence.
                    il_lines.append(f'{instruction.offset:06x} {op} '
                                    + (str(operand)[:100] if isinstance(operand, (float, int)) else ''))
                if op.startswith('ldc.'):
                    try:
                        val = m.const(instruction)
                        if isinstance(val, (int, float)) and len(numeric) < 60:
                            numeric.append({'offset': instruction.offset, 'value': val, 'opcode': op})
                    except Exception:
                        pass
                if op in ('add', 'sub', 'mul', 'div', 'div.un', 'rem', 'ceq', 'clt', 'cgt') \
                        or op.startswith(('br', 'beq', 'bge', 'bgt', 'ble', 'blt', 'switch')):
                    if len(signals) < 100:
                        signals.append({'offset': instruction.offset, 'opcode': op,
                                        'kind': 'arithmetic' if op in ('add', 'sub', 'mul', 'div', 'div.un', 'rem', 'ceq', 'clt', 'cgt') else 'branch'})
                if isinstance(operand, Token):
                    if op in ('call', 'callvirt', 'newobj'):
                        try:
                            owner, name, _ = m.method(operand)
                            called = owner + '::' + name
                            if topics(called) and len(related_calls) < 60:
                                related_calls.append(called)
                        except Exception:
                            pass
                    if op.startswith(('ldfld', 'ldsfld', 'stfld', 'stsfld')):
                        try:
                            field = m.row(operand)
                            named = m.owners.get(id(field), '?') + '::' + str(field.Name)
                            if topics(named) and len(related_fields) < 60:
                                related_fields.append(named)
                        except Exception:
                            pass
            row = {'assembly': relative, 'token': f'0x{0x06000000|rid:08x}', 'method': full,
                   'topics': sorted(set(tags + sum((topics(x) for x in related_calls + related_fields), []))),
                   'score': score + len(related_calls) * 2 + len(related_fields),
                   'numeric_literals': numeric, 'calls_related': related_calls,
                   'fields_related': related_fields,
                   'signals': signals,
                   'evidence_status': 'Static candidate only; server behavior unverified'}
            if il_lines:
                row['il_lines'] = il_lines
            results.append(row)
    finally:
        if m is not None:
            try:
                m.pe.close()
            except Exception:
                pass
            del m
        gc.collect()
    return {'managed': True, 'methods_total': method_count, 'candidate_names': len(ranked),
            'candidates': results, 'issues': issues}


def scan_fast(game, out, *, progress=None, max_candidates_per_assembly=90,
              max_il_bytes=131072, evidence_per_assembly=8, max_total_results=6000):
    game, out = Path(game).resolve(), Path(out).resolve()
    cache_dir = out / 'Combat' / 'AssemblyCache'
    cache_dir.mkdir(parents=True, exist_ok=True)
    dlls = _list_managed_candidates(game)
    all_rows = []
    issues = []
    scanned = 0
    cached = 0
    managed = 0
    skipped = 0
    total_names = 0
    for i, dll in enumerate(dlls, 1):
        rel = dll.relative_to(game).as_posix()
        if progress:
            progress.update(stage='combat-index', done=i - 1, total=len(dlls), current=rel)
        try:
            stat = dll.stat()
            if stat.st_size > MAX_ASSEMBLY_SIZE:
                skipped += 1
                issues.append({'assembly': rel, 'error_type': 'assembly_size_limit'})
                continue
            key = f'{CACHE_VERSION}:{stat.st_size}:{stat.st_mtime_ns}:{max_candidates_per_assembly}:{max_il_bytes}:{evidence_per_assembly}'
            identifier = hashlib.sha256(rel.encode('utf-8')).hexdigest()[:24]
            cache = cache_dir / (identifier + '.json')
            result = None
            if cache.exists():
                try:
                    obj = json.loads(cache.read_text(encoding='utf-8'))
                    if obj.get('key') == key and obj.get('source') == rel:
                        result = obj['result']
                        cached += 1
                except (OSError, ValueError, KeyError, TypeError):
                    pass
            if result is None:
                result = _index_assembly(
                    dll, rel, max_candidates=max_candidates_per_assembly,
                    max_il_bytes=max_il_bytes, evidence_count=evidence_per_assembly,
                    heartbeat=(lambda r, n, t: progress.update(stage='combat-methods', done=n,
                                                                  total=t, current=r)) if progress else None)
                atomic_json(cache, {'key': key, 'source': rel, 'result': result})
                scanned += 1
            managed += bool(result.get('managed'))
            total_names += result.get('candidate_names', 0)
            issues.extend(result.get('issues', []))
            for row in result.get('candidates', []):
                if len(all_rows) >= max_total_results:
                    break
                all_rows.append(row)
        except Exception as exc:
            issues.append({'assembly': rel, 'error_type': type(exc).__name__})
        if progress:
            progress.update(stage='combat-index', done=i, total=len(dlls), current=rel)
    all_rows.sort(key=lambda r: (-r['score'], r['assembly'], r['token']))
    for row in all_rows:
        if row.pop('il_lines', None):
            # IL was reviewed in memory during indexing; only compact signals
            # are retained in default reports, no whole-client disassembly.
            pass
    rows = [{k:v for k,v in row.items() if k != 'signals'} for row in all_rows]
    _write_csv(out/'Combat/Methods.csv', rows,
               ['assembly','token','method','topics','score','numeric_literals','calls_related',
                'fields_related','evidence_status'])
    _write_csv(out/'Combat/CallReferences.csv',
               [{'assembly':r['assembly'],'caller':r['method'],'callee':c,'topics':topics(c)}
                for r in all_rows for c in r['calls_related']],
               ['assembly','caller','callee','topics'])
    _write_csv(out/'Combat/ILSignals.csv',
               [{'assembly':r['assembly'],'method':r['method'],**s} for r in all_rows
                for s in r['signals']],
               ['assembly','method','offset','opcode','kind'])
    dossier = [{'topic': topic, 'candidate_methods': [
        {'assembly':r['assembly'],'method':r['method'],'token':r['token'],
         'score':r['score'],'arithmetic_branch_signals':len(r['signals']),
         'numeric_literals':r['numeric_literals'][:25],
         'calls_related':r['calls_related'][:25], 'fields_related':r['fields_related'][:25]}
        for r in all_rows if topic in r['topics']][:50],
        'interpretation': 'Candidate method names/IL clues, not a verified formula'}
        for topic in TOPICS]
    atomic_json(out/'Combat/Dossiers.json', dossier)
    atomic_json(out/'Combat/Topics.json', [
        {'topic': x['topic'], 'candidate_methods': len([r for r in all_rows if x['topic'] in r['topics']]),
         'status':'Unverified static candidates; investigate server authority'} for x in dossier])
    _write_csv(out/'Combat/Errors.csv', issues, ['assembly','token','error_type'])
    summary = {'generated_utc': datetime.now(timezone.utc).isoformat(), 'method': 'bounded_metadata_first',
               'assemblies_found': len(dlls), 'managed_assemblies': managed,
               'assemblies_scanned': scanned, 'assemblies_reused_from_cache': cached,
               'assemblies_skipped_size': skipped,
               'candidate_method_names': total_names, 'candidate_methods': len(all_rows),
               'errors': len(issues),
               'warning': 'Never verified combat formulas. Static client-code evidence only; server-side behavior may differ.'}
    atomic_json(out/'Combat/Summary.json', summary)
    return summary
