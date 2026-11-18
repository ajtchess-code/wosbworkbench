"""Offline source-aware coverage and missing-data audit for WoSB Workbench.

Audits report artifacts and the local catalog. It never treats source counts as
percentages of the entire game, and never executes game assemblies.
"""
from __future__ import annotations
import csv
import hashlib
import io
import json
from collections import defaultdict
from pathlib import Path
import zipfile
from mechanics_taxonomy import coverage, domain_for_dataset
from workbench_db import utcnow
from discovery_extensions import (normalize_game_path, compare_inventories,
    unpack_unknowns, decoder_priority, extra_catalog_findings,
    index_relationships, save_research_pages, compare_structured_code)

MAX_REPORT_FILES = 80000
MAX_JSON_BYTES = 64 * 1024 * 1024


class ReportSource:
    """Read selected diagnostic reports from ZIP/folder, including Workbench Scan1-3.

    Alias Windows-style paths and nested ``Reports/ScanX`` into canonical
    ``Game``, ``Steam`` and ``Launcher`` paths without extracting or duplicating
    the archive. Always prefer the original Catalog over Catalog-2 duplicates.
    """
    def __init__(self, path):
        self.path = Path(path)
        self.z = zipfile.ZipFile(self.path) if self.path.is_file() and self.path.suffix.lower() == '.zip' else None
        if self.z:
            info = self.z.infolist()
            if len(info) > MAX_REPORT_FILES:
                self.z.close()
                raise ValueError('Too many report entries')
            raw = {x.filename.replace('\\', '/'): x.filename for x in info if not x.is_dir()}
        elif self.path.is_dir():
            raw = {p.relative_to(self.path).as_posix(): p for p in self.path.rglob('*') if p.is_file()}
            if len(raw) > MAX_REPORT_FILES:
                raise ValueError('Too many report entries')
        else:
            raise ValueError('Choose a report ZIP or report folder')
        labels = self._scan_labels(raw, self.z)
        self.names = {}
        # Prefer first-class Catalog over duplicated Catalog-2; do not import both.
        for name, reference in sorted(raw.items(), key=lambda kv: ('/Catalog-2/' in kv[0], kv[0])):
            segments = name.split('/')
            if segments and segments[0] == 'Reports':
                segments = segments[1:]
            if segments and segments[0].lower() in labels:
                segments[0] = labels[segments[0].lower()]
            canonical = '/'.join(segments).replace('/Catalog-2/', '/Catalog/')
            self.names.setdefault(canonical, reference)

    @staticmethod
    def _scan_labels(raw, archive=None):
        mapping = {'scan1':'Game','scan2':'Launcher','scan3':'Steam'}
        status = next((ref for k,ref in raw.items() if k.endswith('CombinedStatus.json')), None)
        if status is None:return mapping
        try:
            # Bound the status lookup; this is untrusted uploaded content.
            if isinstance(status, Path):
                if status.stat().st_size > 1024*1024:return mapping
                contents = status.read_bytes()
            else:
                if archive is None or archive.getinfo(status).file_size > 1024*1024:return mapping
                contents = archive.read(status)
            data = json.loads(contents)
            for entry in data.get('targets', []):
                label = str(entry.get('label','')).lower()
                location = str(entry.get('root','')).lower().replace('\\','/')
                if label.startswith('scan'):
                    mapping[label] = 'Launcher' if 'launcher' in location else 'Steam' if 'steam' in location else 'Game'
        except (OSError,ValueError,TypeError):pass
        return mapping

    def close(self):
        if self.z:self.z.close()

    def read(self, name, max_size=MAX_JSON_BYTES):
        item = self.names.get(name)
        if item is None:return None
        if self.z:
            inf = self.z.getinfo(item)
            if inf.file_size > max_size:raise ValueError('Report file exceeds size limit: '+name)
            with self.z.open(item) as f:raw = f.read(max_size + 1)
        else:
            if item.stat().st_size > max_size:raise ValueError('Report file exceeds size limit: '+name)
            raw = item.read_bytes()
        if len(raw) > max_size:raise ValueError('Report file exceeds size limit: '+name)
        return raw

    def json(self, name):
        data = self.read(name)
        return json.loads(data.decode('utf-8-sig')) if data is not None else None

    def csv(self, name):
        data = self.read(name)
        if data is None:return []
        return list(csv.DictReader(io.StringIO(data.decode('utf-8-sig', errors='replace'))))

    def roots(self):
        return sorted({n.split('/', 1)[0] for n in self.names if '/Analysis/Summary.json' in n or '/Catalog/Extraction-Summary.json' in n})


