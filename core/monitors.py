import ctypes
import sys
from ctypes import wintypes

# Fragt Windows nach allen angeschlossenen Monitoren: Lage auf dem Gesamtdesktop, Auflösung, Hauptbildschirm.
# Die App ist DPI-bewusst (siehe main_window.py), deshalb sind alle Werte echte Pixel.

MONITORINFOF_PRIMARY = 0x1


class _MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


class _DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("DeviceName", wintypes.WCHAR * 32),
        ("DeviceString", wintypes.WCHAR * 128),
        ("StateFlags", wintypes.DWORD),
        ("DeviceID", wintypes.WCHAR * 128),
        ("DeviceKey", wintypes.WCHAR * 128),
    ]


def _model_name(user32, device):
    """Modellname des Monitors (z. B. "LG ULTRAGEAR"), falls Windows ihn kennt."""
    info = _DISPLAY_DEVICEW()
    info.cb = ctypes.sizeof(info)
    if user32.EnumDisplayDevicesW(device, 0, ctypes.byref(info), 0):
        name = info.DeviceString.strip()
        # Windows' Standardtreiber-Namen sagen nichts aus
        if name and "pnp" not in name.lower() and "standard" not in name.lower():
            return name
    return ""


def list_monitors():
    """Liste von Monitoren, sortiert von links nach rechts. Leere Liste außerhalb von Windows."""
    if sys.platform != "win32":
        return []

    user32 = ctypes.windll.user32
    found = []

    MONITORENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HMONITOR, wintypes.HDC,
                                         ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    def callback(handle, hdc, rect, data):
        info = _MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(info)
        if user32.GetMonitorInfoW(handle, ctypes.byref(info)):
            r = info.rcMonitor
            found.append({
                "device": info.szDevice,
                "x": r.left,
                "y": r.top,
                "width": r.right - r.left,
                "height": r.bottom - r.top,
                "primary": bool(info.dwFlags & MONITORINFOF_PRIMARY),
                "model": _model_name(user32, info.szDevice),
            })
        return 1  # weiter aufzählen

    user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(callback), 0)
    return number_monitors(found)


SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020


def place_window(hwnd, monitor):
    """Legt ein Fenster direkt über Windows exakt auf die Fläche eines Monitors.

    Gibt die Lage zurück, die das Fenster danach wirklich hat (links, oben, rechts, unten), zum Prüfen im Log.
    """
    if sys.platform != "win32":
        return None
    user32 = ctypes.windll.user32
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.SetWindowPos(hwnd, None, monitor["x"], monitor["y"], monitor["width"], monitor["height"],
                        SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def number_monitors(monitors):
    """Sortiert von links nach rechts (bei gleicher Spalte oben zuerst) und nummeriert ab 1."""
    ordered = sorted(monitors, key=lambda m: (m["x"], m["y"]))
    for index, monitor in enumerate(ordered, start=1):
        monitor["number"] = index
    return ordered


def choose_monitor(monitors, saved):
    """Gespeicherten Monitor wiederfinden: erst über den Gerätenamen, dann über die Lage, sonst Hauptbildschirm.

    Gerätenamen wie "\\\\.\\DISPLAY2" können sich nach Treiber-Updates ändern, die Lage bleibt meist gleich.
    """
    if not monitors:
        return None
    if saved:
        for monitor in monitors:
            if monitor["device"] == saved.get("device") and monitor["width"] == saved.get("width") \
                    and monitor["height"] == saved.get("height"):
                return monitor
        for monitor in monitors:
            if (monitor["x"], monitor["y"], monitor["width"], monitor["height"]) == \
                    (saved.get("x"), saved.get("y"), saved.get("width"), saved.get("height")):
                return monitor
        for monitor in monitors:
            if monitor["device"] == saved.get("device"):
                return monitor
    return next((m for m in monitors if m["primary"]), monitors[0])


def monitor_settings(monitor):
    """Was in config.json gespeichert wird."""
    return {key: monitor[key] for key in ("device", "x", "y", "width", "height")}


def monitor_label(monitor):
    parts = [f"Bildschirm {monitor['number']}", f"{monitor['width']} × {monitor['height']}"]
    if monitor["primary"]:
        parts.append("Hauptbildschirm")
    if monitor.get("model"):
        parts.append(monitor["model"])
    return " · ".join(parts)
