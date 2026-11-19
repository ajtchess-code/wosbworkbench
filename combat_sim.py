"""Combat, sailing, boarding and fire rules ported from the WoSB client (Common.dll).

Each function names the client code it follows. Where a value is decided only
by the server (cannonball HealthDamage, crit/ignition rolls), the function
takes it as an input or says it is inferred.

Units: world units (the client's metres-ish), seconds, degrees unless noted.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

# --------------------------------------------------------------- client hash

_E = 2.71828182846
_SQ3 = 1.73205080757


def _i32(v):
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v >= 1 << 31 else v


def hash01(h):
    """TheraEngine HashHelper.greater(int): deterministic pseudo-random in [0, 1)."""
    h = int(h)
    sq = _i32(h * h)                       # C# int multiply wraps
    inner = math.fmod(math.fmod(h * 24.232 + sq, _E), _SQ3)
    return math.fmod(h * inner, 1.0)


def gun_spread_table():
    """CannonCommon static table: 128 (yaw, pitch) offsets; both from the same hash, so correlated."""
    return [(-0.1 + 0.2 * hash01(516515 + i), -0.125 + 0.25 * hash01(516515 + i)) for i in range(128)]


SPREAD = gun_spread_table()


# --------------------------------------------------------------- ballistics

@dataclass
class Shot:
    sight_distance: float
    sight_height: float


def shot_data(cannon_max_distance, aim_y, curve_multiplier=1.0, ammo_distance_factor=1.0):
    """Functions.GetData + CannonCollection.SelectAvailableCannons range scaling.

    ``aim_y`` is the sight's vertical normal component (the elevation the player sets).
    Returns the ball's ground range and arc height.
    """
    d = cannon_max_distance - 3.0
    y = aim_y - 0.1
    val = max(0.0, (0.6 + y) * 2.0) ** 5
    sight_distance = max(20.0, 1.0 * d * (1.25 * min(0.8, val)))
    sight_height = (1 + min(6.0, max(0.0, (0.1 + y * 0.6) * 80))) * (sight_distance / max(100.0, d)) * curve_multiplier
    sight_height = max(0.2, sight_height)
    sight_distance = min(sight_distance, cannon_max_distance)
    return Shot(sight_distance * ammo_distance_factor, sight_height)


def ball_height(t, shot, cannon_y=0.0):
    """Functions.GetBallHeight: height at fraction ``t`` (0..1) of the range."""
    amount = min(1.0, shot.sight_distance / 35.0)
    arc = (4 * t - 4 * t * t) * (0.5 + shot.sight_height)
    low = cannon_y - 25.0 * t / shot.sight_distance
    return low + (cannon_y + arc - low) * amount


def speed_multiplier(t, far_distance):
    """Functions.GetCannonBallSpeedMultiplier: balls slow down along the arc."""
    k = far_distance / 140.0
    return ((1 - t) ** 2 * 0.2 + 0.9) * k + (1 - k) * 0.9


def trajectory(shot, *, ball_speed=1.0, cannon_speed=1.0, cannon_y=1.5, dt=1 / 60, ball_id=None, max_t=20.0):
    """Sample a flight (CannonBall.UpdateCannonBall). Returns [(time, distance, height)] and flight time.

    Horizontal speed = 45.76 × cannon ball speed × ammo speed × speed_multiplier(t).
    """
    out = [(0.0, 0.0, cannon_y)]
    dist = 0.0; time = 0.0
    while dist < shot.sight_distance and time < max_t:
        t = dist / shot.sight_distance
        m = speed_multiplier(t, shot.sight_distance)
        if ball_id == 6:
            m = m ** 5 * 1.4
        dist += cannon_speed * dt * 45.760002 * m * ball_speed
        time += dt
        out.append((time, min(dist, shot.sight_distance), ball_height(min(1.0, dist / shot.sight_distance), shot, cannon_y)))
    return out, time


def sight_reduction(converge_elapsed_s, convergence_time_s, effective_ports, sight_speed_bonus=0.0, legacy=0.0):
    """CannonCommon.GetSightReductionBase / CannonConvergence: aim settles over time (1 = unsettled)."""
    if convergence_time_s <= 0:
        return legacy
    precision = 0.85 - min(70, effective_ports) * 0.005
    factor = 0.85 / precision / (1 + sight_speed_bonus)
    return 1 - max(0.0, min(1.0, converge_elapsed_s / max(0.001, convergence_time_s * factor)))


def scatter_factor(base_reduction, scatter, max_distance, right_side_ports, *, reduce_scatter=0.0,
                   worse_scatter=False, additional_dispersion=False, less_scatter=False, single_gun_skill=False):
    """CannonCommon.ModifySightReductionFactor (for a real shot, not the sight preview)."""
    f = base_reduction * (1.4 if worse_scatter else 1.0)
    ports = max(0.0, min(1.0, right_side_ports // 50))      # integer division in the client
    f += scatter / max_distance * (math.pi * 2) * 0.5 * (1 - reduce_scatter) * (0.6 + 0.6 * ports)
    if additional_dispersion:
        f = max(f, 0.25 + 0.15 * ports)
    if less_scatter:
        f *= 0.6
    if single_gun_skill:
        f *= 0.2
    return f


def gun_dispersion(gun_index, factor, sight_distance, sight_height, cannon_max_distance, offset_along_hull=0.0):
    """CannonCommon.FocusAndGunDispersion: (yaw offset rad, pitch offset rad, distance, height) for one gun."""
    rx, ry = SPREAD[gun_index % len(SPREAD)]
    yaw = rx * factor + 0.7 * offset_along_hull / cannon_max_distance
    pitch = ry * factor
    k = max(0.0, min(1.0, (ry + 0.125) / 0.25))
    n2 = (-0.13 + (0.06 + 0.13) * k) * factor
    return yaw, pitch, sight_distance * (1 + 120 * n2 / (20 + cannon_max_distance)), sight_height * (1 + n2)


def in_firing_arc(aim_bearing_deg, side_axis_deg, side_half_arc_deg, angle_bonus_deg=0.0):
    """CannonCommon.A(...): within the side's arc (+bonus, never under 5°)."""
    half = max(side_half_arc_deg + angle_bonus_deg, 5.0)
    d = (aim_bearing_deg - side_axis_deg + 180) % 360 - 180
    return abs(d) < half


