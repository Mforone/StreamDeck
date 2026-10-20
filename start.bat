@echo off
rem Holt den neuesten Stand vom Server, installiert Pakete und startet die App ohne Konsolenfenster.
rem Alles steht in einem Block: cmd liest ihn komplett ein, bevor er laeuft. So stoert es nicht,
rem wenn git pull diese Datei waehrend der Ausfuehrung selbst aktualisiert.
(
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
    if errorlevel 1 (
        echo.
        echo Pakete konnten nicht installiert werden, siehe Meldung oben.
        pause
        exit /b 1
    )

    rem pythonw.exe startet ohne Konsole, start wartet nicht auf das Ende: das Fenster schliesst sich sofort
    rem Ausgaben und Fehler der App stehen in data\streamdeck.log
    start "" .venv\Scripts\pythonw.exe main.py
    exit /b 0
)
