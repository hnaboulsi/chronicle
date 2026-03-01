import asyncio
import logging
import os
import base64
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
from fastapi.responses import HTMLResponse, Response, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc, text, func
from database import engine, Base, get_db, SessionLocal
import models
from models import ActivityLog, CalendarEventJob, HourlySummary, MacHeartbeat, MacTelemetry, iOSZoneEvent, iOSTelemetry
import agent_logic

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
            else:  # sqlite doesn't support IF NOT EXISTS on ALTER
                cols = [r[1] for r in conn.execute(text("PRAGMA table_info(activity_logs)"))]
                if "battery_pct" not in cols:
                    conn.execute(text("ALTER TABLE activity_logs ADD COLUMN battery_pct INTEGER"))

            # Data migration: rename legacy app names to "Vero"
            conn.execute(text("""
                UPDATE activity_logs
                SET app_name = 'Vero'
                WHERE app_name IN ('LifeManager', 'Vero Agent', 'Ambient')
            """))
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
    "/api/ios-zone-event",
    "/api/healthz",
    "/api/login",
    "/login",
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
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth[6:]).decode("utf-8")
            _, _, p = decoded.partition(":")
            if secrets.compare_digest(p.strip(), password):
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
<title>Vero — Login</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0F1117; color: #F9FAFB; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         display: flex; align-items: center; justify-content: center; min-height: 100vh; }
  .card { background: #1A1D27; border: 1px solid rgba(255,255,255,0.08); border-radius: 12px;
          padding: 40px 36px; width: 100%; max-width: 360px; }
  h1 { font-size: 20px; font-weight: 600; margin-bottom: 4px; }
  p { font-size: 13px; color: #6B7280; margin-bottom: 28px; }
  label { display: block; font-size: 12px; font-weight: 500; color: #9CA3AF; margin-bottom: 6px; }
  input { width: 100%; background: #0F1117; border: 1px solid rgba(255,255,255,0.12);
          border-radius: 8px; color: #F9FAFB; font-size: 15px; padding: 10px 14px; outline: none; }
  input:focus { border-color: #6366F1; }
  button { margin-top: 16px; width: 100%; background: #6366F1; border: none; border-radius: 8px;
           color: #fff; font-size: 14px; font-weight: 600; padding: 11px; cursor: pointer; }
  button:hover { background: #4F46E5; }
  .error { margin-top: 14px; font-size: 13px; color: #EF4444; text-align: center; }
</style>
</head>
<body>
<div class="card">
  <h1>Vero</h1>
  <p>Enter your dashboard password to continue.</p>
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
        response = RedirectResponse(url="/dashboard/", status_code=303)
        response.set_cookie(
            "vero_session", token,
            httponly=True, samesite="lax",
            max_age=86400 * 30,  # 30 days
            secure=False,  # Railway terminates TLS upstream
        )
        return response

    _record_failure(client_ip)
    return RedirectResponse(url="/login?error=1", status_code=303)


# Serve frontend static files
frontend_path = os.path.join(os.path.dirname(__file__), "frontend")
os.makedirs(frontend_path, exist_ok=True)
app.mount("/dashboard", StaticFiles(directory=frontend_path, html=True), name="frontend")

@app.get("/")
async def redirect_to_dashboard():
    return RedirectResponse(url="/dashboard/index.html")


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

    try:
        polling_interval_seconds = int(agent_logic.get_state(db, "polling_interval_seconds", "60"))
    except Exception:
        polling_interval_seconds = 60

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
    states["polling_interval_seconds"] = polling_interval_seconds
    states["mac_online_threshold_seconds"] = max(300, polling_interval_seconds * 2 + 30)
    states["last_mac_ping_age_seconds"] = mac_status["last_mac_snapshot_age_seconds"]
    states["last_mac_heartbeat_age_seconds"] = mac_status["last_mac_heartbeat_age_seconds"]
    states["last_mac_snapshot_age_seconds"] = mac_status["last_mac_snapshot_age_seconds"]
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
    states["mac_launch_url"] = "vero://open"
    states["last_mac_heartbeat"] = states.get("last_mac_heartbeat", "")
    states["service_health"] = "ok" if mac_status["mac_status"] in {"online", "online_idle"} else (
        "degraded" if mac_status["mac_status"] in {"degraded", "paused"} else "offline"
    )
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
    log_entry = ActivityLog(
        device="mac",
        app_name=data.app_name,
        window_title=data.window_title,
        is_idle=data.idle_time_seconds > 60 * 30
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


@app.api_route("/api/ios-zone-event", methods=["GET", "POST"])
async def receive_ios_zone_event(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    body_text = ""
    if request.method == "POST":
        body_bytes = await request.body()
        # Rescue iPhone Smart Punctuation curly quotes
        body_text = body_bytes.decode("utf-8", errors="ignore").replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    
    zone_slug = request.query_params.get("zone", "") or request.query_params.get("zone_slug", "")
    transition = request.query_params.get("transition", "")
    
    if body_text.strip():
        import json
        try:
            payload = json.loads(body_text)
            zone_slug = zone_slug or payload.get("zone_slug", "") or payload.get("zone", "")
            transition = transition or payload.get("transition", "")
        except json.JSONDecodeError:
            log.warning("Failed to parse iOS zone event JSON: %s", body_text)
            
    if not zone_slug or not transition:
        return {"status": "error", "reason": "missing zone_slug or transition"}
        
    data = iOSZoneEvent(zone_slug=zone_slug, transition=transition.lower())
    
    def _run_db():
        zone = agent_logic.get_zone(db, data.zone_slug)
        zone_label = zone.name if zone else data.zone_slug.replace("-", " ").title()
        log_entry = ActivityLog(
            device="ios",
            location_label=zone_label,
            activity_type=f"Zone {data.transition.title()}",
            battery_pct=_normalize_battery_level(data.battery_level),
            steps_today=data.steps_today,
        )
        db.add(log_entry)
        db.commit()
        return zone_label

    loop = asyncio.get_running_loop()
    zone_label = await loop.run_in_executor(None, _run_db)
    background_tasks.add_task(_bg_process_ios_zone, data)
    return {"status": "ok", "zone": zone_label, "transition": data.transition}


@app.get("/api/state")
def get_state(db: Session = Depends(get_db)):
    return _build_state_payload(db)

@app.get("/api/settings")
def get_settings(db: Session = Depends(get_db)):
    agent_logic.ensure_default_settings(db)
    polling_str = agent_logic.get_state(db, "polling_interval_seconds", "60")
    tracking_enabled_str = agent_logic.get_state(db, "tracking_enabled", "true")
    return {
        "polling_interval_seconds": int(polling_str),
        "tracking_enabled": tracking_enabled_str.lower() == "true",
        "backend_mode": agent_logic.get_state(db, "backend_mode", "railway_primary"),
        "ai_provider": agent_logic.get_state(db, "ai_provider", "auto"),
        "llm_mode": agent_logic.get_state(db, "llm_mode", "ultra_save"),
        "hourly_summaries_enabled": agent_logic.get_state(db, "hourly_summaries_enabled", "false").lower() == "true",
        "classification_interval_seconds": int(agent_logic.get_state(db, "classification_interval_seconds", "1800")),
        "llm_daily_cap": int(agent_logic.get_state(db, "llm_daily_cap", "30")),
        "user_timezone": agent_logic.get_state(db, "user_timezone", "America/Los_Angeles"),
    }

@app.post("/api/settings")
def update_settings(payload: Dict[str, Any], db: Session = Depends(get_db)):
    agent_logic.ensure_default_settings(db)
    if "polling_interval_seconds" in payload:
        agent_logic.set_state(db, "polling_interval_seconds", str(payload["polling_interval_seconds"]))
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
        agent_logic.set_state(db, "hourly_summaries_enabled", str(bool(payload["hourly_summaries_enabled"])).lower())
    if "classification_interval_seconds" in payload:
        try:
            val = max(300, int(payload["classification_interval_seconds"]))
            agent_logic.set_state(db, "classification_interval_seconds", str(val))
        except Exception:
            raise HTTPException(status_code=400, detail="classification_interval_seconds must be an integer >= 300")
    if "llm_daily_cap" in payload:
        try:
            val = max(1, int(payload["llm_daily_cap"]))
            agent_logic.set_state(db, "llm_daily_cap", str(val))
        except Exception:
            raise HTTPException(status_code=400, detail="llm_daily_cap must be an integer >= 1")
    if "user_timezone" in payload:
        from zoneinfo import ZoneInfo
        tz_name = str(payload["user_timezone"])
        try:
            ZoneInfo(tz_name)  # validate
            agent_logic.set_state(db, "user_timezone", tz_name)
        except Exception:
            raise HTTPException(status_code=400, detail=f"Invalid timezone: {tz_name}")
    return {"status": "updated"}


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
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "created", "zone": zone}


@app.patch("/api/zones/{zone_id}")
def patch_zone(zone_id: int, payload: Dict[str, Any], db: Session = Depends(get_db)):
    try:
        zone = agent_logic.upsert_zone(db, payload, zone_id=zone_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
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
                }
                for l in logs
            ]
        }
    if method == "get_daily_analytics":
        return {"result": await analytics_today(db)}
    if method == "set_tracking":
        enabled = bool(params.get("enabled", True))
        agent_logic.set_state(db, "tracking_enabled", str(enabled).lower())
        return {"result": {"tracking_enabled": enabled}}
    if method == "set_polling_interval":
        seconds = max(60, int(params.get("seconds", 60)))
        agent_logic.set_state(db, "polling_interval_seconds", str(seconds))
        return {"result": {"polling_interval_seconds": seconds}}
    if method == "send_checkin":
        message = str(params.get("message") or "").strip()
        if not message:
            raise HTTPException(status_code=400, detail="message is required")
        return {"result": await chat_message({"message": message}, db)}
    if method == "get_pending_checkin":
        return {"result": await get_checkin(db)}
    if method == "reply_to_prompt":
        reply = str(params.get("reply") or "").strip()
        return {"result": await handle_prompt_reply({"reply": reply}, db)}
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
    return logs


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


@app.get("/api/summary/{log_id}")
async def get_log_summary(log_id: int, db: Session = Depends(get_db)):
    entry = db.query(ActivityLog).filter(ActivityLog.id == log_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Log not found")

    if entry.device == "mac":
        app_name = entry.app_name or "Unknown App"
        title = entry.window_title or "Unknown Title"
        import llm_client
        if not agent_logic.can_use_llm(db):
            return {"summary": "AI budget reached; summary generation is temporarily disabled today."}
        agent_logic.register_llm_call(db)
        summary = await llm_client.generate_activity_summary(app_name, title)
        return {"summary": summary}
    else:
        return {"summary": f"User was {entry.activity_type} near {entry.location_label}."}

@app.get("/api/hourly-summaries")
def get_hourly_summaries(limit: int = 5, db: Session = Depends(get_db)):
    summaries = db.query(HourlySummary).order_by(desc(HourlySummary.hour_start)).limit(limit).all()
    return [
        {
            "id": s.id,
            "hour_start": s.hour_start,
            "summary_text": s.summary_text,
            "productivity_score": s.productivity_score,
        }
        for s in summaries
    ]


@app.post("/api/trigger-hourly-summary")
async def trigger_hourly_summary(db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    await agent_logic._generate_and_store_hourly_summary(db, now)
    return {"status": "ok"}


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
    agent_logic.set_state(db, "pending_checkin", "")
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
    history_key = f"chat_history:{now.strftime('%Y-%m-%d')}"
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

    # Use LLM to generate a smart response if budget allows
    if agent_logic.can_use_llm(db, now):
        agent_logic.register_llm_call(db, now)
        import llm_client
        prompt = (
            f"You are Vero, a personal productivity AI. The user just told you:\n"
            f'"{message}"\n\n'
            f"Current context: {context_str}\n\n"
            f"Recent chat context:\n{prior_context or '- No recent conversation.'}\n\n"
            "Respond in 1-2 short sentences. Be direct, helpful, and specific. "
            "Acknowledge what they said, confirm what the system will track next, and if useful suggest the next likely state "
            "(for example study, class, workout, commute, or break). Do not sound generic."
        )
        reply = await llm_client.ask_gemini(prompt)
        if not reply:
            reply = "Got it. I'll track that and update your context."
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
    history_key = f"chat_history:{now.strftime('%Y-%m-%d')}"
    existing = agent_logic.get_state(db, history_key, "[]")
    try:
        history = json.loads(existing)
    except Exception:
        history = []
    return {"messages": history}


@app.get("/api/checkin")
def get_checkin(db: Session = Depends(get_db)):
    """Check if there's a pending check-in question for the user."""
    checkin = agent_logic.get_state(db, "pending_checkin")
    guess = agent_logic.get_state(db, "checkin_guess")
    if not checkin:
        return {"checkin": None}
    return {"checkin": checkin, "guess": guess}


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

    agent_logic.set_state(db, "pending_checkin", "")
    agent_logic.set_state(db, "checkin_guess", "")
    agent_logic.set_state(db, "last_user_checkin", now.isoformat())
    return {"status": "ok"}


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
    checklist = [
        {"id": "zone_arrive", "label": "Zone arrive automations", "configured": states.get("seen_arrive_automation") == "true"},
        {"id": "zone_leave", "label": "Zone leave automations", "configured": states.get("seen_leave_automation") == "true"},
        {"id": "walking", "label": "Walking automation", "configured": states.get("seen_walking_automation") == "true"},
        {"id": "charging_stationary", "label": "Charging on/off automations", "configured": states.get("seen_charging_automation") == "true"},
    ]
    return {
        "ios_recent_ping": states.get("ios_recent_event", False),
        "last_ios_ping_age_seconds": last_ios_ping_age,
        "sleep_source": states.get("sleep_source", "iphone_only"),
        "sleep_status_note": states.get("sleep_status_note", ""),
        "zones": agent_logic.list_zones(db),
        "checklist": checklist,
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
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600&display=swap" rel="stylesheet">
<style>
  body {{ font-family: 'Inter', sans-serif; background: #0d1117; color: #f0f6fc; padding: 2rem; max-width: 600px; margin: 0 auto; }}
  h1 {{ font-size: 1.5rem; margin-bottom: 0.5rem; }}
  h2 {{ font-size: 1.1rem; color: #58a6ff; margin: 2rem 0 0.75rem; }}
  p {{ color: #8b949e; line-height: 1.6; }}
  .step {{ background: rgba(22,27,34,0.8); border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; padding: 1.25rem; margin: 1rem 0; }}
  .step-num {{ font-size: 0.75rem; color: #58a6ff; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 0.5rem; }}
  code {{ background: rgba(88,166,255,0.1); color: #58a6ff; padding: 0.2rem 0.5rem; border-radius: 6px; font-size: 0.9rem; font-family: monospace; }}
  .action-btn {{ display: inline-block; text-align: center; background: #58a6ff; color: #000; padding: 0.75rem 1.5rem; border-radius: 10px; font-weight: 600; text-decoration: none; font-size: 1rem; border: none; cursor: pointer; }}
  .action-btn:hover {{ background: #79b8ff; }}
  .note {{ font-size: 0.85rem; color: #8b949e; margin-top: 0.75rem; }}
  .divider {{ border: none; border-top: 1px solid rgba(255,255,255,0.08); margin: 2rem 0; }}
  .badge-remote {{ background: rgba(63,185,80,0.15); color: #3fb950; border: 1px solid rgba(63,185,80,0.3); border-radius: 6px; padding: 0.2rem 0.6rem; font-size: 0.8rem; font-weight: 600; margin-left: 0.5rem; }}
  .cmd-box {{ background: #161b22; border: 1px solid rgba(255,255,255,0.1); border-radius: 8px; padding: 1rem 1rem 1rem 1rem; font-family: 'SF Mono', 'Menlo', monospace; font-size: 0.85rem; color: #e6edf3; overflow-x: auto; white-space: pre-wrap; word-break: break-all; position: relative; margin: 0.75rem 0; line-height: 1.6; }}
  pre.cmd {{ background: #161b22; border: 1px solid rgba(255,255,255,0.1); border-radius: 8px; padding: 1rem; overflow-x: auto; font-size: 0.85rem; color: #c9d1d9; white-space: pre-wrap; word-break: break-all; position: relative; }}
  pre.cmd .copy-btn {{ position: absolute; top: 0.5rem; right: 0.5rem; background: rgba(88,166,255,0.2); color: #58a6ff; border: 1px solid rgba(88,166,255,0.3); border-radius: 6px; padding: 0.25rem 0.5rem; font-size: 0.75rem; cursor: pointer; font-family: 'Inter', sans-serif; }}
  pre.cmd .copy-btn:hover {{ background: rgba(88,166,255,0.4); }}
  .checklist li {{ color: #8b949e; margin: 0.4rem 0; }}
  .checklist li span {{ color: #3fb950; margin-right: 0.5rem; }}
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
  <a href="/" style="color:#8b949e;text-decoration:none;font-size:0.9rem;display:inline-flex;align-items:center;gap:0.4rem;">
    ← Dashboard
  </a>
</nav>
<h1>💻 Mac App Setup <span class="badge-remote" style="{remote_only}">☁️ Cloud</span></h1>
<p>Install the native Vero app once, then let the hidden login helper run quietly in the background.</p>

<h2>Prerequisites</h2>
<div class="step">
  <ul class="checklist">
    <li><span>→</span>macOS 13 Ventura or later</li>
    <li><span>→</span>Xcode installed from the App Store</li>
    <li><span>→</span>Xcode Command Line Tools ready &nbsp;<code>xcodebuild -version</code></li>
  </ul>
  <p class="note">You only need to run the visible app once. After that, the login helper should keep the agent alive in the background.</p>
</div>

<h2>Step 1 — Open the native project</h2>
<div class="step">
  <div class="step-num">Paste this into Terminal and let Xcode open the app project</div>
  <pre class="cmd"><button class="copy-btn" onclick="copyCmd(this)">Copy</button>git clone https://github.com/hnaboulsi/vero.git ~/vero 2>/dev/null || git -C ~/vero pull && (brew list xcodegen >/dev/null 2>&1 || brew install xcodegen) && cd ~/vero/mac_native && xcodegen generate && open LifeManager.xcodeproj</pre>
  <p class="note">This updates the repo, ensures XcodeGen is installed, generates the native macOS project, and opens it in Xcode.</p>
</div>

<h2>Step 2 — Configure authentication</h2>
<div class="step" style="{remote_only}">
  <div class="step-num">Set your dashboard password so the tracker can authenticate</div>
  <pre class="cmd"><button class="copy-btn" onclick="copyCmd(this)">Copy</button>echo "admin:YOUR_PASSWORD" > ~/.config/life-manager/auth</pre>
  <p class="note">Replace <code>YOUR_PASSWORD</code> with your actual dashboard password. The tracker uses HTTP Basic Auth to send data securely.</p>
</div>
<div class="step" style="{'display:none' if is_remote else ''}">
  <p>Auth not required for local setup — the tracker connects directly to <code>localhost:8000</code>.</p>
</div>

<h2>Step 3 — Run it once, then close it</h2>
<div class="step">
  <div class="step-num">In Xcode, choose the <strong>LifeManager</strong> scheme and press Run once</div>
  <p>When the app opens, grant the permissions it asks for, then close the window. The goal is to register the hidden login helper, not keep a visible app open.</p>
  <p class="note">If you already have <code>Vero.app</code> in Applications, you can launch it directly with <code>open -a "Vero"</code>.</p>
</div>

<hr class="divider">

<h2>Verify</h2>
<div class="step">
  <div class="step-num">Check that data is arriving</div>
  <p>Go back to the <a href="/" style="color:#58a6ff">Control Center</a> — the Mac card should show <strong>Online</strong> within 60 seconds. If the app window is closed and the Mac stays online, the hidden helper is doing its job.</p>
</div>

<h2>Troubleshooting</h2>
<div class="step">
  <p><strong>Mac still offline?</strong> Open Vero again and use the diagnostics view to check helper registration and permissions.</p>
  <p><strong>Missing permissions?</strong> Re-open the app and grant Accessibility, Notifications, and Calendar access.</p>
  <p><strong>Backend offline error?</strong> Check your backend URL is correct: <code>cat ~/.config/life-manager/backend.url</code></p>
  <p><strong>Auth errors?</strong> Check your password: <code>cat ~/.config/life-manager/auth</code></p>
  <p class="note">If the helper still will not connect, reopen the app and use the built-in diagnostics screen before digging into local logs.</p>
</div>
</body>
</html>"""


@app.get("/setup/ios", response_class=HTMLResponse)
async def ios_setup_page():
    import shutil as _shutil
    backend_url = _get_backend_url()
    is_remote = backend_url.startswith("https://")
    can_auto_sign = bool(_shutil.which("shortcuts"))  # True only on local macOS
    network_note = "Works from any network worldwide." if is_remote else "iPhone must be on the same WiFi network as your Mac."

    remote_only = "" if is_remote else "display:none"
    local_only = "display:none" if is_remote else ""
    # Signing section: show only when on Railway (can't sign on Linux)
    signing_section_display = "" if (is_remote and not can_auto_sign) else "display:none"
    auto_signed_badge = "" if can_auto_sign else "display:none"
    # "Sign all" button: only useful when running locally on macOS
    sign_all_display = "" if (not is_remote and can_auto_sign) else "display:none"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>iPhone Setup — Vero</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600&display=swap" rel="stylesheet">
<style>
  body {{ font-family: 'Inter', sans-serif; background: #0d1117; color: #f0f6fc; padding: 2rem; max-width: 600px; margin: 0 auto; }}
  h1 {{ font-size: 1.5rem; margin-bottom: 0.5rem; }}
  h2 {{ font-size: 1.1rem; color: #58a6ff; margin: 2rem 0 0.75rem; }}
  p {{ color: #8b949e; line-height: 1.6; }}
  .step {{ background: rgba(22,27,34,0.8); border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; padding: 1.25rem; margin: 1rem 0; }}
  .step-num {{ font-size: 0.75rem; color: #58a6ff; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 0.5rem; }}
  code {{ background: rgba(88,166,255,0.1); color: #58a6ff; padding: 0.2rem 0.5rem; border-radius: 6px; font-size: 0.9rem; font-family: monospace; }}
  .url-box {{ background: rgba(88,166,255,0.08); border: 1px solid rgba(88,166,255,0.3); border-radius: 8px; padding: 1rem; font-family: monospace; font-size: 1.1rem; color: #58a6ff; word-break: break-all; margin: 1rem 0; }}
  .action-btn {{ display: inline-block; text-align: center; background: #58a6ff; color: #000; padding: 0.75rem 1.5rem; border-radius: 10px; font-weight: 600; text-decoration: none; font-size: 1rem; border: none; cursor: pointer; }}
  .action-btn:hover {{ background: #79b8ff; }}
  .note {{ font-size: 0.85rem; color: #8b949e; margin-top: 0.75rem; }}
  .divider {{ border: none; border-top: 1px solid rgba(255,255,255,0.08); margin: 2rem 0; }}
  .badge-remote {{ background: rgba(63,185,80,0.15); color: #3fb950; border: 1px solid rgba(63,185,80,0.3); border-radius: 6px; padding: 0.2rem 0.6rem; font-size: 0.8rem; font-weight: 600; margin-left: 0.5rem; }}
  .badge-signed {{ background: rgba(88,166,255,0.15); color: #58a6ff; border: 1px solid rgba(88,166,255,0.3); border-radius: 6px; padding: 0.2rem 0.6rem; font-size: 0.8rem; font-weight: 600; }}
  .cmd-box {{ background: #161b22; border: 1px solid rgba(255,255,255,0.1); border-radius: 8px; padding: 1rem 1rem 1rem 1rem; font-family: 'SF Mono', 'Menlo', monospace; font-size: 0.85rem; color: #e6edf3; overflow-x: auto; white-space: pre-wrap; word-break: break-all; position: relative; margin: 0.75rem 0; line-height: 1.6; }}
  .cmd-box .cmt {{ color: #8b949e; }}
  .copy-btn {{ position: absolute; top: 0.5rem; right: 0.5rem; background: rgba(88,166,255,0.15); color: #58a6ff; border: 1px solid rgba(88,166,255,0.3); border-radius: 6px; padding: 0.25rem 0.6rem; font-size: 0.75rem; cursor: pointer; font-family: 'Inter', sans-serif; }}
  .copy-btn:hover {{ background: rgba(88,166,255,0.3); }}
  pre.cmd {{ background: #161b22; border: 1px solid rgba(255,255,255,0.1); border-radius: 8px; padding: 1rem; overflow-x: auto; font-size: 0.85rem; color: #c9d1d9; white-space: pre-wrap; word-break: break-all; position: relative; }}
  pre.cmd .copy-btn {{ position: absolute; top: 0.5rem; right: 0.5rem; background: rgba(88,166,255,0.2); color: #58a6ff; border: 1px solid rgba(88,166,255,0.3); border-radius: 6px; padding: 0.25rem 0.5rem; font-size: 0.75rem; cursor: pointer; font-family: 'Inter', sans-serif; }}
  pre.cmd .copy-btn:hover {{ background: rgba(88,166,255,0.4); }}
  .signing-note {{ background: rgba(210,153,34,0.1); border: 1px solid rgba(210,153,34,0.3); border-radius: 8px; padding: 1rem; margin: 1rem 0; }}
  .signing-note strong {{ color: #d29922; }}
</style>
<script>
function copyCmd(btn) {{
  // Clone the pre, remove the button node, then grab remaining text
  const pre = btn.closest('pre');
  const clone = pre.cloneNode(true);
  clone.querySelectorAll('button').forEach(b => b.remove());
  const text = clone.textContent.trim();
  navigator.clipboard.writeText(text).then(() => {{
    btn.textContent = 'Copied!';
    btn.style.color = '#3fb950';
    setTimeout(() => {{ btn.textContent = 'Copy'; btn.style.color = ''; }}, 2000);
  }}).catch(() => {{
    // Fallback for older browsers
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
  <a href="/" style="color:#8b949e;text-decoration:none;font-size:0.9rem;display:inline-flex;align-items:center;gap:0.4rem;">
    ← Dashboard
  </a>
</nav>
<h1>📱 iPhone Setup <span class="badge-remote" style="{remote_only}">☁️ Cloud</span></h1>
<p>Follow these steps to set up low-battery iPhone automations. The default model is zone enter/leave events, not periodic GPS polling.</p>

<!-- ── Step 1: Download ─────────────────────────────── -->
<h2>Step 1 — Download only the helper shortcuts you actually need</h2>
<div class="step">
  <div class="step-num">On your Mac — open this page in Safari or Chrome</div>
  <p>
    <span style="{auto_signed_badge}" class="badge-signed">✅ Auto-signed</span>
    <span style="{signing_section_display}" class="badge-signed" style="background:rgba(210,153,34,0.15);color:#d29922;border-color:rgba(210,153,34,0.3);">⚠️ Requires signing — see Step 2</span>
  </p>
  <p style="margin: 0.75rem 0 1rem; font-size:0.88rem; line-height:1.7;">
    <strong style="color:#f0f6fc;">Walking</strong> <span style="color:#8b949e;">— Fires when your iPhone detects a walking workout (best when triggered by Apple Watch walking workouts).</span><br>
    <strong style="color:#f0f6fc;">Charging On/Off</strong> <span style="color:#8b949e;">— Logs when you plug in or unplug (used for sleep inference).</span><br>
    <strong style="color:#f0f6fc;">GPS Ping / Arrive</strong> <span style="color:#8b949e;">— Legacy helpers only. Zone enter/leave automations in Step 4 are the recommended default.</span>
  </p>
  <p style="margin-top:1rem">
    <a class="action-btn" href="/setup/shortcut/download?kind=walking">⬇ Walking</a>&nbsp;
    <a class="action-btn" href="/setup/shortcut/download?kind=charge_on">⬇ Charging On</a>&nbsp;
    <a class="action-btn" href="/setup/shortcut/download?kind=charge_off">⬇ Charging Off</a>
  </p>
  <p class="note" style="margin-top:0.75rem;">Only download the legacy helpers if you intentionally want them:</p>
  <p style="margin-top:0.5rem">
    <a class="action-btn" href="/setup/shortcut/download?kind=gps" style="font-size:0.85rem;padding:0.55rem 1rem;">Legacy GPS Ping</a>&nbsp;
    <a class="action-btn" href="/setup/shortcut/download?kind=arrive" style="font-size:0.85rem;padding:0.55rem 1rem;">Legacy Arrive</a>
  </p>
  <!-- One-click sign all — only shows when running locally on Mac -->
  <div style="{sign_all_display}; margin-top:1rem;">
    <a class="action-btn" href="/setup/shortcut/sign-all" style="background:#3fb950;color:#000;">⚡ Download &amp; Sign All to Desktop</a>
    <p class="note">Saves all 5 signed shortcuts to your Desktop and opens Finder. Then AirDrop to iPhone.</p>
  </div>
</div>

<!-- ── Step 2: Sign (Railway only) ─────────────────── -->
<div style="{signing_section_display}">
<h2>Step 2 — Download &amp; sign shortcuts on your Mac</h2>
<div class="signing-note">
  <strong>⚠️ Required when using Railway:</strong> iOS will not import unsigned shortcuts. Run this one-liner in Terminal — it downloads all 5 and signs them in one step.
</div>
<div class="step">
  <div class="step-num">Open Terminal on your Mac and paste this command</div>
  <pre class="cmd"><button class="copy-btn" onclick="copyCmd(this)">Copy</button>cd ~/Desktop && for kind in gps arrive walking charge_on charge_off; do
  curl -s "{backend_url}/setup/shortcut/download?kind=$kind" -o "Vero-$kind.shortcut" && \\
  shortcuts sign -m anyone -i "Vero-$kind.shortcut" -o "Vero-$kind.shortcut" && \\
  echo "Signed: $kind"
done && echo "All 5 shortcuts ready on your Desktop."</pre>
  <p class="note">This saves 5 signed <code>.shortcut</code> files to your Desktop. Then AirDrop them to your iPhone.</p>
</div>
</div>

<!-- ── Step 3: Send to iPhone ─────────────────────── -->
<h2 id="step-send">Step 3 — Send to iPhone</h2>
<div class="step">
  <div class="step-num">Method A — AirDrop (fastest)</div>
  <p>In Finder, right-click each <code>.shortcut</code> file → <strong>Share → AirDrop</strong> → select your iPhone. Tap <strong>Add Shortcut</strong> for each.</p>
</div>
<div class="step" style="{local_only}">
  <div class="step-num">Method B — iCloud Drive (no AirDrop needed)</div>
  <p><a class="action-btn" href="/setup/save-to-icloud" style="font-size:0.9rem;padding:0.5rem 1rem;">Save helper shortcut to iCloud Drive →</a></p>
  <p class="note">On iPhone: <strong>Files app → iCloud Drive → Vero.shortcut → Add Shortcut</strong>. Use this for the walking helper if you do not want to AirDrop.</p>
</div>

<hr class="divider">

<!-- ── Step 4: Automations ────────────────────────── -->
<h2>Step 4 — Create automations on iPhone</h2>
<div class="step">
  <div class="step-num">In the Shortcuts app → Automation tab → + New Automation</div>
  <p><strong>Preferred model: zone state, not 30-minute GPS polling.</strong></p>
  <p class="note">Create geofences with a radius of about 50-100 meters for: <strong>Anchor House</strong>, <strong>Dwinelle Hall</strong>, <strong>Wheeler Hall</strong>, <strong>VLSB</strong>, and optionally <strong>Doe/Moffitt</strong> and <strong>RSF</strong>.</p>
  <ol style="margin:0.5rem 0 1rem 1.5rem;color:#c9d1d9;line-height:1.8">
    <li>For each zone, create an <strong>Arrive</strong> automation and a <strong>Leave</strong> automation.</li>
    <li>In each automation, use <strong>Get Contents of URL</strong> to fetch exactly this URL, replacing <code>slug</code> with your zone's slug:</li>
    <pre class="cmd" style="margin-top:0.5rem;"><button class="copy-btn" onclick="copyCmd(this)">Copy</button>{backend_url}/api/ios-zone-event?zone=slug&transition=enter</pre>
    <li style="margin-top:0.5rem;">For leaving a zone, use <code>transition=exit</code> at the end instead. Because it uses the URL, no JSON typing or Smart Punctuation errors can happen.</li>
    <li>For Dwinelle and Wheeler, optionally add <strong>Set Focus → Class</strong> before the network action. For VLSB or Doe/Moffitt, optionally add <strong>Set Focus → Deep Work</strong>.</li>
    <li>For Anchor House arrival, optionally turn Focus off before the network action.</li>
  </ol>
  <p class="note">This tracks intentional blocks, commute timing, and time-in-zone. It is lower power and more accurate than 30-minute GPS polling.</p>
  <p class="note">Apple supports automatic run for these trigger types when <strong>Ask Before Running</strong> is turned off, so <em>Arrive</em>, <em>Leave</em>, <em>Workout</em>, and <em>Charger</em> automations can stay hands-off once you set them up.</p>

  <p><strong>Apple Watch walking signal</strong></p>
  <p class="note">Create one more automation: <em>Workout → Walking → Starts</em> → Run Shortcut <strong>Vero Walking</strong>. In the Watch app on iPhone, enable <strong>Workout Start Reminder</strong> and <strong>Workout End Reminder</strong>.</p>

  <p><strong>Sleep signal</strong></p>
  <p class="note"><em>Charger connected</em> → Run Shortcut <strong>Vero Charging On</strong>; <em>Charger disconnected</em> → Run Shortcut <strong>Vero Charging Off</strong>.</p>

  <p><strong>Legacy fallback only</strong></p>
  <p class="note">If you still want a periodic heartbeat, you can keep the old Focus-loop GPS Ping shortcut, but it is no longer the recommended setup.</p>
</div>

<h2>Step 5 — Calendar sync (recommended setup)</h2>
<div class="step">
  <div class="step-num">Recommended</div>
  <p>On your Mac, go to <strong>System Settings → Apple Account → iCloud</strong> and make sure <strong>Calendar</strong> is turned <strong>On</strong>.</p>
  <p><strong>Detected target:</strong> the Mac helper writes to Apple Calendar locally. For cloud sync, the <strong>Vero</strong> calendar should live under the <strong>iCloud</strong> section in Calendar.app, not only under <strong>On My Mac</strong>.</p>
  <p><strong>Fix this if needed:</strong> if you want Google visibility too, add Google under <strong>System Settings → Internet Accounts</strong>, enable Calendar for that account, and let Apple Calendar handle the sync. Vero still writes only to Apple Calendar on the Mac.</p>
</div>

<h2>Your backend URL</h2>
<div class="url-box">{backend_url}</div>
<p class="note">{network_note}</p>

<h2>Verify</h2>
<div class="step">
  <div class="step-num">Run each shortcut once manually in the Shortcuts app</div>
  <p>Then check <a href="/api/ios-setup-status" style="color:#58a6ff">/api/ios-setup-status</a> — all items should show as configured. Personal automations are created per device, so build these on the iPhone that will actually run them.</p>
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


def _build_shortcut_bytes(kind: str = "gps", sign: bool = True) -> bytes:
    """Generate shortcut bytes for all iOS automation types."""
    import plistlib
    import uuid

    kind = (kind or "gps").lower()
    templates = {
        "gps": {
            "name": "Vero GPS",
            "activity": "ios_ping",
            "is_charging": None,
            "use_location_action": True,
            "location_label": "current_location",
        },
        "arrive": {
            "name": "Vero Arrive",
            "activity": "Arrive",
            "is_charging": "false",
            "use_location_action": False,
            "location_label": "arrive_trigger",
        },
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
    if kind not in templates:
        raise ValueError(f"Unknown shortcut kind: {kind}")

    cfg = templates[kind]
    backend_url = _get_backend_url() + "/api/ios-telemetry"
    post_uuid = str(uuid.uuid4()).upper()
    loc_uuid = str(uuid.uuid4()).upper()
    batt_uuid = str(uuid.uuid4()).upper()

    def _dict_item(key: str, value_obj: dict) -> dict:
        return {
            "WFItemType": 0,
            "WFKey": {"Value": {"string": key}, "WFSerializationType": "WFTextTokenString"},
            "WFValue": value_obj,
        }

    def _action_ref(output_name: str, output_uuid: str) -> dict:
        """Reference to a previous action's output as a text token."""
        return {
            "Value": {
                "attachmentsByRange": {"{0, 1}": {"Type": "ActionOutput", "OutputName": output_name, "OutputUUID": output_uuid}},
                "string": "\ufffc",
            },
            "WFSerializationType": "WFTextTokenString",
        }

    if cfg["use_location_action"]:
        location_value = _action_ref("MyLocation", loc_uuid)
    else:
        location_value = {
            "Value": {"string": cfg["location_label"]},
            "WFSerializationType": "WFTextTokenString",
        }

    # Battery level token (output from the battery action below)
    battery_value = _action_ref("BatteryLevel", batt_uuid)

    payload_items = [
        _dict_item("location_label", location_value),
        _dict_item(
            "activity_type",
            {"Value": {"string": cfg["activity"]}, "WFSerializationType": "WFTextTokenString"},
        ),
        _dict_item("battery_level", battery_value),
    ]
    if cfg["is_charging"] is not None:
        payload_items.append(
            _dict_item(
                "is_charging",
                {"Value": {"string": cfg["is_charging"]}, "WFSerializationType": "WFTextTokenString"},
            )
        )

    actions = []
    # Get battery level (available on all devices, no permission needed)
    actions.append({
        "WFWorkflowActionIdentifier": "is.workflow.actions.getbatterylevel",
        "WFWorkflowActionParameters": {"CustomOutputName": "BatteryLevel", "UUID": batt_uuid},
    })
    if cfg["use_location_action"]:
        actions.append(
            {
                "WFWorkflowActionIdentifier": "is.workflow.actions.location",
                "WFWorkflowActionParameters": {"CustomOutputName": "MyLocation", "UUID": loc_uuid},
            }
        )

    actions.append(
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.downloadurl",
            "WFWorkflowActionParameters": {
                "WFURL": backend_url,
                "WFHTTPMethod": "POST",
                "WFHTTPBodyType": "Json",
                "ShowHeaders": False,
                "UUID": post_uuid,
                "WFRequestVariable": {
                    "Value": {"WFDictionaryFieldValueItems": payload_items},
                    "WFSerializationType": "WFDictionaryFieldValue",
                },
            },
        }
    )

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
async def download_shortcut(kind: str = "gps"):
    from fastapi.responses import Response
    filename = f"Vero-{kind}.shortcut"
    try:
        shortcut_bytes = _build_shortcut_bytes(kind)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid shortcut kind")
    return Response(
        content=shortcut_bytes,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/setup/shortcut/sign-all")
async def sign_all_shortcuts():
    """Download, sign, and save all 5 shortcuts to Desktop — macOS only."""
    import os, shutil, subprocess
    from fastapi.responses import HTMLResponse as HR
    if not shutil.which("shortcuts"):
        return HR("<p style='font-family:sans-serif;color:#f85149'>This endpoint only works when the backend is running locally on macOS.</p>")
    desktop = os.path.expanduser("~/Desktop")
    kinds = ["gps", "arrive", "walking", "charge_on", "charge_off"]
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
    """Daily analytics: time per category, productivity %, steps, LLM usage."""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Get all mac logs from today
    logs = (
        db.query(ActivityLog)
        .filter(ActivityLog.device == "mac", ActivityLog.timestamp >= today_start)
        .order_by(ActivityLog.timestamp)
        .all()
    )

    # Compute time per category using log intervals
    states = agent_logic.get_all_states(db)
    polling_secs = max(60, int(states.get("polling_interval_seconds", "60")))
    category_minutes = {}
    total_active_minutes = 0
    for entry in logs:
        if entry.is_idle:
            continue
        cat = "unknown"
        # Classify each log entry using heuristics (no LLM to save budget)
        text_data = f"{(entry.app_name or '').lower()} {(entry.window_title or '').lower()}"
        for needles, result in [
            (["instagram", "twitter", "x.com", "tiktok", "snapchat", "discord"], "social_media"),
            (["youtube", "netflix", "reddit", "spotify", "hulu"], "entertainment"),
            (["steam", "epic", "game"], "gaming"),
            (["canvas", "gradescope", "homework", "lecture", "course", "quiz"], "studying"),
            (["figma", "photoshop", "premiere", "final cut", "design"], "creative"),
            (["vscode", "pycharm", "cursor", "terminal", "github", "slack", "notion"], "working"),
        ]:
            if any(n in text_data for n in needles):
                cat = result
                break
        else:
            cat = "break"
        interval_min = polling_secs / 60
        category_minutes[cat] = category_minutes.get(cat, 0) + interval_min
        total_active_minutes += interval_min

    productive_cats = {"studying", "working", "creative"}
    productive_minutes = sum(category_minutes.get(c, 0) for c in productive_cats)
    productive_pct = round((productive_minutes / total_active_minutes * 100) if total_active_minutes > 0 else 0)

    # Steps
    steps = states.get("steps_today", "0")

    # LLM usage
    llm_stats = agent_logic.llm_usage_snapshot(db, now)

    return {
        "category_minutes": category_minutes,
        "total_active_minutes": round(total_active_minutes),
        "productive_minutes": round(productive_minutes),
        "productive_pct": productive_pct,
        "steps_today": int(steps) if steps else 0,
        "llm_used": llm_stats["daily_used"],
        "llm_cap": llm_stats["daily_cap"],
        "log_count": len(logs),
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
