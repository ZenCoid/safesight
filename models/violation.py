import uuid
from sqlalchemy import Column, String, Float, Boolean, DateTime, func, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from core.database import Base

class ViolationEvent(Base):
    __tablename__ = "violation_events"

    time = Column(DateTime(timezone=True), primary_key=True, server_default=func.now())
    event_id = Column(UUID(as_uuid=True), default=uuid.uuid4, nullable=False)
    rule_id = Column(UUID(as_uuid=True), nullable=False)
    camera_id = Column(UUID(as_uuid=True), nullable=False)
    detection_snapshot = Column(JSONB)
    severity = Column(String, default="warning")
    acknowledged = Column(Boolean, default=False)
    clip_path = Column(String)
    image_hash = Column(String, nullable=True)

    __table_args__ = (
        Index("ix_violation_camera_id", "camera_id"),
        Index("ix_violation_time_camera", "time", "camera_id"),
        Index("ix_violation_event_id", "event_id"),
    )