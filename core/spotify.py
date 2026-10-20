import base64
import hashlib
import json
import os
import queue
import secrets
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

# Spotify Web API: Warteschlange, Shuffle, Wiederholen und Spulen für Spotify.
# Anmeldung per "Authorization Code mit PKCE": kein Client Secret nötig, nur die Client ID der eigenen Spotify-App.
# Zugangsdaten liegen in data/spotify_token.json (nie ins Log oder ins Repo!).

REDIRECT_PORT = 8765
REDIRECT_URI = f"http://127.0.0.1:{REDIRECT_PORT}/callback"
SCOPES = "user-read-playback-state user-modify-playback-state user-read-currently-playing"
AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API_URL = "https://api.spotify.com/v1"
TOKEN_FILE = os.path.join("data", "spotify_token.json")

LOGIN_TIMEOUT_S = 180
PLAYER_POLL_S = 1.5
QUEUE_POLL_S = 15
PENDING_HOLD_S = 2.5   # so lange gilt ein gerade gesendeter Wert, auch wenn Spotify noch den alten meldet
TOKEN_REFRESH_MARGIN_S = 60
QUEUE_SIZE = 5
MAX_SKIPS = 20
SKIP_DELAY_S = 0.25

REPEAT_FROM_SPOTIFY = {"off": "off", "context": "list", "track": "track"}
REPEAT_TO_SPOTIFY = {"off": "off", "list": "context", "track": "track"}


class AuthLost(Exception):
    """Anmeldung ungültig (z. B. Zugriff in Spotify widerrufen): neu verbinden nötig."""


class RateLimited(Exception):
    def __init__(self, retry_after):
        super().__init__(f"Zu viele Anfragen, warte {retry_after} s")
        self.retry_after = retry_after


class ApiError(Exception):
    def __init__(self, status, message=""):
        super().__init__(f"Fehler {status} {message}".strip())
        self.status = status


# ---------------------------------------------------------------------------------------------------------
# Reine Hilfsfunktionen (auf dem Server testbar)
# ---------------------------------------------------------------------------------------------------------

