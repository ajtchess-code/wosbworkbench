"""Opt-in WoSB gameplay observation studio.

Launches external FFmpeg/TShark (when installed) to capture the screen and
passively record the *user's own* game connection, then adds timestamped
research markers. Never injects, decrypts, sends packets, or alters the game.

The raw video/PCAP are private and excluded from review exports by default.
All timestamps use UTC; the FFmpeg launch time is a *provisional* video origin
which can be adjusted by video_offset_seconds using a visible sync flash.
"""
from __future__ import annotations

from fsutil import replace_with_retry
import argparse
import tempfile
import math
import csv
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import time
import uuid
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from network_lab import _decode_packet, find_tshark, iter_pcap, iter_pcapng

GAME_PROCESS='WorldOfSeaBattleClient'
KNOWN_PORT=23771  # Proven by a user Get-NetTCPConnection snapshot; check per session.
FORMAT_VERSION=1
MAX_REVIEW_BIN=200_000
ALLOWED_MARKERS={'single-shot','broadside','bow','stern','side','sails','hit','miss','target-sunk','health','sync-flash','note','mortar','heavy-mortar','barrel','deflection','minor-fire','large-fire'}


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def utc_timestamp(src):
    return datetime.fromisoformat(src.replace('Z','+00:00')).timestamp()


def find_ffmpeg():
    """Discover FFmpeg even when WinGet's user PATH hasn't propagated to the EXE."""
    return find_video_tool('ffmpeg')


def find_video_tool(name):
    if name not in ('ffmpeg','ffprobe'):
        raise ValueError('Unsupported video utility')
    executable=name+'.exe' if os.name=='nt' else name
    found=shutil.which(executable) or shutil.which(name)
    if found:return found
    if os.name=='nt':
        roots=(os.environ.get('LOCALAPPDATA',''),os.environ.get('ProgramFiles',''),
               os.environ.get('ProgramFiles(x86)',''))
        candidates=[]
        if roots[0]:
            candidates.extend((Path(roots[0])/'Microsoft/WinGet/Links'/executable,
                               Path(roots[0])/'Programs/ffmpeg/bin'/executable))
        for root in roots[1:]:
            if root:candidates.extend((Path(root)/'FFmpeg/bin'/executable,Path(root)/'ffmpeg/bin'/executable))
        return next((str(v) for v in candidates if v.is_file()),None)
    return None


def detect_game_capture_interface(port=KNOWN_PORT, *, runner=None, tshark=None):
    """Map the *local* WoSB TCP route to a TShark adapter without persisting IPs.

    Never guesses interface 1 when routing information is unavailable. The
    function can be mocked in unit tests and does not capture payloads.
    """
    if os.name!='nt' and runner is None:return None
    if not 1<=int(port)<=65535:raise ValueError('Invalid game port')
    ps=(
        "$links=Get-NetTCPConnection -RemotePort %d -State Established -ErrorAction SilentlyContinue; "
        "$results=@(foreach($link in $links) { "
        "$p=Get-Process -Id $link.OwningProcess -ErrorAction SilentlyContinue; "
        "if($p.ProcessName -ne '%s'){continue}; "
        "$ip=Get-NetIPAddress -IPAddress $link.LocalAddress -ErrorAction SilentlyContinue | Select-Object -First 1; "
        "if($null -eq $ip){continue}; "
        "$ad=Get-NetAdapter -InterfaceIndex $ip.InterfaceIndex -ErrorAction SilentlyContinue; "
        "if($null -ne $ad){[PSCustomObject]@{Alias=$ad.Name;Guid=[string]$ad.InterfaceGuid}} "
        "}); $results | ConvertTo-Json -Compress" % (int(port),GAME_PROCESS)
    )
    call=runner or (lambda args:subprocess.run(args,capture_output=True,text=True,timeout=15))
    try:
        r=call(['powershell.exe','-NoProfile','-NonInteractive','-Command',ps])
        raw=(r.stdout or '').strip()
        if not raw:return None
        entries=json.loads(raw);entries=entries if isinstance(entries,list) else [entries]
        aliases={(str(x.get('Alias','')).strip().casefold(),
                  str(x.get('Guid','')).strip('{}').casefold()) for x in entries}
        executable=tshark or find_tshark()
        if not executable:return None
        response=call([executable,'-D'])
        matches=[]
        for line in (response.stdout or '').splitlines():
            matched=re.match(r'^\s*(\d+)\.\s*(.*)$',line)
            if not matched:continue
            index,description=matched.groups();description_lower=description.casefold()
            for alias,guid in aliases:
                if guid and len(guid)>20 and guid in description_lower:
                    matches.append((index,description,'route-guid'));break
                if alias and re.search(r'\('+re.escape(alias)+r'\)\s*$',description_lower):
                    matches.append((index,description,'route-alias'));break
        choices={item[0]:item for item in matches}
        if len(choices)!=1:return None
        idx,description,method=next(iter(choices.values()))
        return {'interface':idx,'label':description,'method':method,'port':int(port)}
    except (ValueError,TypeError,KeyError,OSError,subprocess.SubprocessError,json.JSONDecodeError):
        return None


