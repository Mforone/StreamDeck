import sys

# Unter pythonw.exe (Start ohne Konsole) gibt es kein Konsolenfenster für Ausgaben.
# Dann landen alle Meldungen und Fehler mit Uhrzeit in data/streamdeck.log,
# das Log vom vorherigen Start bleibt als data/streamdeck_vorher.log erhalten.
from core.diagnostics import install_exception_hooks, setup_logging, start_hang_watchdog, start_health_log

setup_logging()
install_exception_hooks()

print(f"Python {sys.version}")

from core.config_manager import load_config
from ui.main_window import ControlPanelApp


def report_tk_error(exc_type, exc_value, exc_traceback):
    """Fehler in Tk-Rückrufen (Klicks, after-Schleifen) mit Uhrzeit ins Log."""
    import traceback
    print("Fehler in der Oberfläche:")
    traceback.print_exception(exc_type, exc_value, exc_traceback)


if __name__ == "__main__":
    # 1. Konfiguration beim Anwendungsstart aus data/config.json laden
    config = load_config()

    # 2. App starten und Konfigurations-Daten an das Hauptfenster übergeben
    app = ControlPanelApp(config_data=config)
    app.report_callback_exception = report_tk_error
    start_health_log()
    start_hang_watchdog(app, audio=app.audio_watcher)
    app.mainloop()
    print("Programm regulär beendet")
