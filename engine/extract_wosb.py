#!/usr/bin/env python3
"""Read-only World of Sea Battle catalog export. English only."""
import argparse,csv,hashlib,html,json,math,os,re,sys,traceback
from collections import defaultdict
from datetime import datetime
from pathlib import Path,PurePosixPath
import pyzipper
from client_metadata import Metadata,StaticVM,Unknown,U,plain
from xnb_images import texture

KNOWN_COMMON='3fbe9d5a8199be8e95c449d4f4a981221c823cec70381c709d57c165888fca82'

def digest(b):return hashlib.sha256(b).hexdigest()
def safe_name(s):return re.sub(r'[^A-Za-z0-9_.-]+','_',str(s)).strip(' .') or 'unnamed'
def safe_relative(s):
    p=PurePosixPath(s.replace('\\','/'))
    if p.is_absolute() or any(x in ('..','') or ':' in x for x in p.parts):raise ValueError('Unsafe archive path')
    return Path(*[safe_name(x) for x in p.parts])
def scalar(v):
    if isinstance(v,(dict,list)):return json.dumps(plain(v),ensure_ascii=False,separators=(',',':'))
    return plain(v)
def spreadsheet_text(v):
    v=scalar(v)
    # Prevent game text from becoming an Excel formula when opening CSV files.
    if isinstance(v,str) and v.lstrip().startswith(('=','+','-','@','\t','\r')):return "'"+v
    return v

def write_csv(path,rows,columns=None):
    path.parent.mkdir(parents=True,exist_ok=True)
    columns=columns or list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=columns,extrasaction='ignore');w.writeheader()
        for row in rows:w.writerow({k:spreadsheet_text(row.get(k)) for k in columns})

def english_file(p):
    text=p.read_text(encoding='utf-8-sig');entries=[];mapping={}
    for num,line in enumerate(text.splitlines(),1):
        if not line.strip():continue
        parts=line.split(None,1)
        if len(parts)!=2:continue
        key,value=parts
        entries.append({'Key':key,'English':value,'SourceLine':num})
        mapping[key]=value
    return entries,mapping

def market_bounds(cost,kind='resource',rid=0):
    import struct
    f=lambda v:struct.unpack('<f',struct.pack('<f',v))[0]
    cost=f(cost)
    if kind=='resource':
        lo,hi=(1,30) if rid in (37,38,15,33,40,43,5,8,69,67) else ((f(.666),15) if rid==70 else ((1,40) if rid==23 else (f(.666),4)))
    elif kind=='ammunition':lo,hi=f(.666),8
    elif kind=='cannon':lo,hi=.75,8
    else:lo,hi=.75,4
    return max(1,math.floor(f(cost*lo))),math.ceil(f(cost*hi))

