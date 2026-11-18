#!/usr/bin/env python3
"""Cross-reference .NET combat code without running game assemblies.

Generates candidate-method neighborhoods, field write/read relations, branch
signals and conservative straight-line IL expressions. These are clues, NOT a
verified or authoritative damage/ignition formula.
"""
from __future__ import annotations

import csv
import json
import re
from collections import defaultdict, Counter
from pathlib import Path

from combat_research import TOPICS, topics, json_write, csv_write

ARITHMETIC = {'add': '+','sub': '-','mul': '*','div': '/','div.un': '/', 'rem': '%', 'rem.un': '%',
              'and': '&','or': '|','xor': '^','shl':'<<','shr':'>>',
              'ceq':'==','cgt':'>','cgt.un':'>','clt':'<','clt.un':'<'}
BRANCH_PREFIXES = ('br', 'beq', 'bge', 'bgt', 'ble', 'blt', 'leave', 'switch')
PROBABILITY = re.compile(r'random|chance|probabil|nextdouble|nextsingle|next\b|roll|percent|critical|ignit',re.I)


def mnemonic_field(m, token):
    try:
        field=m.row(token)
        return m.owners.get(id(field),'?')+'::'+str(field.Name)
    except Exception:
        return f'field:{token}'


def mnemonic_method(m,token):
    try:
        owner,name,_=m.method(token)
        return owner+'::'+name
    except Exception:
        return f'method:{token}'


def opcode_signals(m,instructions,limit=250):
    """IL structural signals, useful when gameplay variable names are obfuscated."""
    results=[]
    for ins in instructions:
        op=ins.opcode.name
        if op in ARITHMETIC:
            results.append({'offset':ins.offset,'kind':'arithmetic','opcode':op})
        elif op.startswith(BRANCH_PREFIXES):
            results.append({'offset':ins.offset,'kind':'branch','opcode':op})
        elif op.startswith(('stfld','stsfld','ldfld','ldsfld')):
            field=mnemonic_field(m,ins.operand)
            if topics(field) or op.startswith('st'):
                results.append({'offset':ins.offset,'kind':'field_write' if op.startswith('st') else 'field_read',
                                'opcode':op,'target':field})
        elif op in ('call','callvirt','newobj'):
            method=mnemonic_method(m,ins.operand)
            if topics(method) or PROBABILITY.search(method):
                results.append({'offset':ins.offset,'kind':'relevant_call','opcode':op,'target':method})
    return results[:limit]


