# WoSB Workbench 3.4.0 — Multi-Scan and Ship-Model Research

## Changes verified against the uploaded three-scan report ZIP

- Imports `Reports/Scan1`, `Reports/Scan2`, `Reports/Scan3` from either a ZIP or a local folder, mapping their data to **Game**, **Launcher**, and **Steam** rather than one anonymous Imported source.
- Skips duplicated `Catalog-2` data when the equivalent primary catalog record exists. This prevents doubled source-processing counts and overwritten records.
- The Discovery Center now audits nested and Windows-style report paths. **Audit my saved scans** works directly with `%LOCALAPPDATA%\WoSBWorkbench\Reports`.
- **Import saved Scan1/2/3 reports** imports catalog data from that same location, including combat-method candidates and loose XNB ship-model filenames.
- Ship asset index includes both catalog archive model entries and loose `CommonData/Models/Ships` assets, without treating model names as verified meshes.
- Added a persistent, build-aware `Models` library. Importing a user-supplied, validated OBJ once associates it with the selected ship for later viewer sessions.
- Ship-model filename matching intentionally does **not** equate numeric asset IDs with gameplay ship IDs. The provided reports demonstrate they differ for some ships.
- **Export XNB samples** collects a small set of original model XNB files explicitly on user request, with size limits and SHA-256/frame diagnostics. Review any raw game files before sharing them.
- Empty Ship 3D viewer is replaced by an actionable explanation of the current decoding blocker.
- Windows build script now produces a **real compiled application ZIP patch** `dist\WoSBWorkbench-3.4.0-Update.zip`, min supported version `3.3.0`, in addition to the Windows installer and portable ZIP.

## Findings from the supplied reports

- Game: 3,091 files analyzed; Steam: 3,090; launcher: 153.
- XNB decompression failures: Game 2,473 / Steam 2,472 (broader image-decoder failures: 2,475 / 2,474). The latter includes attempts on non-image assets and must not be presented as 2,475 missing images.
- Catalog issues: 968 and 969, predominantly LZX failures.
- 82 loose ship-named XNB files in the Game installation's XNB header list, with certain external-hitbox filename candidates. Filename evidence is **not** verified collision geometry.
- 1,030 differing file hashes between the normalized game installations; cross-build data needs provenance.
- Test import: 84 ship entries per build, 3,961 combat candidates per build, and 188 model-asset candidates per build; copied Catalog-2 outputs were not imported twice.

## Known limitations

**No validated XNB model decompressor or WoSB proprietary mesh-to-OBJ converter exists in this release.** The combined reports contain metadata, but not raw game XNB bytes needed to diagnose LZX failures or reconstruct geometry. No live game damage multiplier or vulnerable hitbox is inferred from filenames. A saved OBJ is user-provided geometry, not verified game geometry.

A Windows `.exe` or Inno Setup installer cannot be compiled in this Linux environment. This archive contains the complete **Windows build source**. On Windows, run `Build-Windows.cmd`; it will compile the EXE, installer (when Inno Setup is installed), and the updater-compatible ZIP. **Do not select this source archive in the installed application's Updates tab.**

## Upgrade procedure from installed 3.3.0

1. Extract the `WoSB-Workbench-v3.4-Complete-Source.zip` package.
2. In the extracted `WoSB-Workbench-v3.4` directory, double-click `Build-Windows.cmd` (requires Python 3.13; Inno Setup 6 already installed for your account).
3. Once the Windows build completes, open **installed WoSB Workbench 3.3 → Updates → Choose update ZIP**.
4. Choose `dist\WoSBWorkbench-3.4.0-Update.zip` from the *new build directory*, inspect its version/hash validation, and approve the update. The updater backs up the replaced program files and restarts the application.
5. Open **Discovery Center → Audit my saved scans** and **Import & export → Import saved Scan1/2/3 reports**. Your existing wiki database remains under `%LOCALAPPDATA%\WoSBWorkbench`.

Archive SHA-256 hashes verify content integrity, not who published the update; use only your own locally built patches or a trusted release.
