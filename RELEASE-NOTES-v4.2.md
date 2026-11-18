# WoSB Workbench v4.2 — Gameplay Capture & Evidence-Driven Damage Research

## Working features added

- **Gameplay Capture Studio** integrated into Network Research Lab. Optional, read-only, local screen recording via external FFmpeg plus passive packet capture via TShark/Npcap. Verifies that the requested port is owned by the WorldOfSeaBattleClient process using Windows Get-NetTCPConnection. Defaults to the user-confirmed remote TCP port 23771. No game injection, unauthorized packet interception, decryption, replay, server commands, or network probing.
- **Always-on-top research overlay and optional Windows hotkeys:** timestamp single shots, broadsides, bow/side/stern/sail hits, sinking and HP readings. Ctrl+Alt+F1–F8 hotkeys register only while recording, where available. A yellow `Sync flash` can appear on desktop video for manual first-frame alignment. Exclusive-fullscreen games or video capture of game window only may not show the overlay.
- **Private synchronized session:** UTC and monotonic markers, MP4 and PCAPNG saved locally, configurable port/interface, approximate video-launch timing and explicit video offset correction. The game recording stays local. Video launch time is not provably the time of the first encoded frame.
- **Packet timeline matching:** TCP segment sizes, candidate two-byte length fields, client/server direction, retransmission deduplication by TCP sequence, 0.5-second bins and ±2.5-second event correlations. All interpretations remain candidate/timing-only. The actual user-supplied Huracan capture reproduces the earlier 99 candidate 45-byte client segments, versus zero in the older reference capture; this does not prove shot message identity.
- **Shareable evidence bundle:** `Review-Only.zip` excludes original PCAP, video, addresses, payloads and session tokens by default; includes a compact packet timeline, marker/event table and explicit limitations. User-authored marker notes may still contain private text, so review before sharing.
- **Optional short video clips** (3 seconds before to 5 seconds after a marked event), explicitly opted in, remain local under `clips/`. These may show personal/private information; nothing uploads automatically.
- **Measured Damage Atlas:** controlled CSV-based empirical HP map by cannon, ammunition, target, shot type, impact region, 15-degree angle band, 50-unit range band and game version. Three or more matching measurements required for a colored cell; insufficient evidence remains grey. Displays sample size and approximate statistical uncertainty, not the game damage formula. Does not conflate single shots with broadsides/mortars/barrels.
- **Visual parity tool:** renders actual-game vs Workbench screenshots side by side, blended and difference view, with alignment warnings. Does not claim shader equivalence.
- **Ship viewer angle correction:** uses front-facing surface-normal alignment rather than absolute dot product; reverse-facing material normals are flagged as suspects. Accuracy depends on decoded face winding/transform correctness.
- **Regression tests:** Python source tests for gameplay PCAP parsing, privacy-preserving review packages, empirical grouping, visual comparator and retained v4.1 features.

## Existing v4.1 features retained

Game-file mesh/UV and material recovery, skin substitution diagnostics, 3D interactive research, recovered client armor getters and sail energy method, local shipyard/wiki, Mechanics Lab, resumable full recovery and failure-only ZIPs, code signature analysis, sailing/wind research, and offline testbed.

## Still not recovered / not independently verified

- Exact game shader/effect program parameters, all animation playback, every appearance combination, or 1:1 game rendering. Pixel differences require aligned reference screenshots and further content-reader/shader work.
- Verified complete game collision hitboxes and transforms. An OBJ mesh or helper label alone does not prove the server damage collision rules.
- Authoritative *server-side* formulas for cannonball HP damage, deflection, penetration, mortar, heavy mortar, barrel and sail damage. Recorded observations support empirical summaries but not a verified physics/damage law.
- Packet IDs or serialized message schemas for WoSB; network timings are candidate signals only. No playable WoSB server emulator exists.
- Windows FFmpeg/TShark capture, hotkey/global shortcut and generated Windows installer cannot be executed in this Linux build environment and must be validated on Windows.

## Existing scans

No full game rescan is needed to use v4.2 Gameplay Capture Studio or the measured-damage atlas. Asset-reader revision is intentionally unchanged from v4.1. Keep earlier recovery outputs and scan only if game files or readers change.

## Windows requirements

Build with `Build-Windows.cmd` using Python 3.13 and optional Inno Setup 6. FFmpeg and Wireshark/TShark/Npcap are separate, user-installed applications for **live** capture; the packet analyzer and measured damage CSV viewer require no game client or network capture tools. `Build-Update.cmd` builds the compiled updater ZIP; the source ZIP is not a runnable update.
