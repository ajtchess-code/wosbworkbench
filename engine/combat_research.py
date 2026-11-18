#!/usr/bin/env python3
"""Read-only, evidence-first combat research for a WoSB installation.

Never executes or imports game DLLs. Method names and IL are hypotheses/evidence,
not proof of a final server-authoritative combat formula.
"""
from __future__ import annotations
import argparse, csv, hashlib, json, re, traceback
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

TOPICS = {
    'damage': ['damage','dmg','hull','hitpoint','health','hit','penetrat','ballistic','impact','cannon','projectile','explos','critical','broadside','shot'],
    'mitigation': ['armor','armour','resistan','reduc','mitigat','defen','protect','block','absorb','thickness','plating','penetrat','ricochet'],
    'fire': ['largefire','bigfire','greatfire','majorfire','heavyfire','fire','burn','ignit','incend','flamm','combust','extinguish','water','firefight'],
    'flooding': ['flood','leak','pump','waterline','sink','bilge'],
    'status_effects': ['effect','status','buff','debuff','duration','tick','damageovertime','dot','stun','slow','repair'],
    'crew': ['crew','sailor','officer','morale','boarding','captain','skill'],
    'weapons': ['reload','spread','dispersion','accuracy','range','velocity','caliber','calibre','mortar','bomb','barrel','ammo','shell','cannon'],
}
STRONG = {'largefire','bigfire','greatfire','majorfire','heavyfire','ignite','ignition','firechance','firedamage','damage','damagereceived','armor','armour','penetration','mitigation'}
KEYWORDS = sorted({w for words in TOPICS.values() for w in words}, key=len, reverse=True)
SKIP_DIRS = {'userdata','user_data','profiles','profile','saves','save','logs','log','crashes','crashdumps',
             'telemetry','sessions','cookies','secrets','credentials','tokens','auth','accounts','appdata','screenshots'}

def safe_candidate(path,root):
    return (not path.is_symlink()) and not any(c.lower() in SKIP_DIRS for c in path.relative_to(root).parts[:-1])



def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def topics(text):
    s=str(text).lower().replace('_','').replace(' ','')
    return sorted(k for k,words in TOPICS.items() if any(w in s for w in words))


def json_write(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str),encoding='utf-8')


def csv_write(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    fields=sorted({k for row in rows for k in row}) or ['status']
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for r in rows:
            w.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else ("'"+v if isinstance(v,str) and v.lstrip().startswith(('=','+','-','@')) else v) for k,v in r.items()})


def inventory(game):
    return [{'path':p.relative_to(game).as_posix(),'bytes':p.stat().st_size,'sha256':sha(p),'extension':p.suffix.lower()}
            for p in sorted(game.rglob('*')) if p.is_file() and safe_candidate(p,game)]


def scan_structured(game, out, max_bytes=15_000_000):
    """Look for relevant fields and values in local JSON; preserves paths and source."""
    rows=[];errors=[]
    for p in sorted(game.rglob('*')):
        if not p.is_file() or not safe_candidate(p,game) or p.suffix.lower() not in ('.json','.jsonl') or p.stat().st_size>max_bytes:continue
        try:
            obj=json.loads(p.read_text(encoding='utf-8-sig')) if p.suffix.lower()=='.json' else [json.loads(s) for s in p.read_text(encoding='utf-8-sig').splitlines() if s.strip()]
            def visit(x,ptr,depth=0):
                if depth>40:return
                if isinstance(x,dict):
                    for k,v in x.items():
                        if re.search(r'(secret|token|password|email|account|auth|session|key$)',str(k),re.I):continue
                        at=ptr+'/'+str(k).replace('~','~0').replace('/','~1');match=topics(k)
                        if match:
                            rows.append({'source':p.relative_to(game).as_posix(),'json_pointer':at,'field':k,'value':v if isinstance(v,(int,float,bool,type(None))) else '[non-numeric value redacted]','topics':match,'evidence_kind':'client_configuration','interpretation':'field name/value; gameplay usage unverified'})
                        visit(v,at,depth+1)
                elif isinstance(x,list):
                    for i,v in enumerate(x):visit(v,ptr+'/'+str(i),depth+1)
            visit(obj,'')
        except Exception as exc:errors.append({'source':str(p.relative_to(game)),'stage':'json','error':str(exc)})
    csv_write(out/'Combat/ConfigFields.csv',rows)
    return rows,errors


