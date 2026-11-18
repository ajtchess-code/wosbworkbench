"""Protocol Lab: offline message reconstruction from the user's own captures.

Works entirely on PCAP/PCAPNG files the user recorded of their own game
session. Nothing here sends packets, proxies or modifies traffic, or attempts
to decrypt anything. When payloads look encrypted/compressed this is reported
(byte entropy) instead of guessed at.

Pipeline
    1. reassemble_tcp()      directional TCP byte streams (SYN-aware, wrap-safe,
                             retransmit/overlap trimming, gap splitting)
    2. detect_framing()      scores length-prefix layouts (1/2/4 bytes, LE/BE,
                             offset 0-2, length including/excluding header)
    3. split_messages()      cuts each stream into application messages
    4. build_catalog()       groups messages by opcode candidate; per-type size,
                             direction, timing, entropy and constant-byte masks
    5. correlate_markers()   which message types are over-represented around
                             your gameplay markers (shot, hit, sunk, ...)
    6. match_definitions()   overlap with opcode enums extracted statically from
                             the client DLLs (engine/protocol_extract.py)

Outputs distinguish observed facts (bytes, sizes, timing) from hypotheses
(framing choice, opcode position, marker association).
"""
from __future__ import annotations

import csv
import json
import math
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

FORMAT = 'wosb-protocol-catalog-v1'
MAX_STREAM_BYTES = 256 * 1024 * 1024
MAX_MESSAGES = 2_000_000
SAMPLE_PREFIX_BYTES = 48


# ---------------------------------------------------------------- reassembly

@dataclass
class Stream:
    key: tuple            # (src, sport, dst, dport)
    direction: str        # 'client' (to server port) / 'server' / 'unknown'
    chunks: list = field(default_factory=list)   # [(stream_offset, timestamp, bytes)]
    gaps: int = 0
    gap_bytes: int = 0
    retransmits: int = 0
    overlaps: int = 0

    def contiguous_runs(self):
        """Yield (bytes, [(offset_in_run, timestamp)]) for each gap-free run."""
        run = bytearray(); marks = []; expected = None
        for pos, stamp, data in self.chunks:
            if expected is not None and pos != expected:
                if run:
                    yield bytes(run), marks
                run = bytearray(); marks = []
            marks.append((len(run), stamp)); run.extend(data); expected = pos + len(data)
        if run:
            yield bytes(run), marks


def _open_packets(path):
    from network_lab import iter_pcap, iter_pcapng
    path = Path(path)
    with path.open('rb') as fh:
        magic = fh.read(4)
    return iter_pcapng(path) if magic == b'\x0a\x0d\x0d\x0a' else iter_pcap(path)


def reassemble_tcp(paths, *, server_port=None, max_bytes=MAX_STREAM_BYTES):
    """Reassemble directional TCP streams from one or more capture files.

    ``server_port`` (e.g. the game port) labels direction and filters streams.
    Ring-buffer captures can be passed as several files in capture order.
    """
    from network_lab import _decode_packet
    if isinstance(paths, (str, Path)):
        paths = [paths]
    raw = defaultdict(list); syn = {}; total = 0; frames = 0
    for path in paths:
        for stamp, link, data in _open_packets(path):
            frames += 1
            pkt = _decode_packet(data, link)
            if not pkt or pkt['proto'] != 'TCP':
                continue
            if server_port and server_port not in (pkt['sport'], pkt['dport']):
                continue
            key = (pkt['src'], pkt['sport'], pkt['dst'], pkt['dport'])
            if pkt['flags'] & 0x02:          # SYN consumes one sequence number
                syn[key] = (pkt['sequence'] + 1) & 0xffffffff
            payload = pkt['payload']
            if not payload:
                continue
            total += len(payload)
            if total > max_bytes:
                raise ValueError('Capture payload exceeds Protocol Lab memory bound; split the capture')
            raw[key].append((pkt['sequence'], stamp, payload))
    streams = []
    for key, segments in raw.items():
        base = syn.get(key, segments[0][0])
        direction = ('client' if key[3] == server_port else 'server' if key[1] == server_port else 'unknown') if server_port else 'unknown'
        stream = Stream(key, direction)
        ordered = sorted((((seq - base) & 0xffffffff), stamp, data) for seq, stamp, data in segments)
        expected = 0
        for pos, stamp, data in ordered:
            end = pos + len(data)
            if end <= expected:
                stream.retransmits += 1; continue
            if pos < expected:
                stream.overlaps += 1; data = data[expected - pos:]; pos = expected
            if pos > expected:
                stream.gaps += 1; stream.gap_bytes += pos - expected
            stream.chunks.append((pos, stamp, data)); expected = pos + len(data)
        streams.append(stream)
    return {'streams': streams, 'frames': frames, 'payload_bytes': total}


