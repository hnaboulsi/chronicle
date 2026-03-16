import datetime
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text

from database import Base

# Helper to get current UTC time as naive datetime (for backward compat with existing DB)
def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

# SQLAlchemy Models
class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=_utc_now)
    device = Column(String, index=True)  # "mac" or "ios"
    app_name = Column(String, nullable=True)
    window_title = Column(String, nullable=True)
    is_idle = Column(Boolean, default=False)
    location_label = Column(String, nullable=True)  # e.g. "Library", "Home"
    activity_type = Column(String, nullable=True)  # e.g. "Walking", "Stationary"
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    steps_today = Column(Integer, nullable=True)
    battery_pct = Column(Integer, nullable=True)  # 0-100, iOS only
    presence_state = Column(String, nullable=True)
    screen_state = Column(String, nullable=True)

class AgentState(Base):
    __tablename__ = "agent_states"
    
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, index=True)
    value = Column(String)
    updated_at = Column(DateTime, default=_utc_now, onupdate=_utc_now)


class LocationZone(Base):
    __tablename__ = "location_zones"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    radius_meters = Column(Integer, nullable=False, default=75)
    enabled = Column(Boolean, default=True)
    zone_type = Column(String, nullable=False, default="custom")
    focus_mode = Column(String, nullable=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=_utc_now)
    updated_at = Column(DateTime, default=_utc_now, onupdate=_utc_now)


class CalendarEventJob(Base):
    __tablename__ = "calendar_event_jobs"

    id = Column(Integer, primary_key=True, index=True)
    kind = Column(String, nullable=False)
    title = Column(String, nullable=False)
    notes = Column(Text, nullable=True)
    start_at = Column(DateTime, nullable=False)
    end_at = Column(DateTime, nullable=False)
    payload_json = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="pending", index=True)
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_utc_now)
    updated_at = Column(DateTime, default=_utc_now, onupdate=_utc_now)

# Pydantic Schemas
class MacTelemetry(BaseModel):
    app_name: str
    window_title: str
    idle_time_seconds: int
    recent_history: Optional[list] = None
    presence_state: Optional[str] = None
    screen_state: Optional[str] = None
    detailed_capture_enabled: Optional[bool] = False

class HourlySummary(Base):
    __tablename__ = "hourly_summaries"

    id = Column(Integer, primary_key=True, index=True)
    hour_start = Column(DateTime, nullable=False, index=True)  # top of the hour (UTC)
    summary_text = Column(String, nullable=False)
    productivity_score = Column(Float, nullable=True)  # 0.0–10.0
    summary_source = Column(String, nullable=False, default="llm")  # llm | deterministic
    confidence = Column(Float, nullable=True)  # 0..1
    fallback_used = Column(Boolean, default=False)
    created_at = Column(DateTime, default=_utc_now)


class iOSTelemetry(BaseModel):
    location_label: Optional[str] = None
    activity_type: Optional[str] = None  # "Walking", "Stationary", etc.
    battery_level: Optional[float] = None
    is_charging: Optional[bool] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    steps_today: Optional[int] = None


class MacHeartbeat(BaseModel):
    client_id: Optional[str] = None
    app_version: Optional[str] = None
    agent_state: Optional[str] = "running"
    tracking_enabled: Optional[bool] = True
    permissions_state: Optional[str] = "ok"
    last_error: Optional[str] = None


class MacPresence(BaseModel):
    presence_state: str
    screen_state: Optional[str] = "visible"
    changed_at: Optional[datetime.datetime] = None
    idle_time_seconds: int = 0


class UserCalendarEvent(Base):
    __tablename__ = "user_calendar_events"

    id = Column(Integer, primary_key=True, index=True)
    event_uid = Column(String, nullable=True, index=True)  # native calendar UID for dedup
    title = Column(String, nullable=False)
    start_at = Column(DateTime, nullable=False)
    end_at = Column(DateTime, nullable=False)
    calendar_name = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_utc_now)
    updated_at = Column(DateTime, default=_utc_now, onupdate=_utc_now)


class CalendarEventItem(BaseModel):
    event_uid: Optional[str] = None
    title: str
    start_at: datetime.datetime
    end_at: datetime.datetime
    calendar_name: Optional[str] = None
    notes: Optional[str] = None


class iOSZoneEvent(BaseModel):
    zone_slug: str
    transition: str
    event_time: Optional[datetime.datetime] = None
    battery_level: Optional[float] = None
    steps_today: Optional[int] = None
