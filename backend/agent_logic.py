import logging
from zoneinfo import ZoneInfo
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from models import AgentState, ActivityLog, MacTelemetry, iOSTelemetry, HourlySummary
import llm_client
import calendar_sync
from datetime import datetime, timedelta

log = logging.getLogger("life_manager")

# Categories that go on the calendar automatically
PRODUCTIVE_CATEGORIES = {"studying", "working", "creative"}
DISTRACTED_CATEGORIES = {"entertainment", "social_media", "gaming"}

# Minimum session length to log to calendar (minutes)
MIN_SESSION_MINUTES = 10
DEFAULTS = {
    "backend_mode": "railway_primary",
    "llm_mode": "ultra_save",
    "hourly_summaries_enabled": "false",
    "classification_interval_seconds": "1800",
    "llm_daily_cap": "30",
    "sleep_source": "iphone_only",
    "user_timezone": "America/Los_Angeles",
}


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


def ensure_default_settings(db: Session):
    for key, value in DEFAULTS.items():
        if not get_state(db, key):
            set_state(db, key, value)


def _today_key(now: datetime) -> str:
    return now.strftime("%Y-%m-%d")


def _safe_int(value: str, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def llm_usage_snapshot(db: Session, now: datetime | None = None) -> dict:
    now = now or datetime.utcnow()
    cap = _safe_int(get_state(db, "llm_daily_cap", DEFAULTS["llm_daily_cap"]), 30)
    today = _today_key(now)
    used_raw = get_state(db, f"llm_calls:{today}", "0")
    used = _safe_int(used_raw, 0)
    return {"daily_cap": cap, "daily_used": used, "daily_remaining": max(cap - used, 0)}


def can_use_llm(db: Session, now: datetime | None = None) -> bool:
    snap = llm_usage_snapshot(db, now)
    return snap["daily_used"] < snap["daily_cap"]


def register_llm_call(db: Session, now: datetime | None = None):
    now = now or datetime.utcnow()
    today = _today_key(now)
    key = f"llm_calls:{today}"
    used = _safe_int(get_state(db, key, "0"), 0)
    set_state(db, key, str(used + 1))


def heuristic_classify_activity(recent_activities: list, idle_time_seconds: int = 0, recent_history: list = None) -> dict:
    if idle_time_seconds > 60 * 30:
        return {"category": "idle", "summary": "Away from keyboard"}
    if not recent_activities:
        return {"category": "unknown", "summary": "Not enough activity signal"}

    text = " ".join(
        f"{(a.get('app_name') or '').lower()} {(a.get('window_title') or '').lower()}"
        for a in recent_activities
    )
    # Enrich with Chrome history domains and titles for richer keyword matching
    if recent_history:
        history_text = " ".join(
            f"{(h.get('domain') or '').lower()} {(h.get('title') or '').lower()}"
            for h in recent_history
        )
        text = f"{text} {history_text}"
    rules = [
        (["instagram", "twitter", "x.com", "tiktok", "snapchat", "discord"], ("social_media", "On social platforms")),
        (["youtube", "netflix", "reddit", "spotify", "hulu"], ("entertainment", "Watching or browsing media")),
        (["steam", "epic", "game"], ("gaming", "Playing a game")),
        (["canvas", "gradescope", "homework", "lecture", "course", "quiz"], ("studying", "Working on school tasks")),
        (["figma", "photoshop", "premiere", "final cut", "design"], ("creative", "Doing creative work")),
        (["vscode", "pycharm", "cursor", "terminal", "github", "slack", "notion",
          "claude", "claude.ai", "anthropic", "gemini.google", "aistudio.google",
          "chatgpt", "openai", "copilot", "windsurf"], ("working", "Doing focused computer work")),
    ]
    for needles, result in rules:
        if any(n in text for n in needles):
            return {"category": result[0], "summary": result[1]}

    return {"category": "break", "summary": "General browsing or light activity"}


def get_pending_prompt(db: Session) -> str:
    prompt = get_state(db, "pending_prompt")
    return prompt if prompt else None


def clear_pending_prompt(db: Session):
    set_state(db, "pending_prompt", "")


def update_context_with_reply(reply: str, db: Session):
    """Store the user's self-reported activity and log it."""
    set_state(db, "user_self_report", reply)
    log.info("User self-reported: %s", reply)


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
        log.error("Calendar session close error: %s", e)

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
    log.info("Session started: %s — %s", category, summary)


async def _generate_and_store_hourly_summary(db: Session, now: datetime):
    """Background task: generate and persist a 30-min summary."""
    hour_start = now - timedelta(minutes=30)
    logs = get_mac_logs_for_hour(db, since=hour_start)
    if not logs:
        return

    hour_label = f"{hour_start.strftime('%I:%M')}–{now.strftime('%I:%M %p')}"
    result = await llm_client.generate_hourly_summary(logs, hour_label)

    summary = HourlySummary(
        hour_start=hour_start,
        summary_text=result["summary"],
        productivity_score=result.get("productivity_score"),
    )
    db.add(summary)
    db.commit()
    log.info("Hourly summary stored for %s", hour_label)


async def process_mac_telemetry(data: MacTelemetry, db: Session):
    now = datetime.utcnow()
    ensure_default_settings(db)

    # Heartbeat — lets dashboard detect if tracker is actually running
    prev_mac_ping_str = get_state(db, "last_mac_ping")
    set_state(db, "last_mac_ping", now.isoformat())

    # Check-in: if Mac was offline for 15+ min and user hasn't checked in, ask
    if prev_mac_ping_str and not get_state(db, "pending_checkin"):
        try:
            prev_ping = datetime.fromisoformat(prev_mac_ping_str)
            offline_seconds = (now - prev_ping).total_seconds()
            last_checkin_str = get_state(db, "last_user_checkin")
            checkin_stale = True
            if last_checkin_str:
                try:
                    last_ci = datetime.fromisoformat(last_checkin_str)
                    checkin_stale = (now - last_ci).total_seconds() > 1800
                except Exception:
                    pass
            if offline_seconds > 900 and checkin_stale:
                location = get_state(db, "current_location")
                if location:
                    guess = _guess_activity(location, "", now, db)
                    msg = f"Welcome back! You were at {location}. {guess} — what were you up to?"
                else:
                    msg = "Welcome back! What have you been up to?"
                set_state(db, "pending_checkin", msg)
                set_state(db, "checkin_guess", "")
                log.info("Mac return check-in: %s", msg)
        except Exception:
            pass

    # Rule 1 — Idle check (30 min idle → prompt)
    if data.idle_time_seconds > 60 * 30:
        if not get_state(db, "pending_prompt"):
            set_state(db, "pending_prompt", "Hey — you've been idle for 30+ minutes. Taking a break or got distracted?")
        return

    # Rule 2 — Context classification (every 30 min to conserve API quota)
    last_check_str = get_state(db, "last_vagueness_check")
    last_check = datetime.fromisoformat(last_check_str) if last_check_str else datetime.min

    classification_interval = _safe_int(
        get_state(db, "classification_interval_seconds", DEFAULTS["classification_interval_seconds"]),
        1800,
    )
    if (now - last_check).total_seconds() > classification_interval:
        set_state(db, "last_vagueness_check", now.isoformat())

        recent = get_recent_mac_logs(db, limit=20)
        user_self_report = get_state(db, "user_self_report")
        history = getattr(data, "recent_history", None)
        low_signal = len(set((r.get("app_name"), r.get("window_title")) for r in recent[-5:])) <= 2
        if low_signal and get_state(db, "llm_mode", DEFAULTS["llm_mode"]) == "ultra_save":
            result = heuristic_classify_activity(recent, idle_time_seconds=data.idle_time_seconds, recent_history=history)
        elif can_use_llm(db, now):
            register_llm_call(db, now)
            result = await llm_client.classify_activity_context(recent, user_self_report, recent_history=history)
        else:
            result = heuristic_classify_activity(recent, idle_time_seconds=data.idle_time_seconds, recent_history=history)
            result["summary"] = "AI budget reached; using local classification"
        new_category = result["category"]
        new_summary = result["summary"]

        # Close out previous session if category changed, start new one
        _close_session_to_calendar(db, new_category, now)
        _maybe_start_session(db, new_category, new_summary, now)

        set_state(db, "current_activity_category", new_category)
        set_state(db, "current_activity_summary", new_summary)
        log.info("Activity classified: %s — %s", new_category, new_summary)

        # Study mode enforcement: distracted while supposed to be studying → call out
        study_mode = get_state(db, "study_mode")
        if study_mode == "active" and new_category in DISTRACTED_CATEGORIES and not get_state(db, "pending_prompt"):
            if can_use_llm(db, now):
                register_llm_call(db, now)
                prompt = await llm_client.generate_prompt(data.app_name, data.window_title)
            else:
                prompt = "You seem distracted. Is this still part of your intended task?"
            set_state(db, "pending_prompt", prompt)

        # Not studying and not productive → gentle call-out (dashboard will show it)
        elif new_category in DISTRACTED_CATEGORIES and not get_state(db, "pending_prompt"):
            set_state(db, "callout_category", new_category)
            set_state(db, "callout_summary", new_summary)
        else:
            set_state(db, "callout_category", "")
            set_state(db, "callout_summary", "")

    # Rule 3 — Hourly summary auto-trigger (runs inline since we're already in a background task)
    last_summary_str = get_state(db, "last_hourly_summary")
    last_summary = datetime.fromisoformat(last_summary_str) if last_summary_str else datetime.min
    summaries_enabled = get_state(db, "hourly_summaries_enabled", DEFAULTS["hourly_summaries_enabled"]) == "true"
    if summaries_enabled and (now - last_summary).total_seconds() > 1800 and can_use_llm(db, now):
        set_state(db, "last_hourly_summary", now.isoformat())
        register_llm_call(db, now)
        await _generate_and_store_hourly_summary(db, now)

    # Rule 4 — Calendar setup (ensure calendar exists, run once)
    if not get_state(db, "calendar_initialized"):
        try:
            calendar_sync.ensure_life_manager_calendar()
            set_state(db, "calendar_initialized", "true")
        except Exception as e:
            log.error("Calendar init error: %s", e)


def _guess_activity(location: str, prev_location: str, now: datetime, db: Session) -> str:
    """Guess what the user is doing based on location, time, and history."""
    loc = location.lower()
    tz_name = get_state(db, "user_timezone", DEFAULTS["user_timezone"])
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("America/Los_Angeles")
    local_hour = now.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz).hour

    # Known location patterns
    study_places = {"library", "vlsb", "evans", "moffitt", "doe", "soda", "cory", "class", "lecture", "campus"}
    food_places = {"student union", "crossroads", "cafe", "restaurant", "dining", "golden bear", "grab"}
    gym_places = {"gym", "rsf", "rec center", "fitness"}
    home_words = {"home", "apartment", "dorm", "residence"}

    if any(p in loc for p in study_places):
        return "I think you're about to study"
    if any(p in loc for p in food_places):
        return "I think you stopped for food"
    if any(p in loc for p in gym_places):
        return "I think you're working out"
    if any(p in loc for p in home_words):
        if local_hour >= 20:
            return "I think you're winding down for the night"
        return "I think you're back home"

    # Time-based guessing
    if 7 <= local_hour <= 9:
        return "Starting your morning"
    if 11 <= local_hour <= 13:
        return "Maybe grabbing lunch"
    if local_hour >= 22:
        return "Looks like you're heading home"

    # Generic
    if prev_location:
        return f"You came from {prev_location}"
    return "What are you up to?"


