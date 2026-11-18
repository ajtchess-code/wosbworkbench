"""Independent, offline, non-networked WoSB-inspired simulation testbed.

No claim of interoperability with the game's servers or official protocol.
Gameplay damage is accepted only as explicit observed events until the final
hit-resolution rules are validated; no login, sockets or packet interception.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
import json, math

@dataclass
class Vessel:
    id: str
    name: str
    max_hp: float
    hp: float
    x: float=0.
    z: float=0.
    heading_deg: float=0.
    velocity: float=0.
    sails: float=0.

class SandboxWorld:
    def __init__(self, *, tick_seconds=0.1,wind_bearing=0):
        if not 0<tick_seconds<=5:raise ValueError('Invalid tick')
        self.tick_seconds=tick_seconds;self.wind_bearing=wind_bearing;self.vessels={};self.events=[];self.clock=0.
    def spawn(self,id,name,max_hp,*,x=0,z=0,heading_deg=0):
        if id in self.vessels or not 0<float(max_hp)<1e10:raise ValueError('Invalid vessel')
        self.vessels[id]=Vessel(str(id),str(name),float(max_hp),float(max_hp),float(x),float(z),float(heading_deg))
        return self.vessels[id]
    def set_controls(self,id,*,speed=None,heading_deg=None,sails=None):
        v=self.vessels[id]
        if speed is not None:
            v.velocity=float(speed)
            if not math.isfinite(v.velocity) or abs(v.velocity)>10000:raise ValueError('Invalid speed')
        if heading_deg is not None:v.heading_deg=float(heading_deg)%360
        if sails is not None:
            if not 0<=float(sails)<=1:raise ValueError('Sail trim must be between 0 and 1')
            v.sails=float(sails)
    def step(self,n=1):
        if not isinstance(n,int) or not 0<=n<=100000:raise ValueError('Invalid step count')
        for _ in range(n):
            for v in self.vessels.values():
                # Explicit idealized constant velocity; no false claim of WoSB sail dynamics.
                a=math.radians(v.heading_deg);v.x+=math.sin(a)*v.velocity*self.tick_seconds
                v.z+=math.cos(a)*v.velocity*self.tick_seconds
            self.clock+=self.tick_seconds
    def apply_observed_damage(self,id,damage,*,source='user_measurement'):
        if source not in ('user_measurement','test_fixture'):raise ValueError('Only explicit observations are allowed')
        value=float(damage)
        if not math.isfinite(value) or value<0:raise ValueError('Invalid observed damage')
        v=self.vessels[id];before=v.hp;v.hp=max(0.,v.hp-value)
        event={'time':round(self.clock,5),'target':id,'damage':before-v.hp,'source':source,'status':'observed'}
        self.events.append(event);return event
    def snapshot(self):
        return {'format':'wosb-local-sandbox-1','clock':round(self.clock,5),
                'physics_status':'idealized_testbed_not_official_WoSB','damage_status':'observations_only',
                'vessels':[asdict(v) for v in self.vessels.values()],'events':self.events[:]}
    def save(self,path):
        from pathlib import Path
        dest=Path(path);dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_text(json.dumps(self.snapshot(),indent=2),encoding='utf-8')
