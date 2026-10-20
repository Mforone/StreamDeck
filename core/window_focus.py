import ctypes
import os
import sys
import tkinter as tk

# Das Control Panel läuft auf einem eigenen Bildschirm und soll niemandem den Fokus klauen:
# 1. Das Hauptfenster bekommt WS_EX_NOACTIVATE. Klicks kommen an, aber das Fenster,
#    das vorher im Fokus war (z. B. ein Spiel), bleibt im Fokus.
# 2. Nach einem Tippen per Touch springt die Maus dorthin zurück, wo sie vor dem Wechsel aufs Panel war.
#    Klicks mit der echten Maus (zum Einstellen) lösen keinen Rücksprung aus.
# 3. Falls das Panel trotzdem den Fokus bekommt, geht er an das vorherige Fenster zurück.

GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_APPWINDOW = 0x00040000  # Taskleisten-Eintrag behalten

# Windows markiert Maus-Nachrichten, die aus Touch- oder Stift-Eingaben entstehen, mit dieser Signatur
MI_WP_SIGNATURE = 0xFF515700
SIGNATURE_MASK = 0xFFFFFF00

TRACK_INTERVAL_MS = 100
RESTORE_DELAY_MS = 120


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


def _load_user32():
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    hwnd = ctypes.c_void_p

    user32.GetWindowLongPtrW.argtypes = [hwnd, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW.argtypes = [hwnd, ctypes.c_int, ctypes.c_ssize_t]
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = hwnd
    user32.SetForegroundWindow.argtypes = [hwnd]
    user32.SetForegroundWindow.restype = ctypes.c_int
    user32.IsWindow.argtypes = [hwnd]
    user32.IsWindow.restype = ctypes.c_int
    user32.GetWindowThreadProcessId.argtypes = [hwnd, ctypes.POINTER(ctypes.c_ulong)]
    user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
    user32.GetCursorPos.argtypes = [ctypes.POINTER(_POINT)]
    user32.GetCursorPos.restype = ctypes.c_int
    user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    user32.SetCursorPos.restype = ctypes.c_int
    user32.GetWindowRect.argtypes = [hwnd, ctypes.POINTER(_RECT)]
    user32.GetWindowRect.restype = ctypes.c_int
    user32.GetMessageExtraInfo.argtypes = []
    user32.GetMessageExtraInfo.restype = ctypes.c_ssize_t
    return user32


class FocusKeeper:
    def __init__(self, root, return_cursor=True):
        self.root = root
        self.return_cursor = return_cursor
        self.hwnd = None
        self.last_foreground = None
        self.last_cursor = None
        self._previous_sample = None
        self._previous_inside = False
        self._touch_click = False
        self._style_reported = False

        if sys.platform != "win32":
            return

        self.user32 = _load_user32()
        self.pid = os.getpid()

        # Erst nach dem Anzeigen anwenden, Tk setzt die Fensterstile beim Mappen/Vollbild neu
        root.after(500, self._start)

    def _start(self):
        try:
            self.hwnd = int(self.root.wm_frame(), 16)
        except Exception as e:
            print(f"Fokus-Schutz: Fensterhandle nicht ermittelbar: {e}")
            return

        self._ensure_style()
        self.root.bind_all("<ButtonPress-1>", self._on_press, add="+")
        self.root.bind_all("<ButtonRelease-1>", self._on_release, add="+")
        self._track()

    def _ensure_style(self):
        """Setzt WS_EX_NOACTIVATE und prüft es nach (läuft im Tracking-Loop mit, falls Tk es zurücksetzt)."""
        current = self.user32.GetWindowLongPtrW(self.hwnd, GWL_EXSTYLE)
        wanted = current | WS_EX_NOACTIVATE | WS_EX_APPWINDOW
        if current != wanted:
            self.user32.SetWindowLongPtrW(self.hwnd, GWL_EXSTYLE, wanted)

        if not self._style_reported:
            check = self.user32.GetWindowLongPtrW(self.hwnd, GWL_EXSTYLE)
            active = bool(check & WS_EX_NOACTIVATE)
            print(f"Fokus-Schutz: NOACTIVATE {'aktiv' if active else 'NICHT aktiv'} (exstyle=0x{check & 0xFFFFFFFF:08X})")
            self._style_reported = True

    def _is_own_window(self, hwnd):
        if not hwnd:
            return False
        pid = ctypes.c_ulong(0)
        self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value == self.pid

    def _track(self):
        """Merkt sich laufend das letzte fremde Fenster im Fokus und die letzte Mausposition außerhalb des Panels."""
        try:
            # Tk erzeugt das äußere Fenster beim Umschalten des Vollbilds manchmal neu: Handle aktuell halten
            self.hwnd = int(self.root.wm_frame(), 16)
            foreground = self.user32.GetForegroundWindow()
            if foreground and not self._is_own_window(foreground):
                self.last_foreground = foreground

            point = _POINT()
            rect = _RECT()
            if self.user32.GetCursorPos(ctypes.byref(point)) and self.user32.GetWindowRect(self.hwnd, ctypes.byref(rect)):
                inside = rect.left <= point.x < rect.right and rect.top <= point.y < rect.bottom
                sample = (point.x, point.y)
                # Nur Ruhepositionen merken, nicht den Punkt, an dem die Maus auf dem Weg zum Panel vorbeikam
                if not inside and sample == self._previous_sample:
                    self.last_cursor = sample
                self._previous_sample = sample
                self._previous_inside = inside

            self._ensure_style()
        except Exception as e:
            print(f"Fokus-Schutz: Fehler im Tracking: {e}")

        self.root.after(TRACK_INTERVAL_MS, self._track)

    def _on_press(self, event):
        """Entscheidet beim Drücken, ob der Klick vom Touchscreen oder von der Maus kommt."""
        # Weg 1: Windows-Signatur an der Nachricht (muss direkt hier abgefragt werden, nicht später)
        extra = self.user32.GetMessageExtraInfo() & 0xFFFFFFFF
        signed_touch = (extra & SIGNATURE_MASK) == MI_WP_SIGNATURE

        # Weg 2: Beim Tippen springt der Zeiger von außen direkt aufs Panel. Eine Maus
        # dagegen war vor dem Klick schon mindestens eine Messung lang über dem Panel.
        jumped_in = self._previous_sample is not None and not self._previous_inside

        self._touch_click = signed_touch or jumped_in
        print(f"Fokus-Schutz: Klick per {'Touch' if self._touch_click else 'Maus'} (Signatur={signed_touch}, von außen={jumped_in})")

    def _on_release(self, event):
        # Mit der Maus wird eingestellt: dann bleibt alles, wie es ist
        if not self._touch_click:
            return
        # Klicks in Popups und Dialogen zählen mit: nach der Auswahl/dem Speichern ist das Popup zu
        self.root.after(RESTORE_DELAY_MS, self._restore)

    def _other_window_open(self, widget=None):
        """True, solange noch ein Popup oder Dialog der App offen ist (dann bleibt die Maus, wo sie ist)."""
        widget = widget or self.root
        for child in widget.winfo_children():
            if isinstance(child, tk.Toplevel):
                return True
            if self._other_window_open(child):
                return True
        return False

    def _restore(self):
        try:
            if self._other_window_open():
                return
        except Exception:
            return

        if self.return_cursor and self.last_cursor:
            self.user32.SetCursorPos(*self.last_cursor)

        # Rückfall, falls NOACTIVATE nicht greift oder ein Popup den Fokus hatte: nur wenn die App
        # selbst vorne ist, damit ein gerade gestartetes Programm (Spotify, Discord ...) vorne bleiben darf
        foreground = self.user32.GetForegroundWindow()
        if (not foreground or self._is_own_window(foreground)) and self.last_foreground and self.user32.IsWindow(self.last_foreground):
            self.user32.SetForegroundWindow(self.last_foreground)
