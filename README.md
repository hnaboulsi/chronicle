# Chronicle

A self-hosted activity and calendar context system with a native macOS agent, FastAPI backend,
and responsive web dashboard. It records only the signals configured by the operator and keeps
the collection path visible so behavior can be inspected rather than treated as an opaque score.

Chronicle is an experimental personal tool, not employee-monitoring software or a validated
measure of productivity.

## Demo / Results

The current repository includes unit tests for analytics, AI-provider routing, zones, and summary
helpers. The web client has a reproducible Vite build, while the native client is generated from
`mac_native/project.yml` and built with Xcode. Screenshots and longer-term performance measurements
are still missing; the README does not claim them as completed evidence.

## What I Built

- **Tracks your Mac activity** — A silent native macOS agent knows what app you're using and classifies it (studying, working, entertainment, etc.)
- **Tracks your iPhone location** — Uses iOS Shortcut geofences (Zones) to detect when you arrive at or leave a location, with zero background battery drain.
- **Asks you when it doesn't know** — If you arrive somewhere new or come back to your laptop after being away, a check-in card appears on the dashboard. Confirm, correct, snooze, or dismiss directly.
- **Understands context** — Set your current intent from the dashboard. Chronicle adjusts its interpretation of your activity accordingly.
- **Surfaces your calendar** — Today's events appear with AI-generated types (lecture, assignment, meeting, exam) and action notes. Tonight's schedule or remaining events are shown at a glance.
- **Deadline nudges** — When an assignment or exam is approaching and no prep activity is detected, the LLM generates a targeted nudge. One nudge per event per day — not spammy.
- **AI insights** — Hourly recaps, a 7-day productivity heat map, and a daily intelligence summary. Source-transparent (LLM vs. deterministic fallback).
- **Logs to Apple Calendar** — Productive sessions and location visits automatically appear as events on your calendar.

## How It Works

```
iPhone Shortcuts ──→ Railway Backend (FastAPI + PostgreSQL) ←── Native macOS Agent
                           ↓
                    Web Dashboard (Control Center)
                    Apple Calendar Sync
                    AI Classification (Gemini / OpenAI / Anthropic)
```

Everything runs through a single Railway backend. The iPhone uses native Apple Shortcuts (no app needed). The Mac runs a lightweight native Swift app with a background helper agent. The dashboard is a PWA you can add to your iPhone home screen.

## Running It

### 1. Deploy Backend to Railway

Connect the repo to Railway and set the `backend/` directory as the root. Set these environment variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL (Railway provides this automatically) |
| `GEMINI_API_KEY` | Recommended | Free Google Gemini API key for AI features |
| `OPENAI_API_KEY` | Optional | OpenAI fallback |
| `ANTHROPIC_API_KEY` | Optional | Anthropic Claude fallback |
| `DASHBOARD_USER` | Yes | Login username |
| `DASHBOARD_PASS` | Yes | Strong dashboard password |
| `SECRET_KEY` | Yes | Random session-signing secret |

Verify health: `GET https://your-app.railway.app/api/healthz`

### 2. Install the Mac App

1. Open `mac_native/Chronicle.xcodeproj` in Xcode (or run `./install.sh`).
2. Build and run.
3. Enter your backend URL and auth credentials in the app.
4. Click **Enable Agent** to start the background tracking helper.
5. Grant Accessibility, Notification, and Calendar permissions when prompted.

### 3. Add Your Locations (Zones)

Open the web dashboard and go to **Places** (`/zones`) to add your locations. Each zone gets Enter/Leave Shortcut URLs for iPhone automation.

Zones use Enter/Leave automations instead of background GPS — no battery drain.

### 4. Use the Dashboard

Open the dashboard URL in Safari on your iPhone → Share → Add to Home Screen for a PWA experience. Or open it directly from the Mac app.

Press `/` anywhere on the Today page to quickly focus the intent input.

## Features

### Today Page

The main dashboard shows:
- **Time greeting + Intent input** — Set what you're working on. Press `/` to focus.
- **Check-in card** — When Chronicle detects a context switch it isn't sure about, an interactive card appears. Type a correction or confirm the guess. Snooze 30 min or dismiss.
- **Tonight's Schedule / Today's Remaining** — Your upcoming calendar events with AI-classified types (lecture, assignment, meeting, exam, focus) and action notes. Switches label at 5 PM.
- **Deadline nudge banner** — LLM-generated reminder when a high-stakes event approaches and no prep activity is detected.
- **Productivity Pulse** — Bar chart of today's hourly productivity scores, color-coded by grade. Only real tracked hours shown (no sleep stubs).

### 7-Day Chronicle (History Page)

