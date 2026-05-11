import uuid
from sqlalchemy import Column, String, Boolean, Integer, DateTime, func, Index
from sqlalchemy.dialects.postgresql import UUID
from core.database import Base

class Alert(Base):
    __tablename__ = "alerts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    violation_event_id = Column(UUID(as_uuid=True), nullable=False)
    camera_id = Column(UUID(as_uuid=True), nullable=False)
    escalation_level = Column(Integer, default=1)
    channel = Column(String)
    sent = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_alert_violation", "violation_event_id"),
        Index("ix_alert_camera_time", "camera_id", "created_at"),
    )