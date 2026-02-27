# Life Manager Setup (Railway-First)

## 1. Deploy backend to Railway
1. Create Railway project from this repo using `backend/` as service root.
2. Set env vars:
- `GEMINI_API_KEY` (optional but needed for AI features)
- `DASHBOARD_USER` and `DASHBOARD_PASS` (recommended)
- `DATABASE_URL` (Railway Postgres recommended)
3. Confirm health endpoint works:
- `https://<your-railway-domain>/api/healthz`

## 2. Install Mac client in one command
```bash
cd mac_client
./install_and_enable_mac_client.sh https://<your-railway-domain>
```
Optional auth:
```bash
LIFE_MANAGER_AUTH="<user>:<pass>" ./install_and_enable_mac_client.sh https://<your-railway-domain>
```

## 3. Run diagnostics
```bash
cd mac_client
./life-manager doctor
```

## 4. iPhone setup check
- Open: `https://<your-railway-domain>/api/ios-setup-status`
- Sleep detection remains inactive until iPhone automations start pinging `POST /api/ios-telemetry`.

## 5. Budget defaults
- `llm_mode=ultra_save`
- hourly summaries disabled by default
- strict daily LLM cap enabled