# ------------------------------------------------------------------- framing

@dataclass(frozen=True)
class Framing:
    offset: int          # bytes before the length field (e.g. a type byte)
    size: int            # 1, 2 or 4
    endian: str          # 'little' / 'big'
    inclusive: bool      # length counts the header itself
    adjust: int = 0      # constant added to the length value

    @property
    def header(self):
        return self.offset + self.size

    def frame_length(self, buf, pos):
        if pos + self.header > len(buf):
            return None
        value = int.from_bytes(buf[pos + self.offset:pos + self.header], self.endian) + self.adjust
        length = value if self.inclusive else value + self.header
        return length if length >= self.header and length > 0 else None

    def describe(self):
        return (f'{self.size * 8}-bit {self.endian}-endian length at byte {self.offset}, '
                + ('includes header' if self.inclusive else 'excludes header')
                + (f', adjust {self.adjust:+d}' if self.adjust else ''))

    def as_dict(self):
        return {'offset': self.offset, 'size': self.size, 'endian': self.endian,
                'inclusive': self.inclusive, 'adjust': self.adjust, 'description': self.describe()}


def candidate_framings():
    out = []
    for offset in (0, 1, 2):
        for size in (1, 2, 4):
            for endian in (('little', 'big') if size > 1 else ('little',)):
                for inclusive in (False, True):
                    out.append(Framing(offset, size, endian, inclusive))
    return out


def _walk(buf, framing, limit=None):
    pos = 0; frames = 0
    while pos < len(buf):
        length = framing.frame_length(buf, pos)
        if length is None or pos + length > len(buf):
            break
        pos += length; frames += 1
        if limit and frames >= limit:
            break
    return pos, frames


def sync_offset(buf, framing, *, max_scan=512, window=16 * 1024, lookahead=64):
    """Offset from which frames parse back-to-back through the sample window.

    Captures started after the TCP connection opened begin mid-message. Junk
    alignments can also parse (one huge bogus frame swallowing real ones), so
    among starts that walk to the end of the window, the one yielding the most
    frames wins; scanning stops ``lookahead`` bytes after the first good start.
    """
    def walk(start):
        view = buf[start:start + window]
        pos, frames = _walk(view, framing)
        return (frames >= 3 and len(view) - pos < 4096), frames, pos
    good, frames0, _ = walk(0)
    if good and frames0 >= 64:
        return 0
    best = (frames0 if good else -1, 0); fallback = (0, 0); first_good = 0 if good else None
    for start in range(1, min(max_scan, len(buf))):
        if first_good is not None and start > first_good + lookahead:
            break
        good, frames, pos = walk(start)
        if good:
            if first_good is None:
                first_good = start
            if frames > best[0]:
                best = (frames, start)
        elif pos > fallback[0]:
            fallback = (pos, start)
    return best[1] if best[0] >= 0 else fallback[1]


def score_framing(runs, framing, sample_bytes=2 * 1024 * 1024):
    """Fraction of sampled stream bytes consumed by back-to-back frames."""
    consumed = 0; total = 0; frames = 0; lengths = Counter()
    for buf in runs:
        buf = buf[:sample_bytes]
        if not buf:
            continue
        total += len(buf)                     # skipped resync bytes count as unconsumed
        view = buf[sync_offset(buf, framing):]
        pos, count = _walk(view, framing)
        consumed += pos; frames += count
        p = 0
        for _ in range(min(count, 200)):
            n = framing.frame_length(view, p); lengths[n] += 1; p += n
    if not total or frames < 2:
        return {'coverage': 0.0, 'frames': frames}
    distinct = len(lengths)   # one giant frame per run is not an informative framing
    sampled = sum(lengths.values()) or 1
    # Header-only (empty body) frames are the signature of a wrong layout, e.g. reading
    # the always-zero high byte of a 16-bit length as an 8-bit length.
    empty = sum(c for n, c in lengths.items() if n is not None and n <= framing.header) / sampled
    score = consumed / total * min(1.0, math.log2(frames + 1) / 6) * (1.0 if distinct > 1 else 0.6) * (1 - empty) ** 2
    return {'coverage': round(consumed / total, 4), 'frames': frames, 'distinct_lengths': distinct,
            'empty_frame_fraction': round(empty, 4), 'score': round(score, 4)}


