from sqlalchemy.orm import Session
from sqlalchemy import desc
from models import AgentState, ActivityLog, MacTelemetry, iOSTelemetry, HourlySummary
import llm_client
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


def get_recent_mac_logs(db: Session, limit: int = 10) -> list:
    """Returns last `limit` Mac activity logs as dicts for LLM context."""
    logs = (
        db.query(ActivityLog)
        .filter(ActivityLog.device == "mac")
        .order_by(desc(ActivityLog.timestamp))
        .limit(limit)
        .all()
    )
    return [{"app_name": l.app_name, "window_title": l.window_title} for l in reversed(logs)]


def get_mac_logs_for_hour(db: Session, since: datetime) -> list:
    """Returns all Mac logs from `since` until now, for hourly summary."""
    logs = (
        db.query(ActivityLog)
        .filter(ActivityLog.device == "mac", ActivityLog.timestamp >= since)
        .order_by(ActivityLog.timestamp)
        .all()
    )
    return [{"app_name": l.app_name, "window_title": l.window_title} for l in logs]


async def _generate_and_store_hourly_summary(db: Session, now: datetime):
    """Background task: generate and persist an hourly summary."""
    hour_start = now - timedelta(hours=1)
    logs = get_mac_logs_for_hour(db, since=hour_start)
    if not logs:
        return

    hour_label = hour_start.strftime("%I:%M %p UTC")
    result = await llm_client.generate_hourly_summary(logs, hour_label)

    summary = HourlySummary(
        hour_start=hour_start,
        summary_text=result["summary"],
        productivity_score=result.get("productivity_score"),
    )
    db.add(summary)
    db.commit()
    print(f"Hourly summary stored for {hour_label}")


async def process_mac_telemetry(data: MacTelemetry, db: Session, background_tasks=None):
    now = datetime.utcnow()

    # Rule 1 — Idle check (30 min)
    if data.idle_time_seconds > 60 * 30:
        if not get_state(db, "pending_prompt"):
            set_state(db, "pending_prompt", "Hey, are you writing on your iPad or did you get distracted?")
        return

    # Rule 2 — Context classification (every 30 min to conserve API quota)
    last_check_str = get_state(db, "last_vagueness_check")
    last_check = datetime.fromisoformat(last_check_str) if last_check_str else datetime.min

    if (now - last_check).total_seconds() > 60 * 30:
        set_state(db, "last_vagueness_check", now.isoformat())

        recent = get_recent_mac_logs(db, limit=10)
        result = await llm_client.classify_activity_context(recent)

        set_state(db, "current_activity_category", result["category"])
        set_state(db, "current_activity_summary", result["summary"])
        print(f"Activity classified: {result['category']} — {result['summary']}")

        # Study-location enforcement: at library but not studying → prompt
        study_mode = get_state(db, "study_mode")
        not_studying = result["category"] in ["entertainment", "social_media", "gaming"]
        if study_mode == "active" and not_studying and not get_state(db, "pending_prompt"):
            prompt = await llm_client.generate_prompt(data.app_name, data.window_title)
            set_state(db, "pending_prompt", prompt)

    # Rule 3 — Hourly summary auto-trigger
    if background_tasks is not None:
        last_summary_str = get_state(db, "last_hourly_summary")
        last_summary = datetime.fromisoformat(last_summary_str) if last_summary_str else datetime.min
        if (now - last_summary).total_seconds() > 3600:
            set_state(db, "last_hourly_summary", now.isoformat())
            background_tasks.add_task(_generate_and_store_hourly_summary, db, now)


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

    # Sleep Rule
    hour = datetime.utcnow().hour
    local_hour = (hour - 8) % 24
    if local_hour >= 22 or local_hour <= 4:
        if data.is_charging and data.activity_type == "Stationary":
            set_state(db, "user_asleep", "true")
            print("User is asleep. Should check calendar now.")
    else:
        set_state(db, "user_asleep", "false")
