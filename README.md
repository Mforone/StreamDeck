# StreamDeck

Ein Software-Stream-Deck für Windows im „Steam Deck Style“: ein Vollbild-Control-Panel mit frei belegbaren App-Knöpfen und einem Audio-Mixer pro Anwendung.

## Funktionen

- **App-Knöpfe** (linke Leiste): starten Programme, öffnen Webseiten oder senden Tastenkombinationen an das Programm, das gerade vorne ist (Tasten antippen oder auf der Tastatur aufnehmen), oder spielen Sounds ab (Soundboard: im Discord-Call über VB-Audio Virtual Cable und gleichzeitig bei einem selbst, nochmal antippen stoppt), mit eigenem Namen, Icon und Farben. Bearbeiten und Löschen über das Knopf-Menü, neue Knöpfe über „+ App-Button“.
- **Audio-Mixer** (Mitte): Lautstärke und Stummschaltung für das ganze System und für jede Anwendung, die gerade Ton ausgibt.
- **Fokus-Schutz**: Das Panel nimmt keinem anderen Fenster den Fokus weg (gedacht für einen Nebenbildschirm). Nach einem Tippen auf dem Touchscreen springt die Maus dorthin zurück, wo sie vorher war. Mit der echten Maus lässt sich das Panel ganz normal bedienen und einstellen. Abschaltbar mit `"return_cursor": false` unter `settings` in `data/config.json`. Beendet wird die App über das ✕ oben links.
- **Einstellungen** (⚙ neben „Mediaplayer“): Reiter *Mixer* legt für die Kanäle 2 bis 8 eine feste App fest, die den Kanal automatisch belegt, sobald sie Ton abgibt, und eine eigene Farbe für die ganze Kanal-Karte. Gibt eine App 10 Sekunden lang keinen Ton ab, wird ihr Kanal wieder frei (einstellbar über `"mixer_idle_seconds"` unter `settings` in `data/config.json`). Zur Auswahl stehen alle Apps, die je Ton abgegeben haben (Verlauf in `data/audio_apps.json`). Reiter *Monitor* zeigt alle Bildschirme mit Auflösung und legt fest, auf welchem das Panel läuft (sofort und bei jedem Start).
- **Pegelanzeige und Mikrofon** (Kanal 8): umschaltbar zwischen App und Mikrofon; zeigt den Pegel in Echtzeit in dBFS (0 dB = Maximum), grün/gelb/rot. Im Mikrofon-Modus regelt der Kanal die Windows-Eingangslautstärke. Im Hintergrund wird das Standard-Mikrofon überwacht: über dem Schwellwert (Einstellungen, Reiter *Mikrofon*) ertönt ein kurzer Piep, einmal pro Überschreiten.
- **Uhr** (zwischen Mediaplayer und System): Uhrzeit mit Sekunden und Datum.
- **Systemmonitor** (rechts unten): Auslastung von CPU, GPU und RAM als Dreiviertelkreis, grün unter 60 %, gelb ab 60 %, rot ab 85 %. RAM zusätzlich in GB. Die GPU wird wie im Task-Manager über die Windows-Leistungsindikatoren gelesen (NVIDIA, AMD, Intel).
- **Mediaplayer** (rechts oben): zeigt Cover, Titel und Interpret von dem, was gerade läuft (Spotify, YouTube im Browser, VLC …), mit Zeitleiste zum Spulen, Zurück/Pause/Weiter sowie Shuffle und Wiederholen, wenn die App das unterstützt. Nutzt die Windows-Medienschnittstelle (Pakete in `requirements-media.txt`, optional).
- **Spotify** (unter dem Mediaplayer): die nächsten 5 Lieder der Warteschlange (antippen = dorthin springen), Shuffle (aus/an, Smart Shuffle wird blau angezeigt) und Wiederholen (aus/Liste/Lied) über die Spotify Web API. Braucht eine eigene Spotify-App unter developer.spotify.com (Konto mit Premium), Redirect URI `http://127.0.0.1:8765/callback`. Die Anmeldung landet in `data/spotify_token.json` (nicht im Repo).

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

Danach reicht ein Doppelklick auf `start.bat`: Sie holt per `git pull` den neuesten Stand, installiert fehlende Pakete und startet die App ohne Konsolenfenster. Meldungen und Fehler stehen dann in `data/streamdeck.log`.

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
| `core/media_session.py` | Liest und steuert die laufende Wiedergabe über die Windows-Medienschnittstelle |
| `ui/media_player.py` | Mediaplayer-Ansicht |
| `core/spotify.py` | Spotify-Anmeldung (PKCE) und Web API im Hintergrund |
| `core/audio_apps.py` | Beobachtet Audio-Apps: laufende und je gehörte (Verlauf) |
| `core/monitors.py` | Liest alle Monitore aus Windows |
| `ui/settings_dialog.py` | Einstellungen (Mixer-Kanäle, Monitor) |
| `core/mic_monitor.py` | Mikrofon-Überwachung, Pegel in dBFS, Piepton |
| `ui/level_meter.py` | Pegelanzeige grün/gelb/rot |
| `core/hotkeys.py` | Tastentabelle und Senden von Tastenkombinationen (Windows SendInput) |
| `ui/hotkey_picker.py` | Tastenkombination auswählen oder aufnehmen |
| `core/soundboard.py` | Soundboard: spielt Sounds auf virtuellem Kabel und eigenem Ausgang |
| `core/portaudio.py` | Gemeinsame Verwaltung der Audio-Bibliothek für Mikrofon und Soundboard |
| `ui/clock.py` | Uhr-Kachel |
| `ui/colors.py` | Farbhilfen (mischen, lesbare Schrift) |
| `ui/spotify_ui.py` | Warteschlange und Verbinden-Dialog |
| `ui/system_monitor.py` | Dreiviertelkreis-Anzeigen des Systemmonitors |
