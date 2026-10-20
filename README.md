# StreamDeck

Ein Software-Stream-Deck für Windows im „Steam Deck Style“: ein Vollbild-Control-Panel mit frei belegbaren App-Knöpfen und einem Audio-Mixer pro Anwendung.

## Funktionen

- **App-Knöpfe** (linke Leiste): starten Programme oder öffnen Webseiten, mit eigenem Namen, Icon und Farben. Bearbeiten und Löschen über das Knopf-Menü, neue Knöpfe über „+ App-Button“.
- **Audio-Mixer** (Mitte): Lautstärke und Stummschaltung für das ganze System und für jede Anwendung, die gerade Ton ausgibt.
- **Fokus-Schutz**: Das Panel nimmt keinem anderen Fenster den Fokus weg (gedacht für einen Nebenbildschirm). Nach einem Tippen auf dem Touchscreen springt die Maus dorthin zurück, wo sie vorher war. Mit der echten Maus lässt sich das Panel ganz normal bedienen und einstellen. Abschaltbar mit `"return_cursor": false` unter `settings` in `data/config.json`. Beendet wird die App über das ✕ oben links.
- **Systemmonitor** (rechts unten): Auslastung von CPU, GPU und RAM als Dreiviertelkreis, grün unter 60 %, gelb ab 60 %, rot ab 85 %. RAM zusätzlich in GB. Die GPU wird wie im Task-Manager über die Windows-Leistungsindikatoren gelesen (NVIDIA, AMD, Intel).
- **Mediaplayer** (rechts oben): in Arbeit.

## Voraussetzungen

- Windows 10 oder 11 (der Mixer nutzt die Windows-Audio-Schnittstelle über pycaw)
- Python 3.12 oder neuer

## Installation und Start

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Danach reicht ein Doppelklick auf `start.bat`: Sie holt per `git pull` den neuesten Stand, installiert fehlende Pakete und startet die App.

Die App startet im Vollbild, das ✕ oben links beendet sie.

## Konfiguration

Alle Knöpfe stehen in `data/config.json`. Die Datei wird beim ersten Start mit Standardknöpfen angelegt und danach von der App selbst gepflegt. Sie enthält persönliche Pfade und ist deshalb nicht im Repo (siehe `.gitignore`).

## Aufbau

| Pfad | Inhalt |
|---|---|
| `main.py` | Einstiegspunkt |
| `config.py` | Farbschema |
| `core/config_manager.py` | Laden und Speichern von `data/config.json` |
| `core/window_focus.py` | Fokus-Schutz und Maus-Rücksprung (Windows-API) |
| `core/audio_manager.py` | Lautstärke und Stummschaltung über pycaw |
| `ui/main_window.py` | Hauptfenster und Layout |
| `ui/StreamDeckFunktion.py` | App-Knöpfe und ihre Aktionen |
| `ui/edit_dialog.py` | Dialog zum Bearbeiten eines Knopfs |
| `ui/audio_mixer.py` | Mixer-Ansicht |
| `core/system_monitor.py` | Misst CPU, RAM (psutil) und GPU (Windows-PDH) im Hintergrund |
| `ui/system_monitor.py` | Dreiviertelkreis-Anzeigen des Systemmonitors |
