import json
import logging
import os
import re
from datetime import date as _date, datetime, timedelta, timezone
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx
from icalendar import Calendar as iCalCalendar

from sqlalchemy import desc
from sqlalchemy.orm import Session

from models import AgentState, ActivityLog, CalendarEventJob, HourlySummary, LocationZone, MacHeartbeat, MacPresence, MacTelemetry, iOSTelemetry, iOSZoneEvent, UserCalendarEvent
import llm_client

log = logging.getLogger("chronicle")

PRODUCTIVE_CATEGORIES = {"studying", "working", "creative"}
DISTRACTED_CATEGORIES = {"entertainment", "social_media", "gaming"}
MIN_SESSION_MINUTES = 10
VALID_PRESENCE_STATES = {"active", "idle", "away", "locked", "sleeping"}
AWAY_PRESENCE_STATES = {"away", "locked", "sleeping"}
VALID_SCREEN_STATES = {"visible", "locked", "sleeping", "unknown"}
BROWSER_APP_NAMES = {"Safari", "Google Chrome", "Brave Browser", "Arc"}
URL_PATTERN = re.compile(r"https?://[^\s)]+", re.IGNORECASE)
DOMAIN_PATTERN = re.compile(r"\b(?:[a-z0-9-]+\.)+[a-z]{2,}\b", re.IGNORECASE)

DEFAULTS = {
    "backend_mode": "railway_primary",
    "llm_mode": "balanced",
    "ai_provider": "mistral",
    "ai_fallback_providers": json.dumps(["gemini", "openai"]),
    "ai_routing_mode": "task_aware",
    "hourly_summaries_enabled": "true",
    "capture_interval_seconds": "300",
    "polling_interval_seconds": "300",
    "classification_interval_seconds": "300",
    "locked_capture_interval_seconds": "1800",
    "sleep_source": "iphone_only",
    "user_timezone": "America/Los_Angeles",
    "tracking_enabled": "true",
    "privacy_mode": "detailed",
    "calendar_sync_enabled": "true",
    "calendar_ical_url": "",
    "sleep_start_hour": "1",
    "sleep_end_hour": "9",
    "context_special_mode": "normal",
    "context_current_intent": "",
}

DEFAULT_ZONES: list[dict] = []
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
CHECKIN_TTL_SECONDS = 60 * 60
CHECKIN_COOLDOWN_SECONDS = 4 * 60 * 60
CHECKIN_IGNORE_LOCATIONS = {"", "unknown", "test", "charging_trigger", "walking_trigger"}


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


def _set_state_if_changed(db: Session, key: str, value: str):
    if get_state(db, key) != value:
        set_state(db, key, value)


def get_capture_interval_seconds(db: Session) -> int:
    capture = _safe_int(get_state(db, "capture_interval_seconds"), 0)
    polling = _safe_int(get_state(db, "polling_interval_seconds"), 0)
    if capture > 0 and polling > 0:
        raw = min(capture, polling)
    else:
        raw = capture or polling or _safe_int(DEFAULTS["capture_interval_seconds"], 300)
    return max(60, raw)


def get_effective_capture_interval_seconds(db: Session, screen_state: str = "visible") -> int:
    """Return capture interval, extended to 30 min when screen is locked or sleeping."""
    base = get_capture_interval_seconds(db)
    if screen_state in ("locked", "sleeping"):
        raw = get_state(db, "locked_capture_interval_seconds") or DEFAULTS["locked_capture_interval_seconds"]
        return max(base, _safe_int(raw, 1800))
    return base


def set_capture_interval_seconds(db: Session, seconds: int):
    normalized = max(60, int(seconds))
    derived_classification = max(300, normalized)
    _set_state_if_changed(db, "capture_interval_seconds", str(normalized))
    _set_state_if_changed(db, "polling_interval_seconds", str(normalized))
    _set_state_if_changed(db, "classification_interval_seconds", str(derived_classification))


def get_calendar_ical_urls(db: Session) -> list[str]:
    """Return list of iCal feed URLs. Reads new multi-URL key with fallback to legacy single-URL key."""
    multi_raw = get_state(db, "calendar_ical_urls", "")
    if multi_raw:
        try:
            urls = json.loads(multi_raw)
            if isinstance(urls, list):
                return [u for u in urls if isinstance(u, str) and u.strip()]
        except Exception:
            pass
    # Fallback: legacy single URL
    single = get_state(db, "calendar_ical_url", "").strip()
    return [single] if single else []


def set_calendar_ical_urls(db: Session, urls: list[str]):
    """Save list of iCal feed URLs."""
    cleaned = [u.strip() for u in urls if isinstance(u, str) and u.strip()]
    set_state(db, "calendar_ical_urls", json.dumps(cleaned))
    # Keep legacy key in sync with first URL for backward compat
    set_state(db, "calendar_ical_url", cleaned[0] if cleaned else "")


def ensure_default_settings(db: Session):
    for key, value in DEFAULTS.items():
        if key in {"capture_interval_seconds", "polling_interval_seconds", "classification_interval_seconds"}:
            continue
        if not get_state(db, key):
            set_state(db, key, value)
    # Migration: upgrade legacy "private" default to "detailed"
    if get_state(db, "privacy_mode") == "private":
        set_state(db, "privacy_mode", "detailed")
    set_capture_interval_seconds(db, get_capture_interval_seconds(db))
    ensure_default_zones(db)
    sync_ai_preferences_to_env(db)


def _normalize_ai_provider(value: str | None, default: str = "mistral") -> str:
    cleaned = (value or "").strip().lower()
    return cleaned if cleaned in {"auto", "gemini", "openai", "mistral"} else default


def _parse_fallback_providers(raw: str | None) -> list[str]:
    if not raw:
        raw_values = ["gemini", "openai"]
    else:
        try:
            parsed = json.loads(raw)
            raw_values = parsed if isinstance(parsed, list) else []
        except Exception:
            raw_values = [part.strip() for part in str(raw).split(",")]

    normalized: list[str] = []
    for item in raw_values:
        provider = _normalize_ai_provider(str(item), default="")
        if provider in {"gemini", "openai", "mistral"} and provider not in normalized:
            normalized.append(provider)
    return normalized


def get_ai_preferences(db: Session) -> dict:
    primary = _normalize_ai_provider(get_state(db, "ai_provider", DEFAULTS["ai_provider"]))
    fallbacks = _parse_fallback_providers(get_state(db, "ai_fallback_providers", DEFAULTS["ai_fallback_providers"]))
    fallbacks = [provider for provider in fallbacks if provider != primary]
    routing_mode = (get_state(db, "ai_routing_mode", DEFAULTS["ai_routing_mode"]) or DEFAULTS["ai_routing_mode"]).strip().lower()
    if routing_mode not in {"task_aware", "aggressive_fallback", "strict_primary"}:
        routing_mode = DEFAULTS["ai_routing_mode"]
    return {
        "primary_provider": primary,
        "fallback_providers": fallbacks,
        "routing_mode": routing_mode,
    }


def sync_ai_preferences_to_env(db: Session) -> dict:
    preferences = get_ai_preferences(db)
    os.environ["CHRONICLE_AI_PROVIDER"] = preferences["primary_provider"]
    os.environ["LIFE_MANAGER_AI_PROVIDER"] = preferences["primary_provider"]
    os.environ["CHRONICLE_AI_FALLBACK_PROVIDERS"] = json.dumps(preferences["fallback_providers"])
    os.environ["CHRONICLE_AI_ROUTING_MODE"] = preferences["routing_mode"]
    return preferences


def ensure_default_zones(db: Session):
    if not DEFAULT_ZONES:
        return
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


def normalize_zone_slug(slug: str) -> str:
    """Normalize to lowercase/kebab-case slug."""
    cleaned = re.sub(r"[^a-z0-9]+", "-", (slug or "").strip().lower())
    return cleaned.strip("-")


