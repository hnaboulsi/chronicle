from sqlalchemy.orm import Session
from sqlalchemy import desc
from models import AgentState, ActivityLog, MacTelemetry, iOSTelemetry, HourlySummary
import llm_client
import calendar_sync
from datetime import datetime, timedelta

# Categories that go on the calendar automatically
PRODUCTIVE_CATEGORIES = {"studying", "working", "creative"}
DISTRACTED_CATEGORIES = {"entertainment", "social_media", "gaming"}

# Minimum session length to log to calendar (minutes)
MIN_SESSION_MINUTES = 10


def get_state(db: Session, key: str, default: str = "") -> str:
    state = db.query(AgentState).filter(AgentState.key == key).first()
    return state.value if state else default


def set_state(db: Session, key: str, value: str):
    state = db.query(AgentState).filter(AgentState.key == key).first()
    if state:
        state.value = value
    else:
        db.add(AgentState(key=key, value=value))
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
    """Store the user's self-reported activity and log it."""
    set_state(db, "user_self_report", reply)
    print(f"User self-reported: {reply}")


def get_recent_mac_logs(db: Session, limit: int = 20) -> list:
    logs = (
        db.query(ActivityLog)
        .filter(ActivityLog.device == "mac")
        .order_by(desc(ActivityLog.timestamp))
        .limit(limit)
        .all()
    )
    return [
        {
            "app_name": l.app_name,
            "window_title": l.window_title,
            "time": l.timestamp.strftime("%H:%M") if l.timestamp else "",
        }
        for l in reversed(logs)
    ]


def get_mac_logs_for_hour(db: Session, since: datetime) -> list:
    logs = (
        db.query(ActivityLog)
        .filter(ActivityLog.device == "mac", ActivityLog.timestamp >= since)
        .order_by(ActivityLog.timestamp)
        .all()
    )
    return [{"app_name": l.app_name, "window_title": l.window_title} for l in logs]


def _close_session_to_calendar(db: Session, new_category: str, now: datetime):
    """
    If a productive session was in progress, close it out and write to calendar.
    Called whenever the detected category changes.
    """
    session_cat = get_state(db, "session_category")
    session_start_str = get_state(db, "session_start")
    session_summary = get_state(db, "session_summary")

    if not session_cat or not session_start_str:
        return

    if session_cat == new_category:
        return  # Same session, no change

    # Session has ended — log it if it was long enough
    try:
        session_start = datetime.fromisoformat(session_start_str)
        duration_min = (now - session_start).total_seconds() / 60
        should_log = (
            duration_min >= MIN_SESSION_MINUTES
            and session_cat in PRODUCTIVE_CATEGORIES
        )
        if should_log:
            calendar_sync.create_session_event(session_cat, session_summary, session_start, now)
    except Exception as e:
        print(f"Calendar session close error: {e}")

    # Clear session state
    set_state(db, "session_category", "")
    set_state(db, "session_start", "")
    set_state(db, "session_summary", "")


def _maybe_start_session(db: Session, category: str, summary: str, now: datetime):
    """Start tracking a new productive session."""
    if category not in PRODUCTIVE_CATEGORIES:
        return
    current = get_state(db, "session_category")
    if current == category:
        # Ongoing session — update summary if better
        if summary:
            set_state(db, "session_summary", summary)
        return
    # New productive session
    set_state(db, "session_category", category)
    set_state(db, "session_start", now.isoformat())
    set_state(db, "session_summary", summary)
    print(f"Session started: {category} — {summary}")


