"""Broad static-content exports. Definitions and source evidence, never live state."""
import csv,hashlib,html,json,re,shutil,struct
from pathlib import Path
from collections import Counter
from client_metadata import Metadata,StaticVM,plain
from dncil.clr.token import Token,StringToken
from xnb_images import unpack_xnb,Reader

TOPICS=re.compile(r'guild|portlevel|craft|factory|workshop|trading|auction|ship|cannon|powder|npc|whale|map|quest|loot|skill|bonus|resource|interestpoint|design|wind|weather|calendar|atlas|texture|image|icon|shipyard|gui|altar|fort|dig|mine|merc|crew|unit|mode|node|research|isle|arena|hunt|fishing|tournament|store|shop|chest|supply|village|city|collect',re.I)

def parse_number(s):
    try:
        v=float(s);return int(v) if v.is_integer() else v
    except (ValueError,TypeError):return s

def flatten(value,path='$'):
    if isinstance(value,dict):
        for k,v in value.items():yield from flatten(v,path+'.'+str(k))
    elif isinstance(value,list):
        for i,v in enumerate(value):yield from flatten(v,f'{path}[{i}]')
    else:yield path,value

def expand(x,preserve=False):
    """Called after normal extraction, or to expand an existing snapshot."""
    guild=[]
    for table in ('GuildBonuses','PortLevelBonuses'):
        for r in x.tables.get(table,[]):
            values=[v.strip() for v in str(r.get('LevelValues','')).split(',') if v.strip()]
            costs=[v.strip() for v in str(r.get('LevelPrices','')).split(',') if v.strip()]
            for i,v in enumerate(values,1):
                cost=costs[i-1] if i<=len(costs) else ''
                row={'System':table,'BenefitID':r.get('Type'),'EnglishName':r.get('EnglishName'),'EnglishDescription':r.get('EnglishDescription'),'Level':i,'Value':parse_number(v),'RawPrice':cost,'DurationDays':r.get('DurationDays'),'Receiver':r.get('Receiver'),'Source':r.get('Source'),'SourceRecord':r.get('SourceRecord')}
                for code,amount in re.findall(r'([A-Za-z]+)\s*(-?\d+(?:\.\d+)?)',cost):row['CostCode_'+code]=parse_number(amount)
                guild.append(row)
    x.save_table('Benefit_Levels',guild)
    objects=[];leaves=[];waves=[]
    for name,data in x.raw.items():
        for path,value in flatten(data):
            row={'Table':name,'JSONPath':path,'Value':value,'ValueType':type(value).__name__,'Source':f'_lzcommon.wosb/{name}.xnb'}
            if isinstance(value,str) and value in x.en:row['English']=x.en[value]
            leaves.append(row)
        if isinstance(data,list):
            for i,scene in enumerate(data,1):
                if not isinstance(scene,dict):continue
                for group in ('Isles','Objects','RemovedPositions'):
                    items=scene.get(group,[])
                    if not isinstance(items,list):continue
                    for j,item in enumerate(items,1):
                        raw=item.get('LocalPosition',item.get('Position')) if isinstance(item,dict) else item
                        coords=str(raw).replace(',',' ').split() if raw is not None else []
                        vals=[parse_number(z) for z in coords]
                        # Preserve exactly the source component order; no axis convention is assumed.
                        row={'SceneTable':name,'SceneRecord':i,'Group':group,'ObjectIndex':j,'SceneName':x.en.get(scene.get('MapName'),scene.get('MapName','')),'RawPosition':raw,'Position0':vals[0] if vals else None,'Position1':vals[1] if len(vals)>1 else None,'Position2':vals[2] if len(vals)>2 else None,'Source':f'_lzcommon.wosb/{name}.xnb'}
                        if isinstance(item,dict):row.update({k:v for k,v in item.items() if k not in ('LocalPosition','Position')})
                        objects.append(row)
                for wi,wave in enumerate(scene.get('Waves',[]),1):
                    for ni,npc in enumerate(wave.get('NPCS',[]),1):waves.append({'MapKey':scene.get('MapName'),'EnglishMapName':x.en.get(scene.get('MapName'),''),'Wave':wi,'Entry':ni,**npc,'Source':f'_lzcommon.wosb/{name}.xnb'})
    x.save_table('All_Data_Fields',leaves)
    x.save_table('Explicit_Chance_Fields',[{**r,'Interpretation':'Explicit chance/probability field; source system and units must be retained'} for r in leaves if re.search(r'probability|chance|drop.?rate',r['JSONPath'],re.I)])
    x.save_table('Map_Objects',objects)
    x.save_table('NPC_Mission_Waves',waves)
    x.save_table('Marker_Definitions',x.tables.get('InterestPoints',[]))
    # All exact source image matches remain preserved; this is a convenience grouping.
    ui=[]
    patterns={'Shipyard':r'shipyard|craftship|shipicon|shipway','Map':r'map|marker|world|interestpoint','Guild':r'guild|portbonus','Trading':r'trad|auction|workshop|craft|factory|cannonball'}
    for im in x.image_rows:
        for group,pattern in patterns.items():
            if re.search(pattern,im['Source'],re.I):ui.append({'Group':group,'ImageID':im['ImageID'],'PNGPath':im['PNGPath'],'Source':im['Source'],'Relationship':'Filename/atlas-name grouping; not an exact screen layout'})
    x.save_table('UI_Image_Groups',ui)
    system_views(x,objects)
    production_and_whales(x)
    from recipe_chains import export_chains
    export_chains(x)
    metadata_exports(x)
    scan_assets(x,preserve)
    write_map(x,objects)
    notes=[
        {'Topic':'Extraction scope','Detail':'English text; all decoded shared-table fields; images and variants; guild/port levels; map objects; NPC wave definitions; selected game-code schemas, constants and source evidence. Live values are not inferred.'},
        {'Topic':'Benefits','Detail':'Benefit_Levels has one row per defined level. CostCode_g and CostCode_c preserve client price-code letters; their currency meanings are not invented.'},
        {'Topic':'Shipyard','Detail':'Client references shipyard_background and atlas components such as craftShip_infoBlockFrame and craftShip_shipIconMask. Pieces are preserved separately. The final screen also contains runtime text, masks and layout; an exact screen composite has not been reconstructed.'},
        {'Topic':'Map','Detail':'Map_Objects preserves source positions and model paths. Map-Object-Overview.html is a searchable coordinate plot of placed scene objects, not a full textured render of the game world.'},
        {'Topic':'NPCs and whales','Detail':'NPC_Mission_Waves contains decoded mission wave entries. Gameplay_Code_Constants and Game_Schemas preserve further NPC/whale evidence. Code literals are not automatically labeled as NPC stats; active spawns and runtime state are not available offline.'},
        {'Topic':'Undecoded assets','Detail':'Asset_Inventory identifies containers and models. With --preserve-assets, original game asset bytes are copied to RawAssets so unsupported formats are not discarded. Other-language .lang files are excluded.'},
        {'Topic':'Missing ship costs','Detail':'Model metadata and printable model strings are exported for follow-up parsing. Ship gun ports are not yet semantically decoded; unresolved quantities remain blank.'},
    ]
    x.save_table('Archive_Coverage',notes)
    (x.out/'EXPANDED-CATALOG.txt').write_text('WOSB broad static archive v0.2\n\n'+ '\n\n'.join(r['Topic']+': '+r['Detail'] for r in notes),encoding='utf-8')

