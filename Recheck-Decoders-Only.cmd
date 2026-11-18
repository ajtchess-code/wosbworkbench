@echo off
setlocal
cd /d "%~dp0"
set "PYTHON=%~dp0.build-venv\Scripts\python.exe"
if not exist "%PYTHON%" (
  echo Missing build Python environment. Run Build-Windows.cmd first.
  pause
  exit /b 1
)
"%PYTHON%" "%~dp0engine\recover_everything.py" --output "%LOCALAPPDATA%\WoSBWorkbench\FullRecovery-AllClients" --no-catalog --no-code %*
if errorlevel 1 (
  echo.
  echo Decoder verification encountered errors. Inspect Recovery-Status.json.
) else (
  echo.
  echo Decoder recheck finished. Existing saved assets were reused where valid.
  echo Review updated per-client Reports and Review-For-Analysis folders.
)
pause
endlocal
