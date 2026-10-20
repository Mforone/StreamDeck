import math
import tkinter as tk
import tkinter.font as tkfont
from PIL import Image, ImageDraw, ImageTk
import customtkinter as ctk
from config import COLORS
from core.system_monitor import SystemMonitor

REFRESH_MS = 1000

# Ab welcher Auslastung die Farbe wechselt
WARN_FROM = 60
DANGER_FROM = 85

# Dreiviertelkreis: Start unten links, 270° im Uhrzeigersinn, Lücke unten.
# Pillow zählt Winkel im Uhrzeigersinn ab 3 Uhr: unten links = 135°.
ARC_START = 135
ARC_SPAN = 270

# Tk zeichnet Bögen unter Windows ohne Kantenglättung (treppig). Deshalb zeichnen wir den Ring mit Pillow
# in 4-facher Größe und verkleinern ihn: beim Verkleinern werden die Kanten weich.
SUPERSAMPLE = 4


def render_ring(size, line, percent, color, track_color, bg):
    """Dreiviertelkreis als Bild (size x size Pixel), Strichdicke line, Füllung bis percent (0..100 oder None)."""
    big = size * SUPERSAMPLE
    width = max(1, round(line * SUPERSAMPLE))
    image = Image.new("RGB", (big, big), bg)
    draw = ImageDraw.Draw(image)
    # Pillow zeichnet einen dicken Bogen von der Rahmenkante nach INNEN: die Strichmitte liegt also
    # eine halbe Strichdicke innerhalb des Rahmens. Genau dort sitzen auch die runden Enden.
    box = [0, 0, big - 1, big - 1]
    center = (big - 1) / 2
    radius = (big - width) / 2
    inset = width / 2

    def arc(sweep, fill):
        draw.arc(box, ARC_START, ARC_START + sweep, fill=fill, width=width)
        # Runde Enden: an Anfang und Ende ein Punkt in Strichdicke
        for angle in (ARC_START, ARC_START + sweep):
            x = center + radius * math.cos(math.radians(angle))
            y = center + radius * math.sin(math.radians(angle))
            draw.ellipse([x - inset, y - inset, x + inset, y + inset], fill=fill)

    arc(ARC_SPAN, track_color)
    if percent is not None and percent >= 0.5:
        arc(ARC_SPAN * min(percent, 100) / 100, color)
    return image.resize((size, size), Image.LANCZOS)


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
        self.bg = bg
        self._ring_key = None
        self._ring_image = None  # Referenz halten, sonst verschwindet das Bild (Tk kennt es nur schwach)
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
        size = int(min(h - 2 * pad, w * 0.34))
        line = max(3, size * 0.1)
        center_x = pad + size / 2
        center_y = h / 2
        radius = (size - line) / 2

        # Ring als geglättetes Bild; nur neu rechnen, wenn sich Größe, Wert oder Farbe geändert haben
        percent = None if self.percent is None else round(self.percent, 1)
        key = (size, percent, usage_color(self.percent))
        if key != self._ring_key:
            self._ring_key = key
            self._ring_image = ImageTk.PhotoImage(
                render_ring(size, line, percent, usage_color(self.percent), COLORS["border"], self.bg), master=self)
        self.create_image(pad, (h - size) // 2, image=self._ring_image, anchor="nw")

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