class Extractor:
    def __init__(self,game,out,images=True,all_textures=False,broad=False,preserve_assets=False):
        self.game=game;self.out=out;self.images=images;self.all_textures=all_textures;self.broad=broad;self.preserve_assets=preserve_assets
        self.tables={};self.errors=[];self.image_rows=[];self.links=[];self.source_rows=[];self.image_by_stem=defaultdict(list);self.entity_rows=[]
        self.out.mkdir(parents=True,exist_ok=False)
    def warn(self,stage,source,error):
        self.errors.append({'Stage':stage,'Source':str(source),'Detail':str(error)})
    def save_table(self,name,rows):
        self.tables[name]=rows;write_csv(self.out/'Spreadsheets'/(name+'.csv'),rows,['Stage','Source','Detail'] if name=='Extraction_Issues' else None)
    def add_image(self,b,source,rel,kind='texture'):
        try:
            im,info=texture(b)
            rel=Path('Images')/rel.with_suffix('.png');dest=self.out/rel;dest.parent.mkdir(parents=True,exist_ok=True)
            if dest.exists():raise ValueError('Output name collision: '+str(rel))
            im.save(dest)
            row={'ImageID':f'IMG{len(self.image_rows)+1:06d}','Source':source,'PNGPath':rel.as_posix(),'Variant':Path(source).stem,'Kind':kind,'SourceSHA256':digest(b),'PixelSHA256':digest(im.tobytes()),**info}
            self.image_rows.append(row)
            if len(self.image_rows)%100==0:print(f'  Images decoded: {len(self.image_rows)}',flush=True)
            self.image_by_stem[Path(source.replace('\\','/')).stem.lower()].append(row)
            return im,row
        except Exception as e:self.warn('Image decode',source,e);return None,None
    def link(self,category,key,candidates,relation='Exact client reference'):
        for stem in candidates:
            for im in self.image_by_stem.get(stem.lower(),[]):
                self.links.append({'Category':category,'EntityID':key,'ImageID':im['ImageID'],'PNGPath':im['PNGPath'],'Relationship':relation})
    def extract(self):
        lang=self.game/'CommonData/Localization/en-US.lang'
        if not lang.exists():lang=self.game/'en-US.lang'
        self.english_rows,self.en=english_file(lang)
        self.save_table('English_Text',self.english_rows)
        meta_path=self.game/'Libs/Common.dll'
        if not meta_path.exists():meta_path=self.game/'Common.dll'
        engine_path=self.game/'Libs/TheraEngine.dll'
        if not engine_path.exists():engine_path=self.game/'TheraEngine.dll'
        engine=Metadata(engine_path);password=engine.archive_password()
        archive=self.game/'CommonData/_lzcommon.wosb'
        if not archive.exists():archive=self.game/'_lzcommon.wosb'
        self.common=Metadata(meta_path);self.common_hash=digest(meta_path.read_bytes());self.known=self.common_hash==KNOWN_COMMON
        self.raw={};archive_rows=[]
        print('Reading shared archive...',flush=True)
        with pyzipper.AESZipFile(archive) as z:
            z.setpassword(password)
            for idx,info in enumerate(z.infolist()):
                if info.is_dir():continue
                rel=safe_relative(info.filename);b=z.read(info.filename)
                if self.preserve_assets:
                    dest=self.out/'RawAssets/SharedArchive'/rel;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(b)
                archive_rows.append({'ArchivePath':info.filename,'Bytes':len(b),'SHA256':digest(b)})
                if len(rel.parts)==1:
                    try:
                        data=json.loads(b.decode('utf-8-sig'))
                        self.raw[rel.stem]=data
                        dest=self.out/'RawData'/rel.with_suffix('.json');dest.parent.mkdir(parents=True,exist_ok=True)
                        dest.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
                    except (UnicodeDecodeError,json.JSONDecodeError):pass
                if self.images and b.startswith((b'XNB',b'WOSBXNB')):
                    # Archive contains image assets plus map masks; all decodable textures are retained.
                    self.add_image(b,'_lzcommon.wosb/'+info.filename,Path('SharedArchive')/rel)
                if idx%100==0:print(f'  Archive entries: {idx+1}/{len(z.infolist())}',flush=True)
        self.save_table('Archive_Index',archive_rows)
        print('Reading loose textures and atlases...',flush=True)
        if self.images:self.loose_images()
        print('Building English catalog...',flush=True)
        self.resources=self.raw.get('Resources_j',[])
        self.resource_names={i:self.en.get(str(r.get('ID'))+'_name',str(r.get('ID'))) for i,r in enumerate(self.resources,1)}
        self.resource_names[255]=self.en.get('gold','Gold')
        for name,data in self.raw.items():
            if not isinstance(data,list):data=[data]
            rows=[]
            for idx,item in enumerate(data,1):
                row={'SourceRecord':idx,'Source':'_lzcommon.wosb/'+name+'.xnb'}
                if not isinstance(item,dict):item={'Value':item}
                for k,v in item.items():
                    row[k]=v
                    if isinstance(v,str) and v in self.en:row[k+'English']=self.en[v]
                identity=str(item.get('ID',item.get('Name',item.get('MapName',idx))))
                namekey=str(item.get('Name',item.get('PortName',item.get('Type',identity))))
                if namekey in self.en:english=self.en[namekey]
                else:english=self.en.get(namekey+'_name','')
                basekey=namekey.removesuffix('_name')
                desc=next((self.en[basekey+suffix] for suffix in ('_desc','_desc1','_description','_text','_tt') if basekey+suffix in self.en),'')
                if name=='ShipsToPlay_j':
                    identity=str(item['ID']);english=self.en.get('ship_'+identity+'_name','');desc=self.en.get('ship_'+identity+'_desc','')
                    row['ShipRank']=item.get('Rank',0)+1
                    row['BaseCrewPlaces']=int(round(item.get('PlacesForUnitsCount',0)*4))
                    row['InternalBaseSpeed']=item.get('BasicSpeed',0)*2
                    row['ConstructionDataStatus']='See Ship_Construction; some costs depend on model gun ports'
                row={'EnglishName':english,'EnglishDescription':desc,**row}
                rows.append(row)
                if english:self.entity_rows.append({'Category':name.removesuffix('_j'),'EntityID':identity,'EnglishName':english,'EnglishDescription':desc,'Source':row['Source'],'SourceRecord':idx})
                stems=[str(item[k]) for k in ('IconName','Icon','IconTexture','IconTextureName') if item.get(k)]
                self.link(name.removesuffix('_j'),identity,stems)
                if name=='ShipsToPlay_j':
                    sid=item['StaticInfoID'];prefix='shipicon'+str(sid)
                    variants=[stem for stem in self.image_by_stem if re.match(re.escape(prefix)+r'($|[^0-9])',stem)]
                    self.link('ShipsToPlay',identity,variants,'Client StaticInfoID mapped to shipIcon<StaticInfoID>; suffix is preserved')
                elif stems:
                    for stem in stems:
                        variants=[s for s in self.image_by_stem if s.startswith(stem.lower()+'_')]
                        self.link(name.removesuffix('_j'),identity,variants,'Filename variant candidate; confirm appearance')
            self.save_table(safe_name(name.removesuffix('_j')),rows)
        self.save_table('Named_Entities',self.entity_rows)
        named=[]
        for key,value in self.en.items():
            if key.endswith('_name'):
                base=key[:-5];named.append({'Key':base,'EnglishName':value,'EnglishDescription':self.en.get(base+'_desc',''),'CategoryPrefix':base.split('_')[0],'Source':'en-US.lang'})
        self.save_table('English_Names',named)
        if self.known:self.derived()
        else:self.warn('Build support','Common.dll','Unrecognized DLL hash: code-derived costs and recipes omitted. Raw JSON, text and images still exported.')
        if self.broad:
            from expand_catalog import expand
            print('Expanding benefits, map objects, schemas and source evidence...',flush=True)
            expand(self,self.preserve_assets)
        self.save_table('Images',self.image_rows)
        self.save_table('Entity_Images',self.links)
        self.save_table('Extraction_Issues',self.errors)
        if getattr(self,'combat',False):
            from combat_research import analyze
            print('Analyzing combat evidence (read-only)...',flush=True)
            try:analyze(self.game,self.out,max_methods=getattr(self,'combat_max_methods',1000))
            except Exception as exc:self.warn('Combat analysis','Combat',str(exc))
        self.write_readme()
        self.write_gallery()
        (self.out/'catalog.json').write_text(json.dumps(plain(self.tables),ensure_ascii=False,indent=2),encoding='utf-8')
        manifest={'GameDirectory':str(self.game),'CommonSHA256':self.common_hash,'KnownCodeBuild':self.known,'Created':datetime.now().astimezone().isoformat(),'Tables':{k:len(v) for k,v in self.tables.items()},'ImageFiles':len(self.image_rows),'ImageLinks':len(self.links),'IssueCount':len(self.errors)}
        (self.out/'Extraction-Summary.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
        if self.broad:
            from expand_catalog import write_ai_handoff
            print('Packaging AI handoff ZIP...',flush=True)
            write_ai_handoff(self)
            from zipfile import ZipFile,ZIP_DEFLATED
            with ZipFile(self.out/'Review-Report.zip','w',ZIP_DEFLATED) as report:
                for rel in ('Extraction-Summary.json','Spreadsheets/Extraction_Issues.csv','Spreadsheets/Asset_Inventory.csv','Spreadsheets/Model_String_Candidates.csv','Spreadsheets/Archive_Coverage.csv'):
                    if (self.out/rel).is_file():report.write(self.out/rel,rel)
        print(f'Finished: {self.out}\nImages: {len(self.image_rows)}; image links: {len(self.links)}; issues: {len(self.errors)}',flush=True)
        return manifest
    def loose_images(self):
        from PIL import Image
        roots=[self.game/'Data/Textures',self.game/'CommonData/Textures']
        # The sample ZIP puts the selected atlas and Icons at its root.
        if not any(p.exists() for p in roots):roots=[self.game]
        for root in roots:
            for src in sorted(root.rglob('*')):
                if not src.is_file() or src.is_symlink():continue
                rel=src.relative_to(self.game)
                if src.suffix.lower()=='.xnb':
                    im,row=self.add_image(src.read_bytes(),rel.as_posix(),Path('LooseFiles')/rel)
                    atlas=src.with_suffix('.atlas.json')
                    if im is not None and atlas.exists():self.cut_atlas(im,atlas,row)
                elif src.suffix.lower() in ('.png','.jpg','.jpeg','.bmp','.tga','.dds'):
                    try:
                        im=Image.open(src).convert('RGBA');dest=Path('Images/LooseFiles')/rel.with_suffix('.png')
                        # Keep the source extension in case PNG and DDS share a basename.
                        dest=dest.with_name(rel.name+'.png');(self.out/dest).parent.mkdir(parents=True,exist_ok=True);im.save(self.out/dest)
                        row={'ImageID':f'IMG{len(self.image_rows)+1:06d}','Source':rel.as_posix(),'PNGPath':dest.as_posix(),'Variant':src.stem,'Kind':'loose image','SourceSHA256':digest(src.read_bytes()),'PixelSHA256':digest(im.tobytes()),'Width':im.width,'Height':im.height}
                        self.image_rows.append(row);self.image_by_stem[src.stem.lower()].append(row)
                    except Exception as e:self.warn('Loose image',src,e)
        if self.all_textures:
            for root in (self.game/'Data/ModelTextures',):
                if root.exists():
                    for src in sorted(root.rglob('*.xnb')):
                        if not src.is_symlink():self.add_image(src.read_bytes(),src.relative_to(self.game).as_posix(),Path('LooseFiles')/src.relative_to(self.game),'3D model texture')
    def cut_atlas(self,im,path,parent):
        try:
            config=json.loads(path.read_text(encoding='utf-8-sig'))
            if im.size!=(config['width'],config['height']):raise ValueError('Atlas dimensions do not match texture')
            for i,sprite in enumerate(config.get('sprites',[]),1):
                x,y,w,h=sprite['rect']
                if x<0 or y<0 or w<=0 or h<=0 or x+w>im.width or y+h>im.height:raise ValueError('Sprite rectangle outside atlas')
                tile=im.crop((x,y,x+w,y+h));rel=Path(parent['PNGPath']).parent/(path.stem+'.sprites')/(str(i).zfill(4)+'_'+safe_name(sprite['name'])+'.png')
                (self.out/rel).parent.mkdir(parents=True,exist_ok=True);tile.save(self.out/rel)
                row={'ImageID':f'IMG{len(self.image_rows)+1:06d}','Source':parent['Source']+'#'+sprite['name'],'PNGPath':rel.as_posix(),'Variant':sprite['name'],'Kind':'atlas sprite','ParentImageID':parent['ImageID'],'Width':w,'Height':h,'X':x,'Y':y,'PixelSHA256':digest(tile.tobytes()),'AtlasMetadata':sprite.get('meta',{})}
                self.image_rows.append(row);self.image_by_stem[sprite['name'].lower()].append(row)
                for alias in sprite.get('meta',{}).get('aliases',[]):self.image_by_stem[str(alias).lower()].append(row)
                grid=sprite.get('meta',{}).get('grid')
                if grid:self.warn('Atlas grid',row['Source'],'Grid metadata retained; grid cells are not separately assigned to entities.')
        except Exception as e:self.warn('Atlas slicing',path,e)
    def derived(self):
        m=self.common;v=StaticVM(m)
        # Direct recipes are complete before the client's LINQ-derived factory variants.
        try:v.run(m.find('Common.Game.WosbCrafting','.cctor'))
        except Exception as e:self.warn('Additional recipe variants','Common.Game.WosbCrafting::.cctor',str(e)+'; decoded furnace/workshop/personal-island recipes exported; other factory data may be incomplete')
        recipes=[];ingredients=[]
        decoded_recipes=[]
        for field,context in ((0x04000d01,'Furnace'),(0x04000d02,'Workshop'),(0x04000d04,'Personal island workshop')):
            entries=v.fields.get(field,[])
            if isinstance(entries,list):
                for recipe in entries:
                    recipe['Context']=context;decoded_recipes.append(recipe)
        for idx,r in enumerate(decoded_recipes,1):
            recipeid='CRAFT'+str(idx).zfill(3)
            outputs=r['OutputItems'];is_ammo=r.get(0x04000d0b)==2
            for outid,qty in outputs.items():
                key='cball_'+str(outid) if is_ammo else 'res_'+str(outid)
                name=self.en.get(key+'_name',self.resource_names.get(outid,key))
                if outid==255:name='Gold'
                recipes.append({'RecipeID':recipeid,'Context':r.get('Context'),'OutputID':outid,'OutputType':'ammunition' if is_ammo else 'resource','EnglishName':name,'OutputQuantity':qty,'CraftHours':r['CraftHours'],'Category':self.en.get(r['CategoryKey'],r['CategoryKey']),'InputGold':r['InputGold'],'RequiredFactoryID':r.get('NeedsFactoryInPort'),'HiddenAtLowRank':r.get('HideInLowRank',False),'AnnotationKey':r.get(0x04000d12,''),'Source':'Common.dll: Common.Game.WosbCrafting::.cctor (recipes)'})
            for rid,qty in r['InputItems'].items():ingredients.append({'RecipeID':recipeid,'ResourceID':rid,'EnglishName':self.resource_names.get(rid,'res_'+str(rid)),'Quantity':qty})
        self.save_table('Crafting_Recipes',recipes);self.save_table('Recipe_Ingredients',ingredients)
        prices=[]
        for idx,r in enumerate(self.resources,1):
            if 'MediumCost' not in r:continue
            lo,hi=market_bounds(r['MediumCost'],rid=idx) if r['MediumCost']>0 else (None,None)
            prices.append({'Category':'Resources','NumericID':idx,'TextID':r.get('ID'),'EnglishName':self.en.get(str(r.get('ID'))+'_name',''),'BaseMediumCost':r['MediumCost'],'Currency':'Gold','ClientMinUnitPrice':lo,'ClientMaxUnitPrice':hi,'MinSellQuantity':1,'MaxSellQuantity':None,'QuantityRule':'Sell quantity depends on inventory in port storage or ship hold; no fixed per-item stack maximum confirmed','Tradability':'Price bounds do not establish tradability; removed/restricted items retained','Source':'Common.dll: WosbTrading.GetTradeMinAndMaxCost; WorldOfSeaBattles.dll: C.B::A (0x060029df)'})
        for idx,r in enumerate(self.raw.get('CannonBalls_j',[]),1):
            if 'SingleCost' in r:
                cost=max(0,int(r['SingleCost']))
                lo,hi=market_bounds(cost,'ammunition') if cost>0 else (None,None)
                prices.append({'Category':'CannonBalls','NumericID':idx,'TextID':r['ID'],'EnglishName':self.en.get(r['ID']+'_name',''),'Currency':'Gold','BaseMediumCost':cost,'ShopBattleMarks':abs(int(r['SingleCost'])) if r['SingleCost']<0 else 0,'ShopPackQuantity':int(400/r['SingleCost']) if r['SingleCost']>0 else 1,'ClientMinUnitPrice':lo,'ClientMaxUnitPrice':hi,'Source':'Common.dll: WosbTrading.GetTradeMinAndMaxCost; ammunition SingleCost'})
        self.cannon_recipes(prices)
        self.save_table('Market_Price_Limits',prices)
        self.ship_construction(v)
        rules=[
            {'Topic':'Ship rank','Rule':'Runtime ship rank = source Rank + 1','Source':'Common.Resources.PlayerShipInfo::.ctor'},
            {'Topic':'Crew capacity','Rule':'Base crew places = round(PlacesForUnitsCount * 4)','Source':'Common.Resources.PlayerShipInfo::.ctor'},
            {'Topic':'Speed','Rule':'Internal base speed = BasicSpeed * 2. Raw BasicSpeed is retained; displayed speeds may apply further factors.','Source':'Common.Resources.PlayerShipInfo::.ctor'},
            {'Topic':'Build duration','Rule':'Rank 7: 60 sec; 6: 300; 5: 600; 4: 3600; 3: 7200; 2: 14400; 1: 21600; Unique and Elite: 0. Multiply by the current duration modifier.','Source':'Common.Game.Gameplay.ShipwayDuration'},
            {'Topic':'Instant finish','Rule':'int(max((8 - runtimeRank) * 10, base resource-37 cost * (1 - completionFraction))). Resource 37 is the payment item.','Source':'Common.Game.Gameplay.ShipwayQuickFinishPrice'},
            {'Topic':'Actual construction cost','Rule':'Base costs are adjusted by current port, faction, ship type, events and discounts. Model gun ports affect some ingredients. Unknown ingredient amounts are blank.','Source':'Common.Resources.PlayerShipInfo.GetCraftPrice'},
            {'Topic':'Sell quantities','Rule':'Quantity input starts at 1. Selling maximum reads the current storage/hold item count. A separate purchase-order maximum may depend on gold / minimum price.','Source':'WorldOfSeaBattles.dll: n.D::A (0x060029b9); C.B::A (0x060029df)'},
            {'Topic':'Live market','Rule':'Live orders, current averages and actual lowest/highest player listings are server supplied. They are not read from these offline files.','Source':'Common.Packets.OnAuctionQueryResponse'},
            {'Topic':'Images','Rule':'Every decoded source path is retained, including gray/alternate files. Exact and filename-candidate links are distinguished. Mip levels remain recorded but only the largest level is rendered to PNG.','Source':'Images.csv; Entity_Images.csv'},
            {'Topic':'Recipes','Rule':'Furnace, workshop and personal-island recipes are decoded. Other factories and crafting systems may contain additional rules.','Source':'Crafting_Recipes.csv; Extraction_Issues.csv'}]
        self.save_table('Rules_and_Limitations',rules)
        evidence=self.out/'CodeEvidence';evidence.mkdir(exist_ok=True)
        methods=[('WosbTrading','GetTradeMinAndMaxCost'),('Gameplay','ShipwayDuration'),('Gameplay','ShipwayQuickFinishPrice'),('WosbCrafting','.cctor')]
        for owner,name in methods:
            rid=m.find('Common.Game.'+owner,name);(evidence/(owner+'_'+safe_name(name)+'.il.txt')).write_text(m.evidence(rid),encoding='utf-8')
        for rid in (0x22de,0x22e0): (evidence/('ShipCost_'+hex(rid)+'.il.txt')).write_text(m.evidence(rid),encoding='utf-8')
    def cannon_recipes(self,prices):
        costs={i:r.get('MediumCost',0) for i,r in enumerate(self.resources,1)}
        recipes=[];materials=[]
        for idx,r in enumerate(self.raw.get('Cannons_j',[]),1):
            price=r.get('Price',0);items={};gold=0;status='Decoded base recipe'
            if r.get('CraftingType')=='ByGold':gold=price
            else:
                cat=r.get('Category','').split()[0]
                if r.get('Class','').split()[0]=='Mortar':
                    pound=r.get('Poundage',0);feature=r.get('Class','').split()[-1]
                    cat='Light' if pound in (6,7) else ('Medium' if pound in (8,9) or feature!='Default' else 'Heavy')
                weights={'Light':[(4,60),(2,40)],'Medium':[(4,45),(2,20),(11,35)],'Heavy':[(4,22),(23,18),(37,15),(14,45)]}.get(cat)
                if not weights:status='Unresolved category';self.warn('Cannon recipe',r.get('ID'),status)
                else:
                    count=[price*pct//100//costs[rid] if costs[rid]>0 else 0 for rid,pct in weights]
                    total=sum(q*costs[rid] for q,(rid,pct) in zip(count,weights))
                    cheapest=min(range(len(weights)),key=lambda i:costs[weights[i][0]])
                    delta=int(round((price-total)/costs[weights[cheapest][0]]))
                    newtotal=total+delta*costs[weights[cheapest][0]]
                    if abs(price-newtotal)<=abs(price-total):count[cheapest]+=delta
                    items={rid:q for q,(rid,pct) in zip(count,weights) if q>0}
            name=self.en.get(r['ID']+'_name','');value=gold+sum(q*costs[rid] for rid,q in items.items())
            lo,hi=market_bounds(value,'cannon') if value>0 else (None,None)
            recipes.append({'CannonIndex':idx,'TextID':r['ID'],'EnglishName':name,'BaseGold':gold,'CraftingType':r.get('CraftingType'),'GoldEquivalentCost':value,'Status':status,'Source':'Common.dll: Gameplay 0x060022d5 and 0x060022d6; CannonGameInfo::.ctor'})
            for rid,qty in items.items():materials.append({'CannonIndex':idx,'TextID':r['ID'],'EnglishName':name,'ResourceID':rid,'ResourceEnglishName':self.resource_names.get(rid),'BaseQuantity':qty})
            prices.append({'Category':'Cannons','NumericID':idx,'TextID':r['ID'],'EnglishName':name,'Currency':'Gold','BaseMediumCost':value,'ClientMinUnitPrice':lo,'ClientMaxUnitPrice':hi,'Tradability':'Bounds do not establish tradability','Source':'Common.dll: CannonGameInfo.CostAsGold and WosbTrading.GetTradeMinAndMaxCost'})
        self.save_table('Cannon_Crafting',recipes);self.save_table('Cannon_Materials',materials)
    def ship_construction(self,v):
        ships=self.raw.get('ShipsToPlay_j',[]);avg=defaultdict(list)
        for s in ships:avg[s['Rank']].append(s['Health'])
        v.fields[0x04000ba8]=[{'Avg':sum(avg[i])/len(avg[i])} if avg[i] else {'Avg':0} for i in range(10)]
        v.allowed={0x2303,0x22de,0x22e0}
        oldinvoke=v.invoke
        def invoke(tok,args,construct=False):
            if tok.table==6 and tok.rid==0x22c0:
                inputid,outputid=args
                for r in v.created:
                    if outputid in r['OutputItems'] and not r.get(0x04000d0b,0):return r['InputItems'].get(inputid,0)
                raise ValueError('Workshop recipe conversion not found')
            return oldinvoke(tok,args,construct)
        v.invoke=invoke
        rows=[];materials=[]
        cool={'Default':0,'Unique':1,'Elite':2,'Empire':3};classes={'Destroyer':0,'Battleship':1,'Hardship':2,'CargoShip':3,'Mortar':4}
        duration={1:21600,2:14400,3:7200,4:3600,5:600,6:300,7:60}
        for s in ships:
            sid=s['ID'];rank=s['Rank']+1;kind=s.get('Coolness','Default').split()[0];base={};status=''
            try:
                if sid==1:base={};status='Starter ship: no base materials'
                elif kind not in cool or s['Type'] not in classes:raise ValueError('Unrecognized ship classification')
                elif kind not in ('Default','Elite') and s.get('Subtype')!='subclass_balloon':
                    base=v.run(0x22e0,[cool[kind],s['Rank'],sid])['items'];status='Base special-ship purchase recipe; discounts and hull/decraft recipe separate'
                else:
                    base=v.run(0x22de,[cool[kind],classes[s['Type']],sid,s['Rank'],s['Health'],s['Armor'],s['CapacityCg'],U,U,s['BasicSpeed']*2,s['BasicMobility']])['items']
                    status='Base hull materials; blank amounts require model gun-port counts' if any(isinstance(x,Unknown) for x in base.values()) else 'Base hull materials decoded; live modifiers separate'
            except Exception as e:self.warn('Ship construction',sid,e);status='Construction formula unresolved: '+str(e)
            if sid==70:base={72:60000};status='Special direct purchase override'
            if sid==81:base={37:9600};status='Special direct purchase override'
            mark=base.get(37,0)
            minimum=max(0,(8-rank)*10)
            seconds=0 if kind in ('Unique','Elite') else duration.get(rank)
            applicable=bool(seconds)
            finish=None if isinstance(mark,Unknown) or not applicable else int(max(minimum,mark))
            rows.append({'ShipID':sid,'EnglishName':self.en.get(f'ship_{sid}_name',''),'ShipRank':rank,'Coolness':s.get('Coolness'),'BaseShipwaySeconds':seconds,'InstantFinishApplicable':applicable,'InstantFinishAt0Percent_Resource37':finish,'InstantFinishMinimum_Resource37':minimum if applicable else None,'PaymentItemEnglish':self.resource_names.get(37),'BaseGoldCost':0,'GoldCostStatus':'Base gold component is zero in this build; player modifiers and other purchase modes separate','ConstructionStatus':status,'Source':'Common.dll: PlayerShipInfo::.ctor; Gameplay.ShipwayDuration; Gameplay.ShipwayQuickFinishPrice'})
            for rid,qty in base.items():
                if not isinstance(qty,Unknown) and qty==0:continue
                materials.append({'ShipID':sid,'ShipEnglishName':self.en.get(f'ship_{sid}_name',''),'ResourceID':rid,'ResourceEnglishName':self.resource_names.get(rid,'res_'+str(rid)),'BaseQuantity':plain(qty),'Status':'Requires model gun-port counts' if isinstance(qty,Unknown) else 'Computed base amount before player/port/event modifiers'})
        self.save_table('Ship_Construction',rows);self.save_table('Ship_Materials',materials)
    def write_readme(self):
        text='''WORLD OF SEA BATTLE - ENGLISH CATALOG\n\nOpen the CSV files in Spreadsheets with Excel, or import them as UTF-8 CSV.\nNames/descriptions come from en-US.lang only. Other language files are not read.\nRawData preserves decoded JSON tables without discarding extra fields.\nImages contains PNG textures, alternate and gray versions, and atlas sprites.\nImages.csv indexes every image; Entity_Images.csv links known references.\nGallery.html is an offline searchable image browser.\n\nSOURCE DATA AND CALCULATIONS\nRaw stats retain client field names and source records. Derived values are\nseparate. Base quantities are not quotes for a particular player or port.\nShip crafting includes known base ingredients; gun-port-dependent amounts\nremain blank until a model parser is added. Separate gold components and\nplayer/port/event discounts are not fully evaluated.\nDecoded furnace/workshop/personal-island recipes are exported; other factory data,\nweapon crafting, upgrades and other systems may have additional requirements.\nMarket bounds are client limits, not live player listing prices.\nSelling quantity depends on inventory, so no fixed item maximum is invented.\nSee Rules_and_Limitations.csv and Extraction_Issues.csv for details.\n\nImages preserve source paths and variants rather than deduplicating them.\nPixel hashes help identify duplicates. Links marked candidate need review.\nMipLevels records resolution levels; PNG uses the largest level only.\nThis is an image extractor, not a renderer for 3D ship models.\n\nThe tool reads files without loading game DLLs or contacting game servers.\nNo login credentials, launcher config, or tokens are scanned.\n'''
        (self.out/'START-HERE.txt').write_text(text,encoding='utf-8')
    def write_gallery(self):
        data=[];labels=defaultdict(list)
        for l in self.links:labels[l['ImageID']].append(l['Category']+' '+str(l['EntityID']))
        for r in self.image_rows:data.append({'id':r['ImageID'],'path':r['PNGPath'],'name':r['Variant'],'source':r['Source'],'label':', '.join(labels[r['ImageID']]),'w':r['Width'],'h':r['Height']})
        js=json.dumps(data,ensure_ascii=False).replace('<','\\u003c')
        doc='''<!doctype html><html lang="en"><meta charset="utf-8"><title>WOSB Image Catalog</title><style>body{font:15px system-ui;background:#101b2a;color:#e7effa;margin:24px}h1{margin-bottom:8px}input{padding:12px;width:min(600px,90%);font:inherit}#grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:16px;margin-top:22px}.card{background:#203047;padding:12px;overflow-wrap:anywhere}.card img{width:100%;height:160px;object-fit:contain;background:repeating-conic-gradient(#344359 0 25%,#29374b 0 50%) 0/20px 20px}small{color:#c3d3e8}a{color:#9bd9ff}</style><h1>World of Sea Battle images</h1><p>Every extracted version is preserved. Search names, source paths, or linked entity IDs.</p><input id="q" placeholder="Search shipIcon, gray, Res, etc."><p id="count"></p><div id="grid"></div><script>const items=DATA;const q=document.getElementById('q'),grid=document.getElementById('grid');function render(){const text=q.value.toLowerCase();const filtered=items.filter(x=>(x.name+' '+x.source+' '+x.label).toLowerCase().includes(text));document.getElementById('count').textContent=filtered.length+' images';grid.replaceChildren();for(const x of filtered){const c=document.createElement('div');c.className='card';const a=document.createElement('a');a.href=x.path;a.target='_blank';const img=document.createElement('img');img.loading='lazy';img.src=x.path;img.alt=x.name;a.append(img);c.append(a);const t=document.createElement('p');t.textContent=x.id+' — '+x.name;c.append(t);const s=document.createElement('small');s.textContent=x.w+' × '+x.h+' | '+x.source+' | '+x.label;c.append(s);grid.append(c)}}q.oninput=render;render();</script></html>'''
        (self.out/'Gallery.html').write_text(doc.replace('DATA',js),encoding='utf-8')

def locate_game(root):
    p=Path(root)
    for candidate in (p,p/'default/game',p/'game'):
        if (candidate/'CommonData/_lzcommon.wosb').exists() or (candidate/'_lzcommon.wosb').exists():return candidate.resolve()
    raise ValueError('Cannot find CommonData/_lzcommon.wosb under '+str(root))
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--game',default=r'C:\Games\World of Sea Battle')
    p.add_argument('--output',help='New output folder outside the game installation')
    p.add_argument('--no-images',action='store_true')
    p.add_argument('--combat',action='store_true',help='Scan client assemblies and configuration for combat mechanics with IL evidence')
    p.add_argument('--combat-only',action='store_true',help='Run combat research independently; no encrypted archive or game version assumptions')
    p.add_argument('--combat-max-methods',type=int,default=1000,help='Maximum relevant methods whose IL is saved')
    p.add_argument('--craft-quantity',type=int,default=1,help='Requested output quantity for upstream material-chain plans')
    p.add_argument('--broad',action='store_true',help='Export all data fields, benefit levels, map objects, model metadata and game-code evidence')
    p.add_argument('--preserve-assets',action='store_true',help='Copy original shared/loose game assets, including unsupported models/media; may require several GB')
    p.add_argument('--all-textures',action='store_true',help='Also decode 3D model surface textures')
    a=p.parse_args();game=Path(a.game).resolve() if a.combat_only else locate_game(a.game)
    out=Path(a.output).resolve() if a.output else Path(__file__).resolve().parent/('WOSB-Catalog-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
    if game==out or game in out.parents:raise ValueError('Choose an output folder outside the game installation')
    if a.craft_quantity<=0:raise ValueError('Craft quantity must be positive')
    if a.combat_max_methods<1:raise ValueError('Combat max methods must be positive')
    if a.combat_only:
        from combat_research import analyze
        print(json.dumps(analyze(game,out,max_methods=a.combat_max_methods),indent=2))
        return
    extractor=Extractor(game,out,not a.no_images,a.all_textures,a.broad,a.preserve_assets)
    extractor.craft_quantity=a.craft_quantity
    extractor.combat=a.combat
    extractor.combat_max_methods=a.combat_max_methods
    extractor.extract()
if __name__=='__main__':
    try:main()
    except Exception:
        traceback.print_exc();sys.exit(1)
