import time
import tkinter.font as tkfont
import customtkinter as ctk
from config import COLORS
from core.media_session import MediaSession, REPEAT_CYCLE, current_position, format_time
from core.spotify import SpotifyClient, apply_spotify
from ui.spotify_ui import QueuePanel

REFRESH_MS = 250
COVER_PX = 80

# Schriftgrößen (Punkte, customtkinter skaliert sie mit der Windows-Skalierung)
TITLE_SIZE = 15
ARTIST_SIZE = 13
APP_SIZE = 11
TIME_SIZE = 13

# Weniger als so viele Sekunden vor dem Ende springt "Weiter" nicht mehr ans Ende
END_JUMP_MARGIN_S = 1.0

# Symbole aus der Windows-Symbolschrift (Win11: Segoe Fluent Icons, Win10: Segoe MDL2 Assets)
ICON_FONTS = ("Segoe Fluent Icons", "Segoe MDL2 Assets")
ICONS = {
    "play": "",
    "pause": "",
    "previous": "",
    "next": "",
    "shuffle": "",
    "repeat_list": "",
    "repeat_track": "",
}
# Ersatz, falls keine der Schriften installiert ist
FALLBACK_ICONS = {
    "play": "▶",
    "pause": "❚❚",
    "previous": "◀◀",
    "next": "▶▶",
    "shuffle": "⤮",
    "repeat_list": "↻",
    "repeat_track": "↻1",
}


def fit_text(text, font, max_width):
    """Kürzt Text mit „…“, bis er in max_width Pixel passt."""
    measure = tkfont.Font(font=font).measure
    if max_width <= 0 or measure(text) <= max_width:
        return text
    while text and measure(text + "…") > max_width:
        text = text[:-1]
    return text.rstrip() + "…"


