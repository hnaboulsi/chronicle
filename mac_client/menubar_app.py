"""
Life Manager — macOS Menu Bar App
Starts the backend server automatically and runs the activity tracker.
Click the icon in the menu bar to control everything.
"""
import sys
import os

# Ensure venv packages (rumps, requests, etc.) are importable regardless of
# how this script is launched (terminal, launchd, open -a Python.app, etc.)
_here = os.path.dirname(os.path.abspath(__file__))
for _sp in os.listdir(os.path.join(_here, "venv", "lib")):
    _site = os.path.join(_here, "venv", "lib", _sp, "site-packages")
    if os.path.isdir(_site) and _site not in sys.path:
        sys.path.insert(0, _site)

import rumps
import threading
import requests
import subprocess

_CATEGORY_ICONS = {
    "studying":      "📚",
    "working":       "💼",
    "entertainment": "🎬",
    "social_media":  "📲",
    "gaming":        "🎮",
    "creative":      "🎨",
    "break":         "☕",
    "idle":          "💤",
}

sys.path.insert(0, _here)
import tracker
import notifier

# ── Config files ─────────────────────────────────────────────────────────────
_CONFIG_DIR  = os.path.expanduser("~/.config/life-manager")
_URL_FILE    = os.path.join(_CONFIG_DIR, "backend.url")
_AUTH_FILE   = os.path.join(_CONFIG_DIR, "auth")   # format: username:password


def _load_backend_url() -> str:
    if os.path.isfile(_URL_FILE):
        url = open(_URL_FILE).read().strip()
        if url:
            return url.rstrip("/")
    return os.environ.get("LIFE_MANAGER_BACKEND", "http://localhost:8000")


def _load_auth():
    """Return (user, pass) tuple or None if not configured."""
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


BACKEND_URL  = _load_backend_url()
_USING_REMOTE = not BACKEND_URL.startswith("http://localhost") and \
                not BACKEND_URL.startswith("http://127.")

# Single requests.Session so auth + keep-alive work across all calls
_session = requests.Session()
_auth = _load_auth()
if _auth:
    _session.auth = _auth

BACKEND_DIR    = os.path.normpath(os.path.join(_here, "..", "backend"))
BACKEND_PYTHON = os.path.join(BACKEND_DIR, "venv", "bin", "python")