def finding(category, severity, title, description, count=0, evidence='', next_action='', source='report', sample=None):
    basis = '\x00'.join([source, category, title, evidence])
    return {'key':hashlib.sha256(basis.encode()).hexdigest()[:24], 'category':category,
            'severity':severity,'title':title,'description':description,
            'count':int(count),'evidence':evidence,'action':next_action,
            'source':source,'sample':(sample or [])[:12]}


def _asset_group(filename):
    p = filename.lower().replace('\\','/')
    if 'model' in p or 'ship/' in p or 'ship_' in p:return '3D models and ship meshes'
    if 'texture' in p or 'sprite' in p or 'icon' in p or 'image' in p:return 'Textures and sprites'
    if 'map' in p or 'world' in p or 'island' in p:return 'World and map assets'
    return 'Other XNB content'


def scan_reports(report_path):
    src=ReportSource(report_path)
    findings=[]; builds={}; xnb={}; inventories={}; decoder_queue=[]; expected_roots=src.roots()
    try:
        if not expected_roots:
            raise ValueError('No analysis or extraction summaries were found at the expected report paths')
        for root in expected_roots:
            aroot=f'{root}/Analysis'; croot=f'{root}/Catalog'
            findings.extend(unpack_unknowns(src,root,aroot,finding))
            queue,decoder_findings=decoder_priority(src,root,aroot,finding)
            decoder_queue.extend(queue)
            findings.extend(decoder_findings)
            analysis=src.json(aroot+'/Summary.json') or {}
            catalog=src.json(croot+'/Extraction-Summary.json') or {}
            builds[root]={'analysis':analysis,'catalog':catalog}
            if not analysis:
                findings.append(finding(root,'high',f'{root}: missing client analysis summary','The expected analysis summary was not present.',evidence=aroot+'/Summary.json',next_action='Run Client Analysis for this installation.'))
            if not catalog and root.lower() != 'launcher':
                findings.append(finding(root,'high',f'{root}: missing extraction summary','Catalog extraction did not provide a summary.',evidence=croot+'/Extraction-Summary.json',next_action='Run the full extractor and review its worker log.'))
            if catalog:
                if not catalog.get('KnownCodeBuild',True):
                    findings.append(finding('Build compatibility','critical',f'{root}: unknown Common.dll version',
                        'The extractor does not recognize this build; code-derived recipes, factory levels, and other mechanics can be absent.',
                        1,croot+'/Extraction-Summary.json','Add fingerprint-aware code matching for this build before treating derived table absences as game facts.'))
                counts=catalog.get('Tables') or {}
                for key,label in [('Images','decoded images'),('Entity_Images','linked item images'),
                                  ('Crafting_Recipes','crafting recipes'),('Factory_Levels','mine/manufactory production'),
                                  ('Ship_Materials','ship construction materials'),('WindRoses','wind roses')]:
                    if int(counts.get(key,0))==0:
                        severity='high' if key in ('Images','Crafting_Recipes','Factory_Levels') else 'medium'
                        findings.append(finding(domain_for_dataset(key),severity,f'{root}: no {label}',
                            'The derived table is absent or contains zero rows in this extraction. This does not prove the game lacks the mechanic.',
                            0,croot+'/Extraction-Summary.json','Inspect source/decoder support for '+key+'.'))
                issues=int(catalog.get('IssueCount') or 0)
                if issues:
                    findings.append(finding('Asset decoding','high',f'{root}: extractor reported {issues:,} issues',
                        'Catalog generation encountered issues; inspect Extraction_Issues for recurring causes.',issues,croot+'/Extraction-Summary.json',
                        'Group failures by format and fix the highest-yield decoder first.'))
            xnbitems=src.json(aroot+'/Client/XNBHeaders.json')
            if isinstance(xnbitems,list):
                ship_assets=[item for item in xnbitems
                     if '/models/ships/' in str(item.get('source','')).lower().replace('\\','/')
                     and str(item.get('source','')).lower().endswith('.xnb')]
                hitbox_assets=[item for item in ship_assets if 'externalhitbox' in str(item.get('source','')).lower()]
                if ship_assets:
                    pending=[item for item in ship_assets if item.get('status') not in ('content_header_read','decoded')]
                    findings.append(finding('Ship geometry','critical' if pending else 'medium',
                        f'{root}: {len(ship_assets)} ship model XNB files; {len(pending)} not decoded',
                        f'{len(hitbox_assets)} ship-specific external-hitbox filenames discovered. '
                        'Model file presence does not prove damage multipliers or enable a mesh viewer until geometry is decoded.',
                        len(pending),aroot+'/Client/XNBHeaders.json',
                        'Use the Ship 3D model sample exporter to collect small user-reviewed XNB examples, '
                        'validate decompression, then implement game-specific content readers. '
                        'Do not generate or highlight conjectured weak points.',
                        sample=[item.get('source','') for item in (hitbox_assets+pending)[:12]]))
                xnb[root]=xnbitems
                failures=defaultdict(list)
                for item in xnbitems:
                    status=str(item.get('status') or '')
                    if status in ('decompression_failed','content_header_failed','malformed','decode_failed'):
                        failures[_asset_group(item.get('source',''))].append(item.get('source',''))
                for group,names in failures.items():
                    findings.append(finding('Asset decoding','critical' if '3D' in group else 'high',
                        f'{root}: {len(names):,} failed {group.lower()} files',
                        'XNB content could not be decoded; these assets are not available for wiki enrichment, model reconstruction or image references.',
                        len(names),aroot+'/Client/XNBHeaders.json',
                        'Investigate wrapped Windows LZX decompression and content-reader registration. Validate with original known-good samples.',sample=names))
            image_health=src.csv(aroot+'/Client/ImageDecodeHealth.csv')
            imagefail=[i for i in image_health if str(i.get('status','')).lower() in ('failed','error')]
            if imagefail:
                findings.append(finding('Asset decoding','high',f'{root}: {len(imagefail):,} image-decoder failures',
                    'Failed image decoding includes non-image XNB assets; interpret this as an attempted-decoder count, not confirmed missing images.',
                    len(imagefail),aroot+'/Client/ImageDecodeHealth.csv',
                    'Classify assets by content reader first, then retry only images with compatible decoders.',
                    sample=[i.get('source','') for i in imagefail[:12]]))
            errors=src.csv(aroot+'/Combat/Errors.csv')
            if errors:
                findings.append(finding('Code coverage','medium',f'{root}: {len(errors)} .NET analysis errors',
                    'Some failures may be expected native DLLs; inspect types before concluding that game code was lost.',
                    len(errors),aroot+'/Combat/Errors.csv',
                    'Separate native/unsupported files from failed managed assemblies.'))
            inventory=src.json(aroot+'/Client/FileInventory.json')
            if isinstance(inventory,list):
                inventories[root]={normalize_game_path(v.get('path',''),root):str(v.get('sha256','')) for v in inventory if v.get('path')}
        # Differences are evidence of separate builds, not necessarily missing data.
        normal=[r for r in builds if r.lower() in ('game','steam')]
        if len(normal)==2:
            a,b=normal
            ta=(builds[a]['catalog'].get('Tables') or {});tb=(builds[b]['catalog'].get('Tables') or {})
            for table in sorted(set(ta)|set(tb)):
                na=int(ta.get(table,0));nb=int(tb.get(table,0))
                if na!=nb and (na==0 or nb==0 or abs(na-nb)>max(20,min(na,nb)*0.05)):
                    findings.append(finding('Build comparison','high' if not min(na,nb) else 'medium',
                        f'{table}: {a} {na:,} vs {b} {nb:,}',
                        'Derived table sizes differ across installations. A zero count may indicate an unsupported code build.',
                        abs(na-nb),f'{a}/Catalog/Extraction-Summary.json + {b}/Catalog/Extraction-Summary.json',
                        'Compare client versions and extractor compatibility; do not merge rows without source-build labels.'))
            sha_a=builds[a]['catalog'].get('CommonSHA256');sha_b=builds[b]['catalog'].get('CommonSHA256')
            if sha_a and sha_b and sha_a!=sha_b:
                findings.append(finding('Build comparison','medium','Different Common.dll fingerprints across game installations',
                    'The installed builds differ. Mechanics formulas and item values must retain their build provenance.',
                    2,f'{a}/Catalog/Extraction-Summary.json + {b}/Catalog/Extraction-Summary.json',
                    'Keep distinct build versions in the wiki and compare code-derived mechanics carefully.'))
        comparisons=compare_inventories(inventories)
        if comparisons:
            for key,label,severity in (('game_only','only in standalone installation','medium'),
                                       ('steam_only','only in Steam installation','medium'),
                                       ('different_hash','differing hashes across game installations','high')):
                count=comparisons[key]
                if count:
                    sample=comparisons[{'game_only':'game_only_sample','steam_only':'steam_only_sample',
                                        'different_hash':'changed_sample'}[key]]
                    findings.append(finding('Build comparison',severity,
                        f'{count:,} files {label}',
                        'Compared normalized relative paths and SHA-256 hashes. Differences might represent version changes, optional files or packaging, not incomplete extraction.',
                        count,'Game/Analysis/Client/FileInventory.json + Steam/Analysis/Client/FileInventory.json',
                        'Inspect differing paths and hashes; keep build provenance when interpreting code or game data.',sample=sample))
        structured_comparisons=compare_structured_code(src)
        for result in structured_comparisons:
            for key,label in (('only_game','only in standalone'),('only_steam','only in Steam'),
                              ('changed_values','with changed values/signatures')):
                count=result[key]
                if count:
                    sample=result[{'only_game':'only_game_sample','only_steam':'only_steam_sample',
                                   'changed_values':'changed_sample'}[key]]
                    findings.append(finding('Build comparison','high' if key=='changed_values' else 'medium',
                        f'{result["dataset"]}: {count} definitions {label}',
                        'Compared client metadata records between the two installations. Differences may reflect game versions, not missing extraction.',
                        count,f'Game/Catalog/AI-Data/{result["dataset"]}.jsonl + Steam/Catalog/AI-Data/{result["dataset"]}.jsonl',
                        'Inspect values and source assembly fingerprints before merging or describing behavior.',sample=sample))
        if comparisons.get('launcher_unique'):
            findings.append(finding('Build comparison','low',
                f'{comparisons["launcher_unique"]} launcher-specific files',
                'The launcher has an independent software role; its unique files are expected and are not automatically missing gameplay content.',
                comparisons['launcher_unique'],'Launcher/Analysis/Client/FileInventory.json',
                'Inspect launcher files separately for relevant configuration and schemas; avoid mixing launcher resources with game definitions.',
                sample=comparisons['launcher_unique_sample']))
        for r in builds:
            for key in ('Gamepedia','Crew_Sailors','Dig_Sites_Map_References','UI_Image_Groups'):
                count=(builds[r]['catalog'].get('Tables') or {}).get(key)
                if count==0 and key!='UI_Image_Groups':
                    findings.append(finding(domain_for_dataset(key),'low',f'{r}: empty {key} dataset',
                        'No records extracted. This is a candidate investigation, not proof the game lacks corresponding content.',
                        evidence=f'{r}/Catalog/Extraction-Summary.json',next_action='Verify whether client content exists in other tables or unrecognized formats.'))
        return {'source':str(report_path),'roots':expected_roots,'builds':{k:{'common_sha256':v['catalog'].get('CommonSHA256'),
                 'known_code_build':v['catalog'].get('KnownCodeBuild'),
                 'tables':v['catalog'].get('Tables',{}),'files_scanned':v['analysis'].get('files_scanned',0)} for k,v in builds.items()},
                'findings':findings,'decoder_queue':decoder_queue,'comparisons':comparisons,'structured_comparisons':structured_comparisons,'audited_utc':utcnow()}
    finally:src.close()


