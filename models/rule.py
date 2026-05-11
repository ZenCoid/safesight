import uuid
from sqlalchemy import Column, String, Boolean, DateTime, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from core.database import Base

class Rule(Base):
    __tablename__ = "rules"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    version = Column(String, default="1.0")
    enabled = Column(Boolean, default=True)
    definition = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())