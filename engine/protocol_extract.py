#!/usr/bin/env python3
"""Static protocol-definition extractor for WoSB client and launcher assemblies.

Reads .NET metadata and IL with dnfile/dncil (never loads or executes game
code) and produces Protocol-Definitions.json:

* message_types   classes that look like network messages/packets, with their
                  fields (name + decoded CLR type) and base class
* wire_layouts    the ordered Read*/Write* calls inside each serializer-like
                  method (Serialize/Deserialize/Read/Write/Pack/Unpack/...).
                  For hand-written serializers this order IS the field order
                  on the wire, which is what an emulator needs.
* opcode_enums    enums whose names look like message ids/opcodes, with values;
                  protocol_lab.match_definitions() checks them against captures
* dispatch_hints  methods containing large switch tables over a message id
* strings         network-related literals (host names redacted)

Everything is labelled as static evidence; runtime behaviour, encryption and
server-side rules still need confirmation. The pure functions below operate on
plain dictionaries so they are unit-testable without game files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

FORMAT = 'wosb-protocol-definitions-v1'

MESSAGE_NAME = re.compile(r'(packet|message|msg|request|response|reply|command|cmd|rpc|notify|'
                          r'notification|event|sync|update|net|proto|datagram|payload)', re.I)
STRONG_NAME = re.compile(r'(packet|message|msg|request|response|rpc|cmd)$', re.I)
SERIALIZER = re.compile(r'^(serialize|deserialize|write|read|pack|unpack|encode|decode|tobytes|frombytes|'
                        r'writeto|readfrom|save|load|marshal|unmarshal|onserialize|ondeserialize)', re.I)
OPCODE_ENUM = re.compile(r'(opcode|op_code|messagetype|msgtype|messageid|msgid|packettype|packetid|'
                         r'commandtype|commandid|cmdtype|rpcid|rpctype|netmessage|protocolid)', re.I)
IO_OWNER = re.compile(r'(reader|writer|stream|buffer|packet|serializ|bitstream|netdata|bytes?array)', re.I)
IO_CALL = re.compile(r'^(read|write|put|get|peek|skip)', re.I)
NETWORK_STRING = re.compile(r'(tcp|udp|socket|connect|login|auth|session|handshake|ping|pong|packet|opcode|'
                            r'server|lobby|region|port|protocol|encrypt|decrypt|compress)', re.I)
HOSTLIKE = re.compile(r'([a-z0-9-]+\.)+[a-z]{2,}|\b\d{1,3}(\.\d{1,3}){3}\b', re.I)

ELEMENT_TYPES = {0x01: 'void', 0x02: 'bool', 0x03: 'char', 0x04: 'int8', 0x05: 'uint8', 0x06: 'int16',
                 0x07: 'uint16', 0x08: 'int32', 0x09: 'uint32', 0x0a: 'int64', 0x0b: 'uint64',
                 0x0c: 'float32', 0x0d: 'float64', 0x0e: 'string', 0x18: 'intptr', 0x19: 'uintptr',
                 0x1c: 'object'}
# Typical BinaryReader/BinaryWriter method names -> wire type.
READ_TYPES = {'readboolean': 'bool', 'readbyte': 'uint8', 'readsbyte': 'int8', 'readchar': 'char',
              'readint16': 'int16', 'readuint16': 'uint16', 'readint32': 'int32', 'readuint32': 'uint32',
              'readint64': 'int64', 'readuint64': 'uint64', 'readsingle': 'float32', 'readdouble': 'float64',
              'readdecimal': 'decimal', 'readstring': 'string', 'readbytes': 'bytes', 'readchars': 'chars',
              'read7bitencodedint': 'varint32', 'read7bitencodedint64': 'varint64', 'readfloat': 'float32',
              'readshort': 'int16', 'readushort': 'uint16', 'readint': 'int32', 'readuint': 'uint32',
              'readlong': 'int64', 'readulong': 'uint64', 'readbool': 'bool', 'readvarint': 'varint'}


# ----------------------------------------------------------- pure analysis

def decode_type_sig(blob, pos=0, resolve=None, depth=0):
    """Decode one CLR type from a signature blob -> (name, new_pos)."""
    if pos >= len(blob) or depth > 8:
        return '?', len(blob)
    code = blob[pos]; pos += 1
    if code in ELEMENT_TYPES:
        return ELEMENT_TYPES[code], pos
    if code in (0x11, 0x12):                      # valuetype / class TypeDefOrRef
        token, pos = _compressed(blob, pos)
        return (resolve(token) if resolve else f'type#{token:#x}'), pos
    if code == 0x1d:                              # SZARRAY
        inner, pos = decode_type_sig(blob, pos, resolve, depth + 1)
        return inner + '[]', pos
    if code == 0x0f:                              # pointer
        inner, pos = decode_type_sig(blob, pos, resolve, depth + 1)
        return inner + '*', pos
    if code == 0x10:                              # byref
        inner, pos = decode_type_sig(blob, pos, resolve, depth + 1)
        return inner + '&', pos
    if code == 0x15:                              # GENERICINST
        base, pos = decode_type_sig(blob, pos, resolve, depth + 1)
        count, pos = _compressed(blob, pos)
        args = []
        for _ in range(min(count, 16)):
            arg, pos = decode_type_sig(blob, pos, resolve, depth + 1); args.append(arg)
        return f'{base}<{", ".join(args)}>', pos
    if code in (0x13, 0x1e):                      # VAR / MVAR
        index, pos = _compressed(blob, pos)
        return ('T' if code == 0x13 else 'M') + str(index), pos
    if code == 0x14:                              # ARRAY (multi-dim): skip shape conservatively
        inner, pos = decode_type_sig(blob, pos, resolve, depth + 1)
        return inner + '[,]', len(blob)
    return f'elem#{code:#x}', pos


def _compressed(b, pos):
    a = b[pos]; pos += 1
    if a < 0x80:
        return a, pos
    if a < 0xc0:
        return ((a & 0x3f) << 8) | b[pos], pos + 1
    return ((a & 0x1f) << 24) | (b[pos] << 16) | (b[pos + 1] << 8) | b[pos + 2], pos + 3


def field_type(blob, resolve=None):
    if not blob or blob[0] != 0x06:
        return '?'
    pos = 1
    while pos < len(blob) and blob[pos] in (0x1f, 0x20):   # custom modifiers
        _, pos = _compressed(blob, pos + 1)
    return decode_type_sig(blob, pos, resolve)[0]


def first_param_type(blob, resolve=None):
    """Type of the first parameter in a method signature (e.g. BinaryWriter.Write(int))."""
    try:
        pos = 1
        if blob[0] & 0x10:
            _, pos = _compressed(blob, pos)
        count, pos = _compressed(blob, pos)
        _, pos = decode_type_sig(blob, pos, resolve)       # return type
        if count == 0:
            return None
        return decode_type_sig(blob, pos, resolve)[0]
    except (IndexError, ValueError):
        return None


def wire_op(owner, name, param_type=None):
    """Map an IO call to a wire-field description, or None if not IO."""
    low = name.casefold()
    short_owner = owner.rsplit('.', 1)[-1]
    if not (IO_OWNER.search(short_owner) and IO_CALL.match(name)) and low not in READ_TYPES:
        return None
    if low in READ_TYPES:
        return {'op': 'read', 'type': READ_TYPES[low], 'call': f'{short_owner}.{name}'}
    if low.startswith(('write', 'put')):
        guessed = param_type or READ_TYPES.get('read' + low[5:]) or 'unknown'
        return {'op': 'write', 'type': guessed, 'call': f'{short_owner}.{name}'}
    guessed = READ_TYPES.get('read' + re.sub(r'^(read|get|peek)', '', low)) or 'unknown'
    return {'op': 'read', 'type': guessed, 'call': f'{short_owner}.{name}'}


def classify_message_types(types):
    """Score classes as network-message candidates.

    types: [{'name','namespace','base','fields':[{'name','type'}],'methods':[{'name','io':[...]}]}]
    """
    base_counts = Counter(t.get('base') for t in types if t.get('base'))
    out = []
    for t in types:
        full = f"{t.get('namespace') or ''}.{t['name']}".strip('.')
        reasons = []; score = 0
        if STRONG_NAME.search(t['name']):
            score += 6; reasons.append('message-like class name')
        elif MESSAGE_NAME.search(full):
            score += 2; reasons.append('network-related name')
        base = t.get('base') or ''
        if base and MESSAGE_NAME.search(base) and base_counts[base] >= 3:
            score += 5; reasons.append(f'shares message-like base {base} with {base_counts[base] - 1} other classes')
        ser = [m for m in t.get('methods', []) if SERIALIZER.match(m['name']) and m.get('io')]
        if ser:
            score += 6 + min(6, sum(len(m['io']) for m in ser) // 3); reasons.append('serializer method with reader/writer calls')
        if t.get('opcode_constant') is not None:
            score += 4; reasons.append('constant message id field')
        if score >= 6:
            out.append({'type': full, 'base': base or None, 'score': score, 'reasons': reasons,
                        'assembly': t.get('assembly'), 'token': t.get('token'),
                        'fields': t.get('fields', [])[:200],
                        'opcode_constant': t.get('opcode_constant'),
                        'serializers': [{'method': m['name'], 'wire_order': m['io'][:400]} for m in ser]})
    out.sort(key=lambda r: (-r['score'], r['type']))
    return out


def opcode_enums(enums):
    """enums: [{'name','namespace','members':{name:value}}] -> likely message-id enums."""
    out = []
    for e in enums:
        full = f"{e.get('namespace') or ''}.{e['name']}".strip('.')
        members = e.get('members') or {}
        if not members:
            continue
        name_hit = bool(OPCODE_ENUM.search(full))
        values = [v for v in members.values() if isinstance(v, int)]
        dense = len(values) >= 8 and len(set(values)) == len(values)
        names_hit = sum(bool(MESSAGE_NAME.search(k)) for k in members) / max(1, len(members))
        if name_hit or (dense and names_hit > 0.3):
            out.append({'name': full, 'assembly': e.get('assembly'), 'members': members,
                        'member_count': len(members), 'evidence': 'enum name' if name_hit else 'dense id enum with message-like member names'})
    out.sort(key=lambda r: -r['member_count'])
    return out


def diff_definitions(old, new):
    """Compare two Protocol-Definitions.json documents (e.g. Game vs Steam build)."""
    def index(doc):
        return {m['type']: m for m in doc.get('message_types', [])}
    a, b = index(old), index(new)
    changed = []
    for name in sorted(set(a) & set(b)):
        fa = [(f['name'], f['type']) for f in a[name].get('fields', [])]
        fb = [(f['name'], f['type']) for f in b[name].get('fields', [])]
        wa = [[(w['op'], w['type']) for w in s['wire_order']] for s in a[name].get('serializers', [])]
        wb = [[(w['op'], w['type']) for w in s['wire_order']] for s in b[name].get('serializers', [])]
        if fa != fb or wa != wb:
            changed.append({'type': name, 'fields_changed': fa != fb, 'wire_order_changed': wa != wb,
                            'old_fields': fa[:60], 'new_fields': fb[:60]})
    ea = {e['name']: e['members'] for e in old.get('opcode_enums', [])}
    eb = {e['name']: e['members'] for e in new.get('opcode_enums', [])}
    enum_changes = []
    for name in sorted(set(ea) | set(eb)):
        x, y = ea.get(name, {}), eb.get(name, {})
        if x != y:
            enum_changes.append({'enum': name,
                                 'added': {k: y[k] for k in y.keys() - x.keys()},
                                 'removed': {k: x[k] for k in x.keys() - y.keys()},
                                 'renumbered': {k: [x[k], y[k]] for k in x.keys() & y.keys() if x[k] != y[k]}})
    return {'format': 'wosb-protocol-diff-v1',
            'added_types': sorted(set(b) - set(a)), 'removed_types': sorted(set(a) - set(b)),
            'changed_types': changed, 'opcode_enum_changes': enum_changes}


# ------------------------------------------------------- dnfile extraction

def _constant_value(type_code, blob):
    import struct
    fmt = {0x02: '<?', 0x04: '<b', 0x05: '<B', 0x06: '<h', 0x07: '<H', 0x08: '<i', 0x09: '<I',
           0x0a: '<q', 0x0b: '<Q', 0x0c: '<f', 0x0d: '<d'}.get(type_code)
    if fmt and len(blob) >= struct.calcsize(fmt):
        return struct.unpack_from(fmt, blob)[0]
    if type_code == 0x0e:
        return blob.decode('utf-16-le', errors='replace')
    return None


def extract_assembly(path, *, max_types=60000, max_il_bytes=262144):
    """Return (types, enums, dispatch, strings, issues) for one .NET assembly."""
    from client_metadata import Metadata
    from dncil.clr.token import Token, StringToken
    m = Metadata(path)
    net = getattr(m.pe, 'net', None)
    if not net or not net.mdtables or not net.mdtables.TypeDef:
        raise ValueError('Not a managed .NET assembly')
    tables = net.mdtables
    issues = []

    def resolve(token):
        table = [2, 1, 27][token & 3]; rid = token >> 2
        try:
            return m.typename(tables.tables[table].rows[rid - 1])
        except (IndexError, KeyError, AttributeError):
            return f'type#{token:#x}'

    constants = {}
    for row in getattr(tables, 'Constant', None) and tables.Constant.rows or []:
        try:
            parent = row.Parent
            if getattr(parent, 'table', None) is not None and parent.table.name == 'Field':
                blob = row.Value.value if hasattr(row.Value, 'value') else bytes(row.Value)
                constants[id(parent.row)] = _constant_value(int(row.Type), blob)
        except Exception as exc:   # dnfile row variants differ between versions
            issues.append({'stage': 'constant', 'error': type(exc).__name__}); continue

    types = []; enums = []; dispatch = []; strings = Counter()
    for index, t in enumerate(tables.TypeDef.rows[:max_types], 1):
        name = str(t.TypeName); namespace = str(t.TypeNamespace)
        if name.startswith('<') or namespace.startswith('<'):
            continue
        try:
            base = m.typename(t.Extends.row) if t.Extends and t.Extends.row is not None else ''
        except Exception:
            base = ''
        fields = []; opcode_constant = None; members = {}
        for f in t.FieldList:
            row = f.row
            try:
                ftype = field_type(row.Signature.value, resolve)
            except Exception:
                ftype = '?'
            fname = str(row.Name)
            value = constants.get(id(row))
            if base == 'System.Enum':
                if fname != 'value__':
                    members[fname] = value
                continue
            fields.append({'name': fname, 'type': ftype, **({'constant': value} if value is not None else {})})
            if value is not None and isinstance(value, int) and re.search(r'(opcode|msgid|messageid|packetid|typeid|^id$|^type$)', fname, re.I):
                opcode_constant = value
        if base == 'System.Enum':
            enums.append({'name': name, 'namespace': namespace, 'members': members, 'assembly': Path(path).name})
            continue
        methods = []
        for mi in t.MethodList:
            row = mi.row; mname = str(row.Name)
            if not row.Rva:
                continue
            interesting = bool(SERIALIZER.match(mname))
            try:
                body = m.body_limited(mi.row_index, max_il_bytes)
            except Exception:
                continue
            io = []; switch_size = 0
            for ins in body:
                op = ins.operand
                if ins.opcode.name == 'switch' and isinstance(op, (list, tuple)):
                    switch_size = max(switch_size, len(op))
                if isinstance(op, StringToken):
                    try:
                        text = str(net.user_strings.get(op.rid).value)
                        if NETWORK_STRING.search(text) and len(text) < 200:
                            strings[HOSTLIKE.sub('<host>', text)] += 1
                    except Exception:
                        pass
                elif interesting and isinstance(op, Token) and op.table in (6, 10, 43) and ins.opcode.name in ('call', 'callvirt'):
                    try:
                        owner, callee, crow = m.method(op)
                        param = first_param_type(crow.Signature.value, resolve) if hasattr(crow, 'Signature') else None
                        wire = wire_op(owner, callee, param)
                        if wire:
                            io.append(wire)
                        elif SERIALIZER.match(callee) and callee != mname:
                            io.append({'op': 'nested', 'type': owner.rsplit('.', 1)[-1], 'call': f'{owner.rsplit(".", 1)[-1]}.{callee}'})
                    except Exception:
                        continue
            if switch_size >= 16:
                dispatch.append({'method': f'{namespace}.{name}::{mname}', 'switch_cases': switch_size,
                                 'assembly': Path(path).name,
                                 'token': f'0x{0x06000000 | mi.row_index:08x}',
                                 'hint': 'large switch: candidate message dispatcher (verify the switched value)'})
            if interesting:
                methods.append({'name': mname, 'io': io})
        types.append({'name': name, 'namespace': namespace, 'base': base, 'fields': fields,
                      'methods': methods, 'opcode_constant': opcode_constant,
                      'assembly': Path(path).name, 'token': f'0x{0x02000000 | index:08x}'})
    return types, enums, dispatch, strings, issues


def _sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def extract(root, *, label='', include=None, progress=None):
    """Scan every .NET assembly under ``root`` (client, Steam build or launcher)."""
    root = Path(root).resolve(strict=True)
    files = sorted(p for p in root.rglob('*') if p.suffix.lower() in ('.dll', '.exe') and p.is_file()
                   and p.stat().st_size < 256 * 1024 * 1024)
    if include:
        pattern = re.compile(include, re.I)
        files = [p for p in files if pattern.search(p.name)]
    all_types = []; all_enums = []; dispatch = []; strings = Counter(); assemblies = []; issues = []
    for i, path in enumerate(files, 1):
        rel = path.relative_to(root).as_posix()
        if progress:
            progress(f'{i}/{len(files)} {rel}')
        try:
            types, enums, disp, strs, probs = extract_assembly(path)
        except Exception as exc:
            issues.append({'assembly': rel, 'error': f'{type(exc).__name__}: {exc}'[:300]})
            continue
        assemblies.append({'path': rel, 'sha256': _sha256(path), 'types': len(types), 'enums': len(enums)})
        all_types += types; all_enums += enums; dispatch += disp; strings.update(strs)
        issues += [{'assembly': rel, **p} for p in probs[:20]]
    return {'format': FORMAT, 'label': label or root.name,
            'generated_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'assemblies': assemblies, 'issues': issues,
            'message_types': classify_message_types(all_types),
            'opcode_enums': opcode_enums(all_enums),
            'dispatch_hints': sorted(dispatch, key=lambda d: -d['switch_cases'])[:200],
            'network_strings': [{'text': k, 'count': v} for k, v in strings.most_common(400)],
            'evidence': 'static client metadata/IL; runtime encryption, compression and server rules not verified'}


def main(argv=None):
    ap = argparse.ArgumentParser(description='Extract candidate network message definitions from WoSB assemblies (read-only)')
    sub = ap.add_subparsers(dest='cmd', required=True)
    x = sub.add_parser('extract'); x.add_argument('root'); x.add_argument('--out', required=True)
    x.add_argument('--label', default=''); x.add_argument('--include', help='regex filter on assembly file names')
    d = sub.add_parser('diff'); d.add_argument('old'); d.add_argument('new'); d.add_argument('--out', required=True)
    a = ap.parse_args(argv)
    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    if a.cmd == 'extract':
        result = extract(a.root, label=a.label, include=a.include, progress=lambda s: print(s, flush=True))
        print(f"{len(result['message_types'])} message candidates, {len(result['opcode_enums'])} opcode enums, "
              f"{len(result['issues'])} issues")
    else:
        result = diff_definitions(json.loads(Path(a.old).read_text(encoding='utf-8')),
                                  json.loads(Path(a.new).read_text(encoding='utf-8')))
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding='utf-8')
    print(out)


if __name__ == '__main__':
    if str(Path(__file__).resolve().parent) not in sys.path:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
    main()
