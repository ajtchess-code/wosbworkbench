#!/usr/bin/env python3
"""Run reproducible, offline ship-state research fixtures; no sockets or game login."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from offline_emulator import SandboxWorld


def simulate_fixture(data):
    if not isinstance(data,dict):raise ValueError('Expected fixture object')
    world=SandboxWorld(tick_seconds=float(data.get('tick_seconds',0.1)),
                       wind_bearing=float(data.get('wind_bearing',0)))
    for ship in data.get('vessels',[]):
        world.spawn(str(ship['id']),str(ship.get('name') or ship['id']),float(ship['max_hp']),
                    x=ship.get('x',0),z=ship.get('z',0),heading_deg=ship.get('heading_deg',0))
    for action in data.get('events',[]):
        op=action.get('action')
        if op=='controls':world.set_controls(str(action['id']),speed=action.get('speed'),
                           heading_deg=action.get('heading_deg'),sails=action.get('sails'))
        elif op=='step':world.step(int(action.get('ticks',1)))
        elif op=='observed_damage':world.apply_observed_damage(str(action['id']),action['damage'],
                                source=action.get('source','user_measurement'))
        else:raise ValueError('Unsupported fixture action: '+str(op))
    return world.snapshot()


def main():
    p=argparse.ArgumentParser(description='Offline WoSB-inspired state fixture (not a game server)')
    p.add_argument('fixture');p.add_argument('--output',required=True)
    args=p.parse_args()
    source=Path(args.fixture)
    if source.stat().st_size>2*1024*1024:raise ValueError('Fixture too large')
    result=simulate_fixture(json.loads(source.read_text(encoding='utf-8')))
    destination=Path(args.output);destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('Saved non-networked simulation snapshot:',destination)

if __name__=='__main__':main()