def metadata_exports(x):
    schemas=[];enums=[];literals=[];methods=[];refs=[]
    candidates=[x.game/'Libs/Common.dll',x.game/'Libs/WorldOfSeaBattles.dll',x.game/'Libs/TheraEngine.dll']
    if not candidates[0].exists():candidates=[x.game/'Common.dll',x.game/'WorldOfSeaBattles.dll',x.game/'TheraEngine.dll']
    for src in candidates:
        if not src.exists():continue
        m=x.common if src.name=='Common.dll' else Metadata(src)
        parent={}
        for t in m.pe.net.mdtables.TypeDef.rows:
            owner=str(t.TypeNamespace)+'.'+str(t.TypeName)
            include=owner.startswith('CommonDataTypes.') or (owner.startswith(('Common.Resources.','Common.Game.')) and TOPICS.search(owner))
            if not include:continue
            for field in t.FieldList:
                schemas.append({'Assembly':src.name,'Type':owner,'Field':str(field.row.Name),'FieldToken':f'0x{0x04000000+field.row_index:08x}','SignatureHex':field.row.Signature.value.hex(),'Status':'Schema only; not a runtime value'})
                parent[field.row_index]=owner
        for c in m.pe.net.mdtables.Constant.rows:
            if c.Parent.table.name!='Field' or c.Parent.row_index not in parent:continue
            b=c.Value.value;typ=c.Type
            fmts={2:'?',3:'H',4:'b',5:'B',6:'h',7:'H',8:'i',9:'I',10:'q',11:'Q',12:'f',13:'d'}
            try:value=struct.unpack('<'+fmts[typ],b)[0] if typ in fmts else (b.decode('utf-16-le') if typ==14 else b.hex())
            except (ValueError,struct.error):value=b.hex()
            enums.append({'Assembly':src.name,'Type':parent[c.Parent.row_index],'Member':str(c.Parent.row.Name),'Value':value,'Status':'Literal metadata constant / enum member'})
        for rid,row in enumerate(m.pe.net.mdtables.MethodDef.rows,1):
            owner=m.owners.get(id(row),'');name=str(row.Name)
            if not row.Rva:continue
            eligible=bool(TOPICS.search(owner)) and owner.startswith(('Common.Game.','Common.Resources.','World_Of_Sea_Battle.Components.'))
            if not eligible and not (src.name=='Common.dll' and (owner.startswith('A.') or owner.startswith('.'))):continue
            try:ii=m.body(rid)
            except Exception as e:x.warn('Metadata method',owner+'::'+name,e);continue
            if not eligible:
                # Retain obfuscated helpers that instantiate known NPC definitions.
                for ins in ii:
                    if ins.opcode.name=='newobj':
                        target=m.method(ins.operand)[0]
                        if target in ('Common.Resources.NpcGenerator','Common.Resources.NpcInfo','Common.Game.WhaleController'):
                            eligible=True;break
                if not eligible:continue
            token=f'0x{0x06000000+rid:08x}'
            filename=src.stem+'/'+token+'_'+re.sub(r'[^A-Za-z0-9_.-]','_',owner+'_'+name)[:100]+'.il.txt'
            dest=x.out/'CodeArchive'/filename;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(m.evidence(rid),encoding='utf-8')
            methods.append({'Assembly':src.name,'Type':owner,'Method':name,'MethodToken':token,'Instructions':len(ii),'EvidenceFile':str(Path('CodeArchive')/filename),'Status':'Source evidence; not an evaluated formula'})
            for index,i in enumerate(ii):
                a=i.operand;value=None;kind=None
                if i.opcode.name.startswith('ldc.'):
                    value=m.const(i);kind='Numeric IL literal'
                elif isinstance(a,StringToken):value=m.pe.net.user_strings.get(a.rid).value;kind='String IL literal'
                elif isinstance(a,Token) and a.value in m.strings:value=m.strings[a.value];kind='Decoded string literal'
                if kind:
                    context='; '.join(z.opcode.name+' '+str(z.operand or '') for z in ii[max(0,index-2):index+4])
                    literals.append({'Assembly':src.name,'Type':owner,'Method':name,'MethodToken':token,'ILOffset':i.offset,'Kind':kind,'Value':value,'English':x.en.get(str(value),''),'InstructionContext':context,'Interpretation':'Raw code literal; role must be verified from source'})
                    if isinstance(value,str) and re.search(r'\\|/|\.xnb|shipyard|\.png|\.atlas',value,re.I):refs.append({'Assembly':src.name,'Type':owner,'Method':name,'MethodToken':token,'Reference':value,'Interpretation':'Literal path/name fragment; may be concatenated at runtime'})
    x.save_table('NPC_Types',[r for r in enums if re.search(r'NpcType|NpcEducationMap|NpcVisualEffect',r['Type'])]);x.save_table('Game_Schemas',schemas);x.save_table('Game_Enums',enums);x.save_table('Gameplay_Methods',methods);x.save_table('Gameplay_Code_Constants',literals);x.save_table('Code_Asset_References',refs)

