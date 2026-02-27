from fastapi import FastAPI, Depends, BackgroundTasks, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session
from sqlalchemy import desc, text
from database import engine, Base, get_db
import models
from models import ActivityLog, HourlySummary, MacTelemetry, iOSTelemetry
import agent_logic
from typing import Dict, Any
import os
import base64
import secrets
from datetime import datetime

# Create tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Life-Manager Agent API")
_STARTED_AT = datetime.utcnow()

# Telemetry endpoints are called by Mac tracker and iPhone shortcut — no auth needed
_NO_AUTH_PATHS = {"/api/mac-telemetry", "/api/ios-telemetry"}

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
        print(f"Auth: IP {ip} blocked for 15 min after {entry['count']} failures")


def _clear_failures(ip: str):
    _failed_attempts.pop(ip, None)


@app.middleware("http")
async def basic_auth_middleware(request: Request, call_next):
    if request.url.path in _NO_AUTH_PATHS:
        return await call_next(request)

    username = os.environ.get("DASHBOARD_USER", "admin")
    password = os.environ.get("DASHBOARD_PASS", "")
    if not password:
        return await call_next(request)  # No password set — open (local dev)

    client_ip = request.client.host if request.client else "unknown"

    if _is_blocked(client_ip):
        return Response(content="Too many failed attempts. Try again in 15 minutes.", status_code=429)

    auth = request.headers.get("Authorization", "")
    if auth.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth[6:]).decode("utf-8")
            u, _, p = decoded.partition(":")
            if secrets.compare_digest(u, username) and secrets.compare_digest(p, password):
                _clear_failures(client_ip)
                return await call_next(request)
        except Exception:
            pass

    _record_failure(client_ip)
    return Response(
        content="Unauthorized",
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="Life Manager"'},
    )

# Serve frontend static files
from fastapi.responses import RedirectResponse
frontend_path = os.path.join(os.path.dirname(__file__), "frontend")
os.makedirs(frontend_path, exist_ok=True)
app.mount("/dashboard", StaticFiles(directory=frontend_path, html=True), name="frontend")

@app.get("/")
async def redirect_to_dashboard():
    return RedirectResponse(url="/dashboard/index.html")

