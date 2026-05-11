from pydantic import BaseModel
from typing import List, Optional, Tuple
from uuid import UUID

class DetectionObject(BaseModel):
    class_name: str
    confidence: float
    bbox: List[float]  # [xmin, ymin, xmax, ymax] normalised 0‑1
    top_k: Optional[List[Tuple[str, float]]] = None  # top‑k predictions (class, confidence)

class DetectionEvent(BaseModel):
    camera_id: UUID
    frame_id: int
    timestamp: float
    objects: List[DetectionObject]
    raw_confidence_distribution: Optional[dict] = {}