def scan_assets(x,preserve):
    index=[];modelstrings=[];seen=set()
    roots=[x.game/'Data',x.game/'CommonData']
    if not any(p.exists() for p in roots):roots=[x.game]
    for root in roots:
        if not root.exists():continue
        for src in sorted(root.rglob('*')):
            if not src.is_file() or src.is_symlink():continue
            rel=src.relative_to(x.game)
            if rel.as_posix() in seen:continue
            seen.add(rel.as_posix())
            if src.suffix.lower()=='.lang' and src.name!='en-US.lang':continue
            if src.suffix.lower() in ('.log','.bak','.pem','.cer') or src.name=='_lzcommon.wosb':continue
            if root==x.game and src.suffix.lower() not in ('.xnb','.json','.lang','.bin','.dat'):continue
            b=src.read_bytes();row={'RelativePath':rel.as_posix(),'Bytes':len(b),'Extension':src.suffix.lower(),'SHA256':hashlib.sha256(b).hexdigest(),'PreservedPath':''}
            if preserve:
                dest=Path('RawAssets/LooseFiles')/rel;(x.out/dest).parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,x.out/dest);row['PreservedPath']=dest.as_posix()
            if b.startswith((b'XNB',b'WOSBXNB')):
                try:
                    payload=unpack_xnb(b);r=Reader(payload);readers=[]
                    for _ in range(r.seven()):readers.append(r.string());r.i32()
                    row['ContentReaders']=readers;row['DecodedPayloadBytes']=len(payload)
                    if any('Model' in q for q in readers):
                        # These are candidate model strings, not claimed bone or gun-port counts.
                        for found in re.findall(rb'[A-Za-z_][A-Za-z0-9_./\\ -]{3,120}',payload):
                            s=found.decode('ascii')
                            if any(c.isalpha() for c in s):modelstrings.append({'ModelPath':rel.as_posix(),'Text':s,'Interpretation':'Printable model payload string; not yet semantically parsed'})
                    if x.images and any('Texture2DReader' in q for q in readers) and not any(z['Source']==rel.as_posix() for z in x.image_rows):
                        x.add_image(b,rel.as_posix(),Path('LooseFiles')/rel)
                except Exception as e:row['DecodeStatus']=str(e)
            index.append(row)
            if len(index)%100==0:print(f'  Content assets examined: {len(index)}',flush=True)
    x.save_table('Asset_Inventory',index);x.save_table('Model_String_Candidates',modelstrings)

