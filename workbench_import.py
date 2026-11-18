"""Non-destructive streaming imports from v3 reports, wiki exports, and client Gamepedia."""
from __future__ import annotations
import csv
import io
import json
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from html.parser import HTMLParser
from workbench_db import slugify

# Includes all curated categories by default. Very large diagnostic tables are opt-in.
HEAVY = {'All_Data_Fields','Gameplay_Code_Constants','Asset_Inventory','Map_Objects',
         'World','English_Text','System_English_Text','Game_Schemas','Game_Enums',
         'Gameplay_Methods','English_Names','Named_Entities','ProceduralPresets'}
MAX_ZIP_ITEMS = 40000
MAX_LINE_BYTES = 8 * 1024 * 1024
MAX_INDIVIDUAL_FILE = 400 * 1024 * 1024

class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__();self.bits=[];self.ignore=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'): self.ignore+=1
        elif tag in ('p','h1','h2','h3','li','section','div','br'): self.bits.append('\n')
    def handle_endtag(self,tag):
        if tag in ('script','style'): self.ignore=max(0,self.ignore-1)
    def handle_data(self,data):
        if not self.ignore: self.bits.append(data)
    def text(self):
        return '\n'.join(line.strip() for line in ''.join(self.bits).splitlines() if line.strip())

def path_meta(path):
    parts=path.replace('\\','/').split('/')
    dataset=parts[-1].replace('.jsonl','')
    dataset=re.sub(r'\.part\d+$','',dataset,flags=re.I)
    if parts and parts[0].lower()=='reports':parts=parts[1:]
    label=parts[0].lower() if parts else ''
    root={'scan1':'Game','scan2':'Launcher','scan3':'Steam',
          'game':'Game','steam':'Steam','launcher':'Launcher'}.get(label,'Imported')
    return root,dataset

def is_catalog_jsonl(name):
    s=name.replace('\\','/')
    return '/AI-Data/' in s and s.lower().endswith('.jsonl')

csv.field_size_limit(16 * 1024 * 1024)


