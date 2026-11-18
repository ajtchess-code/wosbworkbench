@echo off
setlocal
cd /d "%~dp0"
set "OUT=%LOCALAPPDATA%\WoSBWorkbench\FullRecovery-AllClients"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" "engine\recover_everything.py" --output "%OUT%" %*
) else (
  py -3.13 "engine\recover_everything.py" --output "%OUT%" %*
)
echo.
echo Full Recovery output: %OUT%
pause
