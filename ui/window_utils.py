import customtkinter as ctk


def center_over(window, anchor, width, height):
    """Legt `window` mittig über das Hauptfenster von `anchor`, also immer auf denselben Bildschirm.

    Ohne Position würde Windows neue Fenster auf den Hauptbildschirm legen.
    """
    root = anchor.winfo_toplevel()

    # customtkinter vergrößert Fenster je nach Windows-Skalierung (z. B. 125 %),
    # für die Mitte brauchen wir die echte Größe in Pixeln
    try:
        scaling = ctk.ScalingTracker.get_window_scaling(window)
    except Exception:
        scaling = 1.0
    real_width = round(width * scaling)
    real_height = round(height * scaling)

    # winfo_rootx/rooty: Position auf dem Gesamtdesktop, auf Bildschirmen links oder über dem Hauptbildschirm auch negativ
    x = root.winfo_rootx() + (root.winfo_width() - real_width) // 2
    y = root.winfo_rooty() + (root.winfo_height() - real_height) // 2

    # Breite und Höhe ohne Skalierung übergeben, customtkinter rechnet sie selbst hoch
    window.geometry(f"{width}x{height}+{x}+{y}")
