from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text
from database import Base
import datetime
from pydantic import BaseModel
from typing import Optional

# Helper to get current UTC time as naive datetime (for backward compat with existing DB)
def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

# SQLAlchemy Models
class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=_utc_now)
    device = Column(String, index=True) # "mac" or "ios"
    app_name = Column(String, nullable=True)
    window_title = Column(String, nullable=True)
    is_idle = Column(Boolean, default=False)
    location_label = Column(String, nullable=True) # e.g. "Library", "Home"
    activity_type = Column(String, nullable=True) # e.g. "Walking", "Stationary"
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    steps_today = Column(Integer, nullable=True)
    battery_pct = Column(Integer, nullable=True)  # 0-100, iOS only

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


class iOSZoneEvent(BaseModel):
    zone_slug: str
    transition: str
    event_time: Optional[datetime.datetime] = None
    battery_level: Optional[float] = None
    steps_today: Optional[int] = None
