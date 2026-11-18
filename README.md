# WoSB Workbench

Offline research workbench for World of Sea Battle: client recovery and datamining, catalog and wiki,
ship 3D, and passive capture/protocol analysis of your own game traffic.

## Install

1. Open the repository's **Releases** page (right-hand side on GitHub).
2. Download **`WoSBWorkbench-<version>-Setup.exe`** from the latest release and run it.
   No Python, build tools or command line needed.
3. The app checks this repository for new releases on start-up (Updates page) and installs them
   with backup and rollback. Private repository: create a fine-grained GitHub token with
   read-only **Contents** access to this repo and paste it in **Updates → Access token**.

## Publish an update (maintainers)

**No command line:** edit `workbench_db.py` (`VERSION = '4.3.7'`) and add `RELEASE-NOTES-v4.3.7.md` on GitHub,
commit to `main`, then open **Actions → Build and release → Run workflow**, tick **Publish**, and run it.
GitHub builds the installer and creates the `v4.3.7` release.

**Or from a terminal:**

```
py -3.13 packaging/New-Release.py 4.3.7 --push
```

That bumps `workbench_db.VERSION`, creates `RELEASE-NOTES-v4.3.7.md` (edit it first to describe the changes),
runs the tests, commits, tags `v4.3.7` and pushes. GitHub Actions
(`.github/workflows/build-and-release.yml`) then builds the Windows app and installer, self-tests it,
and publishes the release with `Setup.exe`, `Update.zip`, `Portable.zip` and a `wosb-release.json`
checksum manifest. Every other push builds and tests too (artifacts under **Actions**).

Optional signing: run `packaging/Make-Signing-Key.py`, commit the generated `update-public-key.txt`,
and store the secret's hex as the repository secret `WOSB_SIGNING_KEY_HEX`. From then on, installed
apps accept only releases signed with your key.

---

**Current release: v4.3.6 — bug fixes, setup wizard, Activity panel, Ctrl+K search, upgraded wiki, Datamining page, Protocol Lab with auto-capture, signed updates and a new installer. Start with [START-HERE-v4.3.6.txt](START-HERE-v4.3.6.txt) and [RELEASE-NOTES-v4.3.6.md](RELEASE-NOTES-v4.3.6.md).**

**Previous release: v4.3.5 — [RELEASE-NOTES-v4.3.5.md](RELEASE-NOTES-v4.3.5.md), [FEATURE-STATUS-50-v4.3.5.md](FEATURE-STATUS-50-v4.3.5.md), [START-HERE-v4.3.5.txt](START-HERE-v4.3.5.txt).**

# WoSB Workbench

**Pre-install audited v4.3.1 source:** see `AUDIT-RESULTS-v4.3.1.md` for fixes based on two recovered client reports. After compiling, run `Recheck-Decoders-Only.cmd` to verify previously failed assets without repeating the full code index.
 v4.3 — Research Center, Combat Experiments & Local Codex

**New release:** read `START-HERE-v4.3.txt` and `RELEASE-NOTES-v4.3.md` first. Run `Build-Windows.cmd` for a compiled Windows executable and updater-compatible ZIP, or `Open-Local-WoSB-Codex.cmd` to open the local browser encyclopedia. The new update integrates a more accessible research dashboard, verified game-catalog ship selection and outfitting notebook, controlled damage trials, observed-HP charts, wind observations, a local visual-parity tool, video HP-bar measurements, packet timeline correlation, setup checks, and prioritized failed-asset repair reports. All 25 proposed improvement directions are tracked in the v4.3 notes, including outstanding blockers—**this is not a verified full server combat emulator or perfect original shader reconstruction**.

---

# WoSB Workbench v4.2 — Gameplay Capture & Measured Damage Lab

**Read `START-HERE-v4.2.txt` and `RELEASE-NOTES-v4.2.md` first.**
This version adds synchronized opt-in screen and WoSB packet capture, overlay event markers, optional hotkeys, short event video clips, sanitized shareable review ZIPs, measured damage-by-angle dashboards, and in-game render comparison.
Older release notes below are retained for history; exact authoritative damage formulas and proprietary game shaders are not yet recovered.

