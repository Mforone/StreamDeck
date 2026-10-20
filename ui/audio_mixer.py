import time
import customtkinter as ctk
from config import COLORS
from core.audio_apps import MIC, clean_name
from core.mic_monitor import APP_ZONES, MIN_DB, mic_zones, to_db
from ui.level_meter import LevelMeter, format_db
from ui.colors import contrast_text, mix


METER_REFRESH_MS = 33       # Pegelanzeige ~30-mal pro Sekunde neu zeichnen
DB_LABEL_EVERY = 6          # dB-Zahl nur jedes 6. Mal (5-mal pro Sekunde), sonst flimmert sie unlesbar
MODE_APP = "app"
MODE_MIC = "mic"


def channel_colors(color):
    """Alle Farben eines aktiven Kanals aus einer Grundfarbe.

    mix(farbe, dunkel, 0.8) heißt: 20 % Kanalfarbe, 80 % dunkler Hintergrund. So ist die ganze Karte
    in der Farbe getönt, bleibt aber dunkel genug, dass weiße Schrift gut lesbar ist.
    """
    return {
        "main": color,                                   # Regler, Füllung, Stummschalter
        "hover": mix(color, "#FFFFFF", 0.3),             # 30 % heller beim Drüberfahren
        "card": mix(color, COLORS["card"], 0.82),        # Hintergrund der ganzen Karte
        "track": mix(color, COLORS["bg"], 0.65),         # leere Spur des Reglers
        "control": mix(color, COLORS["bg"], 0.82),       # Auswahlknopf, ▼/▲ (dunkler als die Karte)
        "control_hover": mix(color, COLORS["card"], 0.45),
        "border": mix(color, COLORS["card"], 0.45),
        "text": contrast_text(color),                    # Schrift auf der vollen Farbe
    }


