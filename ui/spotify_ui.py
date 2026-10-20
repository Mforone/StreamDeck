import webbrowser
import customtkinter as ctk
from config import COLORS
from core.spotify import REDIRECT_URI, SpotifyLogin, load_tokens
from ui.window_utils import center_over

QUEUE_TITLE_SIZE = 13
QUEUE_ARTIST_SIZE = 11
LOGIN_CHECK_MS = 500


class QueueRow(ctk.CTkFrame):
    """Ein Lied der Warteschlange: die ganze Zeile ist antippbar."""

    def __init__(self, master, number, on_select):
        super().__init__(master, fg_color="transparent", corner_radius=8)
        self.on_select = on_select
        self.uri = ""
        self.number = str(number)
        self.grid_columnconfigure(1, weight=1)

        self.lbl_number = ctk.CTkLabel(self, text=str(number), width=22, anchor="e",
                                       font=("Helvetica", QUEUE_ARTIST_SIZE, "bold"), text_color=COLORS["muted_text"])
        self.lbl_number.grid(row=0, column=0, rowspan=2, padx=(4, 8), pady=4)
        self.lbl_title = ctk.CTkLabel(self, text="", anchor="w", height=18,
                                      font=("Helvetica", QUEUE_TITLE_SIZE, "bold"), text_color=COLORS["text"])
        self.lbl_title.grid(row=0, column=1, sticky="ew", pady=(4, 0))
        self.lbl_artist = ctk.CTkLabel(self, text="", anchor="w", height=16,
                                       font=("Helvetica", QUEUE_ARTIST_SIZE, "bold"), text_color=COLORS["muted_text"])
        self.lbl_artist.grid(row=1, column=1, sticky="ew", pady=(0, 4))

        # Klick und Hover auf der Fläche und auf allen Texten darauf (leere Zeilen reagieren nicht)
        for widget in (self, self.lbl_number, self.lbl_title, self.lbl_artist):
            widget.bind("<Button-1>", lambda e: self._clicked())
            widget.bind("<Enter>", lambda e: self.uri and self.configure(fg_color=COLORS["card_hover"]))
            widget.bind("<Leave>", lambda e: self.configure(fg_color="transparent"))

    def show(self, entry, fit):
        """entry=None: leere Zeile (hält nur den Platz frei)."""
        self.uri = entry["uri"] if entry else ""
        self.lbl_number.configure(text=self.number if entry else "")
        self.lbl_title.configure(text=fit(entry["title"], QUEUE_TITLE_SIZE, "bold") if entry else "")
        self.lbl_artist.configure(text=fit(entry["artist"], QUEUE_ARTIST_SIZE, "bold") if entry else "")

    def _clicked(self):
        if self.uri:
            # Kurz aufleuchten als Rückmeldung fürs Tippen
            self.configure(fg_color=COLORS["accent"])
            self.after(250, lambda: self.configure(fg_color="transparent"))
            self.on_select(self.uri)