def detect_framing(runs, candidates=None):
    """Rank candidate length-prefix layouts. Returns list, best first."""
    runs = [r for r in runs if r]
    ranked = []
    for framing in candidates or candidate_framings():
        result = score_framing(runs, framing)
        if result.get('score'):
            ranked.append({**framing.as_dict(), **result, '_framing': framing})
    ranked.sort(key=lambda r: (-r['score'], r['offset'], r['size']))
    return ranked


def split_messages(buf, marks, framing):
    """Cut a contiguous run into messages; trailing partial frame is reported."""
    messages = []; pos = sync_offset(buf, framing); mark_i = 0
    while pos < len(buf):
        length = framing.frame_length(buf, pos)
        if length is None or pos + length > len(buf):
            break
        while mark_i + 1 < len(marks) and marks[mark_i + 1][0] <= pos:
            mark_i += 1
        messages.append((marks[mark_i][1] if marks else None, buf[pos:pos + length]))
        pos += length
    return messages, len(buf) - pos


# ------------------------------------------------------------------- catalog

def entropy(data):
    if not data:
        return 0.0
    counts = Counter(data); n = len(data)
    return -sum(c / n * math.log2(c / n) for c in counts.values())


def _opcode(body, width, endian='little'):
    if len(body) < width:
        return None
    return int.from_bytes(body[:width], endian)


def choose_opcode_width(messages, framing):
    """Prefer the opcode width whose values are few, repeated and stable."""
    best = None
    for width in (1, 2, 4):
        values = Counter()
        for _, _, msg in messages:
            op = _opcode(msg[framing.header:], width)
            if op is not None:
                values[op] += 1
        if not values:
            continue
        n = sum(values.values())
        top = sum(c for _, c in values.most_common(64)) / n
        # Few distinct values that cover most messages look like a type field.
        quality = top / math.log2(len(values) + 2)
        if best is None or quality > best[1] * 1.15:
            best = (width, quality, len(values))
    return {'width': best[0], 'distinct_values': best[2], 'quality': round(best[1], 4)} if best else {'width': 1}


def _constant_mask(samples, limit=SAMPLE_PREFIX_BYTES):
    """For each byte position, 'C' when constant across samples, '.' otherwise."""
    if not samples:
        return ''
    width = min(limit, min(len(s) for s in samples))
    return ''.join('C' if len({s[i] for s in samples}) == 1 else '.' for i in range(width))


def build_catalog(messages, framing, opcode_width=None, *, keep_samples=0):
    """messages: [(direction, timestamp, bytes)]."""
    width = opcode_width or choose_opcode_width(messages, framing)['width']
    groups = defaultdict(list)
    for direction, stamp, msg in messages:
        op = _opcode(msg[framing.header:], width)
        groups[(direction, op)].append((stamp, msg))
    types = []
    for (direction, op), items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        sizes = [len(m) for _, m in items]
        stamps = sorted(s for s, _ in items if s is not None)
        gaps = [b - a for a, b in zip(stamps, stamps[1:]) if b >= a]
        bodies = [m[framing.header:] for _, m in items[:400]]
        ent = statistics.mean(entropy(b) for b in bodies) if bodies else 0
        row = {'type_id': f'{direction}:{"none" if op is None else hex(op)}', 'direction': direction,
               'opcode_candidate': op, 'count': len(items),
               'size_min': min(sizes), 'size_max': max(sizes), 'size_mean': round(statistics.mean(sizes), 2),
               'fixed_size': len(set(sizes)) == 1,
               'mean_interval_s': round(statistics.mean(gaps), 4) if gaps else None,
               'periodic_hint': bool(gaps) and len(gaps) > 5 and statistics.pstdev(gaps) < 0.15 * max(1e-9, statistics.mean(gaps)),
               'first_seen': stamps[0] if stamps else None,
               'body_entropy_bits': round(ent, 3),
               'opaque_hint': ent > 7.5 and statistics.mean(sizes) > 64,
               'constant_byte_mask': _constant_mask(bodies)}
        try:
            from protocol_schema import infer_fields
            row['field_hints'] = infer_fields([m[framing.header + width:] for _, m in items[:300]])
        except Exception:
            row['field_hints'] = []
        if keep_samples:
            row['private_samples_hex'] = [m[:SAMPLE_PREFIX_BYTES].hex() for _, m in items[:keep_samples]]
        types.append(row)
    return {'opcode_width': width, 'types': types}


