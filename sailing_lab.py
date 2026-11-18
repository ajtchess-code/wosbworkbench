"""Sailing research built from explicitly recovered Common.dll IL.

The laboratory charts one isolated, reproducible wind-rose *component*, not
complete player speed. Values and calls were extracted from the v3.1 code
archive; the server may apply additional physics and balancing.
"""
from __future__ import annotations

import json
import math

WIND_SOURCES = {
    'WindingDotAtAngle': 'Common.dll 0x060027B5',
    'ComputeWindingDot': 'Common.dll 0x060027B4',
    'SpeedByWind': 'Common.dll 0x060027B6',
    'ComputeWindEffectivity': 'Common.dll 0x06002764',
}

def winding_dot_at_angle(degrees: float) -> float:
    """Derived from WindingDotAtAngle + ComputeWindingDot IL, angle in degrees.

    RotateVector2(UnitX, angle), normalize(rotated + 0.75 * UnitX), dot(UnitX).
    Degenerate length (if any) is avoided by strict 0.75 constant.
    """
    theta = math.radians(float(degrees))
    x = math.cos(theta) + .75
    y = math.sin(theta)
    return x / math.hypot(x, y)

def wind_speed_component(degrees: float) -> float:
    """WindRose.SpeedByWind(WindingDotAtAngle(angle)); NOT full ship speed."""
    return 1.8 * (0.5 + 0.5 * winding_dot_at_angle(degrees))

def rose_records(db, build='Game'):
    rows = db.conn.execute('''SELECT raw_json, source_root FROM records
           WHERE dataset='WindRoses' ORDER BY CASE source_root WHEN ? THEN 0 WHEN 'Steam' THEN 1 ELSE 2 END, id''',(build,)).fetchall()
    builds = {r['source_root'] for r in rows}
    chosen = build if build in builds else ('Steam' if 'Steam' in builds else (rows[0]['source_root'] if rows else None))
    return [json.loads(r['raw_json']) for r in rows if r['source_root']==chosen]

def seed_sailing_pages(db, build='Game'):
    roses = rose_records(db, build)
    lines = [
        '# Sailing, Wind & Navigation — code and data research',
        '',
        '**Research status:** The wind-rose components below are reconstructed from client IL. The final ship-speed and steering formulas are **not yet verified**.',
        '',
        '## What we can calculate now',
        '',
        '`WindingDotAtAngle(theta)` rotates a unit vector by theta, adds `0.75 × UnitX`, normalizes, and takes the dot product with UnitX.',
        '',
        '`w(theta) = (cos(theta) + 0.75) / sqrt((cos(theta) + 0.75)^2 + sin(theta)^2)`',
        '',
        '`SpeedByWind(w) = 1.8 × (0.5 × w + 0.5)`',
        '',
        'This is a **dimensionless internal component**, not knots, velocity or a verified normalized ship-speed multiplier. '
        '`ShipPhysics.ComputeWindEffectivity` applies further conditions, including unique wind roses, forewind penalties, hardness, special ship types and wind-ignoring states.',
        '',
        '## Wind-rose configuration records',
        '',
    ]
    if roses:
        for r in roses:
            data={k:v for k,v in r.items() if k not in ('EnglishDescription','EnglishName','SourceRecord')}
            lines.extend(['### '+str(r.get('Name','Unknown')),'',
             '```json',json.dumps(data,ensure_ascii=False,indent=2),'```',
             'Source: `'+str(r.get('Source','WindRoses'))+'`, client record '+str(r.get('SourceRecord','?')), ''])
    else:
        lines.extend(['No WindRoses rows imported yet. Import the v3.1 report ZIP.', ''])
    lines.extend([
        '## Mechanics to establish',
        '- Base ship speed versus `InternalBaseSpeed`, sail health, mast damage and hull modifications.',
        '- Wind power, wind direction, green wind zones, tacking, points of sail and turning inertia.',
        '- Effects of weather, ship stiffness/hardness, unique sail profile and captain/guild/equipment perks.',
        '- Conditions for special types that ignore wind or use altered physics.',
        '- Client/server agreement and actual speed units. Run controlled trials with one variable at a time.',
        '',
        '## Method references',
    ])
    lines += [f'- `{name}` — `{source}`' for name,source in WIND_SOURCES.items()]
    lines += ['', '## Evidence policy', 'Only the internal component above is currently supported by the extracted IL. Do not extrapolate a whole ship-speed formula without tracing callers and validating observations.']
    db.upsert_article('research-sailing-wind-physics','Sailing and wind — recovered formulas','Sailing, weather & navigation',
                      '\n'.join(lines),'client-code','Common.dll; WindRoses','needs-review',preserve_edited=True)
    db.conn.commit()
    return len(roses)
