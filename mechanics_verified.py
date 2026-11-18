"""Client-code-derived mechanics with explicit provenance and input assumptions.

Never classify a client-side value as the server's final HP damage. Inputs are
raw GetBonus results, not GUI percentage strings. All formulas are taken from
specific IL methods in the locally extracted client archive.
"""
from __future__ import annotations
from math import isfinite

EVIDENCE = {
    'armor': {'assembly':'Common.dll', 'token':'0x06001f6f',
              'method':'Common.Resources.ShipDynamicInfo::get_Armor',
              'formula':'BasicArmor * (1 + GetBonus(5, true)) + GetBonus(13, true)',
              'scope':'verified client property; not server-final damage'},
    'base_armor': {'assembly':'Common.dll', 'token':'0x06001ee8',
                   'method':'Common.Resources.PlayerShipDynamicInfo::get_BasicArmor',
                   'formula':'CraftFrom.PatArmor * (1 - AllStatFine)',
                   'scope':'verified for player ship dynamic info'},
    'bow_reduction_bonus': {'assembly':'Common.dll', 'token':'0x06001f95',
                            'method':'Common.Resources.ShipDynamicInfo::get_ReduceDamageToNose',
                            'formula':'GetBonus(18, true)',
                            'scope':'value access only; downstream HP multiplier unverified'},
    'sail_damage_energy': {'assembly':'Common.dll','token':'0x06002533',
                            'method':'Common.Game.CannonBall::SailDamageEnergy',
                            'formula':'hit_count < 3 ? 1 / (1 + hit_count) : 0',
                            'scope':'verified client method expression; final sail HP application not proven'},
    'cannon_penetration_getter': {'assembly':'Common.dll','token':'0x06001d32',
                            'method':'Common.Resources.CannonGameInfo::get_Penetration',
                            'formula':'Editor_Penetration.HasValue ? Editor_Penetration.Value : fallback_field',
                            'scope':'verified client property selection; penetration resolution unknown'},
    'penetration_bonus': {'assembly':'Common.dll','token':'0x06001f7c',
                          'method':'Common.Resources.ShipDynamicInfo::get_WeaponPenetrationBonus',
                          'formula':'GetBonus(54, true)',
                          'scope':'value access only; interaction with projectile penetration unverified'},
}


def _float(value,label):
    try: val=float(value)
    except (TypeError,ValueError): raise ValueError(label+' must be numeric') from None
    if not isfinite(val):raise ValueError(label+' must be finite')
    return val


def client_armor(pat_armor, *, all_stat_fine=0.0, p_armor=0.0, m_armor=0.0):
    """Evaluate both chained IL getters, assuming inputs are raw client values.

    ``pat_armor`` corresponds to CraftFrom.PatArmor (not necessarily the mined
    ShipsToPlay.Armor field). ``p_armor`` is raw GetBonus(5,true) as a fraction;
    ``m_armor`` is raw GetBonus(13,true). The caller must identify these values.
    """
    base=_float(pat_armor,'PatArmor');fine=_float(all_stat_fine,'AllStatFine')
    p=_float(p_armor,'PArmor');m=_float(m_armor,'MArmor')
    if base<0:raise ValueError('PatArmor cannot be negative')
    if not 0<=fine<=1:raise ValueError('AllStatFine must be a fraction between 0 and 1')
    result_base=base*(1-fine)
    result=result_base*(1+p)+m
    return {'basic_armor':result_base,'client_armor':result,
            'formula_sources':[EVIDENCE['base_armor'],EVIDENCE['armor']],
            'input_note':'PatArmor and bonus values are supplied inputs; catalog Armor might not equal CraftFrom.PatArmor',
            'authoritative_damage':False}


def client_sail_damage_energy(hit_count):
    """Exact extracted CannonBall.SailDamageEnergy client method for nonnegative integer input."""
    if not isinstance(hit_count,int) or hit_count<0:raise ValueError('Expected nonnegative hit count')
    return {'sail_damage_energy':1.0/(1+hit_count) if hit_count<3 else 0.0,
            'source':EVIDENCE['sail_damage_energy'],'status':'verified_client_method_not_final_sail_HP'}


def client_cannon_penetration(editor_penetration, fallback_penetration):
    """The client getter uses the editor override when present."""
    if editor_penetration is None:result=_float(fallback_penetration,'Fallback penetration')
    else:result=_float(editor_penetration,'Editor penetration')
    return {'client_penetration_field':result,'source':EVIDENCE['cannon_penetration_getter'],
            'status':'verified_client_field_selection_not_penetration_test'}
