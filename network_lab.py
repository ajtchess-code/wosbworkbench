"""WoSB Network Research Lab: passive, offline packet metadata research.

No decryption, injection, proxying, replay or manipulation. By default not a
single byte of packet payload or complete address is persisted to the catalog.
"""
from __future__ import annotations
import hashlib
import ipaddress
import json
import os
import re
import shutil
import struct
import subprocess
import time
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

MAX_CAPTURE_BYTES = 2 * 1024**3
MAX_PACKETS = 2_000_000
MAX_PACKET_SIZE = 2 * 1024 * 1024
PROTO = {6:'TCP',17:'UDP'}


def _utc(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec='milliseconds')


def _read_exact(f, size):
    result=f.read(size)
    if len(result)!=size: raise ValueError('Truncated capture file')
    return result


def _l3(packet, linktype):
    if linktype == 1: # Ethernet II
        if len(packet)<14:return None
        eth=int.from_bytes(packet[12:14],'big');pos=14
        for _ in range(2):
            if eth not in (0x8100,0x88a8,0x9100):break
            if len(packet)<pos+4:return None
            eth=int.from_bytes(packet[pos+2:pos+4],'big');pos+=4
        return (packet[pos:],eth)
    if linktype in (101,228,229): # Raw IP / IPv4 / IPv6
        if not packet:return None
        return packet, (0x0800 if packet[0]>>4 ==4 else 0x86dd)
    if linktype == 113: # Linux cooked capture v1
        if len(packet)<16:return None
        return packet[16:],int.from_bytes(packet[14:16],'big')
    if linktype == 276: # Linux cooked capture v2
        if len(packet)<20:return None
        return packet[20:],int.from_bytes(packet[:2],'big')
    if linktype == 0: # BSD null / loopback
        if len(packet)<4:return None
        family=int.from_bytes(packet[:4],'little')
        return packet[4:], 0x0800 if family==2 else 0x86dd if family in (10,24,28,30) else 0
    return None


def _decode_packet(raw, linktype):
    found=_l3(raw,linktype)
    if not found:return None
    packet,eth=found
    if eth==0x0800:
        if len(packet)<20 or packet[0]>>4 !=4:return None
        ihl=(packet[0]&15)*4
        if ihl<20 or len(packet)<ihl:return None
        length=min(len(packet),int.from_bytes(packet[2:4],'big'))
        if length<ihl:return None
        flags_offset=int.from_bytes(packet[6:8],'big')
        # Do not parse non-first fragments as transport headers.
        if flags_offset & 0x1fff:return None
        proto=packet[9];src=str(ipaddress.IPv4Address(packet[12:16]));dst=str(ipaddress.IPv4Address(packet[16:20]));transport=packet[ihl:length]
    elif eth==0x86dd:
        if len(packet)<40 or packet[0]>>4 !=6:return None
        proto=packet[6];src=str(ipaddress.IPv6Address(packet[8:24]));dst=str(ipaddress.IPv6Address(packet[24:40]))
        end=min(len(packet),40+int.from_bytes(packet[4:6],'big'));p=40
        for _ in range(10):
            if proto in (0,43,60):
                if p+2>end:return None
                nex=packet[p];size=(packet[p+1]+1)*8
            elif proto==44:
                if p+8>end:return None
                if (int.from_bytes(packet[p+2:p+4],'big')>>3)!=0:return None
                nex=packet[p];size=8
            elif proto==51:
                if p+2>end:return None
                nex=packet[p];size=(packet[p+1]+2)*4
            else:break
            if p+size>end:return None
            p+=size;proto=nex
        transport=packet[p:end]
    else:return None
    if proto not in (6,17) or len(transport)<8:return None
    sport,dport=struct.unpack_from('!HH',transport)
    if proto==6:
        if len(transport)<20:return None
        hdr=(transport[12]>>4)*4
        if hdr<20 or hdr>len(transport):return None
        flags=transport[13];payload=transport[hdr:];tcp_sequence=struct.unpack_from('!I',transport,4)[0]
    else:
        length=struct.unpack_from('!H',transport,4)[0]
        if length<8:return None
        flags=0;tcp_sequence=None;payload=transport[8:min(len(transport),length)]
    return {'proto':PROTO[proto],'src':src,'dst':dst,'sport':sport,'dport':dport,
            'flags':flags,'sequence':tcp_sequence,'size':len(raw),'payload_size':len(payload),'payload':payload}