def capture_traffic_health(folder,*,port=KNOWN_PORT,max_frames=120):
    """Verify real TCP payloads, not merely PCAPNG headers or a saved filename.

    Bounded scan to keep the recording stop action responsive. Does not expose
    payload bytes, IP addresses or session material.
    """
    files=_pcap_files(folder)
    scanned=0;matching=0;payloads=0
    for file in files:
        with file.open('rb') as fp:magic=fp.read(4)
        packets=iter_pcapng(file) if magic==b'\x0a\x0d\x0d\x0a' else iter_pcap(file)
        for _,link,raw in packets:
            scanned+=1
            pkt=_decode_packet(raw,link)
            if pkt and pkt['proto']=='TCP' and (pkt['sport']==port or pkt['dport']==port):
                matching+=1
                if pkt['payload']:payloads+=1
            if scanned>=max_frames:break
        if scanned>=max_frames:break
    return {'capture_files':len(files),'frames_examined':scanned,
            'game_tcp_frames':matching,'game_payload_frames':payloads,
            'status':'active_game_traffic' if payloads else 'no_game_payloads',
            'warning':None if payloads else ('No WoSB TCP payloads found in sampled capture frames; '
                'check the selected adapter and actual game connection before relying on this session.')}


def preview_interface_traffic(interface,*,port=KNOWN_PORT,seconds=3,tshark=None,runner=None):
    """Optional preflight: short, payload-free TShark probe on selected adapter."""
    if not re.fullmatch(r'[1-9]\d*',str(interface)):
        raise ValueError('Invalid capture adapter number')
    if not 1<=int(seconds)<=8:raise ValueError('Invalid probe duration')
    exe=tshark or find_tshark()
    if not exe:raise FileNotFoundError('TShark missing')
    cmd=[exe,'-i',str(interface),'-a','duration:'+str(int(seconds)),
         '-f','tcp port '+str(int(port)),'-T','fields','-e','frame.number']
    call=runner or (lambda args:subprocess.run(args,capture_output=True,text=True,timeout=seconds+14))
    result=call(cmd)
    frames=sum(1 for line in (result.stdout or '').splitlines() if line.strip().isdigit())
    return {'interface':str(interface),'game_frames':frames,'active':frames>0,
            'status':'traffic_seen' if frames else 'no_traffic_during_probe'}


def game_process_connection(port=KNOWN_PORT, *,runner=None):
    """Read-only ownership check. No remote IP or authentication information saved."""
    if os.name!='nt' and runner is None:return {'confirmed':False,'reason':'Windows only; owner check unavailable'}
    if not 1<=int(port)<=65535:raise ValueError('Invalid game port')
    if runner is None:
        try:
            import win_proc
            found=win_proc.game_connections(GAME_PROCESS,port=int(port))
            if found:return {'confirmed':True,'process':GAME_PROCESS,'pid':found[0]['pid'],'port':int(port)}
            return {'confirmed':False,'reason':'No matching established game connection'}
        except (OSError,AttributeError,ValueError):
            pass
    ps=("Get-NetTCPConnection -RemotePort %d -State Established -ErrorAction SilentlyContinue | "
        "ForEach-Object { $p=Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue; "
        "if ($p.ProcessName -eq '%s') { [PSCustomObject]@{ PID=$p.Id; Name=$p.ProcessName; Port=$_.RemotePort } } } | ConvertTo-Json -Compress" %
        (int(port),GAME_PROCESS))
    run=runner or (lambda cmd:subprocess.run(cmd,capture_output=True,text=True,timeout=12))
    try:
        result=run(['powershell.exe','-NoProfile','-NonInteractive','-Command',ps])
        raw=(result.stdout or '').strip()
        if not raw:return {'confirmed':False,'reason':'No matching established game connection'}
        data=json.loads(raw);data=data[0] if isinstance(data,list) else data
        if data.get('Name')!=GAME_PROCESS or int(data.get('Port',0))!=int(port):
            return {'confirmed':False,'reason':'Not owned by WoSB client'}
        return {'confirmed':True,'process':GAME_PROCESS,'pid':int(data['PID']),'port':int(port)}
    except (subprocess.SubprocessError, ValueError, TypeError, KeyError, json.JSONDecodeError, OSError) as e:
        return {'confirmed':False,'reason':'Process ownership check unavailable: '+type(e).__name__}


