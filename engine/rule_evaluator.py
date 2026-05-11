from typing import List
from datetime import datetime
import pytz
from .spatial import is_bottom_center_in_zone
from .temporal import is_within_schedule
from schemas.detection import DetectionEvent
from schemas.rule_schema import RuleDefinition

class RuleEvaluator:
    def __init__(self, rule: RuleDefinition):
        self.rule = rule
        self.active_violations = {}  # In production, use Redis

    def evaluate(self, det_event: DetectionEvent) -> bool:
        if not self.rule.enabled:
            return False
        # 1. Temporal gating
        if self.rule.schedule:
            tz = pytz.timezone(self.rule.schedule.timezone)
            now = datetime.now(tz)
            if not is_within_schedule(now, self.rule.schedule):
                return False

        # 2. Check required detection modules
        det_classes = {obj.class_name for obj in det_event.objects}
        required = set(self.rule.detection_modules)
        if not required.issubset(det_classes):
            return False

        # 3. Filter by confidence
        confident_objects = [o for o in det_event.objects if o.confidence >= self.rule.confidence_threshold]
        if not confident_objects:
            return False

        # 4. Spatial filtering
        trigger_objs = []
        for obj in confident_objects:
            bc_x = (obj.bbox[0] + obj.bbox[2]) / 2
            bc_y = obj.bbox[3]  # ymax = bottom
            for zone in self.rule.zones:
                if is_bottom_center_in_zone(bc_x, bc_y, zone.points):
                    trigger_objs.append((obj.class_name, zone.name))
                    break

        if not trigger_objs:
            return False

        # 5. Evaluate logical condition (simple DSL)
        # Security note: eval() used for prototyping. Replace with a proper parser.
        context = {
            "person_in_zone": any("person" in o.class_name.lower() for o in confident_objects),
            "helmet_status": "none" if any("no-helmet" in o.class_name.lower() for o in confident_objects) else "wearing"
        }
        condition_met = eval(self.rule.condition, {"__builtins__": {}}, context)
        if not condition_met:
            return False

        # 6. State management (duration & cooldown) handled externally
        return True