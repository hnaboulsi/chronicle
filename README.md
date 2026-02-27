# Life Manager Agent

Railway-first personal activity tracker with a macOS menu bar client and iPhone telemetry webhooks.

## Quick Start

### Backend (Railway)
- Deploy `backend/` to Railway.
- Configure env vars: `DATABASE_URL`, `DASHBOARD_USER`, `DASHBOARD_PASS`, optional `GEMINI_API_KEY`.
- Verify: `GET /api/healthz` returns ok.

### Mac Client (one-click)
```bash
cd mac_client
./install_and_enable_mac_client.sh https://<your-railway-domain>
```

Optional auth:
```bash
LIFE_MANAGER_AUTH="user:pass" ./install_and_enable_mac_client.sh https://<your-railway-domain>
```

Diagnostics:
```bash
cd mac_client
./life-manager doctor
```

## Key Endpoints
- `GET /api/healthz`
- `GET/POST /api/settings`
- `GET /api/state`
- `GET /api/ios-setup-status`
- `POST /api/mac-telemetry`
- `POST /api/ios-telemetry`

## Defaults
- Backend mode: `railway_primary`
- LLM mode: `ultra_save`
- Sleep source: `iphone_only`
- Hourly summaries: disabled by default
