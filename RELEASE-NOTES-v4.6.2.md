# WoSB Workbench 4.6.2

## 3D ship viewer: designs work the way the game's design slots do
These follow the client's slots (ShipDesignCategory and PlayerShipDynamicInfo design places).
- **Two flags.** Flag (place 0) and Second flag (Flag2, place 7) are separate, as the game allows on ships with two main flags (for example Bellona). A flag's free-flying copy and its copy fixed to the frame count as one flag.
- **Sail cloth** (SailTexture, place 8) still re-textures every sail. Each sail picks its main, mini, side or triangle variant, as the game does.
- **Three pattern slots, each set sail by sail:**
  - Paint (Decal1, place 1) starts on every sail;
  - Pattern (Decal2, place 3) and the premium Extra pattern (Decal3, place 9) start on the square (animated) sails only;
  - these defaults follow `Decal*SelectedSailesBits` and `AnimatedSailesBits`.
- **Choose sails:** opens a list of every sail by its client index. You can tick sails there, or click sails in the 3D view. Green boxes show the sails that carry the pattern.
- Model sail meshes are matched to the client's sail index using the rebuilt hitboxes.
