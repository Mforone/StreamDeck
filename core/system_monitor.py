import ctypes
import re
import sys
import threading
import time

import psutil

# Liest CPU, RAM und GPU in einem eigenen Hintergrund-Thread aus, damit die Oberfläche nie hängt.
# Die Oberfläche holt sich nur die letzten Werte über get_values().

UPDATE_INTERVAL_S = 1.0

# ---------------------------------------------------------------------------------------------------------
# GPU über die Windows-Leistungsindikatoren (PDH), genau wie der Task-Manager.
# Funktioniert mit NVIDIA, AMD und Intel, ohne Zusatzprogramm.
# ---------------------------------------------------------------------------------------------------------

PDH_FMT_DOUBLE = 0x00000200
PDH_MORE_DATA = 0x800007D2
PDH_CSTATUS_VALID_DATA = 0x0
PDH_CSTATUS_NEW_DATA = 0x1

# Englischer Name, damit es auch auf deutschem Windows funktioniert (dort heißen die Zähler anders)
GPU_COUNTER = r"\GPU Engine(*)\Utilization Percentage"

# Beispiel-Instanz: pid_1234_luid_0x00000000_0x0000D1A5_phys_0_eng_0_engtype_3D
INSTANCE_PATTERN = re.compile(r"luid_(0x[0-9a-fA-F]+_0x[0-9a-fA-F]+)_phys_(\d+)_eng_\d+_engtype_(.+)$")


class _PDH_FMT_COUNTERVALUE(ctypes.Structure):
    _fields_ = [("CStatus", ctypes.c_ulong), ("doubleValue", ctypes.c_double)]


class _PDH_FMT_COUNTERVALUE_ITEM_W(ctypes.Structure):
    _fields_ = [("szName", ctypes.c_wchar_p), ("FmtValue", _PDH_FMT_COUNTERVALUE)]


class GpuReader:
    def __init__(self):
        self.pdh = ctypes.WinDLL("pdh")
        handle = ctypes.c_void_p
        status = ctypes.c_long

        self.pdh.PdhOpenQueryW.argtypes = [ctypes.c_wchar_p, ctypes.c_size_t, ctypes.POINTER(handle)]
        self.pdh.PdhOpenQueryW.restype = status
        self.pdh.PdhAddEnglishCounterW.argtypes = [handle, ctypes.c_wchar_p, ctypes.c_size_t, ctypes.POINTER(handle)]
        self.pdh.PdhAddEnglishCounterW.restype = status
        self.pdh.PdhCollectQueryData.argtypes = [handle]
        self.pdh.PdhCollectQueryData.restype = status
        self.pdh.PdhGetFormattedCounterArrayW.argtypes = [
            handle, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong), ctypes.c_void_p
        ]
        self.pdh.PdhGetFormattedCounterArrayW.restype = status

        self.query = handle()
        self.counter = handle()
        self._check(self.pdh.PdhOpenQueryW(None, 0, ctypes.byref(self.query)), "PdhOpenQueryW")
        self._check(self.pdh.PdhAddEnglishCounterW(self.query, GPU_COUNTER, 0, ctypes.byref(self.counter)), "PdhAddEnglishCounterW")

        # Auslastung ist ein Rate-Zähler: braucht zwei Messungen, die erste liefert noch nichts
        self.pdh.PdhCollectQueryData(self.query)
        self._reported = False

    @staticmethod
    def _check(result, name):
        if result != 0:
            raise OSError(f"{name} fehlgeschlagen (0x{result & 0xFFFFFFFF:08X})")

    def _read_items(self):
        """Holt alle Instanzen des Zählers. Zweistufig: erst Größe erfragen, dann Daten holen."""
        while True:
            size = ctypes.c_ulong(0)
            count = ctypes.c_ulong(0)
            result = self.pdh.PdhGetFormattedCounterArrayW(self.counter, PDH_FMT_DOUBLE, ctypes.byref(size), ctypes.byref(count), None)
            if (result & 0xFFFFFFFF) != PDH_MORE_DATA:
                return []

            buffer = ctypes.create_string_buffer(size.value)
            result = self.pdh.PdhGetFormattedCounterArrayW(self.counter, PDH_FMT_DOUBLE, ctypes.byref(size), ctypes.byref(count), buffer)
            if (result & 0xFFFFFFFF) == PDH_MORE_DATA:
                continue  # Zwischendurch sind neue Instanzen dazugekommen, nochmal
            if result != 0:
                return []

            items = ctypes.cast(buffer, ctypes.POINTER(_PDH_FMT_COUNTERVALUE_ITEM_W))
            # Namen zeigen in den Puffer, deshalb hier sofort in Python-Strings kopieren
            return [
                (items[i].szName, items[i].FmtValue.doubleValue)
                for i in range(count.value)
                if items[i].FmtValue.CStatus in (PDH_CSTATUS_VALID_DATA, PDH_CSTATUS_NEW_DATA)
            ]

    def read(self):
        """Gibt die GPU-Auslastung in Prozent zurück (wie im Task-Manager) oder None."""
        if self.pdh.PdhCollectQueryData(self.query) != 0:
            return None

        items = self._read_items()

        # Wie der Task-Manager: je Grafikkarte und Engine-Typ (3D, Video Decode, Copy ...)
        # die Werte aller Programme addieren, dann den höchsten Engine-Typ nehmen
        totals = {}
        for name, value in items:
            match = INSTANCE_PATTERN.search(name or "")
            if not match:
                continue
            key = match.groups()
            totals[key] = totals.get(key, 0.0) + value

        if not totals:
            return None

        usage = min(100.0, max(totals.values()))
        if not self._reported:
            print(f"Systemmonitor: GPU über PDH, {len(items)} Instanzen, Auslastung {usage:.1f} %")
            self._reported = True
        return usage


# ---------------------------------------------------------------------------------------------------------
# Hintergrund-Thread
# ---------------------------------------------------------------------------------------------------------

class SystemMonitor:
    def __init__(self):
        self._lock = threading.Lock()
        self._values = {"cpu": None, "gpu": None, "ram": None, "ram_used_gb": None, "ram_total_gb": None}

        thread = threading.Thread(target=self._run, daemon=True)
        thread.start()

    def get_values(self):
        with self._lock:
            return dict(self._values)

    def _run(self):
        gpu = None
        if sys.platform == "win32":
            try:
                gpu = GpuReader()
            except Exception as e:
                print(f"Systemmonitor: GPU nicht auslesbar: {e}")

        # Erster Aufruf liefert immer 0, er startet nur die Messung
        psutil.cpu_percent(interval=None)

        while True:
            time.sleep(UPDATE_INTERVAL_S)

            values = {}
            try:
                values["cpu"] = psutil.cpu_percent(interval=None)
                memory = psutil.virtual_memory()
                values["ram"] = memory.percent
                values["ram_used_gb"] = (memory.total - memory.available) / 1024 ** 3
                values["ram_total_gb"] = memory.total / 1024 ** 3
            except Exception as e:
                print(f"Systemmonitor: CPU/RAM nicht auslesbar: {e}")

            if gpu is not None:
                try:
                    values["gpu"] = gpu.read()
                except Exception as e:
                    print(f"Systemmonitor: Fehler beim Lesen der GPU: {e}")
                    values["gpu"] = None

            with self._lock:
                self._values.update(values)
