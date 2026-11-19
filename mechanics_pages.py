"""Player-facing mechanics articles added in 4.5: fires, boarding, sailing, damage formula, ammo.

Every number here comes from the game client's own code or help text. Where the
server decides something (cannonball damage, the boarding winner at time-out),
the page says so.
"""
from __future__ import annotations

FIRES_PAGE = '''# Large and minor fires

Fire in World of Sea Battle comes in two sizes: short **minor fires** (micro-fires)
that tick small amounts of damage, and a **large fire** that can grow and burn a
ship down. A large fire can only start from minor fires, so you prevent one by
keeping the minor fires down.

## Minor fires (micro-fires)

* **What starts them:** incendiary hits. Ammo marked *can make burnings*
  (cast-iron shot, carcass shells, Saxon shot and others) has a chance to light
  one per hit; ammo with *extra micro-burning* (carcass, Saxon) has a higher chance.
  Fire tower (Prometheus) hits and some specials also light them.
* **Damage:** each minor fire burns for **4 HP per second**.
* **Duration:** **6–10 seconds** each. Crew bonuses for micro-fire fighting
  (PMicrofireFightingSpeed, such as the fire-fighting special crew) shorten it.
* Several can burn at once, and their damage adds up.

## Large fire

### When one can start

The game checks for a large fire on a timer. It can start only when **both** of these are true:

1. The ship has at least **1 + (max HP ÷ 1000, rounded)** minor fires burning at
   the same time. A 3,000 HP ship needs 4; a 6,000 HP ship needs 7.
2. The ship's HP is between **5% and 95%** of maximum.

The check runs faster when the ship is badly damaged: its interval is multiplied
by 0.5 + 0.5 × (HP fraction), so at half HP checks come 25% more often than at full HP.
After a large fire there is an **80-second cooldown** before another can start.

### How it burns

There are three kinds of large fire, set by what started it:

| Kind | Behaviour |
|---|---|
| Finite | Burns for 12 seconds. Strength rises then falls (a bell curve peaking at 6 s). Rams start this kind. |
| Infinite | Ramps up to full strength over 4 s and keeps burning until put out. |
| Infinite, mendable | Grows slowly, then faster after 12 s; repairing (mending) holds it back. |

Large-fire damage is reduced by **PReduceBigFireDamage** (for example, the special crew with +50%).

### Fire areas

Carcass-type ammo can leave a burning **fire area** on the water: 13 damage, starting
radius 5, growing toward a maximum of 14.5 (fast at first, then slowing), lasting
11 seconds. Ships sailing through it take damage and can catch fire.

### Fire and sinking

A ship that is already sinking is **destroyed instantly** by fire if it is under a large fire.

## Fighting fire

* Fire-fighting progress builds at **(fire-fighting level + 0.24) × fighting speed**
  and decays by 0.1 per second when you stop.
* **PBigFireFightingSpeed** (for example, the special crew with +40%) speeds this up.

## How to avoid large fires

1. **Kill the minor fires quickly.** The large fire needs many minor fires at once,
   so micro-fire fighting bonuses are the most effective prevention.
2. **Mind your HP.** Above 95% HP a large fire cannot start; below 50% the checks speed up.
3. **Bigger ships need more minor fires** before a large one can start (the threshold scales with max HP).
4. **Carry fire-fighting crew or upgrades** if you expect carcass, Saxon or Prometheus towers (port battles).
5. **After one burns out you are safe for 80 s**: a window to take risks.

See also: [[Damage and sinking]], [[Damage formula]], the [[Battle simulator]].
'''

