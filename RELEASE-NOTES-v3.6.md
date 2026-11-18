# WoSB Workbench v3.6 — Verified geometry and mechanics research

## Real ship geometry recovered

From the user's original Vasa `Ship_62_Vasa.xnb` (SHA-256 `ac892c5186354a2d7c12cb28ffad604e32c813f82ad89886d5345d5e26a550c0`) we validated:

- XNB v5 Windows LZX unpacking to 5,004,353 bytes (via libarchive on Linux).
- 40 bones, 39 named meshes, 93 mesh parts, 95 shared-resource references.
- A shared vertex buffer with **168,474 vertices** and a 24-byte vertex stride.
- A shared 16-bit index buffer containing **465,498 indices**.
- **155,166 validated triangles**, exported to an 8.36 MB Wavefront OBJ.
- The Game catalog maps playable ship ID **70** to `StaticInfoID=62`, then `ShipsBasics.ID=62` to `ModelName=Ship_62_Vasa`. Numerical ID equality is not assumed.

This is **real recovered geometry**, not an approximate silhouette. Rendered placement and transforms must still be visually validated on a Windows game installation. Texture/shader material recovery, animation, collision-volume alignment, and vulnerable damage multipliers remain **unverified**.

## New software capabilities

- `engine/xnb_geometry.py` reads ModelReader bones, WoSB mesh tags, bounded vertex declarations, shared vertex/index buffers, and exports real OBJ triangles. Unknown layouts fail with actionable errors.
- Ship 3D now offers **Recover XNB → OBJ** from a loose original `.xnb` or debug sample ZIP. The chosen ship and model association, source hash, and recovery metadata persist in `%LOCALAPPDATA%\WoSBWorkbench\Models` across updates.
- The 3D viewer can color **mesh-name components** (sails, hull, mast, hitbox-labeled art) but never portrays them as confirmed weak points.
- Automatic ship-model matching now uses `ShipsToPlay.StaticInfoID → ShipsBasics.ID → ShipsBasics.ModelName`, avoiding the gameplay-ID/asset-ID mismatch.
- New **Mechanics Lab**: evidence-gated armor getter, fire getter/large-fire threshold, crafting capacity and cost scenarios, production per-operation scenarios, and sourced wind-rose boundaries. It explicitly flags unknown stacking/server-side behavior.
- New **Enrich wiki from this build** action: drafts sourced pages for ships, construction materials, skills, guild benefits, factories, crafting, ports, cannons, crew, and wind. Preserves user-edited articles and keeps Game/Steam records distinct.
- The previous Discovery Center, scan importer, updater, and all reports remain intact.

## Validation

- **32/32 source tests pass.**
- End-to-end real original Vasa XNB sample ZIP → OBJ → model library → 3D HTML viewer succeeds, with 168,474 vertices, 155,166 triangles, 93 named mesh groups.
- Model and wiki tests include synthetic fixtures, invalid triangle indices, accurate StaticInfoID mapping, and preservation of manual wiki edits.
- Tkinter desktop startup validated headlessly on Linux with populated local database. Viewer JavaScript syntax validated with Node.js.
- **Not tested:** frozen Windows executable, Windows `expand.exe` CAB decompression, installer, updater on your machine, vertex transform visual fidelity, other WoSB model tag layouts.

## Known limits

1. Not every model is guaranteed to decode: variant custom tags, buffer layouts, extra shared buffers, or mismatched content readers may require additional research samples.
2. Model components called `Hitbox` do not by themselves establish authoritative collision tests or damage vulnerabilities. No verified weak-spot heatmap is generated.
3. Final server-authoritative combat/crafting/wind formulas remain unknown; calculators are verified client getters or clearly labeled what-if scenarios.
4. Textures, UV/material reconstruction and standalone GLB output are not included. OBJ geometry supports the existing offline viewer.
5. No game binaries or original XNB assets are redistributed inside the source package.

## Windows build and ZIP update

Unzip the **source package** and run `Build-Update.cmd` from its project folder with Python 3.13 available. The script uses Inno Setup if installed and creates:

- `dist\WoSBWorkbench-3.6.0-Update.zip` — this file contains `wosb-update.json` and compiled binaries and is selected in **Workbench → Updates**.
- `dist\Installer\WoSBWorkbench-3.6.0-Setup.exe` — optional standalone installer.
- `dist\WoSBWorkbench-3.6.0-Portable.zip` — standalone portable application package.

**The downloadable source ZIP is not an in-app updater patch.** A Windows compiler/build host is necessary to create binaries. Always back up the wiki database first, although the updater is designed to leave `%LOCALAPPDATA%\WoSBWorkbench` untouched.