@app.post("/api/mac-telemetry")
async def receive_mac_telemetry(data: MacTelemetry, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    log_entry = ActivityLog(
        device="mac",
        app_name=data.app_name,
        window_title=data.window_title,
        is_idle=data.idle_time_seconds > 60 * 30
    )
    db.add(log_entry)
    db.commit()
    
    background_tasks.add_task(agent_logic.process_mac_telemetry, data, db, background_tasks)
    pending_prompt = agent_logic.get_pending_prompt(db)
    return {"status": "ok", "prompt": pending_prompt}


@app.post("/api/ios-telemetry")
async def receive_ios_telemetry(data: iOSTelemetry, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    log_entry = ActivityLog(
        device="ios",
        location_label=data.location_label,
        activity_type=data.activity_type,
        latitude=data.latitude,
        longitude=data.longitude,
        steps_today=data.steps_today,
    )
    db.add(log_entry)
    db.commit()

    background_tasks.add_task(agent_logic.process_ios_telemetry, data, db)
    return {"status": "ok"}


@app.get("/api/state")
async def get_state(db: Session = Depends(get_db)):
    agent_logic.ensure_default_settings(db)
    states = agent_logic.get_all_states(db)
    try:
        polling_interval_seconds = int(agent_logic.get_state(db, "polling_interval_seconds", "60"))
    except Exception:
        polling_interval_seconds = 60
    mac_online_threshold_seconds = max(300, polling_interval_seconds * 2 + 30)
    last_ping_str = states.get("last_mac_ping", "")
    last_ios_ping_str = states.get("last_ios_ping", "")
    last_mac_ping_age_seconds = None
    last_ios_ping_age_seconds = None
    if last_ping_str:
        try:
            last_ping = datetime.fromisoformat(last_ping_str)
            last_mac_ping_age_seconds = int((datetime.utcnow() - last_ping).total_seconds())
            states["mac_online"] = last_mac_ping_age_seconds <= mac_online_threshold_seconds
        except Exception:
            states["mac_online"] = False
    else:
        states["mac_online"] = False
    if last_ios_ping_str:
        try:
            ios_ping = datetime.fromisoformat(last_ios_ping_str)
            last_ios_ping_age_seconds = int((datetime.utcnow() - ios_ping).total_seconds())
        except Exception:
            pass
    states["backend_target_url"] = _get_backend_url()
    states["polling_interval_seconds"] = polling_interval_seconds
    states["mac_online_threshold_seconds"] = mac_online_threshold_seconds
    states["last_mac_ping_age_seconds"] = last_mac_ping_age_seconds
    states["last_ios_ping_age_seconds"] = last_ios_ping_age_seconds
    states["ios_recent_ping"] = (last_ios_ping_age_seconds is not None and last_ios_ping_age_seconds < 7200)
    states["sleep_source"] = agent_logic.get_state(db, "sleep_source", "iphone_only")
    states["sleep_status_note"] = (
        "Sleep detection inactive until iPhone automation pings."
        if not states["ios_recent_ping"] else
        "Sleep detection active from iPhone telemetry."
    )
    if states["mac_online"]:
        states["service_health"] = "ok"
    elif last_mac_ping_age_seconds is not None:
        states["service_health"] = "degraded"
    else:
        states["service_health"] = "offline"
    return states

@app.get("/api/settings")
async def get_settings(db: Session = Depends(get_db)):
    agent_logic.ensure_default_settings(db)
    polling_str = agent_logic.get_state(db, "polling_interval_seconds", "60")
    tracking_enabled_str = agent_logic.get_state(db, "tracking_enabled", "true")
    return {
        "polling_interval_seconds": int(polling_str),
        "tracking_enabled": tracking_enabled_str.lower() == "true",
        "backend_mode": agent_logic.get_state(db, "backend_mode", "railway_primary"),
        "llm_mode": agent_logic.get_state(db, "llm_mode", "ultra_save"),
        "hourly_summaries_enabled": agent_logic.get_state(db, "hourly_summaries_enabled", "false").lower() == "true",
        "classification_interval_seconds": int(agent_logic.get_state(db, "classification_interval_seconds", "1800")),
        "llm_daily_cap": int(agent_logic.get_state(db, "llm_daily_cap", "30")),
    }

@app.post("/api/settings")
async def update_settings(payload: Dict[str, Any], db: Session = Depends(get_db)):
    agent_logic.ensure_default_settings(db)
    if "polling_interval_seconds" in payload:
        agent_logic.set_state(db, "polling_interval_seconds", str(payload["polling_interval_seconds"]))
    if "tracking_enabled" in payload:
        agent_logic.set_state(db, "tracking_enabled", str(payload["tracking_enabled"]).lower())
    if "backend_mode" in payload and payload["backend_mode"] in {"railway_primary", "local_primary", "hybrid_auto"}:
        agent_logic.set_state(db, "backend_mode", payload["backend_mode"])
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
    return {"status": "updated"}

@app.get("/api/logs")
async def get_logs(limit: int = 50, db: Session = Depends(get_db)):
    logs = db.query(ActivityLog).order_by(desc(ActivityLog.timestamp)).limit(limit).all()
    return logs

@app.get("/api/summary/{log_id}")
async def get_log_summary(log_id: int, db: Session = Depends(get_db)):
    log = db.query(ActivityLog).filter(ActivityLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="Log not found")
        
    if log.device == "mac":
        app = log.app_name or "Unknown App"
        title = log.window_title or "Unknown Title"
        import llm_client
        if not agent_logic.can_use_llm(db):
            return {"summary": "AI budget reached; summary generation is temporarily disabled today."}
        agent_logic.register_llm_call(db)
        summary = await llm_client.generate_activity_summary(app, title)
        return {"summary": summary}
    else:
        return {"summary": f"User was {log.activity_type} near {log.location_label}."}

@app.get("/api/hourly-summaries")
async def get_hourly_summaries(limit: int = 5, db: Session = Depends(get_db)):
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


@app.post("/api/prompt-reply")
async def handle_prompt_reply(payload: Dict[str, Any], db: Session = Depends(get_db)):
    reply = payload.get("reply", "")
    agent_logic.clear_pending_prompt(db)
    agent_logic.update_context_with_reply(reply, db)
    return {"status": "accepted"}


@app.get("/api/callout")
async def get_callout(db: Session = Depends(get_db)):
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
async def dismiss_callout(db: Session = Depends(get_db)):
    agent_logic.set_state(db, "callout_category", "")
    agent_logic.set_state(db, "callout_summary", "")
    return {"status": "dismissed"}


@app.get("/api/healthz")
async def healthz(db: Session = Depends(get_db)):
    agent_logic.ensure_default_settings(db)
    db_ok = True
    db_error = ""
    try:
        db.execute(text("SELECT 1"))
    except Exception as e:
        db_ok = False
        db_error = str(e)

    now = datetime.utcnow()
    states = agent_logic.get_all_states(db)
    llm_stats = agent_logic.llm_usage_snapshot(db, now)
    llm_configured = bool(os.environ.get("GEMINI_API_KEY"))

    return {
        "status": "ok" if db_ok else "degraded",
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
            "daily_used": llm_stats["daily_used"],
            "daily_remaining": llm_stats["daily_remaining"],
            "daily_cap": llm_stats["daily_cap"],
            "mode": states.get("llm_mode", "ultra_save"),
        },
        "telemetry": {
            "last_mac_ping": states.get("last_mac_ping", ""),
            "last_ios_ping": states.get("last_ios_ping", ""),
        },
    }


@app.get("/api/ios-setup-status")
async def ios_setup_status(db: Session = Depends(get_db)):
    states = await get_state(db)
    last_ios_ping_age = states.get("last_ios_ping_age_seconds")
    checklist = [
        {"id": "periodic_ping", "label": "Time-of-day ping automation", "configured": states.get("seen_periodic_automation") == "true"},
        {"id": "arrive_location", "label": "Arrive location automation", "configured": states.get("seen_arrive_automation") == "true"},
        {"id": "walking", "label": "Walking automation", "configured": states.get("seen_walking_automation") == "true"},
        {"id": "charging_stationary", "label": "Charging on/off automations", "configured": states.get("seen_charging_automation") == "true"},
    ]
    return {
        "ios_recent_ping": states.get("ios_recent_ping", False),
        "last_ios_ping_age_seconds": last_ios_ping_age,
        "sleep_source": states.get("sleep_source", "iphone_only"),
        "sleep_status_note": states.get("sleep_status_note", ""),
        "checklist": checklist,
    }


@app.get("/setup/ios", response_class=HTMLResponse)
async def ios_setup_page():
    backend_url = _get_backend_url()
    is_remote = backend_url.startswith("https://")
    network_note = "Works from any network worldwide." if is_remote else "iPhone must be on the same WiFi network as your Mac."

    remote_only = "" if is_remote else "display:none"
    local_only = "display:none" if is_remote else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>iPhone Setup — Life Manager</title>
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
</style>
</head>
<body>
<h1>📱 iPhone Setup <span class="badge-remote" style="{remote_only}">☁️ Cloud</span></h1>
<p>iOS blocks shortcuts imported from the browser. Use one of these methods instead — takes under 2 minutes.</p>

<h2>Method A — Download on Mac, AirDrop to iPhone</h2>
<div class="step">
  <div class="step-num">Step 1 — On your Mac (open this page in Safari/Chrome)</div>
  <p>Download and import all 5 shortcuts (AirDrop each file to your iPhone and tap <strong>Add Shortcut</strong>):</p>
  <p>
    <a class="action-btn" href="/setup/shortcut/download?kind=gps">Download GPS Ping</a>
    <a class="action-btn" href="/setup/shortcut/download?kind=arrive">Download Arrive</a>
  </p>
  <p>
    <a class="action-btn" href="/setup/shortcut/download?kind=walking">Download Walking</a>
    <a class="action-btn" href="/setup/shortcut/download?kind=charge_on">Download Charging On</a>
  </p>
  <p>
    <a class="action-btn" href="/setup/shortcut/download?kind=charge_off">Download Charging Off</a>
  </p>
  <p class="note">Each shortcut now has only 2 actions: <strong>Location</strong> + <strong>POST webhook</strong>.</p>
  <p class="note">If AirDrop feels annoying, use iCloud Drive and open the files from the iPhone Files app.</p>
</div>

<hr class="divider" style="{local_only}">

<div style="{local_only}">
<h2>Method B — iCloud Drive (no cables, local only)</h2>
<div class="step">
  <div class="step-num">Step 1 — On your Mac</div>
  <p>Click the button below. It saves <strong>LifeManager.shortcut</strong> to your iCloud Drive and opens Finder there.</p>
  <a class="action-btn" href="/setup/save-to-icloud">Save to iCloud Drive →</a>
  <p class="note">Requires iCloud Drive enabled in System Settings → Apple ID → iCloud.</p>
</div>
<div class="step">
  <div class="step-num">Step 2 — On your iPhone</div>
  <p>Open <strong>Files</strong> app → tap <strong>iCloud Drive</strong> → find <strong>LifeManager.shortcut</strong> → tap it → <strong>Add Shortcut</strong>.</p>
</div>
</div>

<hr class="divider">

<h2>Step 2 — Create all automations (Run Shortcut only)</h2>
<div class="step">
  <div class="step-num">In the Shortcuts app on iPhone</div>
  <p><strong>Automation 1:</strong> Time of Day (every 30 min) → Run Shortcut <strong>Life Manager GPS</strong></p>
  <p><strong>Automation 2:</strong> Arrive (Library/campus) → Run Shortcut <strong>Life Manager Arrive</strong></p>
  <p><strong>Automation 3:</strong> Workout: Walking starts → Run Shortcut <strong>Life Manager Walking</strong></p>
  <p><strong>Automation 4:</strong> Charger connected → Run Shortcut <strong>Life Manager Charging On</strong></p>
  <p><strong>Automation 5:</strong> Charger disconnected → Run Shortcut <strong>Life Manager Charging Off</strong></p>
  <p class="note">For each automation: turn <strong>off</strong> Ask Before Running and Notify When Run.</p>
</div>

<h2>Your backend URL</h2>
<div class="url-box">{backend_url}</div>
<p class="note">{network_note}</p>

<h2>Test it</h2>
<div class="step">
  <div class="step-num">Verify</div>
  <p>Run each imported shortcut once manually in Shortcuts, then check <a href="/api/ios-setup-status" style="color:#58a6ff">/api/ios-setup-status</a>. All checklist items should become configured.</p>
</div>
</body>
</html>"""


def _build_shortcut_bytes(kind: str = "gps") -> bytes:
    """Generate shortcut bytes for all iOS automation types."""
    import plistlib
    import uuid

    kind = (kind or "gps").lower()
    templates = {
        "gps": {"name": "Life Manager GPS", "activity": "ios_ping", "is_charging": None},
        "arrive": {"name": "Life Manager Arrive", "activity": "Arrive", "is_charging": "false"},
        "walking": {"name": "Life Manager Walking", "activity": "Walking", "is_charging": "false"},
        "charge_on": {"name": "Life Manager Charging On", "activity": "Stationary", "is_charging": "true"},
        "charge_off": {"name": "Life Manager Charging Off", "activity": "Stationary", "is_charging": "false"},
    }
    if kind not in templates:
        raise ValueError(f"Unknown shortcut kind: {kind}")

    cfg = templates[kind]
    backend_url = _get_backend_url() + "/api/ios-telemetry"
    loc_uuid = str(uuid.uuid4()).upper()
    post_uuid = str(uuid.uuid4()).upper()

    def _dict_item(key: str, value_obj: dict) -> dict:
        return {
            "WFItemType": 0,
            "WFKey": {"Value": {"string": key}, "WFSerializationType": "WFTextTokenString"},
            "WFValue": value_obj,
        }

    payload_items = [
        _dict_item(
            "location_label",
            {
                "Value": {
                    "attachmentsByRange": {"{0, 1}": {"Type": "ActionOutput", "OutputName": "MyLocation", "OutputUUID": loc_uuid}},
                    "string": "\ufffc",
                },
                "WFSerializationType": "WFTextTokenString",
            },
        ),
        _dict_item(
            "activity_type",
            {"Value": {"string": cfg["activity"]}, "WFSerializationType": "WFTextTokenString"},
        ),
    ]
    if cfg["is_charging"] is not None:
        payload_items.append(
            _dict_item(
                "is_charging",
                {"Value": {"string": cfg["is_charging"]}, "WFSerializationType": "WFTextTokenString"},
            )
        )

    shortcut = {
        "WFWorkflowMinimumClientVersion": 900,
        "WFWorkflowMinimumClientVersionString": "900",
        "WFWorkflowName": cfg["name"],
        "WFWorkflowTypes": [],
        "WFWorkflowIcon": {"WFWorkflowIconGlyphNumber": 59511, "WFWorkflowIconStartColor": 4275765759},
        "WFWorkflowActions": [
            {
                "WFWorkflowActionIdentifier": "is.workflow.actions.location",
                "WFWorkflowActionParameters": {"CustomOutputName": "MyLocation", "UUID": loc_uuid},
            },
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
            },
        ],
    }
    return plistlib.dumps(shortcut, fmt=plistlib.FMT_XML)


@app.get("/setup/save-to-icloud")
async def save_shortcut_to_icloud():
    """Save the shortcut to iCloud Drive and open Finder there."""
    import subprocess, os
    from fastapi.responses import HTMLResponse as HR
    icloud_path = os.path.expanduser("~/Library/Mobile Documents/com~apple~CloudDocs")
    if not os.path.isdir(icloud_path):
        return HR("<p style='font-family:sans-serif;color:#f85149'>iCloud Drive not found. Make sure iCloud Drive is enabled in System Settings → Apple ID → iCloud.</p>")
    dest = os.path.join(icloud_path, "LifeManager.shortcut")
    with open(dest, "wb") as f:
        f.write(_build_shortcut_bytes())
    subprocess.run(["open", icloud_path])
    return HR("""<html><head><meta charset='UTF-8'><style>
      body{font-family:sans-serif;background:#0d1117;color:#f0f6fc;display:flex;align-items:center;
           justify-content:center;min-height:100vh;margin:0;flex-direction:column;gap:1rem;}
      p{color:#8b949e;} a{color:#58a6ff;}
    </style></head><body>
    <h2 style='color:#3fb950'>✅ Saved to iCloud Drive!</h2>
    <p>Finder opened. On your iPhone: open <strong>Files → iCloud Drive → LifeManager.shortcut</strong></p>
    <a href='/setup/ios'>← Back to setup</a>
    </body></html>""")


@app.get("/setup/save-to-desktop")
async def save_shortcut_to_desktop():
    """Save the shortcut to the Mac Desktop and reveal it in Finder."""
    import subprocess, os
    from fastapi.responses import HTMLResponse as HR
    dest = os.path.expanduser("~/Desktop/LifeManager.shortcut")
    with open(dest, "wb") as f:
        f.write(_build_shortcut_bytes())
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
    filename = f"LifeManager-{kind}.shortcut"
    try:
        shortcut_bytes = _build_shortcut_bytes(kind)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid shortcut kind")
    return Response(
        content=shortcut_bytes,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _get_backend_url() -> str:
    """Return the public-facing backend URL (Railway HTTPS or local IP)."""
    railway_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN") or os.environ.get("RAILWAY_STATIC_URL")
    if railway_domain:
        domain = railway_domain.replace("https://", "").replace("http://", "").rstrip("/")
        return f"https://{domain}"
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return f"http://{local_ip}:8000"
    except Exception:
        return "http://localhost:8000"


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
