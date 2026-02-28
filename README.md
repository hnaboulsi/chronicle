# Life Manager

AI-powered personal productivity tracker that understands your day. It watches what you're doing on your Mac, tracks your iPhone location, logs everything to your calendar, and proactively asks what you're up to when it doesn't know.

## What It Does

- **Tracks your Mac activity** — A silent native macOS agent knows what app you're using and classifies it (studying, working, entertainment, etc.)
- **Tracks your iPhone location** — Uses iOS Shortcut geofences (Zones) to detect when you arrive at the library or leave home, with zero background battery drain.
- **Asks you when it doesn't know** — If you arrive somewhere new or come back to your laptop after being away, it sends a notification asking for context.
- **You can tell it** — Type "heading to VLSB to study" in the dashboard chat bar and it instantly updates your context.
- **Logs to Apple Calendar** — Productive sessions, walks, and location visits automatically appear as events on your calendar.
- **AI insights** — Click any activity log in the dashboard for an AI summary of what you were doing.
- **Real-time dashboard** — A comprehensive Control Center web app with live updates, charts, and settings.

## Architecture

```
iPhone Shortcuts ──→ Railway Backend (FastAPI + PostgreSQL) ←── Native macOS Agent
                           ↓
                    Web Dashboard Control Center
                    Apple Calendar Sync
                    AI Classification
```

Everything runs through a single Railway backend. The iPhone uses native Apple Shortcuts (no app needed). The Mac runs a lightweight, native Swift application consisting of a setup UI and a hidden background helper. The dashboard is a PWA you can install on any device.

## Quick Start

### 1. Deploy Backend to Railway

Push the backend folder to Railway. Set these environment variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL (Railway provides this) |
| `GEMINI_API_KEY` | Recommended | Free Google Gemini API key for AI features |
| `OPENAI_API_KEY` | Optional | For OpenAI fallback |
| `DASHBOARD_USER` | Optional | Basic auth username (default: admin) |
| `DASHBOARD_PASS` | Optional | Basic auth password (empty = no auth) |

Verify health at: `GET https://your-app.railway.app/api/healthz`

### 2. Install the Mac App

The Mac client has been rewritten in native Swift for maximum efficiency and stability.
1. Open the `mac_native/LifeManager.xcodeproj` in Xcode.
2. Build and run the app.
3. Configure your backend URL and auth credentials.
4. Click **Enable Agent** to start the hidden background tracking helper.
5. Provide Accessibility, Notification, and Calendar permissions.

### 3. Set Up iPhone Geofences

Open the Control Center Web Dashboard and navigate to **Settings -> Zones** to configure your locations. Then generate and secure the required iOS Shortcuts via the `/setup/ios` page. 

Instead of draining your battery with GPS polling, Life Manager uses highly efficient Enter/Leave automations for your Zones via the Apple Shortcuts app.

### 4. Control Center Dashboard

Open the dashboard URL in Safari on your iPhone → Share → Add to Home Screen. It works like a native app. Or, open it on your Mac directly from the Life Manager app.

## Features

### Chat & Proactive Check-Ins
Type in the chat bar: "Going to the library to study". The agent acknowledges and tracks your context. When it doesn't know what you're doing, it asks with a smart guess you can confirm or correct directly from the dashboard.

### Smart Activity Classification
Uses AI (Gemini/OpenAI) to classify your activity. Categories: studying, working, creative, entertainment, social media, gaming, break, idle.

### Local Calendar Integration
The native Mac agent writes productive sessions (10+ min), walks (3+ min), and location visits directly into your local Apple Calendar via EventKit. If you use iCloud Calendar, this syncs seamlessly to all your devices.

### Settings & Zones
Full settings panel accessible from the dashboard. Configure your timezone, AI budget, polling intervals, custom geofence Zones, and notification verbosity.
