import asyncio
import ctypes
import io
import sys
import threading
import time
from datetime import datetime, timezone

# Liest über die Windows-Medienschnittstelle (dieselbe wie die Medienanzeige am Lautstärkeregler),
# was gerade läuft: Spotify, YouTube im Browser, VLC ... und steuert es.
# Alles läuft in einem eigenen Thread mit eigener asyncio-Schleife; die Oberfläche liest nur get_state().

POLL_INTERVAL_S = 0.5
COVER_RETRY_DELAY_S = 1.5
COVER_SIZE = 256

PLAYBACK_PLAYING = 4  # GlobalSystemMediaTransportControlsSessionPlaybackStatus.PLAYING
TICKS_PER_SECOND = 10_000_000  # Windows rechnet Zeiten in 100-Nanosekunden-Schritten

# Wiederholen-Modi wie in Spotify: aus -> ganze Liste -> nur dieses Lied -> aus
REPEAT_CYCLE = {"off": "list", "list": "track", "track": "off"}
REPEAT_FROM_WINDOWS = {0: "off", 1: "track", 2: "list"}  # MediaPlaybackAutoRepeatMode
REPEAT_TO_WINDOWS = {"off": 0, "track": 1, "list": 2}

KNOWN_APPS = [
    ("spotify", "Spotify"),
    ("msedge", "Edge"),
    ("chrome", "Chrome"),
    ("firefox", "Firefox"),
    ("308046b0af4a39cb", "Firefox"),  # So meldet sich Firefox bei Windows
    ("opera", "Opera"),
    ("brave", "Brave"),
    ("vlc", "VLC"),
    ("zunemusic", "Media Player"),
    ("discord", "Discord"),
]

EMPTY_STATE = {
    "available": False,     # Medienschnittstelle nutzbar?
    "active": False,        # Läuft überhaupt etwas?
    "app": "",
    "title": "",
    "artist": "",
    "cover": None,          # PIL-Bild (schon mit runden Ecken) oder None
    "cover_key": None,      # ändert sich, sobald ein neues Cover da ist
    "playing": False,
    "duration": 0.0,        # Sekunden, 0 = App liefert keine Dauer
    "base_position": 0.0,   # Position in Sekunden zum Zeitpunkt base_time
    "base_time": 0.0,       # time.monotonic() der Messung
    "can_play_pause": False,
    "can_next": False,
    "can_previous": False,
    "can_seek": False,
    "can_shuffle": False,
    "can_repeat": False,
    "shuffle": None,        # True/False, None = unbekannt
    "repeat": None,         # "off" / "list" / "track", None = unbekannt
}


# ---------------------------------------------------------------------------------------------------------
# Reine Hilfsfunktionen (ohne Windows, deshalb auch auf dem Server testbar)
# ---------------------------------------------------------------------------------------------------------

def app_display_name(app_id):
    """Macht aus der Windows-Kennung (z. B. 'Spotify.exe', 'MSEdge') einen lesbaren Namen."""
    if not app_id:
        return ""
    lowered = app_id.lower()
    for needle, name in KNOWN_APPS:
        if needle in lowered:
            return name
    name = app_id.split("!")[0]
    if name.lower().endswith(".exe"):
        name = name[:-4]
    return name


def format_time(seconds):
    """3:41 oder 1:02:03"""
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def current_position(state, now=None):
    """Aktuelle Position: Windows meldet nur ab und zu einen Stand, beim Abspielen rechnen wir weiter."""
    position = state["base_position"]
    if state["playing"]:
        now = time.monotonic() if now is None else now
        position += now - state["base_time"]
    if state["duration"] > 0:
        position = min(position, state["duration"])
    return max(0.0, position)


def timeline_to_base(position_s, last_updated, playing, now_utc=None):
    """Rechnet die von Windows gemeldete Position auf 'jetzt' hoch.

    Windows liefert die Position zum Zeitpunkt last_updated. Läuft die Wiedergabe, ist seitdem Zeit vergangen.
    """
    if not playing or last_updated is None:
        return position_s
    try:
        if last_updated.tzinfo is None:
            last_updated = last_updated.replace(tzinfo=timezone.utc)
        now_utc = now_utc or datetime.now(timezone.utc)
        elapsed = (now_utc - last_updated).total_seconds()
    except Exception:
        return position_s
    # Unsinnige Zeitstempel (z. B. Jahr 1601 = "nie") ignorieren
    if elapsed < 0 or elapsed > 6 * 3600:
        return position_s
    return position_s + elapsed


