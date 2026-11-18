@echo off
setlocal
cd /d "%~dp0"
py -3.13 -m unittest discover -s tests -q
if errorlevel 1 exit /b %errorlevel%
py -3.13 research_suite.py release --root .
pause
