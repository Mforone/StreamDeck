import math
import tkinter as tk
import tkinter.font as tkfont
import customtkinter as ctk
from config import COLORS
from core.system_monitor import SystemMonitor

REFRESH_MS = 1000

# Ab welcher Auslastung die Farbe wechselt
WARN_FROM = 60
DANGER_FROM = 85

# Dreiviertelkreis: Start unten links (225°), 270° im Uhrzeigersinn, Lücke unten
ARC_START = 225
ARC_SPAN = 270


def usage_color(percent):
    if percent is None:
        return COLORS["muted_text"]
    if percent >= DANGER_FROM:
        return COLORS["danger"]
    if percent >= WARN_FROM:
        return COLORS["warn"]
    return COLORS["good"]


def format_gb(value):
    return f"{value:.1f}".replace(".", ",")


class GaugeRow(tk.Canvas):
    """Eine Zeile: Dreiviertelkreis mit Prozentwert links, Name und Zusatzinfo rechts daneben."""

    def __init__(self, master, name, bg):
        # width/height=1: Die Zeichenfläche verlangt selbst keinen Platz (Standard wären ~380x270 px),
        # ihre Größe bestimmt allein das Layout
        super().__init__(master, width=1, height=1, bg=bg, highlightthickness=0, bd=0)
        self.name = name
        self.percent = None
        self.detail = ""
        # Neu zeichnen, sobald sich die Größe ändert (Größe selbst wird hier nie verändert)
        self.bind("<Configure>", lambda e: self.redraw())

    def set_value(self, percent, detail=""):
        self.percent = percent
        self.detail = detail
        self.redraw()

    def redraw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 20 or h < 20:
            return

        # Kreisgröße richtet sich nach dem verfügbaren Platz, damit es auf jedem Bildschirm passt
        pad = 4
        size = min(h - 2 * pad, w * 0.34)
        line = max(3, size * 0.1)

        # Rahmen um den halben Strich nach innen, sonst wird der dicke Bogen am Rand abgeschnitten
        left = pad + line / 2
        top = (h - size) / 2 + line / 2
        right = pad + size - line / 2
        bottom = (h + size) / 2 - line / 2
        center_x = pad + size / 2
        center_y = h / 2

        radius = (size - line) / 2

        # Hintergrundbogen (leer)
        self._rounded_arc(center_x, center_y, radius, line, -ARC_SPAN, COLORS["border"])

        # Gefüllter Teil: negativer Winkel = im Uhrzeigersinn
        if self.percent is not None and self.percent >= 0.5:
            extent = -ARC_SPAN * min(self.percent, 100) / 100
            self._rounded_arc(center_x, center_y, radius, line, extent, usage_color(self.percent))

        text = f"{self.percent:.0f}%" if self.percent is not None else "k. A."
        # Schrift wächst mit dem Kreis mit, passt aber immer in sein Inneres
        self.create_text(center_x, center_y, text=text, fill=COLORS["text"],
                         font=self._fitting_font(text, size * 0.22, (radius - line / 2) * 1.6, bold=True))

        # Name und Zusatzinfo rechts neben dem Kreis, Schrift wird verkleinert, bis der Text in die Zeile passt
        text_x = pad + size + size * 0.15
        room = w - text_x - pad
        name_font = self._fitting_font(self.name, size * 0.2, room, bold=True)
        if self.detail:
            self.create_text(text_x, center_y - size * 0.02, text=self.name, anchor="sw",
                             fill=COLORS["text"], font=name_font)
            self.create_text(text_x, center_y + size * 0.04, text=self.detail, anchor="nw",
                             fill=COLORS["muted_text"], font=self._fitting_font(self.detail, size * 0.14, room))
        else:
            self.create_text(text_x, center_y, text=self.name, anchor="w",
                             fill=COLORS["text"], font=name_font)

    def _rounded_arc(self, center_x, center_y, radius, line, extent, color):
        """Bogen mit runden Enden: Tk kann das nicht selbst, deshalb sitzt an jedem Ende ein Punkt in Strichdicke."""
        self.create_arc(center_x - radius, center_y - radius, center_x + radius, center_y + radius,
                        start=ARC_START, extent=extent, style="arc", outline=color, width=line)
        for angle in (ARC_START, ARC_START + extent):
            # Winkel in Bogenmaß; Tk zählt gegen den Uhrzeigersinn ab 3 Uhr, y wächst nach unten
            x = center_x + radius * math.cos(math.radians(angle))
            y = center_y - radius * math.sin(math.radians(angle))
            self.create_oval(x - line / 2, y - line / 2, x + line / 2, y + line / 2, fill=color, outline="")

    @staticmethod
    def _fitting_font(text, pixels, max_width, bold=False):
        """Größte Schrift bis `pixels`, bei der `text` noch in `max_width` passt."""
        pixels = max(6, int(pixels))
        weight = "bold" if bold else "normal"
        while pixels > 6:
            # Negative Größe = Pixel statt Punkte
            if tkfont.Font(family="Helvetica", size=-pixels, weight=weight).measure(text) <= max_width:
                break
            pixels -= 1
        return ("Helvetica", -pixels, weight)


class SystemMonitorPanel(ctk.CTkFrame):
    def __init__(self, master, monitor=None, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)

        header = ctk.CTkLabel(
            self,
            text="🖥️ System",
            font=("Helvetica", 14, "bold"),
            text_color=COLORS["text"],
            anchor="w"
        )
        header.pack(fill="x", pady=(0, 4))

        rows = ctk.CTkFrame(self, fg_color="transparent")
        rows.pack(fill="both", expand=True)
        rows.grid_columnconfigure(0, weight=1)

        self.gauges = {}
        for index, (key, name) in enumerate([("cpu", "CPU"), ("gpu", "GPU"), ("ram", "RAM")]):
            rows.grid_rowconfigure(index, weight=1, uniform="gauges")

            # Eigene Box je Anzeige: etwas hellere Fläche mit runden Ecken, ohne Rahmen
            box = ctk.CTkFrame(rows, fg_color=COLORS["card"], corner_radius=12)
            box.grid(row=index, column=0, sticky="nsew", pady=4)

            # Innenabstand so groß wie die Eckenrundung, damit die Zeichenfläche die runden Ecken nicht überdeckt
            gauge = GaugeRow(box, name, bg=COLORS["card"])
            gauge.pack(fill="both", expand=True, padx=10, pady=6)
            self.gauges[key] = gauge

        # monitor=None nur zum Testen ohne echte Messung
        self.monitor = monitor if monitor is not None else SystemMonitor()
        if self.monitor:
            self.after(REFRESH_MS, self.refresh)

    def show_values(self, values):
        self.gauges["cpu"].set_value(values.get("cpu"))
        self.gauges["gpu"].set_value(values.get("gpu"))

        detail = ""
        if values.get("ram_used_gb") is not None and values.get("ram_total_gb") is not None:
            detail = f"{format_gb(values['ram_used_gb'])} / {format_gb(values['ram_total_gb'])} GB"
        self.gauges["ram"].set_value(values.get("ram"), detail)

    def refresh(self):
        self.show_values(self.monitor.get_values())
        self.after(REFRESH_MS, self.refresh)
