# WoSB Workbench 4.5.0

## New
- **Battle simulator (3D)** (Datamining → Battle & boarding simulators, and on the wiki):
  - Real ship, tower, fort and island models with their textures, rendered with WebGL, plus animated water.
    Ships without a recovered model are drawn from their hull dimensions.
  - Ships fire from their real gun ports, using bow/stern guns and special weapons: double, triple and
    eight-shot (Imperial Bombard), Alchemical Fire and mortars.
  - Hits follow the client's order (hull, then masts, then up to three sails), with angle, bow and stern zones,
    overpenetration, fire and sinking. You can show firing arcs, predicted landing points, ball trails,
    hitboxes and a hit heatmap.
  - Sailing uses the game's wind effectiveness rule, including the unique wind rose and ship hardness.
- **Port battles with fleets**: choose any of the 25 guild-fort sites, a team limit (5–40), a shallows rank limit,
  a city level and the number of defenders. Then watch it play out.
  - The rules come from the client: building HP by shallows rank, team limit and city level; a 25-minute clock,
    +10 min per destroyed tower, up to 90 min; respawn points per side, with each sinking costing more for
    bigger ships; instant respawns.
  - Towers: a 15 s attack timer before a tower can be damaged; a destroyed tower is captured by staying
    within 30 for 30 s, and at most half the towers can be captured.
  - The fort is boarded in 25 s once it is at 0 and no tower stands.
- **Orders and inputs**:
  - Box-select or click ships, then right-click to move (Shift adds waypoints), attack or follow.
  - Formations: line ahead, line abreast, wedge and double column. Squads with Ctrl+1–9.
  - Per-ship settings: hold/engage/retreat, fire at will / return fire / hold fire, engagement range, target
    priority, retreat at an HP %, and sail setting.
  - Ships tack automatically when ordered upwind.
- **Timeline scripts** (`03:00 squad 2 move 100,200`, `05:00 wind 240`, `04:00 blue ammo Heavy Shots`…),
  wind drift, seeded randomness, spotting range, a replay slider, and HP charts.
- **Analysis tools**:
  - Batch runs (30+ battles with different seeds) report win share, battle length and losses.
  - Unit and timeline CSV export.
  - Save/load scenario files and share links.
- **Boarding simulator**: the client's boarding fight loop with your ship, crew mix and boarding upgrades and
  skills. It checks whether boarding can start, plots the HP curves and runs 200 jittered fights.
- **Model packs**: real meshes and textures packed for the browser. The local build uses full detail; the wiki
  uses a lighter version with 512 px textures. Only models that changed are rebuilt. Textures come from the
  recovered PNGs, or are decoded straight from the game's texture files.
- **Calibrate cannonball damage**: log measured hits in Research/Damage-Trials.csv; the fit
  (armor weight and scale) is used by the simulators and the wiki.
- **Wiki**:
  - New pages: Large and minor fires, Boarding, Sailing and wind, Damage formula, Ammunition compared.
  - New categories: Ship cosmetics, Island decorations, Crafting (with ingredients).
  - New world map of every port, guild fort, tower and imperial fort; each port-battle site links straight
    into the simulator.
  - The Wind & sailing tool now plots the real wind effectiveness, with ship hardness and the unique rose per tack.
  - The battle and boarding simulators are public tools.
- **Publish wiki to GitHub Pages**: pushes the built wiki folder to a gh-pages branch using your own git.

## Fixed
- Large-fire kinds were mapped to the wrong enum values (finite vs infinite).
- Folder pickers given a parent folder (e.g. `C:\Games\World of Sea Battle`) now resolve the real client folder.
- Scan pages could still point at the Workbench folder until the next restart.
- Texture decoding no longer needs the optional texture2ddecoder package; a built-in BC1/BC3 decoder is used if it is missing.
- The Windows build bundles the whole viewer folder (simulators and shared library).

## Notes
- Exact per-ball damage is decided by the server. The simulators use the game's "penetration minus defense"
  rule and are labeled as estimates until you calibrate them with measured hits. The bow/stern modifiers,
  ship AI and the port-battle kill-time rule are the simulator's own; this is stated in the tools.
- Re-run Full Recovery once so recovered models carry their gun ports and hardpoints, then rebuild hitboxes,
  the simulators and the wiki.
