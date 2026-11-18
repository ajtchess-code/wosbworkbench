# WoSB Workbench v3.7.1 — source / fresh-install rebuild

This is the full v3.7 project source, with a targeted XNB Windows CAB extraction hotfix. It includes the Network Research Lab, model viewer, wiki, scanning/import tools, update builder and Inno Setup script.

## Decoder change

Windows `expand.exe` now uses `-F:*` before the source CAB, enumerates the actual extracted member, validates its length against the XNB header, and reports detailed diagnostics. The decoder keeps the optional 7z/libarchive fallback. This corrects a likely filename/path handling failure observed with v3.7. It **has not yet been validated on the user's Vasa file or built into a Windows executable**.

## Clean build and install on Windows

1. Extract the complete source ZIP to a new folder and open `WoSB-Workbench-v3.7`.
2. Install Python 3.13 (including tkinter). To build the optional Windows Setup EXE, install Inno Setup 6.
3. Run `Build-Windows.cmd` to compile. It creates `dist\WoSBWorkbench\WoSBWorkbench.exe`, `dist\WoSBWorkbench-3.7.1-Portable.zip`, and `dist\WoSBWorkbench-3.7.1-Update.zip`. If Inno Setup is available, it also creates `dist\Installer\WoSBWorkbench-3.7.1-Setup.exe`.
4. **Fresh install:** run the generated Setup EXE or extract the portable ZIP to an empty directory and run `WoSBWorkbench.exe`.
5. **Existing installation:** use the generated `3.7.1-Update.zip` in the in-app updater; do not select the source ZIP.

User data normally lives in `%LOCALAPPDATA%\WoSBWorkbench` and may persist after reinstall. Back up that directory before cleaning it. Do not delete it unless you intentionally want to reset imported catalog/wiki data. No WoSB game client files are included.

## Local validation

`py -3.13 -m unittest discover -s tests -p test_v371_decoder.py`

The source and tests can be checked on other operating systems, but producing the installer requires Windows. The packaged source is not itself a precompiled installer.