# --------------------------------------------------------------- sailing

UNIQUE_ROSE_STATIC_IDS = {13, 25, 41, 54, 56, 5, 63}   # ShipStaticInfo ctor


def winding_dot(theta_deg):
    """dot(normalize(heading + 0.75·wind), wind); theta = angle between heading and wind direction (0 = downwind)."""
    t = math.radians(theta_deg)
    x, y = math.cos(t) + 0.75, math.sin(t)
    return x / math.hypot(x, y)


def _a(dot):
    return (dot * 0.5 + 0.5) * 1.8


NORM_REGULAR = _a(winding_dot(180 - 40.95))   # ShipPhysics static D
NORM_UNIQUE = _a(winding_dot(180 - 40.4))     # ShipPhysics static d


def hull_factors(weight_tons, static_id=None):
    """ShipStaticInfo: InertionFactor and HardnessFactor from ShipsBasics.Weight."""
    w = weight_tons * 1000.0
    inertion = 2 - max(0.0, min(1.0, (w - 30000) / 50000))
    if static_id == 56:
        inertion = 1.6
    return inertion, 2 - inertion


def wind_effectivity(theta_deg, *, unique=False, hardness=0.0, tack='right', forewind_fine_reduce=0.0,
                     ignore_wind=False, balloon=False):
    """ShipPhysics.ComputeWindEffectivity. Returns (effectivity 0..1, downwind penalty 0..1).

    ``tack``: which side the wind is on ('left' gets the unique rose's 17° advantage when beating upwind).
    """
    theta = abs((theta_deg + 180) % 360 - 180)
    eff_theta = theta
    if unique and theta > 90 and tack == 'left':
        eff_theta = max(0.0, theta - math.degrees(0.3))
    dot = winding_dot(eff_theta)
    if ignore_wind:
        return 1.0, 0.0
    if balloon:
        return max(0.0, dot), 0.0
    band = 0.00445 if unique else 0.01
    fine = max(0.0, dot - (1 - band)) / band
    n3 = _a(dot) / (NORM_UNIQUE if unique else NORM_REGULAR)
    val = n3 + ((0.15 + (1 - 0.15) * n3) - n3) * hardness
    return min(1.0, val) * ((1 - 0.3 * fine) + (1 - (1 - 0.3 * fine)) * forewind_fine_reduce), fine


