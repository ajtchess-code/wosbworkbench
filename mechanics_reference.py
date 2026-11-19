"""Wiki pages for damage mechanics and ship hitboxes.

Pages are written for players (what happens and why), not as code listings.
Sections: 'Mechanics' pages are public-safe; 'Research' pages hold internals
(message layouts, source references) and are excluded from the public site.
"""
from __future__ import annotations

import damage_model as dm

DAMAGE_PAGE = f'''# Damage and sinking

How a ship takes damage once a hit lands. Everything on this page follows the
game client's own rules; the one thing the client does **not** decide is how
much a cannonball hits for, which the server calculates (see
[[Damage formula calibration]]).

## Hull HP

* Damage is removed from the ship's current HP. If what is left would be below
  0.5 HP, it rounds down to zero.
* At zero HP the ship does not vanish: it starts **sinking**. HP is held at 1
  and further hits do no HP damage.
* The sinking timeline lasts **{dm.FLOODING_TIME_MS / 1000:g} seconds**. At the
  end the ship is destroyed by flooding.
* Repairs and healing do nothing once a ship is sinking.

## Things that finish a sinking ship instantly

While a ship is sinking, these destroy it immediately:

* a **powder keg** or **mortar** hit
* fire damage while a **large fire** is burning
* a hit flagged as a **stern** hit, or fireworks
* (tutorial map) any hit on a ship with under 500 max HP

A **ram** from another ship pushes the sinking timeline 0.8 s closer to the end
(capped just short of the end).

## Sails

* Each sail has its own strength (100 % when intact). Overall sail health is
  the average of all sails **weighted by sail size**.
* A single-sail hit damages only the sail that was hit. Because damage is
  divided by the sail's weight, small sails shred faster than big ones.
* "All sails" damage (e.g. chain-type effects) is spread across every sail by weight.
* A cannonball loses energy passing through sails: it keeps **1/2** after one
  sail, **1/3** after two, and **nothing** after three.
* Furled (closed) sails take at most **30 %** of normal sail damage. Sail
  protection bonuses reduce sail damage further.
* Below 95 % sail health, maneuverability drops, down to 80 % at 80 % sails.

## Other effects a hit can carry

| Effect | What it does |
|---|---|
| Crew damage | Kills or wounds specific crew members (by unit type) |
| Cannon critical | Breaks one specific cannon |
| Hull breach (corpus critical) | Breach lasting a set number of seconds (10 s for a ram crit) |
| Micro-fire | Starts a small fire |
| Large fire | Starts a big fire of a given type (finite fires burn out after 12 s) |
| Speed debuff | Slows the ship |

## Mortars

Mortar splash does full damage to a ship inside the blast, then falls off with
distance: 10 % + 90 % × √(1 − distance ÷ radius).

## Sprint (march) speed

Taking damage bleeds off your sprint bonus: roughly the hit's damage ÷ your
remaining HP × 100, plus 100 × any sail damage.

## Tutorial map

Player ships take damage ÷ 1.5; PvP damage there is × 1.2.

Try it: [[Damage simulator]].
'''

CALIBRATION_PAGE = '''# Damage formula calibration

The server, not the client, decides how much HP a cannonball removes
(penetration against armor, range, angle, crits). To reproduce it, record hits
with known inputs and fit a model.

## What to record per shot

* shooter ship, cannon type, ammo, target ship
* range (and angle if possible)
* target HP **before** and **after** the hit (from the HP bar or video)
* where it hit: hull, sail, stern, bow

## How to record it

1. Start a Gameplay Capture session; set shooter, target, weapon and ammo.
2. Use the hotkeys to mark *broadside*, *single shot*, *hit*, *miss*, *stern*, *side*, *bow*.
3. Afterwards, read the HP values off the clips and enter them in the trial sheet.
4. 10–20 clean single-shot hits per cannon/ammo pair is enough for a first fit.

Hull and sail behaviour after the hit is already exact — see [[Damage and sinking]].
'''

