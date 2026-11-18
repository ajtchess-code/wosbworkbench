"""Trace client recipes to leaf resources, keeping route choices and unknowns explicit."""
import math
from collections import defaultdict

def build_plan(tables,target,quantity=1,context='Workshop',whole=True):
    resources={i:r for i,r in enumerate(tables.get('Resources',[]),1)}
    names={i:r.get('EnglishName',r.get('ID',str(i))) for i,r in resources.items()}
    names[255]='Gold'
    inputs=defaultdict(list)
    for r in tables.get('Recipe_Ingredients',[]):inputs[r['RecipeID']].append((int(r['ResourceID']),r['Quantity']))
    recipes=defaultdict(list)
    for r in tables.get('Crafting_Recipes',[]):
        if r.get('OutputType')=='resource' and r.get('OutputQuantity',0)>0:recipes[int(r['OutputID'])].append(r)
    natural=set()
    for f in tables.get('Factory_Levels',[]):
        if f.get('Level')==1 and not f.get('ConsumeItems'):
            natural.update(int(k) for k in f.get('ProduceItems',{}))
    chosen={};seen=set();active=set();post=[];problems=[];edges=[]
    def visit(rid):
        if rid in active:problems.append('Recipe cycle involving '+names.get(rid,str(rid)));return
        if rid in seen:return
        active.add(rid)
        options=recipes.get(rid,[])
        # A bare base-level producer provides a raw acquisition route; recycling
        # recipes for that item are alternatives, not forced upstream steps.
        if rid in natural:options=[]
        options=sorted(options,key=lambda r:(0 if r.get('Context')=='Furnace' else 1 if r.get('Context')==context else 2 if r.get('Context')=='Workshop' else 3,r['RecipeID']))
        recipe=options[0] if options else None;chosen[rid]=recipe
        if recipe:
            for child,amount in inputs[recipe['RecipeID']]:
                if amount<0:problems.append('Negative ingredient quantity in '+recipe['RecipeID']);continue
                edges.append((rid,child,amount));visit(child)
        active.remove(rid);seen.add(rid);post.append(rid)
    visit(target)
    if problems:return {'TargetID':target,'TargetName':names.get(target,str(target)),'RequestedQuantity':quantity,'Context':context,'QuantityMode':'Whole batches' if whole else 'Proportional','Complete':False,'Problems':problems,'Steps':[],'Leaves':[]}
    demands=defaultdict(float);demands[target]=quantity;steps=[];leaves=[];time=0.;gold=0.
    for rid in reversed(post):
        need=demands[rid];r=chosen[rid]
        if r:
            batches=math.ceil(need/r['OutputQuantity']-1e-12) if whole else need/r['OutputQuantity']
            produced=batches*r['OutputQuantity'];hours=batches*r.get('CraftHours',0);money=batches*r.get('InputGold',0)
            time+=hours;gold+=money
            steps.append({'ResourceID':rid,'EnglishName':names.get(rid,str(rid)),'RequiredQuantity':need,'RecipeID':r['RecipeID'],'RecipeContext':r.get('Context'),'OutputPerBatch':r['OutputQuantity'],'Batches':batches,'ProducedQuantity':produced,'LeftoverQuantity':produced-need,'CraftHours':hours,'DirectGold':money,'RequiredFactoryID':r.get('RequiredFactoryID')})
            for child,amount in inputs[r['RecipeID']]:demands[child]+=amount*batches
        else:
            leaves.append({'ResourceID':rid,'EnglishName':names.get(rid,str(rid)),'TotalQuantity':need,'AcquisitionStatus':'Base-level producer with no material input exists; harvesting time/ownership not modeled' if rid in natural else 'No upstream recipe decoded; acquisition path unresolved','UpstreamResolved':rid in natural})
    return {'TargetID':target,'TargetName':names.get(target,str(target)),'RequestedQuantity':quantity,'Context':context,'QuantityMode':'Whole batches' if whole else 'Proportional','Complete':True,'RawAcquisitionFullyLocated':all(r['UpstreamResolved'] for r in leaves),'RoutePolicy':'Prefer bare base-level production as a leaf, then Furnace, selected workshop context, then source-order alternatives. This is one documented route, not an optimized cheapest route. Alternative recipes remain in Crafting_Recipes.','TotalRecipeCraftHours':time,'TotalDirectRecipeGold':gold,'TimeMeaning':'Sum of recipe craft-hour charges; not elapsed wall-clock time and excludes harvesting/parallelism/modifiers','Problems':[],'Steps':steps,'Leaves':leaves}

def export_chains(x):
    summaries=[];steps=[];leaves=[]
    targets=sorted({int(r['OutputID']) for r in x.tables.get('Crafting_Recipes',[]) if r.get('OutputType')=='resource'})
    qty=getattr(x,'craft_quantity',1)
    for rid in targets:
        for context in ('Workshop','Personal island workshop'):
            for whole in (True,False):
                p=build_plan(x.tables,rid,qty,context,whole)
                pid=f'R{rid}_{"personal" if context.startswith("Personal") else "workshop"}_{"batch" if whole else "ratio"}'
                summaries.append({'PlanID':pid,**{k:v for k,v in p.items() if k not in ('Steps','Leaves')}})
                steps.extend({'PlanID':pid,**r} for r in p['Steps'])
                leaves.extend({'PlanID':pid,**r} for r in p['Leaves'])
    x.save_table('Resource_Chain_Plans',summaries);x.save_table('Resource_Chain_Steps',steps);x.save_table('Resource_Chain_Raw_Totals',leaves)
