# WoSB Workbench v4.1 — Codex, Recovery & Mechanics Research

## Executive summary
This is an incremental, integrated update over v4.0. It does not reproduce every unrecovered WoSB mechanic; the purpose is to make known behavior testable, expose remaining gaps, and keep visual modeling, research, and the local wiki connected. No assets or binaries copied from the user's game are included in this source archive.

### Implemented in this release
- **Ship geometry audit:** `model_quality.py` validates full OBJ geometry, degenerates and UV references without thinning faces. The Ship 3D HTML viewer includes a diagnostic summary and writes `*-Mesh-Quality.json` beside exports.
- **Material/skin rendering:** canonical matching for source and replacement material identifiers fixes the previous mismatch between skin diagnostics and actual rendering. Transparent sails are rendered in a separate pass with approximate back-to-front ordering, while preserving visible surfaces and full source geometry. This is an approximation, not a recreation of the game's shader.
- **Shot direction research:** `combat_scenarios.py` calculates impact obliquity from an incoming direction and surface normal, including camera-directed setups. It reports verified client armor when available; it does not fabricate projectile HP damage.
- **Client-calculation verification:** `mechanics_verified.py` adds `Common.Game.CannonBall::SailDamageEnergy` (three-hit energy factor) and the `Common.Resources.CannonGameInfo::get_Penetration` editor override in addition to v4.0 armor formulas. Original extracted IL evidence is in `Research-Combat-Code`. `engine/evidence_signatures.py` audits newly extracted IL files so these assertions can be reevaluated after game updates.
- **Local WoSB Codex:** new Shipyard Atlas, readable guides (cannons, ammunition, armor, wind, fittings and hitboxes), ship comparison tools, an expanded equipment library, local fitting notes, controlled-shot observations and wind observations. The shipyard uses recovered artwork and in-game catalog classification; it does not invent progression edges. Ship articles link to local exported 3D viewers when available.
- **Multi-installation recovery:** `engine/recover_everything.py` finds game installations, drives separate resumable recoveries, compares inventories and creates compact review ZIPs for the remaining decoding issues. Workbench exposes a **Recover ALL installations** control. Stand-alone `Recover-All-Clients.cmd` is also included. Existing single-installation recovery remains supported.
- **Simpler desktop navigation:** primary items stay visible, while specialist tools are grouped behind **More research tools**. No legacy page has been removed.
- **Offline emulator research sandbox:** `offline_emulator.py`, `offline_emulator_cli.py`, and `samples/Offline-Emulator-Fixture.json` run deterministic local test worlds and recorded-damage observations. This is NOT a playable server or packet-protocol implementation.
- **Tests:** 50 Python tests pass in the Linux source environment; source wiki routes and JS syntax have also been checked.

### Features NOT verified or completed
- Exact game appearance: original proprietary shader parameters, all animations and rigging, in-game lighting and every ship skin require client comparison and additional asset decoding.
- Original authoritative collision hulls: candidate hitbox shapes can be viewed, but their gameplay use and transforms are not fully proven.
- HP vulnerability maps and exact ricochet/penetration: direction-dependent color mapping is based on geometry alone, NOT the authoritative damage model. No full end-to-end cannon, ammo, mortar, heavy mortar, sail or barrel damage formula has yet been demonstrated from source/client observations.
- Accurate shipyard unlocking and equipment rules: fitted items and rank-based ship browsing are research tools, not game-enforced requirements.
- Finished server emulator: official protocol definitions, server-side rules, authentication/state persistence and gameplay interoperability have not been recovered or implemented. Existing network research is passive and opt-in.
- Windows installer build and final visual comparisons have not been tested in this non-Windows environment.

### Building and updating
Run `Build-Windows.cmd` on Windows with Python 3.13; optional Inno Setup 6 compiles an installer. `Build-Update.cmd` produces the new `dist\WoSBWorkbench-4.1.0-Update.zip` from the COMPILED executable tree, not from this source ZIP. `%LOCALAPPDATA%\WoSBWorkbench` stores user research data and is preserved.

### Suggested high-value validation
1. Open Apostolov: compare transparency off/on and verify mesh and per-material face counts against the original XNB.
2. Apply a known Vasa or Huracan design; use the diagnostics to confirm every substitution has a resolved texture, then compare screenshots against the running game.
3. Run **Recover ALL installations**, gather `WoSB-Review-Part-*.zip`, and examine any `Code-Recovery/Verified-Client-Methods.json` warnings.
4. Record repeated in-game controlled damage tests at multiple hit locations, angles, ammunition and equipment states. Do not label unverified HP estimates as exact.