HITBOX_PAGE = '''# Ship hitboxes

Every ship has three kinds of hit zones, built by the client from the ship model:

* **Hull (corpus)** — one zone, the bounding box of the ship's dedicated hit
  mesh. Some ships carry a separate, tighter hit model.
* **Sails** — every sail is split into **4 horizontal slices** starting just
  below the deck line, slightly narrower (94 %) than the sail itself. A ball can
  pass through up to 3 sails, losing energy at each (1/2, 1/3, then stopped).
* **Masts** — a box at the base of each mast, from the deck up to roughly half
  the mast's height.

Zones are numbered: **0 = hull**, then the sails, then the masts. Hits report the
zone number, which is how a hit is assigned to a specific sail.

Open any ship in the Ship 3D viewer to see its zones. Zone shapes are exact
reconstructions of the client's rules; which mesh is a "sail" or "mast" is read
from the model's part names.
'''


def seed_damage_pages(db):
    """Create/refresh the mechanics pages (does not overwrite user-edited pages)."""
    pages = [('damage-and-sinking', 'Damage and sinking', 'Mechanics', DAMAGE_PAGE),
             ('damage-formula-calibration', 'Damage formula calibration', 'Mechanics', CALIBRATION_PAGE),
             ('ship-hitboxes', 'Ship hitboxes', 'Mechanics', HITBOX_PAGE)]
    written = 0
    for slug, title, section, body in pages:
        row = db.conn.execute('SELECT is_user_edited FROM articles WHERE slug=?', (slug,)).fetchone()
        if row and row[0]:
            continue
        db.upsert_article(slug, title, section, body, source_kind='client-code', source_ref='Common.dll',
                          review_status='source-verified')
        written += 1
    db.conn.commit()
    try:
        import mechanics_pages
        written += mechanics_pages.seed(db)
    except Exception:  # never block the core pages
        pass
    return written


def seed_hitbox_summary(db, summary):
    """A table of every ship's reconstructed zones (from hitbox_recovery.batch)."""
    rows = ['| Ship model | Hit mesh | Sails | Masts | Zones | Hull size (world) |', '|---|---|---|---|---|---|']
    for s in sorted(summary.get('ships', []), key=lambda r: r['model'].casefold()):
        if 'error' in s:
            rows.append(f"| {s['model']} | failed | | | | |"); continue
        size = ' × '.join(f'{v:g}' for v in s['corpus_world_size'])
        rows.append(f"| {s['model']} | {s['hitmesh']} | {s['sails']} | {s['masts']} | {s['nodes']} | {size} |")
    body = '# Ship hitbox table\n\nReconstructed hit zones for every recovered ship. See [[Ship hitboxes]].\n\n' + '\n'.join(rows) + '\n'
    db.upsert_article('ship-hitbox-table', 'Ship hitbox table', 'Mechanics', body, source_kind='model-recovery',
                      source_ref='hitbox_recovery', review_status='generated')
    db.conn.commit()


def seed_message_pages(db, schemas, *, names=('DamageData', 'OnShipsSomeDamageMsg', 'OnBallsCollisionMsg')):
    """Research-only pages describing key message layouts (excluded from the public site)."""
    import source_schemas
    by_short = {t['type'].rsplit('.', 1)[-1]: t for t in schemas.get('types', [])}
    parts = ['# Combat message layouts', '',
             'Field layouts of the combat messages, recovered from the decompiled client. '
             'Research section: not published to the public wiki.', '']
    for n in names:
        if n in by_short:
            parts += [source_schemas.describe(by_short[n]), '']
    parts += [f"{schemas.get('packets', 0)} packet types and {len(schemas.get('types', []))} serializable types in total "
              '(Research/Protocol/Message-Schemas.json).']
    db.upsert_article('combat-message-layouts', 'Combat message layouts', 'Research', '\n'.join(parts),
                      source_kind='decompiled-client', source_ref='source_schemas', review_status='generated')
    db.conn.commit()
