import ctypes
import sys
import threading
import time

# Tastenkombinationen senden, als hätte man sie auf der Tastatur gedrückt (Windows SendInput).
# Gespeichert wird eine Kombination als Liste von Tasten-Kennungen, Umschalttasten zuerst:
# ["ctrl", "shift", "m"]  ->  Strg + Umschalt + M

# (Kennung, Anzeige, Virtual-Key-Code, erweiterte Taste?)
# Erweiterte Tasten (Pfeile, Pos1, Entf, Medientasten …) braucht Windows mit eigenem Kennzeichen,
# sonst kommen z. B. Pfeiltasten als Ziffernblock-Tasten an.
MODIFIERS = [
    ("ctrl", "Strg", 0x11, False),
    ("shift", "Umschalt", 0x10, False),
    ("alt", "Alt", 0x12, False),
    ("win", "Win", 0x5B, True),
]

KEY_GROUPS = [
    ("Buchstaben", [(c.lower(), c, ord(c), False) for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"] + [
        ("oem_3", "Ö", 0xC0, False), ("oem_7", "Ä", 0xDE, False), ("oem_1", "Ü", 0xBA, False),
        ("oem_4", "ß", 0xDB, False),
    ]),
    ("Zahlen", [(str(n), str(n), 0x30 + n, False) for n in range(10)] + [
        ("oem_comma", ",", 0xBC, False), ("oem_period", ".", 0xBE, False), ("oem_minus", "-", 0xBD, False),
        ("oem_plus", "+", 0xBB, False), ("oem_2", "#", 0xBF, False), ("oem_102", "<", 0xE2, False),
        ("oem_5", "^", 0xDC, False), ("oem_6", "´", 0xDD, False),
    ]),
    ("F-Tasten", [(f"f{n}", f"F{n}", 0x6F + n, False) for n in range(1, 25)]),
    ("Sonder", [
        ("space", "Leertaste", 0x20, False), ("enter", "Enter", 0x0D, False), ("tab", "Tab", 0x09, False),
        ("esc", "Esc", 0x1B, False), ("backspace", "Rücktaste", 0x08, False), ("delete", "Entf", 0x2E, True),
        ("insert", "Einfg", 0x2D, True), ("home", "Pos1", 0x24, True), ("end", "Ende", 0x23, True),
        ("pageup", "Bild ↑", 0x21, True), ("pagedown", "Bild ↓", 0x22, True),
        ("up", "↑", 0x26, True), ("down", "↓", 0x28, True), ("left", "←", 0x25, True), ("right", "→", 0x27, True),
        ("printscreen", "Druck", 0x2C, True), ("pause", "Pause", 0x13, False), ("capslock", "Feststell", 0x14, False),
        ("scrolllock", "Rollen", 0x91, False), ("apps", "Menü", 0x5D, True),
    ]),
    ("Ziffernblock", [(f"num{n}", f"Num {n}", 0x60 + n, False) for n in range(10)] + [
        ("num_add", "Num +", 0x6B, False), ("num_subtract", "Num -", 0x6D, False),
        ("num_multiply", "Num *", 0x6A, False), ("num_divide", "Num /", 0x6F, True),
        ("num_decimal", "Num ,", 0x6E, False), ("numlock", "Num-Lock", 0x90, True),
    ]),
    ("Medien", [
        ("media_play_pause", "Play/Pause", 0xB3, True), ("media_next", "Nächster", 0xB0, True),
        ("media_prev", "Vorheriger", 0xB1, True), ("media_stop", "Stopp", 0xB2, True),
        ("volume_up", "Lauter", 0xAF, True), ("volume_down", "Leiser", 0xAE, True),
        ("volume_mute", "Stumm", 0xAD, True),
    ]),
]

KEYS = {key[0]: key for key in MODIFIERS}
for _, group in KEY_GROUPS:
    KEYS.update({key[0]: key for key in group})
MODIFIER_IDS = [m[0] for m in MODIFIERS]

# Tastendruck beim Aufnehmen: Virtual-Key-Code -> Kennung (Tk liefert unter Windows den VK-Code)
VK_TO_ID = {}
for key_id, _, vk, _ in KEYS.values():
    VK_TO_ID.setdefault(vk, key_id)
