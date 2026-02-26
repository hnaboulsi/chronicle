from fastapi import FastAPI, Depends, BackgroundTasks, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc
from database import engine, Base, get_db
import models
from models import ActivityLog, MacTelemetry, iOSTelemetry
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
    
    background_tasks.add_task(agent_logic.process_mac_telemetry, data, db)
    pending_prompt = agent_logic.get_pending_prompt(db)
    return {"status": "ok", "prompt": pending_prompt}


@app.post("/api/ios-telemetry")
async def receive_ios_telemetry(data: iOSTelemetry, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    log_entry = ActivityLog(
        device="ios",
        location_label=data.location_label,
        activity_type=data.activity_type
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

@app.post("/api/prompt-reply")
async def handle_prompt_reply(payload: Dict[str, Any], db: Session = Depends(get_db)):
    reply = payload.get("reply", "")
    agent_logic.clear_pending_prompt(db)
    agent_logic.update_context_with_reply(reply, db)
    return {"status": "accepted"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