BOARDING_PAGE = '''# Boarding

Boarding is a crew fight between two ships. It is simulated in fixed rounds, so the
outcome depends on crew numbers, crew types and boarding bonuses. Try it in the
[[Boarding simulator]].

## When you can board

All of these must be true:

* The target is at **50% HP or less**.
* The ships are **side by side**: their headings must be within about 37° of parallel
  (either direction). You cannot board bow-on.
* The gap is within hook reach: **7** when stopped, **11** when moving, multiplied
  by (1 + boarding-distance bonus), measured beyond both hulls' half-widths. Small Hooks add +15%.
* Neither ship is sinking.

## How the fight runs

* Each side's crew is split into **groups** of 16 + (ship's crew places ÷ 15) men.
* Each group strikes every **3 seconds** (each group's timing is jittered ±5%).
* A strike deals the group's total damage × (group HP left ÷ group starting HP)<sup>0.7</sup>,
  so weakened groups hit less hard, but not proportionally less.
* Damage is split across up to **3 enemy groups** at a time (the first three, or one random
  group when *Boarding starts with no target* applies).
* Losses: men are removed in proportion to the HP a group loses.
* The fight lasts up to **30 seconds** after 4.1 s of preparation.

## Crew types

| Crew | Damage | Health |
|---|---|---|
| Sailor | 15 | 380 |
| Boarding unit 1 | 30 | 320 |
| Boarding unit 2 | 20 | 450 |
| Musketeer | 50 | 170 |

Each crew member adds its damage and health to its group.

## Bonuses that matter

* **Musketeer defence** (special crew): at the start, groups containing musketeers
  are protected, taking and dealing ×0.2 damage.
* **More weight at boarding** counts your remaining crew as heavier when strength is compared.
* **Boarding distance** extends hook reach.
* **Improve some crew damage** raises musketeer damage.
* Special crews that conflict with each other each work at half strength unless a
  "no conflicts" effect is present.

## Who wins

A side wins outright when the other side's crew is wiped out. If time runs out,
the server decides; the simulator assumes a side needs **1.5× the other's remaining
strength** to win, which matches the game constant but is not confirmed as the rule.
'''

SAILING_PAGE = '''# Sailing and wind

Ship speed = base speed × **wind effectiveness**, adjusted by sail health and upgrades.
This page explains wind effectiveness, the regular and unique wind roses, and why
heavy ships handle differently. Try it in [[Wind & sailing]] or the [[Battle simulator]].

## Wind effectiveness

Angles here are measured from the wind **behind** you (0° = running downwind,
180° = straight into the wind).

| Heading off the wind | Regular rose |
|---|---|
| 0° (dead downwind) | 70% |
| 10° | 85% |
| 30°–90° | 100% |
| 150° | 78% |
| 170° | 20% |
| 180° | 0% |

* Ships are fastest on a broad reach to a beam reach (about 25°–110°).
* **Dead downwind is slower**: within a narrow band around 0° a downwind penalty of up to
  −30% applies, which some upgrades reduce.
* Sailing close to the wind falls off quickly beyond 140°.

## Unique wind rose

Some ships have a unique rose. Two things change:

* On **one tack** when beating upwind, the rose is rotated by about 17° (0.3 rad), so
  the ship can point higher on that side.
* The downwind penalty band is much narrower.

## Hardness (heavy vs light ships)

The ship's weight sets **inertia**: 2 for ships under 30 t, falling to 1 at 80 t and above.
**Hardness** = 2 − inertia. Heavier (harder) ships lose less speed at poor wind angles:
the upwind fall-off is softened toward a 15% floor. Light ships accelerate and turn
faster but suffer more from bad angles.

## Turning

Mobility is the number of degrees a ship turns in **10 seconds**.
'''

