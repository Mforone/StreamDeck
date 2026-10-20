@echo off
rem Holt den neuesten Stand vom Server und startet dann tools\starten.bat.
rem Alles steht in einem Block: cmd liest ihn komplett ein, bevor er laeuft. So stoert es nicht,
rem wenn git pull diese Datei waehrend der Ausfuehrung selbst aktualisiert.
rem Die eigentlichen Schritte stehen in tools\starten.bat: die wird erst NACH git pull gelesen
rem und ist dadurch immer auf dem neuesten Stand.
(
    cd /d "%~dp0"

    git pull
    if errorlevel 1 (
        echo.
        echo git pull ist fehlgeschlagen, starte mit dem lokalen Stand.
    )

    call tools\starten.bat
    exit /b
)
