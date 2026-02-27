#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MAC_DIR="$ROOT_DIR/mac_client"
PLIST_SRC="$MAC_DIR/com.naboulsi.lifemanager.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.naboulsi.lifemanager.plist"
CFG_DIR="$HOME/.config/life-manager"
STATE_DIR="$HOME/.local/state/life-manager"

BACKEND_URL="${1:-${LIFE_MANAGER_BACKEND:-}}"
if [[ -z "$BACKEND_URL" ]]; then
  echo "Usage: $0 <railway-backend-url> [optional auth user:pass via LIFE_MANAGER_AUTH]"
  exit 1
fi

mkdir -p "$CFG_DIR" "$STATE_DIR" "$HOME/Library/LaunchAgents"
echo "$BACKEND_URL" > "$CFG_DIR/backend.url"

if [[ -n "${LIFE_MANAGER_AUTH:-}" ]]; then
  echo "$LIFE_MANAGER_AUTH" > "$CFG_DIR/auth"
fi

cat > "$CFG_DIR/client.json" <<'JSON'
{
  "show_status_window_on_launch": false,
  "recreate_status_icon_on_focus_loss": true,
  "railway_health_check_interval_seconds": 30
}
JSON

if [[ ! -d "$MAC_DIR/venv" ]]; then
  python3 -m venv "$MAC_DIR/venv"
fi
"$MAC_DIR/venv/bin/pip" install -q -r "$MAC_DIR/requirements.txt"

cp "$PLIST_SRC" "$PLIST_DST"

launchctl unload "$PLIST_DST" >/dev/null 2>&1 || true
launchctl load "$PLIST_DST"

sleep 2
HEALTH_URL="$BACKEND_URL/api/healthz"
AUTH_ARGS=()
if [[ -f "$CFG_DIR/auth" ]]; then
  AUTH_ARGS=(-u "$(cat "$CFG_DIR/auth")")
fi
if curl -fsS "${AUTH_ARGS[@]}" "$HEALTH_URL" >/dev/null; then
  echo "OK: backend health reachable at $HEALTH_URL"
else
  echo "WARN: backend not reachable at $HEALTH_URL"
fi

echo "Installed and enabled LaunchAgent: com.naboulsi.lifemanager"