class AudioChannelStrip(ctk.CTkFrame):
    def __init__(self, master, channel_num: int, is_master: bool = False, audio=None,
                 meter=False, mic=None, mode=MODE_APP, on_mode_change=None, **kwargs):
        super().__init__(
            master,
            fg_color=COLORS["card"],
            corner_radius=12,
            border_width=0,  # Rahmenloser Clean-Look für die Karten
            **kwargs
        )

        # audio: der Audio-Dienst (core/audio_apps.py). Alle Windows-Audio-Aufrufe laufen dort im Hintergrund,
        # dieser Kanal liest nur fertige Werte und legt Befehle ab: so kann die Oberfläche nie hängen bleiben
        self.audio = audio
        # Kanal mit Pegelanzeige (Kanal 8): umschaltbar zwischen App und Mikrofon
        self.has_meter = meter
        self.mic = mic
        self.mode = mode if meter else MODE_APP
        self.on_mode_change = on_mode_change
        self._meter_target = None
        self._meter_frame = 0
        self.channel_num = channel_num
        self.is_master = is_master
        self.selected_process = "master" if is_master else ""
        self.color = COLORS["accent"]
        self.selected_at = 0.0  # wann die App gewählt wurde (für die Stille-Regel im Mixer)
        self.is_muted = False
        self.is_dragging = False
        self._active_popup = None

        level = self.audio.level(self.selected_process) if self.audio and self.selected_process else None
        initial_vol = level[0] if level else 0.5
        self.initial_percent_str = f"{int(initial_vol * 100)}%"

        self.setup_ui(initial_vol)
        self.update_channel_appearance()
        if self.has_meter:
            self.set_mode(self.mode, notify=False)
            self.after(METER_REFRESH_MS, self._update_meter)

    def setup_ui(self, initial_vol: float):
        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=4, pady=8)

        # 1. Header
        if self.is_master:
            self.lbl_channel = ctk.CTkLabel(
                container,
                text="🔊 Master",
                font=("Helvetica", 11, "bold"),
                text_color=COLORS["text"]
            )
            self.lbl_channel.pack(pady=(2, 6))
        else:
            self.lbl_channel = ctk.CTkLabel(
                container,
                text=f"Kanal {self.channel_num}",
                font=("Helvetica", 10),
                text_color=COLORS["muted_text"]
            )
            self.lbl_channel.pack(pady=(0, 2))

            if self.has_meter:
                # Umschalter: Pegel einer App oder des eigenen Mikrofons
                self.mode_switch = ctk.CTkSegmentedButton(
                    container,
                    values=["App", "🎙 Mic"],
                    font=("Helvetica", 10, "bold"),
                    height=22,
                    selected_color=COLORS["accent"],
                    selected_hover_color=COLORS["accent_hover"],
                    unselected_color=COLORS["bg"],
                    unselected_hover_color=COLORS["card_hover"],
                    fg_color=COLORS["bg"],
                    command=lambda value: self.set_mode(MODE_MIC if "Mic" in value else MODE_APP)
                )
                self.mode_switch.pack(fill="x", pady=(0, 4))

            self.btn_select = ctk.CTkButton(
                container,
                text="-- Auswählen -- ▾",
                font=("Helvetica", 9),
                fg_color="transparent",
                hover_color=COLORS["card_hover"],
                border_width=1,
                border_color="#2A2D4A",
                text_color=COLORS["muted_text"],
                height=22,
                corner_radius=6,
                command=self.open_session_dropdown
            )
            self.btn_select.pack(fill="x", pady=(0, 6))

        # 2. Vertikaler Fader mit farbigem Fortschrittsbalken
        fader_frame = ctk.CTkFrame(container, fg_color="transparent")
        fader_frame.pack(fill="both", expand=True, pady=2)
        if self.has_meter:
            # Regler und Pegelanzeige nebeneinander, zusammen mittig
            fader_frame = ctk.CTkFrame(fader_frame, fg_color="transparent")
            fader_frame.pack(fill="y", expand=True)

        self.slider = ctk.CTkSlider(
            fader_frame,
            from_=0.0,
            to=1.0,
            orientation="vertical",
            number_of_steps=100,
            button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_hover"],
            progress_color=COLORS["accent"],
            command=self.on_volume_change
        )
        self.slider.set(initial_vol)
        # Standardfarbe der Slider-Spur merken, inaktive Kanäle bekommen sie zurück
        self._default_track = self.slider.cget("fg_color")
        if self.has_meter:
            self.slider.pack(side="left", fill="y", expand=True)
            self.meter = LevelMeter(fader_frame, orientation="vertical", bg=COLORS["card"])
            self.meter.configure(width=12)
            self.meter.pack(side="left", fill="y", padx=(6, 0), pady=8)
        else:
            self.slider.pack(fill="y", expand=True)

        self.slider.bind("<ButtonPress-1>", lambda e: setattr(self, "is_dragging", True))
        self.slider.bind("<ButtonRelease-1>", self.on_drag_release)

        # 3. Prozentanzeige (Fett)
        self.lbl_percent = ctk.CTkLabel(
            container,
            text=self.initial_percent_str,
            font=("Helvetica", 12, "bold"),
            text_color=COLORS["text"]
        )
        self.lbl_percent.pack(pady=(6, 0 if self.has_meter else 4))
        if self.has_meter:
            self.lbl_db = ctk.CTkLabel(container, text="-∞ dB", font=("Helvetica", 10, "bold"),
                                       text_color=COLORS["muted_text"], height=16)
            self.lbl_db.pack(pady=(0, 4))

        # 4. Kompakte Feineinstellungs-Buttons (▼ / ▲)
        step_box = ctk.CTkFrame(container, fg_color="transparent")
        step_box.pack(fill="x", pady=(0, 4))
        step_box.grid_columnconfigure((0, 1), weight=1, uniform="step_btns")

        self.btn_down = ctk.CTkButton(
            step_box,
            text="▼",
            font=("Helvetica", 8, "bold"),
            fg_color=COLORS["bg"],
            hover_color=COLORS["card_hover"],
            text_color=COLORS["muted_text"],
            height=20,
            corner_radius=5,
            command=lambda: self.adjust_volume(-0.02)
        )
        self.btn_down.grid(row=0, column=0, padx=(0, 1), sticky="ew")

        self.btn_up = ctk.CTkButton(
            step_box,
            text="▲",
            font=("Helvetica", 8, "bold"),
            fg_color=COLORS["bg"],
            hover_color=COLORS["card_hover"],
            text_color=COLORS["muted_text"],
            height=20,
            corner_radius=5,
            command=lambda: self.adjust_volume(0.02)
        )
        self.btn_up.grid(row=0, column=1, padx=(1, 0), sticky="ew")

        # 5. Kompakter Mute-Button ganz unten
        self.btn_mute = ctk.CTkButton(
            container,
            text="🔊",
            font=("Helvetica", 11),
            fg_color=COLORS["bg"],
            hover_color=COLORS["card_hover"],
            text_color=COLORS["muted_text"],
            height=24,
            corner_radius=6,
            command=self.toggle_mute
        )
        self.btn_mute.pack(fill="x")

    def on_drag_release(self, event):
        self.is_dragging = False
        if self.selected_process and self.audio:
            self.audio.set_volume(self.selected_process, self.slider.get())

    def update_channel_appearance(self):
        if self.is_master:
            self.configure(fg_color=COLORS["card"])
            self.lbl_percent.configure(text_color=COLORS["text"])
            self.btn_down.configure(text_color=COLORS["text"])
            self.btn_up.configure(text_color=COLORS["text"])
            self.slider.configure(button_color=COLORS["accent"], progress_color=COLORS["accent"])
            if self.is_muted:
                self.btn_mute.configure(text="🔇", fg_color="#BF616A", hover_color="#D08770", text_color="#FFFFFF")
            else:
                self.btn_mute.configure(text="🔊", fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"], text_color=COLORS["text"])
            return

        is_active = bool(self.selected_process and self.selected_process != "-- Auswählen --")

        if is_active:
            # AKTIVER KANAL: alles in der Kanalfarbe getönt
            colors = channel_colors(self.color)
            self.configure(fg_color=colors["card"])
            self.lbl_channel.configure(text_color=COLORS["text"])
            self.btn_select.configure(
                text_color=COLORS["text"],
                fg_color=colors["control"],
                hover_color=colors["control_hover"],
                border_width=1,
                border_color=colors["border"]
            )
            self.lbl_percent.configure(text_color=COLORS["text"])
            for button in (self.btn_down, self.btn_up):
                button.configure(text_color=COLORS["text"], fg_color=colors["control"], hover_color=colors["control_hover"])
            self.slider.configure(
                button_color=colors["main"],
                button_hover_color=colors["hover"],
                progress_color=colors["main"],
                fg_color=colors["track"]
            )
            if self.is_muted:
                self.btn_mute.configure(text="🔇", fg_color="#BF616A", hover_color="#D08770", text_color="#FFFFFF")
            else:
                self.btn_mute.configure(text="🔊", fg_color=colors["main"], hover_color=colors["hover"], text_color=colors["text"])
        else:
            # INAKTIVER KANAL (Sichtbar abgedunkelt mit dünnem Rahmen am Button)
            inactive_bg = "#16182B"
            self.configure(fg_color=inactive_bg)
            self.lbl_channel.configure(text_color=COLORS["muted_text"])
            self.btn_select.configure(
                text_color=COLORS["muted_text"],
                fg_color="transparent",
                hover_color=COLORS["card_hover"],
                border_width=1,
                border_color="#2A2D4A"
            )
            self.lbl_percent.configure(text_color=COLORS["muted_text"])
            for button in (self.btn_down, self.btn_up):
                button.configure(text_color=COLORS["muted_text"], fg_color=COLORS["bg"], hover_color=COLORS["card_hover"])
            self.slider.configure(
                button_color="#2A2D4A",
                button_hover_color=COLORS["accent_hover"],
                progress_color="#232640",
                fg_color=self._default_track
            )
            self.btn_mute.configure(text="🔊", fg_color="transparent", hover_color=COLORS["card_hover"], text_color=COLORS["muted_text"])

    def open_session_dropdown(self):
        """Öffnet das Dropdown stabil ohne ungewolltes Schließen bei Touch/Klick."""
        if hasattr(self, "_active_popup") and self._active_popup and self._active_popup.winfo_exists():
            self._active_popup.destroy()
            self._active_popup = None
            return

        sessions = self.audio.sessions() if self.audio else []

        popup = ctk.CTkToplevel(self)
        self._active_popup = popup
        popup.overrideredirect(True)
        popup.configure(fg_color=COLORS["card"])
        popup.attributes("-topmost", True)

        x = self.btn_select.winfo_rootx()
        y = self.btn_select.winfo_rooty() + self.btn_select.winfo_height() + 4
        w = max(self.btn_select.winfo_width(), 130)

        item_count = len(sessions) + 1
        h = min(item_count * 30 + 8, 180)
        popup.geometry(f"{w}x{h}+{x}+{y}")

        menu_frame = ctk.CTkScrollableFrame(
            popup,
            fg_color=COLORS["card"],
            border_width=1,
            border_color=COLORS["border"],
            corner_radius=8
        )
        menu_frame.pack(fill="both", expand=True)
        menu_frame._scrollbar.grid_forget()

        def select_proc(proc_name, display_text):
            self.select_app(proc_name, display_text)
            if popup.winfo_exists():
                popup.destroy()
            self._active_popup = None

        btn_none = ctk.CTkButton(
            menu_frame,
            text="-- Auswählen --",
            anchor="w",
            fg_color="transparent",
            hover_color=COLORS["card_hover"],
            text_color=COLORS["muted_text"],
            height=26,
            command=lambda: select_proc("", "-- Auswählen --")
        )
        btn_none.pack(fill="x", padx=2, pady=1)

        for s in sessions:
            p_name = s.get("process_name", "")
            d_name = s.get("name", "")
            btn_item = ctk.CTkButton(
                menu_frame,
                text=d_name,
                anchor="w",
                fg_color="transparent",
                hover_color=COLORS["card_hover"],
                text_color=COLORS["text"],
                height=26,
                command=lambda p=p_name, d=d_name: select_proc(p, d)
            )
            btn_item.pack(fill="x", padx=2, pady=1)

        def on_global_click(event):
            if popup.winfo_exists():
                px, py = popup.winfo_rootx(), popup.winfo_rooty()
                pw, ph = popup.winfo_width(), popup.winfo_height()
                if not (px <= event.x_root <= px + pw and py <= event.y_root <= py + ph):
                    popup.after(50, lambda: popup.destroy() if popup.winfo_exists() else None)
                    self.winfo_toplevel().unbind("<Button-1>", click_binding)
                    self._active_popup = None

        click_binding = self.winfo_toplevel().bind("<Button-1>", on_global_click, add="+")

    def select_app(self, proc_name, display_text=None):
        """Kanal auf eine App stellen ("" = leer, zeigt wieder "-- Auswählen --")."""
        if display_text is None:
            display_text = clean_name(proc_name) if proc_name else "-- Auswählen --"
        self.selected_process = proc_name
        self.selected_at = time.monotonic()
        if not proc_name:
            self.is_muted = False
        if not proc_name:
            short_text = "-- Auswählen --"  # nie kürzen
        else:
            short_text = (display_text[:11] + "..") if len(display_text) > 13 else display_text
        self.btn_select.configure(text=f"{short_text} ▾")
        self.update_channel_appearance()
        self.sync_from_system()

    def set_mode(self, mode, notify=True):
        """Kanal 8: zwischen App und Mikrofon umschalten."""
        self.mode = mode
        self.mode_switch.set("🎙 Mic" if mode == MODE_MIC else "App")
        if mode == MODE_MIC:
            # Regler und Stumm-Knopf steuern jetzt das Windows-Mikrofon
            self.select_app(MIC, "🎙 Mikrofon")
            self.btn_select.configure(state="disabled")
        else:
            self.btn_select.configure(state="normal")
            if self.selected_process == MIC:
                self.select_app("")
        if notify and self.on_mode_change:
            self.on_mode_change(mode)

    def _update_meter(self):
        if self.mode == MODE_MIC:
            level = self.mic.level_db() if self.mic else MIN_DB
            red_from, yellow_from = mic_zones(self.mic.settings["threshold_db"]) if self.mic else APP_ZONES
            target = ""
        else:
            target = self.selected_process
            level = to_db(self.audio.meter_peak()) if self.audio and target else MIN_DB
            red_from, yellow_from = APP_ZONES
        # Dem Audio-Dienst sagen, welche App er schnell messen soll (nur bei Änderung)
        if self.audio and target != self._meter_target:
            self.audio.set_meter_target(target)
            self._meter_target = target

        self.meter.set_level(level, red_from, yellow_from)
        self._meter_frame += 1
        if self._meter_frame % DB_LABEL_EVERY == 0:
            self.lbl_db.configure(text=format_db(self.meter.shown_db))
        self.after(METER_REFRESH_MS, self._update_meter)

    def set_color(self, color):
        self.color = color or COLORS["accent"]
        self.update_channel_appearance()

    def on_volume_change(self, value):
        percent = int(value * 100)
        self.lbl_percent.configure(text=f"{percent}%")
        if self.selected_process and self.audio:
            self.audio.set_volume(self.selected_process, value)

    def adjust_volume(self, delta):
        new_val = max(0.0, min(1.0, self.slider.get() + delta))
        self.slider.set(new_val)
        self.on_volume_change(new_val)

    def toggle_mute(self):
        self.is_muted = not self.is_muted
        if self.selected_process and self.audio:
            self.audio.set_mute(self.selected_process, self.is_muted)
        self.update_channel_appearance()

    def sync_from_system(self):
        if not self.selected_process or self.is_dragging or not self.audio:
            return

        level = self.audio.level(self.selected_process)
        if level is None:
            return  # noch keine Werte vom Audio-Dienst
        sys_vol, sys_mute = level

        if abs(self.slider.get() - sys_vol) > 0.01:
            self.slider.set(sys_vol)
            self.lbl_percent.configure(text=f"{int(sys_vol * 100)}%")

        if sys_mute != self.is_muted:
            self.is_muted = sys_mute
            self.update_channel_appearance()


class AudioMixerPanel(ctk.CTkFrame):
    def __init__(self, master, watcher=None, channel_settings=None, idle_seconds=10, mic=None,
                 on_settings_changed=None, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.channels = []
        # watcher: AudioAppWatcher (welche Apps Ton abgeben), channel_settings: {"2": {"app": "Discord.exe", "color": "#5865F2"}, ...}
        self.watcher = watcher
        self.channel_settings = channel_settings if channel_settings is not None else {}
        # So viele Sekunden ohne Ton, dann gibt eine App ihren Kanal frei (kurze Pausen sollen nicht flackern)
        self.idle_seconds = idle_seconds
        self.mic = mic  # Mikrofon-Überwachung für die Pegelanzeige von Kanal 8
        self.on_settings_changed = on_settings_changed  # z. B. Umschalten von Kanal 8 speichern
        self._previous_running = None
        self.setup_ui()
        self.apply_channel_settings()
        self.start_sync_loop()

    def setup_ui(self):
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.pack(fill="x", pady=(0, 8))

        lbl_title = ctk.CTkLabel(
            header_frame,
            text="🎛️ Audio Mixer",
            font=("Helvetica", 14, "bold"),
            text_color=COLORS["text"]
        )
        lbl_title.pack(side="left")

        channels_frame = ctk.CTkFrame(self, fg_color="transparent")
        channels_frame.pack(fill="both", expand=True)

        for col in range(8):
            channels_frame.grid_columnconfigure(col, weight=1, uniform="mixer_cols")
        channels_frame.grid_rowconfigure(0, weight=1)

        for i in range(8):
            is_master = (i == 0)
            number = i + 1
            meter_channel = number == 8
            strip = AudioChannelStrip(
                channels_frame,
                channel_num=number,
                is_master=is_master,
                audio=self.watcher,
                meter=meter_channel,
                mic=self.mic if meter_channel else None,
                mode=self.channel_settings.get("8", {}).get("mode", MODE_APP),
                on_mode_change=(lambda mode: self._save_mode(8, mode)) if meter_channel else None
            )
            strip.grid(row=0, column=i, padx=2, pady=0, sticky="nsew")
            self.channels.append(strip)

    def _save_mode(self, number, mode):
        self.channel_settings.setdefault(str(number), {})["mode"] = mode
        if self.on_settings_changed:
            self.on_settings_changed()

    def apply_channel_settings(self):
        """Farben aus den Einstellungen übernehmen und feste Apps sofort neu zuordnen."""
        for channel in self.channels[1:]:
            channel.set_color(self.channel_settings.get(str(channel.channel_num), {}).get("color"))
        self._previous_running = None  # beim nächsten Durchlauf alle laufenden Apps als "neu gestartet" behandeln

    def auto_assign(self, sounding, now=None):
        """Feste Apps belegen ihren Kanal, sobald sie Ton abgeben; stille Apps geben ihren Kanal frei.

        sounding: Prozessnamen (klein geschrieben) aller Apps, die in den letzten idle_seconds Ton abgegeben haben.
        """
        now = time.monotonic() if now is None else now
        started = sounding if self._previous_running is None else sounding - self._previous_running
        self._previous_running = set(sounding)

        for channel in self.channels[1:]:
            if channel.mode == MODE_MIC:
                continue  # Kanal zeigt das Mikrofon, keine App-Automatik
            selected = channel.selected_process.lower()
            # Frisch gewählte Apps bekommen dieselbe Frist, sonst würde eine gerade pausierte App sofort wieder fliegen
            if selected and selected not in sounding and now - channel.selected_at > self.idle_seconds:
                channel.select_app("")

            fixed = self.channel_settings.get(str(channel.channel_num), {}).get("app", "")
            if fixed and fixed.lower() in started and channel.selected_process.lower() != fixed.lower():
                channel.select_app(fixed)

    def start_sync_loop(self):
        if self.watcher is not None and self.watcher.is_ready():
            self.auto_assign(self.watcher.sounding(self.idle_seconds))
        for channel in self.channels:
            channel.sync_from_system()
        self.after(200, self.start_sync_loop)