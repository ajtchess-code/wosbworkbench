# WoSB Workbench v3.10.0 — Full Recovery & Textured Ship Research

**Release type:** buildable Windows source; use the included `Build-Windows.cmd` to produce the native Windows binaries. This source ZIP is **not** the installed executable or a compatible updater ZIP.

## New in v3.10

### One-button Full Recovery

Open **Full Recovery**, choose the installed game folder, then click **Recover Everything**.

- Recursive read-only inventory of game XNB assets; classify actual XNB content readers rather than extensions alone.
- Recover supported 2D textures to PNG and XNA 3D meshes to OBJ, preserving component and material identifiers, source path, and source SHA-256.
- Preserve optional decompressed asset payloads for unsupported custom readers and original archived client assets for later interpretation.
- Index readable .NET assemblies and method IL without executing them, with explicit method tokens and an error inventory.
- Create the full client catalog and a model-texture candidate-link report.
- Resume unchanged successfully processed assets using an SQLite checkpoint ledger; changing the decoder revision invalidates obsolete cached conclusions. Use **Recheck unchanged XNB assets** to bypass the cache manually.
- Emit a detailed machine-readable `Recovery-Status.json`, per-asset `Reports/AssetLedger.jsonl`, and human-readable `Reports/RecoverySummary.md` with *decoded*, *unsupported*, and *failed* counts.
- Store all results outside the game installation, under `%LOCALAPPDATA%\WoSBWorkbench\FullRecovery\<game-id>`.

### High-fidelity appearance research

- Ship 3D accepts a game Data folder **or a folder containing `WOSB-Research-Part-*.zip`**, including the split 36-part research handoff. The ZIP files are read individually; no giant handoff ZIP must be reassembled or extracted first.
- Match original per-part XNB material IDs and design catalog replacement pairs to the actual recovered image basename. The viewer keeps the original UVs from the v3.9 XNB geometry exporter.
- Export fully offline HTML with a sibling `-assets` folder containing original decoded images, rather than inflating one HTML file with every 2048px texture.
- Browser loads only the active ship design textures to WebGL, releases the previous design's textures upon switching, and preserves other skin choices on disk.
- New **Export textured GLB** button saves a standalone glTF 2.0 binary with vertex positions, triangle normals, UVs, per-part mesh tags, and matched PNG images. The material shader is an approximation: no claim to duplicate custom game shaders, animation, or collision behavior.
- Existing large-model display sampling remains enabled; GLB exports inherit the visible sampled geometry and declare this fact in their metadata.

### Code-evidenced mechanics

- Recovered client formula: `BasicArmor = PatArmor × (1 − AllStatFine)` (`Common.dll:0x06001ee8`, for player ships).
- Recovered client formula: `Armor = BasicArmor × (1 + GetBonus(5, true)) + GetBonus(13, true)` (`Common.dll:0x06001f6f`).
- The 3D shot viewer now exposes these as *verified client getter calculations*, using explicit, raw user-entered inputs with their assumptions documented.
- Relevant accessors also identified: `ReduceDamageToNose = GetBonus(18,true)` (`0x06001f95`); `WeaponPenetrationBonus = GetBonus(54,true)` (`0x06001f7c`). No unverified deflection, region or damage multipliers are automatically applied.
- Keep cannon/ammo/ship catalog values and optional empirical shot comparisons separate from hypothetical HP estimates.

## Validation completed in this environment

- 31 Python unit tests passed: historical Workbench behavior, recovery/SQLite resume, ZIP texture lookup, offline sidecar exports, GLB structure, and client armor arithmetic.
- Ship viewer JavaScript passed a Node.js syntax check after injecting a small test-data placeholder.
- A Vasa demonstration was exported from a user-provided v3.9 material-tagged OBJ and decoded client PNGs. This is a texture-mapping research sample, not a verified screenshot of the live game.

## Important limitations

1. Windows installer/portable executable build could not be run in this Linux environment; run `Build-Windows.cmd` on Windows 11 with Python 3.13 to produce the executable and offline updater.
2. Full Recovery has **not** been run end-to-end against your local original game installation; unsupported custom XNB content readers will be logged for targeted follow-up.
3. The current model reader recovers supported XNA geometry but not every proprietary shader, animation, bone-weight, or special-effects structure. Texture matches by basename are evidence, not proof that game shader behavior is identical.
4. Geometric helper meshes, extracted `Corpus/Mast/Sail` enum values and named collision methods do not independently establish which surfaces take gameplay damage.
5. No complete server-authoritative HP damage, penetration, or ricochet formula has been verified. A client-side armor getter is **not** the final damage formula. Show no invented HP damage as a factual game result.
6. Opening exported HTML away from its sibling `-assets` directory can make textures disappear. Keep the two together or use the standalone textured GLB.

## Build/install

1. Extract this ZIP. Open `WoSB-Workbench-v3.10`.
2. Run `Build-Windows.cmd` (or the PowerShell build script in `packaging`). Python 3.13 is required for building; dependencies are installed into `.build-venv`.
3. To update an existing Workbench, choose `dist\WoSBWorkbench-3.10.0-Update.zip` inside its offline updater. **Do not select the source ZIP or portable ZIP.**
4. Alternatively run `dist\WoSBWorkbench\WoSBWorkbench.exe` directly or install the optional `dist\Installer\WoSBWorkbench-3.10.0-Setup.exe` generated if Inno Setup 6 is installed.
5. In **Ship 3D**, choose your installed game Data folder or the directory containing `WOSB-Research-Part-001.zip` through `...036.zip`. Recover the current XNB model to OBJ with v3.9+ to preserve material IDs.
6. In **Full Recovery**, choose your local game installation root and click **Recover Everything**. Open the saved recovery folder to inspect the coverage report and failures.

**Read-only policy:** The scan never executes game DLLs, alters the installed game, bypasses game protection, or accesses remote servers. Extracted files are user-managed and may contain copyrighted game assets; keep them private and respect the game license.