def scan_assemblies(game,out,max_methods=1000):
    """Find methods by names, field/type names and referenced IL tokens.

    Reachability and final numerical formulas require downstream inspection.
    """
    methods=[];issues=[];references=[];ranked=[]
    try:
        from client_metadata import Metadata
        from dncil.clr.token import Token, StringToken
    except Exception as exc:
        return [],[{'stage':'dependency','error':str(exc),'fix':'Install requirements.txt'}],[]
    dlls=sorted(p for p in game.rglob('*.dll') if p.is_file() and safe_candidate(p,game))
    for dll in dlls:
        rel=dll.relative_to(game).as_posix()
        try:
            m=Metadata(dll)
            if not getattr(m.pe,'net',None) or not m.pe.net.mdtables:continue
            rows=m.pe.net.mdtables.MethodDef.rows
            for rid,row in enumerate(rows,1):
                owner=m.owners.get(id(row),'?');name=str(row.Name);full=owner+'::'+name
                name_topics=topics(full)
                if not row.Rva:continue
                # Scan all methods for interesting references: obfuscated combat methods may have meaningless names.
                try:instructions=m.body(rid)
                except Exception as exc:
                    if name_topics:issues.append({'stage':'IL reading','source':rel,'method':full,'error':str(exc)})
                    continue
                called=[];fields=[];strings=[];numbers=[]
                for ins in instructions:
                    op=ins.operand
                    if isinstance(op,StringToken):
                        try:strings.append(str(m.pe.net.user_strings.get(op.rid).value)[:500])
                        except Exception:pass
                    elif isinstance(op,Token):
                        if op.table in (6,10,43):
                            try:
                                o,n,_=m.method(op);called.append(o+'::'+n)
                            except Exception:pass
                        elif op.table in (4,):
                            try:
                                f=m.row(op);fields.append(m.owners.get(id(f),'?')+'::'+str(f.Name))
                            except Exception:pass
                    elif ins.opcode.name.startswith('ldc.') and isinstance(op,(int,float)):
                        numbers.append({'offset':ins.offset,'opcode':ins.opcode.name,'value':op})
                related=[x for x in called+fields+strings if topics(x)]
                found=sorted(set(name_topics+sum((topics(x) for x in related),[])))
                if not found:continue
                strong=any(k in full.lower().replace('_','') for k in STRONG)
                score=(12 if strong else 0)+len(name_topics)*6+min(20,len(related)*2)+len(found)*2
                ranked.append((score,rel,rid,full,found,called,fields,strings,numbers))
        except Exception as exc:
            issues.append({'stage':'assembly','source':rel,'error':str(exc)})
    ranked.sort(key=lambda r:(-r[0],r[1],r[2]))
    # Always preserve a ranked index, even when IL evidence is limited by max_methods.
    for score,rel,rid,full,found,called,fields,strings,numbers in ranked:
        methods.append({'assembly':rel,'token':f'0x{0x06000000|rid:08x}','method':full,'topics':found,'score':score,'evidence_status':'candidate — inspect IL and execution path; server behavior unverified','calls_related':[x for x in called if topics(x)][:60],'fields_related':[x for x in fields if topics(x)][:60],'strings_related':[x for x in strings if topics(x)][:30],'numeric_literals':numbers[:80]})
        for target in called:
            if topics(target):references.append({'assembly':rel,'caller':full,'callee':target,'topics':topics(target)})
    # Re-open assemblies once per DLL to preserve the strongest candidate method disassemblies.
    bydll=defaultdict(list)
    for i,row in enumerate(methods[:max_methods]):bydll[row['assembly']].append((i,row))
    for rel,selected in bydll.items():
        try:
            m=Metadata(game/rel)
            for i,row in selected:
                rid=int(row['token'],16)&0xFFFFFF
                content=m.evidence(rid)
                evidence_file=Path('Combat/IL')/(re.sub(r'[^a-zA-Z0-9_.-]','_',rel)+'_'+str(rid)+'.il.txt')
                dest=out/evidence_file;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(content,encoding='utf-8')
                row['evidence_path']=evidence_file.as_posix()
                row['evidence_sha256']=sha(dest)
        except Exception as exc:issues.append({'stage':'evidence export','source':rel,'error':str(exc)})
    csv_write(out/'Combat/Methods.csv',methods)
    csv_write(out/'Combat/CallReferences.csv',references)
    return methods,issues,references