class MediaPlayerPanel(ctk.CTkFrame):
    def __init__(self, master, session=None, spotify=None, on_settings=None, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)

        # session=False / spotify=False nur zum Testen ohne echte Windows- bzw. Spotify-Anbindung
        self.session = session if session is not None else MediaSession()
        self.spotify = spotify if spotify is not None else SpotifyClient()
        self.state = None
        self.dragging = False
        self._shown = {}  # zuletzt angezeigte Werte, damit nur Änderungen neu gezeichnet werden
        self._cover_image = None

        families = set(tkfont.families(self))
        self.icon_font_family = next((f for f in ICON_FONTS if f in families), None)
        self.icons = ICONS if self.icon_font_family else FALLBACK_ICONS

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(header, text="🎵 Mediaplayer", font=("Helvetica", 14, "bold"),
                     text_color=COLORS["text"], anchor="w").pack(side="left")
        if on_settings is not None:
            # Zahnrad: Einstellungen (Mixer-Kanäle, Monitor)
            ctk.CTkButton(header, text="⚙", width=32, height=32, corner_radius=16, font=("Helvetica", 17),
                          fg_color="transparent", hover_color=COLORS["card_hover"], text_color=COLORS["muted_text"],
                          command=on_settings).pack(side="right")

        # Karte "läuft gerade": nimmt nur so viel Höhe, wie sie braucht, darunter die Spotify-Warteschlange
        self.card = ctk.CTkFrame(self, fg_color=COLORS["card"], corner_radius=12)
        self.card.pack(fill="x", pady=4)
        inner = ctk.CTkFrame(self.card, fg_color="transparent")
        inner.pack(fill="x", padx=10, pady=10)

        self._build_now_playing(inner)
        self._build_progress(inner)
        self._build_controls(inner)

        self.queue_panel = None
        if self.spotify:
            self.queue_panel = QueuePanel(self, self.spotify, fit_text)
            self.queue_panel.pack(fill="x", pady=4)

        if self.session:
            self.after(REFRESH_MS, self.refresh)

    # ------------------------------------------------------------------------------------------------
    # Aufbau
    # ------------------------------------------------------------------------------------------------

    def _build_now_playing(self, parent):
        top = ctk.CTkFrame(parent, fg_color="transparent")
        top.pack(fill="x")
        top.grid_columnconfigure(1, weight=1)

        # Cover und Platzhalter liegen in derselben Zelle, sichtbar ist immer nur eins
        self.cover_label = ctk.CTkLabel(top, text="", width=COVER_PX, height=COVER_PX)
        self.cover_placeholder = ctk.CTkLabel(top, text="♪", width=COVER_PX, height=COVER_PX,
                                              fg_color=COLORS["card_hover"], corner_radius=10,
                                              font=("Helvetica", 28), text_color=COLORS["muted_text"])
        self.cover_placeholder.grid(row=0, column=0, sticky="nw")

        self.text_box = ctk.CTkFrame(top, fg_color="transparent")
        self.text_box.grid(row=0, column=1, sticky="nsew", padx=(10, 0))

        self.title_font = ("Helvetica", TITLE_SIZE, "bold")
        self.artist_font = ("Helvetica", ARTIST_SIZE, "bold")
        self.lbl_title = ctk.CTkLabel(self.text_box, text="", font=self.title_font,
                                      text_color=COLORS["text"], anchor="w")
        self.lbl_title.pack(fill="x", pady=(4, 0))
        self.lbl_artist = ctk.CTkLabel(self.text_box, text="", font=self.artist_font,
                                       text_color=COLORS["muted_text"], anchor="w")
        self.lbl_artist.pack(fill="x")
        self.lbl_app = ctk.CTkLabel(self.text_box, text="", font=("Helvetica", APP_SIZE, "bold"),
                                    text_color=COLORS["muted_text"], anchor="w")
        self.lbl_app.pack(fill="x")

        # Text neu kürzen, wenn sich die Breite ändert
        self.text_box.bind("<Configure>", lambda e: self._update_texts(force=True))

    def _build_progress(self, parent):
        self.slider = ctk.CTkSlider(
            parent,
            from_=0.0,
            to=1.0,
            height=16,
            button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_hover"],
            progress_color=COLORS["accent"],
            fg_color=COLORS["border"],
            command=self._on_slider_move
        )
        self.slider.set(0)
        self.slider.pack(fill="x", pady=(10, 0))
        self.slider.bind("<ButtonPress-1>", self._on_slider_press)
        self.slider.bind("<ButtonRelease-1>", self._on_slider_release)

        times = ctk.CTkFrame(parent, fg_color="transparent")
        times.pack(fill="x")
        # Feste Breite, damit die Zeile beim Hochzählen nicht wackelt
        self.lbl_position = ctk.CTkLabel(times, text="0:00", width=64, anchor="w",
                                         font=("Helvetica", TIME_SIZE, "bold"), text_color=COLORS["text"])
        self.lbl_position.pack(side="left")
        self.lbl_duration = ctk.CTkLabel(times, text="0:00", width=64, anchor="e",
                                         font=("Helvetica", TIME_SIZE, "bold"), text_color=COLORS["text"])
        self.lbl_duration.pack(side="right")

    def _build_controls(self, parent):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(2, 0))
        for column in range(5):
            row.grid_columnconfigure(column, weight=1, uniform="controls")

        def icon_button(column, icon, command, size=16, big=False):
            button = ctk.CTkButton(
                row,
                text=self.icons[icon],
                font=(self.icon_font_family or "Helvetica", size),
                width=44 if big else 36,
                height=44 if big else 36,
                corner_radius=22 if big else 18,
                fg_color=COLORS["accent"] if big else "transparent",
                hover_color=COLORS["accent_hover"] if big else COLORS["card_hover"],
                text_color=COLORS["text"],
                text_color_disabled=COLORS["border"],
                command=command
            )
            button.grid(row=0, column=column)
            return button

        self.btn_shuffle = icon_button(0, "shuffle", self._on_shuffle)
        self.btn_previous = icon_button(1, "previous", self._on_previous)
        self.btn_play = icon_button(2, "play", self._on_play_pause, size=18, big=True)
        self.btn_next = icon_button(3, "next", self._on_next)
        self.btn_repeat = icon_button(4, "repeat_list", self._on_repeat)

    # ------------------------------------------------------------------------------------------------
    # Bedienung
    # ------------------------------------------------------------------------------------------------

    def _send(self, name, value=None):
        if self.session:
            self.session.command(name, value)

    def _seek(self, seconds):
        """Spulen über Spotify, wenn Windows bei Spotify nicht spulen kann, sonst über Windows."""
        if self.state.get("seek_via_spotify"):
            self.spotify.patch(progress=seconds)
            self.spotify.command("seek", seconds)
        else:
            self.session.patch_state(base_position=seconds, base_time=time.monotonic())
            self._send("seek", seconds)

    def _on_play_pause(self):
        state = self.state
        if not state:
            return
        # Symbol sofort umschalten, damit sich das Tippen direkt anfühlt
        self.session.patch_state(playing=not state["playing"],
                                 base_position=current_position(state), base_time=time.monotonic())
        if state.get("seek_via_spotify"):
            # Zeitleiste kommt gerade von Spotify: dort ebenfalls sofort umschalten
            self.spotify.patch(is_playing=not state["playing"], progress=current_position(state))
        self._send("play_pause")
        self.refresh(reschedule=False)

    def _seek_to(self, seconds):
        self._seek(seconds)
        self.refresh(reschedule=False)

    def _on_previous(self):
        state = self.state
        if not state:
            return
        if state["can_previous"]:
            self._send("previous")
        elif state["can_seek"]:
            # App bietet kein "Zurück" an (z. B. einzelnes YouTube-Video): an den Anfang
            self._seek_to(0)

    def _on_next(self):
        state = self.state
        if not state:
            return
        if state["can_next"]:
            self._send("next")
        elif state["can_seek"] and state["duration"] > END_JUMP_MARGIN_S:
            # App bietet kein "Weiter" an: ans Ende springen, bei YouTube startet dann Autoplay das nächste Video
            self._seek_to(state["duration"] - END_JUMP_MARGIN_S)

    def _on_shuffle(self):
        state = self.state
        if not state:
            return
        if state.get("via_spotify"):
            # Smart Shuffle lässt sich über die Web API nicht einschalten: an -> aus, aus -> normaler Shuffle
            new_value = not (state["shuffle"] or state["smart_shuffle"])
            self.spotify.patch(shuffle=new_value, smart_shuffle=False)
            self.spotify.command("shuffle", new_value)
        else:
            new_value = not bool(state["shuffle"])
            self.session.patch_state(shuffle=new_value)
            self._send("shuffle", new_value)
        self.refresh(reschedule=False)

    def _on_repeat(self):
        state = self.state
        if not state:
            return
        new_mode = REPEAT_CYCLE[state["repeat"] or "off"]
        if state.get("via_spotify"):
            self.spotify.patch(repeat=new_mode)
            self.spotify.command("repeat", new_mode)
        else:
            self.session.patch_state(repeat=new_mode)
            self._send("repeat", new_mode)
        self.refresh(reschedule=False)

    def _on_slider_press(self, event):
        self.dragging = True

    def _on_slider_move(self, value):
        # Beim Ziehen nur die Zeit anzeigen, gespult wird erst beim Loslassen
        if self.state and self.state["duration"] > 0:
            self.lbl_position.configure(text=format_time(value * self.state["duration"]))

    def _on_slider_release(self, event):
        self.dragging = False
        state = self.state
        if not state or not state["can_seek"]:
            return
        self._seek(self.slider.get() * state["duration"])

    # ------------------------------------------------------------------------------------------------
    # Anzeige
    # ------------------------------------------------------------------------------------------------

    def refresh(self, reschedule=True):
        state = self.session.get_state()
        sp = None
        if self.spotify:
            # Spotify nur abfragen, während Spotify wirklich die laufende Wiedergabe ist
            self.spotify.set_active(state["active"] and state["app"] == "Spotify")
            sp = self.spotify.get_state()
            state = apply_spotify(state, sp)
        self.show_state(state, sp)
        if reschedule:
            self.after(REFRESH_MS, self.refresh)

    def show_state(self, state, sp=None):
        self.state = state
        self._update_texts()
        self._update_cover()
        self._update_progress()
        self._update_buttons()
        if self.queue_panel is not None and sp is not None:
            self.queue_panel.show(state, sp)

    def _set_once(self, key, value, apply):
        """Ruft apply(value) nur auf, wenn sich value geändert hat (verhindert Flackern)."""
        if self._shown.get(key, object()) != value:
            self._shown[key] = value
            apply(value)

    def _update_texts(self, force=False):
        state = self.state
        if state is None:
            return
        if not state["available"]:
            title, artist, app = "Nicht verfügbar", "", ""
        elif not state["active"]:
            title, artist, app = "Nichts läuft", "", ""
        else:
            title, artist, app = state["title"] or "Unbekannter Titel", state["artist"], state["app"]

        width = self.text_box.winfo_width()
        if force:
            self._shown.pop("texts", None)

        def apply(values):
            scaling = ctk.ScalingTracker.get_widget_scaling(self)
            title_font = ("Helvetica", -round(TITLE_SIZE * scaling), "bold")
            artist_font = ("Helvetica", -round(ARTIST_SIZE * scaling), "bold")
            # Etwas Luft lassen: das Textfeld im Label hat eigene Innenabstände
            room = values[3] - round(12 * scaling)
            self.lbl_title.configure(text=fit_text(values[0], title_font, room))
            self.lbl_artist.configure(text=fit_text(values[1], artist_font, room))
            self.lbl_app.configure(text=values[2])

        self._set_once("texts", (title, artist, app, width), apply)

    def _update_cover(self):
        state = self.state

        def apply(key):
            if key is None or state["cover"] is None:
                self.cover_label.grid_remove()
                self.cover_placeholder.grid(row=0, column=0, sticky="nw")
                return
            # CTkImage nur bei neuem Cover erzeugen und Referenz halten, sonst verschwindet das Bild
            self._cover_image = ctk.CTkImage(light_image=state["cover"], dark_image=state["cover"],
                                             size=(COVER_PX, COVER_PX))
            self.cover_label.configure(image=self._cover_image)
            self.cover_placeholder.grid_remove()
            self.cover_label.grid(row=0, column=0, sticky="nw")

        self._set_once("cover", state["cover_key"] if state["active"] else None, apply)

    def _update_progress(self):
        state = self.state
        duration = state["duration"] if state["active"] else 0
        has_timeline = duration > 0

        self._set_once("seekable", state["can_seek"] and state["active"],
                       lambda on: self.slider.configure(state="normal" if on else "disabled",
                                                        button_color=COLORS["accent"] if on else COLORS["border"]))
        self._set_once("duration", format_time(duration) if has_timeline else "0:00",
                       lambda text: self.lbl_duration.configure(text=text))

        if self.dragging:
            return
        position = current_position(state) if has_timeline else 0
        self.slider.set(position / duration if has_timeline else 0)
        self._set_once("position", format_time(position), lambda text: self.lbl_position.configure(text=text))

    def _update_buttons(self):
        state = self.state
        active = state["active"]

        def enable(button, on):
            button.configure(state="normal" if on else "disabled")

        self._set_once("play_icon", "pause" if state["playing"] else "play",
                       lambda icon: self.btn_play.configure(text=self.icons[icon]))
        self._set_once("can_play", active and state["can_play_pause"], lambda on: enable(self.btn_play, on))
        # Ohne eigenes Zurück/Weiter der App gehen die Knöpfe trotzdem, solange gespult werden kann
        self._set_once("can_previous", active and (state["can_previous"] or state["can_seek"]),
                       lambda on: enable(self.btn_previous, on))
        self._set_once("can_next", active and (state["can_next"] or state["can_seek"]),
                       lambda on: enable(self.btn_next, on))

        # Shuffle/Wiederholen: grün = an, grau = aus, ausgegraut = von der App nicht unterstützt.
        # Smart Shuffle von Spotify: blau
        if state.get("smart_shuffle"):
            shuffle_mode = "smart"
        else:
            shuffle_mode = "on" if state["shuffle"] else "off"
        shuffle_colors = {"off": COLORS["muted_text"], "on": COLORS["good"], "smart": COLORS["accent_hover"]}
        self._set_once("shuffle", (active and state["can_shuffle"], shuffle_mode), lambda v: (
            enable(self.btn_shuffle, v[0]),
            self.btn_shuffle.configure(text_color=shuffle_colors[v[1]])
        ))

        repeat = state["repeat"] or "off"
        self._set_once("repeat", (active and state["can_repeat"], repeat), lambda v: (
            enable(self.btn_repeat, v[0]),
            self.btn_repeat.configure(
                text=self.icons["repeat_track" if v[1] == "track" else "repeat_list"],
                text_color=COLORS["muted_text"] if v[1] == "off" else COLORS["good"]
            )
        ))