def iter_pcap(path):
    """Yield timestamp, link type, bytes for pcap files, bounded by size/packet count."""
    path=Path(path)
    if path.stat().st_size>MAX_CAPTURE_BYTES:raise ValueError('Capture exceeds 2 GB import safety limit')
    with path.open('rb') as f:
        magic=_read_exact(f,4)
        formats={b'\xd4\xc3\xb2\xa1':('<',1e6),b'\xa1\xb2\xc3\xd4':('>',1e6),
                 b'\x4d\x3c\xb2\xa1':('<',1e9),b'\xa1\xb2\x3c\x4d':('>',1e9)}
        if magic not in formats:raise ValueError('Not a supported PCAP file')
        endian,scale=formats[magic]
        ver_major,ver_minor,_,_,snaplen,linktype=struct.unpack(endian+'HHiIII',_read_exact(f,20))
        if (ver_major,ver_minor)!=(2,4):raise ValueError('Unsupported PCAP version')
        for i in range(MAX_PACKETS):
            header=f.read(16)
            if not header:return
            if len(header)!=16:
                if i:return  # capture stopped mid-write: keep the complete packets
                raise ValueError('Incomplete PCAP packet header')
            sec,sub,caplen,_=struct.unpack(endian+'IIII',header)
            if caplen>MAX_PACKET_SIZE:raise ValueError('Oversized packet')
            data=f.read(caplen)
            if len(data)!=caplen:
                if i:return  # truncated final packet after a forced stop
                raise ValueError('Truncated capture file')
            yield sec+sub/scale,linktype,data
        raise ValueError('Too many packets; split capture into smaller files')


def iter_pcapng(path):
    """Parse SHB, IDB and EPB blocks, timestamp resolution and interface IDs."""
    path=Path(path)
    if path.stat().st_size>MAX_CAPTURE_BYTES:raise ValueError('Capture exceeds 2 GB import safety limit')
    count=0;endian=None;interfaces=[]
    with path.open('rb') as f:
        while True:
            block=f.read(8)
            if not block:return
            if len(block)!=8:
                if interfaces:return  # trailing partial block header after a forced stop
                raise ValueError('Truncated PCAPNG block')
            if block[:4]==b'\x0a\x0d\x0d\x0a':
                bom=_read_exact(f,4)
                if bom==b'\x4d\x3c\x2b\x1a':endian='<'
                elif bom==b'\x1a\x2b\x3c\x4d':endian='>'
                else:raise ValueError('Invalid section byte order')
                size=struct.unpack(endian+'I',block[4:])[0]
                if size<28 or size>16*1024*1024:raise ValueError('Bad section length')
                rest=_read_exact(f,size-12)
                if struct.unpack(endian+'I',rest[-4:])[0]!=size:raise ValueError('Bad section trailer')
                interfaces=[]
                continue
            if endian is None:raise ValueError('PCAPNG missing section header')
            kind,size=struct.unpack(endian+'II',block)
            if size<12 or size%4 or size>16*1024*1024:raise ValueError('Invalid PCAPNG block size')
            body=f.read(size-8)
            if len(body)!=size-8:
                if interfaces:return  # final block cut off when the capture was stopped
                raise ValueError('Truncated capture file')
            if struct.unpack(endian+'I',body[-4:])[0]!=size:raise ValueError('Invalid PCAPNG trailer')
            data=body[:-4]
            if kind==1 and len(data)>=8:
                linktype=struct.unpack_from(endian+'H',data)[0];resolution=1e-6;offset=0
                options=data[8:];p=0
                while p+4<=len(options):
                    code,olen=struct.unpack_from(endian+'HH',options,p);p+=4
                    if code==0:break
                    if p+olen>len(options):break
                    val=options[p:p+olen];p+=(olen+3)&~3
                    if code==9 and val:
                        resolution=2.0**-(val[0]&127) if val[0]&128 else 10.0**-val[0]
                    if code==14 and len(val)==8:offset=struct.unpack(endian+'q',val)[0]
                interfaces.append((linktype,resolution,offset))
            if kind==6 and len(data)>=20:
                iid,hi,lo,caplen,_=struct.unpack_from(endian+'IIIII',data)
                if caplen>MAX_PACKET_SIZE:raise ValueError('Oversized packet')
                if iid>=len(interfaces) or len(data)<20+caplen:continue
                linktype,resolution,offset=interfaces[iid]
                count+=1
                if count>MAX_PACKETS:raise ValueError('Too many packets; split capture')
                yield ((hi<<32)|lo)*resolution+offset,linktype,data[20:20+caplen]