def discover_game_ports(*,runner=None):
    """List established game-process TCP ports without returning remote addresses."""
    if os.name!='nt' and runner is None:return []
    if runner is None:
        # Native IP Helper query: no PowerShell process (and no console window) per poll.
        try:
            import win_proc
            return sorted(win_proc.game_connections(GAME_PROCESS),key=lambda x:(x['port']!=KNOWN_PORT,x['port']))
        except (OSError,AttributeError,ValueError):
            pass
    ps=("Get-NetTCPConnection -State Established -ErrorAction SilentlyContinue | "
        "ForEach-Object { $p=Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue; "
        "if ($p.ProcessName -eq 'WorldOfSeaBattleClient') { "
        "[PSCustomObject]@{PID=$p.Id;Port=$_.RemotePort;Name=$p.ProcessName} } } | ConvertTo-Json -Compress")
    run=runner or (lambda cmd:subprocess.run(cmd,capture_output=True,text=True,timeout=15))
    try:
        r=run(['powershell.exe','-NoProfile','-NonInteractive','-Command',ps])
        if not (r.stdout or '').strip():return []
        data=json.loads(r.stdout)
        if not isinstance(data,list):data=[data]
        seen={}
        for x in data:
            if x.get('Name')!=GAME_PROCESS:continue
            port=int(x['Port']);pid=int(x['PID'])
            if 1<=port<=65535:seen[(pid,port)]={'confirmed':True,'pid':pid,'port':port,'process':GAME_PROCESS}
        return sorted(seen.values(),key=lambda x:(x['port']!=KNOWN_PORT,x['port']))
    except (ValueError,TypeError,KeyError,OSError,subprocess.SubprocessError):return []


def _safe_note(note):
    return str(note or '').replace('\r',' ').replace('\n',' ')[:500]


