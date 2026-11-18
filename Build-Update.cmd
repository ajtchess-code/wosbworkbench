@echo off
setlocal
cd /d "%~dp0"
echo Building WoSB Workbench (version from workbench_db.py) - EXE, updater ZIP and installer...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0packaging\Build-Windows.ps1"
if errorlevel 1 (
    echo Build failed. No updater ZIP is ready; review the error above.
    pause
    exit /b 1
)
set /p WOSB_VERSION=<"%~dp0dist\VERSION.txt"
echo.
echo Update ZIP: %~dp0dist\WoSBWorkbench-%WOSB_VERSION%-Update.zip
echo Choose THIS compiled update ZIP in WoSB Workbench 3.4.0 or newer - Updates.
pause