def write_map(x,objects):
    points=[r for r in objects if r['SceneTable']=='World_j' and r['Group']=='Isles' and isinstance(r.get('Position0'),(int,float)) and isinstance(r.get('Position1'),(int,float))]
    if not points:return
    data=[{'i':r['ObjectIndex'],'x':r['Position0'],'y':r['Position1'],'path':r.get('Path',''),'parameters':r.get('Parameters','')} for r in points]
    js=json.dumps(data).replace('<','\\u003c')
    doc='''<!doctype html><html lang="en"><meta charset="utf-8"><title>WOSB map objects</title><style>body{background:#102333;color:#e5eff7;font:15px system-ui;margin:20px}input{padding:10px;width:500px}canvas{background:#17354a;width:100%;max-width:1400px;touch-action:none}#info{white-space:pre-wrap}</style><h1>World map placed objects</h1><p>Source-coordinate overview. This shows placed objects, not coastline geometry or a textured game map. Horizontal: position component 0; vertical: component 1, increasing upward.</p><input id="q" placeholder="Filter paths: ports, factory, rocks, etc."><p id="count"></p><canvas id="map" width="1600" height="1300"></canvas><p id="info">Hover over a point for its source data.</p><script>const data=DATA,c=document.getElementById('map'),ctx=c.getContext('2d'),q=document.getElementById('q');const xs=data.map(p=>p.x),ys=data.map(p=>p.y),bounds=[Math.min(...xs),Math.max(...xs),Math.min(...ys),Math.max(...ys)];const pxy=p=>[35+(p.x-bounds[0])/(bounds[1]-bounds[0])*1530,1265-(p.y-bounds[2])/(bounds[3]-bounds[2])*1230];let current=data;function draw(){current=data.filter(p=>(p.path+' '+p.parameters).toLowerCase().includes(q.value.toLowerCase()));ctx.clearRect(0,0,c.width,c.height);for(const p of current){const [x,y]=pxy(p);ctx.fillStyle=p.path.toLowerCase().includes('port')?'#ffd589':'#8ad3b6';ctx.beginPath();ctx.arc(x,y,p.path.toLowerCase().includes('port')?4:1.5,0,Math.PI*2);ctx.fill()}document.getElementById('count').textContent=current.length+' of '+data.length+' placed objects'}q.oninput=draw;c.onmousemove=e=>{const b=c.getBoundingClientRect(),mx=(e.clientX-b.left)*c.width/b.width,my=(e.clientY-b.top)*c.height/b.height;let best=null,d=100;for(const p of current){const [x,y]=pxy(p),dd=(x-mx)**2+(y-my)**2;if(dd<d){d=dd;best=p}}if(best)document.getElementById('info').textContent=JSON.stringify(best,null,2)};draw();</script></html>'''
    (x.out/'Map-Object-Overview.html').write_text(doc.replace('DATA',js),encoding='utf-8')