def _write_atomic(path, data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    replace_with_retry(temp,path)


def _exe_probe(path):
    p=Path(path) if path else None
    if not p or not p.is_file():raise FileNotFoundError('Required recording tool missing: '+str(path))
    return str(p)


class GameplaySession:
    """Single recording session; start/stop calls are made from the GUI main thread."""
    def __init__(self,folder,*,interface='1',port=KNOWN_PORT,ffmpeg=None,tshark=None,
                 framerate=20,video_source='desktop',capture_packets=True,
                 require_confirmed_port=True,popen=None):
        self.folder=Path(folder);self.interface=str(interface);self.port=int(port)
        self.ffmpeg=ffmpeg or find_ffmpeg();self.tshark=tshark or find_tshark()
        self.framerate=int(framerate);self.video_source=str(video_source)
        self.capture_packets=bool(capture_packets)
        self.require_confirmed_port=bool(require_confirmed_port)
        self._popen=popen or subprocess.Popen
        self.proc_video=None;self.proc_capture=None;self.meta=None;self.started=False
        self._clock_anchor=None
        if not 1<=self.port<=65535:raise ValueError('Invalid game port')
        if not 5<=self.framerate<=60:raise ValueError('Framerate must be between 5 and 60')
        if not re.fullmatch(r'[1-9]\d*',self.interface):raise ValueError('Choose a TShark interface index from -D')
        if self.video_source!='desktop' and (len(self.video_source)>180 or '\n' in self.video_source or '\r' in self.video_source):
            raise ValueError('Unsafe window title')

    def start(self, *, ownership=None):
        if self.started:raise RuntimeError('Already recording')
        _exe_probe(self.ffmpeg)
        if self.capture_packets:_exe_probe(self.tshark)
        own=ownership if ownership is not None else game_process_connection(self.port)
        if self.require_confirmed_port and self.capture_packets and not own.get('confirmed'):
            raise RuntimeError('WoSB game port ownership not verified. Connect to the game and use Detect connection. '+str(own.get('reason','')))
        if self.folder.exists() and any(self.folder.iterdir()):raise FileExistsError('Session folder must be empty')
        self.folder.mkdir(parents=True,exist_ok=True)
        self._clock_anchor=time.perf_counter()
        self.meta={'format':'wosb-gameplay-evidence','schema':FORMAT_VERSION,
            'session_id':str(uuid.uuid4()),'created_utc':utc_now(),'status':'starting',
            'capture':{'video':'gameplay.mp4','pcap':'game-traffic.pcapng' if self.capture_packets else None,
                       'interface':self.interface if self.capture_packets else None,
                       'port':self.port,'filter':'tcp port '+str(self.port) if self.capture_packets else 'not collected',
                       'game_connection_confirmed':bool(own.get('confirmed')),
                       'game_pid':own.get('pid'),'video_source':self.video_source,'fps':self.framerate,
                       'video_origin':'FFmpeg process launch (approximate; align sync flash before analysis)',
                       'video_offset_seconds':0},
            'privacy':'Raw video and packet capture are private. Review ZIP excludes both by default.',
            'tools':{'ffmpeg':'external','tshark':'external' if self.capture_packets else 'not used'},
            'events_count':0}
        _write_atomic(self.folder/'session.json',self.meta)
        flags=getattr(subprocess,'CREATE_NO_WINDOW',0) if os.name=='nt' else 0
        tshark_flags=getattr(subprocess,'CREATE_NEW_PROCESS_GROUP',0) if os.name=='nt' else 0
        try:
            if self.capture_packets:
                cmd=[self.tshark,'-i',self.interface,'-f','tcp port '+str(self.port),
                     '-b','filesize:102400','-b','files:8',
                     '-w',str(self.folder/'game-traffic.pcapng')]
                with (self.folder/'tshark.log').open('wb') as log:
                    self.proc_capture=self._popen(cmd,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                                                  stderr=log,creationflags=tshark_flags)
                self.meta['capture']['pcap_launch_utc']=utc_now()
            cmd=[self.ffmpeg,'-hide_banner','-loglevel','warning','-y','-f','gdigrab',
                 '-framerate',str(self.framerate),'-draw_mouse','1','-i',
                 self.video_source if self.video_source=='desktop' else 'title='+self.video_source,
                 '-an','-c:v','libx264','-preset','ultrafast','-crf','25',
                 '-pix_fmt','yuv420p','-t','10800','-movflags','+faststart',str(self.folder/'gameplay.mp4')]
            # Record launch before the subprocess call; actual first frame may be later.
            self.meta['capture']['video_launch_utc']=utc_now()
            # The child inherits its own handle; the parent closes its copy at once.
            with (self.folder/'ffmpeg.log').open('wb') as log:
                self.proc_video=self._popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,
                                            stderr=log,creationflags=flags)
            self.started=True;self.meta['status']='recording'
            _write_atomic(self.folder/'session.json',self.meta)
        except Exception:
            self._stop_proc(self.proc_capture,graceful=False)
            self._stop_proc(self.proc_video,graceful=False)
            self.meta['status']='start_failed';_write_atomic(self.folder/'session.json',self.meta)
            raise
        return self.meta

    def mark(self,kind,note='',*,target=None,weapon=None,ammo=None):
        if not self.started:raise RuntimeError('Start recording first')
        if kind not in ALLOWED_MARKERS:raise ValueError('Unknown research event category')
        item={'utc':utc_now(),'elapsed_monotonic_seconds':round(time.perf_counter()-self._clock_anchor,3),
              'kind':kind,'note':_safe_note(note),
              'target':_safe_note(target)[:100] if target is not None else self.meta.get('fight',{}).get('target_ship',''),
              'weapon':_safe_note(weapon)[:100] if weapon is not None else self.meta.get('fight',{}).get('weapon',''),
              'ammo':_safe_note(ammo)[:100] if ammo is not None else self.meta.get('fight',{}).get('ammo','')}
        with (self.folder/'events.jsonl').open('a',encoding='utf-8') as fp:
            fp.write(json.dumps(item,ensure_ascii=False)+'\n')
        self.meta['events_count']+=1
        # Avoid rewrite on every event; JSONL append is durable.
        return item

    @staticmethod
    def _stop_proc(proc,*,graceful):
        if proc is None or proc.poll() is not None:return
        if graceful and proc.stdin:
            try:proc.stdin.write(b'q\n');proc.stdin.flush();proc.wait(timeout=12);return
            except (OSError,ValueError,subprocess.TimeoutExpired):pass
        if graceful and os.name=='nt':
            try:proc.send_signal(signal.CTRL_BREAK_EVENT);proc.wait(timeout=4);return
            except (OSError,ValueError,subprocess.TimeoutExpired):pass
        try:proc.terminate();proc.wait(timeout=6)
        except (OSError,subprocess.TimeoutExpired):
            try:proc.kill();proc.wait(timeout=2)
            except (OSError,subprocess.TimeoutExpired):pass

    def stop(self):
        if not self.started:return self.meta
        self.meta['stopped_utc']=utc_now()
        self.meta['status']='finalizing'
        _write_atomic(self.folder/'session.json',self.meta)
        self._stop_proc(self.proc_video,graceful=True)
        self._stop_proc(self.proc_capture,graceful=True)
        self.started=False
        self.meta['status']='stopped'
        self.meta['capture']['video_file_present']=(self.folder/'gameplay.mp4').is_file()
        self.meta['capture']['pcap_file_present']=any(self.folder.glob('game-traffic*.pcapng')) if self.capture_packets else False
        _write_atomic(self.folder/'session.json',self.meta)
        return self.meta