# WoSB Workbench v4.1 — Local Codex, Mechanics Research and Multi-Client Recovery

**Start with `START-HERE-v4.1.txt` and `RELEASE-NOTES-v4.1.md`.** This release preserves all existing v4.0 features, adds expanded local wiki guides and ship comparisons, a source-traced simulation notebook, improved ship material matching, model audits, code-signature verification, multi-client Full Recovery, and offline emulator fixtures. V4.1 does *not* claim to reproduce unrecovered server-side gameplay rules, original shaders, or the complete official protocol.

Legacy sections below document previous releases and their contemporaneous limitations; consult the v4.1 release notes for the current scope.

# WoSB Workbench v3.10 — One-Button Full Recovery

Go to **Full Recovery** and choose the installed game folder. Click **Recover Everything**.
The scan writes to `%LOCALAPPDATA%\WoSBWorkbench\FullRecovery\<game-id>` and resumes unchanged assets.
Read `RELEASE-NOTES-v3.10.md` for precise capabilities and limits.

**Full fidelity additions:** the Ship 3D asset folder can also point at the directory containing all 36 `WOSB-Research-Part-*.zip` research handoff parts. Workbench reads matching images directly from those archives, exports sibling PNG textures for browser rendering, and has an **Export textured GLB** action. Open the v3.10 release notes for important evidence and damage-formula limitations.

# WoSB Workbench v3.9 — Ship Appearance and Damage Research

**New in v3.9:** real mesh material identifiers from XNB tags, client-recorded ship design swaps, offline local game texture scanning, optional empirical HP estimation from controlled observed shots, and large-ship sampled display geometry. See `RELEASE-NOTES-v3.9.md` and `START-HERE-v3.9.txt`.

The source ZIP does not redistribute ship/game textures or promise server-authoritative damage calculations. For textures, select the installed game Data folder. Use `Build-Windows.cmd` to compile the complete desktop app on Windows (Python 3.13). The source OBJ is left intact when a large ship's display mesh is sampled.

> **v3.8.0 Ballistics & Visualizer:** Read `RELEASE-NOTES-v3.8.md` and `README-Visual-Layers-and-Damage.md` first. The older release notes are retained for history.

# WoSB Workbench v3.7 — Network Research Lab, Wiki & 3D Ship Viewer

A private, offline Windows-oriented research desktop application for World of Sea Battle.

Features: concurrent analysis of three client paths; importable game-data catalog; editable offline wiki; Discovery Center; source-linked combat research and sailing data; evidence-gated crafting/production/combat calculators; real XNA ModelReader OBJ export for compatible ship XNBs; named mesh-part rendering; rollback-capable ZIP updates.

### To build the complete Windows application

1. Extract this **source ZIP**, then open the `WoSB-Workbench-v3.7` project folder.
2. Run `Build-Update.cmd` on Windows with Python 3.13 installed. The script creates a temporary build virtual environment and installs its pip/PyInstaller dependencies automatically.
3. Pick `dist\WoSBWorkbench-3.7.0-Update.zip` in the previous Workbench's **Updates → Choose update ZIP**. Do **not** pick the source ZIP or portable ZIP; those do not contain a proper `wosb-update.json` manifest.
4. If desired, run `dist\Installer\WoSBWorkbench-3.7.0-Setup.exe` created by your Inno Setup 6 compiler (the script supports a per-user installation).

The compiled app bundles Python and the specified libraries; people installing it do not need Python or pip. The application stores local data under `%LOCALAPPDATA%\WoSBWorkbench`, outside its executable directory.

### Recover real ship 3D geometry

In **Ship 3D**, select a build and ship, then choose **Open 3D viewer**. The Workbench first tries a game-evidenced model mapping `ShipsToPlay.StaticInfoID → ShipsBasics.ModelName` and a loose local XNB. If one is found, it offers to convert and save the actual model. Alternatively use **Recover XNB → OBJ** and select an original `.xnb` or previously exported debug-sample ZIP.

