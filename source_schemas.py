"""Message wire layouts recovered from the decompiled client source.

WoSB serializes every network message and shared data struct with its own
``ManualPacketSerialization`` library: a type implements ``IMPSerializable`` and
writes its fields in ``Boxing(WriterExtern)`` / reads them in ``Unboxing``.
The IL extractor sees the calls but not the conditions around them, so it
cannot describe a field that is only present when a flag is set (common:
``DamageData`` writes ``UDamageToSailes`` only for sail hits).

This module reads the ILSpy output indexed by ``datamine.build_source_index``
and turns each ``Boxing`` body into an ordered field list with types, byte
sizes and the ``if`` conditions that gate each field.

Static evidence from your own client. It documents message bodies only:
transport framing, encryption and server behaviour are not covered here.
"""
from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path

FORMAT = 'wosb-source-schemas-v1'

# Byte sizes of the blittable types the client writes with WriteStruct<T>.
SIZES = {'byte': 1, 'sbyte': 1, 'bool': 1, 'short': 2, 'ushort': 2, 'char': 2, 'int': 4, 'uint': 4,
         'float': 4, 'long': 8, 'ulong': 8, 'double': 8, 'Vector2': 8, 'Vector3': 12, 'Vector4': 16,
         'Quaternion': 16, 'Color': 4, 'Point': 8, 'Half': 2, 'DateTime': 8, 'TimeSpan': 8, 'Guid': 16,
         'decimal': 16}
ENUM_BASE = {'byte': 1, 'sbyte': 1, 'short': 2, 'ushort': 2, 'int': 4, 'uint': 4, 'long': 8, 'ulong': 8}

TYPE_DECL = re.compile(r'(?:public|internal|private)?\s*(?:readonly\s+|ref\s+|sealed\s+|abstract\s+|partial\s+|unsafe\s+)*'
                       r'(struct|class)\s+(\w+)(?:\s*\([^)]*\))?\s*:\s*([^{\n]+)')
ENUM_DECL = re.compile(r'enum\s+(\w+)(?:\s*:\s*(\w+))?\s*\{')
FIELD_DECL = re.compile(r'^\s*(?:\[[^\]]*\]\s*)*(?:public|internal|private|protected)\s+(?:readonly\s+|static\s+|const\s+|volatile\s+)*'
                        r'([\w<>\[\],.? `]+?)\s+(\w+)\s*(?:=[^;]*)?;', re.M)
NAMESPACE = re.compile(r'^namespace\s+([\w.]+)', re.M)
WRITER_METHOD = re.compile(r'(?:public|private|internal)?\s*(?:override\s+|virtual\s+)?void\s+(?:IMPSerializable\.)?(\w+)\s*\(\s*WriterExtern\s+(\w+)\s*\)')

# WriterExtern / TlistFormatter calls -> wire encoding (see Reskana WriterExtern.cs).
CALLS = {
    'WriteStruct': 'struct', 'WriteByte': 'u8', 'WriteEnum': 'enum8', 'Write': 'auto',
    'WriteBytes8bitSize': 'bytes[u8 length]', 'WriteBytes32bitSize': 'bytes[i32 length]',
    'WriteByteConstSize': 'bytes[fixed]', 'WriteTlistStruct': 'list[i16 count] of {item}',
    'WriteTlist': 'list[i16 count] of {item}', 'WriteTlistImps': 'list[i16 count] of {item}',
    'WriteNoNull': 'object {type}', 'WriteStruct8bitSize': 'array[u8 count] of {item}',
    'WriteDict': 'dict[i32 count]', 'WriteArray': 'array[i16 count] of {item}',
}
ENCODING_NOTES = {
    'string': 'u8 present (1) / null (0), then i16 byte length, then UTF-16LE bytes',
    'bool': 'u8: 0xFF true, 0xFE false',
    'object?': 'u8 present (1) / null (0), then the object body',
}


def _body(text, start):
    """Text of the brace block that opens at or after ``start``."""
    i = text.find('{', start)
    if i < 0:
        return '', start
    depth = 0
    for j in range(i, len(text)):
        c = text[j]
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return text[i + 1:j], j
    return text[i + 1:], len(text)


def _split_args(arg):
    out = []; depth = 0; cur = ''
    for ch in arg:
        if ch in '(<[':
            depth += 1
        elif ch in ')>]':
            depth -= 1
        if ch == ',' and depth == 0:
            out.append(cur.strip()); cur = ''
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def _clean_expr(expr):
    expr = expr.strip()
    expr = re.sub(r'^(ref|in|out)\s+', '', expr)
    cast = None
    m = re.match(r'^\((\w+)\)\s*(.+)$', expr)
    if m:
        cast, expr = m.group(1), m.group(2)
    expr = re.sub(r'^this\.', '', expr)
    return cast, expr


def _generic_item(type_text):
    m = re.search(r'<\s*([\w.]+)\s*>', type_text or '')
    return m.group(1).rsplit('.', 1)[-1] if m else '?'