def load_session(folder):
    folder=Path(folder)
    meta=json.loads((folder/'session.json').read_text(encoding='utf-8'))
    if meta.get('schema')!=FORMAT_VERSION:raise ValueError('Unsupported session schema')
    return meta


def load_events(folder):
    path=Path(folder)/'events.jsonl'
    if not path.is_file():return []
    records=[]
    for line in path.read_text(encoding='utf-8').splitlines():
        if line.strip():
            obj=json.loads(line)
            if obj.get('kind') in ALLOWED_MARKERS and obj.get('utc'):records.append(obj)
    return records


def game_traffic_bins(pcap_paths,*,port=KNOWN_PORT,step=0.5):
    """Count TCP segments/length hints only. No decrypted payloads or IP addresses."""
    if not 0.1<=step<=5:raise ValueError('Bin width must be 0.1–5 seconds')
    bins=defaultdict(lambda:{'client_segments':0,'server_segments':0,'client_bytes':0,
                             'server_bytes':0,'client_45_bytes':0,'prefix_matches':0})
    counts=Counter();seen_seq=set();begin=None;finish=None
    for file in sorted(map(Path,pcap_paths)):
        with file.open('rb') as f:magic=f.read(4)
        packets=iter_pcapng(file) if magic==b'\x0a\x0d\x0d\x0a' else iter_pcap(file)
        for stamp,link,raw in packets:
            pkt=_decode_packet(raw,link)
            if not pkt or pkt['proto']!='TCP':continue
            if pkt['sport']!=port and pkt['dport']!=port:continue
            payload=pkt['payload']
            if not payload:continue
            # Retransmits can duplicate TCP segments; drop exact same payload at same timestamp bin.
            direction='client' if pkt['dport']==port else 'server'
            secbin=round(int(stamp/step)*step,4)
            marker=(direction,pkt['src'],pkt['dst'],pkt['sport'],pkt['dport'],pkt.get('sequence'),len(payload),hashlib.blake2s(payload,digest_size=8).digest())
            if marker in seen_seq:
                counts['duplicates_skipped']+=1;continue
            if len(seen_seq)<500_000:seen_seq.add(marker)
            b=bins[secbin]
            b[direction+'_segments']+=1;b[direction+'_bytes']+=len(payload)
            if direction=='client' and len(payload)==45:b['client_45_bytes']+=1
            if len(payload)>=4 and (int.from_bytes(payload[:2],'little') in (len(payload),len(payload)-2)):
                b['prefix_matches']+=1
            counts[direction+'_payload_segments']+=1
            if begin is None or stamp<begin:begin=stamp
            if finish is None or stamp>finish:finish=stamp
    if len(bins)>MAX_REVIEW_BIN:raise ValueError('Too many timestamp bins; increase bin width')
    return {'port':port,'bin_seconds':step,'start_utc':datetime.fromtimestamp(begin,timezone.utc).isoformat() if begin is not None else None,
            'end_utc':datetime.fromtimestamp(finish,timezone.utc).isoformat() if finish is not None else None,
            'segments':dict(counts),'timeline':[{'unix_seconds':t,**b} for t,b in sorted(bins.items())],
            'scope':'TCP payload timing only; segments are not reassembled messages, bytes may be encrypted or encoded'}


def _pcap_files(folder):
    return sorted((p for p in Path(folder).glob('game-traffic*.pcapng') if p.is_file() and p.stat().st_size),
                  key=lambda p:p.name)


