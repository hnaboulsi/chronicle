"""
Life Manager macOS menu bar app.
Railway-first mode with watchdog and optional status window.
"""
import json
import os
import subprocess
import sys
import threading
import time
import webbrowser

_here = os.path.dirname(os.path.abspath(__file__))
for _sp in os.listdir(os.path.join(_here, "venv", "lib")):
    _site = os.path.join(_here, "venv", "lib", _sp, "site-packages")
    if os.path.isdir(_site) and _site not in sys.path:
        sys.path.insert(0, _site)

import requests
import rumps

sys.path.insert(0, _here)
import notifier
import tracker

_CONFIG_DIR = os.path.expanduser("~/.config/life-manager")
_URL_FILE = os.path.join(_CONFIG_DIR, "backend.url")
_AUTH_FILE = os.path.join(_CONFIG_DIR, "auth")
_CLIENT_FILE = os.path.join(_CONFIG_DIR, "client.json")

DEFAULT_CLIENT_CONFIG = {
    "show_status_window_on_launch": False,
    "recreate_status_icon_on_focus_loss": True,
    "railway_health_check_interval_seconds": 30,
}

CATEGORY_ICONS = {
    "studying": "📚",
    "working": "💼",
    "entertainment": "🎬",
    "social_media": "📲",
    "gaming": "🎮",
    "creative": "🎨",
    "break": "☕",
    "idle": "💤",
}


def _load_backend_url() -> str:
    if os.path.isfile(_URL_FILE):
        url = open(_URL_FILE).read().strip()
        if url:
            return url.rstrip("/")
    env_url = os.environ.get("LIFE_MANAGER_BACKEND", "").strip()
    if env_url:
        return env_url.rstrip("/")
    return "http://localhost:8000"


def _load_auth():
    if os.path.isfile(_AUTH_FILE):
        line = open(_AUTH_FILE).read().strip()
        if ":" in line:
            u, _, p = line.partition(":")
            return (u, p)
    u = os.environ.get("LIFE_MANAGER_USER", "")
    p = os.environ.get("LIFE_MANAGER_PASS", "")
    if u and p:
        return (u, p)
    return None


