import json
import os
import threading
import time

import psutil

from core.audio_manager import APP_BLACKLIST

# Der Audio-Dienst: EIN Hintergrund-Thread übernimmt alle Gespräche mit Windows-Audio.
# - liest pro Durchgang einmal alle Audiositzungen: laufende Apps, Lautstärke, Stumm, Pegel
# - setzt Lautstärke/Stumm, wenn die Oberfläche es verlangt (Befehle werden gesammelt und hier ausgeführt)
# - merkt sich, welche Apps je hörbar Ton abgegeben haben (data/audio_apps.json)
# Die Oberfläche liest nur fertige Werte und ruft selbst NIE Windows-Audio auf: hängt eine Abfrage
# (z. B. weil ein Spiel gerade seine Audiositzung umbaut), friert so höchstens der Mixer kurz ein, nie die ganze App.

WATCH_INTERVAL_S = 0.25
METER_INTERVAL_S = 1 / 30  # Pegel der App für den Lautstärkemesser: 30-mal pro Sekunde
DEVICE_REFRESH_S = 5.0     # Standard-Lautsprecher/-Mikrofon neu holen (falls in Windows gewechselt)
APPS_FILE = os.path.join("data", "audio_apps.json")
SAVE_EVERY_S = 60          # "zuletzt gehört" höchstens einmal pro Minute auf die Platte schreiben
AUDIBLE_PEAK = 0.01        # ab 1 % Pegel zählt es als "Ton abgegeben" (wie im Mixer-Dropdown)

