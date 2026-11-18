# WoSB Workbench v3.8.0 — Ship Visualizer & Ballistics Lab

Built from the original v3.7.1 source archive and user-supplied Scan1 catalog / Vasa XNB debug sample.

## What is implemented

- The existing ship XNB geometry converter now writes original XNA `TextureCoordinate` UVs (Vector2 / HalfVector2) into the OBJ. The known Vasa sample was decoded and tested at 168,474 vertices and 155,166 triangles, preserving 93 named parts. This is a feature for *new* recoveries; preexisting OBJ files lack UVs and need re-recovery.
- Separate visual layers for hull, sails, rigging, candidate helper meshes, duplicate LOD hulls, and research hitbox overlays. `AverageBox`, `Hitbox`, and `ShipCorpusShapeStrcture` are flagged as possible helper/collision-related geometry and hidden by default. `ShipLowCorpus` and `ShipMin` are hidden by default as duplicate LODs. These categories are based on mesh names only, **not validated physics or damage regions**.
- Offline image texture layer using user-selected PNG/JPG/WEBP or locally owned Texture2D XNB; a chosen image is assigned to UV-mapped visible geometry. Ship-specific texture atlas matching is *not* automatically recovered from `EffectMaterialReader` yet. Do not call this visually equivalent to the game unless exact image/material matches are established.
- Click any visible triangle: offline projected-triangle hit test, local coordinates, actual triangle normal, estimated impact obliquity, component name, impact marker, and provisional bow/side/stern approach direction (user-settable forward axis).
- Offline mined catalog: 42 `Cannons`, 21 `CannonBalls`, 84 `ShipsToPlay`, 81 `ShipsBasics`, 44 `ShipUpgradesNew`, 55 `CaptainSkills`. Preserves underlying extracted names, IDs and fields from `Reports/Scan1/Catalog/AI-Data`.
- Research calculator: displays original cannon penetration, poundage, ammo damage factor and projectile properties, target ship health/armor, a **relative** shot index and a geometric effective-armor proxy.
- Optional user-measured baseline HP and measured region multiplier to produce an explicitly user-calibrated result. Opt-in cosine attenuation and limited effect-string interpretation are *hypotheses* and off by default.
- Exports an offline per-shot research JSON report including source provenance and evidence caveats.
- Existing wiki, XNB decoder hotfix, model recovery, catalog importer, network lab, reporting and offline updater are retained.

## Not yet proven / not implemented

- An automatic reconstruction of all original game texture/material associations. Per-part material labels in the example model are generic and do not link to concrete PNG/XNB files.
- True server-authoritative ship-region damage coefficients, gun penetration or deflection/ricochet code, consumable effects and equipment stacking.
- A hitbox overlay automatically derived from the `AverageBox` or `Hitbox` rendered mesh. These are **geometry labels**, not confirmed game physics objects.
- A verified numeric WoSB damage/HP result without player-calibrated shot measurements.

## Installation / rebuild

On Windows 11, extract this source ZIP to a fresh folder and run `Build-Windows.cmd` with Python 3.13 (tkinter) and the dependencies from `engine/requirements.txt`. Inno Setup 6 is optional for a Setup.exe; otherwise run `dist/WoSBWorkbench/WoSBWorkbench.exe`. The build creates a portable ZIP and updater ZIP. Back up `%LOCALAPPDATA%/WoSBWorkbench` before reinstalling; the app's data is persistent by design.

If upgrading from v3.7.1, use **Recover XNB → OBJ** again on the original ship XNB to generate UVs. You do not need a new network capture for visualizer research.