async def process_ios_telemetry(data: iOSTelemetry, db: Session):
    now = datetime.utcnow()
    ensure_default_settings(db)
    set_state(db, "last_ios_ping", now.isoformat())
    set_state(db, "sleep_source", "iphone_only")
    set_state(db, "sleep_status_note", "Sleep detection uses iPhone automations.")
    activity_type = data.activity_type or ""
    activity_type_lower = activity_type.lower()
    if activity_type_lower == "ios_ping":
        set_state(db, "seen_periodic_automation", "true")
    if activity_type_lower in {"arrive", "arrival", "arrived"}:
        set_state(db, "seen_arrive_automation", "true")
    if "walk" in activity_type_lower:
        set_state(db, "seen_walking_automation", "true")
    if data.is_charging is not None:
        set_state(db, "seen_charging_automation", "true")
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
                    log.error("Walk calendar error: %s", e)
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
                log.error("Location calendar error: %s", e)
        # Start tracking new location
        set_state(db, "current_location", current_location)
        set_state(db, "location_arrival", now.isoformat())

    # Study Mode
    if data.location_label and data.location_label.lower() in ["library", "class", "school", "campus"]:
        set_state(db, "study_mode", "active")
    else:
        if data.location_label:  # Only clear if we have a definitive location
            set_state(db, "study_mode", "inactive")

    # Smart check-in: when location changes, guess what user is doing and ask
    if current_location and current_location != prev_location and current_location not in ("charging_trigger", "walking_trigger"):
        last_checkin_str = get_state(db, "last_user_checkin")
        needs_checkin = True
        if last_checkin_str:
            try:
                last_checkin = datetime.fromisoformat(last_checkin_str)
                # Don't ask if user checked in within last 15 minutes
                if (now - last_checkin).total_seconds() < 900:
                    needs_checkin = False
            except Exception:
                pass

        if needs_checkin and not get_state(db, "pending_checkin"):
            # Build a guess based on location and time
            guess = _guess_activity(current_location, prev_location, now, db)
            if guess:
                checkin_msg = f"Looks like you're at {current_location}. {guess} — is that right?"
                set_state(db, "pending_checkin", checkin_msg)
                set_state(db, "checkin_guess", guess)
                log.info("Check-in generated: %s", checkin_msg)

    # Sleep detection (timezone-aware)
    tz_name = get_state(db, "user_timezone", DEFAULTS["user_timezone"])
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("America/Los_Angeles")
    local_hour = now.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz).hour
    if local_hour >= 22 or local_hour <= 4:
        if data.is_charging and data.activity_type == "Stationary":
            set_state(db, "user_asleep", "true")
    else:
        set_state(db, "user_asleep", "false")
