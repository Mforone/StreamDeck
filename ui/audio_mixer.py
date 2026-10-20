import customtkinter as ctk
from config import COLORS
from core.audio_manager import AudioManager
from core.audio_apps import clean_name
from ui.colors import contrast_text, mix


def channel_colors(color):
    """Alle Farben eines aktiven Kanals aus einer Grundfarbe (wie beim Standard-Blau: Fläche, heller beim Drüberfahren, dunkle Spur)."""
    return {
        "main": color,
        "hover": mix(color, "#FFFFFF", 0.3),
        "track": mix(color, COLORS["card"], 0.75),   # 25 % Farbe, 75 % Kartenhintergrund
        "text": contrast_text(color),
    }


class AudioChannelStrip(ctk.CTkFrame):
    def __init__(self, master, channel_num: int, is_master: bool = False, **kwargs):
        super().__init__(
            master,
            fg_color=COLORS["card"],
            corner_radius=12,
            border_width=0,  # Rahmenloser Clean-Look für die Karten
            **kwargs
        )

        self.channel_num = channel_num
        self.is_master = is_master
        self.selected_process = "master" if is_master else ""
        self.color = COLORS["accent"]
        self.is_muted = False
        self.is_dragging = False
        self._active_popup = None

        initial_vol = AudioManager.get_volume(self.selected_process) if self.selected_process else 0.5
        self.initial_percent_str = f"{int(initial_vol * 100)}%"

        self.setup_ui(initial_vol)
        self.update_channel_appearance()

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
        self.lbl_percent.pack(pady=(6, 4))

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
        if self.selected_process:
            AudioManager.set_volume(self.selected_process, self.slider.get())

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
            # AKTIVER KANAL
            self.configure(fg_color=COLORS["card"])
            self.btn_select.configure(
                text_color=COLORS["text"],
                fg_color=COLORS["bg"],
                border_width=1,
                border_color=COLORS["border"]
            )
            self.lbl_percent.configure(text_color=COLORS["text"])
            self.btn_down.configure(text_color=COLORS["text"])
            self.btn_up.configure(text_color=COLORS["text"])
            colors = channel_colors(self.color)
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
            self.btn_select.configure(
                text_color=COLORS["muted_text"],
                fg_color="transparent",
                border_width=1,
                border_color="#2A2D4A"
            )
            self.lbl_percent.configure(text_color=COLORS["muted_text"])
            self.btn_down.configure(text_color=COLORS["muted_text"])
            self.btn_up.configure(text_color=COLORS["muted_text"])
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

        sessions = AudioManager.get_active_sessions()

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
        if not proc_name:
            self.is_muted = False
        if not proc_name:
            short_text = "-- Auswählen --"  # nie kürzen
        else:
            short_text = (display_text[:11] + "..") if len(display_text) > 13 else display_text
        self.btn_select.configure(text=f"{short_text} ▾")
        self.update_channel_appearance()
        self.sync_from_system()

    def set_color(self, color):
        self.color = color or COLORS["accent"]
        self.update_channel_appearance()

    def on_volume_change(self, value):
        percent = int(value * 100)
        self.lbl_percent.configure(text=f"{percent}%")
        if self.selected_process:
            AudioManager.set_volume(self.selected_process, value)

    def adjust_volume(self, delta):
        new_val = max(0.0, min(1.0, self.slider.get() + delta))
        self.slider.set(new_val)
        self.on_volume_change(new_val)

    def toggle_mute(self):
        self.is_muted = not self.is_muted
        if self.selected_process:
            AudioManager.set_mute(self.selected_process, self.is_muted)
        self.update_channel_appearance()

    def sync_from_system(self):
        if not self.selected_process or self.is_dragging:
            return

        sys_vol = AudioManager.get_volume(self.selected_process)
        sys_mute = AudioManager.get_mute(self.selected_process)

        if abs(self.slider.get() - sys_vol) > 0.01:
            self.slider.set(sys_vol)
            self.lbl_percent.configure(text=f"{int(sys_vol * 100)}%")

        if sys_mute != self.is_muted:
            self.is_muted = sys_mute
            self.update_channel_appearance()


class AudioMixerPanel(ctk.CTkFrame):
    def __init__(self, master, watcher=None, channel_settings=None, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.channels = []
        # watcher: AudioAppWatcher (welche Apps laufen), channel_settings: {"2": {"app": "Discord.exe", "color": "#5865F2"}, ...}
        self.watcher = watcher
        self.channel_settings = channel_settings if channel_settings is not None else {}
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
            strip = AudioChannelStrip(
                channels_frame,
                channel_num=i + 1,
                is_master=is_master
            )
            strip.grid(row=0, column=i, padx=2, pady=0, sticky="nsew")
            self.channels.append(strip)

    def apply_channel_settings(self):
        """Farben aus den Einstellungen übernehmen und feste Apps sofort neu zuordnen."""
        for channel in self.channels[1:]:
            channel.set_color(self.channel_settings.get(str(channel.channel_num), {}).get("color"))
        self._previous_running = None  # beim nächsten Durchlauf alle laufenden Apps als "neu gestartet" behandeln

    def auto_assign(self, running):
        """Feste Apps belegen ihren Kanal, sobald sie starten; beendete Apps geben ihren Kanal frei.

        running: Prozessnamen (klein geschrieben) aller Apps mit Audiositzung.
        """
        started = running if self._previous_running is None else running - self._previous_running
        self._previous_running = set(running)

        for channel in self.channels[1:]:
            selected = channel.selected_process.lower()
            if selected and selected not in running:
                channel.select_app("")

            fixed = self.channel_settings.get(str(channel.channel_num), {}).get("app", "")
            if fixed and fixed.lower() in started and channel.selected_process.lower() != fixed.lower():
                channel.select_app(fixed)

    def start_sync_loop(self):
        if self.watcher is not None and self.watcher.is_ready():
            self.auto_assign(self.watcher.running())
        for channel in self.channels:
            channel.sync_from_system()
        self.after(200, self.start_sync_loop)