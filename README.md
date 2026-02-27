# Life-Manager AI Agent

A personal AI agent that tracks activity across your MacBook M4 and iPhone to build a real-time Google Calendar of your life and keep you focused using a local Mistral model.

## Architecture

1. **Central Backend (Python + FastAPI)**: Core engine running on your 3050 server. Receives telemetry, talks to Mistral via Ollama, and queries Google Calendar.
2. **Mac Telemetry Client (Python)**: Background script natively using macOS PyObjC and Quartz to track active windows, applications, and system idle times.
3. **iOS Integration**: Apple Shortcuts Webhooks triggering based on geofencing and motion.

## 1. Backend Setup

First, install the backend dependencies on your 3050 server:
```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Start the FastAPI server:
```bash
python main.py
```
*Note: Make sure your Ollama instance is running Mistral locally at `http://localhost:11434/api/generate`.*

### Google Calendar setup
Generate a `credentials.json` from the Google Cloud Console (Desktop App type) with Calendar API scopes. Place it in the `backend/` folder. The first time `calendar_sync.py` is called, it will prompt you in the browser to login and will save a `token.json`.

## 2. Mac Client Setup

On your MacBook M4, install the Mac client dependencies. **PyObjC is required**, so a virtual environment is highly recommended.

```bash
cd mac_client
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Run the tracker in the background:
```bash
python tracker.py
```

*Note: You may be prompted by macOS to grant Terminal or Python Accessibility/Automation permissions so it can use AppleScript to query window titles and display dialog boxes.*

## 3. iOS iPhone Tracking Setup

To track location and motion without a custom Swift app, use the built-in **Apple Shortcuts** app on your iPhone.

1. Open **Shortcuts** > **Automation** > **+**
2. Choose a trigger, for example:
   - **Arrive**: Choose "Library" or "Class".
   - **Workout**: Choose "Walking".
   - **Charger**: Choose "Is Connected" (for sleep tracking).
3. Add action: **Get Contents of URL**
   - URL: `http://<YOUR_3050_IP>:8000/api/ios-telemetry`
   - Method: `POST`
   - Headers: `Content-Type: application/json`
   - Request Body: JSON
     - Custom field: `location_label` = `Library` (or wherever)
     - Custom field: `activity_type` = `Stationary` or `Walking`
4. Turn off "Ask Before Running".

When you arrive at the Library, your iPhone will secretly ping your backend. The backend will update `Study Mode`, and the Mac Client will notice the state change and mute your Mac notifications via AppleScript!

## Future Roadmap

### Self-Hosted LLM via Mistral + Ollama (Planned)

The goal is to replace Gemini API calls with a fully local, unlimited LLM running on the Windows laptop:

1. Install Ollama on the Windows laptop and pull Mistral: `ollama run mistral`
2. Ollama exposes a local API at `http://localhost:11434`
3. Make it reachable from the Mac/backend using one of:
   - **Same local network:** Use the laptop's LAN IP (e.g., `http://192.168.x.x:11434`)
   - **Tailscale (recommended):** Install Tailscale on both machines — gives a stable private IP that works across networks
   - **ngrok:** Quick tunnel for testing: `ngrok http 11434`
4. In `backend/llm_client.py`, replace `client.models.generate_content(model='gemini-...')` with an HTTP POST to `http://<laptop-ip>:11434/api/generate` using the Ollama JSON format
5. Benefits: no rate limits, no API costs, full data privacy

### Mobile-Responsive Dashboard (Planned)

The current dashboard is desktop-only. Future work:
- Add CSS breakpoints at 600px for mobile layout
- Stack header vertically on small screens
- Hide the Device column in the activity table to save space
- Increase button touch targets to 44px minimum
- Reduce `backdrop-filter` blur on mobile for performance

## GitHub Sync

To push this codebase to a private repo and sync it between your Mac and 3050 server:

```bash
git remote add origin https://github.com/<YOUR_USERNAME>/life-manager-agent.git
git branch -M main
git push -u origin main
```
