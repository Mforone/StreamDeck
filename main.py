import os
import sys

# Unter pythonw.exe (Start ohne Konsole) gibt es kein Konsolenfenster für Ausgaben.
# Dann landen alle Meldungen und Fehler in data/streamdeck.log (wird bei jedem Start neu angelegt).
if sys.stdout is None or sys.stderr is None:
    os.makedirs("data", exist_ok=True)
    log_file = open(os.path.join("data", "streamdeck.log"), "w", encoding="utf-8", buffering=1)
    sys.stdout = log_file
    sys.stderr = log_file

from core.config_manager import load_config
from ui.main_window import ControlPanelApp

if __name__ == "__main__":
    # 1. Konfiguration beim Anwendungsstart aus data/config.json laden
    config = load_config()

    # 2. App starten und Konfigurations-Daten an das Hauptfenster übergeben
    app = ControlPanelApp(config_data=config)
    app.mainloop()