def pkce_challenge(verifier):
    """SHA-256 des Verifiers, Base64 für URLs, ohne '=' am Ende (RFC 7636)."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def make_pkce_pair():
    verifier = secrets.token_urlsafe(64)  # 86 Zeichen, erlaubt sind 43 bis 128
    return verifier, pkce_challenge(verifier)


def build_auth_url(client_id, challenge, state):
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
        "scope": SCOPES,
        "state": state,
    }
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"


def track_info(item):
    """Titel/Interpret aus einem Spotify-Objekt (Lied oder Podcast-Folge)."""
    if not item:
        return None
    if item.get("type") == "episode":
        artist = (item.get("show") or {}).get("name", "")
    else:
        artist = ", ".join(a.get("name", "") for a in item.get("artists") or [])
    return {"uri": item.get("uri", ""), "title": item.get("name", ""), "artist": artist}


def queue_entries(data, limit=QUEUE_SIZE):
    entries = [track_info(item) for item in (data or {}).get("queue") or []]
    return [e for e in entries if e][:limit]


def plan_skips(queue_uris, target_uri, current_uri):
    """Wie oft "Weiter" gedrückt werden muss, bis target_uri läuft. None = nicht in der Warteschlange."""
    if current_uri == target_uri:
        return 0
    if target_uri not in queue_uris:
        return None
    skips = queue_uris.index(target_uri) + 1
    return skips if skips <= MAX_SKIPS else None


def apply_spotify(state, sp):
    """Ergänzt den Windows-Stand um das, was nur Spotify selbst weiß (Shuffle, Wiederholen, Spulen)."""
    merged = dict(state)
    merged["via_spotify"] = False
    merged["seek_via_spotify"] = False
    merged["smart_shuffle"] = False
    if not (state.get("active") and state.get("app") == "Spotify" and sp.get("connected") and sp.get("player")):
        return merged

    disallows = sp.get("disallows") or set()
    merged["via_spotify"] = True
    merged["shuffle"] = sp["shuffle"]
    merged["smart_shuffle"] = sp["smart_shuffle"]
    merged["repeat"] = sp["repeat"]
    merged["can_shuffle"] = "toggling_shuffle" not in disallows
    merged["can_repeat"] = not ("toggling_repeat_context" in disallows and "toggling_repeat_track" in disallows)

    # Liefert Windows keine Zeitleiste oder kein Spulen, nehmen wir die von Spotify
    if state["duration"] <= 0 or not state["can_seek"]:
        merged["duration"] = sp["duration"]
        merged["base_position"] = sp["progress"]
        merged["base_time"] = sp["sample_time"]
        merged["playing"] = sp["is_playing"]
        merged["can_seek"] = sp["duration"] > 0 and "seeking" not in disallows
        merged["seek_via_spotify"] = True
    return merged


# ---------------------------------------------------------------------------------------------------------
# Zugangsdaten
# ---------------------------------------------------------------------------------------------------------

def load_tokens():
    try:
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            tokens = json.load(f)
        if tokens.get("refresh_token") and tokens.get("client_id"):
            return tokens
    except (OSError, ValueError):
        pass
    return None


def save_tokens(tokens):
    os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
    temp = TOKEN_FILE + ".tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(tokens, f)
    os.replace(temp, TOKEN_FILE)  # erst komplett schreiben, dann tauschen: nie eine halbe Datei


def delete_tokens():
    try:
        os.remove(TOKEN_FILE)
    except OSError:
        pass


def _post_form(url, fields, opener):
    body = urllib.parse.urlencode(fields).encode("ascii")
    request = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
    with opener(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _tokens_from_response(data, client_id, old_refresh=None):
    return {
        "client_id": client_id,
        "access_token": data["access_token"],
        # Spotify schickt manchmal einen neuen Refresh-Token mit, dann gilt nur noch der neue
        "refresh_token": data.get("refresh_token") or old_refresh,
        "expires_at": time.time() + int(data.get("expires_in", 3600)),
    }


def exchange_code(client_id, code, verifier, opener=urllib.request.urlopen):
    data = _post_form(TOKEN_URL, {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": client_id,
        "code_verifier": verifier,
    }, opener)
    return _tokens_from_response(data, client_id)


# ---------------------------------------------------------------------------------------------------------
# Anmeldung im Browser
# ---------------------------------------------------------------------------------------------------------

DONE_PAGE = """<!doctype html><html lang="de"><head><meta charset="utf-8"><title>Control Panel</title></head>
<body style="font-family:Segoe UI,Helvetica,sans-serif;background:#121220;color:#E0E0F0;display:flex;
align-items:center;justify-content:center;height:100vh;margin:0"><div style="text-align:center">
<h2>{title}</h2><p style="color:#8888AA">{text}</p></div></body></html>"""


class _CallbackServer(HTTPServer):
    # Pythons Standard (Port wiederverwenden) erlaubt unter Windows einen ZWEITEN Server auf demselben Port.
    # Dann fängt womöglich ein anderes Programm die Antwort ab. Deshalb unter Windows: Port exklusiv belegen.
    # Unter Linux/macOS ist Wiederverwenden harmlos (dort lauschen trotzdem nie zwei Server gleichzeitig).
    allow_reuse_address = not hasattr(socket, "SO_EXCLUSIVEADDRUSE")

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):  # nur unter Windows vorhanden
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_error(404)
            return
        login = _current_login
        if login is None:
            title, text = "Anmeldung abgelaufen", "Bitte im Control Panel nochmal auf „Im Browser anmelden“ tippen."
        else:
            title, text = login._handle_callback(urllib.parse.parse_qs(parsed.query))
        page = DONE_PAGE.format(title=title, text=text).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        self.wfile.write(page)

    def log_message(self, *args):
        pass  # Die Anfrage-URL enthält den Anmelde-Code: nicht ins Log schreiben


# Ein einziger Rückweg-Server für die ganze Laufzeit des Programms. Er wird beim ersten Anmelden gestartet
# und reicht jede Antwort an die gerade laufende Anmeldung weiter. So muss der Port nie neu belegt werden
# (das Betriebssystem sperrt ihn nach dem Schließen noch eine Weile).
_server = None
_current_login = None
_lock = threading.Lock()


def _ensure_server():
    global _server
    if _server is None:
        server = _CallbackServer(("127.0.0.1", REDIRECT_PORT), _CallbackHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        _server = server


class SpotifyLogin:
    """Ein Anmeldeversuch. Es zählt immer nur der neueste: ein neuer Versuch macht ältere ungültig."""

    def __init__(self, client_id, opener=urllib.request.urlopen):
        self.client_id = client_id.strip()
        self.opener = opener
        self.verifier, challenge = make_pkce_pair()
        self.state = secrets.token_urlsafe(16)  # Schutz: nur die Antwort auf genau diesen Versuch wird angenommen
        self.url = build_auth_url(self.client_id, challenge, self.state)
        self.status = "waiting"  # waiting / ok / error / cancelled
        self.message = ""
        self.tokens = None
        self._busy = threading.Lock()

    def start(self):
        global _current_login
        with _lock:
            try:
                _ensure_server()
            except OSError:
                self._finish("error", f"Port {REDIRECT_PORT} ist belegt. Läuft das Control Panel zweimal? "
                                      f"Dann im Task-Manager alle \"pythonw.exe\" beenden, sonst kurz warten.")
                return False
            if _current_login is not None and _current_login.status == "waiting":
                _current_login._finish("cancelled")
            _current_login = self

        timer = threading.Timer(LOGIN_TIMEOUT_S, self._timeout)
        timer.daemon = True
        timer.start()
        return True

    def _timeout(self):
        if self.status == "waiting":
            self._finish("error", "Zeit abgelaufen, bitte nochmal versuchen.")

    def _finish(self, status, message=""):
        self.message = message
        self.status = status
        if message:
            print(f"Spotify: Anmeldung {status}: {message}")

    def _handle_callback(self, params):
        # Lock: falls der Browser die Seite doppelt aufruft, den Code nur einmal eintauschen
        with self._busy:
            if self.status == "ok":
                return "Spotify verbunden", "Du kannst dieses Fenster schließen."
            if self.status != "waiting":
                return "Anmeldung abgelaufen", "Bitte im Control Panel nochmal auf „Im Browser anmelden“ tippen."
            if params.get("state", [""])[0] != self.state:
                print("Spotify: Antwort mit fremdem state verworfen")
                return ("Veraltete Anmeldung",
                        "Diese Antwort gehört zu einem älteren Anmeldeversuch. "
                        "Bitte im Control Panel nochmal auf „Im Browser anmelden“ tippen.")
            if "error" in params:
                reason = params["error"][0]
                self._finish("error", "Anmeldung abgebrochen." if reason == "access_denied" else f"Spotify meldet: {reason}")
                return "Nicht verbunden", self.message
            code = params.get("code", [""])[0]
            try:
                self.tokens = exchange_code(self.client_id, code, self.verifier, self.opener)
                save_tokens(self.tokens)
            except urllib.error.HTTPError as e:
                self._finish("error", f"Spotify lehnt die Anmeldung ab (Fehler {e.code}). Stimmen Client ID und Redirect URI?")
                return "Nicht verbunden", self.message
            except Exception as e:
                self._finish("error", f"Anmeldung fehlgeschlagen: {type(e).__name__}")
                return "Nicht verbunden", self.message
            self._finish("ok")
            print("Spotify: verbunden")
            return "Spotify verbunden", "Du kannst dieses Fenster schließen."


# ---------------------------------------------------------------------------------------------------------
# Web API
# ---------------------------------------------------------------------------------------------------------

class SpotifyApi:
    def __init__(self, tokens, opener=urllib.request.urlopen):
        self.tokens = tokens
        self.opener = opener

    def refresh(self):
        try:
            data = _post_form(TOKEN_URL, {
                "grant_type": "refresh_token",
                "refresh_token": self.tokens["refresh_token"],
                "client_id": self.tokens["client_id"],
            }, self.opener)
        except urllib.error.HTTPError as e:
            if e.code in (400, 401):
                raise AuthLost()
            raise ApiError(e.code, "beim Erneuern")
        self.tokens = _tokens_from_response(data, self.tokens["client_id"], self.tokens["refresh_token"])
        save_tokens(self.tokens)

    def request(self, method, path, params=None, retry=True):
        """Gibt die JSON-Antwort zurück, oder None bei leerer Antwort (z. B. 204 = nichts aktiv)."""
        if time.time() > self.tokens.get("expires_at", 0) - TOKEN_REFRESH_MARGIN_S:
            self.refresh()

        url = API_URL + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        # POST/PUT brauchen einen (leeren) Inhalt, sonst antwortet Spotify mit 411
        body = b"" if method in ("POST", "PUT") else None
        request = urllib.request.Request(url, data=body, method=method,
                                         headers={"Authorization": f"Bearer {self.tokens['access_token']}"})
        try:
            with self.opener(request, timeout=10) as response:
                raw = response.read()
        except urllib.error.HTTPError as e:
            if e.code == 401 and retry:
                self.refresh()
                return self.request(method, path, params, retry=False)
            if e.code == 429:
                raise RateLimited(int(e.headers.get("Retry-After", "2") or 2))
            raise ApiError(e.code, path)
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            return None


# ---------------------------------------------------------------------------------------------------------
# Hintergrund-Thread
# ---------------------------------------------------------------------------------------------------------

EMPTY_SPOTIFY = {
    "connected": False,
    "player": False,       # Gibt es gerade eine Wiedergabe in Spotify?
    "is_playing": False,
    "track_uri": "",
    "duration": 0.0,
    "progress": 0.0,
    "sample_time": 0.0,
    "shuffle": False,
    "smart_shuffle": False,
    "repeat": "off",
    "disallows": set(),
    "queue": [],
}


class SpotifyClient:
    def __init__(self, opener=urllib.request.urlopen, start_thread=True):
        self.opener = opener
        self._lock = threading.Lock()
        self._state = dict(EMPTY_SPOTIFY)
        self._pending = {}
        self._commands = queue.Queue()
        self._active = False
        self._api = None
        self._next_player_poll = 0.0
        self._next_queue_poll = 0.0
        self._blocked_until = 0.0
        self._last_error = None

        tokens = load_tokens()
        if tokens:
            self._api = SpotifyApi(tokens, opener)
            self._state["connected"] = True

        if start_thread:
            threading.Thread(target=self._run, daemon=True).start()

    # ---- Schnittstelle für die Oberfläche ----

    def set_active(self, active):
        """Nur abfragen, während Spotify wirklich die laufende Wiedergabe ist (schont das Anfrage-Kontingent)."""
        if active and not self._active:
            self._next_player_poll = 0.0
            self._next_queue_poll = 0.0
        self._active = active

    def get_state(self):
        now = time.monotonic()
        with self._lock:
            state = dict(self._state)
            for key, (value, until) in list(self._pending.items()):
                if now > until or state.get(key) == value:
                    del self._pending[key]
                else:
                    state[key] = value
        return state

    def patch(self, **values):
        """Sofort anzeigen, was gerade gesendet wurde, bis Spotify es bestätigt."""
        until = time.monotonic() + PENDING_HOLD_S
        with self._lock:
            for key, value in values.items():
                self._pending[key] = (value, until)
            if "progress" in values:
                self._pending["sample_time"] = (time.monotonic(), until)

    def command(self, name, value=None):
        self._commands.put((name, value))

    def login_finished(self):
        tokens = load_tokens()
        if tokens:
            self._api = SpotifyApi(tokens, self.opener)
            with self._lock:
                self._state["connected"] = True
            self._next_player_poll = 0.0
            self._next_queue_poll = 0.0

    # ---- Worker-Thread ----

    def _run(self):
        while True:
            try:
                name, value = self._commands.get(timeout=0.25)
                self._guarded(self._run_command, name, value)
            except queue.Empty:
                pass

            now = time.monotonic()
            if not self._active or self._api is None or now < self._blocked_until:
                continue
            if now >= self._next_player_poll:
                self._next_player_poll = now + PLAYER_POLL_S
                self._guarded(self._poll_player)
            if now >= self._next_queue_poll:
                self._next_queue_poll = now + QUEUE_POLL_S
                self._guarded(self._poll_queue)

    def _guarded(self, function, *args):
        try:
            function(*args)
            self._last_error = None
        except AuthLost:
            print("Spotify: Anmeldung nicht mehr gültig, bitte neu verbinden")
            delete_tokens()
            self._api = None
            with self._lock:
                self._state = dict(EMPTY_SPOTIFY)
        except RateLimited as e:
            print(f"Spotify: {e}")
            self._blocked_until = time.monotonic() + e.retry_after
        except Exception as e:
            message = f"{type(e).__name__}: {e}"
            if message != self._last_error:  # gleiche Fehler nicht ständig wiederholen
                print(f"Spotify: {message}")
                self._last_error = message

    def _poll_player(self):
        data = self._api.request("GET", "/me/player")
        if not data or not data.get("item"):
            with self._lock:
                self._state.update(player=False, queue=[])
            return

        item = data["item"]
        uri = item.get("uri", "")
        update = {
            "player": True,
            "is_playing": bool(data.get("is_playing")),
            "track_uri": uri,
            "duration": (item.get("duration_ms") or 0) / 1000,
            "progress": (data.get("progress_ms") or 0) / 1000,
            "sample_time": time.monotonic(),
            "shuffle": bool(data.get("shuffle_state")),
            "smart_shuffle": bool(data.get("smart_shuffle")),
            "repeat": REPEAT_FROM_SPOTIFY.get(data.get("repeat_state"), "off"),
            "disallows": {k for k, v in ((data.get("actions") or {}).get("disallows") or {}).items() if v},
        }
        with self._lock:
            track_changed = uri != self._state["track_uri"]
            self._state.update(update)
        if track_changed:
            self._next_queue_poll = 0.0  # neues Lied: Warteschlange sofort neu holen

    def _poll_queue(self):
        data = self._api.request("GET", "/me/player/queue")
        with self._lock:
            self._state["queue"] = queue_entries(data)

    def _run_command(self, name, value):
        if self._api is None:
            return
        if name == "shuffle":
            self._api.request("PUT", "/me/player/shuffle", {"state": "true" if value else "false"})
        elif name == "repeat":
            self._api.request("PUT", "/me/player/repeat", {"state": REPEAT_TO_SPOTIFY[value]})
        elif name == "seek":
            self._api.request("PUT", "/me/player/seek", {"position_ms": int(value * 1000)})
        elif name == "jump":
            self._jump_to(value)
        self._next_player_poll = 0.0

    def _jump_to(self, target_uri):
        """Spotify kennt kein "spiel Lied Nr. 3 der Warteschlange": also so oft weiter, bis es dran ist."""
        data = self._api.request("GET", "/me/player/queue") or {}
        current = (data.get("currently_playing") or {}).get("uri", "")
        uris = [item.get("uri", "") for item in data.get("queue") or []]
        skips = plan_skips(uris, target_uri, current)
        if not skips:
            return
        for _ in range(skips):
            self._api.request("POST", "/me/player/next")
            time.sleep(SKIP_DELAY_S)
        self._next_queue_poll = 0.0
