"""Repeatable self-benchmark for computational research stages (not GPU FPS)."""
from __future__ import annotations
import platform,time,tracemalloc


def benchmark_geometry(*,grid=55,ray_count=200):
    if not 2<=grid<=150 or not 1<=ray_count<=3000:raise ValueError('Unsafe benchmark size')
    from advanced_geometry import MeshRaycaster
    vertices=[];tri=[]
    for y in range(grid+1):
        for x in range(grid+1):vertices.append([float(x),float(y),0])
    for y in range(grid):
        for x in range(grid):
            a=y*(grid+1)+x;b=a+1;c=a+grid+1;d=c+1
            tri.extend([a,b,c,b,d,c])
    tracemalloc.start();a=time.perf_counter()
    caster=MeshRaycaster({'vertices':vertices,'triangles':tri})
    b=time.perf_counter();hits=0
    for i in range(ray_count):
        x=.2+(i*37%(grid*100-40))/100
        if caster.hit([x,grid/2,10],[0,0,-1]):hits+=1
    c=time.perf_counter();current,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
    return {'format':'wosb-geometry-benchmark-v1','python':platform.python_version(),
            'triangles':len(tri)//3,'rays':ray_count,'intersections':hits,
            'bvh_build_seconds':round(b-a,6),'raycast_seconds':round(c-b,6),
            'traced_peak_bytes':peak,
            'scope':'Synthetic CPU mesh/raycast only; not a GPU/WebGL, real-client, or sustained-capture benchmark'}
