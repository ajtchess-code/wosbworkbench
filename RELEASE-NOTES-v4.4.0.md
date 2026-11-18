# WoSB Workbench 4.4.0

## New
- **Wiki website** (Datamining → Build wiki website): a public fan wiki in the style of classic game wikis.
  Left navigation, search, a page with an infobox for every ship, cannon, ammo type, upgrade, crew unit,
  captain skill, resource, port and achievement, sortable category tables, and your guides. Tools built in:
  damage simulator, wind & sailing (regular and unique wind roses), ship comparison, hitbox viewer.
  It never publishes code, file paths, research pages or game model files. The output is a static folder: open it
  locally or upload it to GitHub Pages or any web host.
- **Rebuild ship hitboxes**: hull, sail (4 slices each) and mast zones for every recovered ship, built with the
  client's own hitbox rules, including ships with separate external hit models. The Ship 3D viewer uses them automatically.
- **Damage model reference + simulator**: how the client applies HP loss, the 13 s sinking timeline, instant
  sinks (mortar, powder keg, stern, fire), rams speeding up flooding, weighted sail damage, crew, cannon, breach
  and fire effects. Adds the wiki pages "Damage and sinking", "Damage formula calibration", "Ship hitboxes".
- **Message layouts from decompiled source**: after a decompile, field-by-field layouts of every serializable
  type, including fields that are only present when a flag is set (Research/Protocol/Message-Schemas.json).
- **Unpack launcher code (app.asar)** and **Free disk space** (old duplicate catalogs).

## Fixed
- Install detection saved the **Workbench's own folder as the game install** (it matched "WoSB" in Add/Remove
  Programs). Scans, coverage and decompiles were analyzing this app. It's now repaired automatically at startup.
- Reruns wrote catalogs to Catalog-2, Catalog-3… (~2.3 GB each) while importers kept reading the **oldest**
  one. New runs now replace Catalog (the previous one is kept as Catalog-previous).
- Decompile, protocol extraction, combat scan and Full Recovery's code index skip the bundled .NET runtime
  (~200 DLLs). Full Recovery previously hit its method cap before reaching the game's engine assemblies.
- Decompile keeps each install in its own folder; decompiling the launcher no longer overwrites the game's summary.
- Combat scan no longer logs an error for every native DLL.
- Capture analysis: the server stream was mis-framed when the first packet was larger than 16 KB. The
  confirmed 5-byte WoSB transport header is now recognized automatically, and no fake opcodes are guessed
  from obfuscated payloads. Marker windows now report frame counts and sizes.
- Coverage report: Ogg video, Electron/Chromium files, certificates and JSON-in-.bin are recognized; the
  Full Recovery ledger is now found for all-clients runs.