class LifeManagerApp(rumps.App):
    def __init__(self):
        super().__init__("🧠", quit_button=None)

        self.tracking_enabled    = True
        self._stop_event         = threading.Event()
        self._backend_proc       = None
        self._last_notified_callout = ""

        # --- Status items (non-clickable info lines) ---
        self.backend_item  = rumps.MenuItem("⚙️  Backend: Starting...")
        self.tracking_item = rumps.MenuItem("📡  Tracking: —")

        # --- Action items ---
        self.toggle_item    = rumps.MenuItem("Pause Tracking",   callback=self.toggle_tracking)
        self.dashboard_item = rumps.MenuItem("Open Dashboard",   callback=self.open_dashboard)
        self.connect_item   = rumps.MenuItem("Set Backend URL…", callback=self.set_backend_url)
        self.quit_item      = rumps.MenuItem("Quit Life Manager", callback=self.quit_app)

        self.menu = [
            self.backend_item,
            self.tracking_item,
            None,
            self.toggle_item,
            self.dashboard_item,
            self.connect_item,
            None,
            self.quit_item,
        ]

        threading.Thread(target=self._startup, daemon=True).start()

        rumps.Timer(self._refresh_status, 30).start()
        rumps.Timer(self._check_callout, 300).start()

    # ── Startup ───────────────────────────────────────────────────────────────
    def _startup(self):
        self._start_backend()
        self._tracker_loop()

    def _start_backend(self):
        """Launch the FastAPI backend if not already running (local only)."""
        try:
            _session.get(f"{BACKEND_URL}/api/settings", timeout=2.0)
            self.backend_item.title = "⚙️  Backend: Running ✅"
            return
        except Exception:
            pass

        if _USING_REMOTE:
            self.backend_item.title = "⚙️  Backend: Offline ❌"
            print(f"Remote backend at {BACKEND_URL} is unreachable.")
            return

        try:
            self._backend_proc = subprocess.Popen(
                [BACKEND_PYTHON, "main.py"],
                cwd=BACKEND_DIR,
                stdout=open("/tmp/lifemanager_backend.out", "w"),
                stderr=open("/tmp/lifemanager_backend.err", "w"),
            )
        except Exception as e:
            self.backend_item.title = "⚙️  Backend: Error ❌"
            print(f"Failed to start backend: {e}")
            return

        for _ in range(12):
            if self._stop_event.is_set():
                return
            try:
                _session.get(f"{BACKEND_URL}/api/settings", timeout=1.0)
                self.backend_item.title = "⚙️  Backend: Running ✅"
                return
            except Exception:
                self._stop_event.wait(1)

        self.backend_item.title = "⚙️  Backend: Offline ❌"

    # ── Tracker loop ──────────────────────────────────────────────────────────
    def _tracker_loop(self):
        poll_interval = 60.0

        while not self._stop_event.is_set():
            try:
                resp = _session.get(f"{BACKEND_URL}/api/settings", timeout=2.0)
                if resp.status_code == 200:
                    data = resp.json()
                    poll_interval          = data.get("polling_interval_seconds", 60)
                    self.tracking_enabled  = data.get("tracking_enabled", True)
                    self.backend_item.title  = "⚙️  Backend: Running ✅"
                    self.tracking_item.title = (
                        "📡  Tracking: ON ✅" if self.tracking_enabled else "📡  Tracking: Paused ⏸"
                    )
                    self.toggle_item.title = (
                        "Pause Tracking" if self.tracking_enabled else "Resume Tracking"
                    )
                elif resp.status_code == 401:
                    self.backend_item.title = "⚙️  Backend: Auth Error ❌"
            except Exception:
                self.backend_item.title = "⚙️  Backend: Offline ❌"
                self.tracking_item.title = "📡  Tracking: —"

            if not self.tracking_enabled:
                self._stop_event.wait(300)
                continue

            try:
                idle_time    = tracker.get_idle_time()
                app_name     = tracker.get_active_app()
                window_title = tracker.get_window_title(app_name)

                resp = _session.post(
                    f"{BACKEND_URL}/api/mac-telemetry",
                    json={
                        "app_name":           app_name,
                        "window_title":       window_title,
                        "idle_time_seconds":  idle_time,
                    },
                    timeout=2.0,
                )

                if resp.status_code == 200:
                    prompt = resp.json().get("prompt")
                    if prompt:
                        user_reply = notifier.prompt_user(prompt)
                        if user_reply and user_reply not in ("Canceled", "Error"):
                            _session.post(
                                f"{BACKEND_URL}/api/prompt-reply",
                                json={"reply": user_reply},
                                timeout=2.0,
                            )
            except Exception as e:
                print(f"Tracker error: {e}")

            self._stop_event.wait(poll_interval)

    # ── Status refresh ────────────────────────────────────────────────────────
    def _refresh_status(self, _):
        try:
            resp = _session.get(f"{BACKEND_URL}/api/settings", timeout=2.0)
            if resp.ok:
                enabled = resp.json().get("tracking_enabled", True)
                self.tracking_enabled    = enabled
                self.backend_item.title  = "⚙️  Backend: Running ✅"
                self.tracking_item.title = (
                    "📡  Tracking: ON ✅" if enabled else "📡  Tracking: Paused ⏸"
                )
                self.toggle_item.title = "Pause Tracking" if enabled else "Resume Tracking"
            else:
                self.backend_item.title = "⚙️  Backend: Offline ❌"
        except Exception:
            self.backend_item.title = "⚙️  Backend: Offline ❌"

        # Update menu bar icon with current detected activity
        try:
            state_resp = _session.get(f"{BACKEND_URL}/api/state", timeout=2.0)
            if state_resp.ok:
                cat = state_resp.json().get("current_activity_category", "")
                self.title = _CATEGORY_ICONS.get(cat, "🧠")
        except Exception:
            pass

    def _check_callout(self, _):
        """Send a macOS notification if the AI detected a distraction."""
        try:
            resp = _session.get(f"{BACKEND_URL}/api/callout", timeout=2.0)
            if resp.ok:
                data    = resp.json()
                callout = data.get("callout")
                if callout and callout != self._last_notified_callout:
                    self._last_notified_callout = callout
                    notifier.notify(callout, "Life Manager")
                elif not callout:
                    self._last_notified_callout = ""
        except Exception:
            pass

    # ── Menu callbacks ────────────────────────────────────────────────────────
    def toggle_tracking(self, _):
        new_state = not self.tracking_enabled
        try:
            _session.post(
                f"{BACKEND_URL}/api/settings",
                json={"tracking_enabled": new_state},
                timeout=2.0,
            )
            self.tracking_enabled    = new_state
            self.tracking_item.title = (
                "📡  Tracking: ON ✅" if new_state else "📡  Tracking: Paused ⏸"
            )
            self.toggle_item.title = "Pause Tracking" if new_state else "Resume Tracking"
        except Exception:
            pass

    def open_dashboard(self, _):
        subprocess.Popen(["open", f"{BACKEND_URL}/dashboard/index.html"])

    def set_backend_url(self, _):
        """Prompt the user to enter a new backend URL."""
        win = rumps.Window(
            message="Enter your backend URL\n(e.g. https://life-manager-agent-production.up.railway.app)",
            title="Set Backend URL",
            default_text=BACKEND_URL,
            ok="Save",
            cancel="Cancel",
            dimensions=(400, 24),
        )
        response = win.run()
        if response.clicked and response.text.strip():
            new_url = response.text.strip().rstrip("/")
            os.makedirs(_CONFIG_DIR, exist_ok=True)
            with open(_URL_FILE, "w") as f:
                f.write(new_url)
            notifier.notify(
                f"Backend set to {new_url}\nRestart Life Manager to apply.",
                "Life Manager",
            )

    def quit_app(self, _):
        self._stop_event.set()
        if self._backend_proc and self._backend_proc.poll() is None:
            self._backend_proc.terminate()
        rumps.quit_application()


if __name__ == "__main__":
    # Hide from Dock — menu bar apps should be invisible everywhere except the menu bar
    try:
        import AppKit
        AppKit.NSApp.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
    except Exception:
        pass

    LifeManagerApp().run()