def analyze_session(folder,*,video_offset_seconds=None,bin_seconds=0.5):
    folder=Path(folder);meta=load_session(folder);events=load_events(folder)
    launch=utc_timestamp(meta['capture']['video_launch_utc'])
    # Default to the sync-flash offset saved in session.json; previously a plain
    # re-analysis (stop, CLI, review export) silently reset it to zero.
    if video_offset_seconds is None:
        video_offset_seconds=meta['capture'].get('video_offset_seconds',0) or 0
    offset=float(video_offset_seconds)
    if not -120<=offset<=120:raise ValueError('Video alignment offset must be within 120 seconds')
    files=_pcap_files(folder)
    traffic=game_traffic_bins(files,port=int(meta['capture']['port']),step=bin_seconds) if files else {'timeline':[],'segments':{},'scope':'No PCAP available'}
    index=traffic['timeline'];rows=[]
    # Detect an empty or wrong-interface capture in a human-readable field.
    traffic['capture_status']='traffic_recorded' if traffic.get('segments',{}).get('client_payload_segments',0)+traffic.get('segments',{}).get('server_payload_segments',0)>0 else 'no_game_payloads'
    if traffic['capture_status']=='no_game_payloads':
        traffic['warning']='No WoSB payloads were recorded; check adapter selection. Video/markers may still be useful.'
    for ev in events:
        stamp=utc_timestamp(ev['utc']);window=[b for b in index if abs(b['unix_seconds']-stamp)<=2.5]
        counts={k:sum(b.get(k,0) for b in window) for k in ('client_segments','server_segments','client_bytes','server_bytes','client_45_bytes','prefix_matches')}
        rows.append({'utc':ev['utc'],'video_seconds_approx':round(max(0,stamp-launch+offset),3),
                     'kind':ev['kind'],'note':ev['note'],
                     'target':ev.get('target',meta.get('fight',{}).get('target_ship','')),
                     'weapon':ev.get('weapon',meta.get('fight',{}).get('weapon','')),
                     'ammo':ev.get('ammo',meta.get('fight',{}).get('ammo','')),
                     'packet_window':counts,
                     'evidence':'temporal coincidence only; not decoded WoSB game event'})
    result={'format':'wosb-gameplay-correlated-review-v1','created_utc':utc_now(),
            'video_origin_approx_utc':meta['capture']['video_launch_utc'],'video_offset_seconds':offset,
            'capture_port':meta['capture']['port'],'game_connection_confirmed':meta['capture'].get('game_connection_confirmed',False),
            'recorded_events':len(rows),'events':rows,
            'traffic':traffic,'conclusions':{'damage_formula':'not derived from packet timings',
               'damage_samples':'manual/video HP observations required',
               'attribution':'packet bursts are not identified as shots without game-code and video validation'},
            'privacy':'Raw PCAP, private addresses and video contents excluded'}
    _write_atomic(folder/'review.json',result)
    csvpath=folder/'event-timeline.csv'
    with csvpath.open('w',newline='',encoding='utf-8-sig') as fp:
        w=csv.writer(fp);w.writerow(['UTC','approx_video_s','event','target','weapon','ammo','note','client_tcp_segments_±2.5s','server_tcp_segments_±2.5s','45_byte_client_segments_±2.5s'])
        for ev in rows:
            p=ev['packet_window'];w.writerow([ev['utc'],ev['video_seconds_approx'],ev['kind'],ev['target'],ev['weapon'],ev['ammo'],ev['note'],p['client_segments'],p['server_segments'],p['client_45_bytes']])
    with (folder/'packet-timeline.csv').open('w',newline='',encoding='utf-8-sig') as fp:
        w=csv.writer(fp);w.writerow(['unix_seconds','client_segments','server_segments','client_bytes','server_bytes','client_45_bytes','prefix_matches'])
        for b in traffic['timeline']:
            w.writerow([b.get(k,'') for k in ('unix_seconds','client_segments','server_segments','client_bytes','server_bytes','client_45_bytes','prefix_matches')])
    return result


def export_sanitized_review(folder,output=None):
    folder=Path(folder);target=Path(output or (folder/'Review-Only.zip'))
    if not (folder/'review.json').exists():analyze_session(folder)
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
        for name in ('review.json','event-timeline.csv','packet-timeline.csv'):
            p=folder/name
            if p.exists():z.write(p,name)
        z.writestr('READ-ME.txt','WoSB gameplay research, sanitized metadata only. No PCAP, video, addresses, or payloads.\n'
                   'Event/packet proximity is not proof of game message identity or HP-damage mechanics.\n'
                   'Please correlate the visual events and health values separately.\n')
    return target


def fire_tally(folder):
    """Hits vs minor/large fires per ammo from the user's own markers: the input for the ignition-chance estimate."""
    out={}
    for e in load_events(folder):
        k=e.get('kind');ammo=(e.get('ammo') or 'unknown').strip() or 'unknown'
        row=out.setdefault(ammo,{'hits':0,'broadsides':0,'minor_fires':0,'large_fires':0})
        if k=='hit':row['hits']+=1
        elif k=='broadside':row['broadsides']+=1
        elif k=='minor-fire':row['minor_fires']+=1
        elif k=='large-fire':row['large_fires']+=1
    for row in out.values():
        n,x=row['hits'],row['minor_fires']
        row['rate'],row['low'],row['high']=wilson(x,n)
    return out


def wilson(x,n,z=1.96):
    """Share with a 95% Wilson interval; (None, None, None) without data."""
    if n<=0:return None,None,None
    p=min(1.0,x/n);d=1+z*z/n;c=(p+z*z/(2*n))/d;h=z*((p*(1-p)/n+z*z/(4*n*n))**0.5)/d
    return round(p,4),round(max(0.0,c-h),4),round(min(1.0,c+h),4)


