# Chronicle Setup Guide

This guide will help you set up and deploy Chronicle.
## 1. Deploy backend to Railway
1. Create Railway project from this repo using `backend/` as service root.
2. Set env vars:
- `GEMINI_API_KEY` (optional but needed for AI features)
- `DASHBOARD_USER` and `DASHBOARD_PASS` (recommended)
- `DATABASE_URL` (Railway Postgres recommended)
3. Confirm health endpoint works:
- `https://<your-railway-domain>/api/healthz`

## 2. Install Mac app
Run `./install.sh` from the `mac_native/` directory:
```bash
cd mac_native
./install.sh
```

## 3. iPhone setup
- Open the web dashboard and navigate to **iPhone Setup** for step-by-step instructions.
- Sleep detection remains inactive until iPhone automations start pinging `POST /api/ios-telemetry`.

## 4. Budget defaults
- `llm_mode=ultra_save`
- hourly summaries disabled by default
- strict daily LLM cap enabled