# --------------------------------------------------------------- boarding

@dataclass
class UnitType:
    name: str
    damage: float          # UnitsInfo.DDamage (per 3 s loop)
    health: float          # UnitsInfo.DHealth
    capacity: float = 0.0  # UnitsInfo.DCapacity
    musketeer: bool = False


@dataclass
class Group:
    index: int
    units: dict
    total_damage: float
    hp: float
    initial_hp: float
    initial_units: int
    timer: float
    interval: float

    @property
    def health_factor(self):
        return self.hp / self.initial_hp if self.initial_hp else 0.0

    @property
    def damage_factor(self):
        """BoardingCombatVisualGroup.DamageFactor = HealthFactor ^ 0.7."""
        return self.health_factor ** 0.7


BOARDING_DURATION_S = 30.0
BOARDING_INTERVAL_S = 3.0
PROTECTION_IN = 0.2
PROTECTION_OUT = 0.2
PREPARATION_S = 4.1
PREPONDERANCE_TO_WIN = 1.5


def make_groups(crew, unit_types, unit_places):
    """BoardingCombatInstance(ship): fill groups of 16 + places/15 units, ordered by unit id."""
    size = 16 + unit_places // 15
    groups = []; cur = {}; cur_n = 0

    def close():
        nonlocal cur, cur_n
        if cur_n:
            idx = len(groups)
            dmg = sum(unit_types[u].damage * n for u, n in cur.items())
            hp = sum(unit_types[u].health * n for u, n in cur.items())
            jitter = 1 + 0.1 * (hash01(idx) - 0.5)
            groups.append(Group(idx, dict(cur), dmg, hp, hp, cur_n, BOARDING_INTERVAL_S * jitter, BOARDING_INTERVAL_S))
        cur = {}; cur_n = 0
    for uid in sorted(crew):
        n = crew[uid]
        while n > 0:
            take = min(size - cur_n, n)
            cur[uid] = cur.get(uid, 0) + take; cur_n += take; n -= take
            if cur_n >= size:
                close()
        close()
    return groups, size


@dataclass
class Side:
    name: str
    groups: list
    targets: list = field(default_factory=list)
    protected: set = field(default_factory=set)
    weight_bonus: float = 0.0

    @property
    def hp(self):
        return sum(g.hp for g in self.groups)

    @property
    def units_alive(self):
        return sum(sum(g.units.values()) for g in self.groups if g.hp > 0)


def default_targets(enemy, *, no_target=False, seed=0):
    """BoardingCombatInstance.A(ship, enemy, noTarget): first 3 enemy groups, or one random group."""
    if not enemy.groups:
        return []
    if no_target:
        return [enemy.groups[int(hash01(seed) * len(enemy.groups)) % len(enemy.groups)].index]
    return [g.index for g in enemy.groups[:3]]


def musketeer_protection(side, unit_types, limit):
    """BBoardingStartsMusketeersDefence: protect up to ``limit`` groups led by musketeers."""
    out = set()
    for g in side.groups:
        first = next(iter(g.units), None)
        if first is not None and unit_types[first].musketeer:
            if limit <= 0:
                break
            limit -= 1; out.add(g.index)
    return out


def _attack(attacker, defender, *, log, t):
    passes = []
    if not attacker.targets:
        return passes
    for g in attacker.groups:
        if g.health_factor <= 0:
            continue
        amount = g.total_damage * g.damage_factor * (PROTECTION_OUT if g.index in attacker.protected else 1.0)
        live = [defender.groups[i] for i in attacker.targets if i < len(defender.groups) and defender.groups[i].health_factor > 0]
        if not live:
            continue
        for tgt in live:
            dmg = amount / len(live)
            if tgt.index in defender.protected:
                dmg *= PROTECTION_IN
            passes.append((g.index, tgt.index, dmg))
    return passes


