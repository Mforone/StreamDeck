import comtypes
from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume, IAudioEndpointVolume
from comtypes import CLSCTX_ALL

# Blacklist für Prozesse, die NIEMALS im Mixer-Dropdown erscheinen sollen.
# Prozesstitel einfach in Kleinschreibung (ohne .exe) eintragen:
APP_BLACKLIST = {
    "system",
    "audiodg",
    "svchost",
    "systemsettings",
    "idle",
    "shellexperiencehost",
    "msedgewebview2",
    "mscopilot"
}


def ensure_com():
    """Stellt sicher, dass der aktuelle Thread für COM/Windows-Audio initialisiert ist."""
    try:
        comtypes.CoInitialize()
    except Exception:
        pass


class AudioManager:
    @staticmethod
    def get_master_volume_control():
        ensure_com()
        try:
            device = AudioUtilities.GetSpeakers()
            if device is None:
                return None

            if hasattr(device, "EndpointVolume"):
                return device.EndpointVolume

            if hasattr(device, "Activate"):
                interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                return interface.QueryInterface(IAudioEndpointVolume)

            if hasattr(device, "_ctl"):
                return device._ctl.QueryInterface(IAudioEndpointVolume)

        except Exception as e:
            print(f"Fehler beim Abrufen des Master-Volume-Controls: {e}")
            return None

    @staticmethod
    def set_volume(process_name: str, volume_level: float):
        ensure_com()
        try:
            if process_name == "master":
                master_volume = AudioManager.get_master_volume_control()
                if master_volume:
                    master_volume.SetMasterVolumeLevelScalar(max(0.0, min(1.0, volume_level)), None)
                return

            sessions = AudioUtilities.GetAllSessions()
            for session in sessions:
                if session.Process and session.Process.name().lower() == process_name.lower():
                    volume = session._ctl.QueryInterface(ISimpleAudioVolume)
                    volume.SetMasterVolume(max(0.0, min(1.0, volume_level)), None)
        except Exception as e:
            print(f"Fehler beim Setzen der Lautstärke ({process_name}): {e}")

    @staticmethod
    def get_volume(process_name: str) -> float:
        ensure_com()
        try:
            if process_name == "master":
                master_volume = AudioManager.get_master_volume_control()
                if master_volume:
                    return float(master_volume.GetMasterVolumeLevelScalar())
                return 0.8

            sessions = AudioUtilities.GetAllSessions()
            for session in sessions:
                if session.Process and session.Process.name().lower() == process_name.lower():
                    volume = session._ctl.QueryInterface(ISimpleAudioVolume)
                    return float(volume.GetMasterVolume())
        except Exception:
            pass
        return 0.5

    @staticmethod
    def set_mute(process_name: str, mute: bool):
        ensure_com()
        try:
            if process_name == "master":
                master_volume = AudioManager.get_master_volume_control()
                if master_volume:
                    master_volume.SetMute(mute, None)
                return

            sessions = AudioUtilities.GetAllSessions()
            for session in sessions:
                if session.Process and session.Process.name().lower() == process_name.lower():
                    volume = session._ctl.QueryInterface(ISimpleAudioVolume)
                    volume.SetMute(mute, None)
        except Exception as e:
            print(f"Fehler beim Muten ({process_name}): {e}")

    @staticmethod
    def get_mute(process_name: str) -> bool:
        ensure_com()
        try:
            if process_name == "master":
                master_volume = AudioManager.get_master_volume_control()
                if master_volume:
                    return bool(master_volume.GetMute())
                return False

            sessions = AudioUtilities.GetAllSessions()
            for session in sessions:
                if session.Process and session.Process.name().lower() == process_name.lower():
                    volume = session._ctl.QueryInterface(ISimpleAudioVolume)
                    return bool(volume.GetMute())
        except Exception:
            pass
        return False

    @staticmethod
    def get_active_sessions():
        """Gibt gefilterte Audio-Sessions zurück (ohne Blacklist-Einträge & nur aktive Tonquellen)."""
        ensure_com()
        try:
            sessions = AudioUtilities.GetAllSessions()
            active_apps = []
            for session in sessions:
                if session.Process:
                    full_name = session.Process.name()
                    clean_name = full_name[:-4] if full_name.lower().endswith(".exe") else full_name

                    # 1. Blacklist-Prüfung
                    if clean_name.lower() in APP_BLACKLIST:
                        continue

                    # 2. Session-State Prüfung (State == 1 bedeutet AudioSessionStateActive)
                    try:
                        state = session._ctl.GetState()
                        if state != 1:  # Ignoriere inaktive/abgelaufene Sessions
                            continue
                    except Exception:
                        pass

                    # 3. Audio-Peak Prüfung mit höherem Schwellenwert (>= 1%)
                    has_audio = False
                    try:
                        meter = session._ctl.QueryInterface(comtypes.gen.AudioControlLib.IAudioMeterInformation)
                        peak = meter.GetPeakValue()
                        if peak >= 0.01:  # Mindestens 1% Signalpegel
                            has_audio = True
                    except Exception:
                        # Fallback: Falls Meter-Information nicht abrufbar ist
                        has_audio = True

                    if has_audio:
                        display_name = f"{clean_name} ({session.ProcessId})"
                        active_apps.append({
                            "name": display_name,
                            "process_name": full_name,
                            "pid": session.ProcessId
                        })
            return active_apps
        except Exception as e:
            print(f"Fehler beim Abrufen der aktiven Audio-Sessions: {e}")
            return []