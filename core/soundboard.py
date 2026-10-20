import os
import threading

from core import portaudio

# Soundboard: spielt Sounddateien gleichzeitig auf zwei Geräten ab, ohne ein anderes Programm zu öffnen:
# - auf dem virtuellen Kabel ("CABLE Input" von VB-Audio): Discord hört "CABLE Output" als Mikrofon,
#   Windows leitet dort auch die echte Stimme hinein ("Dieses Gerät abhören"), so hören alle im Call den Sound
# - auf dem eigenen Kopfhörer/Lautsprecher, damit man ihn selbst auch hört
# Jeder Sound bekommt eigene Streams; Windows mischt mehrere gleichzeitige Sounds von selbst.

CABLE_HINT = "CABLE Input"   # so heißt der Wiedergabe-Teil von VB-Audio Virtual Cable
AUTO = ""                    # in den Einstellungen: "" = automatisch (Kabel) bzw. Windows-Standard
CACHE_LIMIT = 30             # so viele Sounds bleiben dekodiert im Speicher (schneller Start beim zweiten Mal)
BLOCK_FRAMES = 1024

SUPPORTED = "*.mp3 *.wav *.ogg *.flac"

instance = None  # wird vom Hauptfenster gesetzt, damit Knöpfe und Dialoge dasselbe Soundboard nutzen


def find_device(devices, wanted, fallback):
    """devices: [(index, name)]; gewünschtes Gerät per Name, sonst fallback (Index), sonst None."""
    if wanted:
        for index, name in devices:
            if name == wanted:
                return index, name
    for index, name in devices:
        if index == fallback:
            return index, name
    return None, None


def find_cable(devices):
    return next(((i, n) for i, n in devices if CABLE_HINT.lower() in n.lower()), (None, None))


class _Playback:
    """Ein abgespielter Sound auf mehreren Geräten. stop() beendet ihn auf allen."""

    def __init__(self, path):
        self.path = path
        self.stopped = False
        self.done = threading.Event()

    def stop(self):
        self.stopped = True