# Linke/rechte Fassungen der Umschalttasten
VK_TO_ID.update({0xA0: "shift", 0xA1: "shift", 0xA2: "ctrl", 0xA3: "ctrl", 0xA4: "alt", 0xA5: "alt", 0x5C: "win"})

PRESS_DELAY_S = 0.03  # kurze Pausen zwischen den Tasten: manche Spiele übersehen sonst gleichzeitige Ereignisse


# ---------------------------------------------------------------------------------------------------------
# Reine Hilfsfunktionen
# ---------------------------------------------------------------------------------------------------------

def normalize(keys):
    """Umschalttasten in fester Reihenfolge zuerst, dann höchstens eine Haupttaste; Unbekanntes fliegt raus."""
    keys = [k for k in keys if k in KEYS]
    modifiers = [m for m in MODIFIER_IDS if m in keys]
    main = [k for k in keys if k not in MODIFIER_IDS]
    return modifiers + main[-1:]


def main_key(keys):
    rest = [k for k in normalize(keys) if k not in MODIFIER_IDS]
    return rest[0] if rest else None


def label(keys):
    """["ctrl", "shift", "m"] -> "Strg + Umschalt + M" """
    keys = normalize(keys)
    return " + ".join(KEYS[k][1] for k in keys) if keys else "Keine Tasten gewählt"


def key_events(keys):
    """Reihenfolge der Ereignisse: Umschalttasten drücken, Haupttaste drücken und loslassen, Umschalttasten loslassen."""
    keys = normalize(keys)
    modifiers = [k for k in keys if k in MODIFIER_IDS]
    main = [k for k in keys if k not in MODIFIER_IDS]
    return ([(k, True) for k in modifiers] + [(k, True) for k in main] +
            [(k, False) for k in main] + [(k, False) for k in reversed(modifiers)])


# ---------------------------------------------------------------------------------------------------------
# Senden über Windows
# ---------------------------------------------------------------------------------------------------------

INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
MAPVK_VK_TO_VSC = 0


class _KEYBDINPUT(ctypes.Structure):
    # Feste Größen wie in der Windows-Doku (WORD = 16 Bit, DWORD = 32 Bit, ULONG_PTR = Zeigergröße)
    _fields_ = [("wVk", ctypes.c_uint16), ("wScan", ctypes.c_uint16), ("dwFlags", ctypes.c_uint32),
                ("time", ctypes.c_uint32), ("dwExtraInfo", ctypes.c_size_t)]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_int32), ("dy", ctypes.c_int32), ("mouseData", ctypes.c_uint32),
                ("dwFlags", ctypes.c_uint32), ("time", ctypes.c_uint32), ("dwExtraInfo", ctypes.c_size_t)]


class _INPUT_UNION(ctypes.Union):
    # Die Maus-Variante ist die größte: sie legt die Größe fest, die Windows erwartet
    _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint32), ("union", _INPUT_UNION)]


def _send_one(key_id, down):
    user32 = ctypes.windll.user32
    _, _, vk, extended = KEYS[key_id]
    flags = (KEYEVENTF_EXTENDEDKEY if extended else 0) | (0 if down else KEYEVENTF_KEYUP)
    # Scancode zusätzlich zum VK-Code: Spiele lesen oft nur den Scancode
    scan = user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
    event = _INPUT(type=INPUT_KEYBOARD, union=_INPUT_UNION(ki=_KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags)))
    if user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(_INPUT)) != 1:
        print(f"Tastenkombination: Windows hat {KEYS[key_id][1]} nicht angenommen "
              f"(z. B. Programm mit Admin-Rechten vorne)")


def send_hotkey(keys):
    """Kombination im Hintergrund senden (die Oberfläche wartet nicht auf die kleinen Pausen)."""
    keys = normalize(keys)
    if not keys or sys.platform != "win32":
        return

    def run():
        for key_id, down in key_events(keys):
            _send_one(key_id, down)
            time.sleep(PRESS_DELAY_S)

    threading.Thread(target=run, name="Tastenkombination", daemon=True).start()