def audit_catalog(db):
    """Check imported tables and exact, source-scoped catalog links."""
    findings=[]; domains=coverage(db)
    for d in domains:
        missing=[x['dataset'] for x in d['datasets'] if not x.get('available', True)]
        if missing and d['key']!='unclassified':
            findings.append(finding(d['key'],'low',d['title']+': '+str(len(missing))+' source tables absent',
                'The local catalog lacks some candidate datasets. Optional imports or incompatible client builds may explain an absent table.',
                len(missing),'Workbench.sqlite3 / records',
                'Inspect source reports and import options before marking game systems absent.',sample=missing,source='catalog'))
    unreviewed=db.conn.execute("SELECT count(*) FROM articles WHERE review_status NOT IN ('reviewed','verified')").fetchone()[0]
    if unreviewed:
        findings.append(finding('Wiki quality','medium','Wiki pages awaiting editorial verification',
            'Wiki outlines and source-only drafts are not confirmed gameplay explanations.',
            unreviewed,'Workbench.sqlite3 / articles',
            'Attach source, client version, precise conditions and gameplay verification.',source='catalog'))
    # Multiple builds can contain different IDs; never resolve references against the other installation.
    indexed={}
    for row in db.conn.execute("SELECT dataset,source_root,raw_json FROM records WHERE dataset IN ('Resources','ShipsToPlay','Crafting_Recipes')"):
        try:rec=json.loads(row['raw_json'])
        except (ValueError,TypeError):continue
        val=rec.get('ID',rec.get('RecipeID'))
        if val is None:val=rec.get('StaticInfoID')
        if val is None:continue
        if row['dataset']=='Resources':
            val='res_'+str(val).removeprefix('res_')
        indexed.setdefault((row['source_root'],row['dataset']),set()).add(str(val))
    for dataset,field,target,kind in (('Recipe_Ingredients','ResourceID','Resources','res'),
                                       ('Ship_Materials','ResourceID','Resources','res'),
                                       ('Cannon_Materials','ResourceID','Resources','res'),
                                       ('Ship_Materials','ShipID','ShipsToPlay','id'),
                                       ('Recipe_Ingredients','RecipeID','Crafting_Recipes','id')):
        missing={};unchecked={}
        for row in db.conn.execute('SELECT source_root,raw_json FROM records WHERE dataset=? LIMIT 40000',(dataset,)):
            try:obj=json.loads(row['raw_json'])
            except (ValueError,TypeError):continue
            value=obj.get(field)
            if value is None:continue
            val=str(value)
            if kind=='res':val='res_'+val.removeprefix('res_')
            root=row['source_root']; available=indexed.get((root,target))
            if not available:
                unchecked[root]=unchecked.get(root,0)+1
            elif val not in available:
                missing.setdefault(root,[]).append(val)
        for root,values in missing.items():
            findings.append(finding('Cross-references','high',
                f'{root}: {dataset}.{field} unresolved against {target}',
                'IDs were compared using consistent resource prefixes and only within the same imported client build.',
                len(values),'Workbench.sqlite3 / '+dataset,
                'Inspect imported source rows; verify type and ID mapping before concluding referenced objects are absent.',
                sample=sorted(set(values))[:12],source='catalog'))
        for root,n in unchecked.items():
            findings.append(finding('Cross-references','medium',
                f'{root}: {dataset}.{field} cannot be checked; {target} missing',
                'Target dataset was not imported for this build, so reference resolution is unknown.',
                n,'Workbench.sqlite3 / '+dataset,
                'Import the missing target table from the same client build and rerun the audit.',source='catalog'))
    findings.extend(extra_catalog_findings(db,finding))
    relation_count=index_relationships(db)
    # Create research questions tied to identifiable candidates, not invented formulas.
    crafting=db.conn.execute('''SELECT DISTINCT from_label,to_id,evidence FROM discovery_relations
        WHERE to_type='modifier' AND
        (lower(to_id) LIKE '%crafttime%' OR lower(to_id) LIKE '%workshop%' OR lower(to_id) LIKE '%warehouse%')
        LIMIT 40''').fetchall()
    if crafting:
        findings.append(finding('Mechanics relationships','high',
            'Determine how crafting-time and workshop bonuses stack',
            'Multiple item/skill/guild modifiers appear to change related crafting systems, but their ordering, caps, interactions and server effects are not established by listing them.',
            len(crafting),'Workbench.sqlite3 / discovery_relations',
            'Trace corresponding calculation methods; test guild benefits, captain skills, port buildings and warehouse limits together.',
            sample=[f'{r[0]} → {r[1]} ({r[2]})' for r in crafting[:12]],source='catalog'))
    fire=db.conn.execute('''SELECT full_name,source_root,assembly,token FROM combat_evidence
        WHERE lower(full_name) LIKE '%burningcheck%' OR lower(full_name) LIKE '%createmicroburning%'
        LIMIT 30''').fetchall()
    if fire:
        findings.append(finding('Mechanics relationships','high',
            'Identify full conditions for microfire to large-fire escalation',
            'Relevant burning methods are present in static client code. Their call conditions and live-server outcomes still require validation.',
            len(fire),'Workbench.sqlite3 / combat_evidence',
            'Trace callers and callees, parameter sources and ship state transitions; compare with controlled in-game tests.',
            sample=[f'{r[1]} / {r[2]} {r[3]} {r[0]}' for r in fire[:12]],source='catalog'))
    return {'source':'local-catalog','roots':[],'builds':{},'findings':findings,
            'domains':domains,'relationship_count':relation_count,'audited_utc':utcnow()}