def production_and_whales(x):
    if not getattr(x,'known',False):return
    v=StaticVM(x.common);old=v.invoke;v.allowed={0x2372,0x2303}
    resources=x.raw.get('Resources_j',[])
    costs={i:r.get('MediumCost',0) for i,r in enumerate(resources,1)}
    labels={i:x.en.get(r['ID']+'_name',r['ID']) for i,r in enumerate(resources,1)}
    v.fields[0x04000c11]={'_type':'ItemSet'}
    def invoke(tok,args,construct=False):
        owner,name,row=x.common.method(tok)
        if owner=='System.Collections.Generic.Dictionary`2':
            if name=='.ctor':return {'_type':'Dictionary','data':{}}
            if name=='set_Item':args[0]['data'][args[1]]=args[2];return None
        if name=='FromID' and isinstance(args[0],dict) and args[0].get('_type')=='ItemSet':return {'MediumCost':costs[args[1]]}
        if owner=='Common.Game.FactoryGameInfo' and name=='.ctor':return {'FactoryTypeID':args[0],'Levels':args[1]}
        if owner=='Common.Game.FactoryMineLivelInfo' and name=='.ctor':return {'Consume':args[0]['items'],'Produce':args[1]['items'],'HoldCapacityBasic':args[2]}
        return old(tok,args,construct)
    v.invoke=invoke
    try:
        v.run(0x236f)
        result=v.fields[0x04000d07]['data'];rows=[]
        # The factory enum is needed for the exact English localization key.
        enum={}
        for t in x.common.pe.net.mdtables.TypeDef.rows:
            if str(t.TypeName)=='FactoryType':
                ids={f.row_index:str(f.row.Name) for f in t.FieldList}
                for c in x.common.pe.net.mdtables.Constant.rows:
                    if c.Parent.table.name=='Field' and c.Parent.row_index in ids:enum[int.from_bytes(c.Value.value,'little',signed=True)]=ids[c.Parent.row_index]
        for fid,factory in result.items():
            key='Fc'+enum.get(fid,str(fid))
            for level,definition in enumerate(factory['Levels'],1):
                rows.append({'FactoryTypeID':fid,'FactoryType':enum.get(fid),'EnglishName':x.en.get(key,''),'Level':level,'ConsumeItems':definition['Consume'],'ConsumeEnglish':{labels.get(k,str(k)):n for k,n in definition['Consume'].items()},'ProduceItems':definition['Produce'],'ProduceEnglish':{labels.get(k,str(k)):n for k,n in definition['Produce'].items()},'BaseHoldCapacity':definition['HoldCapacityBasic'],'TimingStatus':'Amounts per client production operation; real-time rate and player modifiers are separate','Source':'Common.dll: WosbCrafting 0x0600236f; FactoryMineLivelInfo::.ctor'})
        x.save_table('Factory_Levels',rows)
    except Exception as e:x.warn('Factory definitions','Common.dll',e)
    whale=[]
    for subtype,key,low,high in [(2,'whale_3',None,300),(1,'whale_2',300,500),(0,'whale_1',500,2000),(3,None,2000,None)]:
        whale.append({'SubtypeID':subtype,'EnglishName':x.en.get(key,'???') if key else '??? (client fallback label)','HealthLowerExclusive':low,'HealthUpperInclusive':high,'Rule':'Subtype selected from maximum health; this is a classification range, not a fixed spawn-health definition','HealthSource':'DropBonusInfo.Server_WhaleHealth (runtime/server field)','VisualScaleFormula':'0.8 * (maximumHealth / 100)^0.4','Source':'Common.dll: WhaleController.get_Subtype, get_Scale and .ctor'})
    x.save_table('Whale_Rules',whale)