A horizontal week heat map: days are rows, hours are columns, time flows left → right. Each cell is color-coded by productivity score (green = high, yellow = mid, red = low, dark = no data). Click a cell to see the hour's AI summary inline. Grade and percentage shown on the right of each row.

### Deadline Nudges

When an `assignment`, `exam`, or `focus` event is 1–6 hours away (or a `meeting` is 15–60 min away), Chronicle checks whether recent hourly summaries show relevant prep. If not, the LLM generates a short nudge (≤14 words). One nudge per event per day — dismissed with ✕.

### Check-In Prompts

Chronicle generates check-in prompts on context switches: arriving at a new location, returning to the Mac after 15+ min away, or an upcoming calendar event with a location. The check-in card shows the question and the system's best guess. You can:
- **Confirm** the guess (or type a correction and confirm)
- **Snooze 30m** — suppresses the same prompt for 30 minutes
- **Dismiss** — skips this prompt with a 4-hour cooldown for the same location

Prompts auto-expire after 60 minutes.

### Sleep Inference

Chronicle uses a hybrid signal model to decide whether you're asleep: sleep window hours (configurable from Settings), charging state, stationary signal from iPhone, and Mac idle/offline status. No LLM calls are made during the sleep window.

### Smart Activity Classification

Gemini 2.5 Flash (with OpenAI/Anthropic fallback) classifies Mac activity into: `studying`, `working`, `creative`, `entertainment`, `social_media`, `gaming`, `break`, `idle`. Falls back to keyword heuristics when the LLM budget is exhausted.

### Apple Calendar Integration

The Mac agent writes productive sessions (10+ min) and location visits directly to your local Apple Calendar via EventKit. Syncs to all devices via iCloud Calendar if enabled.

### Zones (Places)

Zones are fully user-defined geofences. Add, edit, or delete them from the **Places** page. Each zone has:
- **Name** and **slug** (slug is set once at creation — changing it would break iPhone Shortcut URLs)
- **Type** — Custom, Study, Work, Home, Gym
- **Radius** — 25–500 meters
- **Focus Mode** — optional tag passed to the LLM context

Each zone generates Enter/Leave Shortcut URLs for the iPhone setup page.

### Settings

Configurable from the web dashboard:
- **Capture interval** — how often Mac activity is sampled (5 / 15 / 30 min)
- **Sleep window** — hours when LLM calls and nudges are suppressed
- **iCal URLs** — sync external calendar feeds (Google Calendar, etc.) for event classification and deadline nudges
- **Tracking toggle** — pause all data collection

Timezone is auto-synced from your browser on every app load.

### macOS App Navigation

- **Overview** — agent status, sleep inference, iPhone readiness badge.
- **Zones** — zone list and editor, with iPhone setup deep link.
- **Context** — intent, sleep window, and day mode settings.
- **Diagnostics** — agent health, backend/auth status, calendar status, and recovery actions.

## Environment Variables Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | — | PostgreSQL connection string |
| `GEMINI_API_KEY` | — | Gemini API key (recommended primary) |
| `OPENAI_API_KEY` | — | OpenAI API key (fallback) |
| `ANTHROPIC_API_KEY` | — | Anthropic Claude API key (fallback) |
| `DASHBOARD_USER` | `admin` | Dashboard login username |
| `DASHBOARD_PASS` | _(none)_ | Dashboard password; required for any network-accessible deployment |
| `SECRET_KEY` | _(none)_ | Random session-signing key; required whenever `DASHBOARD_PASS` is set |
| `DAILY_LLM_BUDGET` | `30` | Max LLM calls per day |
| `USER_TIMEZONE` | _(auto)_ | Fallback timezone; auto-synced from browser on each load |
| `BACKEND_URL` | _(auto)_ | Public URL used for Shortcut generation |

## Privacy and Security Boundaries

Chronicle can collect application names, browser window titles, calendar metadata, coarse zone
events, and user-entered context. That data can reveal sensitive personal behavior. Run the
backend only over HTTPS, set both `DASHBOARD_PASS` and a random `SECRET_KEY`, restrict database
access, and review the configured collection fields before enabling the agent. The repository
contains no telemetry from the author's own account. Location is represented as user-defined
enter/leave zone events; the project does not continuously upload raw GPS coordinates.

The in-memory login throttle is a convenience control, not distributed abuse protection. A
public deployment should also use platform-level rate limiting and managed secrets.

## Known Limitations

The app is single-user, its classifier labels are heuristic or model-generated, and its scores
should not be interpreted as objective judgments. Cross-device ordering depends on host clocks.
The current repository does not include a production threat model, external security review, or
long-duration resource benchmark.

## Tech

Swift and SwiftUI, EventKit, FastAPI, SQLAlchemy, PostgreSQL, React, TypeScript, and Vite.
