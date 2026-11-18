"""Mesh integrity diagnostics for recovered, *real* WoSB geometry.

Reports evidence of omitted/degenerate faces, UV availability, and topology.
Topology edges are intentionally bounded, but neither this audit nor the
renderer discards geometry to satisfy its diagnostics budget.
"""
from __future__ import annotations
from collections import Counter
from pathlib import Path
import json, math

MAX_AUDIT_TRIANGLES=250_000


def inspect_mesh(mesh, *, edge_limit=MAX_AUDIT_TRIANGLES):
    verts=mesh.get('vertices',[]);tri=mesh.get('triangles',[])
    if len(tri)%3:raise ValueError('Index buffer not divisible by three')
    n=len(tri)//3;bad=0;zero=0;area=0.0;edge=Counter();invalid_uv=0
    uv=mesh.get('uvs',[]) or [];triu=mesh.get('triangle_uvs',[]) or []
    for j in range(n):
        a,b,c=tri[3*j:3*j+3]
        if min(a,b,c)<0 or max(a,b,c)>=len(verts):bad+=1;continue
        p,q,r=verts[a],verts[b],verts[c]
        x=[q[i]-p[i] for i in range(3)];y=[r[i]-p[i] for i in range(3)]
        norm=(x[1]*y[2]-x[2]*y[1],x[2]*y[0]-x[0]*y[2],x[0]*y[1]-x[1]*y[0])
        ar=math.sqrt(sum(t*t for t in norm))/2
        if not math.isfinite(ar) or ar<1e-10:zero+=1
        else:area+=ar
        if triu and (max(triu[3*j:3*j+3])>=len(uv) or min(triu[3*j:3*j+3]) < -1):invalid_uv+=1
        if j<edge_limit:
            for u,v in ((a,b),(b,c),(c,a)):
                edge[tuple(sorted((u,v)))]+=1
    groups=[]
    for g in mesh.get('groups',[]):
        start=g.get('first_triangle',0);count=g.get('triangle_count',0)
        groups.append({'name':g.get('name',''), 'material':g.get('material',''), 'category':g.get('category',''),
                       'triangles':count,'range_valid':0<=start and count>=0 and start+count<=n})
    problems=[]
    if bad:problems.append(f'{bad} invalid indexed triangles')
    if zero:problems.append(f'{zero} degenerate or near-zero-area triangles')
    if invalid_uv:problems.append(f'{invalid_uv} triangles reference invalid texture UVs')
    if not uv:problems.append('No texture UV coordinates')
    if any(not g['range_valid'] for g in groups):problems.append('Invalid group triangle ranges')
    # A boundary edge is not inherently a hole; sails and open decking have genuine boundaries.
    boundary=sum(c==1 for c in edge.values())
    nonmanifold=sum(c>2 for c in edge.values())
    return {'source':mesh.get('source_name',''), 'source_triangle_count':mesh.get('original_triangles_count',n),
            'decoded_triangles':n,'vertices':len(verts),'uv_coordinates':len(uv),'surface_area_model_units_sq':round(area,4),
            'degenerate_triangles':zero,'invalid_indices':bad,'invalid_uv_triangles':invalid_uv,
            'boundary_edges_sampled':boundary,'nonmanifold_edges_sampled':nonmanifold,
            'topology_triangles_sampled':min(n,edge_limit),'topology_complete':n<=edge_limit,
            'triangle_geometry_preserved':n==mesh.get('original_triangles_count',n),
            'groups':groups,'warnings':problems,
            'interpretation':'Boundary and non-manifold edges do not prove visible holes. Verify original XNB, winding, opacity and render culling.'}


def audit_obj(input_file, output_file=None):
    from ship_viewer import read_obj
    report=inspect_mesh(read_obj(input_file))
    if output_file:
        dest=Path(output_file);dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('obj');p.add_argument('--output');args=p.parse_args()
    print(json.dumps(audit_obj(args.obj,args.output),indent=2))