def _load_client_config():
    data = DEFAULT_CLIENT_CONFIG.copy()
    if os.path.isfile(_CLIENT_FILE):
        try:
            with open(_CLIENT_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            for k in DEFAULT_CLIENT_CONFIG:
                if k in raw:
                    data[k] = raw[k]
        except Exception:
            pass
    return data


BACKEND_URL = _load_backend_url()
USING_REMOTE = not BACKEND_URL.startswith("http://localhost") and not BACKEND_URL.startswith("http://127.")
CLIENT_CONFIG = _load_client_config()

session = requests.Session()
auth = _load_auth()
if auth:
    session.auth = auth


class StatusWindow:
    """Show status via a native macOS dialog (tkinter crashes rumps on macOS)."""

    def __init__(self, app):
        self.app = app

    def start(self):
        status = self.app.last_status
        lines = [
            f"Backend: {status.get('backend', 'Unknown')}",
            f"Tracking: {status.get('tracking', 'Unknown')}",
            f"Last telemetry: {status.get('last_send', 'never')}",
            f"Sleep detection: {status.get('sleep_note', 'waiting for iPhone pings')}",
        ]
        rumps.alert(
            title="Life Manager Status",
            message="\n".join(lines),
            ok="OK",
        )


class LifeManagerApp(rumps.App):
    def __init__(self):
        super().__init__("🧠", quit_button=None)
        self.tracking_enabled = True
        self.stop_event = threading.Event()
        self.last_status = {
            "backend": "Starting...",
            "tracking": "—",
            "last_send": "never",
            "sleep_note": "waiting for iPhone pings",
        }

        self.backend_item = rumps.MenuItem("⚙️  Backend: Starting...")
        self.tracking_item = rumps.MenuItem("📡  Tracking: —")
        self.toggle_item = rumps.MenuItem("Pause Tracking", callback=self.toggle_tracking)
        self.dashboard_item = rumps.MenuItem("Open Dashboard", callback=self.open_dashboard)
        self.status_item = rumps.MenuItem("Open Status Window", callback=self.open_status_window)
        self.connect_item = rumps.MenuItem("Set Backend URL…", callback=self.set_backend_url)
        self.restart_item = rumps.MenuItem("Restart Agent", callback=self.restart_menu_icon)
        self.quit_item = rumps.MenuItem("Quit Life Manager", callback=self.quit_app)

        self.menu = [
            self.backend_item,
            self.tracking_item,
            None,
            self.toggle_item,
            self.dashboard_item,
            self.status_item,
            self.connect_item,
            self.restart_item,
            None,
            self.quit_item,
        ]

        self._chrome_cache: list = []
        self._chrome_cache_time: float = 0.0
        self._last_callout: str = ""

        self.status_window = StatusWindow(self)
        if CLIENT_CONFIG.get("show_status_window_on_launch", False):
            self.status_window.start()

        threading.Thread(target=self._tracker_loop, daemon=True).start()
        interval = int(CLIENT_CONFIG.get("railway_health_check_interval_seconds", 30))
        rumps.Timer(self._refresh_status, max(10, interval)).start()
        rumps.Timer(self._send_heartbeat, 60).start()
        rumps.Timer(self._watchdog, 60).start()

    def _health_ok(self):
        try:
            resp = session.get(f"{BACKEND_URL}/api/healthz", timeout=3)
            return resp.status_code == 200, resp.json() if resp.ok else {}
        except Exception:
            return False, {}

    def _tracker_loop(self):
        poll_interval = 60.0
        while not self.stop_event.is_set():
            ok, _ = self._health_ok()
            if not ok:
                self.backend_item.title = "⚙️  Backend: Offline ❌"
                self.last_status["backend"] = "Offline"
                self.stop_event.wait(10)
                continue

            self.backend_item.title = "⚙️  Backend: Running ✅"
            self.last_status["backend"] = "Running"

            try:
                settings = session.get(f"{BACKEND_URL}/api/settings", timeout=3)
                if settings.ok:
                    data = settings.json()
                    poll_interval = data.get("polling_interval_seconds", 60)
                    self.tracking_enabled = data.get("tracking_enabled", True)
            except Exception:
                pass

            self.tracking_item.title = "📡  Tracking: ON ✅" if self.tracking_enabled else "📡  Tracking: Paused ⏸"
            self.last_status["tracking"] = "ON" if self.tracking_enabled else "Paused"
            self.toggle_item.title = "Pause Tracking" if self.tracking_enabled else "Resume Tracking"

            if not self.tracking_enabled:
                self.stop_event.wait(300)
                continue

            try:
                idle_time = tracker.get_idle_time()
                app_name = tracker.get_active_app()
                window_title = tracker.get_window_title(app_name)
                recent_history = []
                try:
                    now = time.time()
                    if now - self._chrome_cache_time >= 1800:  # 30-min throttle
                        self._chrome_cache = tracker.get_recent_chrome_history(minutes=30)
                        self._chrome_cache_time = now
                    recent_history = self._chrome_cache
                except Exception:
                    pass
                resp = session.post(
                    f"{BACKEND_URL}/api/mac-telemetry",
                    json={
                        "app_name": app_name,
                        "window_title": window_title,
                        "idle_time_seconds": idle_time,
                        "recent_history": recent_history if recent_history else None,
                    },
                    timeout=3,
                )
                if resp.ok:
                    self.last_status["last_send"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    prompt = resp.json().get("prompt")
                    if prompt:
                        user_reply = notifier.prompt_user(prompt)
                        if user_reply and user_reply not in ("Canceled", "Error"):
                            session.post(f"{BACKEND_URL}/api/prompt-reply", json={"reply": user_reply}, timeout=3)
            except Exception as e:
                print(f"Tracker error: {e}")

            self.stop_event.wait(max(10, float(poll_interval)))

    def _refresh_status(self, _):
        try:
            st = session.get(f"{BACKEND_URL}/api/state", timeout=3)
            if st.ok:
                data = st.json()
                cat = data.get("current_activity_category", "")
                self.title = CATEGORY_ICONS.get(cat, "🧠")
                self.last_status["sleep_note"] = data.get("sleep_status_note", "waiting for iPhone pings")
                if data.get("service_health") == "offline":
                    self.backend_item.title = "⚙️  Backend: Offline ❌"
            callout_resp = session.get(f"{BACKEND_URL}/api/callout", timeout=3)
            if callout_resp.ok:
                callout = callout_resp.json().get("callout") or ""
                if callout and callout != self._last_callout:
                    self._last_callout = callout
                    notifier.notify(callout, "Life Manager")
                elif not callout:
                    self._last_callout = ""
        except Exception:
            self.backend_item.title = "⚙️  Backend: Offline ❌"

    def _watchdog(self, _):
        # If status icon title got blank unexpectedly, restore it.
        if CLIENT_CONFIG.get("recreate_status_icon_on_focus_loss", True) and not self.title:
            self.title = "🧠"
            notifier.notify("Recovered missing menu icon state.", "Life Manager")

    def _send_heartbeat(self, _):
        try:
            session.post(
                f"{BACKEND_URL}/api/mac-heartbeat",
                json={
                    "client_id": "python-menubar",
                    "app_version": "legacy-python",
                    "agent_state": "running" if self.tracking_enabled else "paused",
                    "tracking_enabled": self.tracking_enabled,
                    "permissions_state": "ok",
                    "last_error": "",
                },
                timeout=3,
            )
        except Exception:
            pass

    def toggle_tracking(self, _):
        new_state = not self.tracking_enabled
        try:
            session.post(f"{BACKEND_URL}/api/settings", json={"tracking_enabled": new_state}, timeout=3)
            self.tracking_enabled = new_state
        except Exception:
            pass

    def open_dashboard_url(self):
        webbrowser.open(f"{BACKEND_URL}/dashboard/index.html")

    def open_dashboard(self, _):
        self.open_dashboard_url()

    def open_status_window(self, _):
        self.status_window.start()

    def set_backend_url(self, _):
        win = rumps.Window(
            message="Enter your backend URL (Railway URL recommended)",
            title="Set Backend URL",
            default_text=BACKEND_URL,
            ok="Save",
            cancel="Cancel",
            dimensions=(420, 24),
        )
        response = win.run()
        if response.clicked and response.text.strip():
            os.makedirs(_CONFIG_DIR, exist_ok=True)
            with open(_URL_FILE, "w", encoding="utf-8") as f:
                f.write(response.text.strip().rstrip("/"))
            notifier.notify("Backend URL saved. Restart Life Manager to apply.", "Life Manager")

    def restart_agent(self):
        python = sys.executable
        os.execv(python, [python, os.path.abspath(__file__)])

    def restart_menu_icon(self, _):
        self.restart_agent()

    def quit_and_relaunch(self):
        subprocess.Popen([sys.executable, os.path.abspath(__file__)])
        self.quit_app(None)

    def quit_app(self, _):
        self.stop_event.set()
        rumps.quit_application()


if __name__ == "__main__":
    app = LifeManagerApp()
    try:
        import AppKit
        if AppKit.NSApp is not None:
            AppKit.NSApp.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
    except Exception:
        pass
    app.run()
