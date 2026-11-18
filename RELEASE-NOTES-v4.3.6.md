# WoSB Workbench v4.3.6 — review fixes, Protocol Lab, platform & datamining expansion

Based on the complete v4.3.5 source; every v4.3.5 feature is kept. Build with
`Build-Update.cmd` (Python 3.13, Windows). Install with `dist\Installer\WoSBWorkbench-<version>-Setup.exe`
or apply `dist\WoSBWorkbench-<version>-Update.zip` from an installed 4.3.5 via **Updates**.
The version comes from one place, `workbench_db.VERSION`.

## What's new for users

**Getting started**
* **First-run setup wizard.** It finds your Standalone, Steam and launcher installs (registry, Steam `libraryfolders.vdf`, common folders) and checks FFmpeg, TShark, Npcap, .NET and ILSpy, with download links. It saves capture defaults and the theme. You can rerun it from **Settings**.
* **Settings page.** Folders, auto-capture, follow-up actions after recovery, theme (dark/light), text size, toasts, and links to the logs and data folders. Settings persist in `settings.json`; the paths that were hard-coded and re-typed on several pages now come from here.

**Everyday use**
* **Grouped sidebar.** Home, Recover, Catalog & Wiki, Ship 3D, Capture & Protocol, Settings. All pages are visible; there's no hidden "more tools" drawer. The last page and window size are remembered.
* **Overview dashboard.** Cards for installs, catalog/wiki, last recovery, protocol definitions, latest capture and auto-capture, plus suggested next steps.
* **Activity panel.** Every background task shows progress, can be cancelled, and has its log/error and an "Open output" button. The status bar shows running jobs. Long actions no longer freeze the window, including stopping a recording and the setup check.
* **Toasts.** Notifications appear in a corner with action buttons ("Open folder", "Open as table") instead of a modal popup for every message. The full history is kept in Activity → Notifications. Errors still use dialogs.
* **Search everything (Ctrl+K).** Wiki (ranked, with snippets), catalog records, combat methods, protocol message classes and opcodes, and decompiled source.
* **Results as tables.** Advanced Research, Protocol Lab, coverage and setup reports open in a sortable, filterable table view with a full JSON tree.
* **Keyboard shortcuts.** Ctrl+K search, Ctrl+S save article, Ctrl+Shift+A Activity, F1 guides.

**When things go wrong**
* **Crash reporting and logs.** Errors that used to vanish in the windowed build are logged to `%LOCALAPPDATA%\WoSBWorkbench\Logs` (rotating) and shown in a dialog with "Copy details" and "Open logs folder".
* **Crisp text on scaled displays.** Per-monitor DPI awareness is turned on, so Tk no longer looks blurry at 125–200 %.
* **App icon** and a single-instance check.

## Wiki system
* **Full-text search** (SQLite FTS5) with relevance ranking and highlighted snippets, in both the editor search and the web Codex.
* **`[[Wiki links]]`** with **"Pages linking here"** backlinks. Links to pages that don't exist yet are highlighted.
* **Tags.** A `Tags: a, b` line becomes tag chips, `/tag/<name>` pages and a tag cloud.
* **Revision history.** Every save keeps the previous version (up to 200 per article), with preview and one-click restore.
* **Autosaved drafts** every few seconds while you edit; you're offered the draft if the app closes unexpectedly.
* **Live preview** in the desktop editor and an **"Open in web Codex"** button.
* **Richer, still-safe Markdown.** Tables, numbered lists, task lists, blockquotes, rules, bold/italic/strike, inline code and safe links. One renderer is shared by the editor preview, the web Codex and the static export. Raw HTML and `javascript:` links are never rendered.
* **Web Codex** gets a contents sidebar for long articles, Recently changed, tags and backlinks.
* **Generated pages.** Pages are written automatically for client updates ("Datamined changes") and auto-captured sessions.

## Datamining (new page under Recover)
* **Decode coverage report.** Every file type in an install, which decoder handles it, the outcomes from the last Full Recovery ledger, and what is still undecoded. High-entropy files are flagged as probably compressed or encrypted. Native binaries are flagged for Ghidra.
* **Decompile to C# with ILSpy** (`ilspycmd`, optional). One C# project per managed assembly, plus a searchable source index (classes, methods and full text) that feeds Ctrl+K search.
* **Client version tracking.** Fingerprints Game, Steam and launcher installs. On a change it hashes an asset snapshot, diffs it against the previous one, and writes a "Datamined changes" wiki page. It runs automatically after Full Recovery (setting).
* **Protocol definitions** are extracted automatically after Full Recovery (setting). **Recover ALL** now uses every configured install, including the launcher.
* **XACT audio banks (`.xwb`) → WAV** (PCM and MS-ADPCM with proper headers; xWMA/XMA are saved raw for ffmpeg).

