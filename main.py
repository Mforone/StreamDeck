from core.config_manager import load_config
from ui.main_window import ControlPanelApp

if __name__ == "__main__":
    # 1. Konfiguration beim Anwendungsstart aus data/config.json laden
    config = load_config()

    # 2. App starten und Konfigurations-Daten an das Hauptfenster übergeben
    app = ControlPanelApp(config_data=config)
    app.mainloop()