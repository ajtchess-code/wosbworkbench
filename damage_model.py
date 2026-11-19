"""How World of Sea Battle applies damage, ported from the shared Common.dll code.

Every rule here is a line-by-line port of code in your decompiled client
(``Common/Common/Game/Ship.cs``, ``ShipFirstHp.cs``, ``DamageData.cs``,
``CannonBall.cs``, ``MortarShot.cs``, ``Resources/ShipDynamicInfo.cs``,
``Resources/ShipStaticInfo.cs``). Each function names its source.

What the client does NOT contain: the server computes ``HealthDamage`` for a
cannonball hit (penetration vs armor, distance, angle) and sends the result in
``OnBallsCollisionMsg`` / ``OnShipsSomeDamageMsg``. That formula is server-side;
``damage_hypotheses`` keeps candidate models for it, to be calibrated against
measured hits. This module covers everything that happens with a DamageData once
it exists: HP, sails, crew, crits, fire, flooding and sinking.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import IntEnum, IntFlag

SOURCE = 'Common.dll (decompiled locally with ILSpy)'


class DamageID(IntEnum):
    """Common.Game.DamageID — what caused the damage."""
    Other = 0
    Burning = 1
    CannonBall = 2
    Collision = 3
    PowderKeg = 4
    MortarShot = 5
    FireArea = 6
    FalkonetBall = 7


class Flags(IntFlag):
    """Common.Game.SpecificDamageFlags (ushort on the wire)."""
    NONE = 0
    SingleSailDamage = 0x1
    BoardingHookConnected = 0x2
    CorpusCritical = 0x4
    CannonCritical = 0x8
    BurningCritical = 0x10
    TowerSource = 0x20
    CreateMicroburning = 0x40
    SternDamage = 0x80
    CrewDamage = 0x100
    DebufSpeed = 0x200
    PvPDamage = 0x400
    IsHealthDamageReduced = 0x800
    RemoveCannonBall = 0x1000
    TotalSailDamage = 0x2000
    Fireworks = 0x4000
    FriendlyFire = 0x8000


class HitboxType(IntEnum):
    """Common.Resources.HitboxType."""
    Corpus = 0
    Mast = 1
    Sail = 2
    ServerOnly_SailClosed = 3


# ShipFirstHp constants
FLOODING_TIME_MS = 13000.0          # floodingTimeMs: sinking timeline once HP reaches 0
BIG_BURNING_NO_RETURN_MS = 12000.0  # bigBurningNoReturnPointMs
DEFAULT_BIG_HOLE_SEC = 10.0         # defaultBigHoleDurationSec
SHIP_WORLD_SCALE = 0.3              # model units -> world units (ShipStaticInfo CorpusHalf*)
MAX_SAIL_HITBOXES_PER_BALL = 3      # CannonBall.MaxSailHitboxesCount


@dataclass
class DamageData:
    """Common.Game.DamageData — one damage event as the server sends it."""
    target_uid: int = 0
    source_uid: int = -1
    source: DamageID = DamageID.Other
    health_damage: float = 0.0
    collision_node_id: int = 0
    ship_space_point: tuple = (0.0, 0.0, 0.0)
    flags: Flags = Flags.NONE
    burning_type: int = 0
    crit_corpus_time_sec: float = 0.0
    crew_damage: list = field(default_factory=list)   # one byte (unit type id) per crew member killed
    crit_cannon: int = 0
    damage_to_sails: float = 0.0

    @property
    def total_crew_kills(self):
        """DamageData.TotalCrewKills."""
        return len(self.crew_damage) if self.flags & Flags.CrewDamage else 0


@dataclass
class ShipState:
    """The parts of ShipDynamicInfo / ShipFirstHp that damage touches."""
    max_hp: float
    hp: float = None
    sail_strength: list = None        # HitboxSailsStrength[], 1.0 = intact
    sail_weights: list = None         # SailHitbox.Weight per strength index (sum to 1)
    sinking_ms: float = 0.0           # ShipFirstHp.A — >0 once HP hit zero; 13000 = sunk
    flooding_offset_ms: float = 0.0   # ShipFirstHp.c
    temporal_strength: float = 0.0
    march_bonus_speed: float = 0.0
    corpus_crit_sec: float = 0.0
    burning_type: int = 0
    burning: bool = False
    microfires: int = 0
    broken_cannons: list = field(default_factory=list)
    crew_lost: list = field(default_factory=list)
    destroyed: bool = False
    destroyed_by_flooding: bool = False
    is_player: bool = True
    education_map: bool = False
    log: list = field(default_factory=list)

    def __post_init__(self):
        if self.hp is None:
            self.hp = float(self.max_hp)
        if self.sail_weights is None:
            n = len(self.sail_strength or []) or 1
            self.sail_weights = [1.0 / n] * n
        if self.sail_strength is None:
            self.sail_strength = [1.0] * len(self.sail_weights)

    @property
    def hp_factor(self):
        return self.hp / self.max_hp if self.max_hp else 0.0

    @property
    def sails_hp(self):
        """FirstSailHP — weighted sail strength (ShipDynamicInfo.HitboxSailsStrengthCacheUpdate)."""
        if not self.sail_strength:
            return 1.0
        return sum(s * w for s, w in zip(self.sail_strength, self.sail_weights))

    @property
    def flooding_factor(self):
        """ShipFirstHp.FloodingFactor = (A - c) / 13000, or 1 once sunk by flooding."""
        return 1.0 if self.destroyed_by_flooding else (self.sinking_ms - self.flooding_offset_ms) / FLOODING_TIME_MS


# ------------------------------------------------------------- HP pool

def hp_damage(state, amount):
    """ShipFirstHp.Damage: returns HP actually removed.

    While sinking (A > 0) further damage does nothing. Below 0.5 HP the ship is
    treated as 0; reaching 0 starts the 13 s flooding timeline with HP held at 1.
    """
    if state.sinking_ms > 0:
        return 0.0
    state.temporal_strength = max(0.0, state.temporal_strength - amount)
    removed = min(amount, state.hp)
    state.hp = 0.0 if state.hp - removed < 0.5 else state.hp - removed
    if state.hp <= 0:
        state.sinking_ms = 0.01
        state.hp = 1.0
    return removed


def accelerate_flooding(state, hp_fraction=None):
    """ShipFirstHp.A(float): a hit on a sinking ship pushes the timeline 800 ms forward (max 12 999)."""
    if state.sinking_ms == 0:
        raise ValueError('ship is not sinking')
    new = min(12999.0, state.sinking_ms + 800.0)
    state.flooding_offset_ms = new - state.sinking_ms
    state.sinking_ms = new


def sink_now(state):
    """ShipFirstHp.A(): immediate destruction (powder keg/mortar/stern hits on a sinking ship)."""
    state.destroyed_by_flooding = False
    state.hp = 0.0
    state.destroyed = True


def apply_damage(state, data, source_ship_uid=-1):
    """Ship.MakeDamage — apply one DamageData to a ship, in the client's order.

    Returns a dict describing what changed. Raises ValueError for negative/NaN
    values exactly as the client throws ArgumentException.
    """
    if data.health_damage < 0 or data.damage_to_sails < 0 or math.isnan(data.health_damage) or math.isnan(data.damage_to_sails):
        raise ValueError('negative or NaN damage (client throws ArgumentException)')
    if state.destroyed:
        return {'ignored': 'already destroyed'}
    before = {'hp': state.hp, 'sails': state.sails_hp}
    amount = data.health_damage
    # Tutorial (education) map scaling.
    if state.education_map and state.is_player:
        amount = amount / 1.5
    elif state.education_map and data.flags & Flags.PvPDamage:
        amount = amount * 1.2
    removed = hp_damage(state, amount)
    events = []
    if state.flooding_factor > 0:
        instant = (data.source in (DamageID.PowderKeg, DamageID.MortarShot)
                   or (data.source == DamageID.Burning and state.burning)
                   or data.flags & (Flags.SternDamage | Flags.Fireworks)
                   or (state.education_map and state.max_hp < 500))
        if instant:
            sink_now(state); events.append('instant sink while flooding')
        if data.source == DamageID.Collision and source_ship_uid > 0 and not state.destroyed:
            accelerate_flooding(state, data.health_damage / state.max_hp); events.append('ram pushed flooding +800 ms')
    # Damage slows march (sprint) mode.
    state.march_bonus_speed = max(0.0, state.march_bonus_speed - data.health_damage / (1 + state.hp) * 100 - data.damage_to_sails * 100)
    if data.flags & Flags.SingleSailDamage and state.sail_strength:
        i = sail_index_for_node(state, data.collision_node_id)
        state.sail_strength[i] = max(0.0, state.sail_strength[i] - data.damage_to_sails)
        events.append(f'sail {i} -{data.damage_to_sails:.3f}')
    elif data.flags & Flags.TotalSailDamage and state.sail_strength:
        n = len(state.sail_strength)
        for i in range(n):
            weight_mul = state.sail_weights[i] * n   # SailHitbox.WeigthMul
            state.sail_strength[i] = max(0.0, state.sail_strength[i] - data.damage_to_sails / weight_mul)
        events.append(f'all sails -{data.damage_to_sails:.3f} (weighted)')
    if data.flags & Flags.DebufSpeed:
        events.append('speed debuff')
    if data.flags & Flags.CorpusCritical:
        state.corpus_crit_sec = data.crit_corpus_time_sec; events.append(f'hull breach {data.crit_corpus_time_sec:g}s')
    if data.flags & Flags.CreateMicroburning:
        state.microfires += 1; events.append('micro-fire started')
    if data.flags & Flags.BurningCritical:
        state.burning = True; state.burning_type = data.burning_type; events.append('large fire')
    if data.flags & Flags.CrewDamage:
        state.crew_lost += list(data.crew_damage); events.append(f'{len(data.crew_damage)} crew hurt/killed')
    if data.flags & Flags.CannonCritical:
        state.broken_cannons.append(data.crit_cannon); events.append(f'cannon {data.crit_cannon} broken')
    result = {'hp_before': before['hp'], 'hp_after': state.hp, 'hp_removed': removed,
              'sails_before': before['sails'], 'sails_after': state.sails_hp,
              'sinking': state.sinking_ms > 0, 'destroyed': state.destroyed, 'events': events}
    state.log.append({'source': data.source.name, 'flags': str(data.flags), **result})
    return result


def tick_flooding(state, seconds, inertion_factor=1.0):
    """Advance the sinking timeline (ShipFirstHp update): A += ms * InertionFactor; sunk at 13 000 ms."""
    if state.sinking_ms <= 0 or state.destroyed:
        return state
    ms = seconds * 1000.0
    state.temporal_strength = 0.0
    state.flooding_offset_ms = max(0.0, state.flooding_offset_ms - ms * 2)
    state.sinking_ms += ms * inertion_factor
    if state.sinking_ms > FLOODING_TIME_MS:
        state.sinking_ms = FLOODING_TIME_MS
        state.destroyed_by_flooding = True
        state.destroyed = True
    return state


def restore_hp(state, amount):
    """Ship.RestoreHp / ShipFirstHp.Restore: no healing while sinking; capped at MaxHp."""
    if amount < 0:
        raise ValueError('negative repair')
    if state.destroyed or state.sinking_ms:
        return 0.0
    gained = min(state.max_hp - state.hp, amount)
    state.hp = min(state.max_hp, state.hp + amount)
    state.temporal_strength = max(0.0, state.temporal_strength - gained)
    return gained


def restore_sails(state, amount):
    """Ship.RestoreSails: spread over damaged sails, divided by each sail's weight."""
    damaged = sum(1 for s in state.sail_strength if s < 1)
    if damaged == 0 or state.destroyed:
        return state
    for i, w in enumerate(state.sail_weights):
        state.sail_strength[i] = min(1.0, state.sail_strength[i] + amount / (damaged * w))
    return state


