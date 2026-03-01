import json
import logging
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import desc
from sqlalchemy.orm import Session

from models import AgentState, ActivityLog, CalendarEventJob, HourlySummary, LocationZone, MacHeartbeat, MacTelemetry, iOSTelemetry, iOSZoneEvent
import llm_client

log = logging.getLogger("vero")

PRODUCTIVE_CATEGORIES = {"studying", "working", "creative"}
DISTRACTED_CATEGORIES = {"entertainment", "social_media", "gaming"}
MIN_SESSION_MINUTES = 10

DEFAULTS = {
    "backend_mode": "railway_primary",
    "llm_mode": "balanced",
    "ai_provider": "auto",
    "hourly_summaries_enabled": "true",
    "classification_interval_seconds": "1800",  # 30-min default to conserve API budget
    "llm_daily_cap": "30",   # Gemini free tier is generous; 30 is a safe daily default
    "sleep_source": "iphone_only",
    "user_timezone": "America/Los_Angeles",
    "tracking_enabled": "true",
}

DEFAULT_ZONES = [
    {
        "slug": "anchor-house",
        "name": "Anchor House",
        "radius_meters": 90,
        "enabled": True,
        "zone_type": "home",
        "focus_mode": "",
        "sort_order": 10,
    },
    {
        "slug": "dwinelle-hall",
        "name": "Dwinelle Hall",
        "radius_meters": 75,
        "enabled": True,
        "zone_type": "lecture",
        "focus_mode": "Class",
        "sort_order": 20,
    },
    {
        "slug": "wheeler-hall",
        "name": "Wheeler Hall",
        "radius_meters": 75,
        "enabled": True,
        "zone_type": "lecture",
        "focus_mode": "Class",
        "sort_order": 30,
    },
    {
        "slug": "vlsb",
        "name": "VLSB",
        "radius_meters": 75,
        "enabled": True,
        "zone_type": "study",
        "focus_mode": "Deep Work",
        "sort_order": 40,
    },
    {
        "slug": "doe-moffitt",
        "name": "Doe/Moffitt Library",
        "radius_meters": 90,
        "enabled": False,
        "zone_type": "study",
        "focus_mode": "Deep Work",
        "sort_order": 50,
    },
    {
        "slug": "rsf",
        "name": "RSF",
        "radius_meters": 90,
        "enabled": False,
        "zone_type": "gym",
        "focus_mode": "",
        "sort_order": 60,
    },
]


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
    ensure_default_zones(db)
    os.environ["LIFE_MANAGER_AI_PROVIDER"] = get_state(db, "ai_provider", DEFAULTS["ai_provider"])


def ensure_default_zones(db: Session):
    # Only seed default zones on first run (empty table)
    if db.query(LocationZone).count() > 0:
        return
    for zone in DEFAULT_ZONES:
        db.add(LocationZone(**zone))
    db.commit()


def zone_to_dict(zone: LocationZone) -> dict:
    default_slugs = {z["slug"] for z in DEFAULT_ZONES}
    return {
        "id": zone.id,
        "slug": zone.slug,
        "name": zone.name,
        "radius_meters": zone.radius_meters,
        "enabled": bool(zone.enabled),
        "zone_type": zone.zone_type,
        "focus_mode": zone.focus_mode or "",
        "sort_order": zone.sort_order,
        "is_default": zone.slug in default_slugs,
        "created_at": zone.created_at.isoformat() if zone.created_at else "",
        "updated_at": zone.updated_at.isoformat() if zone.updated_at else "",
    }


def list_zones(db: Session) -> list[dict]:
    ensure_default_zones(db)
    zones = db.query(LocationZone).order_by(LocationZone.sort_order, LocationZone.id).all()
    return [zone_to_dict(z) for z in zones]


def get_zone(db: Session, slug: str) -> LocationZone | None:
    ensure_default_zones(db)
    return db.query(LocationZone).filter(LocationZone.slug == slug).first()