Model recovery is read-only. The decoder validates indexed mesh geometry, exports a persistent Wavefront OBJ, records the source SHA-256, and adds source-associated geometry to the browser viewer. Failures for unsupported custom tags are reported rather than silently fabricating a silhouette. Mesh component names are not damage multipliers or confirmed hitboxes.

### Build and enrich the wiki

1. Import a complete Scan1/2/3 reports ZIP from the **Import & export** page.
2. Open **Mechanics Lab → Enrich wiki from this build** to generate source-only pages in the existing local wiki. Choose Game or Steam separately.
3. Review and edit the pages in **Wiki editor**, preserving your own notes during subsequent imports.
4. Export the catalog or static offline wiki for later use.

### Verification notes

See `RELEASE-NOTES-v3.7.md` for proven Vasa recovery counts, tested functions, known decoder limitations, unverified gameplay mechanics, and Windows build instructions. No copyrighted raw XNB game assets are bundled with this source release.


## Network Research Lab (new in v3.7)

Open **Network Research Lab** from the sidebar. Choose **Import PCAP / PCAPNG** to analyze an existing packet capture locally, or install Wireshark with TShark and Npcap to enable an opt-in **Start passive capture** button. List interfaces with the built-in button, choose the numbered interface, then stop the capture before importing the `.pcapng` file.

Only import traffic you own or are authorized to inspect. The original PCAP may include passwords, session tokens, chat, and unrelated traffic; it is retained on disk, not uploaded. The local database records only aggregated flow information, approximate network prefixes, packet counts/sizes, protocol hints, and per-second traffic counts. **Export redacted research** strips even those network prefixes and never includes raw packet payloads. You can record timestamped events (including during live capture), correlate them to nearby traffic, and create wiki research entries. Temporal correlations are not proof of message content or game mechanics. Encrypted traffic is not decrypted.

Parsing supports standard PCAP and PCAPNG Ethernet/IPv4/IPv6 TCP and UDP traffic (selected common link types), with 2 GB/2 million packet safety limits, up to 100 MB rolling TShark capture files and explicit capture stop. Complex encapsulations and TCP stream reassembly are not yet supported. Binary length-prefix hints are only candidates, not confirmed WoSB message definitions. This version does not inject, replay, intercept, modify, or decrypt network traffic.

## Windows update

Run `Build-Update.cmd` on Windows (Python 3.13 for BUILD ONLY). Select **`dist\WoSBWorkbench-3.7.0-Update.zip`** in Workbench Updates. The source ZIP is NOT an updater patch. Inno Setup 6, when installed, creates `dist\Installer\WoSBWorkbench-3.7.0-Setup.exe`. Personal wiki data remains at `%LOCALAPPDATA%\WoSBWorkbench`.


## Ballistics & Ship Visualizer (new in v3.8)

Load a verified Wavefront OBJ, with optional local texture PNG/JPG/WEBP or Texture2D XNB. For the original Vasa model run **Recover XNB → OBJ** again to preserve UVs. The browser visualization lets you hide helper-named geometry such as `AverageBox`, examine the full-detail hull separately from low-detail copies, inspect component names, and click visible triangles to record shot coordinates, impact normal, and obliquity. Select any of the 42 mined cannons and 21 ammo types; see Vasa and other ship health/armor from the user-supplied Scan1 catalog. Record measured damage to enable a transparent approximate HP estimate. Formula limitations are explicit.

**Offline launch:** Build with `Build-Windows.cmd` and launch `dist\WoSBWorkbench\WoSBWorkbench.exe`, or use `Run-Workbench.cmd` with the required Python environment. **No internet connection is needed to view exported HTML.** Data at `%LOCALAPPDATA%\WoSBWorkbench` is retained across reinstallations; back it up before cleaning.

A source ZIP is **not** the compiled program or updater ZIP; run the Windows build script to produce them.
