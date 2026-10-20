import time
import tkinter as tk
import tkinter.font as tkfont
import customtkinter as ctk
from config import COLORS

# Höhe der Uhr: so viel geben die drei Monitoring-Kacheln zusammen ab (je 0,5 cm oben und unten = 1 cm pro Kachel).
# "c" ist in Tk die Einheit Zentimeter: winfo_fpixels("3c") rechnet echte Zentimeter in Pixel dieses Bildschirms um.
CLOCK_HEIGHT = "3c"

class ClockPanel(ctk.CTkFrame):
    """Uhr in eigener Kachel: Stunden:Minuten so groß wie möglich, Sekunden kleiner daneben."""

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

        # So groß wie die Kachel hoch ist; ist der Text zu breit, wird er verkleinert, bis er passt
        main = time.strftime("%H:%M", now)
        seconds = time.strftime(":%S", now)
        size = int(h * 0.95)
        while size > 10:
            time_font = tkfont.Font(family="Helvetica", size=-size, weight="bold")
            seconds_font = tkfont.Font(family="Helvetica", size=-int(size * 0.45), weight="bold")
            main_width = time_font.measure(main)
            total = main_width + seconds_font.measure(seconds)
            if total <= w:
                break
            size -= 2

        # Senkrecht mittig: Ziffern sind etwa 72 % der Schriftgröße hoch. "sw" setzt die Unterkante des Textfelds,
        # darin steckt noch der Platz unter der Grundlinie (für g, p ...): den rechnen wir heraus.
        left = (w - total) / 2
        baseline = h / 2 + size * 0.36
        canvas.create_text(left, baseline + time_font.metrics("descent"), text=main, anchor="sw",
                           font=time_font, fill=COLORS["text"])
        # Sekunden auf derselben Grundlinie: unten bündig mit der großen Uhrzeit
        canvas.create_text(left + main_width, baseline + seconds_font.metrics("descent"), text=seconds,
                           anchor="sw", font=seconds_font, fill=COLORS["muted_text"])