## Protocol work (Capture & Protocol)
* **Auto-capture (opt-in).** While `WorldOfSeaBattleClient.exe` has an established game connection, the app picks the matching adapter and records passively, filtered to the game port, into `AutoCaptures/`. When you disconnect it runs the message catalog, notifies you and writes a wiki page. It's off by default; turn it on in Setup or Settings.
* **Field inference** per message type: constants, counters, length fields, float32 values and small enums (Netzob-style signals). It feeds a "Suggest fields" button.
* **Message browser.** Message types, per-message hex dump, and a field-schema editor with live decoding. Field types: integers in both byte orders, floats, bool, varint, .NET strings, length-prefixed strings, fixed bytes, rest.
* **Decode everything with your schema → JSONL + SQLite.** One table per named message type, IDs annotated with catalog names (ships, cannons, ammo…). This follows the sniff-to-database workflow emulator projects use.
* **Exports.** A **Wireshark Lua dissector** (TCP desegmentation, opcode names, typed fields), an **ImHex pattern** and a **Kaitai Struct** `.ksy`.

## Installer and updates
* **Installer.** Closes a running Workbench (named mutex) instead of failing on locked files, and clears the old `_internal` library folder on upgrade (no stale DLLs). It has an app icon and version info, an optional-tools page with download links for missing FFmpeg/TShark/Npcap, and an uninstall question that keeps or removes your data (default: keep). It's 64-bit aware (Inno Setup 6.3+).
* **Signed updates (Ed25519).** Run `packaging\Make-Signing-Key.py` once. Builds then bundle the public key, and installed apps accept only update ZIPs and feed manifests you signed. Tampered or re-signed packages are rejected. Without a key, packages are accepted but clearly shown as UNSIGNED.
* **Update ZIPs remove stale files.** Files that the new build no longer ships are listed (`WOSB_PREVIOUS_DIR`), backed up and removed, with rollback on failure.
* **Single version source.** The build reads `workbench_db.VERSION` and passes it to Inno Setup; no other file hard-codes a version.
* **Build pipeline.** The build runs the unit tests, then `WoSBWorkbench.exe --self-test` (imports every module and checks bundled resources) on the frozen app. CI runs tests on Linux and builds/self-tests on Windows; signing is optional via a repository secret.

## Ideas taken from other tools
* **WowPacketParser** (WoW emulator community): turns sniffs into readable output and database rows, naming IDs from game data. This is where schema decoding to SQLite with catalog-named entities comes from.
* **Netzob:** field and size inference, and exporting protocol models to Wireshark. That gave us field inference and the dissector/ImHex/Kaitai exports.
* **ILSpy** (`ilspycmd -p --nested-directories`): decompiling the client to complete C# projects.
* **Datamine repositories** (e.g. War Thunder change trackers): tracking file changes across client updates. That became client version tracking and the changes pages.
* **ImHex and Kaitai Struct:** inspecting raw message streams with your schema applied.

## Bugs fixed