class QueuePanel(ctk.CTkFrame):
    """Box "Als Nächstes" unter dem Player. Zeigt je nach Lage Warteschlange, Hinweis oder Verbinden-Knopf."""

    def __init__(self, master, spotify, fit_text, **kwargs):
        super().__init__(master, fg_color=COLORS["card"], corner_radius=12, **kwargs)
        self.spotify = spotify
        self.fit_text = fit_text
        self._shown = None

        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=8, pady=8)

        header = ctk.CTkFrame(inner, fg_color="transparent")
        header.pack(fill="x", padx=4, pady=(0, 2))
        ctk.CTkLabel(header, text="Als Nächstes", font=("Helvetica", 13, "bold"),
                     text_color=COLORS["text"], anchor="w").pack(side="left")
        self.btn_settings = ctk.CTkButton(header, text="⚙", width=26, height=26, corner_radius=13,
                                          fg_color="transparent", hover_color=COLORS["card_hover"],
                                          text_color=COLORS["muted_text"], font=("Helvetica", 13),
                                          command=self._open_connect)
        self.btn_settings.pack(side="right")

        # Immer 5 Zeilen: die Box ist dadurch immer gleich hoch, Uhr und Monitoring darunter springen nicht
        self.rows_frame = ctk.CTkFrame(inner, fg_color="transparent")
        self.rows_frame.pack(fill="x")
        self.rows = [QueueRow(self.rows_frame, i + 1, self._select) for i in range(5)]
        for row in self.rows:
            row.show(None, None)
            row.pack(fill="x", pady=1)

        # Hinweis bzw. Verbinden-Knopf liegen bei Bedarf als Decke über den Zeilen
        self.overlay = ctk.CTkFrame(inner, fg_color=COLORS["card"])
        self.lbl_hint = ctk.CTkLabel(self.overlay, text="", font=("Helvetica", 12, "bold"),
                                     text_color=COLORS["muted_text"], wraplength=260, justify="left", anchor="w")
        self.btn_connect = ctk.CTkButton(self.overlay, text="Mit Spotify verbinden", font=("Helvetica", 13, "bold"),
                                         fg_color=COLORS["good"], hover_color=COLORS["accent_hover"],
                                         text_color="#111111", height=36, corner_radius=18,
                                         command=self._open_connect)

    def _fit(self, text, size, weight):
        scaling = ctk.ScalingTracker.get_widget_scaling(self)
        width = self.rows_frame.winfo_width() - round(48 * scaling)
        return self.fit_text(text, ("Helvetica", -round(size * scaling), weight), width)

    def _select(self, uri):
        self.spotify.command("jump", uri)

    def _open_connect(self):
        SpotifyConnectDialog(self.winfo_toplevel(), self.spotify)

    def show(self, player_state, sp):
        """player_state: zusammengeführter Stand des Players, sp: Stand des Spotify-Clients."""
        if not sp["connected"]:
            mode = ("connect",)
        elif not (player_state["active"] and player_state["app"] == "Spotify"):
            mode = ("hint", "Die Warteschlange gibt es nur, wenn Spotify spielt.")
        elif not sp["player"]:
            mode = ("hint", "Warte auf Spotify …")
        elif not sp["queue"]:
            mode = ("hint", "Keine weiteren Lieder in der Warteschlange.")
        else:
            entries = tuple((e["uri"], e["title"], e["artist"]) for e in sp["queue"])
            mode = ("queue", entries, self.rows_frame.winfo_width())

        if mode == self._shown:
            return
        self._shown = mode

        for widget in (self.lbl_hint, self.btn_connect):
            widget.pack_forget()
        self.btn_settings.pack_forget() if mode[0] == "connect" else self.btn_settings.pack(side="right")

        if mode[0] in ("connect", "hint"):
            for row in self.rows:
                row.show(None, None)
            self.overlay.place(in_=self.rows_frame, x=0, y=0, relwidth=1, relheight=1)
            self.overlay.lift()
            if mode[0] == "connect":
                self.lbl_hint.configure(text="Für Warteschlange, Shuffle und Wiederholen bei Spotify einmal verbinden.")
                self.lbl_hint.pack(fill="x", padx=4, pady=(4, 8))
                self.btn_connect.pack(fill="x", padx=4)
            else:
                self.lbl_hint.configure(text=mode[1])
                self.lbl_hint.pack(fill="x", padx=4, pady=4)
        else:
            self.overlay.place_forget()
            queue = list(sp["queue"]) + [None] * (len(self.rows) - len(sp["queue"]))
            for row, entry in zip(self.rows, queue):
                row.show(entry, self._fit)
            # Breite ist erst nach dem Anzeigen bekannt: einmal nachträglich neu kürzen
            self.after(50, lambda: self._refit(sp))

    def _refit(self, sp):
        if self._shown and self._shown[0] == "queue":
            for row, entry in zip(self.rows, sp["queue"]):
                row.show(entry, self._fit)


