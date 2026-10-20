import time
import tkinter as tk
from config import COLORS
from core.mic_monitor import MIN_DB

FALL_DB_PER_S = 30.0   # so schnell sinkt die Anzeige nach einem lauten Moment (wie bei echten Pegelanzeigen)
PEAK_HOLD_S = 1.5      # der höchste Wert bleibt als Strich so lange stehen

ZONE_COLORS = {"green": "#4CC38A", "yellow": "#E5B84B", "red": "#E54B4B"}


class LevelMeter(tk.Canvas):
    """Pegelanzeige in dBFS: grün / gelb / rot je nach Zone, mit sanftem Abfallen und Spitzenwert-Strich."""

    def __init__(self, master, orientation="vertical", bg=None, threshold_marker=False, **kwargs):
        super().__init__(master, width=1, height=1, bg=bg or COLORS["card"], highlightthickness=0, bd=0, **kwargs)
        self.vertical = orientation == "vertical"
        self.threshold_marker = threshold_marker
        self.shown_db = MIN_DB
        self.peak_db = MIN_DB
        self.peak_at = 0.0
        self.red_from = -3.0
        self.yellow_from = -12.0
        self._last = time.monotonic()
        self.bind("<Configure>", lambda e: self.redraw())

    def set_level(self, level_db, red_from, yellow_from):
        now = time.monotonic()
        elapsed = now - self._last
        self._last = now
        # Steigt sofort, fällt langsam: so sieht man auch kurze laute Momente
        self.shown_db = max(level_db, self.shown_db - FALL_DB_PER_S * elapsed, MIN_DB)
        if level_db >= self.peak_db or now - self.peak_at > PEAK_HOLD_S:
            self.peak_db = level_db
            self.peak_at = now
        self.red_from, self.yellow_from = red_from, yellow_from
        self.redraw()

    def _fraction(self, db):
        """dB -> Anteil der Skala (MIN_DB = 0, 0 dB = 1)."""
        return max(0.0, min(1.0, (db - MIN_DB) / -MIN_DB))

    def redraw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4 or h < 4:
            return
        length = h if self.vertical else w

        def rect(start, end, **style):
            """Abschnitt start..end (Anteile 0..1 der Skala) als Rechteck zeichnen."""
            a, b = start * length, end * length
            if self.vertical:
                self.create_rectangle(0, h - b, w, h - a, outline="", **style)
            else:
                self.create_rectangle(a, 0, b, h, outline="", **style)

        # Leere Skala, in den drei Zonen leicht eingefärbt, damit man die Grenzen auch in Stille sieht
        yellow = self._fraction(self.yellow_from)
        red = self._fraction(self.red_from)
        for start, end, name in ((0, yellow, "green"), (yellow, red, "yellow"), (red, 1, "red")):
            rect(start, end, fill=_dim(ZONE_COLORS[name]))

        # Gefüllter Teil: jede Zone in ihrer Farbe, bis zum aktuellen Pegel
        level = self._fraction(self.shown_db)
        for start, end, name in ((0, yellow, "green"), (yellow, red, "yellow"), (red, 1, "red")):
            if level > start:
                rect(start, min(level, end), fill=ZONE_COLORS[name])

        # Spitzenwert-Strich
        if self.peak_db > MIN_DB:
            p = self._fraction(self.peak_db) * length
            if self.vertical:
                self.create_line(0, h - p, w, h - p, fill=COLORS["text"], width=2)
            else:
                self.create_line(p, 0, p, h, fill=COLORS["text"], width=2)

        # Schwellwert-Markierung (Einstellungen)
        if self.threshold_marker:
            t = red * length
            if self.vertical:
                self.create_line(0, h - t, w, h - t, fill="#FFFFFF", width=3)
            else:
                self.create_line(t, 0, t, h, fill="#FFFFFF", width=3)


def _dim(color):
    """Sehr dunkle Fassung einer Zonenfarbe für die leere Skala."""
    from ui.colors import mix
    return mix(color, COLORS["bg"], 0.82)


def format_db(level_db):
    if level_db <= MIN_DB:
        return "-∞ dB"
    return f"{level_db:.0f} dB"
