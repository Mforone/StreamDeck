import threading

# Gemeinsame Verwaltung von PortAudio (die Bibliothek unter sounddevice) für Mikrofon und Soundboard.
# PortAudio liest die Geräteliste nur beim Start ein. Um neue Geräte zu sehen, muss man es neu starten,
# das würde aber laufende Aufnahmen und Sounds abwürgen. Deshalb: Neustart nur, wenn gerade nichts läuft.

_lock = threading.RLock()
_active = 0


def lock():
    """Für alles, was Streams öffnet/schließt oder Geräte abfragt: nie gleichzeitig mit einem Neustart."""
    return _lock


def stream_opened():
    global _active
    with _lock:
        _active += 1


def stream_closed():
    global _active
    with _lock:
        _active = max(0, _active - 1)


def refresh_devices():
    """Geräteliste neu einlesen, wenn gerade kein Stream läuft. Gibt zurück, ob neu eingelesen wurde."""
    import sounddevice as sd
    with _lock:
        if _active:
            return False
        sd._terminate()
        sd._initialize()
        return True


def wasapi_index():
    """Nummer von WASAPI (Windows' moderner Audioweg) oder None."""
    import sounddevice as sd
    return next((i for i, api in enumerate(sd.query_hostapis()) if "WASAPI" in api["name"]), None)
