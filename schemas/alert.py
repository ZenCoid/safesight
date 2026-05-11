from pydantic import BaseModel
from uuid import UUID
from datetime import datetime

class AlertRead(BaseModel):
    id: UUID
    violation_event_id: UUID
    camera_id: UUID
    escalation_level: int
    channel: str
    sent: bool
    created_at: datetime

    class Config:
        from_attributes = True