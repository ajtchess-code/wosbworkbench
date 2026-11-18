"""Prioritized decoder work from actual failed assets and unresolved links.

A 'matched_filename' is not enough to mark rendering as verified. This module
only produces actionable next research tasks; never edits installed game files.
"""
from __future__ import annotations
from collections import Counter,defaultdict
from pathlib import Path
import json


def make_queue(recovery_root,*,max_ledger=300000,max_links=200000):
    root=Path(recovery_root);ledger=root/'Reports'/'AssetLedger.jsonl';links=root/'Reports'/'ModelTextureLinks.jsonl'
    errors=defaultdict(list);issues=Counter();textures=defaultdict(list);unverified=Counter();total=0
    if ledger.is_file():
        with ledger.open(encoding='utf-8') as f:
            for line in f:
                if not line.strip():continue
                total+=1
                if total>max_ledger:raise ValueError('Too many asset-ledger rows')
                try:r=json.loads(line)
                except json.JSONDecodeError:issues['unreadable_asset_ledger_line']+=1;continue
                if r.get('status') in ('decoded','indexed','preserved'):continue
                reason=str(r.get('error_type') or r.get('reason') or r.get('status') or 'unknown')
                group=(str(r.get('kind') or 'unknown'),reason)
                issues[group]+=1
                if len(errors[group])<12:errors[group].append(str(r.get('path') or '')[:255])
    if links.is_file():
        with links.open(encoding='utf-8') as f:
            for i,line in enumerate(f):
                if i>=max_links:raise ValueError('Too many material links')
                if not line.strip():continue
                try:r=json.loads(line)
                except json.JSONDecodeError:continue
                state=str(r.get('status') or '')
                unverified[state]+=1
                if state=='unresolved':
                    name=str(r.get('material_label') or 'Unknown')[:120]
                    if len(textures[name])<5:textures[name].append(str(r.get('model') or '')[:255])
    tasks=[]
    for key,count in issues.most_common():
        kind,reason=key
        if 'XNBError' in reason or 'decompress' in reason.lower():action='Reproduce XNB header/decompression on a known-good original byte sample, then recheck affected readers'
        elif 'MeshDecodeError' in reason or kind=='model':action='Compare source model geometry, vertex/index counts, transforms and material boundaries'
        elif kind=='effect':action='Inspect EffectReader metadata and original effect parameters; map shader references and blending'
        elif 'ValueError' in reason:action='Inspect asset content type and decoder exception path before retrying; input may not match the selected reader'
        else:action='Classify the reader and reproduce a minimal, read-only decoding sample'
        tasks.append({'category':kind,'reason':reason,'affected_assets':count,'priority':('critical' if kind in ('model','texture') else 'high'),
                      'action':action,'samples':errors[key],'status':'research_needed','verified_fixed':False})
    if textures:
        tasks.append({'category':'material mapping','reason':'unresolved model-to-texture names','affected_assets':sum(unverified.values())-unverified.get('matched_filename_not_verified_shader',0),
                      'distinct_unresolved_labels':len(textures),'priority':'high',
                      'action':'Match exact segment labels to decoded textures; inspect actual shader and blend settings before declaring a match',
                      'samples':[{'material':name,'models':models} for name,models in list(sorted(textures.items()))[:30]],
                      'status':'research_needed','verified_fixed':False})
    if unverified.get('matched_filename_not_verified_shader'):
        tasks.append({'category':'game rendering','reason':'filename matches are not confirmed shader equivalence',
                      'affected_assets':unverified['matched_filename_not_verified_shader'],
                      'priority':'medium','action':'Compare screenshots and original effect parameters against matching models and designs',
                      'samples':[],'status':'visual_validation_needed','verified_fixed':False})
    tasks.extend([
        {'category':'damage','reason':'authoritative hit-resolution not proven','affected_assets':None,'priority':'critical',
         'action':'Trace combat call graphs and compare controlled HP observations; no exact damage simulation until validated',
         'samples':[],'status':'server_rule_or_validation_missing','verified_fixed':False},
        {'category':'protocol','reason':'recorded segment sizes are unclassified','affected_assets':None,'priority':'high',
         'action':'Correlate user-marked video events with sanitized packet timestamps and inspect client serialization code',
         'samples':[],'status':'candidate_only','verified_fixed':False}])
    return {'format':'wosb-repair-queue-v43','asset_ledger_count':total,
            'assets_by_problem':{str(k):v for k,v in issues.items()},
            'material_link_status':dict(unverified),'tasks':tasks,
            'notes':['No game binaries or private packet payloads are included','Recovery success does not establish original shader or authoritative combat rules']}


def export_queue(root):
    root=Path(root);report=make_queue(root);directory=root/'Reports';directory.mkdir(parents=True,exist_ok=True)
    (directory/'Repair-Queue.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    lines=['# WoSB decoder and mechanics repair queue','','This queue is based on the CURRENT saved asset ledger. It does not assume old failures remain unresolved.','']
    for i,task in enumerate(report['tasks'],1):
        lines+=['## '+str(i)+'. '+task['category']+' — '+task['reason'],
                '- Priority: '+task['priority'],
                '- Affected records: '+str(task['affected_assets']),
                '- Next step: '+task['action'],'']
    (directory/'Repair-Queue.md').write_text('\n'.join(lines),encoding='utf-8')
    return report
