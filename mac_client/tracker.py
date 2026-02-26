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

def get_window_title(app_name: str) -> str:
    """Uses AppleScript to try and get the frontmost window title of the active app."""
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
        # Some apps return complicated strings or unprintable chars, handle basic case
        if "execution error" in title.lower():
            return ""
        return title
    except Exception:
        return ""

def send_telemetry(app_name: str, window_title: str, idle_time: int):
    """Sends telemetry data to the backend API."""
    payload = {
        "app_name": app_name,
        "window_title": window_title,
        "idle_time_seconds": idle_time
    }
    try:
        # Timeout quickly so we don't block the loop if backend is down
        resp = requests.post(f"{BACKEND_URL}/api/mac-telemetry", json=payload, timeout=2.0)
        
        # Check if the backend wants us to show a prompt
        if resp.status_code == 200:
            data = resp.json()
            prompt = data.get("prompt")
            if prompt:
                print(f"Backend triggered prompt: {prompt}")
                # Show native macOS dialog box
                user_reply = notifier.prompt_user(prompt)
                
                # Send the reply back
                if user_reply and user_reply != "Canceled" and user_reply != "Error":
                    requests.post(f"{BACKEND_URL}/api/prompt-reply", json={"reply": user_reply}, timeout=2.0)
                
                # Check Study Mode state to silence system if needed 
                # (In a real app we'd trigger a Focus mode via Shortcuts, here we just notify)
                state_resp = requests.get(f"{BACKEND_URL}/api/state", timeout=2.0)
                if state_resp.status_code == 200:
                    states = state_resp.json()
                    if states.get("study_mode") == "active":
                        notifier.notify("Study mode is active. Silencing notifications...", "Life Manager")
                        
    except requests.exceptions.RequestException as e:
        print(f"Error connecting to backend: {e}")

def main():
    print("Starting Life Manager Mac Tracker...")
    print("Press Ctrl+C to exit.")
    
    poll_interval = 5.0  # seconds
    
    while True:
        try:
            idle_time = get_idle_time()
            app_name = get_active_app()
            window_title = get_window_title(app_name)
            
            print(f"Active: {app_name} [{window_title}] - Idle: {idle_time}s")
            
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
