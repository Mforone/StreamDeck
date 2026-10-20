import os
import subprocess
import webbrowser
import customtkinter as ctk
from PIL import Image
from core.config_manager import save_config, load_config
from ui.edit_dialog import EditButtonDialog
from config import COLORS


def execute_button_action(app_data):
    """Führt die hinterlegte Aktion des Buttons aus."""
    if not isinstance(app_data, dict):
        return

    action_type = app_data.get("action_type", "program")
    action_data = app_data.get("action_data", {})

    if action_type == "program":
        path = action_data.get("path", "").strip() if action_data.get("path") else ""
        if path and os.path.exists(path):
            try:
                os.startfile(path)
            except Exception as e:
                print(f"Fehler beim Starten von {path}: {e}")
        elif path:
            print(f"Pfad nicht gefunden: {path}")

    elif action_type == "url":
        url = action_data.get("url", "").strip() if action_data.get("url") else ""
        if url:
            if not (url.startswith("http://") or url.startswith("https://")):
                url = "https://" + url
            webbrowser.open(url)


class AppButtonRow(ctk.CTkFrame):
    def __init__(self, master, left_app=None, right_app=None, **kwargs):
        super().__init__(master, fg_color="transparent", height=100, **kwargs)

        self.left_app = left_app
        self.right_app = right_app

        self.pack_propagate(False)
        self.grid_propagate(False)

        self.grid_columnconfigure(0, weight=1, uniform="row_cols")
        self.grid_columnconfigure(1, weight=1, uniform="row_cols")
        self.grid_rowconfigure(0, weight=1)

        BUTTON_WIDTH = 100
        BUTTON_HEIGHT = 100

        # Linker Button
        if left_app:
            self.btn_left = self.create_tile_button(left_app, BUTTON_WIDTH, BUTTON_HEIGHT)
            self.btn_left.grid(row=0, column=0, padx=(2, 2))
            self.btn_left.bind("<Button-3>", lambda event, app=left_app: self.show_context_menu(event, app))

        # Rechter Button
        if right_app:
            self.btn_right = self.create_tile_button(right_app, BUTTON_WIDTH, BUTTON_HEIGHT)
            self.btn_right.grid(row=0, column=1, padx=(2, 2))
            self.btn_right.bind("<Button-3>", lambda event, app=right_app: self.show_context_menu(event, app))

    def create_tile_button(self, app_data, width, height):
        """Erzeugt ein CTkButton-Objekt: Zeigt NUR das Icon oder NUR den Text."""
        icon_path = app_data.get("icon_path", "") if isinstance(app_data, dict) else ""
        img = None

        # Prüfen, ob eine Bilddatei existiert
        if icon_path and isinstance(icon_path, str) and icon_path.strip() and os.path.exists(icon_path):
            try:
                pil_img = Image.open(icon_path).convert("RGBA")
                # Bildgröße auf der 100x100 Kachel
                img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(80, 80))
            except Exception as e:
                print(f"Fehler beim Laden des Icons ({icon_path}): {e}")
                img = None

        button_name = app_data.get("name", "App") if isinstance(app_data, dict) else "App"

        if img is not None:
            # MIT ICON: Text bleibt leer "", compound="top" zentriert das Bild perfekt!
            btn = ctk.CTkButton(
                self,
                text="",
                image=img,
                compound="top",  # WICHTIG: Erhält die Bilddarstellung ohne Text
                fg_color=app_data.get("bg_color", COLORS["card"]),
                hover_color=COLORS["card_hover"],
                corner_radius=12,
                width=width,
                height=height,
                command=lambda app=app_data: execute_button_action(app)
            )
            btn._image_ref = img  # Schutz vor Garbage Collection
        else:
            # OHNE ICON: Nur Text mittig anzeigen
            btn = ctk.CTkButton(
                self,
                text=button_name,
                font=("Helvetica", 11, "bold"),
                fg_color=app_data.get("bg_color", COLORS["card"]),
                text_color=app_data.get("text_color", COLORS["text"]),
                hover_color=COLORS["card_hover"],
                corner_radius=12,
                width=width,
                height=height,
                command=lambda app=app_data: execute_button_action(app)
            )

        return btn

    def show_context_menu(self, event, app_data):
        """Erstellt ein Pop-up-Menü im Dark-Mode Design."""
        root = self.winfo_toplevel()

        popup = ctk.CTkToplevel(self)
        popup.overrideredirect(True)
        popup.configure(fg_color=COLORS["card"])
        popup.attributes("-topmost", True)

        x = event.x_root
        y = event.y_root
        popup.geometry(f"145x74+{x}+{y}")

        border_frame = ctk.CTkFrame(
            popup,
            fg_color=COLORS["card"],
            border_color=COLORS["border"],
            border_width=1,
            corner_radius=8
        )
        border_frame.pack(fill="both", expand=True)

        def delete_row():
            popup.destroy()

            # Bestätigungs-Pop-up im Dark-Mode Design erstellen
            confirm_dialog = ctk.CTkToplevel(root)
            confirm_dialog.overrideredirect(True)
            confirm_dialog.configure(fg_color=COLORS["card"])
            confirm_dialog.attributes("-topmost", True)

            # Positionieren (Zentriert über dem Hauptfenster oder der Maus)
            confirm_dialog.geometry("320x150")

            # Zentrieren relativ zum Hauptfenster
            root_x = root.winfo_x()
            root_y = root.winfo_y()
            root_w = root.winfo_width()
            root_h = root.winfo_height()
            x = root_x + (root_w // 2) - 160
            y = root_y + (root_h // 2) - 75
            confirm_dialog.geometry(f"320x150+{x}+{y}")

            border_frame = ctk.CTkFrame(
                confirm_dialog,
                fg_color=COLORS["card"],
                border_color=COLORS["border"],
                border_width=1,
                corner_radius=12
            )
            border_frame.pack(fill="both", expand=True)

            container = ctk.CTkFrame(border_frame, fg_color="transparent")
            container.pack(fill="both", expand=True, padx=20, pady=15)

            lbl_title = ctk.CTkLabel(
                container,
                text="⚠️ Button-Reihe löschen?",
                font=("Helvetica", 14, "bold"),
                text_color=COLORS["accent_hover"]
            )
            lbl_title.pack(anchor="w", pady=(0, 5))

            lbl_msg = ctk.CTkLabel(
                container,
                text="Möchtest du diese Reihe wirklich unwiderruflich entfernen?",
                font=("Helvetica", 11),
                text_color=COLORS["text"],
                wraplength=270,
                justify="left"
            )
            lbl_msg.pack(anchor="w", pady=(0, 15))

            btn_box = ctk.CTkFrame(container, fg_color="transparent")
            btn_box.pack(fill="x", side="bottom")

            def do_delete():
                confirm_dialog.destroy()

                left_id = self.left_app.get("id") if isinstance(self.left_app, dict) else None
                right_id = self.right_app.get("id") if isinstance(self.right_app, dict) else None
                ids_to_remove = {left_id, right_id} - {None}

                if hasattr(root, "config_data") and isinstance(root.config_data, dict):
                    config_data = root.config_data
                else:
                    config_data = load_config()

                if "buttons" in config_data:
                    config_data["buttons"] = [
                        btn for btn in config_data["buttons"]
                        if btn.get("id") not in ids_to_remove
                    ]

                    if hasattr(root, "config_data"):
                        root.config_data = config_data

                    save_config(config_data)

                self.destroy()

            btn_yes = ctk.CTkButton(
                btn_box,
                text="Löschen",
                fg_color=COLORS["danger"] if "danger" in COLORS else "#BF616A",
                hover_color="#D08770",
                text_color="#FFFFFF",
                width=90,
                command=do_delete
            )
            btn_yes.pack(side="right", padx=(5, 0))

            btn_no = ctk.CTkButton(
                btn_box,
                text="Abbrechen",
                fg_color="transparent",
                hover_color=COLORS["card_hover"],
                text_color=COLORS["muted_text"],
                width=90,
                command=confirm_dialog.destroy
            )
            btn_no.pack(side="right")

            confirm_dialog.focus_force()

        def save_button_changes(updated_button):
            config_data = root.config_data if hasattr(root, "config_data") else load_config()

            if "buttons" in config_data:
                for idx, btn in enumerate(config_data["buttons"]):
                    if btn.get("id") == updated_button.get("id"):
                        config_data["buttons"][idx] = updated_button
                        break

                if hasattr(root, "config_data"):
                    root.config_data = config_data

                save_config(config_data)

                if hasattr(root, "load_button_rows"):
                    root.load_button_rows()

        def handle_action(action_type):
            if action_type == "edit":
                popup.destroy()
                EditButtonDialog(root, app_data, save_button_changes)
            elif action_type == "delete":
                delete_row()

        btn_edit = ctk.CTkButton(
            border_frame,
            text="✏️ Bearbeiten",
            anchor="w",
            fg_color="transparent",
            hover_color=COLORS["card_hover"],
            text_color=COLORS["text"],
            height=30,
            corner_radius=5,
            command=lambda: handle_action("edit")
        )
        btn_edit.pack(fill="x", padx=4, pady=(5, 2))

        btn_delete = ctk.CTkButton(
            border_frame,
            text="🗑️ Löschen",
            anchor="w",
            fg_color="transparent",
            hover_color=COLORS["card_hover"],
            text_color=COLORS["danger"] if "danger" in COLORS else COLORS["text"],
            height=30,
            corner_radius=5,
            command=lambda: handle_action("delete")
        )
        btn_delete.pack(fill="x", padx=4, pady=(2, 5))

        popup.bind("<FocusOut>", lambda e: popup.after(1000, lambda: popup.destroy() if popup.winfo_exists() else None))
        popup.focus_force()