def parse_writer(body, fields, enums):
    """Ordered wire fields from a Boxing body: [{'name','wire','size','declared','condition'}]."""
    out = []
    # Walk statements, tracking the if/else/for conditions that wrap them.
    stack = []  # (condition text, depth at which it applies)
    depth = 0; pending = None
    i = 0; n = len(body)
    token = re.compile(r'\b(if|else|for|foreach|while)\b|[{}]|(\w+)\.(\w+)\s*(?:<[^>()]*>)?\s*\(|;')
    while i < n:
        m = token.search(body, i)
        if not m:
            break
        tok = m.group(0)
        if m.group(1) in ('if', 'for', 'foreach', 'while'):
            cond, end = _paren(body, m.end())
            pending = (m.group(1) + ' ' + cond.strip()) if m.group(1) != 'if' else cond.strip()
            i = end
            # Single-statement body without braces.
            nxt = re.match(r'\s*\{', body[i:])
            if not nxt:
                stack.append((pending, depth, True)); pending = None
            continue
        if m.group(1) == 'else':
            last = _last_condition
            pending = ('not (' + last + ')') if last else 'else'
            i = m.end()
            if not re.match(r'\s*(\{|if\b)', body[i:]):
                stack.append((pending, depth, True)); pending = None
            continue
        if tok == '{':
            depth += 1
            if pending is not None:
                stack.append((pending, depth, False)); pending = None
            i = m.end(); continue
        if tok == '}':
            while stack and stack[-1][1] == depth and not stack[-1][2]:
                globals()['_last_condition'] = stack.pop()[0]
            depth -= 1
            i = m.end(); continue
        if tok == ';':
            while stack and stack[-1][2]:
                globals()['_last_condition'] = stack.pop()[0]
            i = m.end(); continue
        obj, call = m.group(2), m.group(3)
        args_text, end = _paren(body, m.end() - 1)
        i = end
        condition = ' and '.join(c for c, _d, _s in stack) or None
        if call in ('Boxing',) and obj not in ('IMPSerializable',):
            out.append({'name': obj, 'wire': 'object ' + fields.get(obj, '?'), 'size': None,
                        'declared': fields.get(obj), 'condition': condition}); continue
        if call not in CALLS:
            continue
        args = _split_args(args_text)
        if not args:
            continue
        cast, expr = _clean_expr(args[0])
        name = re.sub(r'\.(Size|Length|Count)$', '', expr)
        declared = fields.get(name.split('.')[0]) if re.match(r'^[A-Za-z_]\w*(\.\w+)?$', name) else None
        literal = re.fullmatch(r'-?\d+(\.\d+)?f?', expr)
        wire = CALLS[call]
        size = None
        if call == 'WriteStruct':
            t = cast or (declared or '').rstrip('?')
            if len(args) == 3:
                wire = f'array of {t}'; size = None
            elif t in SIZES:
                wire = t; size = SIZES[t]
            elif t in enums:
                wire = f'{t} (enum {enums[t][0]})'; size = enums[t][1]
            else:
                wire = f'struct {t or "?"}'
            if expr.endswith(('.Size', '.Length', '.Count')):
                wire += ' (count)'
        elif call == 'WriteByte':
            wire = 'u8' + (f' ({declared} as byte)' if declared and declared != 'byte' else ''); size = 1
        elif call == 'WriteEnum':
            wire = f'u8 enum {declared or "?"}'; size = 1
        elif call == 'Write':
            t = (cast or declared or '').rstrip('?')
            if t == 'string':
                wire = 'string'; size = None
            elif t == 'bool':
                wire = 'bool'; size = 1
            elif len(args) >= 1 and args[0].startswith('ref '):
                wire = f'struct object {t or "?"}'
            else:
                wire = f'object? {t or "?"}'
        elif '{item}' in wire:
            wire = wire.replace('{item}', _generic_item(declared))
        elif '{type}' in wire:
            wire = wire.replace('{type}', declared or '?')
        out.append({'name': ('const ' + expr) if literal else name, 'wire': wire, 'size': size,
                    'declared': declared, 'condition': condition})
    return out


_last_condition = None


def _paren(text, start):
    """Contents of the (...) group starting at ``start`` (which points at or before '(')."""
    i = text.find('(', start)
    if i < 0:
        return '', start
    depth = 0
    for j in range(i, len(text)):
        if text[j] == '(':
            depth += 1
        elif text[j] == ')':
            depth -= 1
            if depth == 0:
                return text[i + 1:j], j + 1
    return text[i + 1:], len(text)


def _fields(type_body):
    out = {}
    for m in FIELD_DECL.finditer(type_body):
        t, name = m.group(1).strip(), m.group(2)
        if t in ('return', 'new', 'using') or '(' in t:
            continue
        out[name] = t.split('.')[-1] if '<' not in t else t
    return out


def _type_blocks(text):
    for m in TYPE_DECL.finditer(text):
        bases = m.group(3)
        if 'IMPSerializable' not in bases and 'IPacketBase' not in bases:
            continue
        body, _end = _body(text, m.end())
        # Primary-constructor fields: public Tlist<DamageData> CollisionData = collisions;
        yield m.group(1), m.group(2), bases.strip(), body, text.count('\n', 0, m.start()) + 1


