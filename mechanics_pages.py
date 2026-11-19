"""Player-facing mechanics articles added in 4.5: fires, boarding, sailing, damage formula, ammo.

Every number here comes from the game client's own code or help text. Where the
server decides something (cannonball damage, the boarding winner at time-out),
the page says so.
"""
from __future__ import annotations

FIRES_PAGE = '''# Large and minor fires

Fire comes in two sizes. **Minor fires** are short and tick small amounts of damage.
A **large fire** can grow and burn a ship down. A large fire almost always grows out
of minor fires, so you prevent one by keeping the minor fires down. Try the numbers
in the [[Fire calculator]].

Everything below is read from the game client. The **chance that a hit starts a fire**
is rolled by the server and is not in the client, so it has to be measured (the Fire
calculator turns your own counts into a rate).

## Minor fires

* **What can start them:** hits from ammo marked *can make burnings*: cast-iron shot,
  carcass shells and Saxon shot. Carcass and Saxon also carry *extra micro-burning*
  (a higher chance). Heavy, chain, grape, fireworks, rockets, phosphorus grapeshot,
  smoke and snowball shot cannot start them.
* **Incendiary Mixture** (upgrade) lets *every* shot type start fires. It can't be fitted on heavy ships.
* **Damage:** each minor fire burns for **4 HP per second**, where the ball hit.
* **Duration:** **6–10 seconds**, fixed by where the ball hit, divided by
  (1 − minor-fire suppression). With +50% they last 3–5 s.
* Any number can burn at once; their damage adds up.

| Minor-fire suppression | Source | One fire lasts |
|---|---|---|
| none | | 6–10 s |
| +25% | Special crew | 4.5–7.5 s |
| +50% | Large Plates (consumable: also +4 armor, −10% turning) | 3–5 s |
| +75% | both | 1.5–2.5 s |

**Sea Ration** (repair consumable) puts out every minor fire at once, fixes a hull breach and
up to 3 guns, and repairs 2% HP.

## When a large fire can start

The server checks on a timer. The check can only pass when **all** of these are true:

1. At least **1 + (max HP ÷ 1000, rounded)** minor fires are burning at once.
   Pickle (850 HP) needs 2, Bellona (3,180) needs 4, 12 Apostolov (3,960) needs 5.
2. HP is between **5% and 95%** of maximum.
3. No large fire has burned in the last **80 seconds**.

The check comes faster when you're hurt: its interval is multiplied by
0.5 + 0.5 × (HP fraction), so at half HP checks are 33% more frequent than at full HP
and at 25% HP 60% more frequent.

A ram flagged as burning, and some boarding and event effects, start a large fire directly
without any minor fires.

## Kinds of large fire

| Kind | Started by | How it burns | Can repairs stop it? |
|---|---|---|---|
| Finite | some events | Rises and falls over **12 s** (peaks at 60% strength at 6 s), then goes out | yes |
| Mendable | burning rams | Grows slowly, then past **12 s** shoots to full strength (the point of no return) | yes |
| Infinite | some events | Full strength in **4 s**, keeps burning | **no** |

Fighting a mendable fire caps its strength: each fire-fighting action adds 24% to your
progress (times big-fire suppression, e.g. +40% from the Special crew), and progress fades
by 10% a second. The ship's HUD shows it as "Extinguishing fire: N%". The **Fire Suppression**
captain skill makes the crew fight fires on their own.

Large-fire damage is reduced by large-fire damage protection. A ship that is already
sinking is destroyed at once by fire while a large fire burns.

## Fire on the water

Carcass shells that **miss** leave a burning patch where they land: 13 damage, radius 5,
lasting 11 s. More shells landing in the same patch grow it (fast at first, then slower,
up to 14.5) and top up its time; it shrinks back toward 5 by 0.65 a second and drifts.
Copper Plating takes 25% off fire-area damage and Iron Plating 45%. Reinforced Sail
Edges halve the damage burning does to sails.

## How to avoid large fires

1. **Kill minor fires fast.** Minor-fire suppression (Special crew, Large Plates) and a Sea
   Ration at the right moment stop the count from ever reaching the threshold.
2. **Stay above 95% HP** if you can: no large fire can start there.
3. **Below half HP the checks speed up**; that's when fire protection pays off most.
4. **Mind burning rams**: they skip the minor-fire stage. Repair to put the fire out.
5. **After a large fire you are safe for 80 s.**

See also: [[Damage and sinking]], [[Damage formula]], the [[Fire calculator]], the [[Battle simulator]].
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
