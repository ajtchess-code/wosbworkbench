# WoSB Workbench v4.3.4 — Compiled FX Investigation & Provisional Damage Model

**November 17, 2026** — Research update built on v4.3.3. This is **not** a complete
reimplementation of WoSB's original graphics shaders or server damage system.
The user-owned installed client remains read-only. Existing Workbench database,
ship model exports, texture catalog, capture recordings, and research notes are
not deleted or modified.

## Game-native graphics investigation

- Added **Discovery Center → Inspect compiled shaders**, a GUI action that lets
  you choose the installed game folder. It reads shader-named XNBs using the
  existing XNA `EffectReader` extractor and writes
  `%LOCALAPPDATA%/WoSBWorkbench/Research/ShaderAudit/Shader-Audit.json`.
  It also saves extracted compiled FX binaries locally in `CompiledEffects`.
- Results include relative game paths, source sizes, SHA-256s, candidate binary
  signatures and **candidate** readable strings, as well as explicit flags that
  parameters, techniques, render states, and shader implementations are **not
  decoded**. Strings must not be mistaken for resolved shader parameters.
- Added standalone `Inspect-Game-Shaders.cmd` for source-build users; it writes
  into `%LOCALAPPDATA%/WoSBWorkbench/ShaderAudit` and can be run without opening
  the Workbench GUI. The chosen game folder is scanned read-only. The compiled
  `.fxb` files remain on the user's local computer and are **not bundled into
  the distributed source code**.
- The existing ship viewer still uses a reconstructed WebGL material pipeline.
  This update **does not** automatically execute Direct3D/XNA FX binaries in
  WebGL, recreate original lighting passes, or guarantee exact ship skins. That
  work needs compiled-effect format decoding, matched effect/material runtime
  parameters, and game-versus-viewer image validation. See **Next rendering
  blockers** below.

## Educated damage calculation (research, not verified HP)

- Added **Mechanics Lab → Combat damage hypotheses** with cannon/ammo choices,
  user-entered armor and angle, hit count, attack bonus and bow protection.
- Evaluates two alternative **unverified** models: a hard penetration gate and
  a smooth transfer. Uses real catalog cannon penetration/poundage and ammo
  factors. Preserves the recovered client armor expression
  `BasicArmor * (1 + GetBonus(5,1)) + GetBonus(13,1)`.
- The model's angle-dependent armor and additive penetration assumptions are
  explicitly labeled hypotheses; it does not infer a direct HP number without
  measured shot data, or confuse the `Poundage` value with HP damage.
- Added `Estimate-Damage-Hypotheses.cmd` for source users and a Python CLI
  (`damage_hypotheses.py`) that can also incorporate explicitly supplied,
  normal-incidence **measured** HP calibration; results remain approximate.
- Starter demonstration: `WoSB-42pdr-Damage-Hypothesis-Example.json` outside
  the source ZIP (generated separately), using a hypothetical armor 12 target.
  **Not** the Golden Bale's confirmed armor or actual HP damage.

## Current evidence and blockers

- v4.0 recovery: **830 decoded models, 1,545 textures, 32 identified unsupported
  shader/effect assets** (the latest scanner can export compiled effect blobs).
  Indexed model-material filenames are *candidates*, not validated bindings.
- Client IL confirms dynamic armor and the final `DamageData.HealthDamage`
  handoff to ship HP. It does **not** establish the earlier armor penetration,
  projectile-energy transfer or server-authoritative hitbox decision.
- To complete rendering parity, first run the local shader audit and compare
  a default Huracan and one actual skin to in-game screenshots. To calibrate
  damage, record pre/post target HP under controlled single-shot conditions.
- Initial `Shader-Audit.json` will not contain fully parsed techniques,
  shaders, material assignments, vertex layouts or render states. Do not
  claim native shader parity based solely on extraction success.

## Build

Extract the entire source ZIP; run `Build-Update.cmd` on Windows using Python
3.13. Choose the resulting **compiled** `dist/WoSBWorkbench-4.3.4-Update.zip`
in the installed Workbench's Updates page. The distributed source ZIP is not
that compiled update. The app includes all the previous 4.3.3 fixes.

## Validation

- Python full regression suite: **105 passing tests** on the current environment.
- Python compilation smoke test: passed.
- Actual Windows frozen build, real game XNB shaders, and GPU in-game parity:
  **not run in this environment**. These require the user's Windows client.