def _writer_body(type_body):
    """The Boxing implementation, following ILSpy's explicit-interface trampolines."""
    methods = {}
    for m in WRITER_METHOD.finditer(type_body):
        body, _ = _body(type_body, m.end())
        methods.setdefault(m.group(1), []).append(body)
    boxing = (methods.get('Boxing') or [None])[0]
    if boxing is None:
        return None
    hop = re.fullmatch(r'\s*(?://[^\n]*\n\s*)*this\.(\w+)\(\w+\);\s*', boxing)
    if hop:
        # Prefer the overload that writes (Write*) rather than the reading twin.
        for candidate in methods.get(hop.group(1), []):
            if re.search(r'\.Write\w*\s*[(<]', candidate) or re.search(r'\.Boxing\(', candidate):
                return candidate
        return (methods.get(hop.group(1)) or [boxing])[0]
    return boxing


def extract_from_index(index_path, *, include=r'^(Common|WorldOfSeaBattles|TheraEngine|Reskana)', limit=None, progress=None):
    """Read ``Source-Index.sqlite3`` and return wire layouts for every IMPSerializable type."""
    pattern = re.compile(include, re.I) if include else None
    enums = {}
    types = []
    with closing(sqlite3.connect(f'file:{index_path}?mode=ro', uri=True)) as conn:
        rows = conn.execute('SELECT path, body FROM source_fts').fetchall()
    # Pass 1: enum underlying types, so WriteStruct(enumField) gets the right size.
    for path, body in rows:
        if pattern and not _assembly_ok(path, pattern):
            continue
        for m in ENUM_DECL.finditer(body):
            base = m.group(2) or 'int'
            enums[m.group(1)] = (base, ENUM_BASE.get(base, 4))
    for k, (path, body) in enumerate(rows):
        if pattern and not _assembly_ok(path, pattern):
            continue
        if 'WriterExtern' not in body:
            continue
        if progress and k % 500 == 0:
            progress(k / max(1, len(rows)), path)
        ns = (NAMESPACE.search(body) or [None, ''])[1] if NAMESPACE.search(body) else ''
        for kind, name, bases, tbody, line in _type_blocks(body):
            fields = _fields(tbody)
            # Primary-constructor struct: fields declared with '= param'.
            writer = _writer_body(tbody)
            if writer is None:
                continue
            wire = parse_writer(writer, fields, enums)
            fixed = all(f['size'] is not None and not f['condition'] for f in wire)
            types.append({'type': (ns + '.' if ns else '') + name, 'kind': kind,
                          'is_packet': 'IPacketBase' in bases,
                          'flow': _flow(tbody), 'source': f'{path}:{line}',
                          'fields': wire,
                          'fixed_size': sum(f['size'] for f in wire) if fixed and wire else None,
                          'conditional_fields': sum(1 for f in wire if f['condition'])})
            if limit and len(types) >= limit:
                break
    types.sort(key=lambda t: (not t['is_packet'], t['type']))
    return {'format': FORMAT, 'index': str(index_path), 'types': types,
            'packets': sum(1 for t in types if t['is_packet']), 'enums_known': len(enums),
            'encodings': ENCODING_NOTES,
            'evidence': 'Decompiled client source (your local install). Message bodies only; '
                        'transport framing/encryption and server-side rules are not described.'}


def _assembly_ok(path, pattern):
    return bool(pattern.search(path.split('/', 1)[0])) or bool(pattern.search(path.split('/')[1] if '/' in path else ''))


def _flow(type_body):
    m = re.search(r'FlowOfPack\.(\w+)', type_body)
    return m.group(1) if m else None


def find_index(data_home):
    """Newest Source-Index.sqlite3 under the Research/Decompiled tree."""
    base = Path(data_home) / 'Research' / 'Decompiled'
    found = sorted(base.glob('**/Source-Index.sqlite3'), key=lambda p: p.stat().st_mtime, reverse=True) if base.is_dir() else []
    return found[0] if found else None


def write_schemas(result, dest):
    from advanced_io import write_json_atomic
    dest = Path(dest); dest.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(dest, result)
    return dest


def describe(type_entry):
    """Markdown table of one type's wire layout (for wiki pages)."""
    lines = [f"### `{type_entry['type']}`", '',
             f"Source: `{type_entry['source']}`" + (f" · flow: {type_entry['flow']}" if type_entry.get('flow') else ''), '',
             '| # | Field | Wire encoding | Bytes | Present when |', '|---|---|---|---|---|']
    for i, f in enumerate(type_entry['fields'], 1):
        lines.append(f"| {i} | `{f['name']}` | {f['wire']} | {f['size'] if f['size'] is not None else 'var'} | "
                     f"{('`' + f['condition'].replace('||', ' or ').replace('&&', ' and ').replace('|', '/') + '`') if f['condition'] else 'always'} |")
    if type_entry.get('fixed_size'):
        lines += ['', f"Fixed size: **{type_entry['fixed_size']} bytes**."]
    return '\n'.join(lines)


if __name__ == '__main__':  # pragma: no cover
    import sys
    res = extract_from_index(sys.argv[1])
    print(json.dumps({'types': len(res['types']), 'packets': res['packets']}, indent=1))