| Area | Problem | Fix |
|---|---|---|
| Offline updater | `os.kill(pid, 0)` was used to wait for the GUI to exit. On Windows, signal 0 is `CTRL_C_EVENT`, so the updater either decided at once that the app had closed (then hit locked files and rolled back) or sent Ctrl+C to a console group. | Waits on a real process handle (`OpenProcess` + `WaitForSingleObject`), then allows 1 s for file locks to clear. File replacement retries briefly on `PermissionError` (antivirus/indexer). |
| Network Lab capture | TShark ring-buffer mode (`-b files:2`) renames the output to `name_00001_<time>.pcapng`. The "Capture saved" path never existed, queued event markers never attached, and older traffic was silently deleted. | Writes one file at the exact path and auto-stops below the 2 GB import limit. Stop is graceful (CTRL_BREAK / SIGTERM), so the last block gets flushed. |
| PCAP/PCAPNG readers | A capture cut off mid-packet (tool stopped hard) made the whole import fail. | The complete packets are kept and the truncated tail is ignored. Corrupt files are still rejected. |
| Advanced Research → PCAP continuity | The pcapng magic was checked as `0a0d0a0d`, so every TShark `.pcapng` was rejected. | Corrected to `0a0d0d0a`. |
| Wiki navigation | "Open research wiki", "Create research page", "Create wiki article from record", the model wiki page and the network wiki page all jumped to tab 3 (Catalog) instead of the Wiki editor. | Pages are now selected by name, not index. |
| Wiki editor | Selecting another article silently discarded unsaved edits. Closing the app did too. | Asks Save / Discard / Cancel. A newly created article hidden by the search filter is now shown. |
| UI event loop | One exception in a background-result handler stopped `_poll_events` from rescheduling, which froze status, scan progress and recovery completion for the rest of the session. | The loop reschedules in `finally` and is bounded per tick. |
| Full Recovery | Tk variables were read inside worker threads (not thread-safe). | All options are read on the main thread first. |
| Video HP tool | The error lambda referenced `exc` after Python had deleted it, so frame-extraction errors raised `NameError` instead of being shown. | The message is bound when the error happens. |
| Local web Codex | Inline `style="width:…"` was blocked by the page's own CSP, so comparison bars were always empty. Non-numeric `ShipRank`/`Health`, a `None` description, or `NULL` article bodies crashed pages (blank response). `#`/`%` in the Windows user path broke the read-only SQLite URI. Search treated `%`/`_` as wildcards. | Bars use `data-percent`, values are parsed defensively, errors return HTTP 500 instead of a dropped connection, the DB URI is built with `Path.as_uri()`, LIKE is escaped, and there is a Host-header (DNS-rebinding) guard. The server socket is closed on exit. |
| Gameplay capture | Re-analysis reset the saved sync-flash video offset to 0. FFmpeg/TShark log handles leaked in the parent process. | The offset stored in `session.json` is the default. Log handles are closed after launch. Ring-buffer files are analysed in order. |
| Ship 3D viewer | Ships with the same display name (or the same ship in Game vs Steam) overwrote each other's viewer HTML and wiki registration. The catalog hull candidate only searched the Game build. | The viewer slug includes the build and ship ID. All builds are searched. |
| Model recovery | Loose XNB lookup only tried two hard-coded `C:\` paths. | Also searches the game folders you configured or browsed to. |
| Importers | A non-object entry in `XNBHeaders.json` or `Asset_Inventory.jsonl`, or one malformed MediaWiki XML file, aborted the whole import. CSV fields over 128 KiB failed. | These entries are skipped and the CSV field limit is raised. |
| Advanced HP trial form | `hits = 0` saved the row and then crashed. HP-after > HP-before was accepted. | Validated before writing. |
| Setup check | `rglob` walked the entire game install on the UI thread. | Bounded search (depth 4). |
| Dependencies | LZ4-compressed XNB support needed `lz4`, which was never installed or bundled. | Added to `requirements.txt` and `--collect-all lz4`. |
| SQLite handles | `with sqlite3.connect()` commits but never closes (several places). | `contextlib.closing` / explicit close. |

## New: Protocol Lab (Network Research Lab → Protocol Lab)

All of these work offline on **your own** captures and client files. They never
send, proxy or modify traffic and never decrypt.

* **Catalog messages (`protocol_lab.py`).** Reassembles directional TCP streams (SYN-aware, wrap-safe, retransmit/overlap trimming, gap splitting). It then ranks 30 length-prefix framings, resyncs when a capture starts mid-message, cuts the streams into application messages, and builds a per-type catalog: direction, opcode candidate, count, size range, period, entropy and a constant-byte mask that hints at field boundaries. Byte entropy flags streams that look encrypted or compressed, so you don't chase noise.
* **Marker association.** For a Gameplay Capture Studio session it computes, per marker kind (broadside, hit, sunk…), which message types are over-represented nearby ("lift"). This is how you find e.g. the client "fire" message.
* **Extract message definitions (`engine/protocol_extract.py`).** Reads .NET metadata/IL of the client, Steam build or launcher without executing it. It finds message-like classes (name, shared base class, serializer methods), their fields with decoded CLR types, the **ordered Read*/Write* calls in each serializer** (the wire field order), opcode/message-id enums with values, large-switch dispatcher candidates, and network-related strings (host names redacted).
* **Definitions ↔ capture matching.** Observed opcode candidates are matched against the extracted enums, so message types get real names when they line up.
* **Build diff.** Compares definitions between Game, Steam and the launcher, or between versions: added/removed classes, field or wire-order changes, renumbered opcodes.
* **Private message log.** Every reassembled message is written as JSONL (time, direction, type, hex) for writing and regression-testing a parser or an offline emulator fixture. It contains raw bytes of your session, so it stays local and is never included in review exports.

CLI equivalents: `advanced_research_cli.py protocol | protocol-extract | protocol-diff`
and `python protocol_lab.py … --message-log`.

## Verification (Linux, Python 3.13)

* **207 tests pass**: 155 existing, plus 28 in `test_v436_fixes_and_protocol.py` and 24 in `test_v436_platform.py`.
* Ed25519 matches the RFC 8032 test vectors.
* Signed, unsigned and tampered update packages are each handled correctly. Stale-file removal is backed up.
* Protocol Lab, field inference, the schema decoder and the exports were checked on synthetic captures with known ground truth.
* The auto-capture state machine was tested with simulated connections.
* `--self-test` passes.
* **Headless UI smoke test.** The whole app is built against a stand-in Tk: all 16 pages, dashboard, search, setup wizard, result tables, wiki edit/draft/preview/save/history, message browser, watcher events and a background job round trip. It found and fixed one crash (duplicate `wrap` option in a text widget).

**Not tested here:**
* The Windows build, installer compile (ISCC), self-test of the frozen exe, and real-Tk visual layout.
* Auto-capture against a live game.
* `protocol_extract` and ILSpy on real WoSB assemblies (dnfile and ILSpy aren't installed here).
* XWB extraction on real WoSB banks; it was only checked on a synthetic bank built to the XNA 4 layout.
* Loading the generated Lua dissector in Wireshark.