class Importer:
    def __init__(self,db):self.db=db

    def catalog_zip(self,archive,all_datasets=False,progress=None):
        """Stream AI-Data JSONL directly from existing ZIP; does not extract binaries."""
        changed=0;processed=0;warnings=[]
        with zipfile.ZipFile(archive) as z:
            all_members=z.infolist()
            if len(all_members)>MAX_ZIP_ITEMS:raise ValueError('ZIP contains too many entries')
            names={m.filename.replace('\\','/') for m in all_members}
            # Some multi-run scans contain byte-for-byte duplicate Catalog-2.
            # Import the primary catalog only when both are present.
            def primary_or_unique(m):
                normalized=m.filename.replace('\\','/')
                if re.search(r'/Catalog-\d+/',normalized) and re.sub(r'/Catalog-\d+/','/Catalog/',normalized) in names:
                    return False
                return True
            members=[m for m in all_members if is_catalog_jsonl(m.filename) and not m.is_dir()
                     and primary_or_unique(m)]
            for m in members:
                root,dataset=path_meta(m.filename)
                if not all_datasets and dataset in HEAVY: continue
                if m.file_size>MAX_INDIVIDUAL_FILE:
                    warnings.append('Skipped large dataset: '+m.filename);continue
                with z.open(m) as stream:
                    text=io.TextIOWrapper(stream,encoding='utf-8-sig',errors='replace')
                    for idx,line in enumerate(text,1):
                        if len(line)>MAX_LINE_BYTES: warnings.append('Oversize row '+m.filename);continue
                        if not line.strip():continue
                        try:data=json.loads(line)
                        except (ValueError,TypeError):
                            warnings.append('Invalid JSON '+m.filename+':'+str(idx));continue
                        if isinstance(data,dict):
                            if self.db.upsert_record(dataset,root,data,idx,m.filename):changed+=1
                            processed+=1
                            if processed%750==0:
                                self.db.conn.commit()
                                if progress:progress(f'{processed:,} records · {dataset}')
                self.db.conn.commit()
                if progress:progress(f'{dataset}: imported {processed:,} total records')
            # Small, high-value mechanics evidence and model candidates are imported
            # even when the giant Asset_Inventory dataset is disabled.
            extra=self._import_research_evidence(z,progress=progress)
            changed+=extra
            for m in z.infolist():
                norm=m.filename.replace('\\','/')
                if norm.endswith('/Analysis/Combat/Methods.csv') and m.file_size<=MAX_INDIVIDUAL_FILE:
                    label=path_meta(m.filename)[0]
                    with z.open(m) as binary:
                        reader=csv.DictReader(io.TextIOWrapper(binary,encoding='utf-8-sig',errors='replace'))
                        for row in reader:
                            if self.db.upsert_combat(label,row,m.filename):changed+=1
                    self.db.conn.commit()
        self.db.log_import(archive,'catalog-zip',changed,'Processed '+str(processed)+' records; '+str(len(warnings))+' warnings')
        return {'records':processed,'changed':changed,'warnings':warnings[:50]}


    def _import_research_evidence(self,z,progress=None):
        """Focused IL and model candidates; no executable client binaries copied."""
        import re
        changed=0;seen=0
        terms=('wind','sail','mast','speed','mobil','maneuv','weather','physics','hitbox',
               'collisio','shipmodel','ship_model','flood','burn','armor','damage','cannonball')
        filenames={m.filename.replace('\\','/') for m in z.infolist()}
        for member in z.infolist():
            norm=member.filename.replace('\\','/')
            if re.search(r'/Catalog-\d+/',norm) and re.sub(r'/Catalog-\d+/','/Catalog/',norm) in filenames:
                continue
            if norm.endswith('/Analysis/Client/XNBHeaders.json') and member.file_size<16*1024*1024:
                # The older extractor only indexed some archive models, omitting
                # loose CommonData/Models/Ships assets entirely. Index them as
                # unverified candidates, not recovered geometry.
                root=path_meta(member.filename)[0]
                try:headers=json.loads(z.read(member))
                except (ValueError,OSError):headers=[]
                for obj in headers if isinstance(headers,list) else []:
                    if not isinstance(obj,dict):continue
                    source=str(obj.get('source') or '').replace('\\','/')
                    if '/Models/Ships/' not in source and '/models/ships/' not in source.lower():continue
                    if not source.lower().endswith('.xnb'):continue
                    rec={'ID':source.casefold(),'Name':Path(source).stem,
                         'RelativePath':source,'DecodeStatus':obj.get('status') or 'unclassified',
                         'Compression':'LZX' if obj.get('compressed_lzx') else 'LZ4' if obj.get('compressed_lz4') else 'None',
                         'ContentReaders':obj.get('reader_types') or [],
                         'GeometryStatus':'not decoded; no verified mesh extracted',
                         'Assessment':'Ship-model filename candidate only; not proof of game hitbox or vulnerability',
                         'SourceScan':norm}
                    if self.db.upsert_record('ModelAssetCandidates',root,rec,seen,norm):changed+=1
                    seen+=1
                self.db.conn.commit()
            
            if norm.endswith('/AI-Data/Asset_Inventory.jsonl') and member.file_size<=MAX_INDIVIDUAL_FILE:
                root=path_meta(member.filename)[0]
                with z.open(member) as f:
                    for line in f:
                        if b'Data/Models/' not in line:continue
                        try:obj=json.loads(line)
                        except ValueError:continue
                        if not isinstance(obj,dict):continue
                        name=str(obj.get('RelativePath') or '').replace('\\','/')
                        if not name.startswith('Data/Models/'):continue
                        obj['ID']=name
                        obj['Name']=Path(name).name
                        obj['ExtractionAssessment']='Asset candidate; not a verified 3D mesh or hitbox'
                        if self.db.upsert_record('ModelAssetCandidates',root,obj,seen,norm):changed+=1
                        seen+=1
                    self.db.conn.commit()
            elif '/CodeArchive/' in norm and norm.lower().endswith('.il.txt') and any(t in norm.rsplit('/',1)[-1].lower() for t in terms):
                if member.file_size>128*1024:continue
                try:body=z.read(member).decode('utf-8-sig',errors='replace')
                except (OSError,ValueError):continue
                root=path_meta(member.filename)[0]
                filename=norm.rsplit('/',1)[-1]
                mat=re.search(r'(0x[0-9a-fA-F]{8})_',filename)
                token=mat.group(1) if mat else filename
                stem=filename[:-7] if filename.lower().endswith('.il.txt') else filename
                category='ShipHitboxMethodEvidence' if any(t in stem.lower() for t in ('hitbox','shipmodel','ship_model','collisio')) else 'SailingAndMechanicsMethodEvidence'
                obj={'ID':stem,'Name':stem.split('_',1)[-1], 'Token':token,
                     'Source':norm,'Assembly':norm.split('/CodeArchive/',1)[-1].split('/')[0]+'.dll',
                     'IL':body,'EvidenceStatus':'Static client-code evidence; not verified server behavior'}
                if self.db.upsert_record(category,root,obj,seen,norm):changed+=1
                seen+=1
                if seen%100==0:self.db.conn.commit()
        self.db.conn.commit()
        if progress:progress('Imported '+str(seen)+' focused model/method evidence records')
        return changed

    def catalog_folder(self,folder,all_datasets=False,progress=None):
        folder=Path(folder)
        files=sorted(folder.rglob('*.jsonl'))
        processed=0;changed=0
        all_files={f.relative_to(folder).as_posix() for f in files}
        for f in files:
            relative=f.relative_to(folder).as_posix()
            if re.search(r'/Catalog-\d+/', '/'+relative) and re.sub(r'/Catalog-\d+/','/Catalog/','/'+relative).lstrip('/') in all_files:
                continue
            if 'AI-Data' not in f.parts:continue
            root,dataset=path_meta(f.relative_to(folder).as_posix())
            if not all_datasets and dataset in HEAVY:continue
            if f.stat().st_size>MAX_INDIVIDUAL_FILE:continue
            with f.open('r',encoding='utf-8-sig',errors='replace') as inp:
                for idx,line in enumerate(inp,1):
                    if len(line)>MAX_LINE_BYTES:continue
                    try:row=json.loads(line)
                    except ValueError:continue
                    if isinstance(row,dict):
                        if self.db.upsert_record(dataset,root,row,idx,str(f)):changed+=1
                        processed+=1
                        if processed%750==0:self.db.conn.commit()
            self.db.conn.commit()
            if progress:progress(f'{dataset}: {processed:,} records')
        # Folder imports should be equivalent to ZIP imports for combat and
        # ship-model evidence. Reports/Scan1-3 is the default Workbench layout.
        extra=self._import_research_folder(folder,progress)
        changed+=extra
        self.db.log_import(folder,'catalog-folder',changed)
        return {'records':processed,'changed':changed,'warnings':[]}

    def _import_research_folder(self,folder,progress=None):
        changed=0;seen=0
        for header_file in sorted(folder.rglob('XNBHeaders.json')):
            if header_file.parent.name!='Client':continue
            if header_file.stat().st_size>16*1024*1024:continue
            root=path_meta(header_file.relative_to(folder).as_posix())[0]
            try:rows=json.loads(header_file.read_text('utf-8-sig'))
            except (OSError,ValueError):continue
            for obj in rows if isinstance(rows,list) else []:
                if not isinstance(obj,dict):continue
                source=str(obj.get('source') or '').replace('\\','/')
                if '/models/ships/' not in source.lower() or not source.lower().endswith('.xnb'):continue
                record={'ID':source.casefold(),'Name':Path(source).stem,
                        'RelativePath':source,'DecodeStatus':obj.get('status') or 'unclassified',
                        'Compression':'LZX' if obj.get('compressed_lzx') else 'LZ4' if obj.get('compressed_lz4') else 'None',
                        'GeometryStatus':'not decoded; no verified mesh extracted',
                        'ContentReaders':obj.get('reader_types') or [],
                        'Assessment':'Filename candidate only; game hitbox or damage correlation unverified'}
                if self.db.upsert_record('ModelAssetCandidates',root,record,seen,str(header_file)):changed+=1
                seen+=1
            self.db.conn.commit()
        for methods in sorted(folder.rglob('Methods.csv')):
            if methods.parent.name!='Combat':continue
            if methods.stat().st_size>MAX_INDIVIDUAL_FILE:continue
            root=path_meta(methods.relative_to(folder).as_posix())[0]
            with methods.open('r',encoding='utf-8-sig',errors='replace') as f:
                for row in csv.DictReader(f):
                    if self.db.upsert_combat(root,row,str(methods)):changed+=1
            self.db.conn.commit()
        if progress:progress(f'Imported {seen} ship-model XNB file candidates and combat-method evidence')
        return changed

    def import_wiki(self,path):
        """Import a user-provided wiki export: Markdown/HTML files, a ZIP, or MediaWiki XML."""
        path=Path(path);files=[]
        if path.is_dir():
            for f in sorted(path.rglob('*')):
                if f.is_file() and f.suffix.lower() in ('.md','.markdown','.html','.htm','.xml'):
                    files.append((f.name,f.read_text(encoding='utf-8-sig',errors='replace')))
        elif path.suffix.lower()=='.zip':
            with zipfile.ZipFile(path) as z:
                if len(z.infolist())>MAX_ZIP_ITEMS:raise ValueError('Wiki ZIP has too many entries')
                for m in z.infolist():
                    if m.file_size<=8*1024*1024 and m.filename.lower().endswith(('.md','.markdown','.html','.htm','.xml')):
                        files.append((m.filename,z.read(m).decode('utf-8-sig',errors='replace')))
        else:files.append((path.name,path.read_text(encoding='utf-8-sig',errors='replace')))
        done=0
        for name,content in files:
            ext=Path(name).suffix.lower()
            if ext=='.xml':
                try:root=ET.fromstring(content)
                except ET.ParseError:continue
                for page in root.iter():
                    if page.tag.rsplit('}',1)[-1]!='page':continue
                    title=next((c.text or '' for c in page if c.tag.rsplit('}',1)[-1]=='title'),'')
                    text=next((c.text or '' for c in page.iter() if c.tag.rsplit('}',1)[-1]=='text'),'')
                    if title:
                        self.db.upsert_article('wiki-'+slugify(title),title,'Imported wiki',text,'wiki-xml',name,'needs-review')
                        done+=1
            elif ext in ('.md','.markdown','.html','.htm'):
                title=Path(name).stem.replace('_',' ').replace('-',' ').strip()
                match=re.search(r'^#\s+(.+)$',content,re.M) if ext in ('.md','.markdown') else None
                if match:title=match.group(1).strip()
                if ext in ('.html','.htm'):
                    p=_HTMLText();p.feed(content);content=p.text()
                self.db.upsert_article('wiki-'+slugify(title),title,'Imported wiki',content,'wiki-file',name,'needs-review')
                done+=1
        self.db.log_import(path,'wiki',done)
        return done
