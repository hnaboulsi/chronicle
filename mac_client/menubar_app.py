import rumps
import threading
import requests
import subprocess
import sys
import os

# Add the mac_client directory to path so we can import tracker + notifier
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tracker
import notifier

BACKEND_URL = "http://localhost:8000"


class LifeManagerApp(rumps.App):
    def __init__(self):
        super().__init__("🧠", quit_button=None)

        self.tracking_enabled = True
        self._stop_event = threading.Event()

        # Menu items
        self.status_item = rumps.MenuItem("Status: Starting...")
        self.toggle_item = rumps.MenuItem("Pause Tracking", callback=self.toggle_tracking)
        self.dashboard_item = rumps.MenuItem("Open Dashboard", callback=self.open_dashboard)
        self.quit_item = rumps.MenuItem("Quit Life Manager", callback=self.quit_app)

        self.menu = [
            self.status_item,
            None,
            self.toggle_item,
            self.dashboard_item,
            None,
            self.quit_item,
        ]

        # Start tracker loop in background thread
        t = threading.Thread(target=self._tracker_loop, daemon=True)
        t.start()

        # Refresh menu status every 30 seconds
        rumps.Timer(self._refresh_status, 30).start()

    # ------------------------------------------------------------------ #
    #  Tracker loop (replaces tracker.py's main())
    # ------------------------------------------------------------------ #
    def _tracker_loop(self):
        poll_interval = 60.0

        while not self._stop_event.is_set():
            try:
                resp = requests.get(f"{BACKEND_URL}/api/settings", timeout=2.0)
                if resp.status_code == 200:
                    data = resp.json()
                    poll_interval = data.get("polling_interval_seconds", 60)
                    self.tracking_enabled = data.get("tracking_enabled", True)
            except Exception:
                self.tracking_enabled = True

            if not self.tracking_enabled:
                self._stop_event.wait(300)   # check back in 5 min when paused
                continue

            try:
                idle_time = tracker.get_idle_time()
                app_name = tracker.get_active_app()
                window_title = tracker.get_window_title(app_name)

                payload = {
                    "app_name": app_name,
                    "window_title": window_title,
                    "idle_time_seconds": idle_time,
                }
                resp = requests.post(f"{BACKEND_URL}/api/mac-telemetry", json=payload, timeout=2.0)
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
                        state_resp = requests.get(f"{BACKEND_URL}/api/state", timeout=2.0)
                        if state_resp.status_code == 200:
                            if state_resp.json().get("study_mode") == "active":
                                notifier.notify("Study mode is active. Silencing notifications...", "Life Manager")
            except Exception as e:
                print(f"Tracker error: {e}")

            self._stop_event.wait(poll_interval)

    # ------------------------------------------------------------------ #
    #  Menu callbacks
    # ------------------------------------------------------------------ #
    def _refresh_status(self, _):
        try:
            resp = requests.get(f"{BACKEND_URL}/api/settings", timeout=2.0)
            if resp.ok:
                enabled = resp.json().get("tracking_enabled", True)
                self.tracking_enabled = enabled
                self.status_item.title = f"Status: {'Tracking ✅' if enabled else 'Paused ⏸'}"
                self.toggle_item.title = "Pause Tracking" if enabled else "Resume Tracking"
            else:
                self.status_item.title = "Status: Backend offline ❌"
        except Exception:
            self.status_item.title = "Status: Backend offline ❌"

    def toggle_tracking(self, _):
        new_state = not self.tracking_enabled
        try:
            requests.post(
                f"{BACKEND_URL}/api/settings",
                json={"tracking_enabled": new_state},
                timeout=2.0,
            )
            self.tracking_enabled = new_state
            self.status_item.title = f"Status: {'Tracking ✅' if new_state else 'Paused ⏸'}"
            self.toggle_item.title = "Pause Tracking" if new_state else "Resume Tracking"
        except Exception:
            pass

    def open_dashboard(self, _):
        subprocess.Popen(["open", "http://localhost:8000"])

    def quit_app(self, _):
        self._stop_event.set()
        rumps.quit_application()


if __name__ == "__main__":
    LifeManagerApp().run()
