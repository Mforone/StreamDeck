@echo off
rem Holt den neuesten Stand vom Server, installiert Pakete und startet die App.
cd /d "%~dp0"

git pull
if errorlevel 1 (
    echo.
    echo git pull ist fehlgeschlagen, starte mit dem lokalen Stand.
)

if not exist .venv\Scripts\python.exe python -m venv .venv
.venv\Scripts\python.exe -m pip install -q -r requirements.txt
.venv\Scripts\python.exe main.py

if errorlevel 1 pause
