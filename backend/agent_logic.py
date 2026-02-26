from sqlalchemy.orm import Session
from models import AgentState, MacTelemetry, iOSTelemetry
import llm_client
import asyncio
from datetime import datetime, timedelta

def get_state(db: Session, key: str, default: str = "") -> str:
    state = db.query(AgentState).filter(AgentState.key == key).first()
    if state:
        return state.value
    return default

def set_state(db: Session, key: str, value: str):
    state = db.query(AgentState).filter(AgentState.key == key).first()
    if state:
        state.value = value
    else:
        new_state = AgentState(key=key, value=value)
        db.add(new_state)
    db.commit()

def get_all_states(db: Session):
    states = db.query(AgentState).all()
    return {s.key: s.value for s in states}

def get_pending_prompt(db: Session) -> str:
    prompt = get_state(db, "pending_prompt")
    return prompt if prompt else None

def clear_pending_prompt(db: Session):
    set_state(db, "pending_prompt", "")

def update_context_with_reply(reply: str, db: Session):
    print(f"User replied: {reply}. Logging to daily context...")
    # In a full app, this would log to a context table or feed back to calendar

async def process_mac_telemetry(data: MacTelemetry, db: Session):
    # Check idle rule
    if data.idle_time_seconds > 60 * 30: # 30 mins
        # Has not moved doc in 30 mins
        if not get_state(db, "pending_prompt"):
            set_state(db, "pending_prompt", "Hey, are you writing on your iPad or did you get distracted?")
        return

    # Check "Active Voice" / Vagueness rule
    # Only check every 30 minutes to save compute. We simulate this by checking a timestamp.
    last_check_str = get_state(db, "last_vagueness_check")
    now = datetime.utcnow()
    last_check = datetime.fromisoformat(last_check_str) if last_check_str else datetime.min
    
    if (now - last_check).total_seconds() > 60 * 30: # 30 mins
        set_state(db, "last_vagueness_check", now.isoformat())
        
        is_vague = await llm_client.check_if_vague(data.app_name, data.window_title)
        if is_vague:
            prompt = await llm_client.generate_prompt(data.app_name, data.window_title)
            set_state(db, "pending_prompt", prompt)

async def process_ios_telemetry(data: iOSTelemetry, db: Session):
    is_walking = (data.activity_type and "walking" in data.activity_type.lower())
    
    # Motion & Location Rule
    if is_walking:
        if not get_state(db, "pending_prompt") and not get_state(db, "is_walking") == "true":
            set_state(db, "pending_prompt", "Where are you headed?")
        set_state(db, "is_walking", "true")
    else:
        set_state(db, "is_walking", "false")

    # Study Mode Rule
    if data.location_label and data.location_label.lower() in ["library", "class", "school"]:
        set_state(db, "study_mode", "active")
    else:
         set_state(db, "study_mode", "inactive")
        
    # Sleep Rule (basic simulation)
    # If stationary, charging, and time > 10PM... 
    hour = datetime.utcnow().hour
    # Convert UTC to simple local check (approx, assumes PT for demo)
    local_hour = (hour - 8) % 24
    if local_hour >= 22 or local_hour <= 4:
        # Assuming we check charging state here
        if data.is_charging and data.activity_type == "Stationary":
            set_state(db, "user_asleep", "true")
            # Triggers calendar alarm setup
            print("User is asleep. Should check calendar now.")
    else:
        set_state(db, "user_asleep", "false")
