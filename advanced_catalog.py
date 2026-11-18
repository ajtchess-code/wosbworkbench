"""Provenance-aware, bounded cross-client encyclopedia and crafting comparison."""
from __future__ import annotations
from collections import Counter,defaultdict
import hashlib


def dataset_snapshot(conn,source_root='Game',*,max_records=250_000):
    rows=conn.execute('SELECT dataset,external_id,name,raw_json,sha256,source_file FROM records WHERE source_root=?',(source_root,))
    entries={};count=0
    for row in rows:
        count+=1
        if count>max_records:raise ValueError('Dataset limit exceeded')
        key=f'{row["dataset"]}:{row["external_id"]}'
        entries[key]={'name':row['name'],'sha256':row['sha256'] or hashlib.sha256(row['raw_json'].encode()).hexdigest(),
                      'source_file':str(row['source_file']).split('/')[-1].split('\\')[-1]}
    return {'format':'wosb-catalog-snapshot-v1','source_root':source_root,'records':entries,
            'note':'Raw game records are not embedded in this difference report.'}


def compare_catalogs(old,new):
    a=old['records'];b=new['records'];groups=defaultdict(lambda:Counter())
    changes={'added':[],'removed':[],'changed':[]}
    for key in sorted(set(a)|set(b)):
        group=key.split(':',1)[0]
        if key not in a:kind='added'
        elif key not in b:kind='removed'
        elif a[key]['sha256']!=b[key]['sha256']:kind='changed'
        else:continue
        changes[kind].append({'key':key,'before':a.get(key),'after':b.get(key)})
        groups[group][kind]+=1
    return {'format':'wosb-catalog-diff-v1','by_dataset':{k:dict(v) for k,v in groups.items()},
            'changes':changes,'status':'client catalog values only, no server confirmation'}


def record_provenance(conn,query,*,max_hits=30):
    text=str(query).strip()
    if not text or len(text)>200:raise ValueError('Search query required')
    safe='%'+text.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
    rows=conn.execute('''SELECT dataset,source_root,external_id,name,description,source_file,sha256 FROM records
        WHERE name LIKE ? ESCAPE '\\' ORDER BY dataset,name LIMIT ?''',(safe,max_hits))
    return {'format':'wosb-encyclopedia-provenance-v1','matches':[dict(r) for r in rows],
            'game_logic_certification':'none; these are imported catalog records'}


def crafting_graph(tables,target_id,quantity=1):
    from engine.recipe_chains import build_plan
    plan=build_plan(tables,int(target_id),quantity)
    nodes={};links=[]
    for step in plan.get('Steps',[]):
        rid=str(step['ResourceID']);nodes[rid]={'name':step['EnglishName'],'kind':'crafted','quantity':step['RequiredQuantity']}
    for raw in plan.get('Leaves',[]):
        rid=str(raw['ResourceID']);nodes[rid]={'name':raw['EnglishName'],'kind':'raw_or_unresolved',
             'quantity':raw['TotalQuantity'],'upstream_resolved':raw['UpstreamResolved']}
    # Exact ingredients are returned from the actual decoded tables.
    target_nodes={int(x['ResourceID']) for x in plan.get('Steps',[])}
    recipes={int(x['RecipeID']):x for x in tables.get('Crafting_Recipes',[]) if x.get('RecipeID') is not None}
    byrecipe=defaultdict(list)
    for x in tables.get('Recipe_Ingredients',[]):byrecipe[int(x['RecipeID'])].append(x)
    for step in plan.get('Steps',[]):
        for item in byrecipe.get(int(step['RecipeID']),[]):
            links.append({'from':str(item['ResourceID']),'to':str(step['ResourceID']),
                          'per_batch_quantity':item['Quantity']})
    return {'format':'wosb-crafting-graph-v1','plan':plan,'nodes':nodes,'edges':links,
            'warning':'One documented recipe route, not necessarily the cheapest or fastest market route.'}