def system_views(x,objects):
    units=x.tables.get('UnitsInfo',[])
    for typ,tab in [('Sailor','Crew_Sailors'),('Boarding','Crew_Boarding'),('Special','Crew_Special')]:
        x.save_table(tab,[r for r in units if r.get('Type')==typ])
    modes=[]
    for table in ['MapsForPassing','MapsArena']:
        for r in x.tables.get(table,[]):modes.append({'DefinitionSet':table,**r})
    x.save_table('Mode_Definitions',modes)
    patterns={'Forts':r'fort|tower|pbs','Mines_and_Nodes':r'mine|factory|quarry|resource|woodcut|lumber|ore|farm','Dig_Sites':r'dig|excavat|treasur|shipwreck','Altar':r'altar','Fishing_Villages':r'fishingvil|fishing_village','Other_Villages':r'village|vil[0-9]'}
    for topic,pattern in patterns.items():
        rows=[]
        for r in objects:
            if re.search(pattern,str(r.get('Path',''))+' '+str(r.get('Parameters','')),re.I):
                rows.append({'Category':topic,'IdentificationStatus':'Source-path/parameter match; exact game role may need model/code interpretation',**r})
        x.save_table(topic+'_Map_References',rows)
    labels=[]
    for key,value in x.en.items():
        for topic,pattern in {**patterns,'Ports':r'port|harbor|harbour','Crew':r'crew|sailor|mercan|mercen|boarding|unit_','Modes':r'arena|passing|mode|mission','Workshop':r'craft|workshop|factory','Collectable_Missions':r'collect|figurine|longhorn|shipwreck|research','Arena_Store':r'arena.*(shop|store|offer)|arenaoffer','Arena_Tournament_Hunt':r'arena|tournament|hunt','Chests_and_Drops':r'chest|drop|loot','Cities_and_Supply':r'city|supply|suppl|portlevel|deficit','Villages':r'village|fishing|settlement','Store':r'shop|store|offer|purchase'}.items():
            if re.search(pattern,key,re.I):labels.append({'System':topic,'Key':key,'English':value,'Interpretation':'Exact English client text; placeholders remain unresolved'})
    x.save_table('System_English_Text',labels)
    x.save_table('Port_Definitions',x.tables.get('WorldPorts',[]))
    x.save_table('Chest_Item_Definitions',[r for r in x.tables.get('Resources',[]) if re.search(r'chest',str(r.get('EnglishName',''))+' '+str(r.get('ID','')),re.I)])
    x.save_table('Collectable_Definitions',x.tables.get('InterestPoints',[]))



