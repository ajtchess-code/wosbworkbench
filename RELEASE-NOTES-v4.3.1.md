# WoSB Workbench v4.3.1 — Startup Hotfix

**November 17, 2026**

Fixes a reproducible v4.3.0 desktop startup crash:

`ValueError: not enough values to unpack (expected 2, got 1)`

The Overview page accidentally wrote `enumerate [...]` rather than
`enumerate([...])` when creating the seven local-wiki shortcuts.
This executed a generic alias expression, which iterated over the wrong values.
The corrected call is now covered by a regression test that also scans top-level
Python modules for accidental subscripts on common iterator functions.

Build labels, the updater ZIP metadata, the Inno Setup output name and the
application version are consistently set to **4.3.1**. Also fixes the stale
v4.2 version label in `Build-Update.cmd`.

All v4.3.0 research tools, full recovery, offline wiki and gameplay recorder
are retained. No database migration, re-import or game scan is necessary.

## Install

This archive contains **source**, not a compiled .exe or an updater binary.
Extract to a new folder and run `Build-Windows.cmd` on Windows with Python 3.13.
For an existing Workbench installation, build `Build-Update.cmd`, then choose
`dist\WoSBWorkbench-4.3.1-Update.zip` from the application's Updates page.
Do **not** upload or select the source ZIP as an updater payload.

Windows executable and installer builds remain unverified in this Linux
runtime; unit tests and a headless GUI launch smoke test are performed here.

## Audited pre-install source revision

This source archive includes the recovery-audit corrections documented in
`AUDIT-RESULTS-v4.3.1.md`: SpriteFont root reader classification and atlas
recovery, nullable model effect references, separately accounted non-XNB files,
compiled-effect evidence preservation, removal of generic `Texture` placeholders
from material failures, explicit managed-method cap reporting, and selective
reuse of successful past asset decodes. Use `Recheck-Decoders-Only.cmd` after
building to verify the affected assets without repeating full code extraction.

The Windows binary still must be built locally. These changes have **not**
been verified against the original failed font, effect and wtframe files.
