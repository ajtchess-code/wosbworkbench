@echo off
setlocal
cd /d "%~dp0"
echo NONAUTHORITATIVE WoSB armor/penetration comparison. NOT an in-game HP prediction.
set /p "ARMOR=Target basic armor [12]: "
if "%ARMOR%"=="" set "ARMOR=12"
set /p "ANGLE=Impact obliquity (degrees from normal) [0]: "
if "%ANGLE%"=="" set "ANGLE=0"
py -3.13 damage_hypotheses.py --cannon "42-pdr Carronade" --ammo "Round Shot" --armor %ARMOR% --angle %ANGLE%
pause
