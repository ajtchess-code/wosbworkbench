"""Evidence-aware WoSB combat scenarios, not invented server damage rules.

Composes only code-derived client getters, catalog values and independently
measured shot results. Camera direction can yield exact geometric obliquity for
an identified triangle; there is NO implied server-side multiplier.
"""
from __future__ import annotations
import math
from mechanics_verified import client_armor, EVIDENCE, client_sail_damage_energy


def unit(vector):
    if len(vector)!=3:raise ValueError('Expected three-dimensional vector')
    values=[float(x) for x in vector]
    if not all(math.isfinite(x) for x in values):raise ValueError('Non-finite vector')
    norm=math.sqrt(sum(x*x for x in values))
    if norm<=1e-12:raise ValueError('Zero direction vector')
    return tuple(x/norm for x in values)


def incoming_direction(bearing_deg, elevation_deg):
    """Local ship space: +X starboard, +Z bow, +Y up. Bearing 0° is +Z.

    Represents direction *from target toward attacker*. A projectile travels
    in the opposite direction. It is not inferred from in-game ship axes.
    """
    bearing=math.radians(float(bearing_deg));elev=math.radians(float(elevation_deg))
    return unit((math.sin(bearing)*math.cos(elev), math.sin(elev), math.cos(bearing)*math.cos(elev)))


def obliquity_deg(normal, toward_attacker):
    normal=unit(normal);direction=unit(toward_attacker)
    alignment=min(1,max(0,abs(sum(n*d for n,d in zip(normal,direction)))))
    return math.degrees(math.acos(alignment))


def angle_grid(normals, bearings=range(0,360,30), elevation=0):
    """Real geometry angle exposures. Input normals must originate from a decoded mesh."""
    values=[]
    for bearing in bearings:
        attack=incoming_direction(bearing,elevation)
        angles=[obliquity_deg(n,attack) for n in normals]
        values.append({'bearing_degrees':bearing,'mean_obliquity_degrees':round(sum(angles)/len(angles),2) if angles else None,
                       'sample_count':len(angles)})
    return {'samples':values,'status':'geometry_only_not_hp_damage'}


def describe_shot(ship, cannon, ammo, *, bearing=0,elevation=0,distance=150,hit_normal=None,
                  pat_armor=None,p_armor=0,m_armor=0,all_stat_fine=0,observed_damage=None,sails_penetrated=None):
    """Return independently evidenced stages without substituting unknown formulas."""
    distance=float(distance)
    if not math.isfinite(distance) or distance<0:raise ValueError('Range must be finite and nonnegative')
    result={'ship':ship.get('EnglishName') or ship.get('Name') or str(ship.get('ID','Unknown')),
      'cannon':cannon.get('EnglishName') or str(cannon.get('ID','Unknown')),
      'ammo':ammo.get('EnglishName') or str(ammo.get('ID','Unknown')),
      'firing':{'distance':distance,'bearing':float(bearing),'elevation':float(elevation),
                'toward_attacker':incoming_direction(bearing,elevation)},
      'catalog_properties':{'ship_health':ship.get('Health'), 'ship_armor_field':ship.get('Armor'),
                'cannon_penetration':cannon.get('Penetration'),'cannon_poundage':cannon.get('Poundage'),
                'ammo_penetration':ammo.get('Penetration'),'ammo_damage_factor':ammo.get('DamageFactor'),
                'ammo_sail_factor':ammo.get('DamageToSailes')},
      'damage':{'hp':None,'penetration':None,'ricochet':None,'sail_damage':None,'mortar_damage':None,
                'barrel_damage':None,'status':'unresolved_server_hit_resolution'},
      'evidence':{'armor':EVIDENCE['armor'],'notes':['Client catalog is not proof of final damage',
                   'Unverified modifiers are deliberately not multiplied into guessed HP']}}
    if hit_normal is not None:
        result['firing']['impact_obliquity_degrees']=round(obliquity_deg(hit_normal,result['firing']['toward_attacker']),3)
    if sails_penetrated is not None:
        result['client_sail_energy']=client_sail_damage_energy(sails_penetrated)
    if pat_armor is not None:
        result['client_armor']=client_armor(pat_armor,all_stat_fine=all_stat_fine,p_armor=p_armor,m_armor=m_armor)
    if observed_damage is not None:
        value=float(observed_damage)
        if not math.isfinite(value) or value<0:raise ValueError('Invalid observed damage')
        result['damage']['observed_hp']=value
        result['damage']['observed_status']='measured_user_supplied_not_predicted'
    return result