def sketch_straight_line(m,instructions,max_lines=70):
    """Partial symbolic expressions only within straight-line IL blocks.

    Unknown opcodes and control flow reset the stack. No runtime assumptions,
    heap effects, loops, or indirect calls are evaluated. Errors never produce
    an executable formula; output is a set of bounded evidence sketches.
    """
    stack=[];loc={};lines=[];branch_count=0;partial=False
    def push(v):
        stack.append(str(v)[-160:]);
        if len(stack)>60:stack.clear()
    def pop():
        nonlocal partial
        if not stack:partial=True;return '?'
        return stack.pop()
    def localnum(name,operand):
        if name.endswith(('.s','.a','.a.s')) or name in ('ldloc','stloc','ldarg','starg'):
            return getattr(operand,'index', '?')
        match=re.search(r'\.(\d+)$',name)
        return match.group(1) if match else '?'
    def emit(text,ins):
        if len(lines)<max_lines:
            lines.append({'offset':ins.offset,'expression':text[:320],
                          'interpretation':'partial straight-line IL sketch, not a validated formula'})
    for ins in instructions[:5000]:
        n=ins.opcode.name
        try:
            if n.startswith('ldc.'):
                try:value=m.const(ins)
                except Exception:value='?'
                push(value)
            elif n.startswith('ldarg'):
                push('arg'+str(localnum(n,ins.operand)))
            elif n.startswith('ldloc'):
                k=str(localnum(n,ins.operand));push(loc.get(k,'local'+k))
            elif n.startswith('stloc'):
                loc[str(localnum(n,ins.operand))]=pop()
            elif n=='dup':push(stack[-1] if stack else '?')
            elif n=='pop':pop()
            elif n=='ldnull':push('null')
            elif n in ('ldfld','ldflda'):
                owner=pop();push('('+owner+'.'+mnemonic_field(m,ins.operand).split('::')[-1]+')')
            elif n in ('ldsfld','ldsflda'):
                push(mnemonic_field(m,ins.operand))
            elif n in ('stfld','stsfld'):
                value=pop();owner=pop() if n=='stfld' else ''
                target=(owner+'.' if owner else '')+mnemonic_field(m,ins.operand)
                emit(target+' := '+value,ins)
            elif n in ARITHMETIC:
                b=pop();a=pop();sym=ARITHMETIC[n]
                expr='('+a+' '+sym+' '+b+')'
                push(expr)
                if n in ('mul','div','div.un','rem','rem.un','cgt','clt','ceq'):
                    emit(expr,ins)
            elif n.startswith('conv.'):
                v=pop();push(n+'('+v+')')
            elif n in ('call','callvirt','newobj'):
                name=mnemonic_method(m,ins.operand)
                # Conservative: unknown call signatures invalidate entire stack.
                # Attempt to recover argument count only from parsed metadata.
                try:
                    _,_,method=m.method(ins.operand)
                    nargs, hasthis, returns=m.sig(method)
                    if n=='callvirt' or n=='call':nargs+=int(hasthis)
                    args=[pop() for _ in range(min(nargs,30))][::-1]
                    expr=name+'('+', '.join(args)+')'
                    if returns or n=='newobj':push(expr)
                    if topics(name) or PROBABILITY.search(name):emit(expr,ins)
                except Exception:
                    stack.clear();partial=True
            elif n=='ret':
                if stack:emit('return '+pop(),ins)
                stack.clear()
            elif n.startswith(BRANCH_PREFIXES) or n in ('throw','rethrow','endfinally'):
                branch_count+=1;stack.clear()
            elif n.startswith(('stelem','ldelem','stind','ldind','ldstr','ldtoken','newarr','box','unbox',
                                'initobj','ldobj','stobj','cpobj','ldlen','isinst','castclass','ldftn',
                                'ldvirtftn','ldc.','ldarga','ldloca')):
                stack.clear();partial=True
            elif n not in ('nop','constrained.','readonly.','volatile.','tail.','unaligned.','break'):
                stack.clear();partial=True
        except (IndexError,KeyError,ValueError,TypeError,AttributeError):
            stack.clear();partial=True
    return {'expressions':lines,'branch_boundaries':branch_count,
            'partial':True,'warning':'Straight-line sketches reset on branches and unsupported operations; do not treat as full formulas.'}