# --------------------------------------------------------------- correlation

def _ts(value):
    if isinstance(value, (int, float)):
        return float(value)
    d = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.timestamp()


def correlate_markers(messages, markers, framing, opcode_width, *, window=1.5, min_events=2):
    """Lift = rate of a message type near markers of one kind vs its overall rate.

    Association only. A high lift across many repetitions is a strong lead
    (e.g. which client message is sent on a broadside), not proof.
    """
    stamped = [(s, d, _opcode(m[framing.header:], opcode_width)) for d, s, m in messages if s is not None]
    if not stamped or not markers:
        return []
    stamped.sort(key=lambda row: row[0])
    t0, t1 = stamped[0][0], stamped[-1][0]
    duration = max(1e-6, t1 - t0)
    overall = Counter((d, op) for _, d, op in stamped)
    by_kind = defaultdict(list)
    for mk in markers:
        try:
            by_kind[str(mk.get('kind') or mk.get('category') or 'event')].append(
                _ts(mk.get('utc') or mk.get('event_utc') or mk.get('timestamp_utc')))
        except (TypeError, ValueError):
            continue
    import bisect
    times = [s for s, _, _ in stamped]
    results = []
    for kind, moments in by_kind.items():
        if len(moments) < min_events:
            continue
        near = Counter(); covered = 0.0
        for t in moments:
            lo = bisect.bisect_left(times, t - window); hi = bisect.bisect_right(times, t + window)
            seen = {(stamped[i][1], stamped[i][2]) for i in range(lo, hi)}
            for k in seen:
                near[k] += 1
            covered += 2 * window
        for (direction, op), hits in near.most_common(25):
            expected_rate = overall[(direction, op)] / duration * 2 * window
            p_present = min(1.0, expected_rate)
            lift = (hits / len(moments)) / max(p_present, 1e-6)
            if hits >= min_events and lift >= 1.5:
                results.append({'marker_kind': kind, 'type_id': f'{direction}:{"none" if op is None else hex(op)}',
                                'markers': len(moments), 'markers_with_type_nearby': hits,
                                'lift': round(lift, 2), 'window_s': window,
                                'evidence': 'temporal association across repeated markers; verify with code and controlled tests'})
    results.sort(key=lambda r: (r['marker_kind'], -r['lift']))
    return results


def match_definitions(catalog, protocol_definitions):
    """Compare observed opcode candidates with statically extracted opcode enums."""
    observed = {t['opcode_candidate'] for t in catalog.get('types', []) if t['opcode_candidate'] is not None}
    matches = []
    for enum in protocol_definitions.get('opcode_enums', []):
        values = {int(v): k for k, v in enum.get('members', {}).items() if isinstance(v, (int, float))}
        if not values:
            continue
        hit = observed & set(values)
        if hit:
            matches.append({'enum': enum['name'], 'assembly': enum.get('assembly'),
                            'observed_overlap': len(hit), 'enum_members': len(values),
                            'observed_types': len(observed),
                            'coverage_of_observed': round(len(hit) / max(1, len(observed)), 3),
                            'named': {hex(v): values[v] for v in sorted(hit)[:200]}})
    matches.sort(key=lambda m: -m['coverage_of_observed'])
    return matches


# ------------------------------------------------------------------ pipeline

