# WoSB Workbench 4.3.8

## Tools find their own folders
- Install-based tools (decode coverage, decompile, message-definition extraction, shader audit,
  version tracking, model sample export) use your saved installs directly. With one install there's
  no dialog. With several, a one-click chooser opens (double-click or Enter; "Other..." still lets you browse).
- If no installs are saved, the app auto-detects Steam, the standalone client and the launcher and saves
  them. If nothing is found, it offers the setup wizard.
- Capture tools (message catalog, message log, clip/review/evidence exports) default to your current or
  most recent session under GameplaySessions / AutoCaptures, newest first.
- Audio extraction finds and extracts every .xwb wave bank in your installs in one run.
- Compare definitions lists your saved Protocol-Definitions extractions instead of opening file dialogs.
- Audit reports uses your saved Reports folder automatically.
