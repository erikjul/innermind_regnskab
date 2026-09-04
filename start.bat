@echo off
rem Starter InnerMind Regnskab og aabner browseren. Dobbeltklik paa filen.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Det virtuelle miljoe mangler. Koer foerst: python -m venv .venv ^&^& .venv\Scripts\pip install -r requirements.txt
  pause
  exit /b 1
)
start "" http://localhost:8000
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000
pause