def _parse_bool(value, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y", "on"}:
        return True
    if text in {"false", "0", "no", "n", "off"}:
        return False
    return default


def get_zone(db: Session, slug: str) -> LocationZone | None:
    ensure_default_zones(db)
    return db.query(LocationZone).filter(LocationZone.slug == slug).first()


def upsert_zone(db: Session, payload: dict, zone_id: int | None = None) -> dict:
    ensure_default_zones(db)
    incoming_slug = normalize_zone_slug(str(payload.get("slug") or ""))
    incoming_name = str(payload.get("name") or "").strip()
    zone = None
    if zone_id is not None:
        zone = db.query(LocationZone).filter(LocationZone.id == zone_id).first()
    elif incoming_slug:
        zone = db.query(LocationZone).filter(LocationZone.slug == incoming_slug).first()

    if zone is None:
        zone = LocationZone()
        db.add(zone)

    if incoming_slug:
        zone.slug = incoming_slug
    elif incoming_name and not zone.slug:
        zone.slug = normalize_zone_slug(incoming_name)
    else:
        zone.slug = normalize_zone_slug(str(zone.slug or ""))

    zone.name = incoming_name or str(zone.name or "").strip()
    if not zone.slug or not zone.name:
        raise ValueError("slug and name are required")
    if not SLUG_RE.match(zone.slug):
        raise ValueError("slug must use lowercase letters, numbers, and hyphens only")

    db.flush()
    duplicate_query = db.query(LocationZone).filter(LocationZone.slug == zone.slug)
    if zone.id is not None:
        duplicate_query = duplicate_query.filter(LocationZone.id != zone.id)
    duplicate = duplicate_query.first()
    if duplicate:
        raise ValueError("slug already exists")

    zone.radius_meters = max(25, int(payload.get("radius_meters", zone.radius_meters or 75)))
    zone.enabled = _parse_bool(payload.get("enabled"), zone.enabled if zone.enabled is not None else True)
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
        today_start_utc, _ = user_day_bounds_utc(db, datetime.now(timezone.utc))
        count = db.query(ActivityLog).filter(ActivityLog.timestamp >= today_start_utc).delete()
    db.commit()
    return count


def delete_zone(db: Session, zone_id: int) -> bool:
    zone = db.query(LocationZone).filter(LocationZone.id == zone_id).first()
    if not zone:
        return False
    db.delete(zone)
    db.commit()
    return True


def resolve_user_timezone(db: Session) -> ZoneInfo:
    tz_name = get_state(db, "user_timezone", DEFAULTS["user_timezone"])
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo(DEFAULTS["user_timezone"])


def local_day_key(db: Session, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return now.astimezone(resolve_user_timezone(db)).strftime("%Y-%m-%d")


def user_day_bounds_utc(db: Session, now: datetime | None = None) -> tuple[datetime, datetime]:
    now = now or datetime.now(timezone.utc)
    tz = resolve_user_timezone(db)
    local_now = now.astimezone(tz)
    local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    local_end = local_start + timedelta(days=1)
    utc_start = local_start.astimezone(timezone.utc).replace(tzinfo=None)
    utc_end = local_end.astimezone(timezone.utc).replace(tzinfo=None)
    return utc_start, utc_end


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
        dt = datetime.fromisoformat(value)
        # Always return timezone-aware datetime to avoid subtraction errors
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception as e:
        log.debug("Failed to parse ISO datetime %r: %s", value, e)
        return None


def _age_seconds(value: str | None, now: datetime | None = None) -> int | None:
    dt = _parse_iso_dt(value)
    if dt is None:
        return None
    now = now or datetime.now(timezone.utc)
    return max(0, int((now - dt).total_seconds()))


def normalize_presence_state(value: str | None, idle_time_seconds: int = 0) -> str:
    cleaned = (value or "").strip().lower()
    if cleaned in VALID_PRESENCE_STATES:
        return cleaned
    if idle_time_seconds < 300:   # 5 min (was 2 min)
        return "active"
    if idle_time_seconds < 1800:  # 30 min (was 15 min)
        return "idle"
    return "away"


def apply_mac_presence_overrides(db: Session, data: MacTelemetry, presence_state: str) -> str:
    """Apply consecutive-log and window-change overrides to presence_state.

    Called synchronously in receive_mac_telemetry (before ActivityLog is written)
    so the stored presence_state is correct — not just in the background task.
    """
    # loginwindow = screen is locked (backend fallback when Mac lock notification missed)
    if (data.app_name or "").lower() == "loginwindow":
        return "locked"

    if presence_state in ("away", "idle"):
        # If the app or window changed since the previous log, the user was active
        prev_log = (
            db.query(ActivityLog)
            .filter(ActivityLog.device == "mac")
            .order_by(ActivityLog.timestamp.desc())
            .first()
        )
        if prev_log and (
            (prev_log.app_name or "") != (data.app_name or "")
            or (prev_log.window_title or "") != (data.window_title or "")
        ):
            return "active"

    # Mac client sent window-change elapsed time — if recent, user is active
    if data.seconds_since_window_change is not None and data.seconds_since_window_change < 300:
        return "active"

    return presence_state


def normalize_screen_state(value: str | None, presence_state: str) -> str:
    cleaned = (value or "").strip().lower()
    if cleaned in VALID_SCREEN_STATES:
        return cleaned
    if presence_state == "locked":
        return "locked"
    if presence_state == "sleeping":
        return "sleeping"
    return "visible"


def presence_summary(presence_state: str) -> str:
    return {
        "active": "Active on your Mac",
        "idle": "Briefly idle",
        "away": "Away from your Mac",
        "locked": "Mac locked",
        "sleeping": "Mac sleeping",
    }.get(presence_state, "Unknown presence")


def _extract_domain_hint(text: str) -> str:
    if not text:
        return ""
    match = URL_PATTERN.search(text)
    if match:
        host = urlparse(match.group(0)).netloc.lower().split("@")[-1].split(":")[0]
        return host[4:] if host.startswith("www.") else host

    for token in re.split(r"\s+", text):
        cleaned = token.strip("()[]{}<>|,;\"'")
        if DOMAIN_PATTERN.fullmatch(cleaned):
            lowered = cleaned.lower()
            return lowered[4:] if lowered.startswith("www.") else lowered
    return ""


def sanitize_window_title(app_name: str, window_title: str, privacy_mode: str, detailed_capture_enabled: bool = False) -> str:
    title = (window_title or "").strip()
    if not title:
        return ""
    if privacy_mode == "detailed" or detailed_capture_enabled:
        return title[:240]

    domain_hint = _extract_domain_hint(title)
    if domain_hint:
        return domain_hint
    if app_name in BROWSER_APP_NAMES:
        return "Browser activity"
    if title.lower() == (app_name or "").strip().lower():
        return app_name[:120]
    if app_name:
        return f"{app_name[:100]} activity"
    return "Activity"


def _presence_changed_at(states: dict, now: datetime) -> datetime:
    return _parse_iso_dt(states.get("last_presence_change_at")) or now


def llm_usage_snapshot(db: Session, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    today = local_day_key(db, now)
    used_raw = get_state(db, f"llm_calls:{today}", "0")
    used = _safe_int(used_raw, 0)
    return {"daily_cap": None, "daily_used": used, "daily_remaining": None}


def can_use_llm(db: Session, now: datetime | None = None, task_type: str = "default") -> bool:
    sync_ai_preferences_to_env(db)
    return llm_client.has_llm_provider(task_type=task_type)


def register_llm_call(db: Session, now: datetime | None = None):
    now = now or datetime.now(timezone.utc)
    today = local_day_key(db, now)
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
        (["vscode", "visual studio", "pycharm", "cursor", "intellij", "xcode", "android studio",
          "terminal", "iterm", "github", "gitlab", "linear", "jira", "notion", "confluence",
          "slack", "zoom", "vero", "lifemanager", "postman", "datagrip", "tableplus",
          "zed", "emacs", "vim", "arc",
          "claude", "claude.ai", "anthropic", "gemini.google", "aistudio.google",
          "chatgpt", "openai", "copilot", "windsurf",
          "code", "stackoverflow", "vercel", "railway", "docs.google", "drive.google",
          "sheets", "supabase", "planetscale", "render.com", "heroku", "aws", "azure", "gcp"], ("working", "Doing focused computer work")),
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


def set_user_self_report(db: Session, value: str):
    """Store user self-report with a timestamp so it can be expired after 6 hours."""
    set_state(db, "user_self_report", value)
    set_state(db, "user_self_report_at", datetime.now(timezone.utc).isoformat())


def get_user_self_report(db: Session) -> str:
    """Return user_self_report only if it was set within the last 6 hours."""
    value = get_state(db, "user_self_report", "")
    if not value:
        return ""
    set_at_str = get_state(db, "user_self_report_at", "")
    if not set_at_str:
        # No timestamp means this was set before expiry was added — treat as stale
        return ""
    try:
        set_at = datetime.fromisoformat(set_at_str)
        set_at = set_at if set_at.tzinfo else set_at.replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - set_at).total_seconds() > 6 * 3600:
            return ""
    except Exception:
        return ""
    return value


def get_global_chat_context(db: Session) -> str:
    """Return global_chat_context — persists until cleared."""
    return get_state(db, "global_chat_context", "")


def update_context_with_reply(reply: str, db: Session):
    set_user_self_report(db, reply)
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
            "is_idle": bool(l.is_idle),
            "presence_state": l.presence_state or "unknown",
        }
        for l in reversed(logs)
    ]


def get_mac_logs_for_hour(db: Session, since: datetime, until: datetime | None = None) -> list:
    q = db.query(ActivityLog).filter(ActivityLog.device == "mac", ActivityLog.timestamp >= since)
    if until is not None:
        q = q.filter(ActivityLog.timestamp < until)
    logs = q.order_by(ActivityLog.timestamp).all()
    return [
        {
            "app_name": l.app_name,
            "window_title": l.window_title,
            "activity_type": l.activity_type,
            "is_idle": bool(l.is_idle),
            "presence_state": l.presence_state or "unknown",
            "timestamp": l.timestamp.isoformat() if l.timestamp else None,
        }
        for l in logs
    ]


