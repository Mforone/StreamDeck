import tkinter as tk
from tkinter import colorchooser
import customtkinter as ctk
from config import COLORS
from core.audio_apps import clean_name
from core.monitors import list_monitors, monitor_label
from ui.colors import contrast_text
from ui.window_utils import center_over

MIXER_CHANNELS = range(2, 9)  # Kanal 1 ist der Master
NO_APP = "Keine feste App"

PRESET_COLORS = [
    "#5B8CCC", "#3BB7C9", "#4CC38A", "#1DB954", "#E5B84B", "#E8893A",
    "#E54B4B", "#E05FA0", "#9B6BDF", "#5865F2", "#8888AA", "#D8D8E8",
]


class SettingsDialog(ctk.CTkToplevel):
    """Einstellungen mit zwei Reitern: Mixer-Kanäle und Monitor."""

    def __init__(self, root, watcher, settings, on_mixer_change, on_monitor_change, current_device):
        super().__init__(root)
        self.root = root
        self.watcher = watcher
        self.settings = settings
        self.on_mixer_change = on_mixer_change
        self.on_monitor_change = on_monitor_change
        self.current_device = current_device
        self._palette = None

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(fg_color=COLORS["card"])
        center_over(self, root, 560, 600)

        box = ctk.CTkFrame(self, fg_color=COLORS["card"], border_color=COLORS["border"], border_width=1, corner_radius=12)
        box.pack(fill="both", expand=True)
        inner = ctk.CTkFrame(box, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=16, pady=12)

        header = ctk.CTkFrame(inner, fg_color="transparent")
        header.pack(fill="x")
        ctk.CTkLabel(header, text="⚙ Einstellungen", font=("Helvetica", 15, "bold"),
                     text_color=COLORS["accent_hover"]).pack(side="left")
        ctk.CTkButton(header, text="✕", width=32, height=32, fg_color="transparent", hover_color=COLORS["card_hover"],
                      text_color=COLORS["accent_hover"], font=("Helvetica", 15, "bold"),
                      command=self.close).pack(side="right")

        tabs = ctk.CTkTabview(inner, fg_color=COLORS["bg"], segmented_button_fg_color=COLORS["bg"],
                              segmented_button_selected_color=COLORS["accent"],
                              segmented_button_selected_hover_color=COLORS["accent_hover"],
                              segmented_button_unselected_color=COLORS["bg"],
                              segmented_button_unselected_hover_color=COLORS["card_hover"],
                              text_color=COLORS["text"], corner_radius=10)
        tabs.pack(fill="both", expand=True, pady=(6, 0))
        tabs._segmented_button.configure(font=("Helvetica", 13, "bold"), height=34)

        self._build_mixer_tab(tabs.add("🎛️ Mixer"))
        self._build_monitor_tab(tabs.add("🖥️ Monitor"))

        # Tippen irgendwo im Dialog schließt eine offene Farbauswahl
        self.bind("<Button-1>", self._close_palette_on_outside_click, add="+")
        self.focus_force()

    def close(self):
        self._close_palette()
        self.destroy()

    # ------------------------------------------------------------------------------------------------
    # Reiter Mixer
    # ------------------------------------------------------------------------------------------------

    def _channel(self, number):
        return self.settings.setdefault("mixer_channels", {}).setdefault(str(number), {})

    def _build_mixer_tab(self, tab):
        # Auswahl: alle Apps, die je Ton abgegeben haben, zuletzt gehörte zuerst
        self.app_by_name = {}
        for process, _ in self.watcher.known_apps() if self.watcher else []:
            self.app_by_name.setdefault(clean_name(process), process)

        header = ctk.CTkFrame(tab, fg_color="transparent")
        header.pack(fill="x", padx=4, pady=(2, 4))
        header.grid_columnconfigure(1, weight=1)
        for column, text in enumerate(("Kanal", "Feste App (aktiviert sich beim Start)", "Farbe")):
            ctk.CTkLabel(header, text=text, font=("Helvetica", 11, "bold"), text_color=COLORS["muted_text"],
                         anchor="w").grid(row=0, column=column, sticky="w", padx=(0, 10))

        self.color_buttons = {}
        for number in MIXER_CHANNELS:
            channel = self._channel(number)
            row = ctk.CTkFrame(tab, fg_color=COLORS["card"], corner_radius=8)
            row.pack(fill="x", padx=4, pady=3)
            row.grid_columnconfigure(1, weight=1)

            ctk.CTkLabel(row, text=f"Kanal {number}", width=70, anchor="w", font=("Helvetica", 13, "bold"),
                         text_color=COLORS["text"]).grid(row=0, column=0, padx=(10, 6), pady=6)

            names = list(self.app_by_name)
            fixed = channel.get("app", "")
            if fixed and clean_name(fixed) not in self.app_by_name:
                # Gespeicherte App, die im Verlauf fehlt (z. B. Datei gelöscht): trotzdem anbieten
                self.app_by_name[clean_name(fixed)] = fixed
                names.append(clean_name(fixed))

            menu = ctk.CTkOptionMenu(
                row, values=[NO_APP] + names, height=34, font=("Helvetica", 13, "bold"),
                dropdown_font=("Helvetica", 13), fg_color=COLORS["bg"], button_color=COLORS["bg"],
                button_hover_color=COLORS["card_hover"], dropdown_fg_color=COLORS["card"],
                dropdown_hover_color=COLORS["card_hover"], text_color=COLORS["text"],
                command=lambda value, n=number: self._set_app(n, value))
            menu.set(clean_name(fixed) if fixed else NO_APP)
            menu.grid(row=0, column=1, sticky="ew", pady=6)

            color = channel.get("color") or COLORS["accent"]
            button = ctk.CTkButton(row, text="", width=44, height=34, corner_radius=8, fg_color=color,
                                   hover_color=color, border_width=2, border_color=COLORS["border"])
            button.configure(command=lambda n=number, b=button: self._open_palette(n, b))
            button.grid(row=0, column=2, padx=10, pady=6)
            self.color_buttons[number] = button

        if not self.app_by_name:
            ctk.CTkLabel(tab, text="Noch keine Apps gemerkt: sobald eine App Ton abgibt, steht sie hier zur Auswahl.",
                         font=("Helvetica", 11, "bold"), text_color=COLORS["muted_text"], wraplength=480,
                         justify="left").pack(fill="x", padx=6, pady=(8, 0))

    def _set_app(self, number, value):
        channel = self._channel(number)
        if value == NO_APP:
            channel.pop("app", None)
        else:
            channel["app"] = self.app_by_name[value]
        self.on_mixer_change()

    def _set_color(self, number, color):
        self._channel(number)["color"] = color
        self.color_buttons[number].configure(fg_color=color, hover_color=color)
        self.on_mixer_change()

    def _open_palette(self, number, button):
        reopen = self._palette is None or self._palette[0] != number
        self._close_palette()
        if not reopen:
            return  # zweites Tippen auf dieselbe Farbe schließt die Auswahl

        popup = ctk.CTkToplevel(self)
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)
        popup.configure(fg_color=COLORS["card"])
        frame = ctk.CTkFrame(popup, fg_color=COLORS["card"], border_color=COLORS["border"], border_width=1, corner_radius=10)
        frame.pack(fill="both", expand=True)

        grid = ctk.CTkFrame(frame, fg_color="transparent")
        grid.pack(padx=8, pady=(8, 4))
        for index, color in enumerate(PRESET_COLORS):
            ctk.CTkButton(grid, text="", width=36, height=36, corner_radius=8, fg_color=color, hover_color=color,
                          command=lambda c=color: self._pick(number, c)).grid(row=index // 6, column=index % 6, padx=3, pady=3)
        ctk.CTkButton(frame, text="Eigene Farbe …", height=32, font=("Helvetica", 12, "bold"), fg_color=COLORS["bg"],
                      hover_color=COLORS["card_hover"], text_color=COLORS["text"],
                      command=lambda: self._pick_custom(number)).pack(fill="x", padx=11, pady=(0, 8))

        popup.update_idletasks()
        x = button.winfo_rootx() + button.winfo_width() - popup.winfo_reqwidth()
        y = button.winfo_rooty() + button.winfo_height() + 4
        popup.geometry(f"+{x}+{y}")
        self._palette = (number, popup)

    def _pick(self, number, color):
        self._close_palette()
        self._set_color(number, color)

    def _pick_custom(self, number):
        self._close_palette()
        current = self._channel(number).get("color") or COLORS["accent"]
        result = colorchooser.askcolor(initialcolor=current, parent=self, title=f"Farbe für Kanal {number}")
        if result and result[1]:
            self._set_color(number, result[1].upper())

    def _close_palette(self):
        if self._palette is not None:
            if self._palette[1].winfo_exists():
                self._palette[1].destroy()
            self._palette = None

    def _close_palette_on_outside_click(self, event):
        if self._palette is None:
            return
        # Klick auf einen Farbknopf öffnet/schließt selbst, alles andere schließt die Auswahl
        if any(event.widget is b or str(event.widget).startswith(str(b)) for b in self.color_buttons.values()):
            return
        self._close_palette()

    # ------------------------------------------------------------------------------------------------
    # Reiter Monitor
    # ------------------------------------------------------------------------------------------------

    def _build_monitor_tab(self, tab):
        self.monitors = list_monitors()
        if not self.monitors:
            ctk.CTkLabel(tab, text="Monitore konnten nicht ermittelt werden.", font=("Helvetica", 12, "bold"),
                         text_color=COLORS["muted_text"]).pack(pady=20)
            return

        # Übersicht: Monitore maßstabsgetreu in ihrer echten Anordnung, antippbar
        self.layout = tk.Canvas(tab, height=170, bg=COLORS["bg"], highlightthickness=0, bd=0)
        self.layout.pack(fill="x", padx=4, pady=(4, 8))
        self.layout.bind("<Configure>", lambda e: self._draw_layout())

        self.monitor_buttons = []
        for monitor in self.monitors:
            button = ctk.CTkButton(tab, text=monitor_label(monitor), anchor="w", height=40, corner_radius=8,
                                   font=("Helvetica", 13, "bold"),
                                   command=lambda m=monitor: self._choose_monitor(m))
            button.pack(fill="x", padx=4, pady=3)
            self.monitor_buttons.append((monitor, button))
        self._refresh_monitor_buttons()

    def _draw_layout(self):
        canvas = self.layout
        canvas.delete("all")
        width, height = canvas.winfo_width(), canvas.winfo_height()
        if width < 50:
            return

        left = min(m["x"] for m in self.monitors)
        top = min(m["y"] for m in self.monitors)
        right = max(m["x"] + m["width"] for m in self.monitors)
        bottom = max(m["y"] + m["height"] for m in self.monitors)
        pad = 10
        scale = min((width - 2 * pad) / (right - left), (height - 2 * pad) / (bottom - top))
        offset_x = (width - (right - left) * scale) / 2
        offset_y = (height - (bottom - top) * scale) / 2

        for monitor in self.monitors:
            x0 = offset_x + (monitor["x"] - left) * scale + 2
            y0 = offset_y + (monitor["y"] - top) * scale + 2
            x1 = offset_x + (monitor["x"] + monitor["width"] - left) * scale - 2
            y1 = offset_y + (monitor["y"] + monitor["height"] - top) * scale - 2
            chosen = monitor["device"] == self.current_device
            fill = COLORS["accent"] if chosen else COLORS["card"]
            tag = f"monitor{monitor['number']}"
            canvas.create_rectangle(x0, y0, x1, y1, fill=fill, outline=COLORS["border"], width=2, tags=tag)
            canvas.create_text((x0 + x1) / 2, (y0 + y1) / 2 - 8, text=str(monitor["number"]), tags=tag,
                               fill=contrast_text(fill), font=("Helvetica", 16, "bold"))
            canvas.create_text((x0 + x1) / 2, (y0 + y1) / 2 + 12, text=f"{monitor['width']}×{monitor['height']}",
                               tags=tag, fill=contrast_text(fill), font=("Helvetica", 9, "bold"))
            canvas.tag_bind(tag, "<Button-1>", lambda e, m=monitor: self._choose_monitor(m))

    def _refresh_monitor_buttons(self):
        for monitor, button in self.monitor_buttons:
            chosen = monitor["device"] == self.current_device
            button.configure(
                text=("✓  " if chosen else "     ") + monitor_label(monitor),
                fg_color=COLORS["accent"] if chosen else COLORS["card"],
                hover_color=COLORS["accent_hover"] if chosen else COLORS["card_hover"],
                text_color=COLORS["text"])

    def _choose_monitor(self, monitor):
        if monitor["device"] == self.current_device:
            return
        self.current_device = monitor["device"]
        self._refresh_monitor_buttons()
        self._draw_layout()
        self.on_monitor_change(monitor)
        # Das Panel ist umgezogen: Dialog mitnehmen
        self.after(400, lambda: center_over(self, self.root, 560, 600) if self.winfo_exists() else None)