def _apply(side, passes):
    killed = 0
    for _src, tgt, dmg in passes:
        g = side.groups[tgt]
        if g.hp <= 0:
            continue
        before = sum(g.units.values())
        g.hp -= dmg
        if g.hp <= 0:
            g.hp = 0; killed += before; g.units = {k: 0 for k in g.units}; continue
        cut = g.initial_units * dmg / g.initial_hp
        # Remove ``cut`` units (fractional part carried as a probability, like GSI.RandomCut).
        remove = int(cut) + (1 if hash01(int(g.hp * 1000) + tgt) < cut - int(cut) else 0)
        for k in sorted(g.units, key=lambda u: -g.units[u]):
            take = min(g.units[k], remove)
            g.units[k] -= take; remove -= take; killed += take
            if remove <= 0:
                break
        if sum(g.units.values()) == 0 and g.hp > 0:
            g.units[next(iter(g.units))] = 1; killed -= 1
    return killed


def simulate_boarding(side_a, side_b, *, duration=BOARDING_DURATION_S, retarget=True):
    """Run the shared boarding loop (UpdateGunnery + CommonApplyDamage) until one side is wiped or time runs out.

    Each group fires on its own timer (3 s ± 5 %). The win rule at time-out is inferred from
    WosbBoarding.PreponderancetoWin: the side whose remaining strength is ≥ 1.5× the other's wins.
    """
    log = []; t = 0.0; dt = 0.05
    while t < duration:
        t += dt
        for att, dfn in ((side_a, side_b), (side_b, side_a)):
            if retarget:
                att.targets = [i for i in att.targets if i < len(dfn.groups) and dfn.groups[i].hp > 0] or \
                              [g.index for g in dfn.groups if g.hp > 0][:3]
            ready = []
            for g in att.groups:
                if g.hp <= 0:
                    continue
                g.timer -= dt
                if g.timer <= 0:
                    g.timer += g.interval; ready.append(g)
            if ready:
                saved = att.groups
                firing = Side(att.name, ready, att.targets, att.protected)
                passes = _attack(firing, dfn, log=log, t=t)
                att.groups = saved
                killed = _apply(dfn, passes)
                if passes:
                    log.append({'t': round(t, 2), 'attacker': att.name, 'damage': round(sum(p[2] for p in passes), 1),
                                'killed': killed, 'hp_a': round(side_a.hp, 1), 'hp_b': round(side_b.hp, 1)})
        if side_a.hp <= 0 or side_b.hp <= 0:
            break
    sa = side_a.hp * (1 + side_a.weight_bonus); sb = side_b.hp * (1 + side_b.weight_bonus)
    if side_b.hp <= 0 and side_a.hp > 0:
        result = side_a.name
    elif side_a.hp <= 0 and side_b.hp > 0:
        result = side_b.name
    elif sb > 0 and sa / sb >= PREPONDERANCE_TO_WIN:
        result = side_a.name
    elif sa > 0 and sb / sa >= PREPONDERANCE_TO_WIN:
        result = side_b.name
    else:
        result = 'undecided'
    return {'winner': result, 'seconds': round(t, 2), 'log': log,
            'remaining': {side_a.name: round(side_a.hp, 1), side_b.name: round(side_b.hp, 1)},
            'units_left': {side_a.name: side_a.units_alive, side_b.name: side_b.units_alive},
            'win_rule': 'wiped out, or ≥1.5× remaining strength at time-out (inferred)'}


