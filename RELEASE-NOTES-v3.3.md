# WoSB Workbench v3.3 — Discovery Center update

This release integrates all six first-pass discovery capabilities:

1. New formats and content readers flagged from reports and local catalog.
2. Source-scoped cross-reference checks for materials, recipes and ships.
3. Candidate modifier/field/method relationships for the mechanics wiki.
4. Game/Steam/Launcher comparisons of file hashes and Game/Steam data definitions.
5. Prioritized XNB decoder failure queue including model and image categories.
6. Evidence-linked, editable wiki research tasks; user edits preserved.

Also: redesigned sidebar and dark app theme, repaired packaging of
`engine/AI-Handoff-Guide.md`, and fixed per-user Inno Setup detection.

## Tested

- Python `compileall`: PASS
- Automated tests: 16 passing
- GUI under virtual display: starts and switches to Discovery Center
- Imported actual `WoSB-v3-Reports.zip` scan: 3 roots, 71 audit findings,
  10 grouped decoder-priority entries, 1,030 shared files with different hashes
  between Game and Steam. These figures reflect a specific uploaded report
  and are not estimates of total WoSB coverage.

## Not finished

- Actual XNB Windows LZX decompression improvement and reconstructed 3D models.
- Fully reconstructed live-server damage, wind or crafting calculations.
- Windows EXE/Setup build or upgrade validation in this environment.

Build with `Build-Windows.cmd` on Windows and verify the resulting desktop
application before replacing an existing installation.
