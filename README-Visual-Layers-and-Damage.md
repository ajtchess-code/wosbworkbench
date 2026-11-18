# Vasa visual layers and combat research: evidence notes

## The large box

The user-provided Vasa model contains a named `AverageBox_part0` mesh with 12 triangles, spanning about 47.85 units along X, 10.59 along Y and 10.24 along Z, consistent with a box. The same OBJ has `Hitbox_part0` (196 triangles), a separate `ShipCorpusShapeStrcture_part0` (162 triangles), high-detail `ShipCorpus` components, and low-detail `ShipLowCorpus` and `ShipMin` alternatives. The visible large rectangular object is **likely** `AverageBox_part0`, but that relationship has not been independently proven by identifying the exact pixels. Mesh names do not prove gameplay collision behavior.

By default, v3.8 renders the full-detail ship and excludes the helper-named and duplicate LOD meshes. Turn on **Candidate hitbox/helper meshes** to compare suspected collision art with the hull; **Duplicate low-detail meshes** shows alternative LODs. Those changes affect visibility and click targeting, not the underlying data.

## Texture recovery

The original Vasa model's validated XNA VertexBuffer has a HalfVector2 texture-coordinate channel (usage 2, format 10) at byte offset 20. The exporter preserves it in OBJ `vt` records. Full visual appearance still requires resolving each `EffectMaterialReader` reference to the original texture images; the Vasa part's `texture_label` is generally `Texture` and cannot uniquely identify the proper asset. For an intermediate viewer, choose a *local* PNG/JPG or Texture2D XNB (game-owned file); it is embedded in the saved offline HTML and applied as a user-selected atlas. This mapping is not assumed true.

## Mechanics evidence

Relevant IL samples are bundled under `Research-Combat-Code/`. In the scanned client, `Common.Resources.ShipDynamicInfo.get_Armor` uses **BasicArmor × (1 + GetBonus(5, 1)) + GetBonus(13, 1)**. Without verified enum mappings, upgrade tiers, and context we cannot equate these bonus indices with specific catalog `MArmor` and `PArmor` records. `Common.Resources.ShipDynamicInfo.get_ReduceDamageToNose` reads `GetBonus(18,1)`. The extracted **Iron Bow** upgrade has `PReduceDamageToNose +20`, indicating a bow-specific modifier exists. The exact damage processing and placement still require validation.

`Ship.CannonBallCollisionTest` first calls `SphereCollisionTest` and dispatches a second intersection routine; it does **not** prove that the rectangle called `AverageBox` is the only impact collider.

## Calibration

Record shots under controlled loadouts: same ship, target HP, cannon, ammunition, distance and initial angle; measure actual HP differences for bow, port, starboard, stern; repeat at oblique angles. Input a measured reference broadside damage and your measured multiplier. The Workbench reports it as a *user-calibrated estimate*, never as confirmed server logic. Do not derive damage multipliers from color-coded cosmetic model geometry.
