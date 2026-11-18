@echo off
cd /d "%~dp0"
py -3.13 run_local_wiki.py
if errorlevel 1 (
  echo.
  echo Could not launch the local Codex. Install Python 3.13, or use the
  echo compiled Workbench and choose Open local Web Wiki.
  pause
)