def _sha256_file(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as fh:
        for chunk in iter(lambda:fh.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()


def _event_timestamp(value):
    """Parse an ISO event time; naive values are UTC (never the PC's local zone)."""
    parsed=datetime.fromisoformat(str(value).replace('Z','+00:00'))
    if parsed.tzinfo is None:parsed=parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _prefix(value):
    ip=ipaddress.ip_address(value)
    return str(ipaddress.ip_network(f'{ip}/{24 if ip.version==4 else 48}',strict=False))


def _classifier(payload,proto,sport,dport):
    """Purely observational hints, never assert the traffic is WoSB traffic."""
    if proto=='TCP' and (sport==443 or dport==443):return 'TLS/HTTPS candidate'
    if proto=='UDP' and (sport==443 or dport==443):return 'QUIC candidate'
    if len(payload)>=3 and payload[:3] in (b'GET',b'POS',b'PUT',b'HEA'):return 'HTTP candidate'
    if len(payload)>5 and payload[0]==22 and payload[1]==3:return 'TLS handshake candidate'
    if proto=='UDP' and (sport==53 or dport==53):return 'DNS candidate'
    return 'unknown binary/other'


def _framing_hints(payload):
    """Find repeated length-prefix candidates, never interpreting user content."""
    found=[]
    for size in (2,4):
        if len(payload)<=size:continue
        for endian in ('little','big'):
            value=int.from_bytes(payload[:size],endian)
            if value in (len(payload),len(payload)-size):
                found.append(f'{size * 8}-bit {endian} length prefix')
    return found


def analyze_capture(path, *, label='', max_packets=MAX_PACKETS, progress=None):
    """Return address-redacted summaries and a fixed-time bin series. No payload bytes retained."""
    path=Path(path).resolve(strict=True)
    with path.open('rb') as fh: magic=fh.read(4)
    packets=iter_pcapng(path) if magic==b'\x0a\x0d\x0d\x0a' else iter_pcap(path)
    flows={};bins=defaultdict(lambda:[0,0]);protocols=Counter();hints=Counter();issues=Counter();start=None;end=None
    for n,(stamp,linktype,raw) in enumerate(packets):
        if n>=max_packets:break
        if progress and n%5000==0:progress(n)
        parsed=_decode_packet(raw,linktype)
        if not parsed:issues['unsupported_or_fragmented']+=1;continue
        if start is None:start=stamp
        end=stamp
        # Canonical bidirectional flow. Redacted prefix only in output.
        a=(parsed['src'],parsed['sport']);b=(parsed['dst'],parsed['dport']);k=(parsed['proto'],*sorted((a,b)))
        if k not in flows:
            flows[k]={'protocol':parsed['proto'],'endpoint_a_prefix':_prefix(k[1][0]),
                'endpoint_b_prefix':_prefix(k[2][0]),'port_a':k[1][1],'port_b':k[2][1],
                'packets':0,'bytes':0,'payload_bytes':0,'first_ts':stamp,'last_ts':stamp,
                'classifications':Counter(),'framing_hints':Counter()}
        fl=flows[k];fl['packets']+=1;fl['bytes']+=parsed['size'];fl['payload_bytes']+=parsed['payload_size'];fl['last_ts']=stamp
        hint=_classifier(parsed['payload'],parsed['proto'],parsed['sport'],parsed['dport'])
        fl['classifications'][hint]+=1
        for framing in _framing_hints(parsed['payload']):fl['framing_hints'][framing]+=1
        protocols[parsed['proto']]+=1;hints[hint]+=1
        binidx=int(stamp//1) # UTC seconds; no information about other packet contents
        bins[binidx][0]+=1;bins[binidx][1]+=parsed['size']
    flowlist=[]
    for i,fl in enumerate(sorted(flows.values(),key=lambda x:x['bytes'],reverse=True)):
        fl['id']=f'flow-{i+1}';fl['first_utc']=_utc(fl.pop('first_ts'));fl['last_utc']=_utc(fl.pop('last_ts'))
        fl['classifications']=dict(fl['classifications']);fl['framing_hints']=dict(fl['framing_hints']);flowlist.append(fl)
    return {'format':'wosb-network-research-1','label':label or path.stem,
        'capture_sha256':_sha256_file(path),
        'first_utc':_utc(start) if start is not None else None,'last_utc':_utc(end) if end is not None else None,
        'packet_count':sum(protocols.values()),'flows':flowlist,'protocols':dict(protocols),
        'classifications':dict(hints),'skipped':dict(issues),
        'timeline':[{'utc':_utc(sec),'packets':v[0],'bytes':v[1]} for sec,v in sorted(bins.items())],
        'privacy':'No payloads, full IP addresses, or authentication data exported. Address network prefixes may still be sensitive.'}


def init_db(conn):
    conn.executescript('''
      CREATE TABLE IF NOT EXISTS network_sessions (
        id TEXT PRIMARY KEY,label TEXT NOT NULL,filename TEXT NOT NULL,
        summary_json TEXT NOT NULL,created_utc TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS network_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,session_id TEXT NOT NULL,
        event_utc TEXT NOT NULL,category TEXT NOT NULL,note TEXT NOT NULL,
        FOREIGN KEY(session_id) REFERENCES network_sessions(id));
      CREATE INDEX IF NOT EXISTS ix_network_events_session ON network_events(session_id,event_utc);
    ''')
    conn.commit()


def save_session(conn,summary,source_path):
    init_db(conn);sid=str(uuid.uuid4());created=_utc(time.time())
    conn.execute('INSERT INTO network_sessions VALUES(?,?,?,?,?)',
        (sid,summary['label'],str(Path(source_path).resolve()),json.dumps(summary),created));conn.commit();return sid


def list_sessions(conn):
    init_db(conn)
    return conn.execute('SELECT id,label,created_utc,filename FROM network_sessions ORDER BY created_utc DESC').fetchall()


def get_summary(conn,sid):
    result=conn.execute('SELECT summary_json FROM network_sessions WHERE id=?',(sid,)).fetchone()
    if not result:raise KeyError('Unknown capture session')
    return json.loads(result[0])


def add_event(conn,sid,event_utc,category,note):
    if not conn.execute('SELECT 1 FROM network_sessions WHERE id=?',(sid,)).fetchone():raise KeyError('Unknown capture session')
    datetime.fromisoformat(event_utc.replace('Z','+00:00'))
    conn.execute('INSERT INTO network_events(session_id,event_utc,category,note) VALUES (?,?,?,?)',
                 (sid,event_utc,str(category)[:80],str(note)[:1200]));conn.commit()


def event_correlations(summary,events,window_seconds=5):
    """Time proximity only; NEVER proof that the packets represent the event."""
    result=[]
    # Parse bin times once (previously re-parsed for every event: O(events × bins) parses).
    bins=[(_event_timestamp(b['utc']),b) for b in summary.get('timeline',[])]
    for ev in events:
        stamp=_event_timestamp(ev['event_utc'])
        nearby=[b for t,b in bins if abs(t-stamp)<=window_seconds]
        result.append({'category':ev['category'],'event_utc':ev['event_utc'],'note':ev['note'],
                       'window_seconds':window_seconds,'packets':sum(b['packets'] for b in nearby),
                       'bytes':sum(b['bytes'] for b in nearby),'confidence':'temporal-only; not decoded game messages'})
    return result


def export_research(conn,sid,destination,*,include_endpoint_prefixes=False):
    """Export only safe aggregated metadata; no original pcap or payloads."""
    summary=get_summary(conn,sid)
    if not include_endpoint_prefixes:
        for fl in summary['flows']:
            fl.pop('endpoint_a_prefix',None);fl.pop('endpoint_b_prefix',None)
    events=[{'event_utc':r[0],'category':r[1],'note':r[2]} for r in conn.execute('SELECT event_utc,category,note FROM network_events WHERE session_id=? ORDER BY event_utc',(sid,))]
    out={'session':summary,'events':events,'temporal_correlations':event_correlations(summary,events),
         'warning':'No causal attribution or server-authoritative formula is established by timestamp correlations.'}
    dest=Path(destination);dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(out,indent=2,ensure_ascii=False),encoding='utf-8');return dest


def find_tshark():
    found=shutil.which('tshark')
    if found:return found
    if os.name=='nt':
        for prefix in (os.environ.get('ProgramFiles',''),os.environ.get('ProgramFiles(x86)','')):
            p=Path(prefix)/'Wireshark'/'tshark.exe'
            if p.is_file():return str(p)
    return None


def list_interfaces(tshark=None):
    executable=tshark or find_tshark()
    if not executable:raise FileNotFoundError('Wireshark/TShark is not installed. Import an existing .pcapng instead.')
    result=subprocess.run([executable,'-D'],capture_output=True,text=True,timeout=12,check=True)
    return [line for line in result.stdout.splitlines() if re.match(r'^\d+\.',line)]


def start_capture(interface_index,output_path,*,tshark=None,bpf='tcp or udp'):
    """Opt-in, passive capture on a selected interface, no process instrumentation."""
    executable=tshark or find_tshark()
    if not executable:raise FileNotFoundError('Install Wireshark with TShark/Npcap to capture traffic')
    if not re.fullmatch(r'[1-9]\d*',str(interface_index)):raise ValueError('Select an interface number from TShark -D')
    path=Path(output_path).resolve();path.parent.mkdir(parents=True,exist_ok=True)
    if path.suffix.lower()!='.pcapng':raise ValueError('Capture output must have .pcapng extension')
    # Single output file at exactly ``path``; TShark stops itself before the 2 GB
    # import limit. A new process group lets stop_capture() send CTRL_BREAK so
    # TShark/dumpcap flush the final block instead of being killed mid-write.
    limit_kb=str(int(MAX_CAPTURE_BYTES*0.95)//1000)
    flags=getattr(subprocess,'CREATE_NEW_PROCESS_GROUP',0)|getattr(subprocess,'CREATE_NO_WINDOW',0) if os.name=='nt' else 0
    if not re.fullmatch(r'[a-z0-9 ()]{1,80}',str(bpf)):raise ValueError('Unsupported capture filter')
    return subprocess.Popen([executable,'-i',str(interface_index),'-f',str(bpf),
        '-a','filesize:'+limit_kb,'-w',str(path)],stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=flags)


def stop_capture(proc,*,timeout=8):
    """Stop a capture started by start_capture(), gracefully where possible."""
    if proc is None or proc.poll() is not None:return
    if os.name=='nt':
        import signal
        try:
            proc.send_signal(signal.CTRL_BREAK_EVENT);proc.wait(timeout=timeout);return
        except (OSError,ValueError,subprocess.TimeoutExpired):pass
    try:
        proc.terminate();proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:proc.wait(timeout=3)
        except subprocess.TimeoutExpired:pass