def sail_index_for_node(state, node_id):
    """Node table: 0 = corpus, then sails (static then animated), then masts (ShipStaticInfo)."""
    i = int(node_id) - 1
    if not 0 <= i < len(state.sail_strength):
        raise ValueError(f'node {node_id} is not a sail hitbox')
    return i


# ------------------------------------------------------------- per-hit factors

def sail_damage_energy(passed_sail_hitboxes):
    """CannonBall.SailDamageEnergy: a ball keeps 1/(1+n) energy after n sails; none after 3."""
    n = int(passed_sail_hitboxes)
    return 1.0 / (1.0 + n) if n < MAX_SAIL_HITBOXES_PER_BALL else 0.0


def damage_to_sail_factor(sail_weight, *, sail_protection=0.0, reduce_damage=0.0, sail_closed=False):
    """ShipDynamicInfo.DamageToSailFactorFromNodeID.

    max(PSailProtection, PReduceDamage) reduces it; a closed (furled) sail takes
    at most 30 %. Divided by the sail's weight, so small sails lose strength faster.
    """
    protection = max(sail_protection, reduce_damage)
    return max(0.0, min(0.3 if sail_closed else 1.0, 1.0 - protection)) / sail_weight


def mortar_splash_factor(distance_to_hitbox, splash_radius):
    """MortarShot.ComputeDamageFactorTo(Ship): 1.0 inside the hitbox, then 0.1 + 0.9·sqrt(1 - d/r).

    ``distance_to_hitbox`` is Ship.DistanceToHitbox (the client subtracts 1 m first).
    """
    d = distance_to_hitbox - 1.0
    if d <= 0:
        return 1.0
    return 0.1 + 0.9 * math.sqrt(1.0 - min(1.0, max(0.0, d / splash_radius)))


