from fastapi import FastAPI, Depends, BackgroundTasks, HTTPException
from sqlalchemy.orm import Session
from database import engine, Base, get_db
import models
from models import ActivityLog, MacTelemetry, iOSTelemetry
import agent_logic
from typing import Dict, Any

# Create tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Life-Manager Agent API")

@app.post("/api/mac-telemetry")
async def receive_mac_telemetry(data: MacTelemetry, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    # Log to database
    log_entry = ActivityLog(
        device="mac",
        app_name=data.app_name,
        window_title=data.window_title,
        is_idle=data.idle_time_seconds > 60 * 30 # Simple logic: idle if > 30 mins
    )
    db.add(log_entry)
    db.commit()
    
    # Process logic in background
    background_tasks.add_task(agent_logic.process_mac_telemetry, data, db)
    
    # Check if we have an immediate prompt to send back (active voice)
    # For now, return a generic status, we can use polling or websockets if needed, 
    # but a simple response payload works best for a simple client script.
    pending_prompt = agent_logic.get_pending_prompt(db)
    
    return {"status": "ok", "prompt": pending_prompt}


@app.post("/api/ios-telemetry")
async def receive_ios_telemetry(data: iOSTelemetry, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    # Log to database
    log_entry = ActivityLog(
        device="ios",
        location_label=data.location_label,
        activity_type=data.activity_type
    )
    db.add(log_entry)
    db.commit()
    
    # Process logic in background (e.g. Study Mode trigger)
    background_tasks.add_task(agent_logic.process_ios_telemetry, data, db)
    
    return {"status": "ok"}


@app.get("/api/state")
async def get_state(db: Session = Depends(get_db)):
    # Used by the Mac Client to know if Study Mode is active, etc.
    return agent_logic.get_all_states(db)

@app.post("/api/prompt-reply")
async def handle_prompt_reply(payload: Dict[str, Any], db: Session = Depends(get_db)):
    # Handle user's response to an "Active Voice" prompt
    reply = payload.get("reply", "")
    agent_logic.clear_pending_prompt(db)
    agent_logic.update_context_with_reply(reply, db)
    return {"status": "accepted"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
