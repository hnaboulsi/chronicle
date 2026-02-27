from fastapi import FastAPI, Depends, BackgroundTasks, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc
from database import engine, Base, get_db
import models
from models import ActivityLog, HourlySummary, MacTelemetry, iOSTelemetry
import agent_logic
from typing import Dict, Any
import os

# Create tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Life-Manager Agent API")

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
    return agent_logic.get_all_states(db)

@app.get("/api/settings")
async def get_settings(db: Session = Depends(get_db)):
    polling_str = agent_logic.get_state(db, "polling_interval_seconds", "60")
    tracking_enabled_str = agent_logic.get_state(db, "tracking_enabled", "true")
    return {
        "polling_interval_seconds": int(polling_str),
        "tracking_enabled": tracking_enabled_str.lower() == "true"
    }

@app.post("/api/settings")
async def update_settings(payload: Dict[str, Any], db: Session = Depends(get_db)):
    if "polling_interval_seconds" in payload:
        agent_logic.set_state(db, "polling_interval_seconds", str(payload["polling_interval_seconds"]))
    if "tracking_enabled" in payload:
        agent_logic.set_state(db, "tracking_enabled", str(payload["tracking_enabled"]).lower())
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
  <p>Click below to download the shortcut file to your Mac.</p>
  <a class="action-btn" href="/setup/shortcut/download">Download LifeManager.shortcut →</a>
  <p class="note">Then right-click the downloaded file → <strong>Share → AirDrop</strong> → select your iPhone → tap Accept → Add Shortcut.</p>
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

<h2>Step 2 — Set up the silent automation</h2>
<div class="step">
  <div class="step-num">In the Shortcuts app on iPhone</div>
  <p>1. Tap the <strong>Automation</strong> tab → tap <strong>+</strong><br>
     2. Choose <strong>Time of Day</strong> → set interval to <strong>every 30 minutes</strong><br>
     3. Under "Do" → tap <strong>New Blank Automation</strong><br>
     4. Add action: <strong>Run Shortcut</strong> → select <strong>Life Manager GPS</strong><br>
     5. Toggle <strong>off</strong> "Ask Before Running" → tap "Don't Ask"<br>
     6. Toggle <strong>off</strong> "Notify When Run"</p>
  <p class="note">Done — it will run silently every 30 minutes. You'll never see it.</p>
</div>

<h2>Your backend URL</h2>
<div class="url-box">{backend_url}</div>
<p class="note">{network_note}</p>

<h2>Test it</h2>
<div class="step">
  <div class="step-num">Verify</div>
  <p>Open Shortcuts → find <strong>Life Manager GPS</strong> → tap play ▶. Then check the <a href="/" style="color:#58a6ff">dashboard</a> — the iPhone card should update within seconds.</p>
</div>
</body>
</html>"""


def _build_shortcut_bytes() -> bytes:
    """Generate the LifeManager.shortcut plist bytes with the backend URL embedded."""
    import plistlib, uuid

    backend_url = _get_backend_url() + "/api/ios-telemetry"
    loc_uuid = str(uuid.uuid4()).upper()
    city_uuid = str(uuid.uuid4()).upper()
    post_uuid = str(uuid.uuid4()).upper()

    shortcut = {
        "WFWorkflowMinimumClientVersion": 900,
        "WFWorkflowMinimumClientVersionString": "900",
        "WFWorkflowName": "Life Manager GPS",
        "WFWorkflowTypes": [],
        "WFWorkflowIcon": {"WFWorkflowIconGlyphNumber": 59511, "WFWorkflowIconStartColor": 4275765759},
        "WFWorkflowActions": [
            {"WFWorkflowActionIdentifier": "is.workflow.actions.location",
             "WFWorkflowActionParameters": {"CustomOutputName": "MyLocation", "UUID": loc_uuid}},
            {"WFWorkflowActionIdentifier": "is.workflow.actions.address",
             "WFWorkflowActionParameters": {
                 "WFAddressField": "City",
                 "WFInput": {"Value": {"Type": "ActionOutput", "OutputName": "MyLocation", "OutputUUID": loc_uuid},
                             "WFSerializationType": "WFTextTokenAttachment"},
                 "CustomOutputName": "CityName", "UUID": city_uuid}},
            {"WFWorkflowActionIdentifier": "is.workflow.actions.downloadurl",
             "WFWorkflowActionParameters": {
                 "WFURL": backend_url, "WFHTTPMethod": "POST",
                 "WFHTTPBodyType": "Json", "ShowHeaders": False, "UUID": post_uuid,
                 "WFRequestVariable": {"Value": {"WFDictionaryFieldValueItems": [
                     {"WFItemType": 0,
                      "WFKey": {"Value": {"string": "location_label"}, "WFSerializationType": "WFTextTokenString"},
                      "WFValue": {"Value": {"attachmentsByRange": {"{0, 1}": {"Type": "ActionOutput",
                                  "OutputName": "CityName", "OutputUUID": city_uuid}}, "string": "\ufffc"},
                                  "WFSerializationType": "WFTextTokenString"}},
                     {"WFItemType": 0,
                      "WFKey": {"Value": {"string": "activity_type"}, "WFSerializationType": "WFTextTokenString"},
                      "WFValue": {"Value": {"string": "ios_ping"}, "WFSerializationType": "WFTextTokenString"}},
                 ]}, "WFSerializationType": "WFDictionaryFieldValue"}}},
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
async def download_shortcut():
    from fastapi.responses import Response
    return Response(
        content=_build_shortcut_bytes(),
        media_type="application/octet-stream",
        headers={"Content-Disposition": 'attachment; filename="LifeManager.shortcut"'},
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

