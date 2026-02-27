# Life Manager

AI-powered personal productivity tracker that understands your day. It watches what you're doing on your Mac, tracks your iPhone location, logs everything to your calendar, and proactively asks what you're up to when it doesn't know.

## What It Does

- **Tracks your Mac activity** — knows what app you're using, classifies it (studying, working, entertainment, etc.)
- **Tracks your iPhone location** — detects when you arrive at the library, walk somewhere, start charging
- **Asks you when it doesn't know** — "Looks like you're at Student Union. I think you stopped for food — is that right?"
- **You can tell it** — type "heading to VLSB to study" in the chat bar and it updates your context
- **Logs to Apple Calendar** — productive sessions, walks, and location visits auto-appear on your calendar
- **AI insights** — click any activity log for a fun AI summary of what you were doing
- **Works as a phone app** — add the dashboard to your iPhone home screen (PWA) for native-feeling control
- **Real-time dashboard** — live updates via Server-Sent Events, no page refreshing

## Architecture

```
iPhone Shortcuts ──→ Railway Backend (FastAPI + PostgreSQL) ←── Mac Menu Bar App
                           ↓
                    Web Dashboard (PWA)
                    Apple Calendar Sync
                    Gemini AI Classification
```

Everything runs through a single Railway backend ($5/month plan). iPhone uses Apple Shortcuts (no app needed). Mac runs a lightweight menu bar agent. The dashboard is a PWA you can install on any device.

## Quick Start

### 1. Deploy Backend to Railway

Push the `backend/` folder to Railway. Set these env vars:

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL (Railway provides this) |
| `GEMINI_API_KEY` | Recommended | Free Google Gemini API key for AI features |
| `DASHBOARD_USER` | Optional | Basic auth username (default: admin) |
| `DASHBOARD_PASS` | Optional | Basic auth password (empty = no auth) |

Verify: `GET https://your-app.railway.app/api/healthz`

### 2. Install Mac Client

```bash
cd mac_client
./install_and_enable_mac_client.sh https://your-app.railway.app
```

With auth:
```bash
LIFE_MANAGER_AUTH="user:pass" ./install_and_enable_mac_client.sh https://your-app.railway.app
```

The menu bar shows a brain emoji (🧠) that changes based on your current activity.

### 3. Set Up iPhone

Open `https://your-app.railway.app/setup/ios` on your Mac. Download 5 shortcut files, AirDrop them to your iPhone, then create automations in the Shortcuts app:

1. **Every 30 min** → Run "Life Manager GPS"
2. **Arrive at location** → Run "Life Manager Arrive"
3. **Walking starts** → Run "Life Manager Walking"
4. **Charger connected** → Run "Life Manager Charging On"
5. **Charger disconnected** → Run "Life Manager Charging Off"

### 4. Add to iPhone Home Screen

Open the dashboard URL in Safari on your iPhone → Share → Add to Home Screen. It works like a native app.

## Features

### Chat & Check-Ins
Type in the chat bar: "Going to the library to study" or "Just grabbing food at Student Union". The agent acknowledges and tracks your context. When it doesn't know what you're doing (you arrived somewhere new, came back to your laptop after being away), it asks with a smart guess you can confirm or correct.

### Smart Activity Classification
Uses Google Gemini (free tier) to classify your activity every 30 minutes. Falls back to keyword heuristics when AI budget is exhausted. Categories: studying, working, creative, entertainment, social media, gaming, break, idle.

### Calendar Integration
Productive sessions (10+ min), walks (3+ min), and location visits (10+ min) automatically appear on your Apple Calendar. Syncs to Google Calendar if linked in System Settings.

### Settings
Full settings panel accessible from the gear icon or mobile bottom nav. Configure timezone, AI budget, polling interval, LLM mode, hourly summaries, and more.

### Budget Controls
Default: 30 AI calls/day (ultra_save mode). Adjustable in settings. Free Gemini API stays well within limits.

## Diagnostics

```bash
cd mac_client
./life-manager doctor
```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/healthz` | Health check with DB, LLM, and telemetry status |
| `GET /api/state` | Current device states, activity, location |
| `GET/POST /api/settings` | Read/update all settings |
| `GET /api/logs` | Activity log feed |
| `GET /api/analytics/today` | Daily productivity breakdown |
| `POST /api/chat` | Send a message to the agent |
| `GET /api/checkin` | Get pending check-in question |
| `GET /api/stream` | SSE real-time updates |
| `GET /api/export?days=30` | Export activity data as CSV |
| `POST /api/mac-telemetry` | Mac tracker heartbeat |
| `POST /api/ios-telemetry` | iPhone shortcut webhook |
