# World of Sea Battle — AI handoff guide

This catalog contains game-client-accessible information recovered by the WoSB Workbench extractor.

## Start here

Read `AI-MANIFEST.json`, then the `AI-Data/*.jsonl` tables. Each line is a separate JSON record. Retain `Source` and `SourceRecord` fields. Use `Spreadsheets/` for human-readable CSVs and `CodeArchive/` for static IL evidence where available.

## Important limitations

- Client-derived values are not proof of live server-authoritative damage or economic rules.
- Missing tables may be extractor limitations, incompatible builds, or unknown file formats.
- Crafting output amounts per production operation are not necessarily hourly rates.
- Decoding and model failures must remain visible; never fabricate images, hitboxes, or formulas.
- `START-HERE-FOR-AI.md` and extraction diagnostics should accompany exported research.

For human-curated interpretations, see the separate offline wiki in WoSB Workbench.