def get_manual_logs_for_hour(db: Session, since: datetime, until: datetime) -> list:
    logs = (
        db.query(ActivityLog)
        .filter(ActivityLog.device == "manual", ActivityLog.timestamp >= since, ActivityLog.timestamp < until)
        .order_by(ActivityLog.timestamp)
        .all()
    )
    return [
        {
            "label": l.app_name or "manual",
            "activity_type": l.activity_type or "manual",
            "note": l.window_title or "",
        }
        for l in logs
    ]


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
    title = f"{display} · {_fmt_duration(duration_min)}"
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


def _fmt_duration(minutes: int) -> str:
    m = max(1, minutes)
    if m < 60:
        return f"{m}m"
    h, rem = divmod(m, 60)
    return f"{h}h {rem}m" if rem else f"{h}h"


def _queue_walk_event(db: Session, location_from: str, location_to: str, start_dt: datetime, end_dt: datetime):
    duration_min = max(1, int((end_dt - start_dt).total_seconds() / 60))
    if location_from and location_to and location_from != location_to:
        title = f"Walk: {location_from} → {location_to} · {_fmt_duration(duration_min)}"
    else:
        label = location_from or location_to or "Unknown"
        title = f"Walk near {label} · {_fmt_duration(duration_min)}"
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
    title = f"{location_label} · {_fmt_duration(duration_min)}"
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


# Zone name keywords → activity category inference
_ZONE_NAME_KEYWORDS: list[tuple[list[str], str]] = [
    (["campus", "library", "school", "class", "lecture", "university", "college"], "studying"),
    (["gym", "park", "trail", "fitness", "workout", "rec"], "break"),
    (["office", "coworking", "work", "studio", "lab"], "working"),
]
_ZONE_TYPE_CATEGORY: dict[str, str] = {
    "study": "studying",
    "work": "working",
    "gym": "break",
}


def _infer_zone_category(zone_type: str, zone_name: str) -> tuple[str, str] | None:
    """Return (category, summary) inferred from zone type/name, or None if ambiguous."""
    name_lower = zone_name.lower()
    for keywords, cat in _ZONE_NAME_KEYWORDS:
        if any(kw in name_lower for kw in keywords):
            return (cat, f"At {zone_name}")
    cat = _ZONE_TYPE_CATEGORY.get(zone_type or "")
    if cat:
        return (cat, f"At {zone_name}")
    return None


_CATEGORY_SCORES = {
    "working": 7.0, "studying": 7.0, "creative": 6.5,
    "break": 5.0, "entertainment": 3.0, "social_media": 3.0,
    "gaming": 2.5, "idle": 4.0, "unknown": 5.0,
}


def _deterministic_hourly_summary(logs: list[dict], hour_label: str) -> dict:
    app_counts: dict[str, int] = {}
    for row in logs:
        app = (row.get("app_name") or "Unknown App").strip() or "Unknown App"
        app_counts[app] = app_counts.get(app, 0) + 1
    top_apps = sorted(app_counts.items(), key=lambda x: x[1], reverse=True)[:3]
    app_text = ", ".join(a for a, _ in top_apps) if top_apps else "mixed activity"

    heuristic = heuristic_classify_activity(logs) if logs else {"category": "unknown"}
    category = heuristic.get("category", "unknown")
    score = _CATEGORY_SCORES.get(category, 5.0) if top_apps else 4.0

    summary = f"Activity was mostly in {app_text}."
    return {"summary": summary, "productivity_score": score}


async def _sync_single_ical(db: Session, url: str, now_utc: datetime) -> tuple[int, str]:
    """Fetch and upsert one iCal feed. Returns (synced_count, error_string)."""
    window_start = (now_utc - timedelta(days=1)).replace(tzinfo=None)
    window_end = (now_utc + timedelta(days=7)).replace(tzinfo=None)

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
        raw = resp.content
    except Exception as exc:
        return 0, str(exc)

    try:
        cal = iCalCalendar.from_ical(raw)
    except Exception as exc:
        return 0, f"parse error: {exc}"

    feed_cal_name = str(cal.get("X-WR-CALNAME", "")).strip() or None
    synced = 0
    for component in cal.walk():
        if component.name != "VEVENT":
            continue
        try:
            dtstart = component.get("DTSTART")
            dtend = component.get("DTEND") or component.get("DTSTART")
            if dtstart is None:
                continue

            summary = str(component.get("SUMMARY", "Untitled")).strip()
            uid = str(component.get("UID", "")).strip()
            cal_name = feed_cal_name or str(component.get("X-WR-CALNAME", "")).strip() or None
            notes = str(component.get("DESCRIPTION", "")).strip() or None
            location_val = str(component.get("LOCATION", "")).strip() or None

            s = dtstart.dt
            e = dtend.dt if dtend else s

            if isinstance(s, _date) and not isinstance(s, datetime):
                s = datetime(s.year, s.month, s.day, 0, 0, tzinfo=timezone.utc)
            if isinstance(e, _date) and not isinstance(e, datetime):
                # iCal all-day end date is exclusive next day — use start of next day
                import datetime as _dt_mod
                e_d = _date(e.year, e.month, e.day) + _dt_mod.timedelta(days=1)
                e = datetime(e_d.year, e_d.month, e_d.day, 0, 0, tzinfo=timezone.utc)

            if s.tzinfo:
                s = s.astimezone(timezone.utc).replace(tzinfo=None)
            if e.tzinfo:
                e = e.astimezone(timezone.utc).replace(tzinfo=None)

            if e < window_start or s > window_end:
                continue

            if uid:
                existing = db.query(UserCalendarEvent).filter(UserCalendarEvent.event_uid == uid).first()
                if existing:
                    existing.title = summary
                    existing.start_at = s
                    existing.end_at = e
                    existing.calendar_name = cal_name
                    existing.notes = notes[:500] if notes else None
                    existing.location = location_val[:200] if location_val else None
                    synced += 1
                    continue

            db.add(UserCalendarEvent(
                event_uid=uid or None,
                title=summary,
                start_at=s,
                end_at=e,
                calendar_name=cal_name,
                notes=notes[:500] if notes else None,
                location=location_val[:200] if location_val else None,
            ))
            synced += 1
        except Exception:
            continue

    db.commit()
    return synced, ""


async def sync_ical_calendar(db: Session) -> dict:
    """Fetch all configured iCal feed URLs and upsert events into user_calendar_events."""
    urls = get_calendar_ical_urls(db)
    if not urls:
        return {"synced": 0, "error": "no_url"}

    now_utc = datetime.now(timezone.utc)
    total_synced = 0
    errors: list[str] = []

    for url in urls:
        count, err = await _sync_single_ical(db, url, now_utc)
        total_synced += count
        if err:
            errors.append(err)

    # Prune events older than 14 days
    cutoff = (now_utc - timedelta(days=14)).replace(tzinfo=None)
    db.query(UserCalendarEvent).filter(UserCalendarEvent.end_at < cutoff).delete()
    db.commit()

    error_str = "; ".join(errors) if errors else ""
    if error_str:
        set_state(db, "calendar_sync_error", error_str[:300])
    else:
        set_state(db, "calendar_sync_error", "")
    set_state(db, "calendar_last_sync", now_utc.isoformat())
    log.info("iCal sync complete: %d events upserted from %d feed(s)", total_synced, len(urls))
    return {"synced": total_synced, "error": error_str}


def get_calendar_events_for_window(db: Session, since: datetime, until: datetime) -> list[dict]:
    """Return UserCalendarEvents that overlap with [since, until]."""
    events = db.query(UserCalendarEvent).filter(
        UserCalendarEvent.start_at < until,
        UserCalendarEvent.end_at > since,
    ).order_by(UserCalendarEvent.start_at).all()
    return [
        {
            "title": e.title,
            "start_at": e.start_at.isoformat(),
            "end_at": e.end_at.isoformat(),
            "calendar_name": e.calendar_name or "",
        }
        for e in events
    ]


