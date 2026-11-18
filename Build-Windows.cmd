@echo off
setlocal
cd /d "%~dp0"
echo Building WoSB Workbench and offline ZIP update helper for Windows...
echo Python 3.13 is needed only to BUILD from source. Users of the finished .exe do not need Python.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0packaging\Build-Windows.ps1"
if errorlevel 1 (
  echo.
  echo BUILD FAILED. Review the error above.
) else (
  echo.
  echo BUILD FINISHED. Look inside dist\WoSBWorkbench and dist\Installer.
  echo Installer creation requires Inno Setup 6 to be present on the build PC.
)
pause
