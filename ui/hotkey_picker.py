import customtkinter as ctk
from config import COLORS
from core.hotkeys import KEY_GROUPS, KEYS, MODIFIERS, MODIFIER_IDS, VK_TO_ID, label, main_key, normalize

KEY_COLUMNS = 6


class HotkeyPicker(ctk.CTkFrame):
    """Tastenkombination zusammenstellen: Umschalttasten antippen, Haupttaste aus Gruppen wählen oder aufnehmen."""

    def __init__(self, master, keys=None, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        keys = normalize(keys or [])
        self.modifiers = {m for m in keys if m in MODIFIER_IDS}
        self.key = main_key(keys)
        self._popup = None
        self._recording = False
        self._held = set()

        # 1. Umschalttasten zum An-/Ausschalten
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x")
        self.modifier_buttons = {}
        for column, (key_id, text, _, _) in enumerate(MODIFIERS):
            row.grid_columnconfigure(column, weight=1, uniform="mods")
            button = ctk.CTkButton(row, text=text, height=34, corner_radius=8, font=("Helvetica", 12, "bold"),
                                   command=lambda k=key_id: self._toggle_modifier(k))
            button.grid(row=0, column=column, padx=2, sticky="ew")
            self.modifier_buttons[key_id] = button

        # 2. Haupttaste wählen oder aufnehmen
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", pady=(6, 0))
        self.btn_key = ctk.CTkButton(row, text="", height=34, corner_radius=8, anchor="w", font=("Helvetica", 12, "bold"),
                                     fg_color=COLORS["bg"], hover_color=COLORS["card_hover"], text_color=COLORS["text"],
                                     border_width=1, border_color=COLORS["border"], command=self._open_keys)
        self.btn_key.pack(side="left", fill="x", expand=True, padx=(2, 4))
        self.btn_record = ctk.CTkButton(row, text="⏺ Aufnehmen", width=110, height=34, corner_radius=8,
                                        font=("Helvetica", 12, "bold"), fg_color=COLORS["bg"],
                                        hover_color=COLORS["card_hover"], text_color=COLORS["text"],
                                        command=self._toggle_recording)
        self.btn_record.pack(side="right", padx=(0, 2))

        # 3. Ergebnis
        self.lbl_combo = ctk.CTkLabel(self, text="", font=("Helvetica", 14, "bold"), text_color=COLORS["accent_hover"])
        self.lbl_combo.pack(fill="x", pady=(6, 0))

        self._refresh()

    def get(self):
        return normalize(sorted(self.modifiers, key=MODIFIER_IDS.index) + ([self.key] if self.key else []))

    def close_popup(self):
        if self._popup is not None and self._popup.winfo_exists():
            self._popup.destroy()
        self._popup = None

    # ------------------------------------------------------------------------------------------------

    def _refresh(self):
        for key_id, button in self.modifier_buttons.items():
            on = key_id in self.modifiers
            button.configure(fg_color=COLORS["accent"] if on else COLORS["bg"],
                             hover_color=COLORS["accent_hover"] if on else COLORS["card_hover"],
                             text_color=COLORS["text"] if on else COLORS["muted_text"])
        self.btn_key.configure(text=f"Taste: {KEYS[self.key][1]}  ▾" if self.key else "Taste wählen  ▾")
        self.lbl_combo.configure(text=label(self.get()))

    def _toggle_modifier(self, key_id):
        self.modifiers ^= {key_id}  # ^= : drin -> raus, nicht drin -> rein
        self._refresh()

    def _set_key(self, key_id):
        self.key = key_id
        self.close_popup()
        self._refresh()

    # ---- Tastenauswahl (Gruppen statt langer Liste: auf dem Touchscreen muss nichts gescrollt werden) ----

    def _open_keys(self):
        if self._popup is not None:
            self.close_popup()
            return
        popup = ctk.CTkToplevel(self)
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)
        popup.configure(fg_color=COLORS["card"])
        self._popup = popup

        box = ctk.CTkFrame(popup, fg_color=COLORS["card"], border_color=COLORS["border"], border_width=1, corner_radius=10)
        box.pack(fill="both", expand=True)
        groups = [name for name, _ in KEY_GROUPS]
        grid = ctk.CTkFrame(box, fg_color="transparent")

        def show_group(name):
            for widget in grid.winfo_children():
                widget.destroy()
            keys = dict(KEY_GROUPS)[name]
            for index, (key_id, text, _, _) in enumerate(keys):
                chosen = key_id == self.key
                ctk.CTkButton(grid, text=text, width=58, height=36, corner_radius=8, font=("Helvetica", 12, "bold"),
                              fg_color=COLORS["accent"] if chosen else COLORS["bg"],
                              hover_color=COLORS["accent_hover"] if chosen else COLORS["card_hover"],
                              text_color=COLORS["text"],
                              command=lambda k=key_id: self._set_key(k)).grid(
                    row=index // KEY_COLUMNS, column=index % KEY_COLUMNS, padx=2, pady=2, sticky="ew")

        tabs = ctk.CTkSegmentedButton(box, values=groups, font=("Helvetica", 11, "bold"), height=30,
                                      selected_color=COLORS["accent"], selected_hover_color=COLORS["accent_hover"],
                                      unselected_color=COLORS["bg"], unselected_hover_color=COLORS["card_hover"],
                                      fg_color=COLORS["bg"], command=show_group)
        tabs.pack(fill="x", padx=8, pady=(8, 4))
        grid.pack(padx=8, pady=(0, 8))
        for column in range(KEY_COLUMNS):
            grid.grid_columnconfigure(column, weight=1, uniform="keys")

        # Mit der Gruppe der aktuellen Taste anfangen
        start = next((name for name, keys in KEY_GROUPS if any(k[0] == self.key for k in keys)), groups[0])
        tabs.set(start)
        show_group(start)

        popup.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - popup.winfo_reqwidth()) // 2
        y = self.btn_key.winfo_rooty() + self.btn_key.winfo_height() + 4
        popup.geometry(f"+{x}+{y}")

    # ---- Aufnehmen über die echte Tastatur ----

    def _toggle_recording(self):
        if self._recording:
            self._stop_recording()
            return
        self._recording = True
        self._held = set()
        self.btn_record.configure(text="⏹ Stopp", fg_color=COLORS["danger"], hover_color="#FF6B6B")
        self.lbl_combo.configure(text="Jetzt die Tasten drücken …")
        top = self.winfo_toplevel()
        top.focus_force()
        self._bindings = [top.bind("<KeyPress>", self._on_key_press, add="+"),
                          top.bind("<KeyRelease>", self._on_key_release, add="+")]

    def _stop_recording(self):
        self._recording = False
        top = self.winfo_toplevel()
        for sequence, binding in zip(("<KeyPress>", "<KeyRelease>"), getattr(self, "_bindings", [])):
            top.unbind(sequence, binding)
        self.btn_record.configure(text="⏺ Aufnehmen", fg_color=COLORS["bg"], hover_color=COLORS["card_hover"])
        self._refresh()

    def _on_key_press(self, event):
        # Tk liefert unter Windows in event.keycode den Virtual-Key-Code: unabhängig vom Tastaturlayout
        key_id = VK_TO_ID.get(event.keycode)
        if key_id is None:
            return "break"
        if key_id in MODIFIER_IDS:
            self._held.add(key_id)
            self.lbl_combo.configure(text=label(list(self._held)) + " + …")
        else:
            # Haupttaste gedrückt: Kombination ist fertig
            self.modifiers = set(self._held)
            self.key = key_id
            self._stop_recording()
        return "break"  # Taste nicht an Eingabefelder weitergeben

    def _on_key_release(self, event):
        key_id = VK_TO_ID.get(event.keycode)
        if key_id in self._held:
            self._held.discard(key_id)
        return "break"