async def _generate_and_store_hourly_summary(db: Session, now: datetime, force_current: bool = False):
    tz = resolve_user_timezone(db)
    local_now = now.astimezone(tz)
    if force_current:
        # Generate for the current partial hour (start of hour to now)
        local_hour_start = local_now.replace(minute=0, second=0, microsecond=0)
        local_hour_end = local_now
    else:
        # Generate for the just-completed previous hour
        local_hour_end = local_now.replace(minute=0, second=0, microsecond=0)
        local_hour_start = local_hour_end - timedelta(hours=1)
    hour_start = local_hour_start.astimezone(timezone.utc).replace(tzinfo=None)
    hour_end = local_hour_end.astimezone(timezone.utc).replace(tzinfo=None)

    existing = db.query(HourlySummary).filter(HourlySummary.hour_start == hour_start).first()

    logs = get_mac_logs_for_hour(db, since=hour_start, until=hour_end)
    if not logs:
        fallback_text = "No Mac activity recorded this hour."
        if existing:
            if existing.summary_text != fallback_text:
                existing.summary_text = fallback_text
                existing.productivity_score = None
                existing.summary_source = "deterministic"
                db.commit()
        else:
            db.add(HourlySummary(
                hour_start=hour_start,
                summary_text=fallback_text,
                productivity_score=None,
                summary_source="deterministic",
            ))
            db.commit()
        return

    if force_current:
        hour_label = f"{local_hour_start.strftime('%I:%M %p')} — {local_now.strftime('%I:%M %p')} (partial hour)"
    else:
        hour_label = f"{local_hour_start.strftime('%I:%M %p')} — {local_hour_end.strftime('%I:%M %p')}"

    # Skip LLM during confirmed sleep or within sleep window (save battery/quota)
    _is_asleep = get_state(db, "likely_asleep", "false").lower() == "true"
    _sh_start = _safe_int(get_state(db, "sleep_start_hour", DEFAULTS["sleep_start_hour"]), 1)
    _sh_end = _safe_int(get_state(db, "sleep_end_hour", DEFAULTS["sleep_end_hour"]), 9)
    _hour_now = local_now.hour
    _in_sleep_window = (
        (_hour_now >= _sh_start or _hour_now < _sh_end) if _sh_start > _sh_end
        else (_sh_start <= _hour_now < _sh_end)
    )
    if _is_asleep or _in_sleep_window:
        sleep_text = "Likely sleeping — no activity recorded."
        if existing:
            pass  # don't overwrite existing real summary
        else:
            db.add(HourlySummary(
                hour_start=hour_start,
                summary_text=sleep_text,
                productivity_score=None,
                summary_source="sleep",
            ))
            db.commit()
        return

    fallback = _deterministic_hourly_summary(logs, hour_label)
    result = fallback
    source = "deterministic"
    confidence = 0.35
    fallback_used = True

    if can_use_llm(db, now, task_type="hourly_summary"):
        try:
            app_cache = json.loads(get_state(db, "app_category_cache") or "{}")
            global_context = get_global_chat_context(db)
            calendar_events = get_calendar_events_for_window(db, hour_start, hour_end)
            upcoming_events = get_calendar_events_for_window(db, hour_end, hour_end + timedelta(hours=2))
            manual_logs = get_manual_logs_for_hour(db, hour_start, hour_end)

            # Idle metrics
            total = len(logs)
            idle_count = sum(1 for l in logs if l.get("is_idle") or l.get("presence_state") in ("away", "locked", "sleeping"))
            idle_pct = round(idle_count / total * 100) if total else 0
            active_pct = 100 - idle_pct

            # Previous hour summary score + text for continuity
            prev_hour_start = (hour_start - timedelta(hours=1))
            prev_summary = db.query(HourlySummary).filter(HourlySummary.hour_start == prev_hour_start).first()
            prev_score = getattr(prev_summary, "productivity_score", None) if prev_summary else None
            prev_summary_text = (getattr(prev_summary, "summary_text", None) or "") if prev_summary else ""

            # Location context with freshness check
            _loc = get_state(db, "current_location", "")
            _loc_arrival_str = get_state(db, "location_arrival", "")
            _loc_age_note = ""
            if _loc and _loc_arrival_str:
                try:
                    _arrival_dt = datetime.fromisoformat(_loc_arrival_str)
                    _arrival_dt = _arrival_dt if _arrival_dt.tzinfo else _arrival_dt.replace(tzinfo=timezone.utc)
                    _loc_age_mins = int((now - _arrival_dt).total_seconds() / 60)
                    if _loc_age_mins > 120:
                        _loc_age_note = f"arrived {_loc_age_mins // 60}h ago"
                    elif _loc_age_mins > 5:
                        _loc_age_note = f"arrived {_loc_age_mins}m ago"
                except Exception:
                    pass
            _zone_type = get_state(db, f"zone_type:{_loc.lower().replace(' ', '_')}", "") if _loc else ""
            _zone_notes = _zone_type
            if _loc_age_note:
                _zone_notes = f"{_zone_type}, {_loc_age_note}" if _zone_type else _loc_age_note
            # Adjacent zone proximity warning (iPhone GPS can confuse neighboring geofences)
            _ADJACENT_ZONES: dict[str, str] = {"anchor": "campus", "campus": "anchor"}
            _loc_key = _loc.lower().replace(" ", "_") if _loc else ""
            _adjacent = _ADJACENT_ZONES.get(_loc_key, "")
            if _adjacent:
                _zone_notes = (_zone_notes + f"; GPS note: adjacent to '{_adjacent}' zone — may be misidentified").lstrip("; ")

            # iOS context (most recent entry in window)
            ios_entry = (
                db.query(ActivityLog)
                .filter(ActivityLog.device == "ios", ActivityLog.timestamp >= hour_start, ActivityLog.timestamp < hour_end)
                .order_by(ActivityLog.timestamp.desc())
                .first()
            )
            ios_context = {}
            if ios_entry:
                ios_context = {
                    "location": ios_entry.location_label,
                    "steps_today": ios_entry.steps_today,
                    "activity_type": ios_entry.activity_type,
                }

            # User intent context
            intent = get_state(db, "context_current_intent", "")

            register_llm_call(db, now)
            llm_result = await llm_client.generate_hourly_summary(
                logs, hour_label, app_cache,
                global_context=global_context,
                calendar_events=calendar_events,
                upcoming_events=upcoming_events,
                manual_logs=manual_logs,
                idle_pct=idle_pct,
                active_pct=active_pct,
                prev_score=prev_score,
                prev_summary_text=prev_summary_text,
                ios_context=ios_context,
                hour_of_day=local_hour_start.hour,
                day_of_week=local_hour_start.strftime("%A"),
                intent=intent,
                location=_loc,
                zone_notes=_zone_notes,
            )
            if llm_result and llm_result.get("summary"):
                result = llm_result
                source = "llm"
                confidence = 0.75
                fallback_used = False
        except Exception as exc:
            log.warning("Hourly summary LLM failed, using deterministic fallback: %s", exc)

    if existing:
        # Only skip overwrite when this is a user-triggered partial (force_current=True) and
        # we'd be downgrading an LLM summary to a weaker deterministic one.
        # At end-of-hour (force_current=False), always overwrite — full data beats partial.
        if force_current and source == "deterministic" and (getattr(existing, "summary_source", "llm") == "llm"):
            return
        existing.summary_text = result["summary"]
        existing.productivity_score = result.get("productivity_score")
        if hasattr(existing, "summary_source"):
            existing.summary_source = source
        if hasattr(existing, "confidence"):
            existing.confidence = confidence
        if hasattr(existing, "fallback_used"):
            existing.fallback_used = fallback_used
    else:
        summary = HourlySummary(
            hour_start=hour_start,
            summary_text=result["summary"],
            productivity_score=result.get("productivity_score"),
        )
        if hasattr(summary, "summary_source"):
            summary.summary_source = source
        if hasattr(summary, "confidence"):
            summary.confidence = confidence
        if hasattr(summary, "fallback_used"):
            summary.fallback_used = fallback_used
        db.add(summary)
    db.commit()
    log.info("Hourly summary stored for %s (%s)", hour_label, source)


def _maybe_office_hours_nudge(db: Session, now: datetime, current_category: str):
    """If office hours start within 30 min and user is distracted, set a callout nudge."""
    UNPRODUCTIVE = {"entertainment", "social_media", "distracted", "idle", "unknown"}
    if current_category not in UNPRODUCTIVE:
        return
    # Only nudge once per office hours event (track last nudge time)
    last_nudge_str = get_state(db, "last_oh_nudge_at", "")
    if last_nudge_str:
        try:
            from dateutil.parser import parse as _parse_oh
            last_nudge = _parse_oh(last_nudge_str)
            if last_nudge.tzinfo is None:
                last_nudge = last_nudge.replace(tzinfo=timezone.utc)
            if (now.astimezone(timezone.utc) - last_nudge.astimezone(timezone.utc)).total_seconds() < 1800:
                return  # Already nudged in last 30 min
        except Exception:
            pass

    window_end = (now + timedelta(minutes=30)).replace(tzinfo=None)
    now_naive = now.replace(tzinfo=None)
    # Look for upcoming office hours events
    upcoming_oh = (
        db.query(UserCalendarEvent)
        .filter(
            UserCalendarEvent.start_at > now_naive,
            UserCalendarEvent.start_at <= window_end,
        )
        .all()
    )
    for ev in upcoming_oh:
        title_lower = ev.title.lower()
        if any(kw in title_lower for kw in ("office hour", " oh ", "ta hour", "instructor hour")):
            mins_until = int((ev.start_at - now_naive).total_seconds() / 60)
            nudge = f"📚 {ev.title} starts in {mins_until} min — consider attending while you have time."
            set_state(db, "callout_summary", nudge)
            set_state(db, "callout_category", "office_hours_nudge")
            set_state(db, "last_oh_nudge_at", now.isoformat())
            log.info("Office hours nudge set: %s", ev.title)
            return


