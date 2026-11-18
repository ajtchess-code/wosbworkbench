@echo off
setlocal
cd /d "%~dp0"
set "GAME_ROOT=C:\Games\World of Sea Battle\default\game"
set /p "CHOSEN=Game folder [%GAME_ROOT%]: "
if not "%CHOSEN%"=="" set "GAME_ROOT=%CHOSEN%"
set "OUTPUT=%LOCALAPPDATA%\WoSBWorkbench\ShaderAudit"
echo Analyzing local game-owned compiled shader effects (read-only)...
py -3.13 shader_recovery.py --game-root "%GAME_ROOT%" --output "%OUTPUT%" --export-compiled
if errorlevel 1 (
 echo Audit failed. Verify Python 3.13, dependencies, and client folder.
) else (
 echo Output: "%OUTPUT%\Shader-Audit.json"
)
pause
