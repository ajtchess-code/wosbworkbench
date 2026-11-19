# WoSB Workbench 4.5.3

## Battle simulator looks closer to the game
- **Sea**: rendered with the game's own ocean textures (wave normal map, foam and foam mask) scrolling with the
  wind, plus sun glints, wave-crest foam and foam wakes behind moving ships.
- **Islands**: terrain now uses the game's ground textures (sand, grass and grassy rock, or snow sets on
  northern islands), blended by height and slope, with the islands' real rock textures.
  The game's terrain shader decides the exact blend, which isn't recoverable as data, so this is a close approximation.
- **Cannon fire**:
  - Cannons fire with a muzzle flash and drifting powder smoke.
  - Balls fly as dark iron shot; trails are optional.
  - Misses throw up a water column and ring; hits throw wood splinters and smoke.

## Fixed
- The simulators and the wiki now build ship hitboxes automatically from your Full Recovery when you haven't
  run "Rebuild ship hitboxes". Before, ships fell back to a generic hull box and generic gun ports.
- Model packs are rebuilt once (format 2) so islands get their terrain groups.
