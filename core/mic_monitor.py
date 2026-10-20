import io
import math
import struct
import sys
import threading
import time
import wave

# Mikrofon-Überwachung: liest das Standard-Mikrofon laufend mit, misst den Pegel in dBFS
# (0 dB = lauteste mögliche Aufnahme, Stille um -60 dB) und piept, wenn ein Schwellwert überschritten wird.
#
# Warum ein eigener Aufnahme-Stream? Windows' Pegelmesser für Mikrofone liefert nur Werte, solange
# irgendein Programm das Mikrofon geöffnet hat. Damit die Überwachung immer läuft, öffnen wir es selbst.

MIN_DB = -60.0             # alles darunter gilt als Stille
BLOCK_S = 0.02             # Audio kommt in 20-ms-Stücken
WINDOW_BLOCKS = 5          # Pegel = Mittel über die letzten 5 Stücke (100 ms): kurze Klicks lösen nicht aus
REARM_BELOW_DB = 3.0       # erst wieder piepen, wenn der Pegel 3 dB unter den Schwellwert gefallen war
MIN_BEEP_GAP_S = 2.0       # und frühestens 2 s nach dem letzten Piep
WARN_RANGE_DB = 6.0        # gelb: die letzten 6 dB (10 % der Skala) vor dem Schwellwert
SILENT_HINT_AFTER_S = 5.0  # so lange exakt 0 = vermutlich stumm oder von Windows blockiert
RESTART_CHECK_S = 2.0
FIRST_SIGNAL_DB = -50.0    # ab hier gilt es als "da kommt etwas an" (fürs Log)
DEFAULT_DEVICE = ""        # in den Einstellungen: "" = Windows-Standard

BEEP_HZ = 1046.5           # hohes C
BEEP_S = 0.14
BEEP_VOLUME = 0.35
SAMPLE_RATE_BEEP = 44100


# ---------------------------------------------------------------------------------------------------------
# Reine Hilfsfunktionen (ohne Mikrofon testbar)
# ---------------------------------------------------------------------------------------------------------

def to_db(amplitude):
    """Amplitude 0..1 -> dBFS, nach unten bei MIN_DB abgeschnitten."""
    if amplitude <= 0:
        return MIN_DB
    return max(MIN_DB, 20 * math.log10(amplitude))


def zone(level_db, red_from, yellow_from):
    if level_db >= red_from:
        return "red"
    if level_db >= yellow_from:
        return "yellow"
    return "green"


def mic_zones(threshold_db):
    """(rot ab, gelb ab) für den Mikrofon-Modus: rot ab Schwellwert, gelb in den 6 dB davor."""
    return threshold_db, threshold_db - WARN_RANGE_DB


APP_ZONES = (-3.0, -12.0)  # App-Modus: rot kurz vor dem Übersteuern, gelb ab -12 dB


class BeepTrigger:
    """Entscheidet, wann gepiept wird: einmal pro Überschreiten, dann erst wieder nach dem Leiserwerden."""

    def __init__(self, threshold_db):
        self.threshold_db = threshold_db
        self.armed = True
        self.last_beep = -1e9

    def update(self, level_db, now):
        if level_db >= self.threshold_db:
            if self.armed and now - self.last_beep >= MIN_BEEP_GAP_S:
                self.armed = False
                self.last_beep = now
                return True
        elif level_db < self.threshold_db - REARM_BELOW_DB:
            self.armed = True
        return False


def pick_device(devices, wanted, default_index):
    """Gerät für die Aufnahme wählen: das gewünschte (per Name), sonst das Windows-Standardgerät, sonst das erste.

    devices: [(index, name), ...]
    """
    if wanted:
        for index, name in devices:
            if name == wanted:
                return index, name
    for index, name in devices:
        if index == default_index:
            return index, name
    return devices[0] if devices else (None, None)


def make_beep_wav(frequency=BEEP_HZ, seconds=BEEP_S, volume=BEEP_VOLUME, rate=SAMPLE_RATE_BEEP):
    """Erzeugt einen kurzen Piepton als WAV-Datei im Speicher (keine Datei, kein Programm nötig)."""
    count = int(rate * seconds)
    fade = int(rate * 0.01)  # 10 ms ein- und ausblenden, sonst knackt es
    samples = bytearray()
    for i in range(count):
        envelope = min(1.0, i / fade, (count - i) / fade)
        value = volume * envelope * math.sin(2 * math.pi * frequency * i / rate)
        samples += struct.pack("<h", int(value * 32767))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(bytes(samples))
    return buffer.getvalue()


