# WoSB Workbench 4.6.1

## 3D ship viewer (`tools/ship-viewer.html?ship=…`)
- Every ship's real model from the wiki's model pack, with orbit, pan and zoom.
- Switch the game's invisible hitboxes on and off: the hull box (which also handles collisions), mast boxes and sail boxes.
- Hull colouring, painted onto the model:
  - damage from a chosen firing direction;
  - average damage over every direction;
  - impact angle;
  - bow/side/stern zones.
- Each point is coloured by where a ball aimed at it would cross the hull box, because that crossing is where the client decides the hit.
- **Fire a cannonball**: use the chosen direction, or click anywhere on the ship. The ball flies in, and the shot log records:
  - the zone it hit, the angle and the damage per ball, or that it glanced off;
  - masts it struck;
  - sail boxes it passed through.
- **In-game designs** from ShipDesingElements:
  - ship skins: material → texture swaps, listed only for the ship they fit;
  - sail textures: the game's prefix + main/mini/side/triangle rule;
  - sail emblems: laid over the sails, placement approximate;
  - flags;
  - figureheads: BowFigures meshes at the ship's figurehead mount, scaled by the client's rule 0.15 + 0.6 × hull half-length ÷ reference hull.
- The model pack now carries the design textures and the figurehead model.
- Ship pages link to the viewer.