def analyze(game,out,max_methods=1000,skip_assemblies=False):
    game=Path(game).resolve();out=Path(out).resolve()
    if not game.is_dir():raise ValueError('Game directory does not exist: '+str(game))
    if game==out or game in out.parents:raise ValueError('Output must be outside the game installation')
    out.mkdir(parents=True,exist_ok=True)
    files=inventory(game);json_write(out/'Diagnostics/FileInventory.json',files)
    config,problems=scan_structured(game,out)
    methods=[];refs=[]
    if not skip_assemblies:
        methods,errors,refs=scan_assemblies(game,out,max_methods);problems+=errors
    csv_write(out/'Diagnostics/Errors.csv',problems)
    topic_report=[]
    for t in TOPICS:
        matches=[m for m in methods if t in m['topics']]
        topic_report.append({'topic':t,'candidate_methods':len(matches),'configuration_fields':sum(t in r['topics'] for r in config),'status':'Candidates found; formulas not yet validated' if matches else 'No verified formula found','top_methods':[m['method'] for m in matches[:15]]})
    json_write(out/'Combat/Topics.json',topic_report)
    summary={'generated_utc':datetime.now(timezone.utc).isoformat(),'game_root':str(game),'files_scanned':len(files),'managed_assemblies_detected':sum(f['extension']=='.dll' for f in files),'candidate_methods':len(methods),'configuration_fields':len(config),'references':len(refs),'errors':len(problems),'warning':'NOT a verified damage/fire formula; results are static client-code candidates. Server behavior may differ. No game DLLs executed.'}
    json_write(out/'Combat/Summary.json',summary)
    (out/'Combat/README.md').write_text('''# WoSB combat research\n\nThis scanner **does not claim** that matching method names prove mechanics.\n\n1. Start with Topics.json; find high-ranking methods in Methods.csv.\n2. Inspect exact IL in evidence_path and follow CallReferences.csv.\n3. Trace inputs to numeric operations and branches; inspect constructors, flags, and status transitions.\n4. Differentiate damage dealt, post-mitigation damage, armor, penetration, critical effects, fire ignition, fire growth, firefighting, flooding, and DOT ticks.\n5. Determine whether computations occur on the authoritative server, in shared assemblies, or client-side only.\n6. Only publish a formula after its full data flow is proven. Use a test case where possible.\n\nThe scanner never executes game DLLs, accesses game accounts, or contacts servers.\n''',encoding='utf-8')
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--game',required=True,help='Directory holding an installed WoSB client')
    p.add_argument('--output',required=True,help='Separate report directory')
    p.add_argument('--max-methods',type=int,default=1000)
    p.add_argument('--skip-assemblies',action='store_true')
    a=p.parse_args();print(json.dumps(analyze(a.game,a.output,max_methods=a.max_methods,skip_assemblies=a.skip_assemblies),indent=2))
if __name__=='__main__':main()