def export_video_clips(folder,*,kinds=('single-shot','broadside','hit','target-sunk','sails'),
                       seconds_before=3,seconds_after=5,max_clips=10,ffmpeg=None):
    """EXPLICIT opt-in only. The clips may show in-game names, chat and personal data."""
    folder=Path(folder);exe=_exe_probe(ffmpeg or find_ffmpeg());meta=load_session(folder)
    video=folder/'gameplay.mp4'
    if not video.is_file():raise FileNotFoundError('Video not found')
    events=[e for e in load_events(folder) if e['kind'] in kinds][:max_clips]
    offset=float(meta['capture'].get('video_offset_seconds',0))
    launch=utc_timestamp(meta['capture']['video_launch_utc'])
    out=folder/'clips';out.mkdir(exist_ok=True)
    paths=[]
    for i,e in enumerate(events,1):
        elapsed=max(0,utc_timestamp(e['utc'])-launch+offset)
        start=max(0,elapsed-seconds_before);duration=seconds_before+seconds_after
        path=out/f'{i:02d}-{e["kind"]}.mp4'
        cmd=[exe,'-hide_banner','-loglevel','error','-y','-ss',f'{start:.3f}',
             '-i',str(video),'-t',str(duration),'-an','-c:v','libx264','-preset','veryfast','-crf','27',str(path)]
        subprocess.run(cmd,check=True,timeout=180)
        paths.append(path)
    return paths