def reduce_damage_cap(p_reduce_damage):
    """ShipDynamicInfo.B(): PReduceDamage is capped at 99 %."""
    return min(0.99, p_reduce_damage)


def cannons_distance_cap(m_cannons_distance):
    """ShipDynamicInfo.a(): flat cannon-range bonus capped at +50."""
    return min(50.0, m_cannons_distance)


# ------------------------------------------------------------- ship stat getters

def max_hp(basic_hp, p_health=0.0, m_health=0.0):
    """ShipDynamicInfo.MaxHp = (int)(BasicHp·(1+PHealth) + MHealth). Bonuses as fractions."""
    return float(int(basic_hp * (1 + p_health) + m_health))


def armor(basic_armor, p_armor=0.0, m_armor=0.0):
    """ShipDynamicInfo.Armor = BasicArmor·(1+PArmor) + MArmor."""
    return basic_armor * (1 + p_armor) + m_armor


def mobility(basic, m_bonus=0.0, p_bonus=0.0, *, hp_factor=1.0, low_hp_bonus=0.0, sails_hp=1.0):
    """ShipDynamicInfo.Mobility: below 50 % HP adds MobilityWithLowHp; under 95 % sails lerps down to ×0.8."""
    value = basic + m_bonus + p_bonus * basic + (low_hp_bonus if hp_factor < 0.5 else 0.0)
    if sails_hp < 0.95:
        t = min(1.0, max(0.0, (sails_hp - 0.8) / 0.15))
        value *= 0.8 + 0.2 * t
    return value


