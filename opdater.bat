@echo off
rem Henter nyeste version af programmet fra GitHub og installerer evt. nye pakker.
cd /d "%~dp0"
git pull
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
echo Faerdig. Start programmet igen med start.bat.
pause