def analyze(paths, *, server_port=None, markers=None, framing=None, opcode_width=None,
            definitions=None, keep_samples=0):
    data = reassemble_tcp(paths, server_port=server_port)
    runs_by_stream = [(s, list(s.contiguous_runs())) for s in data['streams']]
    # Framing detection samples the largest runs only; splitting still uses every run.
    sample_runs = sorted((buf for _, runs in runs_by_stream for buf, _ in runs), key=len, reverse=True)[:64]
    ranking = detect_framing(sample_runs)
    chosen = framing or (ranking[0]['_framing'] if ranking else None)
    messages = []; leftovers = 0
    stream_rows = []
    for stream, runs in runs_by_stream:
        count = 0
        if chosen:
            for buf, marks in runs:
                msgs, rest = split_messages(buf, marks, chosen)
                leftovers += rest; count += len(msgs)
                messages.extend((stream.direction, s, m) for s, m in msgs)
                if len(messages) > MAX_MESSAGES:
                    raise ValueError('Too many messages; analyze a shorter capture')
        stream_rows.append({'ports': [stream.key[1], stream.key[3]], 'direction': stream.direction,
                            'bytes': sum(len(c[2]) for c in stream.chunks), 'messages': count,
                            'gaps': stream.gaps, 'gap_bytes': stream.gap_bytes,
                            'retransmits': stream.retransmits, 'overlaps': stream.overlaps})
    catalog = build_catalog(messages, chosen, opcode_width, keep_samples=keep_samples) if chosen and messages else {'types': []}
    width = catalog.get('opcode_width', 1)
    all_bytes = b''.join(m[:256] for _, _, m in messages[:4000])
    result = {
        'format': FORMAT, 'generated_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'frames_read': data['frames'], 'payload_bytes': data['payload_bytes'], 'server_port': server_port,
        'streams': stream_rows,
        'framing': chosen.as_dict() if chosen else None,
        'framing_alternatives': [{k: v for k, v in r.items() if k != '_framing'} for r in ranking[:6]],
        'messages': len(messages), 'unframed_tail_bytes': leftovers,
        'payload_entropy_bits': round(entropy(all_bytes), 3),
        'catalog': catalog,
        'marker_associations': correlate_markers(messages, markers or [], chosen, width) if chosen else [],
        'definition_matches': match_definitions(catalog, definitions) if definitions else [],
        'evidence': {'observed': 'TCP bytes, sizes, timing and directions from your own capture',
                     'hypothesis': 'framing layout, opcode position and marker associations',
                     'not_done': 'no decryption, no traffic modification, no server contact'}}
    if result['payload_entropy_bits'] > 7.6:
        result['warning'] = ('Payload bytes are near-random (entropy > 7.6 bits/byte): the stream is probably '
                             'encrypted or compressed, so framing/opcode results are unreliable.')
    return result


def export_message_log(paths, dest, *, server_port=None, framing=None, opcode_width=None, max_messages=MAX_MESSAGES):
    """Write every reassembled message, in time order, as JSON lines (local, PRIVATE).

    This is the input for writing and regression-testing a message parser or an
    offline emulator fixture. It contains raw bytes of your own session (which can
    include your account name, chat or session data), so it is never added to the
    shareable review exports. Returns a summary dict.
    """
    data = reassemble_tcp(paths, server_port=server_port)
    runs = [(s, list(s.contiguous_runs())) for s in data['streams']]
    chosen = framing or (detect_framing([b for _, r in runs for b, _ in r]) or [{}])[0].get('_framing')
    if chosen is None:
        raise ValueError('No consistent length-prefix framing found; the stream may be encrypted or use another layout')
    rows = []
    for stream, stream_runs in runs:
        for run_index, (buf, marks) in enumerate(stream_runs):
            msgs, _ = split_messages(buf, marks, chosen)
            rows.extend((t, stream.direction, run_index, m) for t, m in msgs)
    rows.sort(key=lambda r: (r[0] if r[0] is not None else 0))
    width = opcode_width or choose_opcode_width([(d, t, m) for t, d, _, m in rows], chosen)['width']
    dest = Path(dest); dest.parent.mkdir(parents=True, exist_ok=True)
    origin = rows[0][0] if rows and rows[0][0] is not None else 0
    with dest.open('w', encoding='utf-8') as fh:
        fh.write(json.dumps({'_header': {'format': 'wosb-message-log-v1', 'framing': chosen.as_dict(),
                                         'opcode_width': width, 'server_port': server_port,
                                         'privacy': 'PRIVATE raw bytes of your own session; do not share'}}) + '\n')
        for i, (t, direction, run_index, m) in enumerate(rows[:max_messages]):
            op = _opcode(m[chosen.header:], width)
            fh.write(json.dumps({'i': i, 't': round((t or 0) - origin, 6), 'dir': direction, 'run': run_index,
                                 'type': f'{direction}:{"none" if op is None else hex(op)}', 'len': len(m),
                                 'hex': m.hex()}) + '\n')
    return {'output': str(dest), 'messages': min(len(rows), max_messages), 'framing': chosen.describe(), 'opcode_width': width}