def save_audit(db, report):
    db.conn.execute('''CREATE TABLE IF NOT EXISTS discovery_findings (
      key TEXT PRIMARY KEY,category TEXT NOT NULL,severity TEXT NOT NULL,title TEXT NOT NULL,
      description TEXT NOT NULL,count INTEGER NOT NULL,evidence TEXT NOT NULL,action TEXT NOT NULL,
      source TEXT NOT NULL,sample_json TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'open',updated_utc TEXT NOT NULL)''')
    for f in report['findings']:
        db.conn.execute('''INSERT INTO discovery_findings
          (key,category,severity,title,description,count,evidence,action,source,sample_json,status,updated_utc)
          VALUES(?,?,?,?,?,?,?,?,?,?,'open',?) ON CONFLICT(key) DO UPDATE SET
          category=excluded.category,severity=excluded.severity,title=excluded.title,
          description=excluded.description,count=excluded.count,evidence=excluded.evidence,
          action=excluded.action,source=excluded.source,sample_json=excluded.sample_json,
          updated_utc=excluded.updated_utc''',
          (f['key'],f['category'],f['severity'],f['title'],f['description'],f['count'],
           f['evidence'],f['action'],f['source'],json.dumps(f['sample'],ensure_ascii=False),utcnow()))
    db.conn.execute('''CREATE TABLE IF NOT EXISTS discovery_runs
          (id INTEGER PRIMARY KEY,source TEXT NOT NULL,roots_json TEXT NOT NULL,
           finding_count INTEGER NOT NULL,run_utc TEXT NOT NULL)''')
    db.conn.execute('INSERT INTO discovery_runs(source,roots_json,finding_count,run_utc) VALUES(?,?,?,?)',
                    (str(report['source']),json.dumps(report.get('roots',[])),len(report['findings']),utcnow()))
    db.conn.commit()
    save_research_pages(db,report['findings'])
    return len(report['findings'])


