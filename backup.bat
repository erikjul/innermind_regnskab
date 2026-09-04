@echo off
rem Gemmer en sikkerhedskopi (zip) i REGNSKAB_BACKUP_DIR eller data\backup. Bruges fra Opgavestyring.
cd /d "%~dp0"
".venv\Scripts\python.exe" -m app.backup
