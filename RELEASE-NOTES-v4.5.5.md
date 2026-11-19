# WoSB Workbench 4.5.5

## Battle simulator
- **Ships no longer sail through islands.** Each island gets a footprint from its game collision shape (the
  `_shape` model), or from its mesh if there isn't one. Ships stop at the shore, and steer around land by
  following the coast when an order or the AI points them at it. Forts and towers block ships too, and cannonballs
  hit land instead of passing through it.
- **Hit angle and zone now use the game's hull outline.** The client's shared physics code has a table of hull
  surface directions all the way around a ship: a pointed bow, curved shoulders, flat sides and a wide flat stern.
  A ball that crosses the hull box now takes its bow, side or stern zone and its impact angle from that table,
  instead of from the flat faces of the box.

## Wiki
- The **Damage formula** page explains how hits are detected: the ball's path crosses the hull box, then mast
  boxes, then sail boxes, and the surface-direction table supplies the angle.

Model packs rebuild once (format 3) to add island footprints.
