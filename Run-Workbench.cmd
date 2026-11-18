@echo off
setlocal
cd /d "%~dp0"
py -3.13 --version >nul 2>&1
if errorlevel 1 (
  echo WoSB Workbench source launcher requires Python 3.13 for best compatibility.
  echo Alternatively, run the compiled WoSBWorkbench.exe after the Windows build.
  pause
  exit /b 1
)
py -3.13 desktop_main.py
if errorlevel 1 (
  echo Startup failed. Run Install-Dependencies.cmd, then try again.
  pause
)