SESSION_STATE_ACTIVE = 1   # AudioSessionStateActive: spielt gerade (Stream offen)
SESSION_STATE_EXPIRED = 2  # AudioSessionStateExpired: Sitzung beendet
MASTER = "master"
MIC = "mic"


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
        self._wake = threading.Event()
        self._known = load_known()
        self._running = set()       # Prozessnamen in Kleinbuchstaben
        self._last_sound = {}       # Prozessname (klein) -> time.monotonic() des letzten hörbaren Tons
        self._levels = {}           # Prozessname (klein) oder "master" -> (Lautstärke 0..1, stumm)
        self._sessions = []         # aktive Sitzungen für das Mixer-Dropdown
        self._pending = {}          # (Prozessname klein, "volume"/"mute") -> Wert, wartet auf Ausführung
        self._meters = {}           # Prozessname (klein) -> Pegelmesser seiner Sitzungen (vom letzten Durchgang)
        self._meter_target = ""     # App, deren Pegel der Lautstärkemesser gerade zeigt
        self._meter_peak = 0.0      # letzter Spitzenpegel dieser App (0..1)
        self._master = None
        self._mic = None
        self._mic_id = None
        self._devices_at = 0.0
        self._ready = False         # erst nach der ersten Abfrage sind die Werte aussagekräftig
        self._last_tick = time.monotonic()
        self._last_save = time.time()
        self._dirty = False
        self._reported = set()

        if start_thread:
            threading.Thread(target=self._run, name="Audio", daemon=True).start()

    # ---- für die Oberfläche (nur Lesen und Befehle ablegen, nie Windows aufrufen) ----

    def is_ready(self):
        return self._ready

    def last_tick(self):
        """Wann der Audio-Thread zuletzt einen Durchgang beendet hat (für die Hänger-Erkennung)."""
        return self._last_tick

    def running(self):
        with self._lock:
            return set(self._running)

    def sounding(self, within_s):
        """Laufende Apps, die in den letzten within_s Sekunden hörbar Ton abgegeben haben."""
        now = time.monotonic()
        with self._lock:
            return {name for name, at in self._last_sound.items() if now - at <= within_s and name in self._running}

    def known_apps(self):
        """Alle Apps, die je Ton abgegeben haben, zuletzt gehörte zuerst: [(process_name, last_heard), ...]"""
        own = psutil.Process().name().lower()  # früher gemerkter eigener Prozess (Test-Piep) ausblenden
        with self._lock:
            entries = [(v["process"], v["last_heard"]) for v in self._known.values() if v["process"].lower() != own]
        return sorted(entries, key=lambda e: e[1], reverse=True)

    def level(self, process_name):
        """(Lautstärke, stumm) einer App oder von "master"; None, solange unbekannt."""
        with self._lock:
            return self._levels.get(process_name.lower())

    def set_meter_target(self, process_name):
        """Welche App der Lautstärkemesser zeigen soll ("" = keine)."""
        self._meter_target = (process_name or "").lower()
        self._wake.set()

    def meter_peak(self):
        return self._meter_peak

    def mic_id(self):
        """Kennung des Standard-Mikrofons, ändert sich bei einem Wechsel in Windows."""
        return self._mic_id

    def sessions(self):
        with self._lock:
            return list(self._sessions)

    def set_volume(self, process_name, volume):
        self._queue(process_name, "volume", max(0.0, min(1.0, volume)))

    def set_mute(self, process_name, mute):
        self._queue(process_name, "mute", bool(mute))

    def _queue(self, process_name, kind, value):
        key = process_name.lower()
        with self._lock:
            # Beim Ziehen am Regler kommen viele Werte: nur der neueste zählt
            self._pending[(key, kind)] = value
            # Sofort so anzeigen, als wäre es schon gesetzt, sonst springt der Regler kurz zurück
            volume, mute = self._levels.get(key, (0.5, False))
            self._levels[key] = (value, mute) if kind == "volume" else (volume, value)
        self._wake.set()

    # ---- Audio-Thread ----

    def _run(self):
        # COM für diesen Thread einschalten (pycaw spricht über COM mit Windows)
        from core.audio_manager import ensure_com
        ensure_com()

        next_scan = 0.0
        while True:
            now = time.monotonic()
            # Voller Durchgang alle 0,25 s, oder sofort, wenn ein Befehl wartet
            if now >= next_scan or self._pending:
                try:
                    self._tick()
                except Exception as e:
                    self._report_once(f"Fehler im Audio-Dienst: {e}")
                next_scan = time.monotonic() + WATCH_INTERVAL_S
            # Dazwischen nur den Pegel der angezeigten App lesen (billig, deshalb 30-mal pro Sekunde)
            self._read_meter()
            self._last_tick = time.monotonic()
            wait = METER_INTERVAL_S if self._meter_target else next_scan - self._last_tick
            self._wake.wait(max(0.0, wait))
            self._wake.clear()

    def _read_meter(self):
        target = self._meter_target
        if not target:
            self._meter_peak = 0.0
            return
        peak = 0.0
        for meter in self._meters.get(target, []):
            try:
                peak = max(peak, float(meter.GetPeakValue()))
            except Exception:
                pass
        self._meter_peak = peak

    def _tick(self):
        running, heard, levels, sessions, controls, meters = self._scan()
        self._meters = meters
        self._apply_pending(controls, levels)

        now = time.time()
        with self._lock:
            # Befehle, die während des Durchgangs neu kamen, nicht mit alten Werten überschreiben
            for key, kind in self._pending:
                if key in self._levels:
                    levels[key] = self._levels[key]
            self._running = running
            self._levels = levels
            self._sessions = sessions
            self._ready = True
            for process_name in heard:
                self._last_sound[process_name.lower()] = time.monotonic()
            new_apps = {p for p in heard if p.lower() not in self._known}
            merge_heard(self._known, heard, now)
            if heard:
                self._dirty = True
            if new_apps or (self._dirty and now - self._last_save >= SAVE_EVERY_S):
                save_known(self._known)
                self._last_save = now
                self._dirty = False
        if new_apps:
            print(f"Mixer: neue App mit Ton gemerkt: {', '.join(sorted(new_apps))}")

    def _scan(self):
        # Pegelmesser direkt aus pycaw (comtypes.gen.AudioControlLib gibt es nicht, damit schlug es immer still fehl)
        from pycaw.pycaw import AudioUtilities, IAudioMeterInformation, ISimpleAudioVolume

        running, heard, levels, sessions, controls, meters = set(), set(), {}, [], {}, {}
        own_pid = os.getpid()
        for session in AudioUtilities.GetAllSessions():
            pid = session.ProcessId
            if not pid or pid == own_pid:  # eigener Prozess: der Test-Piep ist keine App
                continue
            try:
                # Selbst nachschlagen statt session.Process: das wirft, wenn der Prozess gerade beendet wurde
                process_name = psutil.Process(pid).name()
                state = session._ctl.GetState()
            except Exception:
                continue
            if is_blacklisted(process_name) or state == SESSION_STATE_EXPIRED:
                continue
            key = process_name.lower()
            running.add(key)

            try:
                volume = session._ctl.QueryInterface(ISimpleAudioVolume)
                controls.setdefault(key, []).append(volume)
                if key not in levels:
                    levels[key] = (float(volume.GetMasterVolume()), bool(volume.GetMute()))
            except Exception as e:
                self._report_once(f"Lautstärke von {process_name} nicht lesbar: {e}")

            try:
                meter = session._ctl.QueryInterface(IAudioMeterInformation)
                meters.setdefault(key, []).append(meter)
                if meter.GetPeakValue() >= AUDIBLE_PEAK:
                    heard.add(process_name)
            except Exception as e:
                self._report_once(f"Pegel von {process_name} nicht lesbar: {e}")

            if state == SESSION_STATE_ACTIVE:
                sessions.append({"name": f"{clean_name(process_name)} ({pid})", "process_name": process_name, "pid": pid})

        self._refresh_devices()
        for key, name in ((MASTER, "Master"), (MIC, "Mikrofon")):
            control = self._endpoint(key)
            if control is None:
                continue
            try:
                levels[key] = (float(control.GetMasterVolumeLevelScalar()), bool(control.GetMute()))
            except Exception as e:
                self._devices_at = 0.0  # z. B. Gerät abgesteckt: beim nächsten Mal neu holen
                self._report_once(f"{name}-Lautstärke nicht lesbar: {e}")
        return running, heard, levels, sessions, controls, meters

    def _endpoint(self, key):
        return self._master if key == MASTER else self._mic

    def _refresh_devices(self):
        """Standard-Lautsprecher und -Mikrofon regelmäßig neu holen: in Windows gewechselt = neues Gerät."""
        if time.monotonic() - self._devices_at < DEVICE_REFRESH_S:
            return
        self._devices_at = time.monotonic()
        from core.audio_manager import AudioManager
        self._master = AudioManager.get_master_volume_control()
        try:
            import comtypes
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            device = AudioUtilities.GetMicrophone()
            mic_id = device.GetId()
            if mic_id != self._mic_id or self._mic is None:
                interface = device.Activate(IAudioEndpointVolume._iid_, comtypes.CLSCTX_ALL, None)
                self._mic = interface.QueryInterface(IAudioEndpointVolume)
                self._mic_id = mic_id
        except Exception as e:
            self._mic = None
            self._mic_id = None
            self._report_once(f"Kein Standard-Mikrofon gefunden: {e}")

    def _apply_pending(self, controls, levels):
        with self._lock:
            pending, self._pending = self._pending, {}
        for (key, kind), value in pending.items():
            try:
                if key in (MASTER, MIC):
                    endpoint = self._endpoint(key)
                    if endpoint is None:
                        continue
                    if kind == "volume":
                        endpoint.SetMasterVolumeLevelScalar(value, None)
                    else:
                        endpoint.SetMute(value, None)
                else:
                    for control in controls.get(key, []):
                        if kind == "volume":
                            control.SetMasterVolume(value, None)
                        else:
                            control.SetMute(value, None)
                volume, mute = levels.get(key, (0.5, False))
                levels[key] = (value, mute) if kind == "volume" else (volume, value)
            except Exception as e:
                self._report_once(f"{kind} für {key} nicht setzbar: {e}")

    def _report_once(self, message):
        if message not in self._reported:
            self._reported.add(message)
            print(f"Mixer: {message}")
