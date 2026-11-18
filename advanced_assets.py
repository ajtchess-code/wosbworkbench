"""Read-only cross-client asset comparison, retry triage and design binding audit."""
from __future__ import annotations
from collections import Counter,defaultdict
from pathlib import Path
import hashlib,json


def failure_class(reason,kind=''):
    s=(str(reason)+' '+str(kind)).casefold()
    if 'xnb' in s and any(x in s for x in ('compress','lzx','lz4','header')):return 'compression_or_xnb_header'
    if 'reader' in s or 'unsupported' in s or 'effect' in s:return 'unsupported_reader_or_effect'
    if 'mesh' in s or 'index' in s or 'vertex' in s:return 'mesh_layout_or_triangle'
    if 'missing' in s or 'not found' in s or 'dependency' in s:return 'dependency_or_missing_file'
    if 'permission' in s or 'denied' in s:return 'filesystem_permissions'
    if 'decode' in s or 'texture' in s:return 'texture_or_data_decode'
    return 'unclassified_needs_sample'


def recovery_triage(ledger_path,*,limit=300_000):
    classes=Counter();samples=defaultdict(list);retry=defaultdict(list)
    with Path(ledger_path).open(encoding='utf-8') as f:
        for n,line in enumerate(f):
            if n>=limit:raise ValueError('Too many ledger records')
            if not line.strip():continue
            r=json.loads(line)
            if r.get('status') in ('decoded','indexed','preserved','complete','ok'):continue
            reason=r.get('error_type') or r.get('reason') or r.get('error') or r.get('status')
            category=failure_class(reason,r.get('kind',''))
            classes[category]+=1
            if len(samples[category])<20:
                samples[category].append({'path':str(r.get('path') or r.get('source') or '')[:250],
                                          'reason':str(reason)[:280], 'kind':r.get('kind')})
            retry[category].append(r.get('path') or r.get('source'))
    action={
        'compression_or_xnb_header':'Recheck XNB signature and compressed payload using the available XNB readers',
        'unsupported_reader_or_effect':'Extract type-reader data or compiled effect for research; do not report decoded as rendered',
        'mesh_layout_or_triangle':'Validate vertex declaration, primitive indices and local bone transforms',
        'dependency_or_missing_file':'Verify asset roots and referenced resources before retrying',
        'filesystem_permissions':'Read-only path/access diagnostic: do not modify game installation',
        'texture_or_data_decode':'Try explicitly supported image formats and record original decoder errors',
        'unclassified_needs_sample':'Keep sample bytes local; obtain decoder traceback and identify reader'
    }
    return {'format':'wosb-retry-triage-v1','counts':dict(classes),
            'queues':[{'category':c,'count':n,'recommended_action':action[c],
                       'samples':samples[c], 'retry_requires_original_client_files':True} for c,n in classes.most_common()],
            'note':'Diagnostic queue only: no asset is automatically marked fixed or decoded.'}


def inventory_tree(root,*,extensions=('.xnb','.png','.obj','.glb','.json'),file_limit=400_000,max_bytes=512*1024*1024):
    """Hash only bounded user-selected assets. Keep absolute file paths out of report."""
    base=Path(root).resolve(strict=True)
    if not base.is_dir():raise ValueError('Expected directory')
    files={};count=0
    for p in sorted(base.rglob('*')):
        if p.is_symlink():raise ValueError('External symbolic links are not allowed in local asset snapshots')
        if not p.is_file() or p.suffix.lower() not in extensions:continue
        count+=1
        if count>file_limit:raise ValueError('File count limit exceeded')
        rel=p.relative_to(base).as_posix();size=p.stat().st_size
        if size>max_bytes:files[rel]={'bytes':size,'hash':'skipped-oversized'};continue
        h=hashlib.sha256()
        with p.open('rb') as f:
            for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
        files[rel]={'bytes':size,'sha256':h.hexdigest()}
    return {'format':'wosb-client-asset-snapshot-v1','files':files,'count':count,
            'privacy':'Only relative filenames, content hashes and byte sizes. No raw assets are exported.'}


def diff_inventories(old,new):
    a=old['files'];b=new['files']
    return {'format':'wosb-client-asset-diff-v1',
            'added':sorted(set(b)-set(a)),'removed':sorted(set(a)-set(b)),
            'changed':sorted(k for k in set(a)&set(b) if a[k]!=b[k]),
            'unchanged':sum(a[k]==b[k] for k in set(a)&set(b)),
            'warning':'Asset content changes do not alone prove changed game mechanics.'}


def audit_design(appearance,*,selected_design=None):
    texture_keys={str(k).casefold() for k in appearance.get('textures',{})}
    from appearance_lab import canonical_material
    available={canonical_material(t) for t in texture_keys}
    groups={canonical_material(x) for x in appearance.get('mesh_materials',[])}
    reports=[]
    for design in appearance.get('designs',[]):
        if selected_design is not None and str(design.get('id'))!=str(selected_design):continue
        expected={canonical_material(k):canonical_material(v) for k,v in design.get('swaps',{}).items()}
        matched={k:v for k,v in expected.items() if k in groups}; loaded={k:v for k,v in matched.items() if v in available}
        reports.append({'name':design.get('name'), 'id':design.get('id'),
                        'source_mappings':len(expected),'mesh_matches':len(matched),'replacement_images_loaded':len(loaded),
                        'unmatched_base_materials':sorted(set(expected)-set(matched)),
                        'unloaded_replacement_images':sorted(set(matched.values())-set(loaded.values())),
                        'expected_materials':matched,
                        'status':('no mesh matches' if not matched else 'candidate complete' if len(loaded)==len(matched) else 'partial/missing GPU texture candidates')})
    return {'format':'wosb-design-bindings-v1','designs':reports,'game_shader_equivalence_verified':False,
            'note':'Available image is not proof of upload or draw-call use; WebGL runtime diagnostics are required.'}


def save_json(data,output):
    p=Path(output);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding='utf-8')
    return p
