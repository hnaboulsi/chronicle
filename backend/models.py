from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean
from database import Base
import datetime
from pydantic import BaseModel
from typing import Optional

# SQLAlchemy Models
class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
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
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

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
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class iOSTelemetry(BaseModel):
    location_label: Optional[str] = None
    activity_type: Optional[str] = None  # "Walking", "Stationary", etc.
    battery_level: Optional[float] = None
    is_charging: Optional[bool] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    steps_today: Optional[int] = None