def can_board(attacker_pos, attacker_heading_deg, target_pos, target_heading_deg, *, distance_limit,
              target_hp, target_max_hp, either_sinking=False, either_big_hole=False, first_check=True):
    """WosbBoarding.CheckFor (geometry, HP and state rules)."""
    dx, dy = target_pos[0] - attacker_pos[0], target_pos[1] - attacker_pos[1]
    dist = math.hypot(dx, dy)
    if dist == 0:
        return False, 'same position'
    n = (dx / dist, dy / dist)
    ha = (math.cos(math.radians(attacker_heading_deg)), math.sin(math.radians(attacker_heading_deg)))
    hb = (math.cos(math.radians(target_heading_deg)), math.sin(math.radians(target_heading_deg)))
    if abs(ha[0] * n[0] + ha[1] * n[1]) > 0.8 or abs(hb[0] * n[0] + hb[1] * n[1]) > 0.8:
        return False, 'not alongside (bow or stern toward the other ship)'
    if abs(ha[0] * hb[0] + ha[1] * hb[1]) < 0.8:
        return False, 'ships not parallel enough'
    if dist > distance_limit:
        return False, 'too far'
    if either_sinking or either_big_hole:
        return False, 'a ship is sinking or holed'
    if first_check and target_hp > target_max_hp / 2:
        return False, 'target above 50% HP'
    return True, 'allowed'


def boarding_distance(width_a, width_b, *, first_check=True, now_speed=0.0, distance_bonus=0.0):
    """ShipDynamicInfo.BoardingFailureDisatnce."""
    base = 7 if first_check else (11 if now_speed < 2 else 9)
    return (width_a + width_b) * 0.3 + base * (1 + distance_bonus)


# --------------------------------------------------------------- fire

MICROFIRE_DAMAGE_PER_S = 4.0      # Gameplay.MicroburningDamage per BurningLoopMs (1 s)
BIG_FIRE_NO_RETURN_S = 12.0
BIG_FIRE_COOLDOWN_S = 80.0
FIRE_AREA = {'damage': 13, 'radius': 5.0, 'add_radius': 1.3, 'max_radius': 14.5, 'ttl_s': 11.0}


def microfire_duration(position_hash, fighting_speed_bonus=0.0):
    """MicroburningEffect: 6–10 s, shortened by PMicrofireFightingSpeed."""
    base = hash01(position_hash) * 4.0 + 6.0
    return base * max(0.001, 1 - fighting_speed_bonus)


def big_fire_can_start(microfires, hp, max_hp):
    """ShipFirstHp.ServerBurningCheck conditions (the server also runs a timer)."""
    need = 1 + round(max_hp / 1000.0)
    if microfires < need:
        return False, f'needs {need} micro-fires burning'
    if hp > max_hp * 0.95 or hp < max_hp * 0.05:
        return False, 'HP must be between 5% and 95%'
    return True, 'large fire can start'


def big_fire_check_interval(timer_s, hp, max_hp):
    """The ignition timer runs faster at low HP: timer × (0.5 + 0.5 × HP fraction)."""
    return timer_s * (0.5 + 0.5 * hp / max_hp)


def big_fire_flare(process_s, burning_type, mending_level=0.0):
    """ShipFirstHp.BigBurningFlareUpLevel. burning_type: 'infinite', 'infinite_mendable' or 'finite'."""
    a = process_s * 1000.0
    if a == 0:
        return 0.0
    if burning_type == 'finite':
        x = a / 12000.0
        return x * (1 - x) * 4 * 0.6
    if burning_type == 'infinite':
        return min(1.0, a / 4000.0)
    extra = 0.0 if a < 12000 else (a - 12000) / 2000.0
    return min(max(0.01, 1 - mending_level), (a / 12000.0) ** 1.7 * 0.7 + extra)


def fight_big_fire(mending_level, fire_fighting_bonus=0.0):
    """One firefighting action: (level + 0.24) × BigFireFightingSpeed, capped at 1; decays 0.1/s."""
    return min(1.0, mending_level + 0.14 + 0.1) * (1 + fire_fighting_bonus)


def fire_area_extend(radius):
    """FireArea.Extend: another incendiary ball nearby grows the area (to 14.5) and refreshes its timer."""
    return min(FIRE_AREA['max_radius'], radius + 1.3 * ((14.5 - radius) / 14.5) ** 1.4)