def upsert_zone(db: Session, payload: dict, zone_id: int | None = None) -> dict:
    ensure_default_zones(db)
    zone = None
    if zone_id is not None:
        zone = db.query(LocationZone).filter(LocationZone.id == zone_id).first()
    elif payload.get("slug"):
        zone = db.query(LocationZone).filter(LocationZone.slug == payload["slug"]).first()

    if zone is None:
        zone = LocationZone()
        db.add(zone)

    zone.slug = str(payload.get("slug") or zone.slug or "").strip()
    zone.name = str(payload.get("name") or zone.name or "").strip()
    if not zone.slug or not zone.name:
        raise ValueError("slug and name are required")
    zone.radius_meters = max(25, int(payload.get("radius_meters", zone.radius_meters or 75)))
    zone.enabled = bool(payload.get("enabled", zone.enabled if zone.enabled is not None else True))
    zone.zone_type = str(payload.get("zone_type", zone.zone_type or "custom")).strip() or "custom"
    zone.focus_mode = str(payload.get("focus_mode", zone.focus_mode or "")).strip()
    zone.sort_order = int(payload.get("sort_order", zone.sort_order or 0))
    db.commit()
    db.refresh(zone)
    return zone_to_dict(zone)


def clear_recent_logs(db: Session, minutes: int | None = None) -> int:
    """Delete activity logs from the last `minutes` minutes (or all today if minutes is None)."""
    if minutes is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        count = db.query(ActivityLog).filter(ActivityLog.timestamp >= cutoff).delete()
    else:
        today = datetime.now(timezone.utc).date()
        count = db.query(ActivityLog).filter(
            ActivityLog.timestamp >= datetime(today.year, today.month, today.day)
        ).delete()
    db.commit()
    return count


def delete_zone(db: Session, zone_id: int) -> bool:
    zone = db.query(LocationZone).filter(LocationZone.id == zone_id).first()
    if not zone:
        return False
    db.delete(zone)
    db.commit()
    return True


def _today_key(now: datetime) -> str:
    return now.strftime("%Y-%m-%d")


def _safe_int(value: str, default: int) -> int:
    try:
        return int(value)
    except Exception as e:
        log.debug("Failed to parse int %r: %s", value, e)
        return default


def _parse_iso_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception as e:
        log.debug("Failed to parse ISO datetime %r: %s", value, e)
        return None


def _age_seconds(value: str | None, now: datetime | None = None) -> int | None:
    dt = _parse_iso_dt(value)
    if dt is None:
        return None
    now = now or datetime.now(timezone.utc)
    return max(0, int((now - dt).total_seconds()))


