# v3.9.0 — Local appearance and observed damage research

- Correct per-part OBJ material name from XNB `SegmentTextureInfoTag.segment` (formerly generic `Texture`).
- Actual 595 design elements catalog snapshot, including 157 ShipFullDesign variants.
- Offline ship-specific design selector uses original base→replacement mappings.
- Read-only local game texture scanner: exact filename, local XNB Texture2D decode,
  bounded base64 embedding, missing texture diagnostics. No redistribution of game assets.
- Two-pass OBJ display sampler enables large ships (e.g. Huracan) in the browser
  without exhausting geometry memory; full OBJ left intact. Display sampling is labeled.
- User-selected combat observation CSV provides measured sample averages for
  same loadout/ship/zone/distance/angle, never a fictitious server formula.
- Observation CSV template download from the selected point, for controlled in-game trials.
- Extracted client getter IL for basic/effective armor and weapon penetration bonuses.
- Existing v3.8 features remain intact.

Known limitations: material/texture atlas assignment based on XNB segment labels
and catalog replacements requires local assets; not all XNB texture formats may decode.
Full server damage/deflection logic and gameplay hitboxes are not verified.
