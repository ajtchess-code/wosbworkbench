"""Local TCP/UDP traffic continuity, timing and target-identity research.

Never exports raw packet bytes, full IP addresses, session tokens, or credentials.
No inference that a candidate payload family is an actual WoSB game message.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import hashlib, json, math, statistics


def _timestamp(value):
    if isinstance(value,(float,int)):return float(value)
    s=str(value).strip().replace('Z','+00:00')
    d=datetime.fromisoformat(s)
    if d.tzinfo is None:raise ValueError('Timestamp must have timezone')
    return d.timestamp()


def fit_clocks(pairs):
    """Fit game-video seconds as affine function of capture-clock seconds."""
    if not pairs:raise ValueError('At least one matched event pair required')
    xs=[_timestamp(x['capture_utc']) for x in pairs]
    ys=[float(x['video_seconds']) for x in pairs]
    if any(not math.isfinite(x) for x in xs+ys):raise ValueError('Invalid sync point')
    origin=xs[0];local=[x-origin for x in xs]
    var=sum((x-statistics.mean(local))**2 for x in local)
    slope=(sum((x-statistics.mean(local))*(y-statistics.mean(ys)) for x,y in zip(local,ys))/var) if var>1e-6 else 1.
    offset=statistics.mean(ys)-slope*statistics.mean(local)
    residual=[y-(offset+slope*x) for x,y in zip(local,ys)]
    return {'format':'wosb-clock-calibration-v1','capture_origin_utc':datetime.fromtimestamp(origin,timezone.utc).isoformat(),
            'video_offset_seconds':offset,'video_seconds_per_capture_second':slope,
            'drift_ms_per_minute':(slope-1)*60000,
            'max_residual_ms':round(max(abs(r) for r in residual)*1000,4),
            'measurements':len(pairs),'status':'observed offsets; game event correspondences must be manually verified'}


def assign_target_ids(events):
    """Stable target identity from explicit tracking tokens, never proximity guesses."""
    known={};out=[];ambiguous=0
    for event in events:
        e=dict(event)
        token=e.get('target_guid') or e.get('target_token')
        if token is None:
            e['target_stable_id']=None;e['identity_evidence']='missing';ambiguous+=1
        else:
            token=str(token).strip()
            if not token:raise ValueError('Empty explicit target identifier')
            # Truncated local-hash alias rather than exporting player names/IDs.
            alias=known.setdefault(token, 'target-'+hashlib.sha256(token.encode()).hexdigest()[:12])
            e.pop('target_guid',None);e.pop('target_token',None)
            e['target_stable_id']=alias;e['identity_evidence']='explicit source token alias'
        out.append(e)
    return {'format':'wosb-target-association-v1','events':out,'identified':len(out)-ambiguous,
            'ambiguous':ambiguous,'warning':'Never combine ambiguous targets solely because they appear near the same timestamp.'}


def _segment_signature(payload,proto,sport,dport):
    from network_lab import _classifier, _framing_hints
    return {'bytes':len(payload),'class':_classifier(payload,proto,sport,dport),
            'framing_hints':_framing_hints(payload),
            'first_byte_family':f'0x{payload[0]:02x}' if payload else None}


def analyze_stream_continuity(pcap_path,*,max_packets=1_000_000,max_tracked_bytes=64*1024*1024):
    """Reassemble bounded directional TCP streams and characterize gap/retransmits.

    Contiguous data is not decoded as WoSB application messages; the byte buffers
    are discarded after deriving aggregated lengths and framing hints.
    """
    from network_lab import _decode_packet, iter_pcap, iter_pcapng
    p=Path(pcap_path).resolve(strict=True)
    with p.open('rb') as f:magic=f.read(4)
    iterator=iter_pcapng(p) if magic==b'\x0a\x0d\x0d\x0a' else iter_pcap(p)  # pcapng SHB magic
    streams=defaultdict(list);udp=Counter();skipped=Counter();used=0;num=0
    for stamp,kind,raw in iterator:
        num+=1
        if num>max_packets:raise ValueError('Packet limit exceeded')
        item=_decode_packet(raw,kind)
        if not item:skipped['unparsed_fragment_or_protocol']+=1;continue
        payload=item['payload']; key=(item['proto'],item['src'],item['sport'],item['dst'],item['dport'])
        if item['proto']=='TCP':
            if not payload:continue
            used+=len(payload)
            if used>max_tracked_bytes:raise ValueError('Tracked payload exceeds research memory bound')
            streams[key].append((item['sequence'],stamp,payload))
        else:
            udp[(item['sport'],item['dport'],len(payload)//128)]+=1
    summary=[]
    for key,segments in streams.items():
        # Sequence-based ordering, with natural 32-bit wrap handled relative to
        # first SEEN sequence, not numerical sorting across the wrap boundary.
        base=segments[0][0]
        indexed=sorted((((s-base)&0xffffffff),stamp,data) for s,stamp,data in segments)
        expected=0;dup=0;overlap=0;gaps=0;fragments=[];buf=bytearray();current=0
        for pos,stamp,data in indexed:
            end=pos+len(data)
            if end<=expected:
                dup+=1;continue
            if pos<expected:
                overlap+=1;data=data[expected-pos:];pos=expected
            if pos>expected:
                gaps+=pos-expected
                if buf:
                    fragments.append(bytes(buf));buf.clear()
            buf.extend(data);expected=pos+len(data);current+=len(data)
        if buf:fragments.append(bytes(buf))
        candidates=Counter()
        for fragment in fragments[:1000]:
            sig=_segment_signature(fragment,key[0],key[2],key[4]);candidates[sig['class']]+=1
            for hint in sig['framing_hints']:candidates[hint]+=1
        # Fully anonymize stream endpoint by a per-file non-exported key fingerprint.
        summary.append({'stream_id':'stream-'+str(len(summary)+1), 'transport':key[0],
                        'ports':[key[2],key[4]],'segments':len(segments),'contiguous_bytes':current,
                        'missing_sequence_bytes':gaps,'retransmitted_segments':dup,
                        'overlapping_segments':overlap,'contiguous_fragments':len(fragments),
                        'candidate_protocols':dict(candidates),'application_message_decode':'unknown'})
    return {'format':'wosb-network-continuity-v1','tcp_streams':summary,
            'udp_datagram_groups':len(udp),'frames_seen':num,'skipped':dict(skipped),
            'privacy':'No payload bytes or full endpoint addresses retained; port numbers retained',
            'interpretation':'TCP delivery continuity is measured. Protocol message IDs and gameplay semantics are NOT asserted.'}


def save_analysis(pcap,output):
    result=analyze_stream_continuity(pcap)
    target=Path(output);target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result
