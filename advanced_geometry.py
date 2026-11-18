"""Offline triangle and ray-hit research on recovered game geometry.

A rendered triangle and a ray intersection are NOT an authoritative game hitbox.
No damage multiplier is inferred from geometry. All outputs are labeled hypotheses.
"""
from __future__ import annotations

import math
from pathlib import Path
from dataclasses import dataclass

EPS = 1e-10
MAX_TRIANGLES = 900_000


def _vector(v):
    if len(v) != 3 or any(not math.isfinite(float(x)) for x in v):
        raise ValueError('Expected finite xyz vector')
    return tuple(float(x) for x in v)


def _dot(a, b):
    return sum(x*y for x,y in zip(a,b))


def _sub(a, b):
    return tuple(x-y for x,y in zip(a,b))


def _cross(a,b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def _unit(v):
    length = math.sqrt(_dot(v,v))
    if length <= EPS: raise ValueError('Zero-length direction')
    return tuple(q/length for q in v)


def _bounds(vectors):
    return (tuple(min(v[i] for v in vectors) for i in range(3)),
            tuple(max(v[i] for v in vectors) for i in range(3)))


def _box_hit(origin,direction,bounds,limit):
    tmin=0.0;tmax=limit
    for i in range(3):
        lo,hi=bounds[0][i],bounds[1][i]
        if abs(direction[i]) < EPS:
            if origin[i]<lo or origin[i]>hi:return False
        else:
            a=(lo-origin[i])/direction[i];b=(hi-origin[i])/direction[i]
            if a>b:a,b=b,a
            tmin=max(tmin,a);tmax=min(tmax,b)
            if tmin>tmax:return False
    return True


def _triangle_hit(origin,direction,a,b,c,backface_cull=False):
    edge1=_sub(b,a);edge2=_sub(c,a)
    h=_cross(direction,edge2);det=_dot(edge1,h)
    if (det<EPS if backface_cull else abs(det)<EPS):return None
    inv=1/det;s=_sub(origin,a);u=inv*_dot(s,h)
    if u<-EPS or u>1+EPS:return None
    q=_cross(s,edge1);v=inv*_dot(direction,q)
    if v<-EPS or u+v>1+EPS:return None
    distance=inv*_dot(edge2,q)
    if distance<EPS:return None
    normal=_unit(_cross(edge1,edge2))
    return (distance,u,v,normal)


@dataclass
class _Node:
    bounds: tuple
    left: object = None
    right: object = None
    indices: tuple = ()


class MeshRaycaster:
    """Bounded median-split BVH; returned intersections concern visible mesh only."""
    def __init__(self,mesh,*,leaf_size=16):
        self.vertices=[_vector(v) for v in mesh.get('vertices',[])]
        self.indices=mesh.get('triangles',[])
        if len(self.indices)%3:raise ValueError('Incomplete triangle index buffer')
        self.size=len(self.indices)//3
        if not 0<self.size<=MAX_TRIANGLES:raise ValueError('Empty or excessively large mesh')
        for i in self.indices:
            if type(i)!=int or not 0<=i<len(self.vertices):raise ValueError('Triangle index out of range')
        self.groups=mesh.get('groups',[])
        self.leaf_size=max(2,min(128,int(leaf_size)))
        self.tri_bounds=[];self.centroids=[]
        for j in range(self.size):
            ids=self.indices[3*j:3*j+3];pts=[self.vertices[i] for i in ids]
            box=_bounds(pts);self.tri_bounds.append(box)
            self.centroids.append(tuple(sum(p[k] for p in pts)/3 for k in range(3)))
        self.root=self._build(list(range(self.size)))

    def _build(self,ids):
        box=(tuple(min(self.tri_bounds[j][0][i] for j in ids) for i in range(3)),
             tuple(max(self.tri_bounds[j][1][i] for j in ids) for i in range(3)))
        if len(ids)<=self.leaf_size:return _Node(box,indices=tuple(ids))
        axis=max(range(3),key=lambda i:box[1][i]-box[0][i]);ids.sort(key=lambda j:self.centroids[j][axis]);cut=len(ids)//2
        return _Node(box,self._build(ids[:cut]),self._build(ids[cut:]))

    def _group(self,triangle_id):
        for g in self.groups:
            start=g.get('first_triangle',0)
            if start<=triangle_id<start+g.get('triangle_count',0):
                return {'name':g.get('name'),'material':g.get('material'),'category':g.get('category')}
        return None

    def hit(self,origin,direction,*,distance_limit=1e8,backface_cull=False):
        origin=_vector(origin);direction=_unit(_vector(direction))
        if not 0<distance_limit<=1e10:raise ValueError('Invalid ray length')
        stack=[self.root];best=None;best_distance=distance_limit
        while stack:
            node=stack.pop()
            if not _box_hit(origin,direction,node.bounds,best_distance):continue
            if node.indices:
                for j in node.indices:
                    a,b,c=(self.vertices[self.indices[3*j+k]] for k in range(3))
                    result=_triangle_hit(origin,direction,a,b,c,backface_cull)
                    if result is not None and result[0]<best_distance:
                        best_distance=result[0];best=(j,result)
            else:stack.extend((node.left,node.right))
        if best is None:return None
        j,(t,u,v,normal)=best
        incidence=math.degrees(math.acos(min(1.0,max(0.0,abs(_dot(normal,direction))))))
        return {'triangle':j,'distance':round(t,7),'point':[round(origin[i]+t*direction[i],7) for i in range(3)],
                'normal':[round(q,7) for q in normal], 'barycentric':[round(1-u-v,7),round(u,7),round(v,7)],
                'incidence_angle_deg':round(incidence,5),
                'mesh_group':self._group(j), 'evidence_status':'visible-mesh intersection only',
                'game_collision_verified':False}

    def bounds(self):return [list(self.root.bounds[0]),list(self.root.bounds[1])]


def compare_impacts(mesh, rays,*,max_rays=10000):
    if len(rays)>max_rays:raise ValueError('Too many rays')
    caster=MeshRaycaster(mesh)
    out=[]
    for r in rays:
        hit=caster.hit(r['origin'],r['direction'])
        out.append({'label':r.get('label',''), 'impact':hit})
    return {'format':'wosb-raycast-v1','bounds':caster.bounds(),'rays':out,
            'provenance':{'geometry':'decoded/imported visible mesh', 'collision':'UNVERIFIED',
                          'damage':'NOT predicted from the hit location alone'}}


def sample_heatmap(mesh,cannon,ammo,*,target_armor,angle_deg=0,samples=16,axis=0):
    """Camera-independent orthographic ray grid with assumed armor/damage model.

    Only marks surface hit locations; all points use the same user supplied armor.
    Therefore this is an incidence-angle / hypothetical penetration *index*, not
    a map of independently recovered local armor or a verified weak-spot map.
    """
    if not 2<=samples<=64:raise ValueError('samples must be in 2..64')
    if axis not in (0,1,2):raise ValueError('axis must be 0, 1 or 2')
    from damage_hypotheses import calculate
    caster=MeshRaycaster(mesh);lo,hi=caster.bounds();cross=[i for i in range(3) if i!=axis]
    if any(hi[i]-lo[i]<EPS for i in cross):raise ValueError('Mesh has flat target bounds')
    points=[]
    for j in range(samples):
        for k in range(samples):
            origin=[0.,0.,0.];origin[axis]=hi[axis]+max(1.,(hi[axis]-lo[axis])*.1)
            origin[cross[0]]=lo[cross[0]]+(j+.5)/samples*(hi[cross[0]]-lo[cross[0]])
            origin[cross[1]]=lo[cross[1]]+(k+.5)/samples*(hi[cross[1]]-lo[cross[1]])
            direction=[0.,0.,0.];direction[axis]=-1.
            hit=caster.hit(origin,direction)
            if hit:
                angle=hit['incidence_angle_deg']
                # The optional offset represents a researcher's external angle assumption.
                angle=min(89.9,angle+float(angle_deg))
                candidate=calculate(cannon,ammo,target_armor=float(target_armor),angle_deg=angle)
                points.append({'grid':[j,k], 'hit':hit, 'angle_deg':angle,
                               'hypothetical_penetration_ratio':candidate['hypotheses']['penetration_to_armor_ratio'],
                               'hypothetical_smooth_damage_index':candidate['hypotheses']['index_if_smooth_model']})
    return {'format':'wosb-visual-hypothesis-heatmap-v1','axis':axis,'resolution':samples,
            'points':points,'total_samples':samples*samples,'mesh_hits':len(points),
            'armor_model':'USER-DEFINED UNIFORM ARMOR — no local ship armor information inferred',
            'authoritative_collision':False,'authoritative_damage':False}


def analyze_obj(obj_path,output_dir,*,rays=None,cannon=None,ammo=None,armor=None,samples=12):
    from ship_viewer import read_obj
    from model_quality import inspect_mesh
    mesh=read_obj(obj_path);dest=Path(output_dir);dest.mkdir(parents=True,exist_ok=True)
    products={'quality':inspect_mesh(mesh),'raycast':compare_impacts(mesh,rays or [])}
    if cannon is not None and ammo is not None and armor is not None:
        products['heatmap']=sample_heatmap(mesh,cannon,ammo,target_armor=armor,samples=samples)
    from advanced_io import write_json_atomic
    for kind,content in products.items():
        target=dest/(Path(obj_path).stem+'-'+kind+'.json')
        write_json_atomic(target,content)
    return {'format':'wosb-geometry-research-v1','reports':list(products),'folder':str(dest),'triangles':len(mesh['triangles'])//3}
