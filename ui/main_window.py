import customtkinter as ctk
import tkinter as tk
import ctypes
from ui.StreamDeckFunktion import *
from core.config_manager import save_config
from ui.audio_mixer import AudioMixerPanel
from ui.system_monitor import SystemMonitorPanel
from ui.media_player import MediaPlayerPanel
from core.window_focus import FocusKeeper
from core.audio_apps import AudioAppWatcher
from core.mic_monitor import MicMonitor
from core.monitors import choose_monitor, list_monitors, monitor_settings, place_window
from ui.settings_dialog import SettingsDialog

# DPI-Skalierungsfehler unter Windows beheben (MUSS VOR CTK-INIT SEIN ODER AM ANFANG DER INIT)
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

class ControlPanelApp(ctk.CTk):
    def __init__(self, config_data=None):
        super().__init__()
        self.config_data = config_data if config_data else {}

        # Monitor aus den Einstellungen wiederfinden (sonst Hauptbildschirm) und dessen Maße nehmen
        self.monitor = choose_monitor(list_monitors(), self.config_data.get("settings", {}).get("monitor"))
        if self.monitor:
            screen_width, screen_height = self.monitor["width"], self.monitor["height"]
            screen_x, screen_y = self.monitor["x"], self.monitor["y"]
        else:
            screen_width, screen_height = self.winfo_screenwidth(), self.winfo_screenheight()
            screen_x, screen_y = 0, 0

        # Fenster-Eigenschaften
        self.title("Control Panel")
        print(f"Monitor {self.monitor['device'] if self.monitor else '?'}: {screen_width} {screen_height} bei {screen_x},{screen_y}")
        self.geometry(f"{screen_width}x{screen_height}+{screen_x}+{screen_y}")
        self.attributes("-fullscreen", True) # Fullscreen (auf dem Monitor, auf dem das Fenster gerade liegt)
        # customtkinter versteckt das Fenster beim Start kurz und zeigt es neu an, dabei geht die Position verloren.
        # Deshalb erst, wenn es sicher sichtbar ist, direkt über Windows auf den Monitor legen.
        if self.monitor:
            self.after(800, lambda: self.place_on_monitor(self.monitor))
        self.bind("<Escape>", lambda event: self.destroy()) # Mit ESC schließen

        # Farbliches Aussehen
        self.configure(fg_color=COLORS["bg"])

        # ========================================================================================================
        # Grid
        # ========================================================================================================

        # Zeile 0 geht über die volle Höhe
        self.grid_rowconfigure(0, weight=1)

        # Spalte 0 (Links - Sidebar): Feste Breite
        self.grid_columnconfigure(0, weight=0)
        # Spalte 1 (links - Trenner): Feste Breite
        self.grid_columnconfigure(1, weight=0)
        # Spalte 2 (Mitte - Audio Mixer): Flexibel (nimmt den meisten Platz)
        self.grid_columnconfigure(2, weight=1)
        # Spalte 1 (rechts - Trenner): Feste Breite
        self.grid_columnconfigure(3, weight=0)
        # Spalte 3 (Rechts - Media & System): Feste Breite (z. B. 300px)
        self.grid_columnconfigure(4, weight=0)

        # ========================================================================================================
        # Bereiche
        # ========================================================================================================

        # Sidebar (Buttons)
        self.sidebar_l_1 = ctk.CTkFrame(
            self,
            fg_color=COLORS["sidebar"],
            width=217,
            corner_radius=0,
        )
        self.sidebar_l_1.grid(row=0, column=0, sticky="nsew")
        self.sidebar_l_1.grid_propagate(0)

        # Grid Loutout für die Sidebare mit den Buttons
        self.sidebar_l_1.grid_rowconfigure(0, weight=0)
        self.sidebar_l_1.grid_rowconfigure(1, weight=0)
        self.sidebar_l_1.grid_rowconfigure(2, weight=1)
        self.sidebar_l_1.grid_rowconfigure(3, weight=0)
        self.sidebar_l_1.grid_rowconfigure(4, weight=0)
        self.sidebar_l_1.grid_columnconfigure(0, weight=1)

        # Frame für den Namen oben links
        self.name_frame = ctk.CTkFrame(
            self.sidebar_l_1,
            fg_color=COLORS["sidebar"],
            corner_radius=5,
            width=230,
            height=70,
        )
        self.name_frame.grid(row=0, column=0, sticky="nsew")

        # Trennlinie zwischen Name_Frame und button_Frame
        self.line_divider_titel = tk.Frame(
            self.sidebar_l_1,
            width=230,
            height=1,
            bg=COLORS["border"],
            bd=0,
            highlightthickness=0
        )
        self.line_divider_titel.grid(row=1, column=0, sticky="nsew")

        # Frame für die Buttons
        self.button_frame = ctk.CTkScrollableFrame(
            self.sidebar_l_1,
            fg_color=COLORS["sidebar"],
            corner_radius=0,
            width=230,
            height=screen_height - 122,
        )
        self.button_frame.grid(row=2, column=0, sticky="nsew")
        self.button_frame._scrollbar.grid_forget()

        # Grid für die Buttons
        self.button_frame.grid_columnconfigure(0, weight=1, uniform="tiles")
        self.button_frame.grid_columnconfigure(0, weight=1, uniform="tiles")

        self.load_button_rows()

        # Trennlinie für neue Button_Buttons
        self.divider_h_2 = tk.Frame(
            self.sidebar_l_1,
            bg=COLORS["border"],
            highlightthickness=0,
            width=230,
            height=1,
        )
        self.divider_h_2.grid(row=3, column=0, sticky="nsew")


        # Frame für die "Neue Buttons" Button
        self.new_buttons_frame = ctk.CTkFrame(
            self.sidebar_l_1,
            fg_color=COLORS["sidebar"],
            corner_radius=0,
            width=230,
            height=50,
        )
        self.new_buttons_frame.grid(row=4, column=0, sticky="nsew")

        # Trennlinien
        # Links
        self.line_divider_l = tk.Frame(
            self,
            width=1,
            bg=COLORS["border"],
            bd=0,
            highlightthickness=0
        )
        self.line_divider_l.grid(row=0, column=1, sticky="ns")

        # Rechts
        self.line_divider_r = tk.Frame(
            self,
            width=1,
            bg=COLORS["border"],
            bd=0,
            highlightthickness=0
        )
        self.line_divider_r.grid(row=0, column=3, sticky="ns")

        # Mainbare (Mitte)
        self.mixer_frame = ctk.CTkFrame(
            self,
            fg_color=COLORS["bg"],
            corner_radius=0
        )
        self.mixer_frame.grid(row=0, column=2, sticky="nsew", padx=10, pady=10)
        # Merkt sich im Hintergrund, welche Apps laufen und welche je Ton abgegeben haben
        self.audio_watcher = AudioAppWatcher()
        # Mikrofon-Überwachung (Pegel für Kanal 8 und Piepen bei Überschreiten des Schwellwerts)
        self.mic_monitor = MicMonitor(self.config_data.setdefault("settings", {}).setdefault("mic", {}),
                                      audio=self.audio_watcher)
        channel_settings = self.config_data.setdefault("settings", {}).setdefault("mixer_channels", {})
        self.audio_mixer = AudioMixerPanel(self.mixer_frame, watcher=self.audio_watcher, channel_settings=channel_settings,
                                           idle_seconds=self.config_data["settings"].get("mixer_idle_seconds", 10),
                                           mic=self.mic_monitor,
                                           on_settings_changed=lambda: save_config(self.config_data))
        self.audio_mixer.pack(fill="both", expand=True, padx=10, pady=10)

        # Sidebar Rechts
        self.sidebar_r = ctk.CTkFrame(
            self,
            fg_color=COLORS["sidebar"],
            corner_radius=0,
            width=350,
        )
        self.sidebar_r.grid(row=0, column=4, sticky="nsew")
        self.sidebar_r.grid_propagate(0)

        # Einteilung der rechten Seite
        # Mediaplayer oben, Systemmonitor unten, jeweils genau die Hälfte (uniform = gleich groß, egal wie viel der Inhalt will)
        self.sidebar_r.grid_rowconfigure(0, weight=1, uniform="sidebar_r")
        self.sidebar_r.grid_rowconfigure(1, weight=1, uniform="sidebar_r")
        self.sidebar_r.grid_columnconfigure(0, weight=1)

        # Mediapalyer
        self.media_frame = ctk.CTkFrame(
            self.sidebar_r,
            fg_color=COLORS["sidebar"],
            corner_radius=15
        )
        self.media_frame.grid(row=0, column=0, sticky="nsew")
        media_player = MediaPlayerPanel(self.media_frame, on_settings=self.open_settings)
        media_player.pack(fill="both", expand=True, padx=15, pady=10)

        # Systemmonitor
        self.system_frame = ctk.CTkFrame(
            self.sidebar_r,
            fg_color=COLORS["sidebar"],
            corner_radius=15
        )
        self.system_frame.grid(row=1, column=0, sticky="nsew")
        system_monitor = SystemMonitorPanel(self.system_frame)
        system_monitor.pack(fill="both", expand=True, padx=15, pady=10)

        # ========================================================================================================
        # Texte
        # ========================================================================================================

        # 1. Haupt-Titel ("Control Panel")
        self.title_label = ctk.CTkLabel(
            self.name_frame,
            text="🎮 Control Panel",
            font=("Helvetica", 18, "bold"),  # Schriftart, Schriftgröße & Fett
            text_color=COLORS["accent_hover"],  # Nutzt dein schönes Hellblau
            anchor="w"  # "w" = West (linksbündig ausgerichtet)
        )
        self.title_label.pack(fill="x", padx=15, pady=(12, 0))

        # 2. Untertitel ("Steam Deck Style")
        self.subtitle_label = ctk.CTkLabel(
            self.name_frame,
            text="Steam Deck Style",
            font=("Helvetica", 11),  # Etwas kleiner
            text_color=COLORS["muted_text"],  # Nutzt dein unaufdringliches Grau
            anchor="w"  # Linksbündig
        )
        self.subtitle_label.pack(fill="x", padx=15, pady=(0, 10))

        # Schließen-Knopf (ESC greift nicht, weil das Fenster nie den Tastatur-Fokus bekommt)
        self.close_button = ctk.CTkButton(
            self.name_frame,
            text="✕",
            font=("Helvetica", 14, "bold"),
            width=28,
            height=28,
            fg_color="transparent",
            hover_color=COLORS["danger"],
            text_color=COLORS["muted_text"],
            corner_radius=6,
            command=self.destroy
        )
        self.close_button.place(relx=1.0, x=-8, y=10, anchor="ne")

        # ========================================================================================================
        # Buttons
        # ========================================================================================================

        self.add_app_button = ctk.CTkButton(
            self.new_buttons_frame,
            text="+ App-Button",
            font=("Helvetica", 13, "bold"),
            fg_color=COLORS["accent"],  # Dein Sanftes Blau
            hover_color=COLORS["accent_hover"],  # Leuchtendes Hellblau beim Drüberfahren
            text_color=COLORS["text"],
            corner_radius=8,  # Leicht abgerundete Ecken
            command=self.add_empty_button_row  # Funktion, die beim Klick ausgeführt wird
        )
        self.add_app_button.pack(fill="both", expand=True, padx=10, pady=5)

        # Fokus beim vorherigen Fenster lassen und Maus nach dem Klick zurücksetzen
        settings = self.config_data.get("settings", {})
        self.focus_keeper = FocusKeeper(self, return_cursor=settings.get("return_cursor", True))

    # ========================================================================================================
    # Funktionen
    # ========================================================================================================

    # Funktion für das Einfügen neuer Buttons

    def open_settings(self):
        SettingsDialog(self, self.audio_watcher, self.config_data.setdefault("settings", {}),
                       on_mixer_change=self.on_mixer_settings_changed,
                       on_monitor_change=self.move_to_monitor,
                       current_device=self.monitor["device"] if self.monitor else None,
                       mic=self.mic_monitor, on_mic_change=lambda: save_config(self.config_data))

    def on_mixer_settings_changed(self):
        save_config(self.config_data)
        self.audio_mixer.apply_channel_settings()

    def move_to_monitor(self, monitor):
        """Panel auf einen anderen Monitor legen und das für den nächsten Start speichern."""
        self.monitor = monitor
        self.config_data.setdefault("settings", {})["monitor"] = monitor_settings(monitor)
        save_config(self.config_data)

        self.place_on_monitor(monitor)
        self.button_frame.configure(height=monitor["height"] - 122)

    def place_on_monitor(self, monitor):
        # wm_frame() liefert das äußere Windows-Fenster; immer frisch holen, Tk erzeugt es beim Vollbild manchmal neu
        hwnd = int(self.wm_frame(), 16)
        rect = place_window(hwnd, monitor)
        print(f"Monitor {monitor['device']}: Ziel {monitor['x']},{monitor['y']} {monitor['width']}x{monitor['height']}, "
              f"Fenster liegt bei {rect}")

    def add_empty_button_row(self):
        """Erstellt zwei neue Platzhalter-Buttons, speichert sie in der config.json und lädt die UI neu."""

        # 1. Höchste vorhandene ID ermitteln, um eindeutige IDs zu vergeben
        existing_buttons = self.config_data.get("buttons", [])
        next_index = len(existing_buttons)

        # 2. Schema für die beiden neuen Buttons erstellen
        new_left_button = {
            "id": f"btn_{next_index}",
            "name": "Neuer Button",
            "bg_color": COLORS["card"],
            "text_color": COLORS["text"],
            "action_type": "program",
            "action_data": {"path": "", "url": "", "hotkey": [], "sound_file": ""},
            "icon_path": ""
        }

        new_right_button = {
            "id": f"btn_{next_index + 1}",
            "name": "Neuer Button",
            "bg_color": COLORS["card"],
            "text_color": COLORS["text"],
            "action_type": "program",
            "action_data": {"path": "", "url": "", "hotkey": [], "sound_file": ""},
            "icon_path": ""
        }

        # 3. Zur Konfiguration im Speicher hinzufügen
        self.config_data.setdefault("buttons", []).extend([new_left_button, new_right_button])

        # 4. In data/config.json speichern
        save_config(self.config_data)

        # 5. UI aktualisieren
        self.load_button_rows()

    def load_button_rows(self):
        """Liest die Buttons aus self.config_data und baut die AppButtonRow-Zeilen dynamisch auf."""

        # 1. Alle vorhandenen Zeilen im Scroll-Container löschen (falls neu geladen wird)
        for widget in self.button_frame.winfo_children():
            widget.destroy()

        # 2. Buttons aus der Konfiguration holen
        buttons_list = self.config_data.get("buttons", [])

        # 3. Die Liste in 2er-Paare aufteilen (für linke und rechte Kachel pro Reihe)
        for i in range(0, len(buttons_list), 2):
            left_button = buttons_list[i]
            right_button = buttons_list[i + 1] if (i + 1) < len(buttons_list) else None

            # AppButtonRow erstellen und in die Sidebar/ScrollableFrame packen
            row = AppButtonRow(
                master=self.button_frame,
                left_app=left_button,
                right_app=right_button
            )
            row.pack(fill="x", padx=1, pady=4)

if __name__ == "__main__":
    app = ControlPanelApp()
    app.mainloop()