# ---------------------------------------------------------------------------------------------------------
# Überwachung
# ---------------------------------------------------------------------------------------------------------

class MicMonitor:
    def __init__(self, settings, audio=None):
        """settings: das dict settings["mic"] aus config.json (threshold_db, beep); audio: Audio-Dienst (für Gerätewechsel)."""
        self.settings = settings
        self.settings.setdefault("threshold_db", -12.0)
        self.settings.setdefault("beep", True)
        self.settings.setdefault("device", DEFAULT_DEVICE)
        self.audio = audio
        self.trigger = BeepTrigger(self.settings["threshold_db"])
        self._beep = make_beep_wav()
        self._lock = threading.Lock()
        self._energies = []
        self._level_db = MIN_DB
        self._last_signal = time.monotonic()
        self._status = "startet"
        self._stream = None
        self._restart = threading.Event()
        self._devices = []          # Namen aller erkannten Mikrofone (für die Einstellungen)
        self._default_name = ""     # Name des aktuellen Windows-Standard-Mikrofons
        self._device_name = ""      # Name des gerade überwachten Mikrofons
        self._signal_reported = False

        threading.Thread(target=self._run, name="Mikrofon", daemon=True).start()

    # ---- für die Oberfläche ----

    def level_db(self):
        return self._level_db

    def status(self):
        """Kurzer Zustand für die Einstellungen: "ok", "stumm", "kein Mikrofon" ..."""
        if self._status == "ok" and time.monotonic() - self._last_signal > SILENT_HINT_AFTER_S:
            return "stumm"
        return self._status

    def devices(self):
        """(alle erkannten Mikrofone, Windows-Standard, gerade überwacht)"""
        return list(self._devices), self._default_name, self._device_name

    def set_device(self, name):
        """Mikrofon wählen ("" = Windows-Standard) und die Aufnahme damit neu öffnen."""
        self.settings["device"] = name
        self._restart.set()

    def refresh_devices(self):
        """Geräteliste neu einlesen (z. B. Headset gerade angesteckt)."""
        self._restart.set()

    def set_threshold(self, threshold_db):
        self.settings["threshold_db"] = float(threshold_db)
        self.trigger.threshold_db = float(threshold_db)

    def set_beep_enabled(self, enabled):
        self.settings["beep"] = bool(enabled)

    def play_beep(self):
        threading.Thread(target=self._play, name="Piep", daemon=True).start()

    # ---- Hintergrund ----

    def _play(self):
        if sys.platform != "win32":
            return
        try:
            import winsound
            # SND_MEMORY: Ton direkt aus dem Speicher abspielen. Läuft im eigenen Thread, weil
            # winsound das Abspielen aus dem Speicher nur wartend (nicht asynchron) erlaubt.
            winsound.PlaySound(self._beep, winsound.SND_MEMORY | winsound.SND_NODEFAULT)
        except Exception as e:
            print(f"Mikrofon: Piep nicht abspielbar: {e}")

    def _callback(self, indata, frames, time_info, status):
        # Läuft im Audio-Thread von PortAudio: nur rechnen, nichts Langsames
        import numpy as np
        block = indata[:, 0] if indata.ndim > 1 else indata
        energy = float(np.mean(np.square(block, dtype=np.float64)))
        if energy > 0:
            self._last_signal = time.monotonic()
        if not self._signal_reported and energy > 0 and to_db(math.sqrt(energy)) > FIRST_SIGNAL_DB:
            self._signal_reported = True
            print(f"Mikrofon: Signal kommt an ({to_db(math.sqrt(energy)):.0f} dB)")

        self._energies.append(energy)
        if len(self._energies) > WINDOW_BLOCKS:
            del self._energies[0]
        # RMS über die letzten 100 ms: Wurzel aus der mittleren Energie
        self._level_db = to_db(math.sqrt(sum(self._energies) / len(self._energies)))

        if self.trigger.update(self._level_db, time.monotonic()) and self.settings.get("beep", True):
            self.play_beep()

    def _open_stream(self):
        import sounddevice as sd
        from core import portaudio
        # Geräteliste neu einlesen, damit ein angestecktes Headset oder ein in Windows gewechseltes
        # Standard-Mikrofon erkannt wird (nur wenn gerade kein Sound läuft, sonst würde er abbrechen)
        portaudio.refresh_devices()
        with portaudio.lock():
            return self._open_stream_locked(sd)

    def _open_stream_locked(self, sd):
        from core import portaudio

        # WASAPI ist Windows' moderner Audioweg: volle Gerätenamen wie in den Windows-Soundeinstellungen,
        # das Standardgerät ist das aktuelle aus Windows. Der alte Weg (MME) kürzt Namen auf 31 Zeichen.
        hostapis = sd.query_hostapis()
        wasapi = next((i for i, api in enumerate(hostapis) if "WASAPI" in api["name"]), None)
        api = wasapi if wasapi is not None else sd.default.hostapi
        devices = [(i, d["name"]) for i, d in enumerate(sd.query_devices())
                   if d["hostapi"] == api and d["max_input_channels"] > 0]
        default_index = hostapis[api]["default_input_device"]

        self._devices = [name for _, name in devices]
        self._default_name = next((name for i, name in devices if i == default_index), "")
        wanted = self.settings.get("device", DEFAULT_DEVICE)
        index, name = pick_device(devices, wanted, default_index)
        if index is None:
            raise RuntimeError("kein Mikrofon gefunden")
        if wanted and name != wanted:
            print(f"Mikrofon: \"{wanted}\" nicht gefunden, nehme \"{name}\"")

        info = sd.query_devices(index)
        rate = int(info["default_samplerate"])
        # auto_convert: Windows rechnet auf 1 Kanal und unsere Abtastrate um, egal was das Mikrofon liefert
        extra = sd.WasapiSettings(auto_convert=True) if wasapi is not None else None
        try:
            stream = sd.InputStream(device=index, channels=1, samplerate=rate, blocksize=int(rate * BLOCK_S),
                                    dtype="float32", callback=self._callback, extra_settings=extra)
            stream.start()
        except Exception as e:
            if wasapi is None:
                raise
            # Rückfall auf den alten Weg (MME), z. B. wenn ein Programm das Gerät exklusiv belegt
            print(f"Mikrofon: WASAPI ging nicht ({e}), versuche den alten Weg")
            info = sd.query_devices(kind="input")
            rate = int(info["default_samplerate"])
            stream = sd.InputStream(channels=1, samplerate=rate, blocksize=int(rate * BLOCK_S),
                                    dtype="float32", callback=self._callback)
            stream.start()
            name, api = info["name"], info["hostapi"]
        portaudio.stream_opened()
        self._device_name = name
        self._signal_reported = False
        print(f"Mikrofon: erkannt: {', '.join(self._devices)}")
        print(f"Mikrofon: überwache \"{name}\" mit {rate} Hz über {hostapis[api]['name']}"
              f"{' (Windows-Standard)' if not wanted else ''}")
        return stream

    def _run(self):
        try:
            import sounddevice  # noqa: F401 (nur prüfen, ob installiert)
            import numpy  # noqa: F401
        except Exception as e:
            self._status = "nicht installiert"
            print(f"Mikrofon: sounddevice/numpy fehlen ({e}), Überwachung aus")
            return

        current_id = None
        while True:
            # Standard-Mikrofon in Windows gewechselt? Dann Aufnahme neu öffnen
            mic_id = self.audio.mic_id() if self.audio is not None else None
            if self._stream is None or (mic_id and current_id and mic_id != current_id) or self._restart.is_set():
                self._restart.clear()
                self._close()
                try:
                    self._silence_logged = False
                    self._stream = self._open_stream()
                    self._status = "ok"
                    self._last_signal = time.monotonic()
                except Exception as e:
                    self._status = "kein Mikrofon"
                    if not getattr(self, "_reported_open", False):
                        print(f"Mikrofon: Aufnahme nicht möglich: {e}")
                        self._reported_open = True
                current_id = mic_id
            elif self._stream is not None and not self._stream.active:
                print("Mikrofon: Aufnahme abgebrochen, starte neu")
                self._restart.set()
            elif self._stream is not None and not self._signal_reported and \
                    time.monotonic() - self._last_signal > SILENT_HINT_AFTER_S and not getattr(self, "_silence_logged", False):
                print(f"Mikrofon: von \"{self._device_name}\" kommt seit {SILENT_HINT_AFTER_S:.0f} s nichts an "
                      f"(stumm, falsches Gerät oder von Windows blockiert)")
                self._silence_logged = True
            # Warten, aber sofort weiter, wenn in den Einstellungen ein anderes Mikrofon gewählt wurde
            self._restart.wait(RESTART_CHECK_S)

    def _close(self):
        if self._stream is not None:
            from core import portaudio
            try:
                with portaudio.lock():
                    self._stream.close()
            except Exception:
                pass
            portaudio.stream_closed()
            self._stream = None
            self._level_db = MIN_DB
            self._energies = []
