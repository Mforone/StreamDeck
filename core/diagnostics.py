import ctypes
import faulthandler
import os
import sys
import threading
import time
import traceback
from datetime import datetime

# Fehlersuche bei Abstürzen:
# - Log mit Uhrzeit vor jeder Zeile, das Log vom vorherigen Start bleibt als streamdeck_vorher.log erhalten
# - faulthandler: schreibt bei harten Abstürzen (z. B. in Windows-Bibliotheken) die Stelle aller Threads ins Log
# - unbehandelte Fehler aus Hintergrund-Threads landen mit Uhrzeit im Log
# - alle 5 Minuten eine Zustandszeile (Speicher, Threads, Windows-Handles), damit man ein Volllaufen sieht
# - Hänger-Wächter: reagiert die Oberfläche oder der Audio-Thread länger nicht, steht im Log, wo jeder Thread steckt

LOG_FILE = os.path.join("data", "streamdeck.log")
PREVIOUS_LOG_FILE = os.path.join("data", "streamdeck_vorher.log")
HEALTH_INTERVAL_S = 300
HANG_AFTER_S = 10
WATCHDOG_CHECK_S = 2

_log_file = None  # rohe Logdatei für faulthandler (None = Konsole)


class TimestampedLog:
    """Datei-Ersatz für stdout/stderr, der vor jede neue Zeile die Uhrzeit schreibt."""

    def __init__(self, file):
        self.file = file
        self._at_line_start = True
        self._lock = threading.Lock()

    def write(self, text):
        if not text:
            return 0
        with self._lock:
            out = []
            for part in text.splitlines(keepends=True):
                if self._at_line_start:
                    out.append(datetime.now().strftime("%H:%M:%S "))
                out.append(part)
                self._at_line_start = part.endswith("\n")
            self.file.write("".join(out))
        return len(text)

    def flush(self):
        self.file.flush()

    def fileno(self):
        return self.file.fileno()


def setup_logging():
    """Nur ohne Konsole (pythonw.exe): Ausgaben in die Logdatei umleiten. Gibt die Datei zurück oder None."""
    if sys.stdout is not None and sys.stderr is not None:
        faulthandler.enable(all_threads=True)
        return None

    os.makedirs("data", exist_ok=True)
    # Vorheriges Log aufheben: nach einem Absturz startet man meist neu, dann wäre der Fehler sonst weg
    try:
        if os.path.exists(LOG_FILE):
            os.replace(LOG_FILE, PREVIOUS_LOG_FILE)
    except OSError:
        pass

    global _log_file
    log_file = open(LOG_FILE, "w", encoding="utf-8", buffering=1)
    _log_file = log_file
    sys.stdout = sys.stderr = TimestampedLog(log_file)
    # Harte Abstürze: faulthandler schreibt direkt in die Datei (ohne Uhrzeit, die steht in der Zeile davor)
    faulthandler.enable(file=log_file, all_threads=True)
    return log_file


def install_exception_hooks():
    def thread_hook(args):
        print(f"Unbehandelter Fehler im Thread {args.thread.name if args.thread else '?'}:")
        traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback)

    def main_hook(exc_type, exc_value, exc_traceback):
        print("Unbehandelter Fehler, Programm endet:")
        traceback.print_exception(exc_type, exc_value, exc_traceback)

    threading.excepthook = thread_hook
    sys.excepthook = main_hook


def _gui_resources():
    """Anzahl GDI- und USER-Objekte des Programms (Windows begrenzt beide auf 10 000 pro Programm)."""
    if sys.platform != "win32":
        return None, None
    process = ctypes.windll.kernel32.GetCurrentProcess()
    get = ctypes.windll.user32.GetGuiResources
    return get(process, 0), get(process, 1)


def health_line():
    import psutil
    process = psutil.Process()
    memory_mb = process.memory_info().rss / 1024 ** 2
    parts = [f"Speicher {memory_mb:.0f} MB", f"Threads {process.num_threads()}"]
    if sys.platform == "win32":
        parts.append(f"Handles {process.num_handles()}")
        gdi, user = _gui_resources()
        parts.append(f"GDI {gdi}")
        parts.append(f"USER {user}")
    return "Zustand: " + ", ".join(parts)


def start_health_log():
    def run():
        while True:
            try:
                print(health_line())
            except Exception as e:
                print(f"Zustand nicht lesbar: {e}")
            time.sleep(HEALTH_INTERVAL_S)

    threading.Thread(target=run, name="Zustand", daemon=True).start()


def _dump_all_threads(reason):
    print(f"HÄNGER: {reason}. Wo die Threads gerade stecken:")
    sys.stdout.flush()
    target = _log_file if _log_file is not None else sys.stderr
    faulthandler.dump_traceback(file=target, all_threads=True)
    target.flush()


def start_hang_watchdog(root, audio=None):
    """Oberfläche meldet sich jede Sekunde; ein eigener Thread prüft, ob die Meldungen ausbleiben.

    Hängt der Haupt-Thread, kann er selbst nichts mehr schreiben. Der Wächter-Thread schon:
    er schreibt dann für jeden Thread die Zeile, in der er gerade festsitzt.
    """
    state = {"ui": time.monotonic()}

    def heartbeat():
        state["ui"] = time.monotonic()
        root.after(1000, heartbeat)

    def watch():
        reported = {"ui": False, "audio": False}
        while True:
            time.sleep(WATCHDOG_CHECK_S)
            now = time.monotonic()
            checks = {"ui": ("Die Oberfläche", state["ui"])}
            if audio is not None and audio.is_ready():
                checks["audio"] = ("Der Audio-Thread", audio.last_tick())
            for key, (name, last) in checks.items():
                stuck = now - last
                if stuck > HANG_AFTER_S and not reported[key]:
                    _dump_all_threads(f"{name} reagiert seit {stuck:.0f} s nicht")
                    reported[key] = True
                elif stuck <= HANG_AFTER_S and reported[key]:
                    print(f"{name} reagiert wieder")
                    reported[key] = False

    heartbeat()
    threading.Thread(target=watch, name="Waechter", daemon=True).start()
