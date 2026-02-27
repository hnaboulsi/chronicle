"""
Life Manager — macOS Menu Bar App
Starts the backend server automatically and runs the activity tracker.
Click the 🧠 icon in the menu bar to control everything.
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

sys.path.insert(0, _here)
import tracker
import notifier

# Backend URL — override by writing a URL to ~/.config/life-manager/backend.url
# e.g.  echo "http://100.x.x.x:8000" > ~/.config/life-manager/backend.url
_CONFIG_FILE = os.path.expanduser("~/.config/life-manager/backend.url")
def _load_backend_url() -> str:
    if os.path.isfile(_CONFIG_FILE):
        url = open(_CONFIG_FILE).read().strip()
        if url:
            return url.rstrip("/")
    return os.environ.get("LIFE_MANAGER_BACKEND", "http://localhost:8000")

BACKEND_URL = _load_backend_url()
_USING_REMOTE = not BACKEND_URL.startswith("http://localhost") and not BACKEND_URL.startswith("http://127.")

BACKEND_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend")
)
BACKEND_PYTHON = os.path.join(BACKEND_DIR, "venv", "bin", "python")


class LifeManagerApp(rumps.App):
    def __init__(self):
        super().__init__("🧠", quit_button=None)

        self.tracking_enabled = True
        self._stop_event = threading.Event()
        self._backend_proc = None

        # --- Status items (non-clickable info lines) ---
        self.backend_item = rumps.MenuItem("⚙️  Backend: Starting...")
        self.tracking_item = rumps.MenuItem("📡  Tracking: —")

        # --- Action items ---
        self.toggle_item = rumps.MenuItem("Pause Tracking", callback=self.toggle_tracking)
        self.dashboard_item = rumps.MenuItem("Open Dashboard", callback=self.open_dashboard)
        self.quit_item = rumps.MenuItem("Quit Life Manager", callback=self.quit_app)

        self.menu = [
            self.backend_item,
            self.tracking_item,
            None,  # separator
            self.toggle_item,
            self.dashboard_item,
            None,
            self.quit_item,
        ]

        # Start backend + tracker in a background thread
        threading.Thread(target=self._startup, daemon=True).start()

        # Refresh status display every 30 s
        rumps.Timer(self._refresh_status, 30).start()

    # ------------------------------------------------------------------ #
    #  Startup: launch backend, then begin tracker loop
    # ------------------------------------------------------------------ #
    def _startup(self):
        self._start_backend()
        self._tracker_loop()

    def _start_backend(self):
        """Launch the FastAPI backend if it's not already running (local only)."""
        # Already up?
        try:
            requests.get(f"{BACKEND_URL}/api/settings", timeout=2.0)
            self.backend_item.title = "⚙️  Backend: Running ✅"
            return
        except Exception:
            pass

        # If pointed at a remote backend, don't try to spawn locally
        if _USING_REMOTE:
            self.backend_item.title = "⚙️  Backend: Offline ❌"
            print(f"Remote backend at {BACKEND_URL} is unreachable.")
            return

        # Spawn local backend
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

        # Wait up to 12 s for it to come up
        for _ in range(12):
            if self._stop_event.is_set():
                return
            try:
                requests.get(f"{BACKEND_URL}/api/settings", timeout=1.0)
                self.backend_item.title = "⚙️  Backend: Running ✅"
                return
            except Exception:
                self._stop_event.wait(1)

        self.backend_item.title = "⚙️  Backend: Offline ❌"

    # ------------------------------------------------------------------ #
    #  Main tracker loop (replaces tracker.py)
    # ------------------------------------------------------------------ #
    def _tracker_loop(self):
        poll_interval = 60.0

        while not self._stop_event.is_set():
            # Fetch current settings + kill-switch state
            try:
                resp = requests.get(f"{BACKEND_URL}/api/settings", timeout=2.0)
                if resp.status_code == 200:
                    data = resp.json()
                    poll_interval = data.get("polling_interval_seconds", 60)
                    self.tracking_enabled = data.get("tracking_enabled", True)
                    self.backend_item.title = "⚙️  Backend: Running ✅"
                    self.tracking_item.title = (
                        "📡  Tracking: ON ✅" if self.tracking_enabled else "📡  Tracking: Paused ⏸"
                    )
                    self.toggle_item.title = (
                        "Pause Tracking" if self.tracking_enabled else "Resume Tracking"
                    )
            except Exception:
                self.backend_item.title = "⚙️  Backend: Offline ❌"
                self.tracking_item.title = "📡  Tracking: —"

            if not self.tracking_enabled:
                self._stop_event.wait(300)  # 5 min when paused
                continue

            # Collect and send telemetry
            try:
                idle_time = tracker.get_idle_time()
                app_name = tracker.get_active_app()
                window_title = tracker.get_window_title(app_name)

                resp = requests.post(
                    f"{BACKEND_URL}/api/mac-telemetry",
                    json={
                        "app_name": app_name,
                        "window_title": window_title,
                        "idle_time_seconds": idle_time,
                    },
                    timeout=2.0,
                )

                if resp.status_code == 200:
                    prompt = resp.json().get("prompt")
                    if prompt:
                        user_reply = notifier.prompt_user(prompt)
                        if user_reply and user_reply not in ("Canceled", "Error"):
                            requests.post(
                                f"{BACKEND_URL}/api/prompt-reply",
                                json={"reply": user_reply},
                                timeout=2.0,
                            )
                        # Check if study mode just activated
                        state_resp = requests.get(f"{BACKEND_URL}/api/state", timeout=2.0)
                        if state_resp.ok and state_resp.json().get("study_mode") == "active":
                            notifier.notify(
                                "Study mode is active. Silencing notifications...",
                                "Life Manager",
                            )
            except Exception as e:
                print(f"Tracker error: {e}")

            self._stop_event.wait(poll_interval)

    # ------------------------------------------------------------------ #
    #  Menu callbacks
    # ------------------------------------------------------------------ #
    def _refresh_status(self, _):
        """Periodic status refresh (every 30 s) to keep menu accurate."""
        try:
            resp = requests.get(f"{BACKEND_URL}/api/settings", timeout=2.0)
            if resp.ok:
                enabled = resp.json().get("tracking_enabled", True)
                self.tracking_enabled = enabled
                self.backend_item.title = "⚙️  Backend: Running ✅"
                self.tracking_item.title = (
                    "📡  Tracking: ON ✅" if enabled else "📡  Tracking: Paused ⏸"
                )
                self.toggle_item.title = "Pause Tracking" if enabled else "Resume Tracking"
            else:
                self.backend_item.title = "⚙️  Backend: Offline ❌"
        except Exception:
            self.backend_item.title = "⚙️  Backend: Offline ❌"

    def toggle_tracking(self, _):
        new_state = not self.tracking_enabled
        try:
            requests.post(
                f"{BACKEND_URL}/api/settings",
                json={"tracking_enabled": new_state},
                timeout=2.0,
            )
            self.tracking_enabled = new_state
            self.tracking_item.title = (
                "📡  Tracking: ON ✅" if new_state else "📡  Tracking: Paused ⏸"
            )
            self.toggle_item.title = "Pause Tracking" if new_state else "Resume Tracking"
        except Exception:
            pass

    def open_dashboard(self, _):
        subprocess.Popen(["open", "http://localhost:8000"])

    def quit_app(self, _):
        """Clean quit: stop tracker loop and shut down the backend."""
        self._stop_event.set()
        if self._backend_proc and self._backend_proc.poll() is None:
            self._backend_proc.terminate()
        rumps.quit_application()


if __name__ == "__main__":
    LifeManagerApp().run()