class SpotifyConnectDialog(ctk.CTkToplevel):
    """Client ID eingeben, Anmeldung im Browser starten, auf das Ergebnis warten."""

    def __init__(self, root, spotify):
        super().__init__(root)
        self.spotify = spotify
        self.login = None

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(fg_color=COLORS["card"])
        center_over(self, root, 440, 330)

        box = ctk.CTkFrame(self, fg_color=COLORS["card"], border_color=COLORS["border"], border_width=1, corner_radius=12)
        box.pack(fill="both", expand=True)
        inner = ctk.CTkFrame(box, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=20, pady=15)

        header = ctk.CTkFrame(inner, fg_color="transparent")
        header.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(header, text="🎵 Spotify verbinden", font=("Helvetica", 15, "bold"),
                     text_color=COLORS["accent_hover"]).pack(side="left")
        ctk.CTkButton(header, text="✕", width=28, height=28, fg_color="transparent", hover_color=COLORS["card_hover"],
                      text_color=COLORS["accent_hover"], font=("Helvetica", 14, "bold"),
                      command=self.destroy).pack(side="right")

        ctk.CTkLabel(inner, text="Client ID deiner Spotify-App", font=("Helvetica", 11, "bold"),
                     text_color=COLORS["muted_text"], anchor="w").pack(fill="x")
        self.entry = ctk.CTkEntry(inner, height=34, fg_color=COLORS["bg"], border_color=COLORS["border"],
                                  text_color=COLORS["text"], placeholder_text="z. B. 1a2b3c4d…")
        self.entry.pack(fill="x", pady=(2, 10))
        tokens = load_tokens()
        if tokens:
            self.entry.insert(0, tokens["client_id"])

        ctk.CTkLabel(inner, text="Redirect URI (so in der Spotify-App eintragen)", font=("Helvetica", 11, "bold"),
                     text_color=COLORS["muted_text"], anchor="w").pack(fill="x")
        uri_row = ctk.CTkFrame(inner, fg_color="transparent")
        uri_row.pack(fill="x", pady=(2, 12))
        ctk.CTkLabel(uri_row, text=REDIRECT_URI, font=("Consolas", 12), text_color=COLORS["text"],
                     anchor="w").pack(side="left")
        ctk.CTkButton(uri_row, text="Kopieren", width=80, height=26, fg_color=COLORS["bg"],
                      hover_color=COLORS["card_hover"], text_color=COLORS["text"],
                      command=self._copy_uri).pack(side="right")

        self.lbl_status = ctk.CTkLabel(inner, text="", font=("Helvetica", 11, "bold"), text_color=COLORS["muted_text"],
                                       wraplength=390, justify="left", anchor="w")
        self.lbl_status.pack(fill="x")

        buttons = ctk.CTkFrame(inner, fg_color="transparent")
        buttons.pack(fill="x", side="bottom")
        self.btn_start = ctk.CTkButton(buttons, text="Im Browser anmelden", font=("Helvetica", 13, "bold"),
                                       fg_color=COLORS["good"], hover_color=COLORS["accent_hover"], text_color="#111111",
                                       height=34, command=self._start)
        self.btn_start.pack(side="right")

        self.focus_force()
        self.entry.focus_set()

    def _copy_uri(self):
        self.clipboard_clear()
        self.clipboard_append(REDIRECT_URI)
        self._status("Kopiert.")

    def _status(self, text, color=None):
        self.lbl_status.configure(text=text, text_color=color or COLORS["muted_text"])

    def _start(self):
        client_id = self.entry.get().strip()
        if len(client_id) != 32:
            self._status("Die Client ID hat 32 Zeichen, bitte nochmal prüfen.", COLORS["danger"])
            return
        self.login = SpotifyLogin(client_id)
        if not self.login.start():
            self._status(self.login.message, COLORS["danger"])
            return
        webbrowser.open(self.login.url)
        self.btn_start.configure(state="disabled")
        self._status("Browser geöffnet: bei Spotify anmelden und „Zustimmen“ klicken …")
        self.after(LOGIN_CHECK_MS, self._check)

    def _check(self):
        if not self.winfo_exists():
            return
        if self.login.status == "waiting":
            self.after(LOGIN_CHECK_MS, self._check)
        elif self.login.status == "ok":
            self.spotify.login_finished()
            self._status("Verbunden ✓", COLORS["good"])
            self.after(1200, self.destroy)
        else:
            self._status(self.login.message, COLORS["danger"])
            self.btn_start.configure(state="normal")
