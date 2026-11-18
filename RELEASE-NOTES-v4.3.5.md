# WoSB Workbench v4.3.5 — Advanced Research & Pre-Release Hardening

November 18, 2026. Based on the **complete v4.3.4 source**, preserving all
v4.3.2 capture improvements and v4.3.3 appearance / v4.3.4 shader and damage
research additions. This is a **complete editable source package and Windows
builder**, **not** a precompiled Windows executable.

## Implemented in this source update

- **Advanced Research** sidebar page: run bounded recovery-ledger triage,
  read-only mesh quality and BVH preparation, TCP continuity inspection,
  catalog Game/Steam comparisons, video transient candidates, CPU benchmark,
  source/runtime release checks, and create/export controlled HP observations.
- **Triangle geometry research** (`advanced_geometry.py`): exact visible
  OBJ-triangle raycasts with BVH acceleration, impact point/normal/angle,
  stable mesh-group association, and a configurable orthographic sample grid.
  Heatmap numbers are explicitly **uniform-armor hypotheses**, not the game's
  actual collision mesh or server damage result.
- **XNA vertex declarations** (`engine/xnb_geometry.py`): annotate recovered
  vertex format, channel, offset, stride overflow, and unknown shader inputs
  in the original XNB geometry conversion report.
- **Network continuity** (`advanced_network.py`): offline sequence-aware
  directional TCP segment assembly, retransmit/gap counts, bounded memory,
  non-content protocol hints, user-anchored UTC/video clock calibration, and
  explicit target-ID stability without guessing identities.
- **Asset recovery** (`advanced_assets.py`): failure categories/retry triage,
  exact SHA-256 cross-client asset inventory/difference reports, and ship-design
  material coverage diagnostics that distinguish a found file from verified
  shader behavior. The original client is never modified.
- **Experiment database** (`advanced_experiments.py`): validated user-entered
  pre/post HP measurements, independent observation records, mean/variance and
  rough confidence intervals by identical measured configuration, CSV/JSON
  evidence ZIP, and source manifests. No actual HP values are invented.
- **Game research notebooks**: sailing telemetry/turn radius, a recovered
  wind-component comparison with user-set coefficients, user-defined classical
  projectile trajectories, sail-condition associations, candidate named gun
  mounts, user-configured loadout modifier hypotheses, recipe dependency
  graphs and source-hashed catalog diff/lookup.
- **Video research** (`advanced_video.py`): bounded FFmpeg frame-change
  detection to produce manual-review timestamps, *not* classified cannon hits.
- **Release safety** (`advanced_release.py`, `advanced_io.py`): versioned
  SHA-256 source inventory, Python parse checks, critical-file gate, atomic
  research report writes, optional frozen-resource audit, integrity-checked
  complete source ZIP generation, and CPU geometry benchmark.

## New command-line tools

Run `py -3.13 advanced_research_cli.py --help` for all operations, including
`geometry`, `network`, `recovery`, `snapshot`, `diff`, `video`, `benchmark`,
`sync`, `targets`, `sailing`, `sails`, `trajectory`, `gunports`, `outfit`,
`catalog`, `experiment`, `experiments-report` and `release`.

Examples (execute from source folder; paths are local paths on *your* PC):

```powershell
py -3.13 advanced_research_cli.py release --out "$env:TEMP\WoSB-release-qa.json"
py -3.13 advanced_research_cli.py benchmark --out "$env:TEMP\WoSB-benchmark.json"
py -3.13 advanced_research_cli.py geometry "C:\path\ship.obj" --out "$env:TEMP\WoSB-Geometry"
py -3.13 advanced_research_cli.py recovery "C:\path\Reports\AssetLedger.jsonl" --out "$env:TEMP\WoSB-retry-triage.json"
```

The `geometry` command can accept `--armor 12 --resolution 16` to generate an
**illustrative** heatmap using a user-entered armor assumption. It does not
establish the actual armor of a named ship. For the GUI open **Advanced Research**
after building and launching.

## What is *not* finished

See `FEATURE-STATUS-50-v4.3.5.md` for all 50 requested work items.
In particular, these cannot be certified by a source-only update:

- Full original Direct3D shader execution or perfect game skin/material parity.
  Compiled FX blobs are inspected, not executed as original game effects.
- Recovery of authoritative projectile hitboxes, armor-zone values, ricochet
  and server-authoritative damage formulas for all ships. Rendering geometry,
  client metadata and an HP-change sample do not prove this.
- Automatic proof of cannon firing, a hit, or target HP changes solely from
  a frame difference or a packet size; these remain *candidates* for review.
- A verified gun-port count from candidate mesh component names.
- A genuine clean Windows install, frozen EXE, GPU render, or live multi-target
  capture test. These need the actual Windows game environment.

## Test status

The original v4.3.4 **105 automated tests** passed before integration. The complete
v4.3.5 source passed **130 tests**, including 25 new regression tests. They cover geometry, asset triage, TCP continuity,
clock synchronization, target identity, HP experiments, sailing, catalog
comparison, vertex semantics, optional video, source gate, loadout hypotheses
and CPU benchmarks. Consult the final included `TEST-RESULTS-v4.3.5.txt` for
actual verified test counts and platform limitations.

## Windows build/install

1. Extract the complete source ZIP to a normal writable directory.
2. Open its folder and run **Build-Update.cmd** with Python 3.13 on Windows.
3. To update an already installed Workbench, choose the resulting **compiled**
   `dist\WoSBWorkbench-4.3.5-Update.zip` in the Workbench Updates page.
4. Do **not** install the source ZIP as an updater; it is intentionally a
   separate artifact. To create a fresh installer, install Inno Setup 6 and
   build using `Build-Windows.cmd`.
5. Existing `%LOCALAPPDATA%\WoSBWorkbench` database, recovery, screenshots,
   footage and research data remain outside the installer source directory.
   Existing original game files are never modified by the research tools.

## Known research limitations

Recovered meshes and sampled ray intersections are not equivalent to confirmed
server-side collision geometry. Filename-matched textures and parsed compiled
FX strings are not proof of shader parity. User-entered armor, wind, projectile
and damage parameters produce labeled hypotheses, **not exact game mechanics**.
