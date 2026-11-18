# WoSB Workbench v4.3.2 — Verified Capture & Combat Evidence Update

**November 17, 2026**

Based on the recorded Huracan battles, the empty capture from the wrong adapter,
and the successful 17-marker recording with 273 outbound and 2,621 inbound
TCP payload segments. This is a focused improvement to **v4.3.1 audited**;
no game assets, database schema or existing research sessions are deleted.

## Fixes and improvements

- **Game-route interface discovery.** Uses the local WoSB TCP connection's
  Windows network-adapter identity and TShark's adapter list to pick the correct
  adapter; never blindly defaults to adapter 1. If the mapping is ambiguous,
  the operator chooses an adapter. No IP addresses are saved by this feature.
- **Live packet preflight.** Before capture, checks the selected adapter for
  game TCP packets using a short, payload-free TShark probe. If there is no
  traffic it warns rather than silently calling the capture valid. In-game
  inactivity can also cause a zero-count preflight; continue only knowingly.
- **Recording-integrity warnings.** After a recording, the tool checks the real
  game TCP timeline; an empty PCAPNG header no longer counts as a successful
  capture. The stop status reports explicitly when no game payloads were seen.
- **Multiple targets per session.** The floating overlay now includes an
  editable current target. Each new marker stores its target, weapon and ammo.
  Historical sessions remain readable and fall back to the session's initial
  target if older markers lack per-target fields.
- **One-click Combat evidence ZIP.** From a *completed* gameplay session,
  extracts full-quality before/after stills for marked events, generates a
  compact compressed gameplay video and an aligned, anonymized packet timeline.
  Auto-crops the chosen side of a dual-monitor recording (left/right) or keeps
  the full frame (none). The ZIP is limited to 45 MiB. It excludes raw PCAP
  payloads and full game data. Review video and stills before sharing them;
  visible player names and chat cannot be automatically redacted.
- **FFmpeg/FFprobe discovery.** Setup Check and the recorder now recognize the
  WinGet FFmpeg aliases even when the PATH change has not propagated to an
  already-running packaged application. PyInstaller remains optional at runtime.
- **Independent video alignment.** Export reruns packet correlation with the
  chosen video correction so a previous review file cannot quietly retain a
  stale offset.

## Use

1. Connect to WoSB; open More research tools > Network Research Lab > Gameplay Capture Studio.
2. Click **Detect game** and **Auto-select network adapter**. Check it chose Wi-Fi,
   Ethernet or your actual game connection. The number is not fixed across PCs.
3. Start recording; check the preflight. Mark shots/impacts and **update Current
   target** in the overlay when switching NPCs.
4. Stop & analyze. A missing-game-traffic warning means capture is unusable for
   protocol correlation, though the video/markers may still help.
5. Click **Combat evidence ZIP** to export a compressed video, clear event frames,
   per-target events and packet timing without raw packet payloads.

Existing recordings can also be selected in the export dialog; no new full
asset scan and no repeat fight is required just to generate the ZIP.

## Evidence and validation limits

This update does **not** discover an authoritative cannon, mortar, barrel or
sail-damage equation; it does **not** decode confirmed network game opcodes,
recreate proprietary shaders, or provide a playable server emulator.
The 45-byte segment signature remains a hypothesis. Target health values from
small/obscured video HUD elements still require human verification.

The source tests cover route matching, zero-packet warning, per-target markers,
compact video export, privacy exclusions and the existing Workbench regressions.
Live capture and the Windows installer must be checked on the user's PC.
