import uuid
from sqlalchemy import Column, String, Boolean, Float, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from core.database import Base

class Camera(Base):
    __tablename__ = "cameras"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    rtsp_url = Column(String, nullable=False)
    enabled = Column(Boolean, default=True)
    health_status = Column(String, default="unknown")   # online / offline / degraded
    current_fps = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())