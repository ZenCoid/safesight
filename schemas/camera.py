from pydantic import BaseModel
from typing import Optional
from uuid import UUID
from datetime import datetime

class CameraCreate(BaseModel):
    name: str
    rtsp_url: str
    enabled: bool = True

class CameraRead(BaseModel):
    id: UUID
    name: str
    rtsp_url: str
    enabled: bool
    health_status: str
    current_fps: float
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True