async def _generate_and_store_hourly_summary(db: Session, now: datetime):
    """Background task: generate and persist an hourly summary."""
    hour_start = now - timedelta(hours=1)
    logs = get_mac_logs_for_hour(db, since=hour_start)
    if not logs:
        return

    hour_label = hour_start.strftime("%I:%M %p")
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

    # Heartbeat — lets dashboard detect if tracker is actually running
    set_state(db, "last_mac_ping", now.isoformat())

    # Rule 1 — Idle check (30 min idle → prompt)
    if data.idle_time_seconds > 60 * 30:
        if not get_state(db, "pending_prompt"):
            set_state(db, "pending_prompt", "Hey — you've been idle for 30+ minutes. Taking a break or got distracted?")
        return

    # Rule 2 — Context classification (every 30 min to conserve API quota)
    last_check_str = get_state(db, "last_vagueness_check")
    last_check = datetime.fromisoformat(last_check_str) if last_check_str else datetime.min

    if (now - last_check).total_seconds() > 60 * 15:
        set_state(db, "last_vagueness_check", now.isoformat())

        recent = get_recent_mac_logs(db, limit=20)
        user_self_report = get_state(db, "user_self_report")
        result = await llm_client.classify_activity_context(recent, user_self_report)
        new_category = result["category"]
        new_summary = result["summary"]

        # Close out previous session if category changed, start new one
        _close_session_to_calendar(db, new_category, now)
        _maybe_start_session(db, new_category, new_summary, now)

        set_state(db, "current_activity_category", new_category)
        set_state(db, "current_activity_summary", new_summary)
        print(f"Activity classified: {new_category} — {new_summary}")

        # Study mode enforcement: distracted while supposed to be studying → call out
        study_mode = get_state(db, "study_mode")
        if study_mode == "active" and new_category in DISTRACTED_CATEGORIES and not get_state(db, "pending_prompt"):
            prompt = await llm_client.generate_prompt(data.app_name, data.window_title)
            set_state(db, "pending_prompt", prompt)

        # Not studying and not productive → gentle call-out (dashboard will show it)
        elif new_category in DISTRACTED_CATEGORIES and not get_state(db, "pending_prompt"):
            set_state(db, "callout_category", new_category)
            set_state(db, "callout_summary", new_summary)
        else:
            set_state(db, "callout_category", "")
            set_state(db, "callout_summary", "")

    # Rule 3 — Hourly summary auto-trigger
    if background_tasks is not None:
        last_summary_str = get_state(db, "last_hourly_summary")
        last_summary = datetime.fromisoformat(last_summary_str) if last_summary_str else datetime.min
        if (now - last_summary).total_seconds() > 3600:
            set_state(db, "last_hourly_summary", now.isoformat())
            background_tasks.add_task(_generate_and_store_hourly_summary, db, now)

    # Rule 4 — Calendar setup (ensure calendar exists, run once)
    if not get_state(db, "calendar_initialized"):
        try:
            calendar_sync.ensure_life_manager_calendar()
            set_state(db, "calendar_initialized", "true")
        except Exception as e:
            print(f"Calendar init error: {e}")


async def process_ios_telemetry(data: iOSTelemetry, db: Session):
    now = datetime.utcnow()
    is_walking = bool(data.activity_type and "walk" in data.activity_type.lower())

    # Store steps if provided
    if data.steps_today is not None:
        set_state(db, "steps_today", str(data.steps_today))

    # Walking detection with calendar logging
    was_walking = get_state(db, "is_walking") == "true"
    if is_walking:
        if not was_walking:
            # Walk just started
            set_state(db, "walk_start", now.isoformat())
            set_state(db, "walk_from", data.location_label or "")
        set_state(db, "is_walking", "true")
        set_state(db, "walk_current_location", data.location_label or "")
    else:
        if was_walking:
            # Walk just ended — log to calendar
            walk_start_str = get_state(db, "walk_start")
            walk_from = get_state(db, "walk_from")
            walk_to = get_state(db, "walk_current_location") or data.location_label or ""
            if walk_start_str:
                try:
                    walk_start = datetime.fromisoformat(walk_start_str)
                    duration_min = (now - walk_start).total_seconds() / 60
                    if duration_min >= 3:  # Only log walks 3+ minutes
                        calendar_sync.create_walk_event(walk_from, walk_to, walk_start, now)
                except Exception as e:
                    print(f"Walk calendar error: {e}")
            set_state(db, "walk_start", "")
        set_state(db, "is_walking", "false")

    # Location visit tracking (for calendar)
    prev_location = get_state(db, "current_location")
    current_location = data.location_label or ""
    if current_location and current_location != prev_location:
        # Left previous location — log the visit
        arrival_str = get_state(db, "location_arrival")
        if prev_location and arrival_str:
            try:
                arrival_dt = datetime.fromisoformat(arrival_str)
                duration_min = (now - arrival_dt).total_seconds() / 60
                if duration_min >= 10:  # Only log visits 10+ minutes
                    calendar_sync.create_location_event(prev_location, arrival_dt, now)
            except Exception as e:
                print(f"Location calendar error: {e}")
        # Start tracking new location
        set_state(db, "current_location", current_location)
        set_state(db, "location_arrival", now.isoformat())

    # Study Mode
    if data.location_label and data.location_label.lower() in ["library", "class", "school", "campus"]:
        set_state(db, "study_mode", "active")
    else:
        if data.location_label:  # Only clear if we have a definitive location
            set_state(db, "study_mode", "inactive")

    # Sleep detection
    hour = now.hour
    local_hour = (hour - 8) % 24
    if local_hour >= 22 or local_hour <= 4:
        if data.is_charging and data.activity_type == "Stationary":
            set_state(db, "user_asleep", "true")
    else:
        set_state(db, "user_asleep", "false")
