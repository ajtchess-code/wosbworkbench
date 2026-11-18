# WoSB Workbench v4.3.3 — Ship Appearance Loading Repair

**November 17, 2026**

This is a focused follow-up to v4.3.2. Existing database, model library, gameplay
captures, raw game files and research records are left unchanged.

## Fixed in source

- Automatically locate installed WoSB game assets at `C:\Games\World of Sea Battle`
  (and common Steam location) when the appearance asset folder is blank. A
  user-chosen directory still takes priority. Environment variables
  `WOSB_GAME_ROOT` and `WOSB_ASSET_ROOT` are supported.
- For a standalone offline ship viewer, export per-material PNG plus a
  companion per-material `*.png.js` loader. The latter returns a `data:` image
  on demand so WebGL can use local images without relying on `file://` image
  cross-origin behavior. HTML viewers remain locally portable with their
  adjacent `-assets` folder.
- Keep original base textures loaded as fallback even if a selected design's
  replacement image fails to decode. Show **design not visually applied**,
  **partial design**, or full matching-material coverage based on loaded GPU
  texture objects, not mere dropdown entries or available catalog names.
- Correct the viewer's misleading "no image supplied" status when client
  material textures exist, and show textured-triangle coverage.
- Export an `-Appearance-Diagnostics.json` beside each generated ship viewer,
  listing matched/unmatched design identifiers, unresolved materials, texture
  decoding errors, and source material IDs. No packet payloads or installed
  game paths are written in that report.
- Cache material-label lookups to avoid per-frame repeated O(n) texture-key scans.

## Install/update

On Windows, extract the complete source to a writable folder, run
`Build-Update.cmd`, and install the resulting compiled updater ZIP from the
Workbench Updates page. The provided source ZIP is **not** a precompiled EXE.

Open **Ship 3D**, choose a ship with recovered OBJ geometry, verify the
**Game Data or research ZIP parts folder** points at your actual installation
(or rely on auto-detection), then select **Open visualizer + damage lab**.
Re-exporting the viewer is required to rebuild its per-material files. Keep
`ship-...html` and `ship-...-assets` together when copying them.

## Limits

This patch repairs source texture lookup and offline browser delivery, not the
original game's proprietary shader, dynamic UV animation, model effect settings
or collision/damage formulas. Original textures are matched by exact material
basenames and remain **candidates** until checked visually against the game.
The Windows browser, full installer, and the user's actual asset installation
are not available in this development environment and still need live testing.

## Validation

Python test suite: 99 tests passing. Added 4.3.3 fixture regression tests for
installed-asset detection, default + swapped material script delivery, and
appearance diagnostic export. JavaScript syntax checked using Node.js.