def _guess_activity(location: str, prev_location: str, now: datetime, db: Session) -> str:
    loc = location.lower()
    tz_name = get_state(db, "user_timezone", DEFAULTS["user_timezone"])
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        log.debug("Invalid timezone %r, falling back to %s", tz_name, DEFAULTS["user_timezone"])
        tz = ZoneInfo(DEFAULTS["user_timezone"])
    local_hour = now.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz).hour

    study_places = {"library", "class", "lecture", "campus", "school", "university", "college"}
    food_places = {"student union", "cafe", "restaurant", "dining", "cafeteria", "canteen", "grab"}
    gym_places = {"gym", "rec center", "fitness", "pool", "sports"}
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
    if zone_type in {"study", "lecture"} or any(word in label for word in ["library", "class", "school", "campus", "university", "college"]):
        set_state(db, "study_mode", "active")
    elif location_label:
        set_state(db, "study_mode", "inactive")


def _location_context_key(location: str) -> str:
    return normalize_zone_slug(location or "unknown") or "unknown"


def _is_checkin_ignored_location(location: str) -> bool:
    normalized = normalize_zone_slug(location or "")
    return normalized in CHECKIN_IGNORE_LOCATIONS


def _set_pending_checkin(db: Session, message: str, now: datetime, context_key: str, guess: str = ""):
    created = now.isoformat()
    expires = (now + timedelta(seconds=CHECKIN_TTL_SECONDS)).isoformat()
    set_state(db, "pending_checkin", message)
    set_state(db, "checkin_guess", guess)
    set_state(db, "pending_checkin_created_at", created)
    set_state(db, "pending_checkin_expires_at", expires)
    set_state(db, "pending_checkin_context_key", context_key)


def clear_pending_checkin(db: Session):
    set_state(db, "pending_checkin", "")
    set_state(db, "checkin_guess", "")
    set_state(db, "pending_checkin_created_at", "")
    set_state(db, "pending_checkin_expires_at", "")
    set_state(db, "pending_checkin_context_key", "")
    set_state(db, "pending_checkin_event_title", "")
    set_state(db, "pending_checkin_event_location", "")


