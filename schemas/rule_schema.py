from pydantic import BaseModel, Field, confloat
from typing import List, Optional, Literal
from datetime import time
from uuid import UUID

class PolygonZone(BaseModel):
    name: str
    points: List[List[float]]

class ScheduleWindow(BaseModel):
    days: List[Literal["mon","tue","wed","thu","fri","sat","sun"]]
    start_time: time
    end_time: time
    timezone: str = "UTC"

class EscalationLevel(BaseModel):
    channels: List[Literal["whatsapp","push_notification","email","sms","siren","autonomous_action"]]
    delay_seconds: int = 0
    unacknowledged_seconds: Optional[int] = None

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
    cameras: List[UUID]
    detection_modules: List[str]
    zones: List[PolygonZone] = []
    confidence_threshold: confloat(ge=0.0, le=1.0) = 0.5
    min_duration_seconds: int = 0
    cooldown_seconds: int = 30
    schedule: Optional[ScheduleWindow] = None
    escalation_levels: List[EscalationLevel] = []
    multi_camera_links: List[MultiCameraLink] = []
    condition: str = "person_in_zone AND helmet_status=='none'"