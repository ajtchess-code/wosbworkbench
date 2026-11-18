"""Verify selected reverse-engineered client expressions across game builds.

This performs bounded comparison of managed IL instruction signatures, without
executing game DLLs. A matching client expression is NOT proof that the server
uses it as the final damage rule.
"""
from __future__ import annotations
import hashlib,json,re
from pathlib import Path

SIGNATURES={
 'sail_damage_energy':{
    'method':'Common.Game.CannonBall::SailDamageEnergy',
    'required':['ldc.i4.3','bge.s','ldc.r4 1.0','conv.r4','add','div','ldc.r4 0.0'],
    'meaning':'1/(1+n) when n < 3, otherwise 0, for nonnegative integer n'},
 'cannon_penetration_getter':{
    'method':'Common.Resources.CannonGameInfo::get_Penetration',
    'required':['Editor_Penetration','get_HasValue','GetValueOrDefault','ret'],
    'meaning':'Editor override when nullable value present; otherwise fallback field'},
 'ship_armor_getter':{
    'method':'Common.Resources.ShipDynamicInfo::get_Armor',
    'required':['GetBonus','mul','add','ret'],
    'meaning':'BasicArmor * (1 + bonus 5) + bonus 13, pending exact instruction mapping'},
}
METHOD_RE=re.compile(r'^#\s+(0x[0-9a-fA-F]{8})\s+(.+?)\s*$',re.MULTILINE)
CALL_RE=re.compile(r'\b(?:call|callvirt|newobj)\s+(\S.*?)(?:\s+token\(0x[0-9a-fA-F]+\))?\s*$')
MAX_IL=250*1024*1024


def audit_folder(directory,output=None):
    base=Path(directory);total=0;matched={};methods=0;damage_calls=[]
    for file in sorted(base.rglob('*.il.txt')) if base.is_dir() else []:
        if not file.is_file() or file.stat().st_size>MAX_IL:continue
        raw=file.read_text(encoding='utf-8',errors='replace');total+=len(raw)
        if total>MAX_IL:break
        sections=METHOD_RE.split(raw)
        if len(sections)==1:
            sections=['', 'unknown',file.stem,raw]
        for i in range(1,len(sections)-2,3):
            token,name,body=sections[i:i+3];methods+=1
            for key,sign in SIGNATURES.items():
                if name.casefold()==sign['method'].casefold():
                    matched[key]={'method':name,'token':token,'source_file':str(file.relative_to(base)),
                        'sha256':hashlib.sha256(body.encode()).hexdigest(),
                        'status':'client_signature_matches' if all(term.casefold() in body.casefold() for term in sign['required'])
                            else 'client_signature_changed_or_unmatched',
                        'interpretation':sign['meaning'],
                        'authoritative_server_damage':False}
            if any(key in name.casefold() for key in ('damage','collision','cannonball','sail','mortar','barrel','penetration')):
                calls=[]
                for line in body.splitlines():
                    m=CALL_RE.search(line)
                    if m and any(key in m.group(1).casefold() for key in ('damage','collision','penetration','cannonball','ship','sail')):
                        calls.append(m.group(1)[:220])
                if calls:damage_calls.append({'name':name,'token':token,'calls':calls[:100],
                                              'source_file':str(file.relative_to(base))})
    report={'format':'wosb-code-signatures-v41','methods_inspected':methods,
            'verified_client_methods':{k:matched.get(k,{'status':'not_found_in_examined_IL','method':v['method']}) for k,v in SIGNATURES.items()},
            'damage_related_call_sites':damage_calls[:10000],
            'caveat':'Signature matches demonstrate client method structure, not server-authoritative final damage or ricochet.'}
    if output:
        dst=Path(output);dst.parent.mkdir(parents=True,exist_ok=True)
        dst.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    return report

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('il_folder');p.add_argument('--output');args=p.parse_args()
    print(json.dumps(audit_folder(args.il_folder,args.output),indent=2)[:6000])
