# WoSB Workbench v4.3.7

Fixes found on the first real Windows builds and runs of 4.3.6.

## Fixes
- **Scans no longer crash with "WinError 5 Access is denied"** on `CombinedStatus.json` or `Progress.json`.
  Windows refuses to replace a file another process has open (the app polls these status files; antivirus
  and the search indexer open new files too). All atomic writes now retry briefly, polled status files are
  written best-effort, and the scan coordinator stops its workers if it ever fails.
- **No more console windows flashing** while auto-capture is on: game-connection checks use the Windows
  IP Helper API instead of PowerShell, and every background tool starts without a window.
- **Build fixes:** Windows PowerShell 5.1 parse error in `Build-Windows.ps1` (non-ASCII character), an Inno Setup
  6.7 incompatible shortcut flag, and Windows-only test failures (text encoding, an unclosed test database).

## Updating
Installed 4.3.6: **Updates → Check GitHub now → Download and install update**, or run
`WoSBWorkbench-4.3.7-Setup.exe` from the release.