def big_fire_flare(process_ms, burning_type, mending_level=0.0):
    """ShipFirstHp.BigBurningFlareUpLevel — intensity of a large fire.

    burning_type is the client's PredefinedBurningType: 0 Infinite, 1 InfiniteAllowMending, 2 Finite
    (finite fires burn out at 12 s).
    """
    if process_ms == 0:
        return 0.0
    if burning_type == 2:
        x = process_ms / BIG_BURNING_NO_RETURN_MS
        return x * (1 - x) * 4 * 0.6
    if burning_type == 0:
        return min(1.0, process_ms / 4000.0)
    extra = 0.0 if process_ms < BIG_BURNING_NO_RETURN_MS else (process_ms - BIG_BURNING_NO_RETURN_MS) / 2000.0
    return min(max(0.01, 1 - mending_level), (process_ms / BIG_BURNING_NO_RETURN_MS) ** 1.7 * 0.7 + extra)

def collision_damage_event(target_uid, source_uid, damage, *, corpus_crit=False, make_burning=False,
                           upgrade_destroy_flooding=False, friendly_fire=False):
    """Ship.MakeCollisionDamage: how a ram becomes a DamageData (crit = 10 s hull breach)."""
    flags = Flags.NONE
    if corpus_crit:
        flags |= Flags.CorpusCritical
    if make_burning:
        flags |= Flags.BurningCritical
    if upgrade_destroy_flooding:
        flags |= Flags.SternDamage
    if friendly_fire:
        flags |= Flags.FriendlyFire
    return DamageData(target_uid=target_uid, source_uid=source_uid, source=DamageID.Collision,
                      health_damage=damage, flags=flags, crit_corpus_time_sec=10.0 if corpus_crit else 0.0,
                      burning_type=1 if make_burning else 0)


def simulate(max_hp_value, hits, *, sail_weights=None, education_map=False, is_player=True, flood_seconds=0.0):
    """Run a list of hits (dicts of DamageData fields) and return the timeline."""
    state = ShipState(max_hp=max_hp_value, sail_weights=sail_weights, education_map=education_map, is_player=is_player)
    for h in hits:
        h = dict(h)
        if 'source' in h and not isinstance(h['source'], DamageID):
            h['source'] = DamageID[h['source']] if isinstance(h['source'], str) else DamageID(int(h['source']))
        if 'flags' in h and not isinstance(h['flags'], Flags):
            raw = h['flags']
            h['flags'] = Flags(int(raw)) if not isinstance(raw, (list, tuple)) else _flags(raw)
        data = DamageData(**h)
        apply_damage(state, data, source_ship_uid=data.source_uid)
    if flood_seconds:
        tick_flooding(state, flood_seconds)
    return {'final_hp': state.hp, 'sails': state.sails_hp, 'sinking': state.sinking_ms > 0,
            'destroyed': state.destroyed, 'flooding_factor': state.flooding_factor, 'log': state.log}


def _flags(names):
    value = Flags.NONE
    for n in names:
        value |= Flags[n]
    return value


REFERENCE = {
    'DamageData wire layout': 'see source_schemas.describe(DamageData) — fields 8–12 only appear when their flag bit is set',
    'Hitbox node ids': '0 = corpus; 1..S = sails (static then animated, SailStrengthIndex order); then masts',
    'Ship scale': 'model units × 0.3 = world units (CorpusHalfLength = FinalLength × 0.3 × 0.5)',
    'Server-only': 'HealthDamage for ball hits, crit and crew-loss rolls, fire ignition chances',
}