def llm_usage_snapshot(db: Session, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    cap = _safe_int(get_state(db, "llm_daily_cap", DEFAULTS["llm_daily_cap"]), 30)
    today = _today_key(now)
    used_raw = get_state(db, f"llm_calls:{today}", "0")
    used = _safe_int(used_raw, 0)
    return {"daily_cap": cap, "daily_used": used, "daily_remaining": max(cap - used, 0)}


def can_use_llm(db: Session, now: datetime | None = None) -> bool:
    snap = llm_usage_snapshot(db, now)
    return snap["daily_used"] < snap["daily_cap"]


def register_llm_call(db: Session, now: datetime | None = None):
    now = now or datetime.now(timezone.utc)
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


def get_pending_prompt(db: Session) -> str | None:
    prompt = get_state(db, "pending_prompt")
    return prompt if prompt else None


def clear_pending_prompt(db: Session):
    set_state(db, "pending_prompt", "")


def update_context_with_reply(reply: str, db: Session):
    set_state(db, "user_self_report", reply)
    set_state(db, "last_user_checkin", datetime.now(timezone.utc).isoformat())
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


def get_mac_logs_for_hour(db: Session, since: datetime, until: datetime | None = None) -> list:
    q = db.query(ActivityLog).filter(ActivityLog.device == "mac", ActivityLog.timestamp >= since)
    if until is not None:
        q = q.filter(ActivityLog.timestamp < until)
    logs = q.order_by(ActivityLog.timestamp).all()
    return [{"app_name": l.app_name, "window_title": l.window_title} for l in logs]


def queue_calendar_job(
    db: Session,
    kind: str,
    title: str,
    start_dt: datetime,
    end_dt: datetime,
    notes: str = "",
    payload: dict | None = None,
) -> CalendarEventJob:
    job = CalendarEventJob(
        kind=kind,
        title=title,
        notes=notes,
        start_at=start_dt,
        end_at=end_dt,
        payload_json=json.dumps(payload or {}),
        status="pending",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    set_state(db, "last_calendar_job_at", datetime.now(timezone.utc).isoformat())
    return job


def _queue_session_event(db: Session, category: str, summary: str, start_dt: datetime, end_dt: datetime):
    duration_min = max(1, int((end_dt - start_dt).total_seconds() / 60))
    label_map = {
        "studying": "Study",
        "working": "Work",
        "creative": "Creative",
        "entertainment": "Entertainment",
        "social_media": "Social Media",
        "gaming": "Gaming",
        "break": "Break",
    }
    label = label_map.get(category, category.replace("_", " ").title())
    display = summary if summary else label
    title = f"{display} ({duration_min} min)"
    notes = f"Auto-logged by Vero | Category: {category}"
    queue_calendar_job(
        db,
        kind="session",
        title=title,
        start_dt=start_dt,
        end_dt=end_dt,
        notes=notes,
        payload={"category": category, "summary": summary},
    )


def _queue_walk_event(db: Session, location_from: str, location_to: str, start_dt: datetime, end_dt: datetime):
    duration_min = max(1, int((end_dt - start_dt).total_seconds() / 60))
    if location_from and location_to and location_from != location_to:
        title = f"Walk: {location_from} to {location_to} ({duration_min} min)"
    else:
        label = location_from or location_to or "Unknown"
        title = f"Walk near {label} ({duration_min} min)"
    queue_calendar_job(
        db,
        kind="walk",
        title=title,
        start_dt=start_dt,
        end_dt=end_dt,
        payload={"from": location_from, "to": location_to},
    )


def _queue_location_visit(db: Session, location_label: str, arrival_dt: datetime, departure_dt: datetime):
    duration_min = max(1, int((departure_dt - arrival_dt).total_seconds() / 60))
    title = f"At {location_label} ({duration_min} min)"
    queue_calendar_job(
        db,
        kind="location_visit",
        title=title,
        start_dt=arrival_dt,
        end_dt=departure_dt,
        payload={"location": location_label},
    )


def _close_session_to_calendar(db: Session, new_category: str, now: datetime):
    session_cat = get_state(db, "session_category")
    session_start_str = get_state(db, "session_start")
    session_summary = get_state(db, "session_summary")

    if not session_cat or not session_start_str:
        return
    if session_cat == new_category:
        return

    try:
        session_start = datetime.fromisoformat(session_start_str)
        duration_min = (now - session_start).total_seconds() / 60
        should_log = duration_min >= MIN_SESSION_MINUTES and session_cat in PRODUCTIVE_CATEGORIES
        if should_log:
            _queue_session_event(db, session_cat, session_summary, session_start, now)
    except Exception as exc:
        log.error("Calendar session queue error: %s", exc)

    set_state(db, "session_category", "")
    set_state(db, "session_start", "")
    set_state(db, "session_summary", "")


def _maybe_start_session(db: Session, category: str, summary: str, now: datetime):
    if category not in PRODUCTIVE_CATEGORIES:
        return
    current = get_state(db, "session_category")
    if current == category:
        if summary:
            set_state(db, "session_summary", summary)
        return
    set_state(db, "session_category", category)
    set_state(db, "session_start", now.isoformat())
    set_state(db, "session_summary", summary)
    log.info("Session started: %s - %s", category, summary)


async def _generate_and_store_hourly_summary(db: Session, now: datetime):
    # Snap to clean hour boundaries: cover the previous complete hour
    hour_end = now.replace(minute=0, second=0, microsecond=0)
    hour_start = hour_end - timedelta(hours=1)

    # Skip if we already have a summary for this hour
    existing = db.query(HourlySummary).filter(HourlySummary.hour_start == hour_start).first()
    if existing:
        return

    logs = get_mac_logs_for_hour(db, since=hour_start, until=hour_end)
    if not logs:
        return

    hour_label = f"{hour_start.strftime('%I:%M %p')} — {hour_end.strftime('%I:%M %p')}"
    result = await llm_client.generate_hourly_summary(logs, hour_label)

    summary = HourlySummary(
        hour_start=hour_start,
        summary_text=result["summary"],
        productivity_score=result.get("productivity_score"),
    )
    db.add(summary)
    db.commit()
    log.info("Hourly summary stored for %s", hour_label)


def _guess_activity(location: str, prev_location: str, now: datetime, db: Session) -> str:
    loc = location.lower()
    tz_name = get_state(db, "user_timezone", DEFAULTS["user_timezone"])
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        log.debug("Invalid timezone %r, falling back to %s", tz_name, DEFAULTS["user_timezone"])
        tz = ZoneInfo(DEFAULTS["user_timezone"])
    local_hour = now.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz).hour

    study_places = {"library", "vlsb", "evans", "moffitt", "doe", "soda", "cory", "class", "lecture", "campus"}
    food_places = {"student union", "crossroads", "cafe", "restaurant", "dining", "golden bear", "grab"}
    gym_places = {"gym", "rsf", "rec center", "fitness"}
    home_words = {"home", "apartment", "dorm", "residence", "anchor"}

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
    if 7 <= local_hour <= 9:
        return "Starting your morning"
    if 11 <= local_hour <= 13:
        return "Maybe grabbing lunch"
    if local_hour >= 22:
        return "Looks like you're heading home"
    if prev_location:
        return f"You came from {prev_location}"
    return "What are you up to?"


def _update_study_mode(db: Session, location_label: str, zone_type: str = ""):
    label = (location_label or "").lower()
    zone_type = (zone_type or "").lower()
    if zone_type in {"study", "lecture"} or any(word in label for word in ["library", "class", "school", "campus", "vlsb", "dwinelle", "wheeler", "doe", "moffitt"]):
        set_state(db, "study_mode", "active")
    elif location_label:
        set_state(db, "study_mode", "inactive")


def _maybe_generate_checkin(db: Session, current_location: str, prev_location: str, now: datetime):
    if not current_location:
        return
    if current_location in {"charging_trigger", "walking_trigger"}:
        return

    last_checkin_str = get_state(db, "last_user_checkin")
    needs_checkin = True
    if last_checkin_str:
        try:
            last_checkin = datetime.fromisoformat(last_checkin_str)
            if (now - last_checkin).total_seconds() < 900:
                needs_checkin = False
        except Exception as e:
            log.debug("Failed to parse last checkin time: %s", e)

    if needs_checkin and not get_state(db, "pending_checkin"):
        guess = _guess_activity(current_location, prev_location, now, db)
        if guess:
            checkin_msg = f"Looks like you're at {current_location}. {guess} - is that right?"
            set_state(db, "pending_checkin", checkin_msg)
            set_state(db, "checkin_guess", guess)
            log.info("Check-in generated: %s", checkin_msg)


def _close_current_location_visit(db: Session, now: datetime, explicit_location: str | None = None):
    prev_location = explicit_location or get_state(db, "current_location")
    arrival_str = get_state(db, "location_arrival")
    if prev_location and arrival_str:
        try:
            arrival_dt = datetime.fromisoformat(arrival_str)
            duration_min = (now - arrival_dt).total_seconds() / 60
            if duration_min >= 10:
                _queue_location_visit(db, prev_location, arrival_dt, now)
        except Exception as exc:
            log.error("Location calendar queue error: %s", exc)
    set_state(db, "current_location", "")
    set_state(db, "location_arrival", "")


def _start_location_visit(db: Session, location_label: str, now: datetime):
    set_state(db, "current_location", location_label)
    set_state(db, "location_arrival", now.isoformat())


def _handle_location_change(db: Session, current_location: str, now: datetime, zone_type: str = ""):
    prev_location = get_state(db, "current_location")
    if current_location and current_location != prev_location:
        if prev_location:
            _close_current_location_visit(db, now, explicit_location=prev_location)
        _start_location_visit(db, current_location, now)
        _maybe_generate_checkin(db, current_location, prev_location, now)
    _update_study_mode(db, current_location, zone_type=zone_type)


def _update_sleep_state(db: Session, now: datetime, activity_type: str, is_charging: bool | None):
    tz_name = get_state(db, "user_timezone", DEFAULTS["user_timezone"])
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        log.debug("Invalid timezone %r, falling back to %s", tz_name, DEFAULTS["user_timezone"])
        tz = ZoneInfo(DEFAULTS["user_timezone"])
    local_hour = now.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz).hour
    if local_hour >= 22 or local_hour <= 4:
        if is_charging and activity_type == "Stationary":
            set_state(db, "user_asleep", "true")
    else:
        set_state(db, "user_asleep", "false")


