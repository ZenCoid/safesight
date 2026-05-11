import uuid
from sqlalchemy import Column, ForeignKey, DateTime, func, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from core.database import Base

class RuleCamera(Base):
    __tablename__ = "rule_camera"
    __table_args__ = (
        UniqueConstraint("rule_id", "camera_id", name="uq_rule_camera"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rule_id = Column(UUID(as_uuid=True), ForeignKey("rules.id", ondelete="CASCADE"), nullable=False)
    camera_id = Column(UUID(as_uuid=True), ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())