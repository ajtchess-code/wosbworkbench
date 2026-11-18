@echo off
setlocal
cd /d "%~dp0"
py -3.13 research_suite.py check
if errorlevel 1 echo Python 3.13 may be missing. Open START-HERE-v4.3.txt for setup.
pause