def compute_mac_status(states: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    heartbeat_age = _age_seconds(states.get("last_mac_heartbeat"), now)
    snapshot_age = _age_seconds(states.get("last_mac_ping"), now)
    tracking_enabled = str(states.get("tracking_enabled", "true")).lower() == "true"
    permissions_state = (states.get("last_mac_permissions_state") or "ok").lower()
    agent_state = (states.get("last_mac_agent_state") or "running").lower()
    is_idle = str(states.get("last_mac_idle", "false")).lower() == "true"

    if heartbeat_age is None or heartbeat_age > 150:
        status = "offline"
        reason = "No recent heartbeat from the Mac agent."
    elif not tracking_enabled or agent_state == "paused":
        status = "paused"
        reason = "The Mac agent is running, but tracking is paused."
    elif permissions_state not in {"ok", "granted"}:
        status = "degraded"
        reason = "The agent is alive, but macOS permissions are incomplete."
    elif is_idle:
        status = "online_idle"
        reason = "The agent is online and the Mac has been idle."
    else:
        status = "online"
        reason = "The agent is online and sending heartbeats."

    return {
        "mac_status": status,
        "mac_status_reason": reason,
        "mac_online": status != "offline",
        "last_mac_heartbeat_age_seconds": heartbeat_age,
        "last_mac_snapshot_age_seconds": snapshot_age,
    }


async def process_mac_heartbeat(data: MacHeartbeat, db: Session):
    now = datetime.now(timezone.utc)
    ensure_default_settings(db)
    set_state(db, "last_mac_heartbeat", now.isoformat())
    set_state(db, "last_mac_client_id", data.client_id or "")
    set_state(db, "last_mac_app_version", data.app_version or "")
    set_state(db, "last_mac_agent_state", data.agent_state or "running")
    set_state(db, "last_mac_permissions_state", data.permissions_state or "ok")
    set_state(db, "last_mac_error", data.last_error or "")
    if data.tracking_enabled is not None:
        set_state(db, "tracking_enabled", str(bool(data.tracking_enabled)).lower())


async def process_mac_telemetry(data: MacTelemetry, db: Session):
    now = datetime.now(timezone.utc)
    ensure_default_settings(db)

    prev_mac_ping_str = get_state(db, "last_mac_ping")
    set_state(db, "last_mac_ping", now.isoformat())
    set_state(db, "last_mac_idle", str(data.idle_time_seconds > 60 * 30).lower())

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
                    msg = f"Welcome back! You were at {location}. {guess} - what were you up to?"
                else:
                    msg = "Welcome back! What have you been up to?"
                set_state(db, "pending_checkin", msg)
                set_state(db, "checkin_guess", "")
                log.info("Mac return check-in: %s", msg)
        except Exception:
            pass

    if data.idle_time_seconds > 60 * 30:
        if not get_state(db, "pending_prompt"):
            set_state(db, "pending_prompt", "Hey - you've been idle for 30+ minutes. Taking a break or got distracted?")
        return

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

        _close_session_to_calendar(db, new_category, now)
        _maybe_start_session(db, new_category, new_summary, now)

        set_state(db, "current_activity_category", new_category)
        set_state(db, "current_activity_summary", new_summary)
        log.info("Activity classified: %s - %s", new_category, new_summary)

        study_mode = get_state(db, "study_mode")
        if study_mode == "active" and new_category in DISTRACTED_CATEGORIES and not get_state(db, "pending_prompt"):
            if can_use_llm(db, now):
                register_llm_call(db, now)
                prompt = await llm_client.generate_prompt(data.app_name, data.window_title)
            else:
                prompt = "You seem distracted. Is this still part of your intended task?"
            set_state(db, "pending_prompt", prompt)
        elif new_category in DISTRACTED_CATEGORIES and not get_state(db, "pending_prompt"):
            set_state(db, "callout_category", new_category)
            set_state(db, "callout_summary", new_summary)
        else:
            set_state(db, "callout_category", "")
            set_state(db, "callout_summary", "")

    last_summary_str = get_state(db, "last_hourly_summary")
    last_summary = datetime.fromisoformat(last_summary_str) if last_summary_str else datetime.min
    summaries_enabled = get_state(db, "hourly_summaries_enabled", DEFAULTS["hourly_summaries_enabled"]) == "true"
    if summaries_enabled and (now - last_summary).total_seconds() > 1800 and can_use_llm(db, now):
        set_state(db, "last_hourly_summary", now.isoformat())
        register_llm_call(db, now)
        await _generate_and_store_hourly_summary(db, now)


def _record_ios_event(db: Session, now: datetime):
    set_state(db, "last_ios_ping", now.isoformat())
    set_state(db, "last_ios_event", now.isoformat())
    set_state(db, "sleep_source", "iphone_only")
    set_state(db, "sleep_status_note", "Sleep detection uses iPhone automations.")


def _handle_ios_steps(db: Session, steps_today: int | None):
    if steps_today is not None:
        set_state(db, "steps_today", str(steps_today))


def _handle_walking_transition(db: Session, now: datetime, is_walking: bool, location_label: str):
    was_walking = get_state(db, "is_walking") == "true"
    if is_walking:
        if not was_walking:
            set_state(db, "walk_start", now.isoformat())
            set_state(db, "walk_from", location_label or get_state(db, "current_location"))
        set_state(db, "is_walking", "true")
        set_state(db, "walk_current_location", location_label or get_state(db, "current_location"))
        return

    if was_walking:
        walk_start_str = get_state(db, "walk_start")
        walk_from = get_state(db, "walk_from")
        walk_to = get_state(db, "walk_current_location") or location_label or get_state(db, "current_location")
        if walk_start_str:
            try:
                walk_start = datetime.fromisoformat(walk_start_str)
                duration_min = (now - walk_start).total_seconds() / 60
                if duration_min >= 3:
                    _queue_walk_event(db, walk_from, walk_to, walk_start, now)
            except Exception as exc:
                log.error("Walk calendar queue error: %s", exc)
        set_state(db, "walk_start", "")
    set_state(db, "is_walking", "false")


async def process_ios_telemetry(data: iOSTelemetry, db: Session):
    now = datetime.now(timezone.utc)
    ensure_default_settings(db)
    _record_ios_event(db, now)
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

    _handle_ios_steps(db, data.steps_today)
    is_walking = bool(activity_type and "walk" in activity_type_lower)
    _handle_walking_transition(db, now, is_walking, data.location_label or "")

    current_location = data.location_label or ""
    if current_location:
        _handle_location_change(db, current_location, now)

    _update_sleep_state(db, now, activity_type, data.is_charging)


async def process_ios_zone_event(data: iOSZoneEvent, db: Session):
    now = data.event_time or datetime.now(timezone.utc)
    ensure_default_settings(db)
    _record_ios_event(db, now)
    _handle_ios_steps(db, data.steps_today)

    zone = get_zone(db, data.zone_slug)
    zone_label = zone.name if zone else data.zone_slug.replace("-", " ").title()
    zone_type = zone.zone_type if zone else "custom"
    transition = (data.transition or "").strip().lower()
    if transition not in {"enter", "exit"}:
        raise ValueError("transition must be 'enter' or 'exit'")

    if transition == "enter":
        set_state(db, "seen_arrive_automation", "true")
        _handle_location_change(db, zone_label, now, zone_type=zone_type)
        set_state(db, "last_zone_enter", zone.slug if zone else data.zone_slug)

        if get_state(db, "commute_start") and zone_type != "home":
            commute_start = _parse_iso_dt(get_state(db, "commute_start"))
            commute_from = get_state(db, "commute_from")
            if commute_start:
                duration_min = max(1, int((now - commute_start).total_seconds() / 60))
                set_state(db, "last_commute_minutes", str(duration_min))
                set_state(db, "last_commute_route", f"{commute_from} -> {zone_label}")
            set_state(db, "commute_start", "")
            set_state(db, "commute_from", "")
        return

    set_state(db, "seen_leave_automation", "true")
    if zone_type == "home":
        set_state(db, "commute_start", now.isoformat())
        set_state(db, "commute_from", zone_label)
    if get_state(db, "current_location") == zone_label:
        _close_current_location_visit(db, now, explicit_location=zone_label)
    if zone_type == "home":
        set_state(db, "study_mode", "inactive")
