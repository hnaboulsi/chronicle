import asyncio
import json
import logging
import os
import base64
import html
import subprocess
import secrets
import hmac
import hashlib
import threading
from datetime import datetime, timedelta, timezone
from typing import Dict, Any

from fastapi import FastAPI, Depends, BackgroundTasks, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, Response, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc, text, func
from database import engine, Base, get_db, SessionLocal
import models
from models import ActivityLog, CalendarEventJob, HourlySummary, MacHeartbeat, MacPresence, MacTelemetry, iOSZoneEvent, iOSTelemetry, UserCalendarEvent, CalendarEventItem
import agent_logic
import llm_client

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("vero")

_STARTUP_STATUS = {
    "process_ready": False,
    "database_ready": False,
    "startup_migrations_ok": False,
    "startup_errors": [],
}


# Lightweight column migrations — add missing columns to existing tables
def _run_migrations() -> list[str]:
    errors: list[str] = []
    with engine.connect() as conn:
        dialect = engine.dialect.name
        try:
            if dialect == "postgresql":
                conn.execute(text("ALTER TABLE activity_logs ADD COLUMN IF NOT EXISTS battery_pct INTEGER"))
                conn.execute(text("ALTER TABLE activity_logs ADD COLUMN IF NOT EXISTS presence_state VARCHAR(32)"))
                conn.execute(text("ALTER TABLE activity_logs ADD COLUMN IF NOT EXISTS screen_state VARCHAR(32)"))
                conn.execute(text("ALTER TABLE hourly_summaries ADD COLUMN IF NOT EXISTS summary_source VARCHAR(32) DEFAULT 'llm'"))
                conn.execute(text("ALTER TABLE hourly_summaries ADD COLUMN IF NOT EXISTS confidence FLOAT"))
                conn.execute(text("ALTER TABLE hourly_summaries ADD COLUMN IF NOT EXISTS fallback_used BOOLEAN DEFAULT FALSE"))
            else:  # sqlite doesn't support IF NOT EXISTS on ALTER
                cols = [r[1] for r in conn.execute(text("PRAGMA table_info(activity_logs)"))]
                if "battery_pct" not in cols:
                    conn.execute(text("ALTER TABLE activity_logs ADD COLUMN battery_pct INTEGER"))
                if "presence_state" not in cols:
                    conn.execute(text("ALTER TABLE activity_logs ADD COLUMN presence_state VARCHAR(32)"))
                if "screen_state" not in cols:
                    conn.execute(text("ALTER TABLE activity_logs ADD COLUMN screen_state VARCHAR(32)"))
                summary_cols = [r[1] for r in conn.execute(text("PRAGMA table_info(hourly_summaries)"))]
                if "summary_source" not in summary_cols:
                    conn.execute(text("ALTER TABLE hourly_summaries ADD COLUMN summary_source VARCHAR(32) DEFAULT 'llm'"))
                if "confidence" not in summary_cols:
                    conn.execute(text("ALTER TABLE hourly_summaries ADD COLUMN confidence FLOAT"))
                if "fallback_used" not in summary_cols:
                    conn.execute(text("ALTER TABLE hourly_summaries ADD COLUMN fallback_used BOOLEAN DEFAULT 0"))

            # Data migration: rename legacy app names to "Vero"
            conn.execute(text("""
                UPDATE activity_logs
                SET app_name = 'Vero'
                WHERE app_name IN ('LifeManager', 'Vero Agent', 'Ambient')
            """))

            # Reset migration (v3): zones are now user-defined only.
            marker = conn.execute(
                text("SELECT value FROM agent_states WHERE key = 'zones_reset_v3' LIMIT 1")
            ).scalar()
            if marker != "true":
                conn.execute(text("DELETE FROM location_zones"))
                conn.execute(
                    text(
                        """
                        DELETE FROM agent_states
                        WHERE key IN (
                          'current_location',
                          'location_arrival',
                          'commute_start',
                          'commute_from',
                          'last_zone_enter',
                          'study_mode'
                        )
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO agent_states (key, value, updated_at)
                        VALUES ('zones_reset_v3', 'true', CURRENT_TIMESTAMP)
                        ON CONFLICT(key) DO UPDATE SET value='true', updated_at=CURRENT_TIMESTAMP
                        """
                    )
                )

            # Restore migration (v3b): automation-seen flags were incorrectly wiped by v3.
            restore_marker = conn.execute(
                text("SELECT value FROM agent_states WHERE key = 'automation_flags_restore_v1' LIMIT 1")
            ).scalar()
            if restore_marker != "true":
                for flag in ('seen_arrive_automation', 'seen_leave_automation', 'seen_charging_automation'):
                    existing = conn.execute(
                        text("SELECT value FROM agent_states WHERE key = :k LIMIT 1"),
                        {"k": flag}
                    ).scalar()
                    if existing is None:
                        conn.execute(
                            text(
                                """
                                INSERT INTO agent_states (key, value, updated_at)
                                VALUES (:k, 'true', CURRENT_TIMESTAMP)
                                ON CONFLICT(key) DO NOTHING
                                """
                            ),
                            {"k": flag}
                        )
                conn.execute(
                    text(
                        """
                        INSERT INTO agent_states (key, value, updated_at)
                        VALUES ('automation_flags_restore_v1', 'true', CURRENT_TIMESTAMP)
                        ON CONFLICT(key) DO UPDATE SET value='true', updated_at=CURRENT_TIMESTAMP
                        """
                    )
                )
            checkin_marker = conn.execute(
                text("SELECT value FROM agent_states WHERE key = 'checkin_cleanup_v1' LIMIT 1")
            ).scalar()
            if checkin_marker != "true":
                conn.execute(
                    text(
                        """
                        DELETE FROM agent_states
                        WHERE key IN (
                          'pending_checkin',
                          'checkin_guess',
                          'pending_checkin_created_at',
                          'pending_checkin_expires_at',
                          'pending_checkin_context_key'
                        )
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO agent_states (key, value, updated_at)
                        VALUES ('checkin_cleanup_v1', 'true', CURRENT_TIMESTAMP)
                        ON CONFLICT(key) DO UPDATE SET value='true', updated_at=CURRENT_TIMESTAMP
                        """
                    )
                )
            conn.commit()
        except Exception as exc:
            errors.append(str(exc))
    return errors

app = FastAPI(title="Vero API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
_STARTED_AT = datetime.now(timezone.utc)
_BUILD_VERSION = os.environ.get("VERO_BUILD_VERSION") or os.environ.get("LIFE_MANAGER_BUILD_VERSION", "dev")
_DEPLOYMENT_CHANNEL = os.environ.get("VERO_DEPLOYMENT_CHANNEL") or os.environ.get("LIFE_MANAGER_DEPLOYMENT_CHANNEL", "internal")
try:
    _GIT_SHA = (
        subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=os.path.dirname(__file__),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        or "unknown"
    )
except Exception:
    _GIT_SHA = "unknown"

# iOS shortcut endpoints can't send auth headers; Mac clients send auth natively
_NO_AUTH_PATHS = {
    "/api/ios-telemetry",
    "/api/ios-event",
    "/api/ios-zone-event",
    "/api/healthz",
    "/api/login",
    "/login",
    "/manifest.json",
    "/favicon.svg",
    "/apple-touch-icon.svg",
    "/dashboard/manifest.json",
    "/dashboard/sw.js",
    "/dashboard/icon.svg",
    "/dashboard/apple-touch-icon.svg",
    "/dashboard/favicon.svg",
    "/dashboard/favicon.ico",
}


def _session_token(password: str) -> str:
    """Deterministic token derived from the password — no server-side state needed."""
    key = os.environ.get("SECRET_KEY", "vero-default-secret").encode()
    return hmac.new(key, password.encode(), hashlib.sha256).hexdigest()


def _verify_session_cookie(cookie: str) -> bool:
    password = os.environ.get("DASHBOARD_PASS", "").strip()
    if not password:
        return True
    expected = _session_token(password)
    return hmac.compare_digest(cookie, expected)
_NO_AUTH_PREFIXES = (
    "/dashboard/icons/",
    "/assets/",
)

# Brute-force protection: track failed attempts per IP
# { ip: {"count": int, "blocked_until": float} }
_failed_attempts: dict = {}
_MAX_FAILURES = 5
_BLOCK_SECONDS = 900  # 15 minutes


def _is_blocked(ip: str) -> bool:
    import time
    entry = _failed_attempts.get(ip)
    if not entry:
        return False
    if time.time() < entry.get("blocked_until", 0):
        return True
    # Block expired — clear it
    _failed_attempts.pop(ip, None)
    return False


def _record_failure(ip: str):
    import time
    entry = _failed_attempts.setdefault(ip, {"count": 0, "blocked_until": 0})
    entry["count"] += 1
    if entry["count"] >= _MAX_FAILURES:
        entry["blocked_until"] = time.time() + _BLOCK_SECONDS
        log.warning("Auth: IP %s blocked for 15 min after %d failures", ip, entry['count'])


def _clear_failures(ip: str):
    _failed_attempts.pop(ip, None)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if (
        path in _NO_AUTH_PATHS
        or path.startswith("/setup/")
        or any(path.startswith(prefix) for prefix in _NO_AUTH_PREFIXES)
    ):
        return await call_next(request)

    password = os.environ.get("DASHBOARD_PASS", "").strip()
    if not password:
        return await call_next(request)  # No password set — open (local dev)

    client_ip = request.client.host if request.client else "unknown"

    if _is_blocked(client_ip):
        return Response(content="Too many failed attempts. Try again in 15 minutes.", status_code=429)

    # 1. Check session cookie (browser login page)
    cookie = request.cookies.get("vero_session", "")
    if cookie and _verify_session_cookie(cookie):
        return await call_next(request)

    # 2. Check Basic Auth header (API clients: Mac agent, iOS shortcuts)
    # Accept either DASHBOARD_PASS or the full "user:pass" value stored in Mac app
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth[6:]).decode("utf-8")
            _, _, p = decoded.partition(":")
            # p is the password portion; if no colon, the whole value is the token
            token = p.strip() if p else decoded.strip()
            if secrets.compare_digest(token, password) or secrets.compare_digest(decoded.strip(), password):
                _clear_failures(client_ip)
                return await call_next(request)
        except Exception as e:
            log.debug("Auth middleware error for %s: %s", client_ip, e)

    # Browser request — redirect to login page instead of showing native dialog
    _record_failure(client_ip)
    accept = request.headers.get("Accept", "")
    if "text/html" in accept:
        return RedirectResponse(url="/login", status_code=302)
    return Response(content="Unauthorized", status_code=401)

_LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vero</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0f1117; color: #f1f5f9; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Inter', sans-serif;
         display: flex; align-items: center; justify-content: center; min-height: 100vh; -webkit-font-smoothing: antialiased; }
  .card { background: #1a1d27; border: 1px solid #2a2d3a; border-radius: 16px;
          padding: 40px 36px; width: 100%; max-width: 360px; box-shadow: 0 1px 3px rgba(0,0,0,0.3); }
  h1 { font-size: 20px; font-weight: 600; margin-bottom: 4px; color: #f1f5f9; }
  .subtitle { font-size: 13px; color: #94a3b8; margin-bottom: 28px; }
  label { display: block; font-size: 12px; font-weight: 500; color: #94a3b8; margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.05em; }
  input { width: 100%; background: #13161f; border: 1px solid #374151;
          border-radius: 8px; color: #f1f5f9; font-size: 15px; padding: 10px 14px; outline: none; }
  input:focus { border-color: #64748b; background: #1a1d27; }
  button { margin-top: 14px; width: 100%; background: #374151; border: none; border-radius: 8px;
           color: #fff; font-size: 14px; font-weight: 600; padding: 11px; cursor: pointer; }
  button:hover { background: #475569; }
  .error { margin-top: 14px; font-size: 13px; color: #EF4444; text-align: center; }
</style>
</head>
<body>
<div class="card">
  <h1>Vero</h1>
  <p class="subtitle">Enter your password to continue.</p>
  <form method="post" action="/api/login">
    <label for="pw">Password</label>
    <input id="pw" name="password" type="password" autocomplete="current-password" autofocus required>
    <button type="submit">Sign in</button>
  </form>
  {error_block}
</div>
</body>
</html>"""


@app.get("/login")
async def login_page(error: str = ""):
    error_block = '<p class="error">Incorrect password. Try again.</p>' if error else ""
    return HTMLResponse(_LOGIN_HTML.replace("{error_block}", error_block))


@app.post("/api/login")
async def do_login(request: Request):
    form = await request.form()
    pw = (form.get("password") or "").strip()
    password = os.environ.get("DASHBOARD_PASS", "").strip()
    client_ip = request.client.host if request.client else "unknown"

    if not password or secrets.compare_digest(pw, password):
        _clear_failures(client_ip)
        token = _session_token(password)
        response = RedirectResponse(url="/today", status_code=303)
        response.set_cookie(
            "vero_session", token,
            httponly=True, samesite="lax",
            max_age=86400 * 30,  # 30 days
            secure=False,  # Railway terminates TLS upstream
        )
        return response

    _record_failure(client_ip)
    return RedirectResponse(url="/login?error=1", status_code=303)


BACKEND_DIR = os.path.dirname(__file__)
LEGACY_FRONTEND_PATH = os.path.join(BACKEND_DIR, "frontend")
WEB_DIST_PATH = os.path.join(BACKEND_DIR, "web_dist")
WEB_ASSETS_PATH = os.path.join(WEB_DIST_PATH, "assets")
FRONTEND_DEV_URL = os.environ.get("FRONTEND_DEV_URL", "").rstrip("/")

if os.path.isdir(WEB_ASSETS_PATH):
    app.mount("/assets", StaticFiles(directory=WEB_ASSETS_PATH), name="web-assets")


def _frontend_index_response() -> Response:
    index_path = os.path.join(WEB_DIST_PATH, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    if FRONTEND_DEV_URL:
        return RedirectResponse(url=f"{FRONTEND_DEV_URL}/today")
    return HTMLResponse(
        """
        <html><body style="font-family: ui-sans-serif, system-ui; padding: 2rem;">
        <h1>Vero frontend not built</h1>
        <p>Run <code>npm install</code> and <code>npm run build</code> in <code>web/</code>, or set <code>FRONTEND_DEV_URL</code>.</p>
        </body></html>
        """,
        status_code=503,
    )


@app.get("/")
async def redirect_to_dashboard():
    return RedirectResponse(url="/today")


@app.get("/dashboard")
@app.get("/dashboard/")
@app.get("/dashboard/{rest:path}")
async def legacy_dashboard_redirect(rest: str = ""):
    return RedirectResponse(url="/today")


def _serve_web_file(filename: str) -> Response:
    target = os.path.join(WEB_DIST_PATH, filename)
    if os.path.exists(target):
        return FileResponse(target)
    legacy_target = os.path.join(LEGACY_FRONTEND_PATH, filename)
    if os.path.exists(legacy_target):
        return FileResponse(legacy_target)
    raise HTTPException(status_code=404, detail=f"{filename} not found")


@app.get("/manifest.json")
async def serve_manifest():
    return _serve_web_file("manifest.json")


@app.get("/favicon.svg")
async def serve_favicon_svg():
    return _serve_web_file("favicon.svg")


@app.get("/apple-touch-icon.svg")
async def serve_touch_icon():
    return _serve_web_file("apple-touch-icon.svg")


@app.get("/today")
@app.get("/setup")
@app.get("/diagnostics")
@app.get("/zones")
@app.get("/settings")
async def serve_web_app():
    return _frontend_index_response()


@app.on_event("startup")
async def initialize_runtime():
    _STARTUP_STATUS["process_ready"] = True
    _STARTUP_STATUS["database_ready"] = False
    _STARTUP_STATUS["startup_migrations_ok"] = False
    _STARTUP_STATUS["startup_errors"] = []

    # Run all synchronous DB work in a thread so we don't block the event loop.
    # Use a timeout so Railway's healthcheck isn't held up by slow cold-start DB
    # connections (SSL handshake, pgbouncer, etc.).
    import concurrent.futures

    def _init_db_sync():
        try:
            Base.metadata.create_all(bind=engine)
            _STARTUP_STATUS["database_ready"] = True
        except Exception as exc:
            msg = f"Schema init failed: {exc}"
            _STARTUP_STATUS["startup_errors"].append(msg)
            log.error(msg)

        try:
            migration_errors = _run_migrations()
            if migration_errors:
                for migration_error in migration_errors:
                    msg = f"Lightweight migrations failed: {migration_error}"
                    _STARTUP_STATUS["startup_errors"].append(msg)
                    log.error(msg)
                _STARTUP_STATUS["startup_migrations_ok"] = False
            else:
                _STARTUP_STATUS["startup_migrations_ok"] = True
        except Exception as exc:
            msg = f"Lightweight migrations failed: {exc}"
            _STARTUP_STATUS["startup_errors"].append(msg)
            log.error(msg)

        try:
            with SessionLocal() as db:
                agent_logic.ensure_default_settings(db)
            _STARTUP_STATUS["database_ready"] = True
        except Exception as exc:
            msg = f"Default settings init failed: {exc}"
            _STARTUP_STATUS["startup_errors"].append(msg)
            log.error(msg)

    loop = asyncio.get_running_loop()
    try:
        # 20s timeout — Railway's healthcheck allows 30s; we need to be ready in time
        await asyncio.wait_for(loop.run_in_executor(None, _init_db_sync), timeout=20.0)
    except asyncio.TimeoutError:
        msg = "DB startup timed out after 20s; continuing anyway"
        _STARTUP_STATUS["startup_errors"].append(msg)
        log.warning(msg)
    except Exception as exc:
        msg = f"DB startup error: {exc}"
        _STARTUP_STATUS["startup_errors"].append(msg)
        log.error(msg)

    # Start background task for hourly summary generation (even if Mac is offline)
    loop.create_task(_hourly_summary_scheduler())
    loop.create_task(_calendar_sync_scheduler())


async def _hourly_summary_scheduler():
    """Background task: generates hourly summaries. Runs every 5 min but only
    does real work in the first 15 minutes of each hour, or when a summary is
    still missing/deterministic (catch-up after downtime or LLM quota hit)."""
    await asyncio.sleep(10)  # Wait 10s for DB to stabilize on startup
    while True:
        try:
            await asyncio.sleep(300)  # Check every 5 minutes
            now = datetime.now(timezone.utc)
            # Skip the expensive work if we're well into the hour and already
            # have a good LLM summary for the previous hour.
            if now.minute > 15:
                db = SessionLocal()
                try:
                    prev_hour_start = (now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)).replace(tzinfo=None)
                    existing = db.query(HourlySummary).filter(HourlySummary.hour_start == prev_hour_start).first()
                    if existing and getattr(existing, "summary_source", "") == "llm":
                        continue  # Good summary already exists — nothing to do
                finally:
                    db.close()
            db = SessionLocal()
            try:
                summaries_enabled = agent_logic.get_state(db, "hourly_summaries_enabled", "true") == "true"
                if summaries_enabled:
                    await agent_logic._generate_and_store_hourly_summary(db, now)
            finally:
                db.close()
        except Exception as exc:
            log.error(f"Hourly summary scheduler error: {exc}")


async def _calendar_sync_scheduler():
    """Background task: syncs iCal feed every 30 minutes if a URL is configured."""
    await asyncio.sleep(15)  # Stagger slightly after hourly summary scheduler
    while True:
        try:
            db = SessionLocal()
            try:
                url = agent_logic.get_state(db, "calendar_ical_url", "").strip()
                if url:
                    await agent_logic.sync_ical_calendar(db)
            finally:
                db.close()
        except Exception as exc:
            log.error("Calendar sync scheduler error: %s", exc)
        await asyncio.sleep(30 * 60)  # Every 30 minutes


def _run_async(coro):
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


def _normalize_battery_level(battery_level: float | None) -> int | None:
    if battery_level is None:
        return None
    raw = float(battery_level)
    return int(raw) if raw > 1 else int(raw * 100)


def _coerce_bool(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y", "on"}:
        return True
    if text in {"false", "0", "no", "n", "off"}:
        return False
    return default


def _parse_event_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        normalized = value.strip()
        if normalized.endswith("Z"):
            normalized = f"{normalized[:-1]}+00:00"
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _serialize_calendar_job(job: CalendarEventJob) -> dict:
    return {
        "id": job.id,
        "kind": job.kind,
        "title": job.title,
        "notes": job.notes or "",
        "start_at": job.start_at.isoformat() if job.start_at else "",
        "end_at": job.end_at.isoformat() if job.end_at else "",
        "status": job.status,
        "attempts": job.attempts,
        "last_error": job.last_error or "",
        "payload_json": job.payload_json or "{}",
        "created_at": job.created_at.isoformat() if job.created_at else "",
        "updated_at": job.updated_at.isoformat() if job.updated_at else "",
    }


def _build_state_payload(db: Session) -> dict:
    agent_logic.ensure_default_settings(db)
    states = agent_logic.get_all_states(db)
    now = datetime.now(timezone.utc)
    capture_interval_seconds = agent_logic.get_capture_interval_seconds(db)

    last_ios_event_age_seconds = None
    last_ios_ping_age_seconds = None
    last_ios_event_str = states.get("last_ios_event") or states.get("last_ios_ping") or ""
    last_ios_ping_str = states.get("last_ios_ping", "")
    if last_ios_event_str:
        try:
            last_ios_event_age_seconds = int((now - datetime.fromisoformat(last_ios_event_str)).total_seconds())
        except Exception:
            last_ios_event_age_seconds = None
    if last_ios_ping_str:
        try:
            last_ios_ping_age_seconds = int((now - datetime.fromisoformat(last_ios_ping_str)).total_seconds())
        except Exception:
            last_ios_ping_age_seconds = None

    mac_status = agent_logic.compute_mac_status(states, now)
    states["backend_target_url"] = _get_backend_url()
    states["capture_interval_seconds"] = capture_interval_seconds
    states["polling_interval_seconds"] = capture_interval_seconds
    states["classification_interval_seconds"] = max(300, capture_interval_seconds)
    states["privacy_mode"] = agent_logic.get_state(db, "privacy_mode", agent_logic.DEFAULTS["privacy_mode"])
    states["calendar_sync_enabled"] = agent_logic.get_state(db, "calendar_sync_enabled", agent_logic.DEFAULTS["calendar_sync_enabled"]).lower() == "true"
    states["mac_online_threshold_seconds"] = max(180, capture_interval_seconds * 2 + 30)
    states["last_mac_ping_age_seconds"] = mac_status["last_mac_snapshot_age_seconds"]
    states["last_mac_heartbeat_age_seconds"] = mac_status["last_mac_heartbeat_age_seconds"]
    states["last_mac_snapshot_age_seconds"] = mac_status["last_mac_snapshot_age_seconds"]
    states["last_mac_capture_age_seconds"] = mac_status["last_mac_capture_age_seconds"]
    states["last_ios_ping_age_seconds"] = last_ios_ping_age_seconds
    states["last_ios_event_age_seconds"] = last_ios_event_age_seconds
    states["ios_recent_ping"] = (last_ios_ping_age_seconds is not None and last_ios_ping_age_seconds < 3600)
    states["ios_recent_event"] = (last_ios_event_age_seconds is not None and last_ios_event_age_seconds < 3600)
    states["sleep_source"] = agent_logic.get_state(db, "sleep_source", "iphone_only")
    states["sleep_status_note"] = (
        "Sleep detection inactive until iPhone automation pings."
        if not states["ios_recent_event"] else
        "Sleep detection active from iPhone telemetry."
    )
    states["mac_online"] = mac_status["mac_online"]
    states["mac_status"] = mac_status["mac_status"]
    states["mac_status_reason"] = mac_status["mac_status_reason"]
    states["mac_idle"] = mac_status.get("mac_idle", False)
    states["presence_state"] = mac_status.get("presence_state")
    states["screen_state"] = mac_status.get("screen_state")
    _is_walking = states.get("is_walking") == "true"
    _cur_loc = states.get("current_location", "")
    _zone_until = agent_logic._parse_iso_dt(states.get("zone_activity_until"))
    if _is_walking:
        states["presence_display"] = "walking"
    elif _cur_loc and not _cur_loc.startswith("Outside ") and _zone_until and now < _zone_until:
        states["presence_display"] = "at_location"
    elif _cur_loc.startswith("Outside "):
        states["presence_display"] = "away_from_location"
    else:
        states["presence_display"] = states.get("presence_state") or "unknown"
    states["last_presence_change_at"] = states.get("last_presence_change_at", "")
    states["last_capture_at"] = states.get("last_capture_at", states.get("last_mac_ping", ""))
    states["last_heartbeat_at"] = states.get("last_mac_heartbeat", "")
    states["mac_launch_url"] = "vero://open"
    states["last_mac_heartbeat"] = states.get("last_mac_heartbeat", "")
    states["service_health"] = "ok" if mac_status["mac_status"] in {"online"} else (
        "degraded" if mac_status["mac_status"] in {"degraded", "paused"} else "offline"
    )
    states["likely_asleep"] = agent_logic.get_state(db, "likely_asleep", "false")
    states["likely_asleep_reason"] = agent_logic.get_state(db, "likely_asleep_reason", "")
    states["likely_asleep_confidence"] = agent_logic.get_state(db, "likely_asleep_confidence", "0.0")
    states["current_intent"] = agent_logic.get_state(db, "context_current_intent", "")
    return states

def _bg_process_mac(data: MacTelemetry):
    """Run mac telemetry processing in its own thread + event loop (FastAPI-safe)."""
    def _run():
        db = SessionLocal()
        try:
            asyncio.run(agent_logic.process_mac_telemetry(data, db))
        except Exception as e:
            log.error("Background mac telemetry error: %s", e)
        finally:
            db.close()
    threading.Thread(target=_run, daemon=True).start()


def _bg_process_ios(data: iOSTelemetry):
    """Run ios telemetry processing in its own thread + event loop (FastAPI-safe)."""
    def _run():
        db = SessionLocal()
        try:
            asyncio.run(agent_logic.process_ios_telemetry(data, db))
        except Exception as e:
            log.error("Background ios telemetry error: %s", e)
        finally:
            db.close()
    threading.Thread(target=_run, daemon=True).start()


def _bg_process_heartbeat(data: MacHeartbeat):
    """Run mac heartbeat processing in its own thread + event loop (FastAPI-safe)."""
    def _run():
        db = SessionLocal()
        try:
            asyncio.run(agent_logic.process_mac_heartbeat(data, db))
        except Exception as e:
            log.error("Background mac heartbeat error: %s", e)
        finally:
            db.close()
    threading.Thread(target=_run, daemon=True).start()


def _bg_process_mac_presence(data: MacPresence):
    """Run mac presence processing in its own thread + event loop (FastAPI-safe)."""
    def _run():
        db = SessionLocal()
        try:
            asyncio.run(agent_logic.process_mac_presence(data, db))
        except Exception as e:
            log.error("Background mac presence error: %s", e)
        finally:
            db.close()
    threading.Thread(target=_run, daemon=True).start()


def _bg_process_ios_zone(data: iOSZoneEvent):
    """Run iOS zone event processing in its own thread + event loop (FastAPI-safe)."""
    def _run():
        db = SessionLocal()
        try:
            asyncio.run(agent_logic.process_ios_zone_event(data, db))
        except Exception as e:
            log.error("Background ios zone event error: %s", e)
        finally:
            db.close()
    threading.Thread(target=_run, daemon=True).start()


@app.post("/api/mac-telemetry")
def receive_mac_telemetry(data: MacTelemetry, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    privacy_mode = agent_logic.get_state(db, "privacy_mode", agent_logic.DEFAULTS["privacy_mode"])
    presence_state = agent_logic.normalize_presence_state(data.presence_state, data.idle_time_seconds)
    screen_state = agent_logic.normalize_screen_state(data.screen_state, presence_state)
    sanitized_title = agent_logic.sanitize_window_title(
        data.app_name,
        data.window_title,
        privacy_mode,
        bool(data.detailed_capture_enabled),
    )
    log_entry = ActivityLog(
        device="mac",
        app_name=data.app_name,
        window_title=sanitized_title,
        is_idle=presence_state != "active",
        presence_state=presence_state,
        screen_state=screen_state,
    )
    db.add(log_entry)
    db.commit()

    background_tasks.add_task(_bg_process_mac, data)
    pending_prompt = agent_logic.get_pending_prompt(db)
    return {"status": "ok", "prompt": pending_prompt}


@app.post("/api/mac-heartbeat")
def receive_mac_heartbeat(data: MacHeartbeat, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    background_tasks.add_task(_bg_process_heartbeat, data)
    states = _build_state_payload(db)
    return {
        "status": "ok",
        "mac_status": states["mac_status"],
        "mac_status_reason": states["mac_status_reason"],
        "tracking_enabled": str(states.get("tracking_enabled", "true")).lower() == "true",
    }


@app.post("/api/mac-presence")
def receive_mac_presence(data: MacPresence, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    background_tasks.add_task(_bg_process_mac_presence, data)
    states = _build_state_payload(db)
    return {
        "status": "ok",
        "presence_state": states.get("presence_state"),
        "screen_state": states.get("screen_state"),
    }


@app.post("/api/ios-telemetry")
def receive_ios_telemetry(data: iOSTelemetry, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    batt_pct = _normalize_battery_level(data.battery_level)

    log_entry = ActivityLog(
        device="ios",
        location_label=data.location_label,
        activity_type=data.activity_type,
        latitude=data.latitude,
        longitude=data.longitude,
        steps_today=data.steps_today,
        battery_pct=batt_pct,
    )
    db.add(log_entry)
    db.commit()

    background_tasks.add_task(_bg_process_ios, data)
    return {"status": "ok"}


@app.get("/api/ios-event")
def receive_ios_event(kind: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """GET endpoint for charging and walking events. No JSON body required.
    kind: charge_on | charge_off | walking
    """
    kind = (kind or "").lower().strip()
    if kind == "charge_on":
        data = iOSTelemetry(activity_type="Stationary", is_charging=True)
        display_type = "Charging On"
    elif kind == "charge_off":
        data = iOSTelemetry(activity_type="Stationary", is_charging=False)
        display_type = "Charging Off"
    elif kind == "walking":
        data = iOSTelemetry(activity_type="Walking")
        display_type = "Walking"
    else:
        raise HTTPException(status_code=400, detail=f"Unknown kind: {kind!r}. Valid: charge_on, charge_off, walking")

    log_entry = ActivityLog(device="ios", activity_type=display_type)
    db.add(log_entry)
    db.commit()
    background_tasks.add_task(_bg_process_ios, data)
    return {"status": "ok", "kind": kind}


@app.api_route("/api/ios-zone-event", methods=["GET", "POST"])
async def receive_ios_zone_event(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    body_text = ""
    payload: Dict[str, Any] = {}
    if request.method == "POST":
        body_bytes = await request.body()
        # Rescue iPhone Smart Punctuation curly quotes
        body_text = body_bytes.decode("utf-8", errors="ignore").replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")

    zone_slug = request.query_params.get("zone", "") or request.query_params.get("zone_slug", "")
    transition = request.query_params.get("transition", "")
    battery_level = request.query_params.get("battery_level")
    steps_today = request.query_params.get("steps_today")
    event_time = request.query_params.get("event_time")

    if body_text.strip():
        import json
        try:
            payload = json.loads(body_text)
            zone_slug = zone_slug or payload.get("zone_slug", "") or payload.get("zone", "")
            transition = transition or payload.get("transition", "")
            battery_level = battery_level if battery_level is not None else payload.get("battery_level")
            steps_today = steps_today if steps_today is not None else payload.get("steps_today")
            event_time = event_time or payload.get("event_time")
        except json.JSONDecodeError:
            log.warning("Failed to parse iOS zone event JSON: %s", body_text)

    zone_slug = agent_logic.normalize_zone_slug(zone_slug or "")
    transition = str(transition or "").strip().lower()
    if not zone_slug or not transition:
        return {"status": "error", "reason": "missing zone_slug or transition"}
    if transition not in {"enter", "exit"}:
        return {"status": "error", "reason": "transition must be 'enter' or 'exit'"}

    parsed_battery = None
    if battery_level not in (None, ""):
        try:
            parsed_battery = float(battery_level)
        except Exception:
            parsed_battery = None
    parsed_steps = None
    if steps_today not in (None, ""):
        try:
            parsed_steps = int(steps_today)
        except Exception:
            parsed_steps = None

    data = iOSZoneEvent(
        zone_slug=zone_slug,
        transition=transition,
        event_time=_parse_event_time(event_time),
        battery_level=parsed_battery,
        steps_today=parsed_steps,
    )
    event_timestamp = (
        data.event_time.astimezone(timezone.utc).replace(tzinfo=None)
        if data.event_time
        else datetime.now(timezone.utc).replace(tzinfo=None)
    )

    zone = agent_logic.get_zone(db, data.zone_slug)
    zone_label = zone.name if zone else data.zone_slug.replace("-", " ").title()
    log_entry = ActivityLog(
        timestamp=event_timestamp,
        device="ios",
        location_label=zone_label,
        activity_type=f"Zone {data.transition.title()}",
        battery_pct=_normalize_battery_level(data.battery_level),
        steps_today=data.steps_today,
    )
    db.add(log_entry)
    db.commit()
    background_tasks.add_task(_bg_process_ios_zone, data)
    return {"status": "ok", "zone": zone_label, "transition": data.transition}


@app.get("/api/state")
def get_state(db: Session = Depends(get_db)):
    return _build_state_payload(db)

@app.get("/api/settings")
def get_settings(db: Session = Depends(get_db)):
    agent_logic.ensure_default_settings(db)
    tracking_enabled_str = agent_logic.get_state(db, "tracking_enabled", "true")
    capture_interval_seconds = agent_logic.get_capture_interval_seconds(db)
    return {
        "capture_interval_seconds": capture_interval_seconds,
        "polling_interval_seconds": capture_interval_seconds,
        "tracking_enabled": tracking_enabled_str.lower() == "true",
        "backend_mode": agent_logic.get_state(db, "backend_mode", "railway_primary"),
        "ai_provider": agent_logic.get_state(db, "ai_provider", "auto"),
        "llm_mode": agent_logic.get_state(db, "llm_mode", agent_logic.DEFAULTS["llm_mode"]),
        "hourly_summaries_enabled": agent_logic.get_state(db, "hourly_summaries_enabled", agent_logic.DEFAULTS["hourly_summaries_enabled"]).lower() == "true",
        "classification_interval_seconds": max(300, capture_interval_seconds),
        "llm_daily_cap": int(agent_logic.get_state(db, "llm_daily_cap", agent_logic.DEFAULTS["llm_daily_cap"])),
        "user_timezone": agent_logic.get_state(db, "user_timezone", agent_logic.DEFAULTS["user_timezone"]),
        "privacy_mode": agent_logic.get_state(db, "privacy_mode", agent_logic.DEFAULTS["privacy_mode"]),
        "calendar_sync_enabled": agent_logic.get_state(db, "calendar_sync_enabled", agent_logic.DEFAULTS["calendar_sync_enabled"]).lower() == "true",
        "calendar_ical_url": agent_logic.get_state(db, "calendar_ical_url", ""),
        "calendar_last_sync": agent_logic.get_state(db, "calendar_last_sync", ""),
        "calendar_sync_error": agent_logic.get_state(db, "calendar_sync_error", ""),
    }

@app.post("/api/settings")
def update_settings(payload: Dict[str, Any], db: Session = Depends(get_db)):
    agent_logic.ensure_default_settings(db)
    if "capture_interval_seconds" in payload:
        try:
            agent_logic.set_capture_interval_seconds(db, int(payload["capture_interval_seconds"]))
        except Exception:
            raise HTTPException(status_code=400, detail="capture_interval_seconds must be an integer >= 60")
    if "polling_interval_seconds" in payload:
        try:
            agent_logic.set_capture_interval_seconds(db, int(payload["polling_interval_seconds"]))
        except Exception:
            raise HTTPException(status_code=400, detail="polling_interval_seconds must be an integer >= 60")
    if "tracking_enabled" in payload:
        agent_logic.set_state(db, "tracking_enabled", str(payload["tracking_enabled"]).lower())
    if "backend_mode" in payload and payload["backend_mode"] in {"railway_primary", "local_primary", "hybrid_auto"}:
        agent_logic.set_state(db, "backend_mode", payload["backend_mode"])
    if "ai_provider" in payload and payload["ai_provider"] in {"auto", "gemini", "openai"}:
        agent_logic.set_state(db, "ai_provider", payload["ai_provider"])
        os.environ["VERO_AI_PROVIDER"] = payload["ai_provider"]
    if "llm_mode" in payload and payload["llm_mode"] in {"ultra_save", "balanced", "quality"}:
        agent_logic.set_state(db, "llm_mode", payload["llm_mode"])
    if "hourly_summaries_enabled" in payload:
        agent_logic.set_state(db, "hourly_summaries_enabled", str(_coerce_bool(payload["hourly_summaries_enabled"])).lower())
    if "llm_daily_cap" in payload:
        try:
            val = max(1, int(payload["llm_daily_cap"]))
            agent_logic.set_state(db, "llm_daily_cap", str(val))
        except Exception:
            raise HTTPException(status_code=400, detail="llm_daily_cap must be an integer >= 1")
    if "privacy_mode" in payload:
        privacy_mode = str(payload["privacy_mode"]).strip().lower()
        if privacy_mode not in {"private", "detailed"}:
            raise HTTPException(status_code=400, detail="privacy_mode must be 'private' or 'detailed'")
        agent_logic.set_state(db, "privacy_mode", privacy_mode)
    if "calendar_sync_enabled" in payload:
        agent_logic.set_state(db, "calendar_sync_enabled", str(_coerce_bool(payload["calendar_sync_enabled"])).lower())
    if "calendar_ical_url" in payload:
        agent_logic.set_state(db, "calendar_ical_url", str(payload["calendar_ical_url"]).strip())
    if "user_timezone" in payload:
        from zoneinfo import ZoneInfo
        tz_name = str(payload["user_timezone"])
        try:
            ZoneInfo(tz_name)  # validate
            agent_logic.set_state(db, "user_timezone", tz_name)
        except Exception:
            raise HTTPException(status_code=400, detail=f"Invalid timezone: {tz_name}")
    return {"status": "updated"}


@app.get("/api/context/preferences")
def get_context_preferences(db: Session = Depends(get_db)):
    return agent_logic.get_context_preferences(db)


@app.post("/api/context/preferences")
def post_context_preferences(payload: Dict[str, Any], db: Session = Depends(get_db)):
    try:
        prefs = agent_logic.update_context_preferences(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "updated", "preferences": prefs}


@app.get("/api/version")
async def api_version():
    return {
        "build_version": _BUILD_VERSION,
        "deployment_channel": _DEPLOYMENT_CHANNEL,
        "git_sha": _GIT_SHA,
        "started_at": _STARTED_AT.isoformat(),
    }


@app.get("/api/zones")
def get_zones(db: Session = Depends(get_db)):
    return {"zones": agent_logic.list_zones(db)}


@app.post("/api/zones")
def create_zone(payload: Dict[str, Any], db: Session = Depends(get_db)):
    try:
        zone = agent_logic.upsert_zone(db, payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_zone_payload", "message": str(exc)},
        )
    return {"status": "created", "zone": zone}


@app.patch("/api/zones/{zone_id}")
def patch_zone(zone_id: int, payload: Dict[str, Any], db: Session = Depends(get_db)):
    try:
        zone = agent_logic.upsert_zone(db, payload, zone_id=zone_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_zone_payload", "message": str(exc)},
        )
    return {"status": "updated", "zone": zone}


@app.delete("/api/zones/{zone_id}")
def remove_zone(zone_id: int, db: Session = Depends(get_db)):
    if not agent_logic.delete_zone(db, zone_id):
        raise HTTPException(status_code=404, detail="Zone not found")
    return {"status": "deleted"}


@app.get("/api/calendar/jobs")
def get_calendar_jobs(limit: int = 25, status: str = "pending", db: Session = Depends(get_db)):
    query = db.query(CalendarEventJob)
    if status and status != "all":
        query = query.filter(CalendarEventJob.status == status)
    jobs = query.order_by(CalendarEventJob.created_at).limit(max(1, min(limit, 100))).all()
    return {"jobs": [_serialize_calendar_job(job) for job in jobs]}


@app.post("/api/calendar/jobs/{job_id}/ack")
def ack_calendar_job(job_id: int, db: Session = Depends(get_db)):
    job = db.query(CalendarEventJob).filter(CalendarEventJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Calendar job not found")
    job.status = "done"
    job.last_error = ""
    db.commit()
    db.refresh(job)
    return {"status": "acknowledged", "job": _serialize_calendar_job(job)}


@app.post("/api/calendar/jobs/{job_id}/fail")
def fail_calendar_job(job_id: int, payload: Dict[str, Any], db: Session = Depends(get_db)):
    job = db.query(CalendarEventJob).filter(CalendarEventJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Calendar job not found")
    job.status = "failed"
    job.attempts = (job.attempts or 0) + 1
    job.last_error = str(payload.get("error") or "Unknown error")
    db.commit()
    db.refresh(job)
    return {"status": "failed", "job": _serialize_calendar_job(job)}


@app.post("/api/calendar/sync-now")
async def calendar_sync_now(db: Session = Depends(get_db)):
    """Manually trigger an iCal feed sync."""
    result = await agent_logic.sync_ical_calendar(db)
    return result


@app.get("/api/calendar/today")
def get_calendar_today(db: Session = Depends(get_db)):
    """Return today's calendar events in the user's local timezone, sorted by start time."""
    tz = agent_logic.resolve_user_timezone(db)
    now_local = datetime.now(timezone.utc).astimezone(tz)
    day_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).replace(tzinfo=None)
    day_end = now_local.replace(hour=23, minute=59, second=59, microsecond=0).astimezone(timezone.utc).replace(tzinfo=None)
    now_utc_naive = datetime.now(timezone.utc).replace(tzinfo=None)

    events = (
        db.query(UserCalendarEvent)
        .filter(UserCalendarEvent.start_at < day_end, UserCalendarEvent.end_at > day_start)
        .order_by(UserCalendarEvent.start_at)
        .all()
    )

    def _local_iso(dt):
        if dt is None:
            return ""
        return dt.replace(tzinfo=timezone.utc).astimezone(tz).isoformat()

    return [
        {
            "id": e.id,
            "title": e.title,
            "start_at": _local_iso(e.start_at),
            "end_at": _local_iso(e.end_at),
            "calendar_name": e.calendar_name,
            "is_current": e.start_at <= now_utc_naive <= e.end_at,
            "is_past": e.end_at < now_utc_naive,
        }
        for e in events
    ]


@app.post("/api/mac-calendar-events")
def upsert_mac_calendar_events(events: list[CalendarEventItem], db: Session = Depends(get_db)):
    """Mac companion pushes today's calendar events for cross-referencing in AI summaries."""
    upserted = 0
    for ev in events:
        start_utc = ev.start_at.replace(tzinfo=None) if ev.start_at.tzinfo else ev.start_at
        end_utc = ev.end_at.replace(tzinfo=None) if ev.end_at.tzinfo else ev.end_at
        if ev.event_uid:
            existing = db.query(UserCalendarEvent).filter(UserCalendarEvent.event_uid == ev.event_uid).first()
            if existing:
                existing.title = ev.title
                existing.start_at = start_utc
                existing.end_at = end_utc
                existing.calendar_name = ev.calendar_name
                existing.notes = ev.notes
                upserted += 1
                continue
        db.add(UserCalendarEvent(
            event_uid=ev.event_uid,
            title=ev.title,
            start_at=start_utc,
            end_at=end_utc,
            calendar_name=ev.calendar_name,
            notes=ev.notes,
        ))
        upserted += 1
    db.commit()
    return {"status": "ok", "upserted": upserted}


@app.post("/mcp")
async def mcp_http_transport(payload: Dict[str, Any], db: Session = Depends(get_db)):
    method = str(payload.get("method") or "").strip()
    params = payload.get("params") or {}

    if method == "get_current_state":
        return {"result": _build_state_payload(db)}
    if method == "get_recent_logs":
        limit = max(1, min(int(params.get("limit", 15)), 100))
        logs = db.query(ActivityLog).order_by(desc(ActivityLog.timestamp)).limit(limit).all()
        return {
            "result": [
                {
                    "id": l.id,
                    "timestamp": l.timestamp.isoformat() if l.timestamp else "",
                    "device": l.device,
                    "app_name": l.app_name,
                    "window_title": l.window_title,
                    "is_idle": l.is_idle,
                    "location_label": l.location_label,
                    "activity_type": l.activity_type,
                    "steps_today": l.steps_today,
                    "battery_pct": l.battery_pct,
                    "presence_state": l.presence_state,
                    "screen_state": l.screen_state,
                }
                for l in logs
            ]
        }
    if method == "get_daily_analytics":
        return {"result": await analytics_today(db)}
    if method == "set_tracking":
        enabled = _coerce_bool(params.get("enabled"), True)
        agent_logic.set_state(db, "tracking_enabled", str(enabled).lower())
        return {"result": {"tracking_enabled": enabled}}
    if method == "set_polling_interval":
        seconds = max(60, int(params.get("seconds", 60)))
        agent_logic.set_capture_interval_seconds(db, seconds)
        return {"result": {"capture_interval_seconds": seconds, "polling_interval_seconds": seconds}}
    if method == "send_checkin":
        message = str(params.get("message") or "").strip()
        if not message:
            raise HTTPException(status_code=400, detail="message is required")
        return {"result": await chat_message({"message": message}, db)}
    if method == "get_pending_checkin":
        return {"result": get_checkin(db)}
    if method == "reply_to_prompt":
        reply = str(params.get("reply") or "").strip()
        return {"result": handle_prompt_reply({"reply": reply}, db)}
    if method == "list_zones":
        return {"result": {"zones": agent_logic.list_zones(db)}}
    if method == "upsert_zone":
        try:
            return {"result": {"zone": agent_logic.upsert_zone(db, params)}}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    raise HTTPException(status_code=404, detail=f"Unknown MCP method: {method}")

@app.get("/api/logs")
def get_logs(limit: int = 50, db: Session = Depends(get_db)):
    logs = db.query(ActivityLog).order_by(desc(ActivityLog.timestamp)).limit(limit).all()
    return [
        {
            "id": entry.id,
            "timestamp": entry.timestamp.isoformat() if entry.timestamp else "",
            "device": entry.device,
            "app_name": entry.app_name,
            "window_title": entry.window_title,
            "is_idle": entry.is_idle,
            "location_label": entry.location_label,
            "activity_type": entry.activity_type,
            "steps_today": entry.steps_today,
            "battery_pct": entry.battery_pct,
            "presence_state": entry.presence_state,
            "screen_state": entry.screen_state,
        }
        for entry in logs
    ]


@app.post("/api/logs/clear")
def clear_logs(payload: Dict[str, Any], db: Session = Depends(get_db)):
    minutes = payload.get("minutes")  # int or None (None = all today)
    if minutes is not None:
        try:
            minutes = int(minutes)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="minutes must be an integer")
    count = agent_logic.clear_recent_logs(db, minutes=minutes)
    return {"status": "cleared", "count": count}


@app.post("/api/manual-log")
def create_manual_log(payload: Dict[str, Any], db: Session = Depends(get_db)):
    from datetime import datetime, timezone as tz
    entry = ActivityLog(
        timestamp=datetime.now(tz.utc),
        device="manual",
        app_name=payload.get("label", "Manual entry"),
        activity_type=payload.get("activity_type", "manual"),
        window_title=payload.get("note") or "",
        presence_state="active",
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return {"status": "logged", "id": entry.id}


def _fallback_summary_payload(entry: ActivityLog, context_logs: list[ActivityLog] | None = None) -> dict:
    context_logs = context_logs or []
    if entry.device == "ios":
        event = (entry.activity_type or "location event").strip()
        place = (entry.location_label or "an unknown place").strip()
        signals = [f"event: {event}", f"location: {place}"]
        if entry.steps_today is not None:
            signals.append(f"steps: {entry.steps_today}")
        if entry.battery_pct is not None:
            signals.append(f"battery: {entry.battery_pct}%")
        text = f"iPhone reported {event.lower()} near {place}. Keep zone automations running so future summaries stay accurate."
        return {
            "summary_text": text,
            "focus_assessment": "unknown",
            "confidence": 0.6,
            "signals": signals[:4],
            "fallback_used": True,
            "summary": text,
        }

    app_name = (entry.app_name or "unknown app").strip()
    title = (entry.window_title or "").strip()
    nearby_apps = sorted({(log.app_name or "").strip() for log in context_logs if (log.app_name or "").strip()})
    if nearby_apps:
        signal = ", ".join(nearby_apps[:4])
        text = f"Most likely focused in {app_name} with related context from {signal}. Continue your current task or note a manual check-in if this was a context switch."
    elif title:
        text = f"Most likely worked in {app_name} on '{title[:80]}'. If that was not intentional work, add a quick check-in to correct context."
    else:
        text = f"Most likely worked in {app_name}. Add a brief check-in when switching tasks to keep summaries accurate."
    return {
        "summary_text": text,
        "focus_assessment": "mixed",
        "confidence": 0.45,
        "signals": [f"app: {app_name}", f"title: {title[:80] or 'n/a'}"],
        "fallback_used": True,
        "summary": text,
    }


@app.get("/api/summary/{log_id}")
async def get_log_summary(log_id: int, db: Session = Depends(get_db)):
    entry = db.query(ActivityLog).filter(ActivityLog.id == log_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Log not found")

    context_logs: list[ActivityLog] = []
    if entry.timestamp:
        window_start = entry.timestamp - timedelta(minutes=20)
        window_end = entry.timestamp + timedelta(minutes=20)
        context_logs = (
            db.query(ActivityLog)
            .filter(
                ActivityLog.device == entry.device,
                ActivityLog.timestamp >= window_start,
                ActivityLog.timestamp <= window_end,
            )
            .order_by(ActivityLog.timestamp.asc())
            .limit(25)
            .all()
        )

    if entry.device == "mac" and agent_logic.can_use_llm(db):
        agent_logic.register_llm_call(db)
        structured = await llm_client.generate_activity_summary_structured(entry, context_logs)
        if structured and structured.get("summary_text"):
            structured["summary"] = structured["summary_text"]
            return structured

    return _fallback_summary_payload(entry, context_logs)

@app.get("/api/hourly-summaries")
def get_hourly_summaries(limit: int = 5, db: Session = Depends(get_db)):
    tz = agent_logic.resolve_user_timezone(db)
    summaries = db.query(HourlySummary).order_by(desc(HourlySummary.hour_start)).limit(limit).all()
    return [
        {
            "id": s.id,
            "hour_start": s.hour_start,
            "hour_start_utc": s.hour_start.isoformat() if s.hour_start else "",
            "hour_start_local": (
                s.hour_start.replace(tzinfo=timezone.utc).astimezone(tz).isoformat()
                if s.hour_start else ""
            ),
            "summary_text": s.summary_text,
            "productivity_score": s.productivity_score,
            "source": getattr(s, "summary_source", "llm"),
            "confidence": getattr(s, "confidence", None),
            "fallback_used": bool(getattr(s, "fallback_used", False)),
        }
        for s in summaries
    ]


@app.delete("/api/hourly-summaries/{summary_id}")
def delete_hourly_summary(summary_id: int, db: Session = Depends(get_db)):
    summary = db.query(HourlySummary).filter(HourlySummary.id == summary_id).first()
    if not summary:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete(summary)
    db.commit()
    return {"status": "deleted"}


async def _run_hourly_summary_bg(now: datetime):
    db = SessionLocal()
    try:
        # force_current=True: generate for what the user has done so far this hour
        await agent_logic._generate_and_store_hourly_summary(db, now, force_current=True)
    except Exception as exc:
        log.error("Background hourly summary error: %s", exc)
    finally:
        db.close()


@app.post("/api/trigger-hourly-summary")
async def trigger_hourly_summary(background_tasks: BackgroundTasks):
    now = datetime.now(timezone.utc)
    background_tasks.add_task(_run_hourly_summary_bg, now)
    return {"status": "queued"}


@app.post("/api/refresh-app-categories")
async def refresh_app_categories(db: Session = Depends(get_db)):
    """Force re-classification of apps with updated LLM prompt."""
    now = datetime.now(timezone.utc)
    agent_logic.set_state(db, "last_category_cache_refresh", "")  # Clear timestamp to force refresh
    agent_logic.set_state(db, "app_category_cache", "")  # Clear cache
    await agent_logic._refresh_app_category_cache(db, now)
    return {"status": "refreshed"}


@app.post("/api/recap-feedback")
async def recap_feedback(payload: Dict[str, Any], db: Session = Depends(get_db)):
    """User gives feedback on an hourly recap. LLM verifies and updates if user is right."""
    hour_start = payload.get("hour_start", "")
    feedback = payload.get("feedback", "")
    original_summary = payload.get("original_summary", "")

    if not hour_start or not feedback:
        return {"status": "error", "message": "Missing hour_start or feedback"}

    summary = db.query(HourlySummary).filter(HourlySummary.hour_start == hour_start).first()
    if not summary:
        return {"status": "error", "message": "Summary not found"}

    # Get activity logs for context
    try:
        hour_end = datetime.fromisoformat(hour_start) + timedelta(hours=1)
    except ValueError:
        return {"status": "error", "message": "Invalid hour_start format"}
    logs = agent_logic.get_mac_logs_for_hour(db, since=hour_start, until=hour_end.isoformat())

    # Ask LLM to verify feedback
    verification_prompt = (
        f"The user gave feedback on this activity recap:\n\n"
        f"Original recap: {original_summary}\n"
        f"User's feedback: {feedback}\n\n"
        f"Based on the feedback, is the user correct that the recap missed something or got it wrong?\n"
        f"Respond with ONLY JSON: {{\n"
        f'  "user_is_correct": true/false,\n'
        f'  "reasoning": "brief explanation",\n'
        f'  "corrected_summary": "improved summary if user was right, otherwise null",\n'
        f'  "adjusted_score": 6.5\n'
        f"}}"
    )

    try:
        result_text = await llm_client.ask_llm(verification_prompt)
        start = result_text.find('{')
        end = result_text.rfind('}') + 1
        if start >= 0 and end > start:
            result = json.loads(result_text[start:end])

            if result.get("user_is_correct") and result.get("corrected_summary"):
                # User was right — update the summary
                summary.summary_text = result["corrected_summary"]
                if "adjusted_score" in result:
                    summary.productivity_score = result["adjusted_score"]
                summary.summary_source = "llm_verified"
                db.commit()
                return {
                    "status": "updated",
                    "message": "Recap updated with your correction",
                    "new_summary": result["corrected_summary"],
                    "new_score": result.get("adjusted_score")
                }
            else:
                # User was wrong or feedback wasn't specific enough
                return {
                    "status": "verified_incorrect",
                    "message": result.get("reasoning", "LLM verified the original recap was accurate"),
                    "original_is_correct": True
                }
        else:
            return {"status": "error", "message": "LLM returned unexpected format"}
    except Exception as e:
        return {"status": "error", "message": f"LLM verification failed: {str(e)}"}


@app.post("/api/prompt-reply")
def handle_prompt_reply(payload: Dict[str, Any], db: Session = Depends(get_db)):
    reply = payload.get("reply", "")
    agent_logic.clear_pending_prompt(db)
    agent_logic.update_context_with_reply(reply, db)
    return {"status": "accepted"}


@app.get("/api/callout")
def get_callout(db: Session = Depends(get_db)):
    """Returns a call-out if the AI thinks you're being unproductive."""
    category = agent_logic.get_state(db, "callout_category")
    summary = agent_logic.get_state(db, "callout_summary")
    if not category:
        return {"callout": None}
    label_map = {
        "entertainment": "Entertainment",
        "social_media": "Social Media",
        "gaming": "Gaming",
    }
    label = label_map.get(category, category.replace("_", " ").title())
    message = f"You've been on {label} for the past 30 min. What are you actually doing?"
    if summary:
        message = f"Looks like {summary}. Is that intentional? What are you actually doing?"
    return {"callout": message, "category": category}


@app.post("/api/callout/dismiss")
def dismiss_callout(db: Session = Depends(get_db)):
    agent_logic.set_state(db, "callout_category", "")
    agent_logic.set_state(db, "callout_summary", "")
    return {"status": "dismissed"}


@app.post("/api/chat")
async def chat_message(payload: Dict[str, Any], db: Session = Depends(get_db)):
    """Handle user chat messages — tell the agent what you're doing or where you're going."""
    message = (payload.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required")

    now = datetime.now(timezone.utc)
    agent_logic.ensure_default_settings(db)

    # Store the user's message as self-report
    agent_logic.set_state(db, "user_self_report", message)
    agent_logic.set_state(db, "last_user_checkin", now.isoformat())

    # Clear any pending check-in since user proactively told us
    agent_logic.clear_pending_checkin(db)
    agent_logic.set_state(db, "pending_prompt", "")

    # Build context for the LLM to understand and respond
    states = agent_logic.get_all_states(db)
    location = states.get("current_location", "")
    activity_cat = states.get("current_activity_category", "unknown")
    is_walking = states.get("is_walking") == "true"

    context_parts = []
    if location:
        context_parts.append(f"Current location: {location}")
    if activity_cat and activity_cat != "unknown":
        context_parts.append(f"Current detected activity: {activity_cat}")
    if is_walking:
        context_parts.append("Currently walking")

    recent_logs = agent_logic.get_recent_mac_logs(db, limit=5)
    if recent_logs:
        apps = ", ".join(set(l.get("app_name", "") for l in recent_logs if l.get("app_name")))
        if apps:
            context_parts.append(f"Recent apps: {apps}")

    context_str = "; ".join(context_parts) if context_parts else "No recent context"
    history_key = f"chat_history:{agent_logic.local_day_key(db, now)}"
    import json
    existing = agent_logic.get_state(db, history_key, "[]")
    try:
        history = json.loads(existing)
    except Exception:
        history = []
    prior_turns = history[-3:]
    prior_context = "\n".join(
        f'- User: {turn.get("user", "")}\n  Assistant: {turn.get("reply", "")}'
        for turn in prior_turns
        if turn.get("user") or turn.get("reply")
    )

    # Use LLM to generate a smart response and extract context if budget allows
    if agent_logic.can_use_llm(db, now):
        agent_logic.register_llm_call(db, now)
        import llm_client
        prompt = (
            f"You are Vero, a personal productivity AI. The user just told you:\n"
            f'"{message}"\n\n'
            f"Current context: {context_str}\n\n"
            f"Recent chat context:\n{prior_context or '- No recent conversation.'}\n\n"
            "Respond ONLY with a JSON object containing two keys:\n"
            "1. 'reply': 1-2 short sentences. Be direct, helpful, and specific. Acknowledge what they said, confirm tracking next, and suggest likely state.\n"
            "2. 'extracted_context': If the user mentions working on a specific project, class, intent or rule (e.g. 'ChipChop is an unpaid internship' or 'I am studying for CS161'), extract this fact as a short phrase to remember permanently. Otherwise, set this to null.\n"
        )
        result_text = await llm_client.ask_gemini(prompt)
        reply = "Got it. I'll track that and update your context."
        
        start = result_text.find('{')
        end = result_text.rfind('}') + 1
        if start >= 0 and end > start:
            try:
                import json
                parsed = json.loads(result_text[start:end])
                reply = parsed.get("reply", reply)
                extracted = parsed.get("extracted_context")
                if extracted:
                    existing_global = agent_logic.get_state(db, "global_chat_context", "")
                    facts = [f.strip() for f in existing_global.split('|') if f.strip()]
                    facts.append(extracted.strip())
                    if len(facts) > 4:
                        facts = facts[-4:]
                    agent_logic.set_state(db, "global_chat_context", " | ".join(facts))
            except Exception:
                pass
    else:
        reply = "Got it. I noted that and will use it in your activity tracking."

    # Try to extract activity intent from the message using heuristics
    msg_lower = message.lower()
    if any(w in msg_lower for w in ["going to", "headed to", "walking to", "heading to"]):
        # Extract destination
        for prefix in ["going to ", "headed to ", "walking to ", "heading to "]:
            if prefix in msg_lower:
                dest = message[msg_lower.index(prefix) + len(prefix):].strip().rstrip(".")
                if dest:
                    agent_logic.set_state(db, "user_stated_destination", dest)
                    break

    if any(w in msg_lower for w in ["studying", "homework", "class", "lecture"]):
        agent_logic.set_state(db, "current_activity_category", "studying")
        agent_logic.set_state(db, "current_activity_summary", message[:80])
    elif any(w in msg_lower for w in ["working", "coding", "meeting", "email"]):
        agent_logic.set_state(db, "current_activity_category", "working")
        agent_logic.set_state(db, "current_activity_summary", message[:80])
    elif any(w in msg_lower for w in ["gym", "workout", "exercise", "running"]):
        agent_logic.set_state(db, "current_activity_category", "break")
        agent_logic.set_state(db, "current_activity_summary", message[:80])

    # Store in chat history
    history.append({"time": now.isoformat() + "Z", "user": message, "reply": reply})
    # Keep last 20 messages per day
    if len(history) > 20:
        history = history[-20:]
    agent_logic.set_state(db, history_key, json.dumps(history))

    return {"reply": reply, "activity_updated": True}


@app.get("/api/chat/history")
def chat_history(db: Session = Depends(get_db)):
    """Get today's chat history."""
    import json
    now = datetime.now(timezone.utc)
    history_key = f"chat_history:{agent_logic.local_day_key(db, now)}"
    existing = agent_logic.get_state(db, history_key, "[]")
    try:
        history = json.loads(existing)
    except Exception:
        history = []
    return {"messages": history}


@app.get("/api/checkin")
def get_checkin(db: Session = Depends(get_db)):
    """Check if there's a pending check-in question for the user."""
    return agent_logic.get_checkin_payload(db, datetime.now(timezone.utc))


@app.post("/api/checkin/confirm")
def confirm_checkin(payload: Dict[str, Any], db: Session = Depends(get_db)):
    """User confirms or corrects the check-in guess."""
    confirmed = payload.get("confirmed", False)
    correction = (payload.get("correction") or "").strip()
    now = datetime.now(timezone.utc)

    if confirmed:
        # Use the guess as the activity
        guess = agent_logic.get_state(db, "checkin_guess")
        if guess:
            agent_logic.set_state(db, "user_self_report", guess)
    elif correction:
        agent_logic.set_state(db, "user_self_report", correction)

    context_key = agent_logic.get_state(db, "pending_checkin_context_key", "")
    if context_key:
        cooldown_until = now + timedelta(seconds=agent_logic.CHECKIN_COOLDOWN_SECONDS)
        agent_logic.set_state(db, f"checkin_cooldown_until:{context_key}", cooldown_until.isoformat())
    agent_logic.clear_pending_checkin(db)
    agent_logic.set_state(db, "last_user_checkin", now.isoformat())
    return {"status": "ok"}


@app.post("/api/checkin/snooze")
def snooze_checkin(payload: Dict[str, Any], db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    minutes = max(5, min(240, int(payload.get("minutes", 30))))
    context_key = agent_logic.get_state(db, "pending_checkin_context_key", "")
    if context_key:
        cooldown_until = now + timedelta(minutes=minutes)
        agent_logic.set_state(db, f"checkin_cooldown_until:{context_key}", cooldown_until.isoformat())
    agent_logic.clear_pending_checkin(db)
    return {"status": "snoozed", "minutes": minutes}


@app.post("/api/checkin/dismiss")
def dismiss_checkin(db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    context_key = agent_logic.get_state(db, "pending_checkin_context_key", "")
    if context_key:
        cooldown_until = now + timedelta(seconds=agent_logic.CHECKIN_COOLDOWN_SECONDS)
        agent_logic.set_state(db, f"checkin_cooldown_until:{context_key}", cooldown_until.isoformat())
    agent_logic.clear_pending_checkin(db)
    return {"status": "dismissed"}


@app.get("/api/healthz")
async def healthz():
    now = datetime.now(timezone.utc)
    llm_configured = bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("OPENAI_API_KEY"))
    ai_provider = os.environ.get("VERO_AI_PROVIDER") or os.environ.get("LIFE_MANAGER_AI_PROVIDER", "auto")

    # --- Non-blocking DB check (3s timeout) ---
    # Railway requires a 200 response within 30s; we must not block the event loop.
    db_ok = False
    db_error = ""
    llm_stats = {"daily_used": 0, "daily_remaining": 0, "daily_cap": 0}
    states = {
        "llm_mode": "balanced",
        "last_mac_ping": "",
        "last_mac_heartbeat": "",
        "last_ios_ping": "",
        "last_ios_event": "",
        "mac_status": "offline",
        "mac_status_reason": "Database initializing.",
    }
    pending_calendar_jobs = None

    import concurrent.futures

    def _db_check():
        _db = SessionLocal()
        try:
            _db.execute(text("SELECT 1"))
            _payload = _build_state_payload(_db)
            _llm = agent_logic.llm_usage_snapshot(_db, datetime.now(timezone.utc))
            _ai = agent_logic.get_state(_db, "ai_provider", "auto")
            _pending = _db.query(func.count(CalendarEventJob.id)).filter(CalendarEventJob.status == "pending").scalar()
            return True, "", _payload, _llm, _ai, _pending
        except Exception as exc:
            return False, str(exc), None, None, None, None
        finally:
            _db.close()

    loop = asyncio.get_running_loop()
    try:
        result = await asyncio.wait_for(loop.run_in_executor(None, _db_check), timeout=8.0)
        db_ok, db_error, _states, _llm_stats, _ai_provider, pending_calendar_jobs = result
        if db_ok:
            states = _states
            llm_stats = _llm_stats
            ai_provider = _ai_provider
            _STARTUP_STATUS["database_ready"] = True
    except asyncio.TimeoutError:
        db_ok = False
        db_error = "DB check timed out (8s)"
    except Exception as exc:
        db_ok = False
        db_error = str(exc)

    startup_errors = list(_STARTUP_STATUS["startup_errors"])
    if db_error:
        startup_errors = startup_errors + [f"Runtime DB check: {db_error}"]

    # Always return 200 — Railway healthcheck only looks at HTTP status code.
    # Degraded state is reported in the body for dashboards to surface.
    return {
        "status": "ok" if db_ok else "degraded",
        "process_ready": bool(_STARTUP_STATUS["process_ready"]),
        "database_ready": db_ok,
        "startup_migrations_ok": bool(_STARTUP_STATUS["startup_migrations_ok"]),
        "startup_errors": startup_errors,
        "started_at": _STARTED_AT.isoformat(),
        "uptime_seconds": int((now - _STARTED_AT).total_seconds()),
        "backend_url": _get_backend_url(),
        "database": {
            "ok": db_ok,
            "dialect": engine.url.get_backend_name(),
            "error": db_error,
        },
        "auth": {
            "enabled": bool(os.environ.get("DASHBOARD_PASS", "")),
            "user": os.environ.get("DASHBOARD_USER", "admin"),
        },
        "llm": {
            "configured": llm_configured,
            "provider": ai_provider,
            "daily_used": llm_stats["daily_used"],
            "daily_remaining": llm_stats["daily_remaining"],
            "daily_cap": llm_stats["daily_cap"],
            "mode": states.get("llm_mode", "ultra_save"),
        },
        "telemetry": {
            "last_mac_ping": states.get("last_mac_ping", ""),
            "last_mac_heartbeat": states.get("last_mac_heartbeat", ""),
            "last_ios_ping": states.get("last_ios_ping", ""),
            "last_ios_event": states.get("last_ios_event", ""),
        },
        "calendar": {
            "pending_jobs": pending_calendar_jobs,
            "last_job_enqueued_at": states.get("last_calendar_job_at", ""),
            "executor": "mac_helper_only",
        },
        "build": {
            "build_version": _BUILD_VERSION,
            "deployment_channel": _DEPLOYMENT_CHANNEL,
            "git_sha": _GIT_SHA,
        },
        "mac": {
            "status": states.get("mac_status", "offline"),
            "reason": states.get("mac_status_reason", ""),
        },
    }



@app.get("/api/ios-setup-status")
def ios_setup_status(db: Session = Depends(get_db)):
    states = _build_state_payload(db)
    last_ios_ping_age = states.get("last_ios_event_age_seconds")
    required = [
        {"id": "zone_arrive", "label": "Zone arrive automations", "configured": states.get("seen_arrive_automation") == "true"},
        {"id": "zone_leave", "label": "Zone leave automations", "configured": states.get("seen_leave_automation") == "true"},
    ]
    optional = [
        {"id": "charging_stationary", "label": "Charging on/off automations", "configured": states.get("seen_charging_automation") == "true"},
    ]
    checklist = required + optional
    return {
        "ios_recent_ping": states.get("ios_recent_event", False),
        "last_ios_ping_age_seconds": last_ios_ping_age,
        "sleep_source": states.get("sleep_source", "iphone_only"),
        "sleep_status_note": states.get("sleep_status_note", ""),
        "zones": agent_logic.list_zones(db),
        "required": required,
        "optional": optional,
        "checklist": checklist,
    }


@app.get("/api/ios-setup-pack")
def ios_setup_pack(db: Session = Depends(get_db)):
    backend_url = _get_backend_url().rstrip("/")
    zones = agent_logic.list_zones(db)
    enriched = []
    for zone in zones:
        slug = zone.get("slug", "")
        enriched.append({
            **zone,
            "arrive_url": f"{backend_url}/api/ios-zone-event?zone_slug={slug}&transition=enter",
            "leave_url": f"{backend_url}/api/ios-zone-event?zone_slug={slug}&transition=exit",
            "arrive_shortcut_url": f"{backend_url}/setup/shortcut/download-zone?zone_slug={slug}&transition=enter",
            "leave_shortcut_url": f"{backend_url}/setup/shortcut/download-zone?zone_slug={slug}&transition=exit",
        })
    return {
        "backend_url": backend_url,
        "zones": enriched,
        "required": [
            {"id": "zone_arrive", "label": "Zone arrive automations"},
            {"id": "zone_leave", "label": "Zone leave automations"},
        ],
        "optional": [
            {"id": "charging_stationary", "label": "Charging on/off automations"},
        ],
        "events": {
            "walking_url": f"{backend_url}/api/ios-event?kind=walking",
            "charge_on_url": f"{backend_url}/api/ios-event?kind=charge_on",
            "charge_off_url": f"{backend_url}/api/ios-event?kind=charge_off",
        },
        "shortcuts": {
            kind: f"{backend_url}/setup/shortcut/download?kind={kind}"
            for kind in SUPPORTED_SHORTCUT_KINDS
        },
    }


@app.get("/setup/mac", response_class=HTMLResponse)
async def mac_setup_page():
    backend_url = _get_backend_url()
    is_remote = backend_url.startswith("https://")
    remote_only = "" if is_remote else "display:none"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Mac Setup — Vero</title>
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
  :root {{
    color-scheme: light;
    --bg: #f5efe2;
    --panel: rgba(255, 251, 244, 0.92);
    --panel-strong: #fffdf8;
    --line: rgba(18, 57, 55, 0.12);
    --text: #123937;
    --muted: #667a77;
    --teal: #0f766e;
    --teal-deep: #0b5a54;
    --orange: #ea6b2d;
    --orange-soft: rgba(234, 107, 45, 0.12);
    --shadow: 0 24px 60px rgba(18, 57, 55, 0.1);
  }}
  body {{
    font-family: 'Plus Jakarta Sans', sans-serif;
    color: var(--text);
    padding: 2rem;
    max-width: 720px;
    margin: 0 auto;
    background:
      radial-gradient(circle at top left, rgba(17, 133, 121, 0.14), transparent 28%),
      radial-gradient(circle at top right, rgba(234, 107, 45, 0.12), transparent 22%),
      linear-gradient(180deg, var(--bg) 0%, #efe6d6 100%);
  }}
  h1 {{ font-size: 2.1rem; margin-bottom: 0.5rem; letter-spacing: -0.04em; }}
  h2 {{ font-size: 1.1rem; color: var(--teal); margin: 2rem 0 0.75rem; letter-spacing: -0.02em; }}
  p {{ color: var(--muted); line-height: 1.65; }}
  a {{ color: var(--teal); }}
  .step {{ background: var(--panel); border: 1px solid var(--line); border-radius: 24px; padding: 1.35rem; margin: 1rem 0; box-shadow: var(--shadow); backdrop-filter: blur(18px); }}
  .step-num {{ font-size: 0.75rem; color: var(--teal); text-transform: uppercase; letter-spacing: 0.12em; margin-bottom: 0.5rem; font-weight: 700; }}
  code {{ background: rgba(15,118,110,0.09); color: var(--teal-deep); padding: 0.2rem 0.5rem; border-radius: 8px; font-size: 0.9rem; font-family: monospace; }}
  .note {{ font-size: 0.85rem; color: var(--muted); margin-top: 0.75rem; }}
  .divider {{ border: none; border-top: 1px solid var(--line); margin: 2rem 0; }}
  .badge-remote {{ background: var(--orange-soft); color: var(--orange); border: 1px solid rgba(234,107,45,0.24); border-radius: 999px; padding: 0.25rem 0.75rem; font-size: 0.78rem; font-weight: 700; margin-left: 0.5rem; text-transform: uppercase; letter-spacing: 0.08em; }}
  pre.cmd {{ background: var(--panel-strong); border: 1px solid var(--line); border-radius: 18px; padding: 1rem; overflow-x: auto; font-size: 0.85rem; color: var(--text); white-space: pre-wrap; word-break: break-all; position: relative; line-height: 1.65; }}
  pre.cmd .copy-btn {{ position: absolute; top: 0.5rem; right: 0.5rem; background: rgba(15,118,110,0.1); color: var(--teal); border: 1px solid rgba(15,118,110,0.22); border-radius: 8px; padding: 0.25rem 0.6rem; font-size: 0.75rem; cursor: pointer; font-family: 'Plus Jakarta Sans', sans-serif; }}
  pre.cmd .copy-btn:hover {{ background: rgba(15,118,110,0.18); }}
  .checklist li {{ color: var(--muted); margin: 0.45rem 0; }}
  .checklist li span {{ color: var(--teal); margin-right: 0.5rem; }}
</style>
<script>
function copyCmd(btn) {{
  const pre = btn.closest('pre');
  const clone = pre.cloneNode(true);
  clone.querySelectorAll('button').forEach(b => b.remove());
  const text = clone.textContent.trim();
  navigator.clipboard.writeText(text).then(() => {{
    btn.textContent = 'Copied!';
    btn.style.color = '#3fb950';
    setTimeout(() => {{ btn.textContent = 'Copy'; btn.style.color = ''; }}, 2000);
  }}).catch(() => {{
    const ta = document.createElement('textarea');
    ta.value = text; document.body.appendChild(ta); ta.select();
    document.execCommand('copy'); document.body.removeChild(ta);
    btn.textContent = 'Copied!';
    setTimeout(() => btn.textContent = 'Copy', 2000);
  }});
}}
</script>
</head>
<body>
<nav style="margin-bottom:1.5rem;">
  <a href="/" style="text-decoration:none;font-size:0.9rem;display:inline-flex;align-items:center;gap:0.4rem;">
    ← Companion
  </a>
</nav>
<h1>Mac Setup <span class="badge-remote" style="{remote_only}">Hosted</span></h1>
<p>Install Vero once, connect it to your hosted backend, and then let the menu bar companion keep running quietly in the background. The dashboard is where you manage settings and diagnostics.</p>

<h2>Prerequisites</h2>
<div class="step">
  <ul class="checklist">
    <li><span>→</span>macOS 13 Ventura or later</li>
    <li><span>→</span>Xcode installed from the App Store</li>
    <li><span>→</span>Xcode Command Line Tools ready &nbsp;<code>xcodebuild -version</code></li>
  </ul>
  <p class="note">You only need to use the visible window for connection or repair. After that, Vero should stay out of the way in the menu bar.</p>
</div>

<h2>Step 1 — Open the native project</h2>
<div class="step">
  <div class="step-num">Paste this into Terminal and let Xcode open the app project</div>
  <pre class="cmd"><button class="copy-btn" onclick="copyCmd(this)">Copy</button>git clone https://github.com/hnaboulsi/vero.git ~/vero 2>/dev/null || git -C ~/vero pull && (brew list xcodegen >/dev/null 2>&1 || brew install xcodegen) && cd ~/vero/mac_native && xcodegen generate && open Vero.xcodeproj</pre>
  <p class="note">This updates the repo, ensures XcodeGen is installed, generates the native macOS project, and opens it in Xcode.</p>
</div>

<h2>Step 2 — Configure authentication</h2>
<div class="step" style="{remote_only}">
  <div class="step-num">Set the password/basic-auth value that protects your hosted dashboard</div>
  <pre class="cmd"><button class="copy-btn" onclick="copyCmd(this)">Copy</button>echo "admin:YOUR_PASSWORD" > ~/.config/life-manager/auth</pre>
  <p class="note">Replace <code>YOUR_PASSWORD</code> with the real dashboard password or basic-auth value. The tracker uses HTTP Basic Auth to send data securely.</p>
</div>
<div class="step" style="{'display:none' if is_remote else ''}">
  <p>Auth not required for local setup — the tracker connects directly to <code>localhost:8000</code>.</p>
</div>

<h2>Step 3 — Run it once, then close it</h2>
<div class="step">
  <div class="step-num">In Xcode, choose the <strong>Vero</strong> scheme and press Run once</div>
  <p>When the app opens, grant the permissions it asks for, connect the backend if prompted, then close the window. The goal is to register the menu bar helper, not keep a full app window open.</p>
  <p class="note">If you already have <code>Vero.app</code> in Applications, you can launch it directly with <code>open -a "Vero"</code>.</p>
  <p class="note">Once connected, use the dashboard for tracking cadence, privacy, zones, and diagnostics.</p>
</div>

<hr class="divider">

<h2>Verify</h2>
<div class="step">
  <div class="step-num">Check that data is arriving</div>
  <p>Go back to the <a href="/today" style="color:#58a6ff">companion web app</a> — the Mac status should show <strong>Online</strong> within 60 seconds. If the app window is closed and the Mac stays online, the menu bar helper is doing its job.</p>
</div>

<h2>Troubleshooting</h2>
<div class="step">
  <p><strong>Mac still offline?</strong> Relaunch Vero or rerun this Mac setup guide to reconnect the menu bar companion and refresh local permissions.</p>
  <p><strong>Missing permissions?</strong> Re-open the app and grant Accessibility, Notifications, and Calendar access.</p>
  <p><strong>Backend offline error?</strong> Check your backend URL is correct: <code>cat ~/.config/life-manager/backend.url</code></p>
  <p><strong>Auth errors?</strong> Check your password: <code>cat ~/.config/life-manager/auth</code></p>
  <p class="note">If the helper still will not connect, reopen Vero, reconnect the backend, and then verify status from the dashboard before digging into local logs.</p>
</div>
</body>
</html>"""


@app.get("/setup/ios", response_class=HTMLResponse)
async def ios_setup_page(db: Session = Depends(get_db)):
    pack = ios_setup_pack(db)
    status = ios_setup_status(db)
    backend_url = pack["backend_url"]
    required_items = status.get("required", [])
    optional_items = status.get("optional", [])
    zones = pack.get("zones", [])
    walking_url = pack["events"]["walking_url"]
    charge_on_url = pack["events"]["charge_on_url"]
    charge_off_url = pack["events"]["charge_off_url"]
    shortcut_links = pack.get("shortcuts", {})

    def _check_items(items: list[dict]) -> str:
        if not items:
            return "<li>No checks yet</li>"
        out = []
        for item in items:
            mark = "✅" if item.get("configured") else "◻️"
            out.append(f"<li>{mark} {html.escape(item.get('label', ''))}</li>")
        return "".join(out)

    if zones:
        zone_cards = []
        for zone in zones:
            name = html.escape(zone.get("name", "Unnamed Zone"))
            slug = html.escape(zone.get("slug", ""))
            arrive_url_raw = zone.get("arrive_url", "")
            leave_url_raw = zone.get("leave_url", "")
            arrive_shortcut_raw = zone.get("arrive_shortcut_url", "")
            leave_shortcut_raw = zone.get("leave_shortcut_url", "")
            arrive_url = html.escape(arrive_url_raw)
            leave_url = html.escape(leave_url_raw)
            arrive_shortcut = html.escape(arrive_shortcut_raw)
            leave_shortcut = html.escape(leave_shortcut_raw)
            arrive_js = f'"{html.escape(arrive_url_raw)}"'
            leave_js = f'"{html.escape(leave_url_raw)}"'
            zone_cards.append(
                f"""
                <div class="zone-card">
                  <h3>{name}</h3>
                  <p class="slug">slug: {slug}</p>
                  <div class="url-row"><span>{arrive_url}</span><button class="copy-btn" onclick="copyURL(this, {arrive_js})">Copy Arrive</button></div>
                  <div class="url-row"><span>{leave_url}</span><button class="copy-btn" onclick="copyURL(this, {leave_js})">Copy Leave</button></div>
                  <div class="url-row"><span>Arrive shortcut</span><a href="{arrive_shortcut}" class="copy-btn" style="text-decoration:none;">Download</a></div>
                  <div class="url-row"><span>Leave shortcut</span><a href="{leave_shortcut}" class="copy-btn" style="text-decoration:none;">Download</a></div>
                </div>
                """
            )
        zone_cards_html = "".join(zone_cards)
    else:
        zone_cards_html = (
            "<div class='zone-card empty'>No zones yet. Open Settings → Zones in the dashboard and add at least one zone.</div>"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>iPhone Setup — Vero</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Inter', sans-serif; background:#0f1117; color:#f1f5f9; max-width:900px; margin:0 auto; padding:2rem; }}
  a {{ color: #60a5fa; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  h1 {{ font-size:1.8rem; margin:0 0 0.25rem 0; }}
  h2 {{ margin-top:2rem; font-size:1.15rem; }}
  .section {{ background:#1a1d27; border:1px solid #2a2d3a; border-radius:12px; padding:1rem 1.25rem; margin-top:1rem; }}
  .checklist li {{ margin:0.35rem 0; color:#cbd5e1; }}
  .zone-card {{ border:1px solid #2a2d3a; background:#13161f; border-radius:10px; padding:0.85rem; margin-top:0.75rem; }}
  .zone-card.empty {{ color:#94a3b8; }}
  .zone-card h3 {{ margin:0; font-size:1rem; }}
  .zone-card .slug {{ margin:0.2rem 0 0.7rem 0; color:#94a3b8; font-size:0.8rem; }}
  .url-row {{ display:flex; gap:0.5rem; align-items:center; justify-content:space-between; background:#1a1d27; border:1px solid #2a2d3a; border-radius:8px; padding:0.55rem; margin-top:0.45rem; }}
  .url-row span {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size:0.78rem; word-break:break-all; color:#94a3b8; }}
  .copy-btn {{ border:1px solid #374151; background:#1a1d27; color:#cbd5e1; border-radius:7px; padding:0.3rem 0.55rem; cursor:pointer; font-size:0.74rem; white-space:nowrap; }}
  .copy-btn:hover {{ background:#252a3a; }}
  .muted {{ color:#94a3b8; font-size:0.9rem; }}
  code {{ background:#13161f; padding:0.15rem 0.4rem; border-radius:6px; }}
</style>
<script>
function copyURL(btn, url) {{
  navigator.clipboard.writeText(url).then(() => {{
    const oldText = btn.textContent;
    btn.textContent = 'Copied';
    setTimeout(() => {{ btn.textContent = oldText; }}, 1200);
  }});
}}
</script>
</head>
<body>
  <p><a href="/">← Dashboard</a></p>
  <h1>iPhone Setup</h1>
  <p class="muted">This page generates exact URLs for each zone. Required setup is zone Arrive + Leave automations. Charging is optional.</p>

  <div class="section">
    <h2>Checklist</h2>
    <p><strong>Required</strong></p>
    <ul class="checklist">{_check_items(required_items)}</ul>
    <p><strong>Optional</strong></p>
    <ul class="checklist">{_check_items(optional_items)}</ul>
  </div>

  <div class="section">
    <h2>Zone URLs (Required)</h2>
    <p class="muted">For each zone in Shortcuts: create one Arrive automation and one Leave automation using <code>Get Contents of URL</code> or download the shortcut and use <code>Run Shortcut</code>.</p>
    {zone_cards_html}
  </div>

  <div class="section">
    <h2>Charging (Optional)</h2>
    <div class="url-row"><span>{html.escape(charge_on_url)}</span><button class="copy-btn" onclick="copyURL(this, '{html.escape(charge_on_url)}')">Copy Charge On</button></div>
    <div class="url-row"><span>{html.escape(charge_off_url)}</span><button class="copy-btn" onclick="copyURL(this, '{html.escape(charge_off_url)}')">Copy Charge Off</button></div>
    <p class="muted" style="margin-top:0.75rem;">Or download prebuilt shortcuts and use <code>Run Shortcut</code> instead.</p>
    <div class="url-row"><span>Charge On shortcut</span><a href="{html.escape(shortcut_links.get('charge_on', ''))}" class="copy-btn" style="text-decoration:none;">Download</a></div>
    <div class="url-row"><span>Charge Off shortcut</span><a href="{html.escape(shortcut_links.get('charge_off', ''))}" class="copy-btn" style="text-decoration:none;">Download</a></div>
  </div>

  <div class="section">
    <h2>Quick Verify</h2>
    <p>Run each automation once manually, then refresh <a href="/api/ios-setup-status">/api/ios-setup-status</a>. Required items should show as configured.</p>
    <p class="muted">Backend: <code>{html.escape(backend_url)}</code></p>
  </div>
</body>
</html>"""


def _sign_shortcut_bytes(unsigned_bytes: bytes, name: str = "shortcut") -> bytes:
    """Sign shortcut bytes using the macOS `shortcuts sign` CLI.

    Returns signed bytes on macOS, or the original unsigned bytes on Linux/Railway.
    """
    import shutil, tempfile, subprocess
    if not shutil.which("shortcuts"):
        log.warning("shortcuts CLI not found (not macOS?) — returning unsigned")
        return unsigned_bytes
    try:
        with tempfile.NamedTemporaryFile(suffix=".shortcut", delete=False) as tmp_in:
            tmp_in.write(unsigned_bytes)
            tmp_in_path = tmp_in.name
        tmp_out_path = tmp_in_path.replace(".shortcut", "-signed.shortcut")
        result = subprocess.run(
            ["shortcuts", "sign", "-m", "anyone", "-i", tmp_in_path, "-o", tmp_out_path],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            with open(tmp_out_path, "rb") as f:
                signed = f.read()
            log.info("Signed shortcut: %s (%d bytes)", name, len(signed))
            return signed
        else:
            log.error("shortcuts sign failed: %s", result.stderr.strip())
            return unsigned_bytes
    except Exception as e:
        log.error("Error signing shortcut %s: %s", name, e)
        return unsigned_bytes
    finally:
        import os
        for p in [tmp_in_path, tmp_out_path]:
            try:
                os.unlink(p)
            except OSError:
                pass


SHORTCUT_TEMPLATES = {
    "walking": {
        "name": "Vero Walking",
        "activity": "Walking",
        "is_charging": "false",
        "use_location_action": False,
        "location_label": "walking_trigger",
    },
    "charge_on": {
        "name": "Vero Charging On",
        "activity": "Stationary",
        "is_charging": "true",
        "use_location_action": False,
        "location_label": "charging_trigger",
    },
    "charge_off": {
        "name": "Vero Charging Off",
        "activity": "Stationary",
        "is_charging": "false",
        "use_location_action": False,
        "location_label": "charging_trigger",
    },
}
SUPPORTED_SHORTCUT_KINDS = tuple(SHORTCUT_TEMPLATES.keys())


def _build_shortcut_bytes(kind: str = "walking", sign: bool = True) -> bytes:
    """Generate shortcut bytes for all iOS automation types."""
    import plistlib
    import uuid

    kind = (kind or "walking").lower()
    if kind not in SHORTCUT_TEMPLATES:
        raise ValueError(f"Unknown shortcut kind: {kind}")

    cfg = SHORTCUT_TEMPLATES[kind]
    action_url = f"{_get_backend_url().rstrip('/')}/api/ios-event?kind={kind}"

    actions = [
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.downloadurl",
            "WFWorkflowActionParameters": {
                "WFURL": action_url,
                "WFHTTPMethod": "GET",
                "ShowHeaders": False,
            },
        }
    ]

    shortcut = {
        "WFWorkflowMinimumClientVersion": 900,
        "WFWorkflowMinimumClientVersionString": "900",
        "WFWorkflowName": cfg["name"],
        "WFWorkflowTypes": [],
        "WFWorkflowIcon": {"WFWorkflowIconGlyphNumber": 59511, "WFWorkflowIconStartColor": 4275765759},
        "WFWorkflowActions": actions,
    }
    raw = plistlib.dumps(shortcut, fmt=plistlib.FMT_XML)
    return _sign_shortcut_bytes(raw, cfg["name"]) if sign else raw


def _build_zone_shortcut_bytes(zone_slug: str, transition: str, sign: bool = True) -> bytes:
    import plistlib

    clean_slug = agent_logic.normalize_zone_slug(zone_slug or "")
    clean_transition = (transition or "").strip().lower()
    if not clean_slug:
        raise ValueError("zone_slug is required")
    if clean_transition not in {"enter", "exit"}:
        raise ValueError("transition must be 'enter' or 'exit'")

    action_url = (
        f"{_get_backend_url().rstrip('/')}/api/ios-zone-event"
        f"?zone_slug={clean_slug}&transition={clean_transition}"
    )
    transition_label = "Arrive" if clean_transition == "enter" else "Leave"
    shortcut = {
        "WFWorkflowMinimumClientVersion": 900,
        "WFWorkflowMinimumClientVersionString": "900",
        "WFWorkflowName": f"Vero {clean_slug} {transition_label}",
        "WFWorkflowTypes": [],
        "WFWorkflowIcon": {"WFWorkflowIconGlyphNumber": 59511, "WFWorkflowIconStartColor": 4275765759},
        "WFWorkflowActions": [
            {
                "WFWorkflowActionIdentifier": "is.workflow.actions.downloadurl",
                "WFWorkflowActionParameters": {
                    "WFURL": action_url,
                    "WFHTTPMethod": "GET",
                    "ShowHeaders": False,
                },
            }
        ],
    }
    raw = plistlib.dumps(shortcut, fmt=plistlib.FMT_XML)
    return _sign_shortcut_bytes(raw, f"{clean_slug}-{clean_transition}") if sign else raw


@app.get("/setup/save-to-icloud")
async def save_shortcut_to_icloud():
    """Save the walking helper shortcut to iCloud Drive and open Finder there."""
    import subprocess, os
    from fastapi.responses import HTMLResponse as HR
    icloud_path = os.path.expanduser("~/Library/Mobile Documents/com~apple~CloudDocs")
    if not os.path.isdir(icloud_path):
        return HR("<p style='font-family:sans-serif;color:#f85149'>iCloud Drive not found. Make sure iCloud Drive is enabled in System Settings → Apple ID → iCloud.</p>")
    dest = os.path.join(icloud_path, "Vero-walking.shortcut")
    with open(dest, "wb") as f:
        f.write(_build_shortcut_bytes(kind="walking"))
    subprocess.run(["open", icloud_path])
    return HR("""<html><head><meta charset='UTF-8'><style>
      body{font-family:sans-serif;background:#0d1117;color:#f0f6fc;display:flex;align-items:center;
           justify-content:center;min-height:100vh;margin:0;flex-direction:column;gap:1rem;}
      p{color:#8b949e;} a{color:#58a6ff;}
    </style></head><body>
    <h2 style='color:#3fb950'>✅ Saved to iCloud Drive!</h2>
    <p>Finder opened. On your iPhone: open <strong>Files → iCloud Drive → Vero-walking.shortcut</strong></p>
    <a href='/setup/ios'>← Back to setup</a>
    </body></html>""")


@app.get("/setup/save-to-desktop")
async def save_shortcut_to_desktop():
    """Save the walking helper shortcut to the Mac Desktop and reveal it in Finder."""
    import subprocess, os
    from fastapi.responses import HTMLResponse as HR
    dest = os.path.expanduser("~/Desktop/Vero-walking.shortcut")
    with open(dest, "wb") as f:
        f.write(_build_shortcut_bytes(kind="walking"))
    subprocess.run(["open", "-R", dest])  # Reveal in Finder
    return HR("""<html><head><meta charset='UTF-8'><style>
      body{font-family:sans-serif;background:#0d1117;color:#f0f6fc;display:flex;align-items:center;
           justify-content:center;min-height:100vh;margin:0;flex-direction:column;gap:1rem;}
      p{color:#8b949e;} a{color:#58a6ff;}
    </style></head><body>
    <h2 style='color:#3fb950'>✅ Saved to Desktop!</h2>
    <p>Finder opened with the file selected.<br>Right-click it → <strong>Share → AirDrop</strong> → select your iPhone.</p>
    <a href='/setup/ios'>← Back to setup</a>
    </body></html>""")


@app.get("/setup/shortcut/download")
async def download_shortcut(kind: str = "walking"):
    from fastapi.responses import Response
    kind = (kind or "walking").strip().lower()
    filename = f"Vero-{kind}.shortcut"
    try:
        shortcut_bytes = _build_shortcut_bytes(kind)
    except ValueError:
        valid = ", ".join(SUPPORTED_SHORTCUT_KINDS)
        raise HTTPException(status_code=400, detail=f"Invalid shortcut kind. Valid kinds: {valid}")
    return Response(
        content=shortcut_bytes,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/setup/shortcut/download-zone")
async def download_zone_shortcut(zone_slug: str, transition: str):
    from fastapi.responses import Response

    clean_slug = agent_logic.normalize_zone_slug(zone_slug or "")
    clean_transition = (transition or "").strip().lower()
    if not clean_slug:
        raise HTTPException(status_code=400, detail="zone_slug is required")
    if clean_transition not in {"enter", "exit"}:
        raise HTTPException(status_code=400, detail="transition must be 'enter' or 'exit'")

    transition_label = "arrive" if clean_transition == "enter" else "leave"
    filename = f"Vero-zone-{clean_slug}-{transition_label}.shortcut"
    try:
        shortcut_bytes = _build_zone_shortcut_bytes(clean_slug, clean_transition)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return Response(
        content=shortcut_bytes,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/setup/shortcut/sign-all")
async def sign_all_shortcuts():
    """Download, sign, and save all shortcuts to Desktop — macOS only."""
    import os, shutil, subprocess
    from fastapi.responses import HTMLResponse as HR
    if not shutil.which("shortcuts"):
        return HR("<p style='font-family:sans-serif;color:#f85149'>This endpoint only works when the backend is running locally on macOS.</p>")
    desktop = os.path.expanduser("~/Desktop")
    kinds = list(SUPPORTED_SHORTCUT_KINDS)
    saved = []
    failed = []
    for kind in kinds:
        try:
            signed_bytes = _build_shortcut_bytes(kind, sign=True)
            dest = os.path.join(desktop, f"Vero-{kind}.shortcut")
            with open(dest, "wb") as f:
                f.write(signed_bytes)
            saved.append(f"Vero-{kind}.shortcut")
        except Exception as e:
            failed.append(f"{kind}: {e}")
    # Reveal Desktop in Finder
    subprocess.run(["open", desktop])
    items_html = "".join(f"<li>✅ {s}</li>" for s in saved)
    items_html += "".join(f"<li style='color:#f85149'>❌ {f}</li>" for f in failed)
    return HR(f"""<html><head><meta charset='UTF-8'><style>
      body{{font-family:sans-serif;background:#0d1117;color:#f0f6fc;padding:2rem;max-width:500px;margin:0 auto;}}
      li{{margin:0.5rem 0;color:#8b949e;}} a{{color:#58a6ff;text-decoration:none;}}
      h2{{color:#3fb950;}} p{{color:#8b949e;}}
    </style></head><body>
    <h2>⚡ All shortcuts saved to Desktop!</h2>
    <p>Finder opened. AirDrop each file to your iPhone and tap <strong>Add Shortcut</strong>.</p>
    <ul>{items_html}</ul>
    <p style='margin-top:1.5rem'><a href='/setup/ios'>← Back to setup</a></p>
    </body></html>""")


@app.get("/api/analytics/today")
async def analytics_today(db: Session = Depends(get_db)):
    """Daily analytics: local-day active time, productive %, and AI usage."""
    now = datetime.now(timezone.utc)
    today_start, today_end = agent_logic.user_day_bounds_utc(db, now)
    user_tz = agent_logic.resolve_user_timezone(db)

    # Get all mac logs from today
    logs = (
        db.query(ActivityLog)
        .filter(ActivityLog.device == "mac", ActivityLog.timestamp >= today_start, ActivityLog.timestamp < today_end)
        .order_by(ActivityLog.timestamp)
        .all()
    )

    # Compute time per category using log intervals
    states = agent_logic.get_all_states(db)
    polling_secs = agent_logic.get_capture_interval_seconds(db)

    # AI-generated app→category cache (updated hourly by _refresh_app_category_cache)
    app_cache: dict[str, str] = {}
    try:
        raw = states.get("app_category_cache", "")
        if raw:
            app_cache = json.loads(raw)
    except Exception:
        pass

    category_minutes = {}
    total_active_minutes = 0
    idle_count = 0
    unclassified_apps = {}
    for entry in logs:
        interval_min = polling_secs / 60
        if entry.is_idle:
            idle_count += 1
            category_minutes["idle"] = category_minutes.get("idle", 0) + interval_min
            continue
        total_active_minutes += interval_min
        app_name = (entry.app_name or "").strip()
        # 1. Check AI cache first (personalized, updates hourly)
        if app_name in app_cache:
            cat = app_cache[app_name]
        else:
            # 2. Fall back to keyword heuristics
            text_data = f"{app_name.lower()} {(entry.window_title or '').lower()}"
            cat = "break"
            for needles, result in [
                (["instagram", "twitter", "x.com", "tiktok", "snapchat", "discord"], "social_media"),
                (["youtube", "netflix", "reddit", "spotify", "hulu"], "entertainment"),
                (["steam", "epic", "game"], "gaming"),
                (["canvas", "gradescope", "homework", "lecture", "course", "quiz", "anki",
                  "textbook", "study", "chegg", "coursera", "udemy", "khan", "edx", "mit"], "studying"),
                (["figma", "photoshop", "premiere", "final cut", "sketch", "illustrator", "design", "canva"], "creative"),
                (["vscode", "visual studio", "pycharm", "cursor", "intellij", "xcode", "android studio",
                  "terminal", "iterm", "github", "gitlab", "linear", "jira", "notion", "confluence",
                  "slack", "zoom", "vero", "lifemanager", "postman", "datagrip", "tableplus",
                  "zed", "emacs", "vim", "arc", "code",
                  "stackoverflow", "vercel", "railway", "anthropic", "claude.ai",
                  "docs.google", "drive.google", "sheets", "supabase", "planetscale",
                  "render.com", "heroku", "aws", "azure", "gcp"], "working"),
            ]:
                if any(n in text_data for n in needles):
                    cat = result
                    break
            if cat == "break":
                # 3. Check if the window title matches any user-defined global context rules
                global_context = states.get("global_chat_context", "").lower()
                global_rules = [r.strip() for r in global_context.split('|') if r.strip() and len(r.strip()) > 3]
                if any(rule in text_data for rule in global_rules):
                    cat = "working"
            if cat == "break":
                unclassified_apps[app_name] = unclassified_apps.get(app_name, 0) + 1
        category_minutes[cat] = category_minutes.get(cat, 0) + interval_min

    if unclassified_apps:
        log.debug("Unclassified apps (defaulted to break): %s", unclassified_apps)

    global_context = states.get("global_chat_context", "").lower()
    global_rules = [r.strip() for r in global_context.split('|') if r.strip()]

    productive_cats = {"studying", "working", "creative"}
    
    # Re-evaluate all "break" minutes if they match a global user rule (like a specific project name)
    # The analytics calculates per loop, but since we didn't inject global rules into the loop above,
    # we need to fix the actual loop itself!
    productive_minutes = sum(category_minutes.get(c, 0) for c in productive_cats)
    productive_pct = round((productive_minutes / total_active_minutes * 100) if total_active_minutes > 0 else 0)

    # LLM usage
    llm_stats = agent_logic.llm_usage_snapshot(db, now)
    last_log_ts = logs[-1].timestamp if logs else None
    freshness_seconds = int((now.replace(tzinfo=None) - last_log_ts).total_seconds()) if last_log_ts else None
    last_updated_at = (
        last_log_ts.replace(tzinfo=timezone.utc).isoformat()
        if last_log_ts else ""
    )

    return {
        "category_minutes": category_minutes,
        "total_active_minutes": round(total_active_minutes),
        "productive_minutes": round(productive_minutes),
        "productive_pct": productive_pct,
        "llm_used": llm_stats["daily_used"],
        "llm_cap": llm_stats["daily_cap"],
        "log_count": len(logs),
        "idle_log_count": idle_count,
        "timezone": user_tz.key,
        "day_start_utc": today_start.replace(tzinfo=timezone.utc).isoformat(),
        "day_end_utc": today_end.replace(tzinfo=timezone.utc).isoformat(),
        "last_updated_at": last_updated_at,
        "data_freshness_seconds": freshness_seconds,
        "active_minutes_formula": "Count non-idle Mac telemetry points in the local day and multiply by the capture interval.",
        "productive_formula": "productive_minutes / total_active_minutes where productive categories are studying, working, creative.",
        # Backward compatibility for older clients.
        "steps_today": int(states.get("steps_today", "0") or "0"),
    }


@app.get("/api/export")
async def export_data(days: int = 30, db: Session = Depends(get_db)):
    """Export activity logs as CSV."""
    import csv
    import io
    since = datetime.now(timezone.utc) - timedelta(days=min(days, 365))
    logs = (
        db.query(ActivityLog)
        .filter(ActivityLog.timestamp >= since)
        .order_by(ActivityLog.timestamp)
        .all()
    )
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["timestamp", "device", "app_name", "window_title", "is_idle", "location_label", "activity_type", "steps_today"])
    for entry in logs:
        writer.writerow([
            entry.timestamp.isoformat() if entry.timestamp else "",
            entry.device, entry.app_name, entry.window_title,
            entry.is_idle, entry.location_label, entry.activity_type, entry.steps_today,
        ])
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=vero-export-{days}d.csv"},
    )


@app.get("/api/stream")
async def event_stream():
    """Server-Sent Events stream for real-time dashboard updates.
    Pushes every 5s and auto-closes after 5 minutes to conserve Railway resources.
    Client should reconnect automatically (EventSource handles this)."""
    import time as _time
    import json as _json
    from starlette.responses import StreamingResponse

    def _fetch_sse_data():
        fresh_db = SessionLocal()
        try:
            states = _build_state_payload(fresh_db)
            logs = fresh_db.query(ActivityLog).order_by(desc(ActivityLog.timestamp)).limit(15).all()
            logs_data = [
                {
                    "id": l.id,
                    "timestamp": l.timestamp.isoformat() if l.timestamp else "",
                    "device": l.device,
                    "app_name": l.app_name,
                    "window_title": l.window_title,
                    "is_idle": l.is_idle,
                    "location_label": l.location_label,
                    "activity_type": l.activity_type,
                    "steps_today": l.steps_today,
                    "battery_pct": l.battery_pct,
                }
                for l in logs
            ]
            return {"states": states, "logs": logs_data}
        finally:
            fresh_db.close()

    async def generate():
        start = _time.time()
        max_duration = 300  # 5 minutes then close — client reconnects
        loop = asyncio.get_running_loop()
        try:
            while _time.time() - start < max_duration:
                try:
                    data = await loop.run_in_executor(None, _fetch_sse_data)
                    payload = _json.dumps(data)
                    yield f"data: {payload}\n\n"
                except Exception as e:
                    log.error("SSE stream error: %s", e)
                    yield f"data: {{}}\n\n"
                
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            log.debug("SSE client disconnected")

    return StreamingResponse(generate(), media_type="text/event-stream")


def _get_backend_url() -> str:
    """Return the public-facing backend URL (Railway HTTPS or local IP)."""
    # Priority 1: Railway public domain env vars (auto-injected by Railway)
    railway_domain = (
        os.environ.get("RAILWAY_PUBLIC_DOMAIN")
        or os.environ.get("RAILWAY_STATIC_URL")
        or os.environ.get("RAILWAY_SERVICE_LIFE_MANAGER_AGENT_URL")
    )
    if railway_domain:
        domain = railway_domain.replace("https://", "").replace("http://", "").rstrip("/")
        return f"https://{domain}"
    # Priority 2: Local network IP (use actual $PORT to match start command)
    port = int(os.environ.get("PORT", "8000"))
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return f"http://{local_ip}:{port}"
    except Exception:
        return f"http://localhost:{port}"


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
