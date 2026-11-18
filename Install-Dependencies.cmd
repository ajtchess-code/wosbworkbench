@echo off
setlocal
cd /d "%~dp0"
py -3.13 -m pip install -r engine\requirements.txt
if errorlevel 1 echo Dependency installation failed. Verify Python 3.13 and pip.
pause
