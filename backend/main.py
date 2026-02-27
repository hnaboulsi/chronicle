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
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        local_ip = "localhost"

    backend_url = f"http://{local_ip}:8000"
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
  .download-btn {{ display: block; text-align: center; background: #58a6ff; color: #000; padding: 1rem; border-radius: 12px; font-weight: 600; text-decoration: none; margin: 1.5rem 0; font-size: 1.1rem; }}
  .note {{ font-size: 0.85rem; color: #8b949e; margin-top: 0.5rem; }}
  .badge {{ background: #3fb950; color: #000; font-size: 0.7rem; padding: 0.2rem 0.5rem; border-radius: 10px; font-weight: 600; }}
</style>
</head>
<body>
<h1>📱 iPhone Setup</h1>
<p>This page sets up silent iPhone tracking. Open it on your iPhone via Safari.</p>

<h2>Step 1 — Download the Shortcut</h2>
<div class="step">
  <div class="step-num">Action</div>
  <p>Tap the button below on your iPhone to download and install the Life Manager shortcut.</p>
  <a class="download-btn" href="/setup/shortcut/download">⬇ Install Life Manager Shortcut</a>
  <p class="note">Tap "Open in Shortcuts" then "Add Shortcut" when prompted.</p>
</div>

<h2>Step 2 — Create the Silent Automation</h2>
<div class="step">
  <div class="step-num">In Shortcuts app on iPhone</div>
  <p>1. Open <strong>Shortcuts</strong> → tap <strong>Automation</strong> tab<br>
     2. Tap <strong>+</strong> → <strong>Time of Day</strong><br>
     3. Set to repeat every <strong>30 minutes</strong> (or pick a time interval)<br>
     4. Under "Do", tap <strong>New Blank Automation</strong><br>
     5. Add action: <strong>Run Shortcut</strong> → select <strong>Life Manager GPS</strong><br>
     6. Toggle <strong>OFF</strong> "Ask Before Running" → tap "Don't Ask"<br>
     7. Toggle <strong>OFF</strong> "Notify When Run"</p>
  <p class="note">After this, it runs silently every 30 min — you'll never see it.</p>
</div>

<h2>Step 3 — Allow Location Access</h2>
<div class="step">
  <div class="step-num">One-time permission</div>
  <p>The first time it runs, iOS will ask for location access. Tap <strong>Always Allow</strong>.</p>
</div>

<h2>Your Backend URL</h2>
<div class="url-box">{backend_url}</div>
<p class="note">This is your Mac's local IP. Your iPhone must be on the same WiFi network.</p>

<h2>Test It</h2>
<div class="step">
  <div class="step-num">Verify it works</div>
  <p>After installing, open the Shortcuts app, find <strong>Life Manager GPS</strong>, and tap the play button. Then check the <a href="/" style="color:#58a6ff">dashboard</a> — your iPhone card should update within seconds.</p>
</div>
</body>
</html>"""


@app.get("/setup/shortcut/download")
async def download_shortcut():
    import plistlib, uuid
    from fastapi.responses import Response
    import socket

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        local_ip = "localhost"

    backend_url = f"http://{local_ip}:8000/api/ios-telemetry"

    loc_uuid = str(uuid.uuid4()).upper()
    city_uuid = str(uuid.uuid4()).upper()
    motion_uuid = str(uuid.uuid4()).upper()
    post_uuid = str(uuid.uuid4()).upper()

    shortcut = {
        "WFWorkflowMinimumClientVersion": 900,
        "WFWorkflowMinimumClientVersionString": "900",
        "WFWorkflowName": "Life Manager GPS",
        "WFWorkflowTypes": [],
        "WFWorkflowIcon": {
            "WFWorkflowIconGlyphNumber": 59511,
            "WFWorkflowIconStartColor": 4275765759,
        },
        "WFWorkflowActions": [
            # 1. Get current location
            {
                "WFWorkflowActionIdentifier": "is.workflow.actions.location",
                "WFWorkflowActionParameters": {
                    "CustomOutputName": "MyLocation",
                    "UUID": loc_uuid,
                },
            },
            # 2. Get city from location
            {
                "WFWorkflowActionIdentifier": "is.workflow.actions.address",
                "WFWorkflowActionParameters": {
                    "WFAddressField": "City",
                    "WFInput": {
                        "Value": {
                            "Type": "ActionOutput",
                            "OutputName": "MyLocation",
                            "OutputUUID": loc_uuid,
                        },
                        "WFSerializationType": "WFTextTokenAttachment",
                    },
                    "CustomOutputName": "CityName",
                    "UUID": city_uuid,
                },
            },
            # 3. Get motion activity
            {
                "WFWorkflowActionIdentifier": "is.workflow.actions.gettypedvalue",
                "WFWorkflowActionParameters": {
                    "WFInput": {
                        "Value": {
                            "Type": "ActionOutput",
                            "OutputName": "MyLocation",
                            "OutputUUID": loc_uuid,
                        },
                        "WFSerializationType": "WFTextTokenAttachment",
                    },
                    "CustomOutputName": "Latitude",
                    "UUID": motion_uuid,
                    "WFTypedValueType": "Latitude",
                },
            },
            # 4. POST to backend
            {
                "WFWorkflowActionIdentifier": "is.workflow.actions.downloadurl",
                "WFWorkflowActionParameters": {
                    "WFURL": backend_url,
                    "WFHTTPMethod": "POST",
                    "WFHTTPBodyType": "Json",
                    "ShowHeaders": False,
                    "UUID": post_uuid,
                    "WFRequestVariable": {
                        "Value": {
                            "WFDictionaryFieldValueItems": [
                                {
                                    "WFItemType": 0,
                                    "WFKey": {
                                        "Value": {"string": "location_label"},
                                        "WFSerializationType": "WFTextTokenString",
                                    },
                                    "WFValue": {
                                        "Value": {
                                            "attachmentsByRange": {
                                                "{0, 1}": {
                                                    "Type": "ActionOutput",
                                                    "OutputName": "CityName",
                                                    "OutputUUID": city_uuid,
                                                }
                                            },
                                            "string": "\ufffc",
                                        },
                                        "WFSerializationType": "WFTextTokenString",
                                    },
                                },
                                {
                                    "WFItemType": 0,
                                    "WFKey": {
                                        "Value": {"string": "activity_type"},
                                        "WFSerializationType": "WFTextTokenString",
                                    },
                                    "WFValue": {
                                        "Value": {"string": "ios_ping"},
                                        "WFSerializationType": "WFTextTokenString",
                                    },
                                },
                            ]
                        },
                        "WFSerializationType": "WFDictionaryFieldValue",
                    },
                },
            },
        ],
    }

    data = plistlib.dumps(shortcut, fmt=plistlib.FMT_XML)
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": 'attachment; filename="LifeManager.shortcut"'},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

