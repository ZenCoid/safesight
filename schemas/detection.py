from pydantic import BaseModel
from typing import List, Optional
from uuid import UUID

class DetectionObject(BaseModel):
    class_name: str
    confidence: float
    bbox: List[float]  # [xmin, ymin, xmax, ymax] normalized 0-1

class DetectionEvent(BaseModel):
    camera_id: UUID
    frame_id: int
    timestamp: float  # epoch
    objects: List[DetectionObject]
    raw_confidence_distribution: Optional[dict] = {}  # for teacher-student loop