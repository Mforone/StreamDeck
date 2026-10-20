import json
import os
import threading
import time

import psutil

from core.audio_manager import APP_BLACKLIST

# Beobachtet im Hintergrund die Windows-Audiositzungen:
# - welche Apps gerade eine Audiositzung haben ("laufen", für das automatische Belegen der Mixer-Kanäle)
# - welche Apps jemals hörbar Ton abgegeben haben (dauerhaft in data/audio_apps.json, für die Auswahl in den Einstellungen)

WATCH_INTERVAL_S = 1.0
APPS_FILE = os.path.join("data", "audio_apps.json")
SAVE_EVERY_S = 60          # "zuletzt gehört" höchstens einmal pro Minute auf die Platte schreiben
AUDIBLE_PEAK = 0.01        # ab 1 % Pegel zählt es als "Ton abgegeben" (wie im Mixer-Dropdown)

SESSION_STATE_EXPIRED = 2  # AudioSessionStateExpired: Sitzung beendet


def clean_name(process_name):
    """'Spotify.exe' -> 'Spotify'"""
    return process_name[:-4] if process_name.lower().endswith(".exe") else process_name


def is_blacklisted(process_name):
    return clean_name(process_name).lower() in APP_BLACKLIST


def merge_heard(known, heard, now):
    """Trägt gehörte Apps ein. Gibt True zurück, wenn eine App neu ist (dann sofort speichern)."""
    is_new = False
    for process_name in heard:
        key = process_name.lower()
        if key not in known:
            is_new = True
            known[key] = {"process": process_name, "first_heard": now, "last_heard": now}
        else:
            known[key]["last_heard"] = now
    return is_new


def load_known():
    try:
        with open(APPS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_known(known):
    os.makedirs(os.path.dirname(APPS_FILE), exist_ok=True)
    temp = APPS_FILE + ".tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(known, f, indent=2, ensure_ascii=False)
    os.replace(temp, APPS_FILE)


class AudioAppWatcher:
    def __init__(self, start_thread=True):
        self._lock = threading.Lock()
        self._known = load_known()
        self._running = set()       # Prozessnamen in Kleinbuchstaben
        self._ready = False         # erst nach der ersten Abfrage ist _running aussagekräftig
        self._last_save = time.time()
        self._dirty = False
        self._reported = set()

        if start_thread:
            threading.Thread(target=self._run, daemon=True).start()

    # ---- für die Oberfläche ----

    def is_ready(self):
        return self._ready

    def running(self):
        with self._lock:
            return set(self._running)

    def known_apps(self):
        """Alle Apps, die je Ton abgegeben haben, zuletzt gehörte zuerst: [(process_name, last_heard), ...]"""
        with self._lock:
            entries = [(v["process"], v["last_heard"]) for v in self._known.values()]
        return sorted(entries, key=lambda e: e[1], reverse=True)

    # ---- Hintergrund ----

    def _run(self):
        # COM für diesen Thread einschalten (pycaw spricht über COM mit Windows)
        from core.audio_manager import ensure_com
        ensure_com()

        while True:
            try:
                running, heard = self._scan()
                now = time.time()
                with self._lock:
                    self._running = running
                    self._ready = True
                    is_new = merge_heard(self._known, heard, now)
                    if heard:
                        self._dirty = True
                    if is_new or (self._dirty and now - self._last_save >= SAVE_EVERY_S):
                        save_known(self._known)
                        self._last_save = now
                        self._dirty = False
                if is_new:
                    print(f"Mixer: neue App mit Ton gemerkt: {', '.join(sorted(heard))}")
            except Exception as e:
                self._report_once(f"Fehler beim Beobachten der Audio-Apps: {e}")
            time.sleep(WATCH_INTERVAL_S)

    def _scan(self):
        # Pegelmesser direkt aus pycaw (comtypes.gen.AudioControlLib gibt es nicht, damit schlug es immer still fehl)
        from pycaw.pycaw import AudioUtilities, IAudioMeterInformation

        running, heard = set(), set()
        for session in AudioUtilities.GetAllSessions():
            pid = session.ProcessId
            if not pid:
                continue
            try:
                # Selbst nachschlagen statt session.Process: das wirft, wenn der Prozess gerade beendet wurde
                process_name = psutil.Process(pid).name()
                state = session._ctl.GetState()
            except Exception:
                continue
            if is_blacklisted(process_name) or state == SESSION_STATE_EXPIRED:
                continue
            running.add(process_name.lower())

            try:
                meter = session._ctl.QueryInterface(IAudioMeterInformation)
                if meter.GetPeakValue() >= AUDIBLE_PEAK:
                    heard.add(process_name)
            except Exception as e:
                self._report_once(f"Pegel von {process_name} nicht lesbar: {e}")
        return running, heard

    def _report_once(self, message):
        if message not in self._reported:
            self._reported.add(message)
            print(f"Mixer: {message}")
