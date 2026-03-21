# Chronicle

AI-powered personal productivity tracker that understands your day. It watches what you're doing on your Mac, tracks your iPhone location, logs everything to your calendar, and proactively asks what you're up to when it doesn't know.

Chronicle is currently in internal alpha.

## What It Does

- **Tracks your Mac activity** — A silent native macOS agent knows what app you're using and classifies it (studying, working, entertainment, etc.)
- **Tracks your iPhone location** — Uses iOS Shortcut geofences (Zones) to detect when you arrive at or leave a location, with zero background battery drain.
- **Asks you when it doesn't know** — If you arrive somewhere new or come back to your laptop after being away, it sends a check-in prompt. Snooze or dismiss directly from the dashboard.
- **Understands context** — Set your current intent, sleep window, and day mode (travel/exam/rest) from the macOS app. Chronicle adjusts its interpretation of your activity accordingly.
- **Logs to Apple Calendar** — Productive sessions and location visits automatically appear as events on your calendar.
- **AI insights** — Hourly recaps with source transparency (LLM vs deterministic fallback). Click any activity log for an AI summary.
- **Real-time dashboard** — Live updates, KPI cards, activity timeline, check-in prompts, and full settings.

## Architecture

```
iPhone Shortcuts ──→ Railway Backend (FastAPI + PostgreSQL) ←── Native macOS Agent
                           ↓
                    Web Dashboard (Control Center)
                    Apple Calendar Sync
                    AI Classification (Gemini / OpenAI)
```

Everything runs through a single Railway backend. The iPhone uses native Apple Shortcuts (no app needed). The Mac runs a lightweight native Swift app with a background helper agent. The dashboard is a PWA you can add to your iPhone home screen.

## Quick Start

### 1. Deploy Backend to Railway

Connect the repo to Railway and set the `backend/` directory as the root. Set these environment variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL (Railway provides this automatically) |
| `GEMINI_API_KEY` | Recommended | Free Google Gemini API key for AI features |
| `OPENAI_API_KEY` | Optional | OpenAI fallback |
| `DASHBOARD_USER` | Optional | Login username (default: admin) |
| `DASHBOARD_PASS` | Optional | Login password (empty = no auth) |

Verify health: `GET https://your-app.railway.app/api/healthz`

### 2. Install the Mac App

1. Open `mac_native/LifeManager.xcodeproj` in Xcode (or run `./install.sh`).
2. Build and run.
3. Enter your backend URL and auth credentials in the app.
4. Click **Enable Agent** to start the background tracking helper.
5. Grant Accessibility, Notification, and Calendar permissions when prompted.

### 3. Set Up iPhone Geofences

Open the web dashboard and go to **Settings → Zones** to add your locations. Then open the **iPhone Setup** page (`/setup/ios`) to generate and install the required Shortcuts for each zone.

Vero uses Enter/Leave automations instead of background GPS — no battery drain.

### 4. Use the Dashboard

Open the dashboard URL in Safari on your iPhone → Share → Add to Home Screen for a PWA experience. Or open it directly from the Mac app.

## Features

### Dashboard KPIs

Three cards on the dashboard home:
- **Active Today** — minutes of non-idle Mac activity in the current local day.
- **Productive %** — percentage of active time in productive categories (studying, working, creative).
- **AI Calls Today** — LLM calls used vs. your daily cap, with heuristic fallback when the cap is hit.

Status shows as: **Online / Paused / Needs Attention / Offline**. Idle is shown as secondary detail only.

### Check-In Prompts

When Vero detects a context switch it isn't sure about, it prompts you in the dashboard. Prompts auto-expire after 60 minutes. You can Snooze (suppress for a configured duration) or Dismiss. Same-location prompts are suppressed for a 4-hour cooldown window.

### Hourly Recaps

A rolling hourly summary is always available. Vero first attempts an LLM-generated recap; if the LLM is unavailable or the budget is exhausted, it falls back to a deterministic recap from the raw activity logs. Each recap shows its source (LLM or deterministic) and a confidence score.

### Activity Timeline

The Activity Timeline on the dashboard is derived from Mac telemetry sampling — it is not a mirror of your Apple Calendar. A tooltip on the dashboard clarifies the distinction.

### Context (macOS App)

The macOS app has a **Context** tab where you can set:
- **Current intent** — what you're doing right now (helps Vero classify ambiguous activity).
- **Sleep window** — your expected sleep and wake hours (used for sleep inference).
- **Day mode** — Normal, Travel, Exam, or Rest (adjusts activity interpretation).

### Sleep Inference

Vero uses a hybrid signal model to estimate whether you're asleep: local time window, charging state (on/off), stationary signal, and Mac idle/offline status. The current inference reason and confidence are shown on the dashboard and in macOS Overview.

### Smart Activity Classification

Gemini 2.5 Flash (with OpenAI fallback) classifies activity into: `studying`, `working`, `creative`, `entertainment`, `social media`, `gaming`, `break`, `idle`. Falls back to keyword heuristics when the LLM budget is exhausted.

### Apple Calendar Integration

The Mac agent writes productive sessions (10+ min) and location visits directly to your local Apple Calendar via EventKit. Syncs to all devices via iCloud Calendar if enabled.

### Zones

Zones are fully user-defined geofences. Add, edit, or delete them from the dashboard or the macOS Zones tab. Each zone generates Enter/Leave Shortcut URLs for the iPhone setup page. Zone validation is strict — slugs must be unique and non-empty.

### macOS App Navigation

- **Overview** — agent status, sleep inference, iPhone readiness badge.
- **Zones** — zone list and editor, with iPhone setup deep link.
- **Context** — intent, sleep window, and day mode settings.
- **Diagnostics** — agent health, backend/auth status (auth errors shown with actionable reconnect instructions), calendar status, and recovery actions.

## Environment Variables Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | — | PostgreSQL connection string |
| `GEMINI_API_KEY` | — | Gemini API key |
| `OPENAI_API_KEY` | — | OpenAI API key (fallback) |
| `DASHBOARD_USER` | `admin` | Dashboard login username |
| `DASHBOARD_PASS` | _(none)_ | Dashboard login password |
| `DAILY_LLM_BUDGET` | `30` | Max LLM calls per day |
| `USER_TIMEZONE` | `America/Los_Angeles` | Local timezone for analytics boundaries |
| `BACKEND_URL` | _(auto)_ | Public URL used for Shortcut generation |
