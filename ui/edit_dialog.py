import os
import customtkinter as ctk
from tkinter import colorchooser, filedialog
from PIL import Image
from config import COLORS


def get_contrast_text_color(hex_color: str) -> str:
    """Berechnet die Helligkeit und gibt die optimale Schriftfarbe (Schwarz/Weiß) zurück."""
    if not hex_color or not isinstance(hex_color, str):
        return COLORS["text"]

    hex_color = hex_color.lstrip('#')
    if len(hex_color) != 6:
        return COLORS["text"]

    try:
        r, g, b = [int(hex_color[i:i+2], 16) for i in (0, 2, 4)]
        luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
        return "#111111" if luminance > 0.5 else "#FFFFFF"
    except ValueError:
        return COLORS["text"]


class EditButtonDialog(ctk.CTkToplevel):
    def __init__(self, parent, button_data, on_save_callback):
        super().__init__(parent)

        self.button_data = button_data.copy()
        self.on_save_callback = on_save_callback

        # Drag-Variablen
        self._offset_x = 0
        self._offset_y = 0

        # Titelleiste entfernen & im Vordergrund halten
        self.overrideredirect(True)
        self.attributes("-topmost", True)

        self.geometry("420x620")
        self.configure(fg_color=COLORS["card"])

        # Daten initialisieren
        self.current_bg = self.button_data.get("bg_color", COLORS["card"])
        self.current_text = self.button_data.get("text_color", get_contrast_text_color(self.current_bg))
        self.current_icon = self.button_data.get("icon_path", "")

        action_data = self.button_data.get("action_data", {}) if isinstance(self.button_data.get("action_data"), dict) else {}
        self.current_path = action_data.get("path", "")
        self.current_url = action_data.get("url", "")
        self.current_action_type = self.button_data.get("action_type", "program")

        self.setup_ui()
        self.update_preview()
        self.focus_force()

    def setup_ui(self):
        border_frame = ctk.CTkFrame(
            self,
            fg_color=COLORS["card"],
            border_color=COLORS["border"],
            border_width=1,
            corner_radius=12
        )
        border_frame.pack(fill="both", expand=True)

        container = ctk.CTkFrame(border_frame, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=20, pady=15)

        # Header (Drag & Drop)
        header_frame = ctk.CTkFrame(container, fg_color="transparent")
        header_frame.pack(fill="x", pady=(0, 10))

        lbl_title = ctk.CTkLabel(
            header_frame,
            text="✏️ Button konfigurieren",
            font=("Helvetica", 15, "bold"),
            text_color=COLORS["accent_hover"]
        )
        lbl_title.pack(side="left")

        for widget in (header_frame, lbl_title):
            widget.bind("<Button-1>", self.start_drag)
            widget.bind("<B1-Motion>", self.do_drag)

        btn_close = ctk.CTkButton(
            header_frame,
            text="✕",
            width=28,
            height=28,
            fg_color="transparent",
            hover_color=COLORS["card_hover"],
            text_color=COLORS["accent_hover"],
            font=("Helvetica", 14, "bold"),
            command=self.destroy
        )
        btn_close.pack(side="right")

        # ==========================================
        # LIVE VORSCHAU (PREVIEW)
        # ==========================================
        lbl_prev_title = ctk.CTkLabel(container, text="Vorschau:", font=("Helvetica", 11), text_color=COLORS["muted_text"])
        lbl_prev_title.pack(anchor="w", pady=(0, 2))

        self.preview_box = ctk.CTkFrame(container, fg_color="transparent", height=105)
        self.preview_box.pack(fill="x", pady=(0, 10))
        self.preview_box.pack_propagate(False)

        self.preview_button = ctk.CTkButton(
            self.preview_box,
            text="",
            font=("Helvetica", 12, "bold"),
            corner_radius=12,
            width=100,
            height=100
        )
        self.preview_button.place(relx=0.5, rely=0.5, anchor="center")

        # ==========================================
        # EINGABEFELDER
        # ==========================================
        # 1. Name Input
        lbl_name = ctk.CTkLabel(container, text="Name:", font=("Helvetica", 12), text_color=COLORS["text"])
        lbl_name.pack(anchor="w", pady=(2, 2))

        self.entry_name = ctk.CTkEntry(
            container,
            fg_color=COLORS["bg"],
            border_color=COLORS["border"],
            text_color=COLORS["text"]
        )
        self.entry_name.insert(0, self.button_data.get("name", ""))
        self.entry_name.pack(fill="x", pady=(0, 10))
        self.entry_name.bind("<KeyRelease>", lambda e: self.update_preview())



        # 2. Aktionstyp (CUSTOM DARK-DROPDOWN) & Ziel
        lbl_action = ctk.CTkLabel(container, text="Aktionstyp:", font=("Helvetica", 12), text_color=COLORS["text"])
        lbl_action.pack(anchor="w", pady=(2, 2))

        self.btn_dropdown = ctk.CTkButton(
            container,
            text="Programm / App  ▾" if self.current_action_type == "program" else "Webseite (URL)  ▾",
            anchor="w",
            fg_color=COLORS["bg"],
            hover_color=COLORS["card_hover"],
            border_color=COLORS["border"],
            border_width=1,
            text_color=COLORS["text"],
            command=self.open_custom_dropdown
        )
        self.btn_dropdown.pack(fill="x", pady=(0, 10))

        self.target_frame = ctk.CTkFrame(container, fg_color="transparent")
        self.target_frame.pack(fill="x", pady=(0, 15))

        self.entry_target = ctk.CTkEntry(
            self.target_frame,
            fg_color=COLORS["bg"],
            border_color=COLORS["border"],
            text_color=COLORS["text"]
        )
        self.entry_target.pack(side="left", fill="x", expand=True, padx=(0, 5))

        self.btn_browse_target = ctk.CTkButton(
            self.target_frame,
            text="📁",
            width=35,
            fg_color=COLORS["bg"],
            hover_color=COLORS["card_hover"],
            command=self.browse_target_file
        )
        self.btn_browse_target.pack(side="right")

        self.update_target_field()

        # 3. Farbauswahl
        lbl_color = ctk.CTkLabel(container, text="Hintergrundfarbe:", font=("Helvetica", 12), text_color=COLORS["text"])
        lbl_color.pack(anchor="w", pady=(2, 2))

        color_frame = ctk.CTkFrame(container, fg_color="transparent")
        color_frame.pack(fill="x", pady=(0, 10))

        self.entry_color = ctk.CTkEntry(
            color_frame,
            fg_color=COLORS["bg"],
            border_color=COLORS["border"],
            text_color=COLORS["text"],
            width=200
        )
        self.entry_color.insert(0, self.current_bg)
        self.entry_color.pack(side="left", padx=(0, 10))
        self.entry_color.bind("<KeyRelease>", self.on_hex_changed)

        btn_picker = ctk.CTkButton(
            color_frame,
            text="🎨 Wählen",
            width=90,
            fg_color=COLORS["bg"],
            hover_color=COLORS["card_hover"],
            command=self.open_color_picker
        )
        btn_picker.pack(side="left")

        # Palette
        palette_frame = ctk.CTkFrame(container, fg_color="transparent")
        palette_frame.pack(fill="x", pady=(0, 15))

        presets = ["#3b3f7f", "#2A2D5A", "#BF616A", "#D08770", "#EBCB8B", "#A3BE8C", "#B48EAD", "#ffffff"]
        for color in presets:
            btn_preset = ctk.CTkButton(
                palette_frame,
                text="",
                fg_color=color,
                hover_color=color,
                width=26,
                height=26,
                corner_radius=13,
                command=lambda c=color: self.apply_color(c)
            )
            btn_preset.pack(side="left", padx=2)

        # 2. Icon Pfad
        lbl_icon = ctk.CTkLabel(container, text="Icon / Logo:", font=("Helvetica", 12), text_color=COLORS["text"])
        lbl_icon.pack(anchor="w", pady=(2, 2))

        icon_frame = ctk.CTkFrame(container, fg_color="transparent")
        icon_frame.pack(fill="x", pady=(0, 10))

        self.entry_icon = ctk.CTkEntry(
            icon_frame,
            fg_color=COLORS["bg"],
            border_color=COLORS["border"],
            text_color=COLORS["text"]
        )
        self.entry_icon.insert(0, self.current_icon if self.current_icon else "")
        self.entry_icon.pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.entry_icon.bind("<KeyRelease>", lambda e: self.update_icon_from_entry())

        btn_browse_icon = ctk.CTkButton(
            icon_frame,
            text="Brwose...",
            width=35,
            fg_color=COLORS["accent"],
            hover_color=COLORS["card_hover"],
            command=self.browse_icon
        )
        btn_browse_icon.pack(side="right")

        # Buttons unten
        btn_box = ctk.CTkFrame(container, fg_color="transparent")
        btn_box.pack(fill="x", side="bottom")

        btn_save = ctk.CTkButton(
            btn_box,
            text="Speichern",
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            text_color=COLORS["text"],
            command=self.save
        )
        btn_save.pack(side="right", padx=(5, 0))

        btn_cancel = ctk.CTkButton(
            btn_box,
            text="Abbrechen",
            fg_color="transparent",
            hover_color=COLORS["card_hover"],
            text_color=COLORS["muted_text"],
            command=self.destroy
        )
        btn_cancel.pack(side="right")

    # ==========================================
    # CUSTOM DROPDOWN LOGIK (VOLLE BREITE & DARK-MODE)
    # ==========================================
    def open_custom_dropdown(self):
        """Öffnet ein rahmenloses Pop-up exakt über die gesamte Breite des Eingabefeldes."""
        self.update_idletasks()

        popup = ctk.CTkToplevel(self)
        popup.overrideredirect(True)
        popup.configure(fg_color=COLORS["card"])
        popup.attributes("-topmost", True)

        # Exakte Position und exakte Breite des Auswahlbuttons berechnen
        x = self.btn_dropdown.winfo_rootx()
        y = self.btn_dropdown.winfo_rooty() + self.btn_dropdown.winfo_height() + 4
        width = self.btn_dropdown.winfo_width()
        popup.geometry(f"{width}x72+{x}+{y}")

        menu_frame = ctk.CTkFrame(
            popup,
            fg_color=COLORS["card"],
            border_color=COLORS["border"],
            border_width=1,
            corner_radius=8
        )
        menu_frame.pack(fill="both", expand=True)

        def select_option(action_type, label_text):
            self.current_action_type = action_type
            self.btn_dropdown.configure(text=f"{label_text}  ▾")
            self.update_target_field()
            popup.destroy()

        btn_opt1 = ctk.CTkButton(
            menu_frame,
            text="Programm / App",
            anchor="w",
            fg_color="transparent",
            hover_color=COLORS["card_hover"],
            text_color=COLORS["text"],
            height=30,
            command=lambda: select_option("program", "Programm / App")
        )
        btn_opt1.pack(fill="x", padx=4, pady=(4, 2))

        btn_opt2 = ctk.CTkButton(
            menu_frame,
            text="Webseite (URL)",
            anchor="w",
            fg_color="transparent",
            hover_color=COLORS["card_hover"],
            text_color=COLORS["text"],
            height=30,
            command=lambda: select_option("url", "Webseite (URL)")
        )
        btn_opt2.pack(fill="x", padx=4, pady=(2, 4))

        # Schließt sich automatisch, wenn der Fokus verloren geht
        popup.bind("<FocusOut>", lambda e: popup.after(200, lambda: popup.destroy() if popup.winfo_exists() else None))
        popup.focus_force()

    # ==========================================
    # LOGIK & UPDATES
    # ==========================================
    def update_preview(self):
        """Aktualisiert die Live-Vorschau: Zeigt Icon ODER Text."""
        name = self.entry_name.get().strip() if hasattr(self, "entry_name") else "App"
        if not name:
            name = "App"

        img = None
        path_to_check = self.current_icon.strip() if isinstance(self.current_icon, str) else ""

        if path_to_check and os.path.exists(path_to_check):
            try:
                pil_img = Image.open(path_to_check).convert("RGBA")
                img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(64, 64))
            except Exception as e:
                print(f"Vorschau Icon-Ladefehler: {e}")
                img = None

        if img is not None:
            self.preview_button.configure(
                text="",
                image=img,
                compound="top",
                fg_color=self.current_bg
            )
            self.preview_button._image_ref = img
        else:
            self.preview_button.configure(
                text=name,
                image=None,
                compound="center",
                fg_color=self.current_bg,
                text_color=self.current_text
            )

    def browse_icon(self):
        filename = filedialog.askopenfilename(
            parent=self,
            title="Icon auswählen",
            filetypes=[("Bilder", "*.png *.jpg *.jpeg *.ico"), ("Alle Dateien", "*.*")]
        )
        if filename:
            self.current_icon = filename
            self.entry_icon.delete(0, "end")
            self.entry_icon.insert(0, filename)
            self.update_preview()

    def update_icon_from_entry(self):
        self.current_icon = self.entry_icon.get().strip()
        self.update_preview()

    def update_target_field(self):
        self.entry_target.delete(0, "end")

        if self.current_action_type == "program":
            self.entry_target.insert(0, self.current_path)
            self.btn_browse_target.pack(side="right")
        else:
            self.entry_target.insert(0, self.current_url)
            self.btn_browse_target.pack_forget()

    def browse_target_file(self):
        filename = filedialog.askopenfilename(
            parent=self,
            title="Programm oder Datei auswählen",
            filetypes=[("Ausführbare Dateien & Links", "*.exe *.lnk *.bat"), ("Alle Dateien", "*.*")]
        )
        if filename:
            self.current_path = filename
            self.entry_target.delete(0, "end")
            self.entry_target.insert(0, filename)

    def apply_color(self, hex_color: str):
        self.current_bg = hex_color
        self.current_text = get_contrast_text_color(hex_color)
        self.entry_color.delete(0, "end")
        self.entry_color.insert(0, hex_color)
        self.update_preview()

    def on_hex_changed(self, event):
        val = self.entry_color.get().strip()
        if len(val) == 7 and val.startswith("#"):
            self.apply_color(val)

    def open_color_picker(self):
        color = colorchooser.askcolor(initialcolor=self.current_bg, parent=self)
        if color[1]:
            self.apply_color(color[1])

    def start_drag(self, event):
        self._offset_x = event.x
        self._offset_y = event.y

    def do_drag(self, event):
        x = self.winfo_pointerx() - self._offset_x
        y = self.winfo_pointery() - self._offset_y
        self.geometry(f"+{x}+{y}")

    def save(self):
        new_name = self.entry_name.get().strip() or "Unbenannt"
        target_val = self.entry_target.get().strip()

        self.button_data["name"] = new_name
        self.button_data["bg_color"] = self.current_bg
        self.button_data["text_color"] = self.current_text
        self.button_data["icon_path"] = self.current_icon

        if self.current_action_type == "program":
            self.button_data["action_type"] = "program"
            self.button_data["action_data"] = {"path": target_val, "url": "", "hotkey": [], "sound_file": ""}
        else:
            self.button_data["action_type"] = "url"
            self.button_data["action_data"] = {"path": "", "url": target_val, "hotkey": [], "sound_file": ""}

        self.on_save_callback(self.button_data)
        self.destroy()