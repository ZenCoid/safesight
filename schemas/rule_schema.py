from pydantic import BaseModel, Field, confloat
from typing import List, Optional, Literal
from datetime import time
from uuid import UUID

class PolygonZone(BaseModel):
    name: str
    points: List[List[float]]  # list of [x, y] normalized 0-1, closed polygon

class ScheduleWindow(BaseModel):
    days: List[Literal["mon","tue","wed","thu","fri","sat","sun"]]
    start_time: time
    end_time: time
    timezone: str = "UTC"  # IANA

class EscalationLevel(BaseModel):
    channels: List[Literal["whatsapp","push_notification","email","sms","siren","autonomous_action"]]
    delay_seconds: int = 0   # after violation start
    unacknowledged_seconds: Optional[int] = None  # after violation still unacknowledged

class MultiCameraLink(BaseModel):
    trigger_camera_id: UUID
    target_camera_id: UUID
    action: Literal["increase_sensitivity","enable_rule","disable_rule"]
    rule_ids: Optional[List[UUID]] = None

class RuleDefinition(BaseModel):
    rule_id: UUID
    rule_name: str
    version: str = "1.0"
    enabled: bool = True
    cameras: List[UUID]  # camera IDs
    detection_modules: List[str]  # "person", "helmet", "fire", etc.
    zones: List[PolygonZone] = []
    confidence_threshold: confloat(ge=0.0, le=1.0) = 0.5
    min_duration_seconds: int = 0
    cooldown_seconds: int = 30
    schedule: Optional[ScheduleWindow] = None
    escalation_levels: List[EscalationLevel] = []
    multi_camera_links: List[MultiCameraLink] = []
    # The rule's logical expression can be stored as a structured object or a simple DSL.
    # For Phase 1 we'll use a simple "condition" field that the evaluator interprets.
    condition: str = "person_in_zone AND helmet_status=='none'"  # example DSL