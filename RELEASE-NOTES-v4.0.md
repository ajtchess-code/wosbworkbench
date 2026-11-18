# WoSB Workbench v4.0 — Local Codex & Mechanics Research

This release targets fidelity to **World of Sea Battle's own game files**, not historical reconstructions. It retains the v3.10 catalog, existing labs, updater and read-only extraction tools.

## Delivered in this source package

### Model and skin repairs
- Removed silent, per-triangle display sampling. All source triangles are preserved below an explicit 750,000-triangle browser limit; bigger files produce an error instead of a broken-looking ship. GLB export and actual game LODs remain the recommended path for larger files.
- Fixed OBJ `usemtl` changes inside the same named mesh: each material span now has an independent draw group, preserving the complete vertex/index/UV data.
- Added case-insensitive and extension-aware texture/material name matching. Design switching reports matched mesh labels and found replacement image counts, and falls back to the base texture if a replacement is unavailable.
- Added solid-surface diagnostic mode for texture alpha problems.
- Updated GLB export to honor compatible material aliases.
- Added game-geometry validation report for eight original XNB samples supplied during research.

### Mechanic and hitbox investigation
- Introduced a **camera-directed impact-angle heatmap** over actual recovered 3D triangles (geometric exposure, not HP damage).
- Added candidate bounding-box overlays measured from helper mesh triangles; also shows catalog `CorpusHitboxCenter`/`CorpusHitboxSize` when present, with warnings that game collision transforms and usage remain unverified.
- Retained clickable single-shot scenarios and evidence-aware armor calculations, with empirical shot CSV export rather than guessed in-game HP.
- Retained Sailing & Wind Lab with explicitly identified recovered/estimated variables.

### Local web wiki and shipyard
- New local-only browser Codex on `127.0.0.1`, with no external CDN or telemetry.
- Actual extracted shipyard background and available ship icons (numeric icon association unverified).
- Searchable shipyard grouped by recovered ship rank, readable ship profiles, static stat comparison bars, weapon/ammo catalog, special crew and upgrades selection, ship-design choices, ship fitting notebook, player-friendly notes and source disclosures.
- Interactive mechanics page: schematic shot-direction/angle view, wind-component curve, recovered armor getter and raw ammunition/cannon property references.
- Existing human-edited wiki articles are preserved by Workbench's database. Local wiki can be opened from the desktop Overview or with `Open-Local-WoSB-Codex.cmd`.
- The exact in-game progression tree and equip restrictions are **not yet verified**; no invented unlock links or stat stacking are shown.

### One-button Full Recovery and review ZIPs
- Existing checkpointed Full Recovery pipeline scans user-selected local game files and indexes XNB content, supported textures/models, managed-code metadata, catalogs, and model-to-texture links.
- New *failure-focused* output creates **independent ZIP parts capped at 45 MiB** (configurable): failed/unsupported entries, unresolved material links, code warnings, recovery summary and targeted method queue. Successful assets and bulk PNGs are excluded.
- Added method research index for projectile/damage, sailing and protocol-related candidates. Method names are leads, not verified formulas.
- Added a versioned offline emulator-research fixture scaffold for organizing future behavior observations. This is not a working game server.

## Known limitations / priority for future analysis

1. Exact WoSB shader settings (transparent surfaces, custom effects and animation bindings) remain incompletely decoded. Rendering matches recovered materials/UVs, not guaranteed engine visual equivalence.
2. Recovered `Corpus`, `Mast`, and `Sail` types and helper meshes are not automatically proof of authoritative projectile collision geometry.
3. The exact server-side equation for final cannon, mortar, barrel, sail and fire damage, armor penetration and deflection remains unresolved. Only evidence-backed client getters and user-calibrated observations should be called verified.
4. The camera heatmap does not infer damage multipliers from mesh shape. It displays angle exposure, while the HP-damage outcome remains unknown until demonstrated.
5. Large models over 750k triangles require the native GLB/LOD workflow; the browser will no longer truncate the mesh invisibly.
6. The installed Windows executable/installer and a complete scan of the user's local game client cannot be tested in this environment.
7. An actual protocol-complete, playable server emulator cannot be produced from static client catalogs alone. Passive, consented captures, behavioral fixtures and validated mechanics are needed. This release provides a research foundation, not a running emulator.

## Setup and validation

Build on Windows 11 with `Build-Windows.cmd` (Python 3.13; Inno Setup 6 optional). The builder produces a portable executable, a versioned updater ZIP, and a setup EXE when Inno Setup is available. Back up `%LOCALAPPDATA%\WoSBWorkbench` before changing installations.

Run `py -3.13 -m unittest discover -s tests -q` from the extracted source to check Python tests. Run `py -3.13 engine\full_recovery.py --game "C:\Games\World of Sea Battle\default\game" --output "%USERPROFILE%\Downloads\WoSB-Recovery-v4"` after installing requirements, or use the desktop Recover Everything button.

**Development note:** All original game files remain user-owned and local. The source ZIP ships source, application templates and the existing starter dataset. The full 36-part research archive and game binaries are not repackaged into this release.