DAMAGE_FORMULA_PAGE = '''# Damage formula

The game's own help text states the core rule: **damage equals penetration minus defense**.
This page puts that into numbers and shows what changes it. Exact per-ball damage is
calculated by the server, so these figures are estimates until calibrated with
[[Damage formula calibration|measured hits]].

## Per ball

Damage per ball ≈ (cannon penetration + ammo penetration − armor at the impact angle) × ammo damage factor

* The in-game UI shows per-ball damage as (cannon pen + ammo pen − 2.1) × damage factor,
  and damage per minute as (pen − 2) × 60 ÷ reload.
* Armor at an angle: a ball striking at an angle meets more armor. Effective armor ≈ armor ÷ cos(angle).
  Very flat (glancing) hits do little.
* Some ammo has a minimum damage through any hit zone.

## How a hit is detected

A cannonball doesn't have to touch the visible hull. Each frame, the game draws a line from the ball's last position to
its new one, and tests that line against three kinds of invisible boxes, in this order:

1. **The hull box**: one box around the hull, from the waterline to the deck. If the line crosses it, it's a hull
   hit, even where the curved hull is narrower than the box (near the bow, for example).
2. **Mast boxes**: if the hull box was missed.
3. **Sail boxes**: up to three sails per ball. Each sail slows the ball.

The box can stand in for a curved hull because the game also keeps a table of hull **surface directions** all the way
around the outline: a pointed bow, curved shoulders, flat sides, and a wide flat stern. Where the ball meets the box
tells the game which part of the hull it struck and how steeply. That's what makes angling, bow and stern matter.

## Where you hit

* **Bow**: the sturdiest part of the ship; hits there do less.
* **Stern**: protection is much lower, so hits do more. A stern hit on a
  ship that is already sinking finishes it instantly.
* **Side**: normal armor.
* **Masts and sails**: balls passing through sails damage them and lose energy
  (after one sail a ball keeps 1/2 its energy, after two 1/3, and it stops after three).

## Overpenetration

Ammo with **overpenetration** (Saxon shot) can pass through the first ship and hit
another behind it with reduced energy.

## Modifiers

| Effect | What it does |
|---|---|
| Armor bonus (PArmor / MArmor) | Raises armor |
| Ball damage (PBallDamage) | Multiplies ball damage |
| Weapon penetration (MWeaponPenetration) | Adds penetration |
| Damage reduction (PReduceDamage) | Cuts incoming damage, capped at 99% |
| Bow damage reduction (PReduceDamageToNose) | Extra reduction for bow hits |
| Long-range damage (PBallDamageWhenMaxDistance) | More damage at maximum range |

All bonuses from upgrades, crew, skills and items add together.

## Targeting hint

The game warns you when the target's armor is above 40% of your average penetration:
a sign that your guns will do little.
'''

AMMO_PAGE = '''# Ammunition compared

Which ammo does the most damage depends on the target's armor, because
**penetration minus armor** is multiplied by the ammo's damage factor. High-penetration
ammo gains the most against heavily armored ships; high-damage-factor ammo wins against light ones.

## Heavy shot vs Saxon shot vs Cast-iron shot

| Ammo | Damage factor | Reload | Ball speed | Sail damage | Crew damage | Special |
|---|---|---|---|---|---|---|
| Cast-iron shot | ×1.0 | ×1.0 | ×1.0 | 3.5 | 0.2 | can start fires |
| Heavy shot | ×1.25 | ×1.4 (slower) | ×1.1 | 3.5 | 0.2 | none |
| Saxon shot | ×0.8 | ×1.0 | ×1.2 | 8 | 0.8 | overpenetration, extra minor fires |
| Carcass shells | ×0.9 | ×1.0 | ×1.0 | 7 | 0.2 | fire area, extra minor fires, 60% range |

* **Heavy shot** hits 25% harder per ball, but its 40% longer reload means about
  **89% of cast-iron's damage per minute**. Heavy shot adds no penetration, so its edge is the
  same against any armor. It wins on **burst**: one broadside into a stern or a nearly sunk ship.
  It cannot start fires.
* **Saxon shot** does 20% less per ball, but its faster ball is easier to land at range, it
  **overpenetrates** into a ship behind, shreds sails and crew more, and starts extra minor fires.
  It is the better choice for setting up a [[Large and minor fires|large fire]], for crowded fights
  and before boarding. For raw hull damage per minute, cast-iron is ahead (×1.0 vs ×0.8).
* **Cast-iron shot** gives the best sustained hull damage per minute of the three.
* **Chain shot** and **grapeshot** are for sails and crew, not the hull.

## Compare them yourself

The [[Battle simulator]] has a *Compare ammo* button: pick your cannon and a target ship
and it lists per-ball damage (side, bow and stern) and damage per minute for every ammo type.
'''

PAGES = [
    ('large-and-minor-fires', 'Large and minor fires', 'Mechanics', FIRES_PAGE),
    ('boarding', 'Boarding', 'Mechanics', BOARDING_PAGE),
    ('sailing-and-wind', 'Sailing and wind', 'Mechanics', SAILING_PAGE),
    ('damage-formula', 'Damage formula', 'Mechanics', DAMAGE_FORMULA_PAGE),
    ('ammunition-compared', 'Ammunition compared', 'Mechanics', AMMO_PAGE),
]


def seed(db):
    written = 0
    for slug, title, section, body in PAGES:
        row = db.conn.execute('SELECT is_user_edited FROM articles WHERE slug=?', (slug,)).fetchone()
        if row and row[0]:
            continue
        db.upsert_article(slug, title, section, body, source_kind='client-code', source_ref='Common.dll',
                          review_status='source-verified')
        written += 1
    db.conn.commit()
    return written