def list_findings(db, query='', include_reviewed=False, limit=1000):
    conditions=[];values=[]
    if not include_reviewed:conditions.append("status='open'")
    if query:
        conditions.append('(title LIKE ? OR category LIKE ? OR description LIKE ?)');values.extend(['%'+query+'%']*3)
    where=' WHERE '+' AND '.join(conditions) if conditions else ''
    return db.conn.execute('SELECT * FROM discovery_findings'+where+
        " ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,count DESC,title LIMIT ?",(*values,limit)).fetchall()


def export_findings(db,path):
    items=[]
    for r in list_findings(db,include_reviewed=True,limit=100000):
        item=dict(r);item['sample']=json.loads(item.pop('sample_json'))
        items.append(item)
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps({'tool':'WoSB Workbench discovery audit','version':'1',
                                'exported_utc':utcnow(),'findings':items},indent=2,ensure_ascii=False),encoding='utf-8')
    return path


def export_relationships(db,path):
    """Export only source-linked relationships; never assert a modifier applies at runtime."""
    rows=[dict(x) for x in db.conn.execute('SELECT * FROM discovery_relations ORDER BY source_root,relation,from_type,from_id')]
    dest=Path(path)
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps({'version':1,'warning':'Candidate static links; verify game server mechanics before making claims',
                                'relations':rows},ensure_ascii=False,indent=2),encoding='utf-8')
    return dest
