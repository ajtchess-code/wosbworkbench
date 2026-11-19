# WoSB Workbench 4.5.6

## New wiki tools
- **Hit analysis** (`tools/hit-analysis.html?ship=…`): a damage heatmap around each ship from its real hull box and the client's hull-direction table, plus a side-view zone strip and a shot table. It also includes:
  - a stat strip: rank, class, HP, armor, gun ports, swivels, masts and sails, crew, speed, hull box size;
  - every ammo against the ship (side, bow-on, stern rake, glancing limit, sail and crew damage, reload);
  - every broadside gun against the ship, with damage per minute;
  - mortars and the keg launcher: splash coverage drawn on the hull at world scale.
- **Every ship page** gets a compact "Where to hit it" section with the same analysis.
- **Every cannon and mortar page** gets a "What it can damage" table covering every ship.
- **Towers, forts & mortars** (`tools/defenses.html`):
  - tower reach versus your gun range at any distance, and a tower-versus-ship duel;
  - a tower and fort strength table by rank, team size and port level;
  - mortar and keg range bars, the splash fall-off curve, and damage against any ship.
- **Fire calculator** (`tools/fire-calculator.html`) with a new fire infographic:
  - the large-fire threshold, minor-fire duration with suppression bonuses, and the HP check window;
  - the odds of reaching the threshold under fire;
  - large-fire strength curves, including fire-fighting;
  - an ignition-chance tally with a 95% range.

## Fire mechanics corrected from the client code
- Burning rams start a *mendable* large fire, not a finite one. Repairs stop finite and mendable large fires but not infinite ones.
- Large Plates: +50% minor-fire suppression. Sea Ration puts out all minor fires. Incendiary Mixture can't be fitted on heavy ships.
- Fire on the water comes only from carcass shells that miss.
- The ignition chance per hit is rolled by the server and is not in the client.

## Gameplay capture
- Added **Minor fire** and **Large fire** markers (overlay buttons, Ctrl+Alt+F9 / F10).
- `fire_tally()` summarises hits versus fires per ammo, so the ignition chance can be measured.