def build_dossiers(game,out,max_methods=150000,max_candidate_per_topic=90,max_assembly_bytes=80_000_000):
    from client_metadata import Metadata
    from dncil.clr.token import Token
    game=Path(game).resolve();out=Path(out).resolve()
    methods={}; outgoing=defaultdict(set);incoming=defaultdict(set)
    field_reads=defaultdict(set);field_writes=defaultdict(set)
    method_fields=defaultdict(list);issues=[];signal_rows=[]
    dlls=sorted(p for p in game.rglob('*') if p.is_file() and not p.is_symlink() and p.suffix.lower() in ('.dll','.exe'))
    count=0
    for dll in dlls:
        if count>=max_methods:break
        rel=dll.relative_to(game).as_posix()
        if dll.stat().st_size>max_assembly_bytes:continue
        try:
            m=Metadata(dll)
            if not getattr(m.pe,'net',None) or not m.pe.net.mdtables:continue
            for rid,row in enumerate(m.pe.net.mdtables.MethodDef.rows,1):
                if count>=max_methods:break
                count+=1
                key=rel+'|'+str(rid)
                name=m.owners.get(id(row),'?')+'::'+str(row.Name)
                methods[key]={'source':rel,'token':f'0x{(0x06000000|rid):08x}',
                              'name':name,'topics':topics(name),'rva':bool(row.Rva),
                              'ops':Counter(),'calls_named':[],'field_names':[],'numeric':[],
                              'signals':[],'probability_clues':[]}
                if not row.Rva:continue
                try:body=m.body(rid)
                except Exception as e:
                    if topics(name):issues.append({'source':rel,'method':name,'error_type':type(e).__name__})
                    continue
                for ins in body:
                    op=ins.opcode.name
                    if op in ARITHMETIC or op.startswith(BRANCH_PREFIXES):methods[key]['ops'][op]+=1
                    if op in ('call','callvirt','newobj'):
                        target=mnemonic_method(m,ins.operand)
                        if len(methods[key]['calls_named'])<100:methods[key]['calls_named'].append(target)
                        if PROBABILITY.search(target) and len(methods[key]['probability_clues'])<30:
                            methods[key]['probability_clues'].append(target)
                        if isinstance(ins.operand,Token) and ins.operand.table==6:
                            dest=rel+'|'+str(ins.operand.rid)
                            outgoing[key].add(dest);incoming[dest].add(key)
                    elif op in ('ldfld','ldsfld','stfld','stsfld') and isinstance(ins.operand,Token):
                        field=rel+'|'+str(ins.operand.value)
                        target=mnemonic_field(m,ins.operand)
                        if op.startswith('st'):field_writes[field].add(key)
                        else:field_reads[field].add(key)
                        if len(methods[key]['field_names'])<100:methods[key]['field_names'].append(target)
                        method_fields[key].append(field)
                    elif op.startswith('ldc.'):
                        try:
                            val=m.const(ins)
                            if isinstance(val,(float,int)) and len(methods[key]['numeric'])<100:
                                methods[key]['numeric'].append(val)
                        except (ValueError,IndexError,TypeError):pass
                # Only relevant methods need full IL structural signals.
                if methods[key]['topics'] or any(topics(x) for x in methods[key]['calls_named']):
                    methods[key]['signals']=opcode_signals(m,body,100)
        except Exception as e:
            issues.append({'source':rel,'error_type':type(e).__name__})
    dossiers={}
    compact_graph=[];field_relationships=[];seed_count=0;selected_global=set()
    for topic in TOPICS:
        candidates=[(key,data) for key,data in methods.items() if topic in data['topics'] or
                    any(topic in topics(c) for c in data['calls_named']+data['field_names'])]
        def rank(candidate):
            key,data=candidate
            name_match=topic in data['topics']
            matching_fields=sum(topic in topics(f) for f in data['field_names'])
            matching_calls=sum(topic in topics(c) for c in data['calls_named'])
            signal_count=sum(int(k in ('mul','div','div.un','rem','clt','cgt','ceq'))*v for k,v in data['ops'].items())
            return 10*name_match+4*matching_fields+3*matching_calls+2*bool(data['probability_clues'])+min(15,signal_count)
        candidates.sort(key=lambda c:(-rank(c),c[0]))
        seed_count+=len(candidates)
        items=[]
        for key,data in candidates[:max_candidate_per_topic]:
            selected_global.add(key)
            callers=sorted(incoming[key])[:15]
            callees=sorted(outgoing[key])[:15]
            fields=set(method_fields[key])
            shared_writers=sorted({v for f in fields for v in field_writes[f] if v!=key})[:15]
            shared_readers=sorted({v for f in fields for v in field_reads[f] if v!=key})[:15]
            related_keys=set(callers+callees+shared_writers+shared_readers)
            selected_global.update(related_keys)
            item={'method':data['name'],'source':data['source'],'token':data['token'],
                  'candidate_rank':rank((key,data)),
                  'topic_evidence':data['topics'],
                  'numeric_literals':data['numeric'][:30],
                  'relevant_calls':[x for x in data['calls_named'] if topics(x)][:30],
                  'probability_clues':data['probability_clues'][:15],
                  'opcode_counts':dict(data['ops']),
                  'signals':data['signals'][:30],
                  'callers':[methods[v]['name'] for v in callers if v in methods],
                  'callees':[methods[v]['name'] for v in callees if v in methods],
                  'shared_field_writers':[methods[v]['name'] for v in shared_writers if v in methods],
                  'shared_field_readers':[methods[v]['name'] for v in shared_readers if v in methods],
                  'status':'candidate static reference — no runtime/server verification'}
            items.append(item)
        dossiers[topic]={'matches':len(candidates),'included':len(items),'candidates':items,
                         'investigation':'Trace the listed writers/readers and callers, then validate branch predicates and numeric operations against controlled observations.'}
    for src in sorted(selected_global):
        if src not in methods:continue
        for dst in sorted(outgoing[src]):
            if dst in methods:
                compact_graph.append({'caller':methods[src]['name'],'callee':methods[dst]['name'],
                                      'source':methods[src]['source'],'relation':'direct_MethodDef_call'})
    for field in set(field_reads)|set(field_writes):
        writers=sorted(field_writes[field] & selected_global)
        readers=sorted(field_reads[field] & selected_global)
        for writer in writers[:25]:
            for reader in readers[:25]:
                if reader != writer and reader in methods and writer in methods:
                    field_relationships.append({'writer':methods[writer]['name'],'reader':methods[reader]['name'],
                                                'field_token':field,'relation':'read_write_candidate'})
    # Export symbolic sketches only for focused top 15 topic candidates; no full IL text in the shareable pack.
    sketches=[]
    seen=set()
    for topic in TOPICS:
        for item in dossiers[topic]['candidates'][:15]:
            key=item['source']+'|'+str(int(item['token'],16)&0xffffff)
            if key in seen:continue
            seen.add(key)
            try:
                m=Metadata(game/item['source'])
                expr=sketch_straight_line(m,m.body(int(item['token'],16)&0xffffff))
                sketches.append({'source':item['source'],'method':item['method'],'token':item['token'],
                                 'expressions':expr['expressions'][:30], 'partial':True,
                                 'note':'Arithmetic sketch, not validated formula'})
            except Exception as e:
                issues.append({'source':item['source'],'method':item['method'],'error_type':type(e).__name__})
    json_write(out/'Combat/Dossiers.json',{'method_scanned':len(methods),'topics':dossiers,
               'field_relationships':field_relationships[:10000],
               'expression_sketches':sketches,
               'limitations':['Static IL only; no client code executed',
                              'Only MethodDef direct calls are linked; virtual/interface and external calls may be missing',
                              'Cross-method flow, game state, network/server authority and random distributions are not validated',
                              'Expression sketches are partial and reset at branches/unsupported opcodes'],
               'issues':issues[:1000]})
    csv_write(out/'Combat/CallGraph.csv',compact_graph[:100000])
    csv_write(out/'Combat/ILSignals.csv',
              [{'source':i['source'],'method':i['method'],'token':i['token'],
                'opcode':s['opcode'],'offset':s['offset'],'kind':s['kind'],'target':s.get('target','')}
               for t in TOPICS for i in dossiers[t]['candidates'] for s in i['signals']][:100000])
    return {'methods_scanned':len(methods),'candidate_methods_across_topics':seed_count,
            'dossier_topics':len(dossiers),'callgraph_edges':len(compact_graph),
            'field_relationships':len(field_relationships),'expression_sketches':len(sketches),'issues':len(issues)}


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--game',required=True)
    p.add_argument('--output',required=True)
    a=p.parse_args()
    print(json.dumps(build_dossiers(a.game,a.output),indent=2))
