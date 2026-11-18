# WoSB Workbench v4.3 — Research Center & Player Codex

**Source release, November 17, 2026**

This is a cumulative upgrade to v4.2. It integrates a coherent research workspace and extensive local wiki functionality around the existing client extractor, ship viewer, footage/packet recorder, sailing lab and offline emulator research fixture. It **does not** claim the official server's damage calculations, complete proprietary shaders, collision model, ship fitting restrictions, or original network protocol have been reconstructed.

## Player-facing additions

- **Cleaner start screen.** Main actions link to Full Recovery, catalog, combined Mechanics Lab, local Research Center, Shipyard & fitting, ballistics, experiments, measured HP research, video/packet correlation, visual parity, setup and release checks. Specialist tools remain available under the existing expanded navigation.
- **Local Codex Research Center** (`/studio`) centralizes player-oriented research paths and evidence levels.
- **Ship Outfitting Studio** (`/workshop`) connects ship choice to the real recovered 84 ship records, available upgrades, special crew, captain skills and designs. A saved planning notebook exports the exact catalog description; original equip-slot rules and stacking are explicitly unverified. The design selection uses original ShipId assignments. Recovered game UI icons accompany fitting controls. Browser verification: selecting Huracan displays Huracan, 8,000 catalog HP, armor 12, and Huracan's Gold, Red Fish, Supay's Seal design entries.
- **Cannon & ammunition comparison** (`/weapon-compare`) adds readable comparisons using recovered cannon and ammunition statistics, without inventing HP outputs.
- **Sailing performance notebook** (`/sailing-performance`) plots user-entered observations against research reference curves and preserves per-ship evidence separately; it does not pretend to be the verified game wind engine.
- **Ballistics Studio** (`/ballistics-studio`) displays attacker-relative bearing, elevation, incoming shot geometry and an *illustrative* trajectory with explicitly entered physics constants.
- **Controlled Experiment Builder** (`/experiments`) creates balanced HP-damage trials, records before/after HP with target region, shot type, weapon and angle, and supports local CSV/JSON exports.
- **Damage Evidence Atlas** (`/damage-research`) summarizes observed HP results by weapon, ammunition, target, impact area and angle. Untested regions stay unknown; it never interpolates verified WoSB damage over unmeasured triangles.
- **Visual Fidelity Lab** (`/visual-parity`) compares a Workbench render to an in-game screenshot with blended and difference display in the local browser. Player-provided pictures stay local; this is visual QA, *not* shader recovery.
- **Capture & Protocol Research** (`/capture-research`, `/protocol-library`) aligns exported UTC event markers with sanitized packet timelines, saves message-type hypotheses, and distinguishes time correlation from packet meaning. Existing v4.2 opt-in recording/hotkeys/overlay remain intact.
- **Manual HP-bar video tool** in desktop Overview: choose an MP4, select a rectangle containing the HP bar on a sampled frame, select the bar color and export relative bar-fill measurements with confidence. Relative fill is not automatically absolute target HP; optional maximum HP assumption must be supplied by user.

## Full Recovery and desktop improvements

- **Repair Queue** identifies groups of failed/unsupported decodes and unresolved material-to-texture links. It emits `Reports/Repair-Queue.json` and `.md` and includes them in the existing failure-only review ZIPs, without exposing game login data, PCAP payloads or complete asset archives.
- **Setup check** reports whether FFmpeg/FFprobe/TShark and Python are available, installed game roots when supplied, and free disk space. It never silently downloads or installs software.
- **Release readiness** checks required source files, a valid source database and key research tables; it does not claim that compiled Windows recording or in-game render parity were tested.
- **Research workspace** can atomically save and restore selected ship, equipment, camera and research notes, preserving a previous backup; this does not mean every desktop widget automatically persists in every workflow.
- **Geometry research utility** computes attack direction, front-facing incidence, local surface exposure and idealized flight paths; server HP remains unknown without source-proven formula or measured evidence.
- **Offline world research fixture** remains a deterministic sandbox, not a WoSB-compatible multiplayer server. Protocol research remains passive and opt-in.
- Updated Windows build/updater/installer version to **4.3.0**; existing installation data continues to live outside the executable at `%LOCALAPPDATA%\WoSBWorkbench`.

