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
frontend_path = os.path.join(os.path.dirname(__file__), "frontend")
os.makedirs(frontend_path, exist_ok=True)
app.mount("/dashboard", StaticFiles(directory=frontend_path, html=True), name="frontend")

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

@app.get("/api/logs")
async def get_logs(limit: int = 50, db: Session = Depends(get_db)):
    logs = db.query(ActivityLog).order_by(desc(ActivityLog.timestamp)).limit(limit).all()
    return logs

@app.post("/api/prompt-reply")
async def handle_prompt_reply(payload: Dict[str, Any], db: Session = Depends(get_db)):
    reply = payload.get("reply", "")
    agent_logic.clear_pending_prompt(db)
    agent_logic.update_context_with_reply(reply, db)
    return {"status": "accepted"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

