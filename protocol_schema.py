"""Message schemas: field inference, decoding, emulator data export and tool exports.

A schema describes what you have learned about each message type:

    {"format": "wosb-protocol-schema-v1",
     "framing": {...protocol_lab.Framing dict...}, "opcode_width": 1,
     "types": {"client:0x7": {"name": "FireBroadside", "fields": [
         {"name": "shot_id", "type": "uint32"}, {"name": "angle", "type": "float32"}]}}}

Fields are sequential from the first byte after the opcode. Supported types:
int8/uint8/int16/uint16/int32/uint32/int64/uint64 (little-endian unless suffixed
"_be"), float32/float64, bool, varint (7-bit LEB128), string8/string16 (u8/u16
length-prefixed UTF-8), dotnet_string (7-bit length, as BinaryWriter.Write(string)),
bytes:N (fixed), rest (remaining bytes).

Exports: decoded JSONL and SQLite tables (one per message type, like the
sniff-to-database workflow emulator projects use), a Wireshark Lua dissector, an
ImHex pattern and a Kaitai Struct definition.
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
import statistics
import struct
from collections import Counter
from pathlib import Path

FORMAT = 'wosb-protocol-schema-v1'
SCALARS = {'int8': ('b', 1), 'uint8': ('B', 1), 'int16': ('h', 2), 'uint16': ('H', 2), 'int32': ('i', 4),
           'uint32': ('I', 4), 'int64': ('q', 8), 'uint64': ('Q', 8), 'float32': ('f', 4), 'float64': ('d', 8),
           'bool': ('?', 1)}


# --------------------------------------------------------------- inference

def infer_fields(bodies, *, max_offset=64):
    """Per-offset hints from many samples of ONE message type (opcode already stripped).

    Looks for constants, counters, length fields, plausible float32 values and
    small enumerations — the same signals protocol-inference tools use.
    """
    bodies = [b for b in bodies if b]
    if len(bodies) < 3:
        return []
    width = min(max_offset, min(len(b) for b in bodies))
    lengths = [len(b) for b in bodies]
    hints = []; offset = 0
    while offset < width:
        column = [b[offset] for b in bodies]
        hint = None
        # Multi-byte interpretations first: a float such as 1.5 has constant zero low
        # bytes, which a byte-level constant check would otherwise claim.
        if offset + 4 <= width:
            u32 = [struct.unpack_from('<I', b, offset)[0] for b in bodies]
            f32 = [struct.unpack_from('<f', b, offset)[0] for b in bodies]
            diffs = [b - a for a, b in zip(u32, u32[1:])]
            if len(set(u32)) > 2 and diffs and all(0 < d <= 16 for d in diffs):
                hint = {'offset': offset, 'size': 4, 'kind': 'counter_u32', 'step': statistics.median(diffs)}
            elif all(math.isfinite(v) and (v == 0 or 1e-6 < abs(v) < 1e7) for v in f32) and len(set(u32)) > 2 \
                    and sum(1 for b in bodies if b[offset + 3] in range(0x30, 0x50) or b[offset + 3] in range(0xb0, 0xd0)) > 0.8 * len(bodies):
                hint = {'offset': offset, 'size': 4, 'kind': 'float32',
                        'min': round(min(f32), 4), 'max': round(max(f32), 4)}
            elif len(set(lengths)) > 1:
                rest = [len(b) - offset - 4 for b in bodies]
                if u32 == rest or u32 == [len(b) for b in bodies]:
                    hint = {'offset': offset, 'size': 4, 'kind': 'length_u32'}
        if hint is None and len(set(column)) == 1:
            hint = {'offset': offset, 'size': 1, 'kind': 'constant', 'value': column[0]}
        if offset + 2 <= width and hint is None and len(set(lengths)) > 1:
            u16 = [struct.unpack_from('<H', b, offset)[0] for b in bodies]
            if u16 == [len(b) - offset - 2 for b in bodies]:
                hint = {'offset': offset, 'size': 2, 'kind': 'length_u16'}
        if hint is None:
            distinct = len(set(column))
            if distinct <= 8 and len(bodies) >= 10:
                hint = {'offset': offset, 'size': 1, 'kind': 'enum_u8', 'values': sorted(set(column))}
        if hint:
            hints.append(hint); offset += hint['size']
        else:
            offset += 1
    return hints


def suggest_fields(hints):
    """Turn inference hints into an editable starting schema field list."""
    fields = []; cursor = 0
    for h in hints:
        if h['offset'] > cursor:
            fields.append({'name': f'unknown_{cursor}', 'type': f'bytes:{h["offset"] - cursor}'})
        name = {'constant': 'const', 'counter_u32': 'sequence', 'float32': 'value', 'length_u32': 'length',
                'length_u16': 'length', 'enum_u8': 'kind'}[h['kind']] + f'_{h["offset"]}'
        typ = {'constant': 'uint8', 'counter_u32': 'uint32', 'float32': 'float32', 'length_u32': 'uint32',
               'length_u16': 'uint16', 'enum_u8': 'uint8'}[h['kind']]
        fields.append({'name': name, 'type': typ, 'inferred': h['kind']})
        cursor = h['offset'] + h['size']
    fields.append({'name': 'rest', 'type': 'rest'})
    return fields


# ---------------------------------------------------------------- decoding

def _varint(buf, pos):
    value = 0; shift = 0
    while True:
        if pos >= len(buf) or shift > 63:
            raise ValueError('truncated varint')
        b = buf[pos]; pos += 1
        value |= (b & 0x7f) << shift; shift += 7
        if not b & 0x80:
            return value, pos


def decode_fields(body, fields):
    """Decode ``body`` (after opcode) with a field list -> (dict, error or None)."""
    out = {}; pos = 0
    try:
        for f in fields:
            name, typ = f['name'], f['type']
            big = typ.endswith('_be'); base = typ[:-3] if big else typ
            if base in SCALARS:
                code, size = SCALARS[base]
                if pos + size > len(body):
                    raise ValueError(f'{name}: needs {size} bytes at {pos}')
                value = struct.unpack_from(('>' if big else '<') + code, body, pos)[0]
                if isinstance(value, float) and not math.isfinite(value):
                    value = str(value)
                out[name] = value; pos += size
            elif base == 'varint':
                out[name], pos = _varint(body, pos)
            elif base in ('string8', 'string16', 'dotnet_string'):
                if base == 'string8':
                    n = body[pos]; pos += 1
                elif base == 'string16':
                    n = struct.unpack_from('<H', body, pos)[0]; pos += 2
                else:
                    n, pos = _varint(body, pos)
                if pos + n > len(body):
                    raise ValueError(f'{name}: string runs past end')
                out[name] = body[pos:pos + n].decode('utf-8', 'replace'); pos += n
            elif base.startswith('bytes:'):
                n = int(base.split(':', 1)[1])
                if pos + n > len(body):
                    raise ValueError(f'{name}: needs {n} bytes')
                out[name] = body[pos:pos + n].hex(); pos += n
            elif base == 'rest':
                out[name] = body[pos:].hex(); pos = len(body)
            else:
                raise ValueError(f'unknown field type {typ}')
        if pos < len(body):
            out['_trailing_hex'] = body[pos:].hex()
        return out, None
    except (ValueError, IndexError, struct.error) as exc:
        return out, str(exc)


def load_schema(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if data.get('format') != FORMAT:
        raise ValueError('Not a WoSB protocol schema')
    return data


def save_schema(schema, path):
    schema = dict(schema); schema['format'] = FORMAT
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(schema, indent=2, ensure_ascii=False), encoding='utf-8')
    return path


def new_schema(framing, opcode_width, catalog=None):
    types = {}
    for t in (catalog or {}).get('types', []):
        types[t['type_id']] = {'name': '', 'fields': [], 'notes': ''}
    return {'format': FORMAT, 'framing': framing, 'opcode_width': opcode_width, 'types': types}


def read_message_log(path):
    """Yield (header, record) from protocol_lab.export_message_log output."""
    header = None
    with Path(path).open(encoding='utf-8') as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            if '_header' in row:
                header = row['_header']; continue
            yield header, row


def decode_log(log_path, schema, *, entity_names=None):
    """Decode every message of a message log with the schema.

    entity_names: optional {field_name_regex: {id: name}} used to annotate IDs
    (e.g. ship or item IDs from the catalog), like named-entity output in
    sniff parsers.
    """
    header_len = None; width = schema.get('opcode_width', 1)
    for header, row in read_message_log(log_path):
        if header_len is None:
            f = header.get('framing', {}) if header else schema.get('framing', {})
            header_len = int(f.get('offset', 0)) + int(f.get('size', 2))
            width = header.get('opcode_width', width) if header else width
        raw = bytes.fromhex(row['hex'])
        body = raw[header_len + width:]
        spec = schema.get('types', {}).get(row['type'], {})
        fields, error = decode_fields(body, spec.get('fields') or [{'name': 'payload', 'type': 'rest'}])
        names = {}
        for pattern, table in (entity_names or {}).items():
            for key, value in fields.items():
                if re.search(pattern, key, re.I) and isinstance(value, int) and value in table:
                    names[key] = table[value]
        yield {'i': row['i'], 't': row['t'], 'dir': row['dir'], 'type': row['type'],
               'name': spec.get('name') or row['type'], 'fields': fields,
               **({'entities': names} if names else {}), **({'decode_error': error} if error else {})}


def export_decoded(log_path, schema, out_dir, *, entity_names=None):
    """Decoded JSONL + SQLite (one table per named message type) for emulator work."""
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    db_path = out / 'Decoded-Messages.sqlite3'
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    counts = Counter(); errors = Counter(); created = set()
    try:
        conn.execute('CREATE TABLE messages (i INTEGER, t REAL, dir TEXT, type TEXT, name TEXT, fields_json TEXT, decode_error TEXT)')
        with (out / 'Decoded-Messages.jsonl').open('w', encoding='utf-8') as fh:
            for rec in decode_log(log_path, schema, entity_names=entity_names):
                fh.write(json.dumps(rec, ensure_ascii=False) + '\n')
                counts[rec['name']] += 1
                if rec.get('decode_error'):
                    errors[rec['name']] += 1
                conn.execute('INSERT INTO messages VALUES (?,?,?,?,?,?,?)',
                             (rec['i'], rec['t'], rec['dir'], rec['type'], rec['name'],
                              json.dumps(rec['fields'], ensure_ascii=False), rec.get('decode_error')))
                spec = schema.get('types', {}).get(rec['type'], {})
                if spec.get('name') and spec.get('fields') and not rec.get('decode_error'):
                    table = 'msg_' + re.sub(r'\W+', '_', spec['name'])[:60]
                    cols = [re.sub(r'\W+', '_', f['name'])[:60] for f in spec['fields']]
                    if table not in created:
                        conn.execute(f'CREATE TABLE IF NOT EXISTS "{table}" (i INTEGER, t REAL, dir TEXT, '
                                     + ', '.join(f'"{c}"' for c in cols) + ')')
                        created.add(table)
                    values = [rec['fields'].get(f['name']) for f in spec['fields']]
                    conn.execute(f'INSERT INTO "{table}" VALUES (?,?,?,' + ','.join('?' * len(cols)) + ')',
                                 (rec['i'], rec['t'], rec['dir'], *values))
        conn.commit()
    finally:
        conn.close()
    summary = {'output_dir': str(out), 'messages': sum(counts.values()), 'by_type': dict(counts.most_common()),
               'decode_errors': dict(errors), 'tables': sorted(created),
               'note': 'Decoded with YOUR schema; fields are hypotheses until verified against client code.'}
    (out / 'Decode-Summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    return summary


# ----------------------------------------------------------- tool exports

def _ident(name, fallback):
    ident = re.sub(r'\W+', '_', str(name or '')).strip('_')
    return (ident if ident and not ident[0].isdigit() else fallback)[:60]


def wireshark_lua(schema, *, port=23771, proto_name='wosb'):
    """Generate a Wireshark Lua dissector (desegments TCP using the framing)."""
    f = schema.get('framing') or {'offset': 0, 'size': 2, 'endian': 'little', 'inclusive': False}
    width = int(schema.get('opcode_width', 1))
    header = int(f['offset']) + int(f['size'])
    read = {1: 'uint', 2: 'uint', 4: 'uint'}[int(f['size'])]
    le = 'le_' if f.get('endian') == 'little' and int(f['size']) > 1 else ''
    names = {}
    for type_id, spec in schema.get('types', {}).items():
        direction, _, op = type_id.partition(':')
        if op.startswith('0x'):
            names[(direction, int(op, 16))] = spec.get('name') or type_id
    lines = ['-- Generated by WoSB Workbench Protocol Lab. Fields are research hypotheses.',
             f'local p = Proto("{proto_name}", "World of Sea Battle (research)")',
             f'local f_len = ProtoField.uint{int(f["size"]) * 8}("{proto_name}.length", "Length")',
             f'local f_op = ProtoField.uint{width * 8}("{proto_name}.opcode", "Opcode", base.HEX)',
             f'local f_name = ProtoField.string("{proto_name}.name", "Message")',
             f'local f_body = ProtoField.bytes("{proto_name}.body", "Body")',
             'local fields = {f_len, f_op, f_name, f_body}',
             'local names = {']
    for (direction, op), name in sorted(names.items()):
        lines.append(f'  ["{direction}:{op}"] = "{str(name).replace(chr(34), "")}",')
    lines += ['}', 'local type_fields = {}']
    ws_types = {'int8': ('int8', 1, 'int'), 'uint8': ('uint8', 1, 'uint'), 'int16': ('int16', 2, 'int'),
                'uint16': ('uint16', 2, 'uint'), 'int32': ('int32', 4, 'int'), 'uint32': ('uint32', 4, 'uint'),
                'int64': ('int64', 8, 'int64'), 'uint64': ('uint64', 8, 'uint64'), 'float32': ('float', 4, 'float'),
                'float64': ('double', 8, 'float'), 'bool': ('uint8', 1, 'uint')}
    for type_id, spec in schema.get('types', {}).items():
        specs = []
        for fld in spec.get('fields', []):
            base = fld['type'].replace('_be', '')
            if base not in ws_types:
                break  # stop at the first variable-length field
            ws, size, _ = ws_types[base]
            ident = _ident(fld['name'], 'f')
            var = 'tf_' + _ident(type_id, 't') + '_' + ident
            lines.append(f'local {var} = ProtoField.{ws}("{proto_name}.{_ident(spec.get("name"), _ident(type_id, "t")).lower()}.{ident.lower()}", "{ident}")')
            lines.append(f'table.insert(fields, {var})')
            specs.append(f'{{{var}, {size}, {"true" if fld["type"].endswith("_be") else "false"}}}')
        if specs:
            lines.append(f'type_fields["{type_id}"] = {{{", ".join(specs)}}}')
    lines += ['p.fields = fields', '',
              f'local HEADER = {header}', f'local OPW = {width}', f'local PORT = {int(port)}', '',
              'local function msg_len(tvb, offset)',
              f'  local v = tvb(offset + {int(f["offset"])}, {int(f["size"])}):{le}{read}()',
              ('  return v' if f.get('inclusive') else '  return v + HEADER'),
              'end', '',
              'function p.dissector(tvb, pinfo, tree)',
              '  local offset = 0',
              '  local dir = (pinfo.dst_port == PORT) and "client" or "server"',
              '  while offset < tvb:len() do',
              '    if tvb:len() - offset < HEADER then pinfo.desegment_offset = offset; pinfo.desegment_len = DESEGMENT_ONE_MORE_SEGMENT; return end',
              '    local len = msg_len(tvb, offset)',
              '    if len < HEADER then return end',
              '    if tvb:len() - offset < len then pinfo.desegment_offset = offset; pinfo.desegment_len = len - (tvb:len() - offset); return end',
              '    local sub = tree:add(p, tvb(offset, len))',
              f'    sub:add{"_le" if le else ""}(f_len, tvb(offset + {int(f["offset"])}, {int(f["size"])}))',
              '    if len >= HEADER + OPW then',
              f'      local op = tvb(offset + HEADER, OPW):{"le_" if width > 1 else ""}uint()',
              '      local key = dir .. ":" .. op',
              '      local name = names[key] or (dir .. ":0x" .. string.format("%x", op))',
              f'      sub:add{"_le" if width > 1 else ""}(f_op, tvb(offset + HEADER, OPW))',
              '      sub:add(f_name, name)',
              '      sub:append_text(" " .. name)',
              '      pinfo.cols.info:append(" " .. name)',
              '      local pos = offset + HEADER + OPW',
              '      local defs = type_fields[dir .. ":0x" .. string.format("%x", op)]',
              '      if defs then for _, d in ipairs(defs) do',
              '        if pos + d[2] > offset + len then break end',
              '        if d[3] then sub:add(d[1], tvb(pos, d[2])) else sub:add_le(d[1], tvb(pos, d[2])) end',
              '        pos = pos + d[2]',
              '      end end',
              '      if offset + len > pos then sub:add(f_body, tvb(pos, offset + len - pos)) end',
              '    end',
              '    offset = offset + len',
              '  end',
              '  pinfo.cols.protocol = "WoSB"',
              'end', '',
              'DissectorTable.get("tcp.port"):add(PORT, p)', '']
    return '\n'.join(lines)


def imhex_pattern(schema):
    """ImHex pattern for a raw stream of messages (e.g. one message log's hex dumped to a file)."""
    f = schema.get('framing') or {'offset': 0, 'size': 2, 'endian': 'little', 'inclusive': False}
    ints = {1: 'u8', 2: 'u16', 4: 'u32'}
    hx = {'int8': 's8', 'uint8': 'u8', 'int16': 's16', 'uint16': 'u16', 'int32': 's32', 'uint32': 'u32',
          'int64': 's64', 'uint64': 'u64', 'float32': 'float', 'float64': 'double', 'bool': 'bool'}
    width = ints[int(schema.get('opcode_width', 1))]
    out = ['// Generated by WoSB Workbench Protocol Lab (research hypotheses).',
           '#pragma endian ' + ('little' if f.get('endian', 'little') == 'little' else 'big'), '']
    for type_id, spec in schema.get('types', {}).items():
        fields = [fl for fl in spec.get('fields', []) if fl['type'].replace('_be', '') in hx]
        if not fields:
            continue
        out.append(f'struct {_ident(spec.get("name"), "T_" + _ident(type_id, "t"))} {{')
        out += [f'    {hx[fl["type"].replace("_be", "")]} {_ident(fl["name"], "f")};' for fl in fields]
        out.append('};')
    pre = f'    u8 pre[{int(f["offset"])}];' if int(f['offset']) else ''
    length_expr = 'length' if f.get('inclusive') else f'length + {int(f["offset"]) + int(f["size"])}'
    out += ['', 'struct Message {', *([pre] if pre else []),
            f'    {ints[int(f["size"])]} length;', f'    {width} opcode;',
            f'    u8 body[({length_expr}) - {int(f["offset"]) + int(f["size"])} - sizeof(opcode)];', '};', '',
            'Message messages[while(!std::mem::eof())] @ 0x00;']
    return '\n'.join(out)


def kaitai_struct(schema, *, ident='wosb_messages'):
    """Kaitai Struct .ksy for a raw message stream."""
    f = schema.get('framing') or {'offset': 0, 'size': 2, 'endian': 'little', 'inclusive': False}
    kt = {1: 'u1', 2: 'u2', 4: 'u4'}
    ks = {'int8': 's1', 'uint8': 'u1', 'int16': 's2', 'uint16': 'u2', 'int32': 's4', 'uint32': 'u4',
          'int64': 's8', 'uint64': 'u8', 'float32': 'f4', 'float64': 'f8', 'bool': 'u1'}
    header = int(f['offset']) + int(f['size'])
    size_expr = 'length - ' + str(header) if f.get('inclusive') else 'length'
    lines = ['meta:', f'  id: {ident}', '  endian: ' + ('le' if f.get('endian', 'little') == 'little' else 'be'),
             'doc: Generated by WoSB Workbench Protocol Lab; fields are research hypotheses.',
             'seq:', '  - id: messages', '    type: message', '    repeat: eos', 'types:', '  message:', '    seq:']
    if int(f['offset']):
        lines += ['      - id: pre', f'        size: {int(f["offset"])}']
    lines += ['      - id: length', f'        type: {kt[int(f["size"])]}',
              '      - id: body', f'        size: {size_expr}']
    for type_id, spec in schema.get('types', {}).items():
        fields = [fl for fl in spec.get('fields', []) if fl['type'].replace('_be', '') in ks]
        if not fields:
            continue
        lines += [f'  {_ident(spec.get("name"), "t_" + _ident(type_id, "t")).lower()}:', '    seq:']
        for fl in fields:
            lines += [f'      - id: {_ident(fl["name"], "f").lower()}', f'        type: {ks[fl["type"].replace("_be", "")]}']
    return '\n'.join(lines) + '\n'


def export_tools(schema, out_dir, *, port=23771):
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    (out / 'wosb_dissector.lua').write_text(wireshark_lua(schema, port=port), encoding='utf-8')
    (out / 'wosb_messages.hexpat').write_text(imhex_pattern(schema), encoding='utf-8')
    (out / 'wosb_messages.ksy').write_text(kaitai_struct(schema), encoding='utf-8')
    (out / 'README-Exports.txt').write_text(
        'Wireshark: copy wosb_dissector.lua to %APPDATA%\\Wireshark\\plugins\\ and reload Lua plugins (Ctrl+Shift+L).\n'
        'ImHex: open a raw stream file and load wosb_messages.hexpat in the Pattern Editor.\n'
        'Kaitai: open wosb_messages.ksy in the Kaitai Web IDE with a raw stream file.\n'
        'All definitions come from your schema and remain hypotheses until verified.\n', encoding='utf-8')
    return [str(out / n) for n in ('wosb_dissector.lua', 'wosb_messages.hexpat', 'wosb_messages.ksy')]


def entity_tables_from_catalog(db_path):
    """{field-name pattern: {id: name}} from the Workbench catalog for annotating decoded IDs."""
    patterns = {r'ship': ('ShipsToPlay',), r'(cannon|gun)': ('Cannons',), r'(ammo|ball|shell)': ('CannonBalls',),
                r'(item|resource|good)': ('Resources', 'Items'), r'(port|city)': ('Ports',)}
    out = {}
    from contextlib import closing
    with closing(sqlite3.connect(Path(db_path).resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        for pattern, datasets in patterns.items():
            table = {}
            for dataset in datasets:
                for raw, name in conn.execute('SELECT raw_json, name FROM records WHERE dataset=?', (dataset,)):
                    try:
                        rid = int(json.loads(raw).get('ID'))
                    except (TypeError, ValueError):
                        continue
                    table.setdefault(rid, name)
            if table:
                out[pattern] = table
    return out
