@echo off
rem Holt den neuesten Stand vom Server, installiert Pakete und startet die App.
cd /d "%~dp0"

git pull
if errorlevel 1 (
    echo.
    echo git pull ist fehlgeschlagen, starte mit dem lokalen Stand.
)

rem Kaputte oder halbfertige .venv entfernen
if exist .venv if not exist .venv\Scripts\python.exe rmdir /s /q .venv

if not exist .venv\Scripts\python.exe (
    rem Zuerst den Python-Launcher "py" versuchen, dann "python"
    py -3 -m venv .venv 2>nul
    if not exist .venv\Scripts\python.exe python -m venv .venv 2>nul
)

if not exist .venv\Scripts\python.exe (
    echo.
    echo Python wurde nicht gefunden.
    echo Bitte Python von https://www.python.org/downloads/ installieren
    echo und im Installer den Haken bei "Add python.exe to PATH" setzen.
    echo Danach start.bat erneut ausfuehren.
    echo.
    pause
    exit /b 1
)

.venv\Scripts\python.exe -m pip install -q -r requirements.txt
.venv\Scripts\python.exe main.py

if errorlevel 1 pause
