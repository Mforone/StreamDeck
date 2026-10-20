import json
import os

# Ordner- und Dateipfad definieren
DATA_DIR = "data"
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")

# Standard-Einstellungen, falls keine JSON existiert
DEFAULT_CONFIG = {
    "settings": {
        "mixer_accent_color": "#1E2040"
    },
    "buttons": [
        {
            "id": "btn_0_0",
            "name": "Spotify",
            "bg_color": "#1E2040",
            "text_color": "#FFFFFF",
            "action_type": "program",
            "action_data": {
                "path": "C:\\Program Files\\Spotify\\Spotify.exe",
                "url": "",
                "hotkey": [],
                "sound_file": ""
            },
            "icon_path": ""
        },
        {
            "id": "btn_0_1",
            "name": "YouTube",
            "bg_color": "#1E2040",
            "text_color": "#FFFFFF",
            "action_type": "url",
            "action_data": {
                "path": "",
                "url": "https://youtube.com",
                "hotkey": [],
                "sound_file": ""
            },
            "icon_path": ""
        }
    ]
}

def ensure_data_dir_exists():
    """Stellt sicher, dass der data/-Ordner existiert."""
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR, exist_ok=True)

def load_config():
    """
    Lädt die Konfiguration aus data/config.json.
    Erstellt den Ordner und die Datei mit Standardwerten, falls sie nicht existieren oder leer sind.
    """
    ensure_data_dir_exists()

    if not os.path.exists(CONFIG_FILE) or os.path.getsize(CONFIG_FILE) == 0:
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Fehler beim Laden der config.json: {e}")
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG

def save_config(data):
    """Speichert das Konfigurations-Dictionary in data/config.json."""
    ensure_data_dir_exists()

    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        print(f"Configuration erfolgreich in '{CONFIG_FILE}' gespeichert!")
    except Exception as e:
        print(f"Fehler beim Speichern der config.json: {e}")