def write_ai_handoff(x):
    from zipfile import ZipFile,ZIP_DEFLATED
    folder=x.out/'AI-Data';folder.mkdir(exist_ok=True);manifest=[]
    for table,rows in x.tables.items():
        if not rows:continue
        chunks=[];part=[];size=0
        for row in rows:
            line=json.dumps(plain(row),ensure_ascii=False,separators=(',',':'))+'\n';n=len(line.encode('utf-8'))
            if part and size+n>4*1024*1024:chunks.append(part);part=[];size=0
            part.append(line);size+=n
        if part:chunks.append(part)
        paths=[]
        for i,lines in enumerate(chunks,1):
            name=table+(f'.part{i:03d}' if len(chunks)>1 else '')+'.jsonl'
            (folder/name).write_text(''.join(lines),encoding='utf-8');paths.append('AI-Data/'+name)
        manifest.append({'Table':table,'Rows':len(rows),'Files':paths,'Fields':list(dict.fromkeys(k for row in rows for k in row)),'CSV':'Spreadsheets/'+table+'.csv'})
    from recipe_chains import build_plan
    bulk=next((i for i,r in enumerate(x.tables.get('Resources',[]),1) if r.get('EnglishName')=='Bulkhead'),None)
    if bulk is not None:
        (x.out/'Bulkhead-Example.json').write_text(json.dumps({'WholeBatchPlan':build_plan(x.tables,bulk,getattr(x,'craft_quantity',1),'Workshop',True),'ProportionalPlan':build_plan(x.tables,bulk,getattr(x,'craft_quantity',1),'Workshop',False)},ensure_ascii=False,indent=2),encoding='utf-8')
    guide_path=Path(__file__).parent/'AI-Handoff-Guide.md'
    guide=(guide_path.read_text(encoding='utf-8') if guide_path.is_file() else
           '# WoSB AI handoff\n\nRead AI-MANIFEST.json and AI-Data/*.jsonl. Preserve source provenance.\n'
           'Missing client data must never be interpreted as proof a mechanic does not exist.\n')
    (x.out/'START-HERE-FOR-AI.md').write_text(guide,encoding='utf-8')
    (x.out/'AI-MANIFEST.json').write_text(json.dumps({'Format':'WOSB static client AI handoff','Version':'0.2','Language':'English','Tables':manifest,'ImagesDirectory':'Images','SourceEvidence':'CodeArchive','KnownLimitations':'START-HERE-FOR-AI.md','NotIncluded':['RawAssets binary originals','databases','Excel workbooks','game executable DLLs','audio/video']},ensure_ascii=False,indent=2),encoding='utf-8')
    zip_path=x.out/'WOSB-AI-Handoff.zip'
    allowed={'AI-Data','RawData','Spreadsheets','Images','CodeArchive','CodeEvidence'}
    files={'START-HERE-FOR-AI.md','AI-MANIFEST.json','Extraction-Summary.json','EXPANDED-CATALOG.txt','Gallery.html','Map-Object-Overview.html','Bulkhead-Example.json'}
    with ZipFile(zip_path,'w',ZIP_DEFLATED) as z:
        for path in sorted(x.out.rglob('*')):
            if not path.is_file():continue
            rel=path.relative_to(x.out)
            if rel.parts[0] in allowed or rel.as_posix() in files:z.write(path,'WOSB-AI-Handoff/'+rel.as_posix())
    return zip_path
