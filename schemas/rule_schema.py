from pydantic import BaseModel, Field, confloat, validator
from typing import List, Optional, Literal
from datetime import time
from uuid import UUID
import re

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

    @validator('condition')
    def validate_condition(cls, v):
        if not isinstance(v, str):
            raise ValueError('Condition must be a string')
        forbidden = ['__', 'import', 'exec', 'eval', 'subprocess', 'os.', 'sys.', 'open(']
        lower = v.lower()
        for token in forbidden:
            if token in lower:
                raise ValueError(f'Condition contains forbidden token: {token}')
        if not re.match(r'^[\w\s\'\"=!<>&|()_.,:+\-*/%\[\]@]+$', v):
            raise ValueError('Condition contains disallowed characters')
        return v

    @validator('detection_modules')
    def validate_modules(cls, v):
        for mod in v:
            if not re.match(r'^[a-zA-Z0-9_\- ]+$', mod):
                raise ValueError(f'Invalid detection module name: {mod}')
        return v

    @validator('rule_name')
    def validate_rule_name(cls, v):
        if len(v) > 128:
            raise ValueError('Rule name must be 128 characters or less')
        if not re.match(r'^[\w\s\-_]+$', v):
            raise ValueError('Rule name contains invalid characters')
        return v