import time
import tkinter as tk
import tkinter.font as tkfont
import customtkinter as ctk
from config import COLORS

# Höhe der Uhr: so viel geben die drei Monitoring-Kacheln zusammen ab (je 0,5 cm oben und unten = 1 cm pro Kachel).
# "c" ist in Tk die Einheit Zentimeter: winfo_fpixels("3c") rechnet echte Zentimeter in Pixel dieses Bildschirms um.
CLOCK_HEIGHT = "3c"

WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
          "August", "September", "Oktober", "November", "Dezember"]


def date_text(now):
    """time.struct_time -> "Dienstag, 20. Oktober" (unabhängig von der Spracheinstellung von Windows)"""
    return f"{WEEKDAYS[now.tm_wday]}, {now.tm_mday}. {MONTHS[now.tm_mon - 1]}"


class ClockPanel(ctk.CTkFrame):
    """Uhr in eigener Kachel: Stunden:Minuten groß, Sekunden kleiner daneben, Datum darunter."""

    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=COLORS["card"], corner_radius=12, **kwargs)
        height = round(self.winfo_fpixels(CLOCK_HEIGHT))
        # Feste Höhe: die Kachel bestimmt ihre Größe selbst, nicht ihr Inhalt
        self.configure(height=height)
        self.pack_propagate(False)

        self.canvas = tk.Canvas(self, width=1, height=1, bg=COLORS["card"], highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True, padx=10, pady=6)
        self.canvas.bind("<Configure>", lambda e: self.redraw())
        self._tick()

    def _tick(self):
        self.redraw()
        # Genau zum nächsten Sekundenwechsel wieder aufwachen, damit die Uhr nicht hinterherhinkt
        delay = 1000 - int((time.time() % 1) * 1000) + 5
        self.after(delay, self._tick)

    def redraw(self):
        canvas = self.canvas
        canvas.delete("all")
        w, h = canvas.winfo_width(), canvas.winfo_height()
        if w < 20 or h < 20:
            return
        now = time.localtime()

        # Schriftgrößen aus der Höhe: Uhrzeit gut die Hälfte, Datum ein Fünftel (negative Größe = Pixel)
        time_font = tkfont.Font(family="Helvetica", size=-int(h * 0.56), weight="bold")
        seconds_font = tkfont.Font(family="Helvetica", size=-int(h * 0.28), weight="bold")
        date_font = tkfont.Font(family="Helvetica", size=-int(h * 0.19), weight="bold")

        main = time.strftime("%H:%M", now)
        seconds = time.strftime(":%S", now)
        main_width = time_font.measure(main)
        total = main_width + seconds_font.measure(seconds)
        left = (w - total) / 2
        baseline = h * 0.64

        # Uhrzeit mittig; Sekunden auf derselben Grundlinie, damit sie unten bündig sitzen
        canvas.create_text(left, baseline, text=main, anchor="sw", font=time_font, fill=COLORS["text"])
        canvas.create_text(left + main_width, baseline - h * 0.05, text=seconds, anchor="sw",
                           font=seconds_font, fill=COLORS["muted_text"])
        canvas.create_text(w / 2, h * 0.84, text=date_text(now), anchor="center",
                           font=date_font, fill=COLORS["muted_text"])