def export_combat_evidence(folder,output=None,*,ffmpeg=None,ffprobe=None,
                           monitor='left',max_events=24,video_budget_mb=19):
    """Produce one upload-sized, USER-APPROVED evidence ZIP for a local session.

    Includes compressed gameplay and high-detail nearby frames, but NEVER raw
    packets, game credentials, network addresses or DLLs. Content visible in a
    video can still be sensitive. No image is claimed as a verified HP reading.
    """
    folder=Path(folder)
    if monitor not in ('left','right','none'):
        raise ValueError('Monitor must be left, right, or none')
    if not 1<=int(max_events)<=64 or not 5<=int(video_budget_mb)<=32:
        raise ValueError('Invalid export limits')
    ffmpeg=_exe_probe(ffmpeg or find_ffmpeg())
    ffprobe=_exe_probe(ffprobe or find_video_tool('ffprobe'))
    meta=load_session(folder)
    source=folder/meta.get('capture',{}).get('video','gameplay.mp4')
    if not source.is_file():raise FileNotFoundError('Original gameplay video missing')
    if not (folder/'review.json').exists():analyze_session(folder)
    review=json.loads((folder/'review.json').read_text(encoding='utf-8'))
    events=review.get('events',[])[:int(max_events)]
    proc=subprocess.run([ffprobe,'-v','error','-select_streams','v:0',
        '-show_entries','stream=width,height:format=duration','-of','json',str(source)],
        capture_output=True,text=True,timeout=35,check=True)
    detail=json.loads(proc.stdout)
    stream=detail.get('streams',[{}])[0]
    width=int(stream.get('width',0));height=int(stream.get('height',0))
    duration=float(detail.get('format',{}).get('duration',0))
    if width<=0 or height<=0 or not math.isfinite(duration) or duration<=0:
        raise ValueError('Video has invalid dimensions or duration')
    # Only crop when the input clearly represents side-by-side 16:9 displays.
    crop_applied=width>=3200 and width>=height*3 and monitor!='none'
    crop=('crop=iw/2:ih:0:0' if monitor=='left' else 'crop=iw/2:ih:iw/2:0') if crop_applied else 'null'
    video_filter=crop+',fps=12'
    # Bytes ~ bitrate*duration/8. Reserve room for full-quality event screenshots.
    kbps=max(180,min(1600,int(video_budget_mb*1024*1024*8/duration/1000*0.80)))
    destination=Path(output or folder/'Combat-Evidence-For-Review.zip')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='wosb-combat-review-') as temp:
        stage=Path(temp)
        clip=stage/'Gameplay-Review.mp4'
        encode=[ffmpeg,'-y','-hide_banner','-loglevel','error','-i',str(source),
                '-vf',video_filter,'-c:v','libx264','-preset','veryfast',
                '-b:v',f'{kbps}k','-maxrate',f'{int(kbps*1.2)}k',
                '-bufsize',f'{kbps*2}k','-pix_fmt','yuv420p',
                '-movflags','+faststart','-an',str(clip)]
        subprocess.run(encode,check=True,timeout=max(180,int(duration*4)))
        shots=stage/'Event-Frames';shots.mkdir()
        image_manifest=[]
        for i,event in enumerate(events,1):
            center=float(event.get('video_seconds_approx',0))
            if not math.isfinite(center):continue
            image_paths=[]
            for tag,delta in (('before',-0.5),('after',1.1)):
                moment=min(max(0.,center+delta),max(0.,duration-0.1))
                out=shots/f'{i:02d}-{event.get("kind","event")}-{tag}.jpg'
                cmd=[ffmpeg,'-y','-hide_banner','-loglevel','error',
                     '-ss',f'{moment:.3f}','-i',str(source),
                     '-vf',crop,'-frames:v','1','-q:v','3',str(out)]
                try:
                    subprocess.run(cmd,check=True,timeout=45)
                    if out.exists():image_paths.append({'file':'Event-Frames/'+out.name,'video_s':round(moment,3)})
                except (subprocess.CalledProcessError,subprocess.TimeoutExpired):
                    pass  # Surface missing screenshot in manifest; do not invent.
            image_manifest.append({'kind':event.get('kind'),
                 'target':event.get('target',''), 'video_second':center,
                 'frames':image_paths, 'hp_verified':False})
        # Copy only privacy-reduced metadata, not original game IPs or payloads.
        for filename in ('review.json','event-timeline.csv','packet-timeline.csv'):
            src=folder/filename
            if src.is_file():shutil.copy2(src,stage/filename)
        # Relative time series makes overlaying traffic and video straightforward.
        timeline=review.get('traffic',{}).get('timeline',[])
        launch=utc_timestamp(meta['capture']['video_launch_utc'])
        offset=float(review.get('video_offset_seconds',0))
        with (stage/'packet-timeline-video-seconds.csv').open('w',newline='',encoding='utf-8') as out:
            cols=['video_seconds','client_segments','server_segments','client_45_bytes','prefix_matches']
            writer=csv.DictWriter(out,fieldnames=cols);writer.writeheader()
            for line in timeline:
                row={'video_seconds':round(float(line['unix_seconds'])-launch+offset,3)}
                for key in cols[1:]:row[key]=line.get(key,0)
                writer.writerow(row)
        still_bytes=sum(x.stat().st_size for x in stage.rglob('*.jpg'))
        clip_included=(clip.stat().st_size<=30*1024*1024 and
                       clip.stat().st_size+still_bytes<=45*1024*1024-2*1024*1024)
        manifest={
          'format':'wosb-combat-evidence-v432','generated_utc':utc_now(),
          'session_id':meta.get('session_id',''),
          'original_video_name':source.name,'original_video_bytes':source.stat().st_size,
          'source_resolution':[width,height],'source_duration_seconds':round(duration,3),
          'compressed_video':'Gameplay-Review.mp4' if clip_included else None,
          'crop_applied':crop_applied,'monitor_preference':monitor,
          'included_events':len(image_manifest),'event_frames':image_manifest,
          'capture_status':review.get('traffic',{}).get('capture_status','not_checked'),
          'not_included':['Raw packet payloads','Original uncompressed video','Private game installation files'],
          'privacy_warning':'Video frames may contain player names, chat or other private screen content. Review before sharing.',
          'evidence_limit':'Frames are visual context, NOT validated HP samples. TCP timing is correlation, NOT identified game opcodes.'}
        _write_atomic(stage/'Evidence-Manifest.json',manifest)
        (stage/'READ-FIRST.txt').write_text(
           'WoSB controlled combat evidence. Review compressed video and screenshots for private screen content before sharing.\n'
           'Packet metadata is timeline only: no original packet payloads or IP addresses.\n'
           'No damage formula or HP number is asserted by this export.\n',encoding='utf-8')
        size_limit=45*1024*1024
        with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as zipout:
            for file in sorted(stage.rglob('*')):
                if not file.is_file():continue
                if file==clip and not clip_included:
                    continue
                zipout.write(file,file.relative_to(stage).as_posix())
        if destination.stat().st_size>size_limit:
            destination.unlink(missing_ok=True)
            raise ValueError('Review exceeds 45 MiB. Lower bitrate or event count.')
    return destination

def main():
    ap=argparse.ArgumentParser(description='Analyze a locally recorded WoSB gameplay session, no network access')
    ap.add_argument('--review',type=Path,required=True,help='Session directory with session.json')
    ap.add_argument('--offset-seconds',type=float,default=None,
                    help='Video clock correction; defaults to the value saved in session.json')
    ap.add_argument('--export-zip',action='store_true')
    args=ap.parse_args()
    result=analyze_session(args.review,video_offset_seconds=args.offset_seconds)
    print(f'Analyzed {result["recorded_events"]} markers; traffic correlation is temporal only.')
    if args.export_zip:print(export_sanitized_review(args.review))

if __name__=='__main__':main()