def write_reports(result, out_dir):
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    (out / 'Protocol-Catalog.json').write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    with (out / 'Message-Types.csv').open('w', newline='', encoding='utf-8-sig') as fh:
        cols = ['type_id', 'direction', 'opcode_candidate', 'count', 'size_min', 'size_max', 'size_mean',
                'fixed_size', 'mean_interval_s', 'periodic_hint', 'body_entropy_bits', 'opaque_hint', 'constant_byte_mask']
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction='ignore'); w.writeheader()
        for row in result['catalog'].get('types', []):
            w.writerow(row)
    with (out / 'Marker-Associations.csv').open('w', newline='', encoding='utf-8-sig') as fh:
        cols = ['marker_kind', 'type_id', 'markers', 'markers_with_type_nearby', 'lift', 'window_s']
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction='ignore'); w.writeheader()
        for row in result.get('marker_associations', []):
            w.writerow(row)
    return out / 'Protocol-Catalog.json'


def load_markers(path):
    """Accept gameplay events.jsonl, a JSON list, or a Network Lab export."""
    p = Path(path)
    text = p.read_text(encoding='utf-8')
    if p.suffix.lower() == '.jsonl':
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    data = json.loads(text)
    if isinstance(data, dict):
        data = data.get('events') or data.get('markers') or []
    return [x for x in data if isinstance(x, dict)]


def analyze_session_folder(folder, *, definitions=None, keep_samples=0):
    """Convenience: Gameplay Capture Studio folder (session.json + game-traffic*.pcapng)."""
    folder = Path(folder)
    meta = json.loads((folder / 'session.json').read_text(encoding='utf-8'))
    files = sorted(p for p in folder.glob('game-traffic*.pcapng') if p.is_file() and p.stat().st_size)
    if not files:
        raise FileNotFoundError('No game-traffic*.pcapng in session folder')
    markers = load_markers(folder / 'events.jsonl') if (folder / 'events.jsonl').is_file() else []
    return analyze(files, server_port=int(meta['capture']['port']), markers=markers,
                   definitions=definitions, keep_samples=keep_samples)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description='Offline message framing/catalog for your own WoSB captures')
    ap.add_argument('captures', nargs='+', help='PCAP/PCAPNG files in capture order, or one session folder')
    ap.add_argument('--port', type=int, help='Game server port (labels client/server direction)')
    ap.add_argument('--markers', help='events.jsonl or JSON event list')
    ap.add_argument('--definitions', help='Protocol-Definitions.json from protocol_extract')
    ap.add_argument('--samples', type=int, default=0, help='Keep N private hex samples per type (local only)')
    ap.add_argument('--message-log', help='Also write every message as private JSONL to this path')
    ap.add_argument('--out', required=True)
    a = ap.parse_args(argv)
    defs = json.loads(Path(a.definitions).read_text(encoding='utf-8')) if a.definitions else None
    if len(a.captures) == 1 and Path(a.captures[0]).is_dir():
        result = analyze_session_folder(a.captures[0], definitions=defs, keep_samples=a.samples)
    else:
        result = analyze(a.captures, server_port=a.port, markers=load_markers(a.markers) if a.markers else None,
                         definitions=defs, keep_samples=a.samples)
    print(write_reports(result, a.out))
    if a.message_log and not Path(a.captures[0]).is_dir():
        print(export_message_log(a.captures, a.message_log, server_port=a.port))
    print(f"{result['messages']:,} messages · {len(result['catalog'].get('types', []))} type candidates · "
          f"framing: {result['framing']['description'] if result['framing'] else 'none found'}")


if __name__ == '__main__':
    main()