class Soundboard:
    def __init__(self, settings):
        """settings: das dict settings["soundboard"] aus config.json."""
        self.settings = settings
        self.settings.setdefault("call_device", AUTO)
        self.settings.setdefault("local", True)
        self.settings.setdefault("local_device", AUTO)
        self.settings.setdefault("volume", 1.0)
        self._lock = threading.Lock()
        self._cache = {}
        self._playing = []
        self._devices = []
        self._default_output = None
        self._error = None

    # ---- für Knöpfe und Einstellungen ----

    def toggle(self, path, volume=1.0):
        """Antippen spielt den Sound, nochmal antippen (solange er läuft) stoppt ihn."""
        with self._lock:
            running = [p for p in self._playing if p.path == path and not p.done.is_set()]
        if running:
            for playback in running:
                playback.stop()
            return
        self.play(path, volume)

    def play(self, path, volume=1.0):
        playback = _Playback(path)
        with self._lock:
            self._playing = [p for p in self._playing if not p.done.is_set()] + [playback]
        # Laden und Abspielen im Hintergrund: die Oberfläche wartet nie auf das Dekodieren
        threading.Thread(target=self._run, args=(playback, volume), name="Sound", daemon=True).start()

    def stop_all(self):
        with self._lock:
            for playback in self._playing:
                playback.stop()

    def is_playing(self, path=None):
        with self._lock:
            return any(not p.done.is_set() and (path is None or p.path == path) for p in self._playing)

    def devices(self):
        """(Ausgabegeräte, Windows-Standard, gefundenes Kabel oder None, letzter Fehler)"""
        self._scan_devices()
        cable = find_cable(self._devices)[1]
        default = find_device(self._devices, AUTO, self._default_output)[1]
        return [n for _, n in self._devices], default, cable, self._error

    def refresh_devices(self):
        try:
            portaudio.refresh_devices()
        except Exception as e:
            self._error = f"Audio nicht verfügbar: {e}"
        self._scan_devices()

    # ---- intern ----

    def _scan_devices(self):
        try:
            import sounddevice as sd
            with portaudio.lock():
                api = portaudio.wasapi_index()
                if api is None:
                    api = sd.default.hostapi
                self._devices = [(i, d["name"]) for i, d in enumerate(sd.query_devices())
                                 if d["hostapi"] == api and d["max_output_channels"] > 0]
                self._default_output = sd.query_hostapis(api)["default_output_device"]
                self._wasapi = api == portaudio.wasapi_index()
        except Exception as e:
            self._devices, self._default_output = [], None
            self._error = f"Audio nicht verfügbar: {e}"

    def _targets(self):
        """Geräte, auf denen gespielt wird: das Kabel (für den Call) und der eigene Ausgang."""
        self._scan_devices()
        targets = []
        wanted_call = self.settings.get("call_device", AUTO)
        call = find_device(self._devices, wanted_call, None) if wanted_call else find_cable(self._devices)
        if call[0] is not None:
            targets.append(call)
        if self.settings.get("local", True):
            local = find_device(self._devices, self.settings.get("local_device", AUTO), self._default_output)
            # Ist das Kabel versehentlich Windows-Standard, nicht doppelt hineinspielen
            if local[0] is not None and local[0] != call[0]:
                targets.append(local)
        return targets, call[1]

    def _load(self, path):
        if path in self._cache:
            return self._cache[path]
        import soundfile
        data, rate = soundfile.read(path, dtype="float32", always_2d=True)
        if len(self._cache) >= CACHE_LIMIT:
            self._cache.pop(next(iter(self._cache)))
        self._cache[path] = (data, rate)
        return data, rate

    def _run(self, playback, volume):
        try:
            if not playback.path or not os.path.exists(playback.path):
                print(f"Soundboard: Datei nicht gefunden: {playback.path}")
                return
            try:
                data, rate = self._load(playback.path)
            except Exception as e:
                print(f"Soundboard: {os.path.basename(playback.path)} nicht lesbar: {e}")
                return

            targets, call_name = self._targets()
            if call_name is None:
                self._error = "Kein virtuelles Kabel gefunden: der Sound ist nur bei dir zu hören."
            else:
                self._error = None
            if not targets:
                print("Soundboard: kein Ausgabegerät gefunden")
                return

            gain = max(0.0, float(volume)) * max(0.0, float(self.settings.get("volume", 1.0)))
            streams = [s for s in (self._open(index, data, rate, gain, playback) for index, _ in targets) if s]
            # Warten, bis alle Geräte fertig sind (oder gestoppt wurde), dann aufräumen
            for stream, finished in streams:
                finished.wait()
            for stream, _ in streams:
                with portaudio.lock():
                    stream.close()
                portaudio.stream_closed()
        finally:
            playback.done.set()

    def _open(self, device, data, rate, gain, playback):
        import sounddevice as sd
        finished = threading.Event()
        position = [0]

        def callback(outdata, frames, time_info, status):
            if playback.stopped:
                outdata.fill(0)
                raise sd.CallbackStop
            chunk = data[position[0]:position[0] + frames]
            count = len(chunk)
            outdata[:count] = chunk * gain
            if count < frames:
                outdata[count:] = 0
                raise sd.CallbackStop  # Datei zu Ende
            position[0] += count

        # auto_convert: Windows passt Abtastrate und Kanalzahl an das Gerät an (z. B. 44,1 kHz Datei auf 48-kHz-Gerät)
        extra = sd.WasapiSettings(auto_convert=True) if getattr(self, "_wasapi", False) else None
        try:
            with portaudio.lock():
                stream = sd.OutputStream(device=device, samplerate=rate, channels=data.shape[1], dtype="float32",
                                         blocksize=BLOCK_FRAMES, callback=callback, extra_settings=extra,
                                         finished_callback=finished.set)
                stream.start()
                portaudio.stream_opened()
            return stream, finished
        except Exception as e:
            print(f"Soundboard: Gerät {device} nicht nutzbar: {e}")
            return None
