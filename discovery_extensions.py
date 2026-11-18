"""Additional bounded, evidence-linked WoSB catalog discovery.

All relationships are candidate links from client files; this module does not
claim that game or server mechanics have been proven. Reports are read-only.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict

MAX_ROWS_PER_DATASET = 25000
MAX_CONNECTIONS = 30000
ENGINE_DATASETS = (
    'CaptainSkills', 'GuildBonuses', 'ShipUpgradesNew', 'PortLevelBonuses',
    'Benefit_Levels', 'ShipsToPlay', 'Ship_Materials', 'Crafting_Recipes',
    'Recipe_Ingredients', 'Factory_Levels', 'Cannon_Materials', 'Ship_Construction', 'Game_Enums', 'Game_Schemas',
    'Gameplay_Methods', 'Resources', 'Cannons', 'CannonBalls',
)
MODIFIER_REGEX = re.compile(r'\b[A-Z][A-Za-z][A-Za-z0-9]{3,}\b')
MODIFIER_STOP = {'None', 'True', 'False', 'Status', 'Source', 'Common', 'Name', 'Type'}
DOMAINS = {
    'crafting': ('craft', 'workshop', 'warehouse', 'manufactory', 'factory', 'production', 'mine', 'worker'),
    'fire': ('fire', 'burn', 'ignite', 'flame'),
    'combat': ('damage', 'armor', 'critical', 'penetration', 'resist', 'health', 'reload'),
    'sailing': ('wind', 'speed', 'sail', 'mobility', 'turn', 'rudder'),
    'shipbuilding': ('ship', 'shipway', 'construction', 'repair', 'upgrade'),
    'guilds': ('guild', 'port', 'fort'),
    'economy': ('market', 'trade', 'gold', 'price', 'capacity'),
}


def normalize_game_path(path, root):
    """Remove known container folders, not semantic path segments."""
    p = str(path).replace('\\', '/').lstrip('/').casefold()
    if root.casefold() == 'game' and p.startswith('default/game/'):
        p = p[len('default/game/'):]
    return p


def compare_inventories(inventories):
    if 'Game' not in inventories or 'Steam' not in inventories:
        return {}
    a = inventories['Game']
    b = inventories['Steam']
    only_a = sorted(set(a) - set(b))
    only_b = sorted(set(b) - set(a))
    changed = sorted(path for path in a.keys() & b.keys() if a[path] and b[path] and a[path] != b[path])
    result={'game_only': len(only_a), 'steam_only': len(only_b), 'different_hash': len(changed),
            'shared': len(a.keys() & b.keys()), 'game_only_sample': only_a[:30],
            'steam_only_sample': only_b[:30], 'changed_sample': changed[:30]}
    if 'Launcher' in inventories:
        launcher=inventories['Launcher']
        unique=sorted(set(launcher)-set(a)-set(b))
        result['launcher_unique']=len(unique)
        result['launcher_unique_sample']=unique[:30]
    return result


def unpack_unknowns(src, root, analysis_prefix, finding):
    """Group unknown on-disk file formats and non-texture content readers."""
    results=[]
    file_inventory = src.json(analysis_prefix+'/Client/FileInventory.json') or []
    groups=defaultdict(list)
    for item in file_inventory:
        fmt=str(item.get('format', ''))
        if fmt in ('unrecognized', 'unknown', 'XNB with unknown 4-byte wrapper'):
            ext = str(item.get('extension') or '<no extension>')
            groups[(fmt, ext)].append(str(item.get('path', '')))
    for (fmt, ext), paths in sorted(groups.items(), key=lambda t:-len(t[1])):
        results.append(finding('Unknown data discovery','medium',
            f'{root}: {len(paths)} unclassified {ext} files ({fmt})',
            'The format scanner has not classified these files. Some may be ordinary data or third-party files, not missing gameplay data.',
            len(paths), analysis_prefix+'/Client/FileInventory.json',
            'Inspect file signatures and parent paths; register a safe decoder only after confirming the content.',
            sample=paths))
    xnb=src.json(analysis_prefix+'/Client/XNBHeaders.json') or []
    reader_groups=defaultdict(list)
    for item in xnb:
        for rdr in item.get('reader_types') or []:
            name = str(rdr)
            # Only Texture2D has a dedicated type-reader implementation at present.
            if 'Texture2DReader' not in name:
                reader_groups[name].append(str(item.get('source','')))
    for name,paths in sorted(reader_groups.items(), key=lambda t:-len(t[1]))[:50]:
        results.append(finding('Unknown content readers','medium',
            f'{root}: non-texture XNB reader {name[:140]}',
            'This content reader is visible in decoded headers, but the current image reader handles Texture2D only. Its payload may contain game data, geometry or non-image assets.',
            len(paths),analysis_prefix+'/Client/XNBHeaders.json',
            'Document its schema and implement a bounded parser using sample content; do not load game DLLs.',sample=paths))
    return results


def decoder_priority(src, root, prefix, finding):
    """Rank failures by asset family, compression and observed failure status."""
    headers=src.json(prefix+'/Client/XNBHeaders.json') or []
    buckets=defaultdict(list)
    for item in headers:
        status=str(item.get('status') or '')
        if status in ('content_header_read', 'ok', 'decoded', ''):continue
        source=str(item.get('source') or '')
        sp=source.lower().replace('\\','/')
        family=('Sprite and icon assets' if '/modeltextures/' in sp or '/textures/' in sp or 'sprite' in sp or 'icon' in sp else
                '3D ship or world models' if '/models/' in sp or '/ships/' in sp else
                'Map and environment' if '/maps/' in sp or '/world' in sp else
                'Other content')
        compression=('LZX' if item.get('compressed_lzx') else 'LZ4' if item.get('compressed_lz4') else 'uncompressed/unknown')
        buckets[(compression,status,family)].append(source)
    rank={'3D ship or world models':3,'Map and environment':2,'Sprite and icon assets':2,'Other content':1}
    ordered=sorted(buckets.items(), key=lambda pair:(-(len(pair[1])*rank[pair[0][2]]),-len(pair[1])))
    queue=[];findings=[]
    for (compression,status,family),files in ordered:
        priority_score=len(files)*rank[family]
        queue.append({'root':root,'compression':compression,'status':status,'family':family,
                      'file_count':len(files),'priority_score':priority_score,'sample_files':files[:20],
                      'estimated_yield':'number of affected files; not a guarantee of recovered assets'})
        findings.append(finding('Decoder improvement queue','critical' if '3D' in family else 'high',
           f'{root}: {family}, {compression}, {status}',
           'These assets share a failure mode and can be targeted together. Priority score reflects affected file count and relevance, not probability of successful recovery.',
           len(files),prefix+'/Client/XNBHeaders.json',
           'Reproduce on one sample, fix format handling, test against known-good output, then rerun and compare recovered content.',
           sample=files))
    return queue,findings


def _documented_domain(symbol):
    s=symbol.lower()
    return [name for name,words in DOMAINS.items() if any(word in s for word in words)]


def _modifiers(record, dataset):
    fragments=[]
    if dataset=='CaptainSkills':fragments=[record.get('Effect','')]
    if dataset=='GuildBonuses':fragments=[record.get('Type','')]
    if dataset=='ShipUpgradesNew':fragments=[record.get('EffectsBoost','')]
    if dataset=='PortLevelBonuses':fragments=[record.get('Type',''),record.get('Effect','')]
    if dataset=='Benefit_Levels':fragments=[record.get('Type',''),record.get('Effect','')]
    tokens=set()
    for fragment in fragments:
        if not isinstance(fragment, str):continue
        for token in MODIFIER_REGEX.findall(fragment):
            if token not in MODIFIER_STOP and len(token)<=100:tokens.add(token)
    return sorted(tokens)


def index_relationships(db):
    """Build persistent edges using exact source IDs and bonus symbols.

    Cross-source edges are candidate correlations, not a proof of stacking or
    causation. Do not bridge separate game builds by ID alone.
    """
    db.conn.execute('''CREATE TABLE IF NOT EXISTS discovery_relations (
       key TEXT PRIMARY KEY, source_root TEXT NOT NULL, from_type TEXT NOT NULL,
       from_id TEXT NOT NULL, from_label TEXT NOT NULL, to_type TEXT NOT NULL,
       to_id TEXT NOT NULL, relation TEXT NOT NULL, domain TEXT NOT NULL,
       evidence TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'candidate')''')
    db.conn.execute('DELETE FROM discovery_relations')
    rows=db.conn.execute('''SELECT source_root,dataset,external_id,name,raw_json,source_file FROM records
        WHERE dataset IN (''' + ','.join('?'*len(ENGINE_DATASETS)) + ''') ORDER BY source_root,dataset,id LIMIT 120000''', ENGINE_DATASETS)
    def emit(root, from_type,from_id,from_label,to_type,to_id,relation,domain,evidence,status='candidate'):
        if not to_id:return
        key=hashlib.sha256('\0'.join(map(str,(root,from_type,from_id,to_type,to_id,relation))).encode()).hexdigest()[:32]
        db.conn.execute('''INSERT OR IGNORE INTO discovery_relations
            (key,source_root,from_type,from_id,from_label,to_type,to_id,relation,domain,evidence,status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
            (key,root,from_type,str(from_id),str(from_label)[:300],to_type,str(to_id),relation,domain,str(evidence)[:1000],status))
    i=0
    for row in rows:
        try:rec=json.loads(row['raw_json'])
        except (ValueError,TypeError):continue
        root,ds,ext,name=row['source_root'],row['dataset'],row['external_id'],row['name']
        source=f'{root}: {ds}:{ext}; {row["source_file"]}'
        for token in _modifiers(rec,ds):
            emit(root,ds,ext,name,'modifier',token,'grants_or_modifies',','.join(_documented_domain(token)) or 'unclassified',source)
            for domain in _documented_domain(token):
                emit(root,'modifier',token,token,'wiki_domain',domain,'candidate_mechanics_area',domain,source)
        if ds in ('Ship_Materials','Cannon_Materials','Recipe_Ingredients'):
            item=rec.get('ResourceID')
            if item is not None:
                domain='crafting' if ds=='Recipe_Ingredients' else 'shipbuilding'
                emit(root,ds,ext,name,'Resources',f'res_{item}','requires_resource',domain,source)
        if ds=='Recipe_Ingredients':
            if rec.get('RecipeID') is not None:
                emit(root,ds,ext,name,'Crafting_Recipes',rec['RecipeID'],'ingredient_of','crafting',source)
        if ds=='Crafting_Recipes':
            if rec.get('OutputType')=='resource' and rec.get('OutputID') is not None:
                emit(root,ds,ext,name,'Resources',f'res_{rec["OutputID"]}','produces','crafting',source)
        if ds=='Ship_Materials' and rec.get('ShipID') is not None:
            emit(root,ds,ext,name,'ShipsToPlay',rec['ShipID'],'part_of_ship_construction','shipbuilding',source)
        i+=1
        if i>=MAX_CONNECTIONS:break
    # Match exact modifier symbols to game-code references. Matching is case-sensitive
    # and only links methods from the same client build; the result is a research lead.
    modifiers={r['to_id'] for r in db.conn.execute("SELECT DISTINCT to_id FROM discovery_relations WHERE to_type='modifier'")}
    for row in db.conn.execute('SELECT source_root,assembly,token,full_name,evidence_json,source_file FROM combat_evidence LIMIT 10000'):
        try:obj=json.loads(row['evidence_json'])
        except (TypeError,ValueError):continue
        references=[]
        for key in ('fields_related','calls_related'):
            values=obj.get(key,[])
            if isinstance(values,str):
                try:values=json.loads(values)
                except ValueError:values=[]
            if isinstance(values,list):references.extend(v for v in values if isinstance(v,str))
        found=set()
        for reference in references:
            terminal=reference.rsplit('::',1)[-1].rsplit('.',1)[-1].strip()
            if terminal in modifiers:found.add(terminal)
        # Method-to-domain links let the graph include algorithms for which no
        # known item bonus has yet been extracted.
        for topic in _documented_domain(row['full_name']):
            emit(row['source_root'],'client_method',row['assembly']+'::'+row['token'],
                 row['full_name'],'wiki_domain',topic,'candidate_code_area',topic,
                 row['source_file'],status='candidate')
        for symbol in sorted(found):
            domain=','.join(_documented_domain(symbol)) or 'unclassified'
            emit(row['source_root'],'modifier',symbol,symbol,'client_method',
                 row['assembly']+'::'+row['token'],'referenced_by_client_method',domain,
                 row['source_file']+' :: '+row['full_name'],status='candidate')
    db.conn.commit()
    return db.conn.execute('SELECT count(*) FROM discovery_relations').fetchone()[0]


def extra_catalog_findings(db, finding):
    """Flag novel datasets, unknown typed schemas, and uncataloged modifier candidates."""
    from mechanics_taxonomy import domain_for_dataset
    findings=[]
    categories=dict(db.categories())
    unknown={n:c for n,c in categories.items() if domain_for_dataset(n)=='unclassified'}
    if unknown:
        findings.append(finding('Unknown data discovery','high',
            f'{len(unknown)} imported datasets need classification',
            'These tables are present in the local database but absent from the mechanics taxonomy. They may expose additional systems.',
            sum(unknown.values()),'Workbench.sqlite3 / records',
            'Inspect example rows, assign the datasets to wiki domains, and add source-linked article templates.',
            source='catalog',sample=sorted(unknown,key=unknown.get,reverse=True)))
    # Look for schema type families not yet represented in an existing manual or sourced page.
    type_counts=Counter()
    for rec in db.conn.execute("SELECT raw_json FROM records WHERE dataset IN ('Game_Schemas','Game_Enums') LIMIT 30000"):
        try:val=json.loads(rec['raw_json'])
        except (ValueError,TypeError):continue
        typ=val.get('Type')
        if isinstance(typ,str) and typ:type_counts[typ]+=1
    if type_counts:
        known_sections={str(r[0]).lower() for r in db.conn.execute('SELECT title FROM articles')}
        unknown_types=[(name,count) for name,count in type_counts.most_common() if name.lower() not in known_sections]
        if unknown_types:
            findings.append(finding('Unknown data discovery','medium',
                f'{len(unknown_types)} .NET schema/enum types have no exact wiki article',
                'This is a candidate review inventory: a wiki need not have one article per type. Many may be internal structures.',
                len(unknown_types),'Workbench.sqlite3 / Game_Schemas and Game_Enums',
                'Group by namespace and game subsystem; create wiki pages only for useful gameplay types.',
                source='catalog',sample=[f'{name} ({count} fields)' for name,count in unknown_types[:12]]))
    return findings


def save_research_pages(db, findings, max_pages=125):
    """Automatically create source-linked, editable investigation pages for top gaps."""
    created=0
    for item in sorted(findings,key=lambda x:({'critical':0,'high':1,'medium':2,'low':3}.get(x['severity'],3),-x['count'])):
        if created>=max_pages:break
        if item['severity'] not in ('critical','high'):continue
        parts=['# '+item['title'],'','**Status: investigation needed; not verified gameplay behavior.**','',
               '## What is missing or uncertain','',item['description'],'',
               '## Recommended investigation','',item['action'],'',
               '## Source evidence','', '`'+str(item['evidence']).replace('`','')+'`','',
               '## Examples','']
        parts.extend('- `'+str(v).replace('`','')+'`' for v in item.get('sample',[])[:12])
        parts.extend(['','## Confirmed result','','_Not yet established._'])
        db.upsert_article('discovery-'+item['key'],item['title'],'Research backlog',
                          '\n'.join(parts),'discovery-audit',item['evidence'],
                          'needs-review',preserve_edited=True)
        created+=1
    db.conn.commit()
    return created


def compare_structured_code(src):
    """Compare enum values, schema signatures and method names across game builds."""
    def rows(root,dataset):
        path=f'{root}/Catalog/AI-Data/{dataset}.jsonl'
        raw=src.read(path,max_size=16*1024*1024)
        if not raw:return None
        result={}
        for ln in raw.splitlines()[:60000]:
            try:r=json.loads(ln)
            except (ValueError,TypeError):continue
            if dataset=='Game_Enums':
                key=str(r.get('Type',''))+'::'+str(r.get('Member',''))
                val=str(r.get('Value',''))
            elif dataset=='Game_Schemas':
                key=str(r.get('Type',''))+'::'+str(r.get('Field',''))
                val=str(r.get('SignatureHex',''))
            else:
                key=str(r.get('Type',''))+'::'+str(r.get('Method',''))
                val=str(r.get('Instructions',''))
            if key.strip(':'):result[key]=val
        return result
    comparisons=[]
    for dataset in ('Game_Enums','Game_Schemas','Gameplay_Methods'):
        a=rows('Game',dataset);b=rows('Steam',dataset)
        if a is None or b is None:continue
        only_a=sorted(a.keys()-b.keys());only_b=sorted(b.keys()-a.keys())
        changed=sorted(key for key in a.keys() & b.keys() if a[key]!=b[key])
        comparisons.append({'dataset':dataset,'only_game':len(only_a),'only_steam':len(only_b),
                            'changed_values':len(changed),'only_game_sample':only_a[:15],
                            'only_steam_sample':only_b[:15],
                            'changed_sample':[f'{key}: {a[key]} / {b[key]}' for key in changed[:15]]})
    return comparisons
