import time
import requests
import subprocess
from AppKit import NSWorkspace
from Quartz import CGEventSourceSecondsSinceLastEventType, kCGEventSourceStateHIDSystemState, kCGAnyInputEventType
import notifier

BACKEND_URL = "http://localhost:8000"

def get_idle_time() -> int:
    """Returns system idle time in seconds using Quartz."""
    idle = CGEventSourceSecondsSinceLastEventType(kCGEventSourceStateHIDSystemState, kCGAnyInputEventType)
    return int(idle)

def get_active_app() -> str:
    """Gets the name of the currently active macOS application."""
    workspace = NSWorkspace.sharedWorkspace()
    active_app = workspace.frontmostApplication()
    if active_app:
        return active_app.localizedName()
    return "Unknown"

def get_browser_tab(app_name: str) -> str:
    """Special handling for browsers to get the actual active tab name/URL instead of just window title."""
    if app_name == "Safari":
        applescript = '''
        try
            tell application "Safari"
                set currentTab to current tab of front window
                return (name of currentTab) & " - " & (URL of currentTab)
            end tell
        on error
            return ""
        end try
        '''
    elif app_name in ["Google Chrome", "Brave Browser", "Arc"]:
        applescript = f'''
        try
            tell application "{app_name}"
                set currentTab to active tab of front window
                return (title of currentTab) & " - " & (URL of currentTab)
            end tell
        on error
            return ""
        end try
        '''
    else:
        return ""

    try:
        result = subprocess.run(
            ["osascript", "-e", applescript],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except Exception:
        return ""

def get_window_title(app_name: str) -> str:
    """Uses AppleScript to try and get the frontmost window title of the active app."""
    # If it's a browser, use the specialized tab function for deeper context
    if app_name in ["Safari", "Google Chrome", "Brave Browser", "Arc"]:
        tab_info = get_browser_tab(app_name)
        if tab_info:
            return tab_info

    applescript = f'''
    try
        tell application "{app_name}"
            get name of front window
        end tell
    on error
        return ""
    end try
    '''
    try:
        result = subprocess.run(
            ["osascript", "-e", applescript],
            capture_output=True,
            text=True,
            check=True
        )
        title = result.stdout.strip()
        if "execution error" in title.lower():
            return ""
        return title
    except Exception:
        return ""

def get_recent_chrome_history(minutes: int = 15) -> list:
    """Read recent Chrome history for richer activity context.

    Chrome locks its History SQLite DB while running, so we copy it first.
    Returns list of {domain, title, visited_at} dicts — no full URLs for privacy.
    """
    import os, sqlite3, shutil
    from urllib.parse import urlparse
    from datetime import datetime, timedelta

    chrome_db = os.path.expanduser(
        "~/Library/Application Support/Google/Chrome/Default/History"
    )
    tmp_db = "/tmp/lm_chrome_history.db"

    if not os.path.exists(chrome_db):
        return []

    try:
        shutil.copy2(chrome_db, tmp_db)
    except Exception:
        return []

    # Chrome timestamps: microseconds since Jan 1, 1601
    cutoff_unix = (datetime.utcnow() - timedelta(minutes=minutes)).timestamp()
    cutoff_chrome = int((cutoff_unix + 11644473600) * 1_000_000)

    results = []
    try:
        conn = sqlite3.connect(f"file:{tmp_db}?mode=ro", uri=True)
        cursor = conn.execute(
            """
            SELECT u.url, u.title, v.visit_time
            FROM visits v
            JOIN urls u ON v.url = u.id
            WHERE v.visit_time > ?
            ORDER BY v.visit_time DESC
            LIMIT 50
            """,
            (cutoff_chrome,),
        )
        for url, title, visit_time in cursor:
            try:
                parsed = urlparse(url)
                domain = parsed.netloc
                if domain.startswith("www."):
                    domain = domain[4:]
            except Exception:
                domain = ""
            unix_ts = (visit_time / 1_000_000) - 11644473600
            visited_at = datetime.utcfromtimestamp(unix_ts).isoformat()
            results.append({
                "domain": domain,
                "title": (title or "")[:120],
                "visited_at": visited_at,
            })
        conn.close()
    except Exception:
        pass
    finally:
        try:
            os.unlink(tmp_db)
        except OSError:
            pass

    return results


def send_telemetry(app_name: str, window_title: str, idle_time: int):
    """Sends telemetry data to the backend API."""
    payload = {
        "app_name": app_name,
        "window_title": window_title,
        "idle_time_seconds": idle_time
    }
    try:
        resp = requests.post(f"{BACKEND_URL}/api/mac-telemetry", json=payload, timeout=2.0)
        
        if resp.status_code == 200:
            data = resp.json()
            prompt = data.get("prompt")
            if prompt:
                print(f"Backend triggered prompt: {prompt}")
                user_reply = notifier.prompt_user(prompt)
                
                if user_reply and user_reply != "Canceled" and user_reply != "Error":
                    requests.post(f"{BACKEND_URL}/api/prompt-reply", json={"reply": user_reply}, timeout=2.0)
                
                state_resp = requests.get(f"{BACKEND_URL}/api/state", timeout=2.0)
                if state_resp.status_code == 200:
                    states = state_resp.json()
                    if states.get("study_mode") == "active":
                        notifier.notify("Study mode is active. Silencing notifications...", "Life Manager")
                        
    except requests.exceptions.RequestException as e:
        print(f"Error connecting to backend: {e}")

def main():
    print("Starting Life Manager Mac Tracker with Tab Tracking...")
    print("Press Ctrl+C to exit.")
    
    poll_interval = 60.0 # Changed to 60s to save LLM credits
    
    while True:
        try:
            # Dynamically fetch the polling interval and tracking state
            try:
                settings_resp = requests.get(f"{BACKEND_URL}/api/settings", timeout=2.0)
                if settings_resp.status_code == 200:
                    data = settings_resp.json()
                    poll_interval = data.get("polling_interval_seconds", 60)
                    tracking_enabled = data.get("tracking_enabled", True)
            except Exception as e:
                tracking_enabled = True # failsafe

            if not tracking_enabled:
                print("Tracking is DISABLED. Sleeping for 5 min...")
                time.sleep(300)
                continue

            idle_time = get_idle_time()
            app_name = get_active_app()
            window_title = get_window_title(app_name)
            
            # Print truncated for clean terminal output
            display_title = window_title[:60] + "..." if len(window_title) > 60 else window_title
            print(f"Active: {app_name} [{display_title}] - Idle: {idle_time}s")
            
            send_telemetry(app_name, window_title, idle_time)
            
            time.sleep(poll_interval)
            
        except KeyboardInterrupt:
            print("\nExiting tracker...")
            break
        except Exception as e:
            print(f"Tracker error: {e}")
            time.sleep(poll_interval)

if __name__ == "__main__":
    main()