def rounded_cover(data, size=COVER_SIZE, radius_ratio=0.12):
    """Bilddaten -> quadratisches PIL-Bild mit runden Ecken."""
    from PIL import Image, ImageDraw

    image = Image.open(io.BytesIO(data)).convert("RGBA")
    # Mittig quadratisch zuschneiden (YouTube-Vorschaubilder sind 16:9)
    side = min(image.size)
    left = (image.width - side) // 2
    top = (image.height - side) // 2
    image = image.crop((left, top, left + side, top + side)).resize((size, size), Image.LANCZOS)

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius=int(size * radius_ratio), fill=255)
    image.putalpha(mask)
    return image


# ---------------------------------------------------------------------------------------------------------
# Hintergrund-Thread mit der Windows-Schnittstelle
# ---------------------------------------------------------------------------------------------------------

class MediaSession:
    def __init__(self):
        self._lock = threading.Lock()
        self._state = dict(EMPTY_STATE)
        self._loop = None
        self._wake = None
        self._track_key = None
        self._cover_track_key = None
        self._cover_retry_at = None
        self._last_error = None

        if sys.platform != "win32":
            return
        threading.Thread(target=self._thread_main, daemon=True).start()

    # ---- Schnittstelle für die Oberfläche (Haupt-Thread) ----

    def get_state(self):
        with self._lock:
            return dict(self._state)

    def command(self, name, value=None):
        """Befehl an die laufende Wiedergabe schicken: play_pause, next, previous, seek, shuffle, repeat."""
        if self._loop is None or not self.get_state()["available"]:
            return
        asyncio.run_coroutine_threadsafe(self._run_command(name, value), self._loop)

    def patch_state(self, **changes):
        """Sofort sichtbare Änderung (z. B. Pause-Symbol), bis Windows den echten Stand meldet."""
        with self._lock:
            self._state.update(changes)

    # ---- Worker-Thread ----

    def _thread_main(self):
        # Dieser Thread nutzt COM im Multi-Thread-Modus. Der Haupt-Thread bleibt davon unberührt,
        # das brauchen die Datei- und Farbdialoge von Tk.
        try:
            ctypes.windll.ole32.CoInitializeEx(None, 0)  # 0 = COINIT_MULTITHREADED
        except Exception:
            pass

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._main())

    async def _main(self):
        try:
            # Erst hier importieren, damit winrt nur diesen Thread betrifft
            from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as SessionManager
            from winrt.windows.media import MediaPlaybackAutoRepeatMode
            from winrt.windows.storage.streams import Buffer, DataReader, InputStreamOptions
        except Exception as e:
            print(f"Mediaplayer: Windows-Medienschnittstelle nicht verfügbar ({e}). "
                  f"Fehlen die winrt-Pakete? Python {sys.version.split()[0]}")
            return

        self._repeat_enum = MediaPlaybackAutoRepeatMode
        self._buffer_types = (Buffer, DataReader, InputStreamOptions)
        self._wake = asyncio.Event()

        try:
            self._manager = await SessionManager.request_async()
        except Exception as e:
            print(f"Mediaplayer: Sitzungsverwaltung nicht erreichbar: {e}")
            return

        with self._lock:
            self._state["available"] = True
        print("Mediaplayer: Windows-Medienschnittstelle verbunden")

        while True:
            try:
                await self._poll()
            except Exception as e:
                self._log_error(f"Fehler beim Abfragen: {e}")
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=POLL_INTERVAL_S)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()

    def _log_error(self, message):
        # Gleiche Fehler nicht jede halbe Sekunde ins Log schreiben
        if message != self._last_error:
            print(f"Mediaplayer: {message}")
            self._last_error = message

    async def _poll(self):
        session = self._manager.get_current_session()
        if session is None:
            with self._lock:
                self._state.update({k: v for k, v in EMPTY_STATE.items() if k != "available"})
            self._track_key = None
            return

        app_id = session.source_app_user_model_id or ""
        props = await session.try_get_media_properties_async()
        info = session.get_playback_info()
        timeline = session.get_timeline_properties()
        controls = info.controls

        title = props.title or ""
        artist = props.artist or props.album_artist or ""
        playing = int(info.playback_status) == PLAYBACK_PLAYING

        duration = (timeline.end_time - timeline.start_time).total_seconds()
        position = (timeline.position - timeline.start_time).total_seconds()
        base_position = timeline_to_base(position, timeline.last_updated_time, playing)

        repeat = None
        if info.auto_repeat_mode is not None:
            repeat = REPEAT_FROM_WINDOWS.get(int(info.auto_repeat_mode))

        update = {
            "active": True,
            "app": app_display_name(app_id),
            "title": title,
            "artist": artist,
            "playing": playing,
            "duration": max(0.0, duration),
            "base_position": base_position,
            "base_time": time.monotonic(),
            "can_play_pause": bool(controls.is_play_pause_toggle_enabled),
            "can_next": bool(controls.is_next_enabled),
            "can_previous": bool(controls.is_previous_enabled),
            "can_seek": bool(controls.is_playback_position_enabled) and duration > 0,
            "can_shuffle": bool(controls.is_shuffle_enabled),
            "can_repeat": bool(controls.is_repeat_enabled),
            "shuffle": info.is_shuffle_active,
            "repeat": repeat,
        }

        # Neues Lied? Dann Cover holen (und nach kurzer Zeit nochmal, manche Apps liefern es verspätet)
        track_key = (app_id, title, artist)
        now = time.monotonic()
        if track_key != self._track_key:
            self._track_key = track_key
            self._cover_retry_at = now + COVER_RETRY_DELAY_S
            print(f"Mediaplayer: {app_id!r} | {title} | Dauer {duration:.0f}s | "
                  f"spulen={update['can_seek']} shuffle={update['can_shuffle']} wiederholen={update['can_repeat']}")
            await self._load_cover(props, track_key)
        elif self._cover_retry_at is not None and now >= self._cover_retry_at:
            self._cover_retry_at = None
            await self._load_cover(props, track_key)

        with self._lock:
            self._state.update(update)

    async def _load_cover(self, props, track_key):
        cover = None
        if props.thumbnail is not None:
            try:
                data = await self._read_stream(props.thumbnail)
                if data:
                    cover = rounded_cover(data)
            except Exception as e:
                self._log_error(f"Cover nicht lesbar: {e}")

        with self._lock:
            # Beim Nachladen ein vorhandenes Cover nicht durch "keins" ersetzen
            if cover is not None or self._cover_track_key != track_key:
                self._state["cover"] = cover
                self._state["cover_key"] = (track_key, time.monotonic()) if cover is not None else None
            self._cover_track_key = track_key

    async def _read_stream(self, reference):
        Buffer, DataReader, InputStreamOptions = self._buffer_types
        stream = await reference.open_read_async()
        size = int(stream.size)
        if size <= 0:
            return None
        buffer = Buffer(size)
        await stream.read_async(buffer, size, InputStreamOptions.READ_AHEAD)
        try:
            return bytes(memoryview(buffer))[:buffer.length]
        except TypeError:
            # Ältere winrt-Versionen: Umweg über DataReader
            reader = DataReader.from_buffer(buffer)
            data = bytearray(buffer.length)
            reader.read_bytes(data)
            return bytes(data)

    async def _run_command(self, name, value):
        try:
            session = self._manager.get_current_session()
            if session is None:
                return
            if name == "play_pause":
                await session.try_toggle_play_pause_async()
            elif name == "next":
                await session.try_skip_next_async()
            elif name == "previous":
                await session.try_skip_previous_async()
            elif name == "seek":
                await session.try_change_playback_position_async(int(value * TICKS_PER_SECOND))
            elif name == "shuffle":
                await session.try_change_shuffle_active_async(bool(value))
            elif name == "repeat":
                await session.try_change_auto_repeat_mode_async(self._repeat_enum(REPEAT_TO_WINDOWS[value]))
        except Exception as e:
            self._log_error(f"Befehl {name} fehlgeschlagen: {e}")
        finally:
            # Sofort neu abfragen statt bis zur nächsten halben Sekunde zu warten
            if self._wake is not None:
                self._wake.set()
