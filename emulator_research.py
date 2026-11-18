"""Local, *offline* planning scaffold for an independent WoSB rules emulator.

This is not an authentic game server, protocol implementation or substitute
for the missing server-authoritative rules. It deliberately refuses to assert
unknown damage or networking behavior. No external sockets are opened.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import json

CAPABILITIES = {
    'ship_catalog': {'status':'client_static', 'needed':'Versioned ships and equipment records'},
    'ship_meshes': {'status':'partially_reconstructed', 'needed':'Validated model and collision transforms'},
    'sailing': {'status':'client_partial', 'needed':'Server tick/update and modifier tests'},
    'damage': {'status':'server_unverified', 'needed':'Collision-to-DamageData calculation and calibrated shot tests'},
    'inventory': {'status':'schema_candidates', 'needed':'Player inventory state and observable update rules'},
    'protocol': {'status':'unidentified', 'needed':'Consented gameplay recordings, framing, messages and schema validation'},
    'authentication': {'status':'out_of_scope', 'needed':'No attempt to reproduce or bypass official authentication'},
}

@dataclass
class Observation:
    name: str
    game_build: str
    kind: str
    input: dict = field(default_factory=dict)
    expected: dict = field(default_factory=dict)
    evidence: str = ''
    status: str = 'observed'


def validate_observation(data):
    if not isinstance(data,dict):raise ValueError('Observation must be a mapping')
    if not data.get('name') or not data.get('game_build'):
        raise ValueError('Every observation requires a name and client build')
    if data.get('status','observed') not in ('observed','client_verified','experimental'):
        raise ValueError('Observation status must describe its evidence')
    for key in ('input','expected'):
        if not isinstance(data.get(key,{}),dict):raise ValueError(key+' must be an object')
    for key in ('password','token','cookie','session_key'):
        if key in json.dumps(data).lower():raise ValueError('Do not save credentials or session data in fixtures')
    return Observation(**{k:data[k] for k in Observation.__dataclass_fields__ if k in data})


def create_research_manifest(path):
    result={'format':'wosb-offline-emulator-research-1',
            'target':'independent local simulation based on recovered evidence',
            'capabilities':CAPABILITIES,'observations':[],
            'warning':'Not a working WoSB server. No official network protocol or authoritative damage formula reconstructed.'}
    target=Path(path);target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result
