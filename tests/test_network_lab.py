import json
import socket
import sqlite3
import struct
from datetime import datetime,timezone
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import network_lab as n

def packet(payload=b'hello',src='10.0.0.10',dst='203.0.113.7',sport=45000,dport=2222):
    udp=struct.pack('!HHHH',sport,dport,8+len(payload),0)+payload
    ip=bytes([0x45,0])+struct.pack('!H',20+len(udp))+b'\0'*5+bytes([17])+b'\0\0'+socket.inet_aton(src)+socket.inet_aton(dst)
    return b'\0'*12+b'\x08\x00'+ip+udp

def pcap(path):
    raw=packet()
    path.write_bytes(b'\xd4\xc3\xb2\xa1'+struct.pack('<HHiIII',2,4,0,0,65535,1)+struct.pack('<IIII',1700000000,123456,len(raw),len(raw))+raw)

def block(kind,body):
    sz=12+len(body)
    return struct.pack('<II',kind,sz)+body+struct.pack('<I',sz)

def pcapng(path):
    raw=packet()
    shb=block(0x0a0d0d0a,b'\x4d\x3c\x2b\x1a'+struct.pack('<HHq',1,0,-1))
    idb=block(1,struct.pack('<HHI',1,0,65535))
    padding=b'\x00'*((-len(raw))%4)
    # overflow timestamp in low half: separate high/low
    ticks=1700000000*1000000
    epb=block(6,struct.pack('<IIIII',0,ticks>>32,ticks&0xffffffff,len(raw),len(raw))+raw+padding)
    path.write_bytes(shb+idb+epb)

def test_pcap(tmp_path):
    path=tmp_path/'test.pcap';pcap(path)
    result=n.analyze_capture(path)
    assert result['packet_count']==1
    assert result['protocols']=={'UDP':1}
    assert result['flows'][0]['endpoint_a_prefix']=='10.0.0.0/24'
    assert not any('203.0.113.7' in str(x) for x in result['flows'])
    assert 'hello' not in json.dumps(result)

def test_pcapng(tmp_path):
    path=tmp_path/'test.pcapng';pcapng(path)
    result=n.analyze_capture(path)
    assert result['packet_count']==1
    assert result['flows'][0]['payload_bytes']==5

def test_events_export_redacted(tmp_path):
    path=tmp_path/'test.pcap';pcap(path)
    summary=n.analyze_capture(path)
    conn=sqlite3.connect(':memory:');sid=n.save_session(conn,summary,path)
    n.add_event(conn,sid,summary['first_utc'],'cannon impact','impact 250 damage')
    dest=n.export_research(conn,sid,tmp_path/'research.json')
    data=json.loads(dest.read_text())
    assert data['temporal_correlations'][0]['packets']==1
    assert '10.0.0.0/24' not in dest.read_text()
    assert str(path) not in dest.read_text()
    assert len(n.list_sessions(conn))==1

def test_unsafe_pcap(tmp_path):
    path=tmp_path/'bad.pcap';path.write_bytes(b'junk')
    import pytest
    with pytest.raises(ValueError):n.analyze_capture(path)

def test_capture_interface_validation(tmp_path):
    import pytest
    with pytest.raises(ValueError):n.start_capture('1; rm -rf /',tmp_path/'file.pcapng',tshark='/fake/tshark')

def test_ipv4_tcp_packet():
    payload=b'GET / HTTP/1.1\r\n'
    tcp=struct.pack('!HHIIBBHHH',1500,80,0,0,5<<4,0x18,0,0,0)+payload
    ip=bytes([0x45,0])+struct.pack('!H',20+len(tcp))+b'\0'*5+bytes([6])+b'\0\0'+socket.inet_aton('192.0.2.4')+socket.inet_aton('192.0.2.5')
    decoded=n._decode_packet(b'\0'*12+b'\x08\x00'+ip+tcp,1)
    assert decoded['proto']=='TCP' and decoded['payload']==payload