def _checkin_is_active(db: Session, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    checkin = get_state(db, "pending_checkin")
    if not checkin:
        return False
    expires_at = _parse_iso_dt(get_state(db, "pending_checkin_expires_at"))
    if expires_at and now >= expires_at:
        clear_pending_checkin(db)
        return False
    return True


def get_checkin_payload(db: Session, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    if not _checkin_is_active(db, now):
        return {"checkin": None}
    created_at = _parse_iso_dt(get_state(db, "pending_checkin_created_at"))
    expires_at = _parse_iso_dt(get_state(db, "pending_checkin_expires_at"))
    age_seconds = int((now - created_at).total_seconds()) if created_at else None
    return {
        "checkin": get_state(db, "pending_checkin"),
        "guess": get_state(db, "checkin_guess"),
        "created_at": created_at.isoformat() if created_at else "",
        "expires_at": expires_at.isoformat() if expires_at else "",
        "age_seconds": age_seconds,
        "can_snooze": True,
        "can_dismiss": True,
        "event_title": get_state(db, "pending_checkin_event_title") or None,
        "event_location": get_state(db, "pending_checkin_event_location") or None,
    }


async def _maybe_generate_checkin(db: Session, current_location: str, prev_location: str, now: datetime):
    if not current_location or _is_checkin_ignored_location(current_location):
        return
    # Don't ping user during confirmed sleep or within sleep window
    if get_state(db, "likely_asleep", "false").lower() == "true":
        return
    tz_ci = resolve_user_timezone(db)
    local_h = now.astimezone(tz_ci).hour
    _s_start = _safe_int(get_state(db, "sleep_start_hour", DEFAULTS["sleep_start_hour"]), 1)
    _s_end = _safe_int(get_state(db, "sleep_end_hour", DEFAULTS["sleep_end_hour"]), 9)
    _in_sleep = (local_h >= _s_start or local_h < _s_end) if _s_start > _s_end else (_s_start <= local_h < _s_end)
    if _in_sleep:
        return
    if _checkin_is_active(db, now):
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

    context_key = _location_context_key(current_location)
    cooldown_key = f"checkin_cooldown_until:{context_key}"
    cooldown_until = _parse_iso_dt(get_state(db, cooldown_key))
    if cooldown_until and now < cooldown_until:
        needs_checkin = False

    if needs_checkin:
        guess = _guess_activity(current_location, prev_location, now, db)
        if can_use_llm(db, now, task_type="checkin"):
            global_context = get_global_chat_context(db)
            zone_type = get_state(db, f"zone_type:{_location_context_key(current_location)}", "")
            current_intent = get_state(db, "context_current_intent", "")
            special_mode = get_state(db, "context_special_mode", "normal")
            tz_ci = resolve_user_timezone(db)
            local_now_ci = now.astimezone(tz_ci)
            time_label_ci = local_now_ci.strftime("%A %-I:%M %p")
            # Upcoming events in the next 90 minutes
            upcoming_ci = get_calendar_events_for_window(db, now, now + timedelta(minutes=90))
            upcoming_ci_str = ""
            if upcoming_ci:
                ev_strs = []
                for ev in upcoming_ci[:2]:
                    start_dt = datetime.fromisoformat(ev["start_at"]).replace(tzinfo=timezone.utc).astimezone(tz_ci)
                    mins_away = int((start_dt.replace(tzinfo=None) - local_now_ci.replace(tzinfo=None)).total_seconds() / 60)
                    label = f"in {mins_away}m" if mins_away > 0 else "now"
                    ev_strs.append(f"{ev['title']} ({label})")
                upcoming_ci_str = f"\nUpcoming: {', '.join(ev_strs)}"

            prompt = (
                f"Time: {time_label_ci}\n"
                f"User just arrived at: {current_location} (zone type: {zone_type or 'unknown'}).\n"
                f"Previous location: {prev_location or 'unknown'}.\n"
                + (f'Active intent: "{current_intent}"\n' if current_intent else "")
                + (f"Mode: {special_mode}\n" if special_mode and special_mode != "normal" else "")
                + (f"User context: {global_context}\n" if global_context else "")
                + upcoming_ci_str
                + "\nWrite ONE short check-in question (under 10 words) asking what they're working on. "
                "Be specific if context hints at a project or upcoming deadline. "
                "Do NOT start with 'Hey' or 'Hi'. No filler."
            )
            try:
                register_llm_call(db, now)
                ai_msg = await llm_client.ask_llm(prompt, task_type="checkin")
                checkin_msg = ai_msg.strip() if ai_msg and ai_msg.strip() else f"At {current_location} — what are you working on?"
            except Exception:
                checkin_msg = f"At {current_location} — what are you working on?"
        elif guess and "what are you up to" not in guess.lower():
            checkin_msg = f"At {current_location} — {guess.rstrip('.')}?"
        else:
            checkin_msg = f"At {current_location} — what are you working on?"
        _set_pending_checkin(db, checkin_msg, now, context_key, guess or "")
        log.info("Check-in generated: %s", checkin_msg)


def _is_checkin_stale(db: Session, now: datetime) -> bool:
    last_checkin = _parse_iso_dt(get_state(db, "last_user_checkin"))
    if not last_checkin:
        return True
    return (now - last_checkin).total_seconds() > 1800


# ---------------------------------------------------------------------------
# Calendar event attendance tracking
# ---------------------------------------------------------------------------

def _attendance_key(title: str, location: str) -> str:
    """Stable slug for event+location pair."""
    raw = f"{title.lower().strip()}|{location.lower().strip()}"
    return "event_attendance:" + re.sub(r"[^a-z0-9|]", "_", raw)[:80]


def record_event_attendance(db: Session, title: str, location: str, attended: bool) -> None:
    key = _attendance_key(title, location)
    history = json.loads(get_state(db, key, "[]"))
    history.append(attended)
    set_state(db, key, json.dumps(history[-10:]))  # keep last 10


def get_attendance_summary(db: Session, title: str, location: str) -> str:
    """Return human-readable attendance pattern, e.g. 'usually goes (4/5)'."""
    key = _attendance_key(title, location)
    history = json.loads(get_state(db, key, "[]"))
    if not history:
        return "no history"
    attended = sum(1 for x in history if x)
    total = len(history)
    if attended / total >= 0.7:
        return f"usually goes ({attended}/{total})"
    elif attended / total <= 0.3:
        return f"usually skips ({attended}/{total})"
    return f"mixed ({attended}/{total})"


def _location_near_zone(event_location: str, current_zone: str) -> bool:
    """True if event location string suggests the user is already near it."""
    if not event_location or not current_zone:
        return False
    loc = event_location.lower()
    zone = current_zone.lower()
    if zone in loc or loc in zone:
        return True
    synonyms = [{"home", "house"}, {"office", "work", "studio"}]
    for group in synonyms:
        if any(w in loc for w in group) and any(w in zone for w in group):
            return True
    return False


async def _maybe_checkin_for_upcoming_events(db: Session) -> None:
    """Fire a check-in prompt for calendar events with locations starting in 15–45 min."""
    now_utc = datetime.now(timezone.utc)
    if _checkin_is_active(db, now_utc):
        return  # existing check-in already pending

    now_naive = now_utc.replace(tzinfo=None)
    window_start = now_naive + timedelta(minutes=15)
    window_end = now_naive + timedelta(minutes=45)

    events = (
        db.query(UserCalendarEvent)
        .filter(
            UserCalendarEvent.start_at >= window_start,
            UserCalendarEvent.start_at <= window_end,
            UserCalendarEvent.location != None,
            UserCalendarEvent.calendar_name != "Vero",
        )
        .order_by(UserCalendarEvent.start_at)
        .all()
    )

    for ev in events:
        dedup_key = f"calendar_event_checkin_fired:{ev.id}:{now_naive.date()}"
        if get_state(db, dedup_key):
            continue  # already fired for this event today

        attendance = get_attendance_summary(db, ev.title, ev.location)
        current_zone = get_state(db, "current_location", "")
        mins_away = int((ev.start_at - now_naive).total_seconds() / 60)

        if _location_near_zone(ev.location, current_zone):
            zone_hint = f"You're near {ev.location}. "
        else:
            zone_hint = ""

        history_hint = f" (you {attendance})" if attendance != "no history" else ""
        msg = (
            f"{zone_hint}{ev.title} at {ev.location} starts in {mins_away} min{history_hint}. Are you going?"
        )

        _set_pending_checkin(db, msg, now_utc, f"cal_event:{ev.id}")
        set_state(db, "pending_checkin_event_title", ev.title)
        set_state(db, "pending_checkin_event_location", ev.location)
        set_state(db, dedup_key, now_utc.isoformat())
        log.info("Calendar event check-in generated: %s", msg)
        break  # one prompt at a time


def _set_resume_checkin(db: Session, now: datetime):
    if get_state(db, "pending_checkin"):
        return

    location = get_state(db, "current_location")
    if location:
        guess = _guess_activity(location, "", now, db)
        if guess:
            msg = f"Back at {location} — {guess.rstrip('.')}?"
        else:
            msg = f"Back at {location} — what are you working on?"
    else:
        msg = "Welcome back. What are you working on next?"

    set_state(db, "pending_checkin", msg)
    set_state(db, "checkin_guess", "")
    log.info("Mac return check-in: %s", msg)


def _record_presence_state(
    db: Session,
    presence_state: str,
    screen_state: str,
    now: datetime,
    idle_time_seconds: int,
):
    states = get_all_states(db)
    previous_presence = normalize_presence_state(states.get("presence_state"), idle_time_seconds)
    previous_changed_at = _presence_changed_at(states, now)
    changed = previous_presence != presence_state or (states.get("screen_state") or "visible") != screen_state

    if changed:
        set_state(db, "last_presence_change_at", now.isoformat())
        if previous_presence in AWAY_PRESENCE_STATES and presence_state == "active":
            away_seconds = max(0, int((now - previous_changed_at).total_seconds()))
            if away_seconds >= 900 and _is_checkin_stale(db, now):
                _set_resume_checkin(db, now)

    set_state(db, "presence_state", presence_state)
    set_state(db, "screen_state", screen_state)
    set_state(db, "last_mac_presence", now.isoformat())
    set_state(db, "last_mac_idle", str(presence_state != "active").lower())

    if presence_state in AWAY_PRESENCE_STATES:
        set_state(db, "callout_category", "")
        set_state(db, "callout_summary", "")
        set_state(db, "pending_prompt", "")


def _close_current_location_visit(db: Session, now: datetime, explicit_location: str | None = None):
    prev_location = explicit_location or get_state(db, "current_location")
    # Strip "Outside " prefix — the visit title should name the place, not the departure state
    if prev_location and prev_location.startswith("Outside "):
        prev_location = prev_location[len("Outside "):]
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


async def _handle_location_change(db: Session, current_location: str, now: datetime, zone_type: str = ""):
    prev_location = get_state(db, "current_location")
    if current_location and current_location != prev_location:
        if prev_location:
            _close_current_location_visit(db, now, explicit_location=prev_location)
        _start_location_visit(db, current_location, now)
        await _maybe_generate_checkin(db, current_location, prev_location, now)
    _update_study_mode(db, current_location, zone_type=zone_type)


def _set_sleep_state(db: Session, asleep: bool, confidence: float, reason: str):
    set_state(db, "likely_asleep", "true" if asleep else "false")
    set_state(db, "user_asleep", "true" if asleep else "false")
    set_state(db, "likely_asleep_confidence", f"{min(confidence, 0.99):.2f}")
    set_state(db, "likely_asleep_reason", reason)
    set_state(db, "sleep_status_note", reason)


def _update_sleep_state(db: Session, now: datetime, activity_type: str, is_charging: bool | None):
    # Rule 1: explicit user intent → definitely awake
    current_intent = get_state(db, "context_current_intent", "").strip()
    if current_intent:
        _set_sleep_state(db, False, 0.00, f"Awake — intent set: {current_intent[:60]}")
        return

    # Resolve Mac ping age once
    mac_age_seconds = 9999.0
    last_mac_ping_str = get_state(db, "last_mac_ping")
    if last_mac_ping_str:
        try:
            from dateutil.parser import parse as _parse_ping
            last_ping = _parse_ping(last_mac_ping_str)
            if last_ping.tzinfo is None:
                last_ping = last_ping.replace(tzinfo=timezone.utc)
            mac_age_seconds = (now.astimezone(timezone.utc) - last_ping.astimezone(timezone.utc)).total_seconds()
        except Exception:
            pass

    # Rule 2: Mac active in last 10 min → definitely awake
    if mac_age_seconds < 600:
        _set_sleep_state(db, False, 0.00, "Awake — Mac active")
        return

    # Rule 3: Mac screen sleeping (lid closed) → definitely sleeping
    mac_screen_state = get_state(db, "screen_state", "visible")
    if mac_screen_state == "sleeping":
        _set_sleep_state(db, True, 0.95, "Asleep — laptop lid closed")
        return

    # Rule 4: Mac has been silent for 60+ min → sleeping (no activity for a full hour)
    if mac_age_seconds >= 3600:
        _set_sleep_state(db, True, 0.90, f"Asleep — Mac quiet for {int(mac_age_seconds // 60)} min")
        return

    # Rule 5: Mac silent 20+ min — weigh supporting signals
    if mac_age_seconds < 1200:
        # Mac too recent to infer sleep
        _set_sleep_state(db, False, 0.10, "Awake — Mac recent")
        return

    tz = resolve_user_timezone(db)
    local_hour = now.astimezone(tz).hour
    sleep_start = _safe_int(get_state(db, "sleep_start_hour", DEFAULTS["sleep_start_hour"]), 1) % 24
    sleep_end = _safe_int(get_state(db, "sleep_end_hour", DEFAULTS["sleep_end_hour"]), 9) % 24
    in_sleep_window = (
        (local_hour >= sleep_start or local_hour < sleep_end)
        if sleep_start > sleep_end
        else (sleep_start <= local_hour < sleep_end)
    )

    # Base: Mac has been quiet 20+ min
    confidence = 0.35
    reasons: list[str] = [f"mac quiet {int(mac_age_seconds // 60)} min"]

    if mac_screen_state == "locked":
        confidence += 0.20
        reasons.append("mac locked")
    if in_sleep_window:
        # Weight sleep window more heavily — time of day is a strong prior
        confidence += 0.35
        reasons.append(f"sleep window ({sleep_start:02d}:00-{sleep_end:02d}:00)")
    if is_charging:
        confidence += 0.10
        reasons.append("charging")
    if (activity_type or "").lower() == "stationary":
        confidence += 0.10
        reasons.append("stationary")

    # Lower threshold during sleep window since time-of-day is reliable
    threshold = 0.55 if in_sleep_window else 0.65
    likely_asleep = confidence >= threshold
    note = ("Likely asleep" if likely_asleep else "Likely awake") + f" ({', '.join(reasons)})"
    _set_sleep_state(db, likely_asleep, confidence, note)


def compute_mac_status(states: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    heartbeat_age = _age_seconds(states.get("last_mac_heartbeat"), now)
    capture_age = _age_seconds(states.get("last_capture_at") or states.get("last_mac_ping"), now)
    tracking_enabled = str(states.get("tracking_enabled", "true")).lower() == "true"
    permissions_state = (states.get("last_mac_permissions_state") or "ok").lower()
    agent_state = (states.get("last_mac_agent_state") or "running").lower()
    presence_state = normalize_presence_state(states.get("presence_state"), 0)
    screen_state = normalize_screen_state(states.get("screen_state"), presence_state)
    is_idle = presence_state != "active"

    if heartbeat_age is None or heartbeat_age > 300:
        status = "offline"
        reason = "No recent heartbeat from the Mac agent."
    elif not tracking_enabled:
        status = "paused"
        reason = "The Mac agent is running, but tracking is paused."
    elif agent_state == "paused":
        # If the agent says it's paused, but the global state is 'tracking_enabled',
        # it just hasn't synced the resume command yet. We'll show it as online-but-idle
        # to the user to make the UI feel reactive.
        status = "online"
        reason = "Resuming tracking..."
    elif permissions_state not in {"ok", "granted"}:
        status = "degraded"
        reason = "The agent is alive, but macOS permissions are incomplete."
    elif presence_state == "idle":
        status = "online"
        reason = "The agent is online and the Mac is briefly idle."
    elif presence_state == "away":
        status = "online"
        reason = "The agent is online and you are away from your Mac."
    elif presence_state == "locked":
        status = "online"
        reason = "The agent is online and the Mac is locked."
    elif presence_state == "sleeping":
        status = "online"
        reason = "The agent is online and the Mac is sleeping."
    else:
        status = "online"
        reason = "The agent is online and sending heartbeats."

    return {
        "mac_status": status,
        "mac_status_reason": reason,
        "mac_online": status != "offline",
        "mac_idle": is_idle,
        "last_mac_heartbeat_age_seconds": heartbeat_age,
        "last_mac_capture_age_seconds": capture_age,
        "last_mac_snapshot_age_seconds": capture_age,
        "presence_state": presence_state,
        "screen_state": screen_state,
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


async def process_mac_presence(data: MacPresence, db: Session):
    now = data.changed_at or datetime.now(timezone.utc)
    ensure_default_settings(db)
    presence_state = normalize_presence_state(data.presence_state, data.idle_time_seconds)
    screen_state = normalize_screen_state(data.screen_state, presence_state)
    _record_presence_state(db, presence_state, screen_state, now, data.idle_time_seconds)


async def _refresh_app_category_cache(db: Session, now: datetime):
    """Ask LLM to classify today's unique apps. Runs at most once per hour."""
    last_refresh = _parse_iso_dt(get_state(db, "last_category_cache_refresh"))
    if last_refresh and (now - last_refresh).total_seconds() < 3600:
        return
    if not can_use_llm(db, now, task_type="app_cache_refresh"):
        return

    today_start, today_end = user_day_bounds_utc(db, now)
    logs = (
        db.query(ActivityLog)
        .filter(
            ActivityLog.device == "mac",
            ActivityLog.is_idle == False,
            ActivityLog.timestamp >= today_start,
            ActivityLog.timestamp < today_end,
        )
        .all()
    )

    # Collect unique app names with one representative window title each
    app_titles: dict[str, str] = {}
    for entry in logs:
        app = (entry.app_name or "").strip()[:50]
        title = (entry.window_title or "").strip()[:80]
        if app and app not in app_titles:
            app_titles[app] = title

    if not app_titles:
        return

    app_list = "\n".join(
        f"- {app}: {title}" for app, title in list(app_titles.items())[:30]
    )
    global_context = get_global_chat_context(db)
    context_str = f"User's context notes:\n{global_context}\n\n" if global_context else ""

    prompt = (
        "Classify these Mac apps for a personal productivity tracker.\n"
        "Valid categories: studying, working, creative, entertainment, social_media, gaming, break\n\n"
        "- studying: Canvas, Gradescope, homework, research papers, lecture materials\n"
        "- working: code editors, terminal, IDEs, GitHub, project management, Slack, Zoom\n"
        "- creative: Figma, Photoshop, video/audio editing, design tools\n"
        "- entertainment: YouTube (casual), Netflix, Spotify, Reddit browsing\n"
        "- social_media: Instagram, Twitter/X, TikTok, Snapchat\n"
        "- gaming: games, Steam, game launchers\n"
        "- break: Finder, System Preferences, casual/unknown browsing\n\n"
        "Notes: 'Vero'/'LifeManager'/'Code'/'Visual Studio Code'/'Cursor'/'Antigravity' = working. 'Cursor' is an AI code editor. 'Antigravity' is a productivity app.\n"
        f"{context_str}"
        f"Apps:\n{app_list}\n\n"
        'Respond ONLY with JSON: {"AppName": "category", ...}'
    )

    try:
        register_llm_call(db, now)
        result_text = await llm_client.ask_llm(prompt, task_type="app_cache_refresh")
        start = result_text.find('{')
        end = result_text.rfind('}') + 1
        if start >= 0 and end > start:
            parsed = json.loads(result_text[start:end])
            valid_cats = {"studying", "working", "creative", "entertainment", "social_media", "gaming", "break"}
            clean = {k: v.lower() for k, v in parsed.items() if isinstance(v, str) and v.lower() in valid_cats}
            if clean:
                set_state(db, "app_category_cache", json.dumps(clean))
                set_state(db, "last_category_cache_refresh", now.isoformat())
                log.info("App category cache updated: %d entries", len(clean))
    except Exception as exc:
        log.warning("App category cache refresh failed: %s", exc)


def _expire_stale_outside_location(db: Session, now: datetime) -> None:
    """Clear 'Outside X' location if it's been more than 2 hours since arrival."""
    loc = get_state(db, "current_location", "")
    if not loc.startswith("Outside "):
        return
    arrival_str = get_state(db, "location_arrival", "")
    if not arrival_str:
        set_state(db, "current_location", "")
        return
    try:
        arrival = datetime.fromisoformat(arrival_str)
        arrival = arrival if arrival.tzinfo else arrival.replace(tzinfo=timezone.utc)
        if (now - arrival).total_seconds() > 2 * 3600:
            set_state(db, "current_location", "")
            log.info("Cleared stale Outside location: %s", loc)
    except Exception:
        pass


async def process_mac_telemetry(data: MacTelemetry, db: Session):
    now = datetime.now(timezone.utc)
    ensure_default_settings(db)
    _expire_stale_outside_location(db, now)
    privacy_mode = get_state(db, "privacy_mode", DEFAULTS["privacy_mode"])
    presence_state = normalize_presence_state(data.presence_state, data.idle_time_seconds)
    screen_state = normalize_screen_state(data.screen_state, presence_state)
    presence_state = apply_mac_presence_overrides(db, data, presence_state)

    # If the window/app changed from the previous log, the user was definitely at their
    # computer between captures — override "away" regardless of idle_time_seconds.
    if presence_state in ("away", "idle"):
        prev_log = (
            db.query(ActivityLog)
            .filter(ActivityLog.device == "mac")
            .order_by(ActivityLog.timestamp.desc())
            .first()
        )
        if prev_log and (
            (prev_log.app_name or "") != (data.app_name or "")
            or (prev_log.window_title or "") != (data.window_title or "")
        ):
            presence_state = "active"

    # seconds_since_window_change sent by Mac client (Fix 1) overrides as well
    if data.seconds_since_window_change is not None and data.seconds_since_window_change < 300:
        presence_state = "active"

    set_state(db, "last_capture_at", now.isoformat())
    set_state(db, "last_mac_ping", now.isoformat())
    _record_presence_state(db, presence_state, screen_state, now, data.idle_time_seconds)

    # Recompute sleep state immediately using latest Mac idle status + stored iOS state
    stored_activity_type = get_state(db, "last_ios_activity_type", "")
    stored_charging_str = get_state(db, "last_ios_is_charging", "")
    stored_is_charging = None if not stored_charging_str else (stored_charging_str == "true")
    _update_sleep_state(db, now, stored_activity_type, stored_is_charging)

    # "idle" means paused < 30 min — user likely still at desk reading/watching, so continue classifying.
    # Only skip classification for truly absent states (away = 30+ min, locked, sleeping).
    if presence_state in ("away", "locked", "sleeping"):
        zone_until = _parse_iso_dt(get_state(db, "zone_activity_until"))
        current_location = get_state(db, "current_location", "")
        at_named_location = bool(
            current_location
            and not current_location.startswith("Outside ")
            and zone_until
            and now < zone_until
        )
        is_currently_walking = get_state(db, "is_walking") == "true"
        if not at_named_location and not is_currently_walking:
            set_state(db, "current_activity_category", "idle")
            set_state(db, "current_activity_summary", presence_summary(presence_state))
        return

    last_check_str = get_state(db, "last_vagueness_check")
    last_check = _parse_iso_dt(last_check_str) or datetime.min.replace(tzinfo=timezone.utc)

    classification_interval = max(300, get_capture_interval_seconds(db))
    if (now - last_check).total_seconds() > classification_interval:
        set_state(db, "last_vagueness_check", now.isoformat())

        recent = get_recent_mac_logs(db, limit=20)
        user_self_report = get_user_self_report(db)
        history = getattr(data, "recent_history", None)
        global_context = get_global_chat_context(db)
        low_signal = (
            len(recent) < 3
            or all(
                not (entry.get("app_name") or "").strip() and not (entry.get("window_title") or "").strip()
                for entry in recent
            )
        )
        if low_signal and get_state(db, "llm_mode", DEFAULTS["llm_mode"]) == "ultra_save":
            result = heuristic_classify_activity(recent, idle_time_seconds=data.idle_time_seconds, recent_history=history)
        elif can_use_llm(db, now, task_type="classification"):
            register_llm_call(db, now)
            _cls_location = get_state(db, "current_location", "")
            _cls_intent = get_state(db, "context_current_intent", "")
            _cls_upcoming = get_calendar_events_for_window(db, now, now + timedelta(hours=2))
            result = await llm_client.classify_activity_context(
                recent,
                user_self_report,
                recent_history=history,
                global_context=global_context,
                location=_cls_location,
                upcoming_events=_cls_upcoming,
                intent=_cls_intent,
            )
        else:
            result = heuristic_classify_activity(recent, idle_time_seconds=data.idle_time_seconds, recent_history=history)
        new_category = result["category"]
        new_summary = result["summary"]
        presence_inference = result.get("presence_inference", "unknown")

        # If AI says user was present, correct the most recent ActivityLog's is_idle flag
        if presence_inference in ("active", "likely_active"):
            latest_log = (
                db.query(ActivityLog)
                .filter(ActivityLog.device == "mac")
                .order_by(ActivityLog.timestamp.desc())
                .first()
            )
            if latest_log and latest_log.is_idle:
                latest_log.is_idle = False
                db.commit()

        _close_session_to_calendar(db, new_category, now)
        _maybe_start_session(db, new_category, new_summary, now)

        set_state(db, "current_activity_category", new_category)
        set_state(db, "current_activity_summary", new_summary)
        set_state(
            db,
            "last_redacted_window_title",
            sanitize_window_title(data.app_name, data.window_title, privacy_mode, bool(data.detailed_capture_enabled)),
        )
        log.info("Activity classified: %s - %s (presence: %s)", new_category, new_summary, presence_inference)

        study_mode = get_state(db, "study_mode")
        if study_mode == "active" and new_category in DISTRACTED_CATEGORIES and not get_state(db, "pending_prompt"):
            if can_use_llm(db, now, task_type="prompt"):
                register_llm_call(db, now)
                prompt = await llm_client.generate_prompt(data.app_name, data.window_title)
            else:
                prompt = "You seem distracted. Is this still part of your intended task?"
            set_state(db, "pending_prompt", prompt)
        elif new_category in DISTRACTED_CATEGORIES and not get_state(db, "pending_prompt"):
            prev_callout_category = get_state(db, "callout_category")
            set_state(db, "callout_category", new_category)
            set_state(db, "callout_summary", new_summary)
            # Generate AI-driven callout message when category becomes distracted
            if prev_callout_category != new_category and can_use_llm(db, now, task_type="prompt"):
                global_context = get_global_chat_context(db)
                _nudge_intent = get_state(db, "context_current_intent", "")
                _nudge_location = get_state(db, "current_location", "")
                # Check how stale the last Mac data is
                _last_capture_str = get_state(db, "last_capture_at", "")
                _data_age_note = ""
                if _last_capture_str:
                    try:
                        _last_cap = datetime.fromisoformat(_last_capture_str)
                        _last_cap = _last_cap if _last_cap.tzinfo else _last_cap.replace(tzinfo=timezone.utc)
                        _data_age_mins = int((now - _last_cap).total_seconds() / 60)
                        if _data_age_mins > 10:
                            _data_age_note = f" (data {_data_age_mins}m old)"
                    except Exception:
                        pass
                callout_prompt = (
                    f"User has been on {new_category} ({new_summary}){_data_age_note} during a work/study period.\n"
                    + (f'Their stated intent is: "{_nudge_intent}"\n' if _nudge_intent else "")
                    + (f"Current location: {_nudge_location}\n" if _nudge_location else "")
                    + (f"User context: {global_context}\n" if global_context else "")
                    + "Write ONE short nudge (under 12 words) referencing their intent if set. "
                    "Be direct, not preachy. No emojis."
                )
                try:
                    register_llm_call(db, now)
                    ai_callout = await llm_client.ask_llm(callout_prompt, task_type="prompt")
                    if ai_callout and ai_callout.strip():
                        set_state(db, "callout_ai_message", ai_callout.strip())
                except Exception:
                    set_state(db, "callout_ai_message", "")
            elif prev_callout_category != new_category:
                set_state(db, "callout_ai_message", "")
        else:
            set_state(db, "callout_category", "")
            set_state(db, "callout_summary", "")
            set_state(db, "callout_ai_message", "")

        # Nudge for upcoming office hours when user is distracted or unproductive
        _maybe_office_hours_nudge(db, now, new_category)

        # Refresh AI-driven app category cache (at most once per hour)
        await _refresh_app_category_cache(db, now)

    summaries_enabled = get_state(db, "hourly_summaries_enabled", DEFAULTS["hourly_summaries_enabled"]) == "true"
    if summaries_enabled:
        local_tz = resolve_user_timezone(db)
        current_hour_start = now.astimezone(local_tz).replace(minute=0, second=0, microsecond=0)
        last_summary_str = get_state(db, "last_hourly_summary")
        last_summary_hour_start = None
        if last_summary_str:
            try:
                dt = datetime.fromisoformat(last_summary_str)
                dt = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
                last_summary_hour_start = dt.astimezone(local_tz).replace(minute=0, second=0, microsecond=0)
            except Exception:
                pass
        if last_summary_hour_start is None or last_summary_hour_start < current_hour_start:
            set_state(db, "last_hourly_summary", now.isoformat())
            await _generate_and_store_hourly_summary(db, now)  # previous completed hour
        # Always update current partial hour summary
        await _generate_and_store_hourly_summary(db, now, force_current=True)


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
            set_state(db, "current_activity_category", "break")
            set_state(db, "current_activity_summary", "Out for a walk")
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
        set_state(db, "current_activity_category", "unknown")
        set_state(db, "current_activity_summary", "Just finished a walk")
    set_state(db, "is_walking", "false")


async def process_ios_telemetry(data: iOSTelemetry, db: Session):
    now = datetime.now(timezone.utc)
    ensure_default_settings(db)
    _record_ios_event(db, now)
    activity_type = data.activity_type or ""
    activity_type_lower = activity_type.lower()
    if "walk" in activity_type_lower:
        set_state(db, "seen_walking_automation", "true")
    if data.is_charging is not None:
        set_state(db, "seen_charging_automation", "true")

    _handle_ios_steps(db, data.steps_today)
    is_walking = bool(activity_type and "walk" in activity_type_lower)
    _handle_walking_transition(db, now, is_walking, data.location_label or "")

    current_location = data.location_label or ""
    if current_location:
        await _handle_location_change(db, current_location, now)

    # Persist so Mac telemetry can recompute sleep state without waiting for next iOS ping
    set_state(db, "last_ios_activity_type", activity_type)
    if data.is_charging is not None:
        set_state(db, "last_ios_is_charging", "true" if data.is_charging else "false")

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
        await _handle_location_change(db, zone_label, now, zone_type=zone_type)
        set_state(db, "last_zone_enter", zone.slug if zone else data.zone_slug)

        # Infer activity category from zone and lock it for 2 hours so Mac idle won't override
        inferred = _infer_zone_category(zone_type, zone_label)
        if inferred:
            cat, summary = inferred
            set_state(db, "current_activity_category", cat)
            set_state(db, "current_activity_summary", summary)
        zone_until = (now + timedelta(hours=2)).isoformat()
        set_state(db, "zone_activity_until", zone_until)

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

    # Set "outside" context so UI shows where user left, not blank
    set_state(db, "current_location", f"Outside {zone_label}")
    set_state(db, "current_activity_category", "away")
    set_state(db, "current_activity_summary", f"Left {zone_label}")
    set_state(db, "zone_activity_until", "")  # clear zone lock on exit


def get_context_preferences(db: Session) -> dict:
    ensure_default_settings(db)
    return {
        "current_intent": get_state(db, "context_current_intent", DEFAULTS["context_current_intent"]),
        "sleep_start_hour": _safe_int(get_state(db, "sleep_start_hour", DEFAULTS["sleep_start_hour"]), 1),
        "sleep_end_hour": _safe_int(get_state(db, "sleep_end_hour", DEFAULTS["sleep_end_hour"]), 9),
        "special_mode": get_state(db, "context_special_mode", DEFAULTS["context_special_mode"]) or "normal",
    }


def update_context_preferences(db: Session, payload: dict) -> dict:
    ensure_default_settings(db)
    if "current_intent" in payload:
        set_state(db, "context_current_intent", str(payload.get("current_intent") or "").strip()[:240])
    if "sleep_start_hour" in payload:
        hour = max(0, min(23, int(payload.get("sleep_start_hour"))))
        set_state(db, "sleep_start_hour", str(hour))
    if "sleep_end_hour" in payload:
        hour = max(0, min(23, int(payload.get("sleep_end_hour"))))
        set_state(db, "sleep_end_hour", str(hour))
    if "special_mode" in payload:
        special_mode = str(payload.get("special_mode") or "normal").strip().lower()
        if special_mode not in {"normal", "travel", "exam", "rest"}:
            raise ValueError("special_mode must be one of: normal, travel, exam, rest")
        set_state(db, "context_special_mode", special_mode)
    return get_context_preferences(db)