## Source evidence and recovery status

Previous supplied recovery summary (not a new v4.3 scan): **2,482 XNB records, 2,375 decoded, 75 decode failures and 32 unsupported effect assets**; material links: **63,764 candidates**, of which **32,124 unresolved** and **31,640 candidates** based on asset metadata rather than validated shaders. New repair queue reads your current local ledgers and derives up-to-date tasks when recovery runs.

## 25-feature checklist — what v4.3 actually delivers

| Requested direction | v4.3 state |
|---|---|
| Redesign dashboard / contextual navigation | Improved main workflow and linked wiki routes; some legacy specialist screens retained |
| First-run setup | Read-only dependency and free-space readiness checks; manual installation remains |
| Shared ship selection / saved research workspace | Ship-specific browser notebook and persistent research state available; not universal across all old UI pages |
| Recovery retry diagnostics and prioritization | Grouped repair queue, supported decode-revision rechecks |
| Original shaders/materials | Existing recovered textures/GLB and visual-comparison tools; complete shader recreation **not verified** |
| Original animations | Inspect existing recovered model assets; comprehensive animations **not implemented** |
| Complete skins/flags/decorations | Curated catalog choices + material diagnostics; every combination still **not verified/render-complete** |
| Exact shipyard progression tree | Recovered shipyard artwork and categorized selection; unproven unlock relationships are **not fabricated** |
| Authentic 3D equipment slots | Ship fitting notebook and recovered port icons; original equip rules, physical transforms **not verified** |
| Projectile trajectory, collision, HP heatmaps | Geometry-based direction/angle with illustrative trajectory; 2D actual HP measurements; game authoritative hitboxes and true 3D HP still **unknown** |
| Full combat/damage formula | Exact recovered *getter* logic plus measurements; final HP/ricochet/mortar/barrel/sail resolution **unverified** |
| Gameplay video/packet capture and event correlation | v4.2 recorder retained; v4.3 timeline import/correlation and protocol hypothesis notebook |
| Automatic video HP measurement | Manual bar ROI/color segmentation for relative bar fill; not automatic robust tracking/OCR |
| Guided controlled experiments | Balanced plans, observed HP notebook, CSV/JSON export, measured atlas |
| Sailing lab | Observed-performance research charts; official wind physics **not recovered** |
| Extensive, readable local wiki and tools | Research Center, comparison, ships, guides, fitting, charts, experiments and evidence pages |
| Local server emulator | Existing offline deterministic test world; no compatible live WoSB server |
| Release tests | 80 Python tests, 11 browser pages tested with local catalog fixture, static JS syntax and ZIP verification; no Windows end-to-end run |

## Validation performed in this build environment

- `python -m unittest discover -s tests -q`: **80 tests passed**.
- `node --check wiki_site/app.js` and `node --check wiki_site/next.js`: passed.
- Browser tested all **11 v4.3 wiki pages** with a local-catalog fixture: no JavaScript page errors. In-game image loading, live FFmpeg/TShark, PyInstaller and graphics fidelity need Windows testing.
- Corrected a newly discovered bug where a server-rendered ship `<select>` used IDs but the client treated them as array positions. Huracan now correctly identifies its ship record and three full designs.
- `PRAGMA integrity_check` on bundled SQLite database: `ok`.
- Privacy: all wiki/browser data remains local; raw packet data, recordings and game assets are not included in standard failure-only review ZIPs.

## Important limits

Do not assume v4.3 reproduces authoritative client/server mechanics, unlock progression, animations or shader output. For an accurate HP damage map, capture repeatable screenshots/observations along with synchronized packet markers, identify game-code formulas and validate them against several actual battles. When game files change, re-run Full Recovery with failure recheck and compare the repair queue.

This package is **buildable source**. Use `Build-Windows.cmd` on Windows to create the portable executable and update-compatible ZIP; optional Inno Setup generates the installer. **The source ZIP is not an executable updater.**
