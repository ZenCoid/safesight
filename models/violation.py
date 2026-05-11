import uuid
from sqlalchemy import Column, String, Float, Boolean, DateTime, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from core.database import Base

class ViolationEvent(Base):
    __tablename__ = "violation_events"
    time = Column(DateTime(timezone=True), primary_key=True, server_default=func.now())
    event_id = Column(UUID(as_uuid=True), default=uuid.uuid4)
    rule_id = Column(UUID(as_uuid=True), nullable=False)
    camera_id = Column(UUID(as_uuid=True), nullable=False)
    detection_snapshot = Column(JSONB)
    severity = Column(String, default="warning")
    acknowledged = Column(Boolean, default=False)
    clip_path = Column(String)