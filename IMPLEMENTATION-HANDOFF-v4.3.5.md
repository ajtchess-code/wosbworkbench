# WoSB Workbench v4.3.5 — implementation handoff

**Artifact:** Complete editable v4.3.5 source and Windows builder, based on the actual v4.3.4 archive and therefore retaining the v4.3.2 capture features and subsequent v4.3.3 and 4.3.4 work.

## Delivered

- New Advanced Research GUI route, measured HP observation recording, offline evidence exports, diagnostic button flows.
- New geometry BVH raycasting, mathematical impact-angle analysis, provisional armor-parameter heatmap, and vertex declaration diagnostics.
- Offline TCP continuity checks, retransmission/gap tracking, privacy-safe target identity and video/packet time alignment.
- Recovery error triage, cross-client asset hashing and differences, design-to-material diagnostics and source confidence flags.
- SQLite experiment data, comparative statistics, video transient candidates, sailing trajectory/maneuver studies, loadout hypothesis and candidate mount analyses.
- Source release verification, atomic report writes, size guards, performance smoke benchmark and 25 added tests.

## Verification

**130 Python tests passed** on Linux/Python 3.13. Bytecode compilation, command-line help, benchmark and source-manifest smoke checks passed. The source ZIP includes Windows build scripts but **not** a precompiled Windows executable. Consult `TEST-RESULTS-v4.3.5.txt`.

## Not represented as complete

The original list of 50 improvements is tracked individually in `FEATURE-STATUS-50-v4.3.5.md`. Full original Direct3D shader parity and skin application, authoritative game hitbox discovery, server-calibrated exact damage, live Windows GPU/capture tests, and complete game client version validation remain unverified or partial. Some analyses are deliberately labeled **hypotheses** rather than recovered game mechanics.

## Windows build

Extract the **source ZIP** on Windows, run `Build-Update.cmd` using Python 3.13, and use the resulting `dist\WoSBWorkbench-4.3.5-Update.zip` from the installed Workbench's Updates panel. Do **not** try to install the complete-source archive as the updater.
