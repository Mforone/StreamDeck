import tkinter as tk
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

    def __init__(self, master, name):
        super().__init__(master, bg=COLORS["sidebar"], highlightthickness=0, bd=0)
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
        size = min(h - 2 * pad, w * 0.5)
        line = max(4, size * 0.11)

        # Rahmen um den halben Strich nach innen, sonst wird der dicke Bogen am Rand abgeschnitten
        left = pad + line / 2
        top = (h - size) / 2 + line / 2
        right = pad + size - line / 2
        bottom = (h + size) / 2 - line / 2
        center_x = pad + size / 2
        center_y = h / 2

        # Hintergrundbogen (leer)
        self.create_arc(left, top, right, bottom, start=ARC_START, extent=-ARC_SPAN,
                        style="arc", outline=COLORS["border"], width=line)

        # Gefüllter Teil: negativer Winkel = im Uhrzeigersinn
        if self.percent is not None and self.percent >= 0.5:
            extent = -ARC_SPAN * min(self.percent, 100) / 100
            self.create_arc(left, top, right, bottom, start=ARC_START, extent=extent,
                            style="arc", outline=usage_color(self.percent), width=line)

        text = f"{self.percent:.0f}%" if self.percent is not None else "k. A."
        # Negative Schriftgröße = Pixel, so wächst die Schrift mit dem Kreis mit
        self.create_text(center_x, center_y, text=text, fill=COLORS["text"],
                         font=("Helvetica", -int(size * 0.24), "bold"))

        # Name und Zusatzinfo rechts neben dem Kreis
        text_x = pad + size + size * 0.18
        name_font = ("Helvetica", -int(size * 0.22), "bold")
        if self.detail:
            self.create_text(text_x, center_y - size * 0.02, text=self.name, anchor="sw",
                             fill=COLORS["text"], font=name_font)
            self.create_text(text_x, center_y + size * 0.04, text=self.detail, anchor="nw",
                             fill=COLORS["muted_text"], font=("Helvetica", -int(size * 0.15)))
        else:
            self.create_text(text_x, center_y, text=self.name, anchor="w",
                             fill=COLORS["text"], font=name_font)


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
            gauge = GaugeRow(rows, name)
            gauge.grid(row=index, column=0, sticky="nsew", pady=2)
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
