import logging
from datetime import datetime, timedelta
from typing import Dict, Optional
from uuid import UUID
from sqlalchemy import select
from models.violation import ViolationEvent
from models.alert import Alert
from core.database import AsyncSessionLocal
from schemas.rule_schema import RuleDefinition, EscalationLevel
from core.celery_app import celery_app

logger = logging.getLogger(__name__)

class EscalationState:
    """Tracks active violations and triggers alerts according to escalation levels."""
    def __init__(self):
        # In production, use Redis for distributed state
        self._violations: Dict[UUID, datetime] = {}
        self._escalations_sent: Dict[UUID, int] = {}  # violation_id -> last level sent

    async def handle_violation_start(self, violation_id: UUID, rule: RuleDefinition):
        self._violations[violation_id] = datetime.utcnow()
        self._escalations_sent[violation_id] = 0
        # Level 1 immediate
        await self._dispatch_level(violation_id, rule, 1)

    async def handle_violation_end(self, violation_id: UUID):
        self._violations.pop(violation_id, None)
        self._escalations_sent.pop(violation_id, None)

    async def tick(self):
        """Periodic check for escalation deadlines."""
        now = datetime.utcnow()
        for viol_id, start_time in list(self._violations.items()):
            # Fetch rule and state from DB to get escalation levels
            async with AsyncSessionLocal() as session:
                viol = await session.get(ViolationEvent, viol_id)
                if not viol or viol.acknowledged:
                    await self.handle_violation_end(viol_id)
                    continue

                # Get rule definition
                rule_q = await session.execute(select(Rule).where(Rule.id == viol.rule_id))
                rule = rule_q.scalar_one_or_none()
                if not rule:
                    continue
                rule_def = RuleDefinition(**rule.definition)  # parse JSON

            elapsed = (now - start_time).total_seconds()
            last_level = self._escalations_sent.get(viol_id, 0)

            for level in rule_def.escalation_levels:
                # level is EscalationLevel object; we need to check delay_seconds and unacknowledged
                # Level index 1-based: first is level 1, second level 2, etc.
                # We assume escalation_levels are ordered: 0 -> L1, 1 -> L2, ...
                idx = rule_def.escalation_levels.index(level) + 1
                if idx <= last_level:
                    continue
                if level.delay_seconds > 0 and elapsed >= level.delay_seconds:
                    # Check unacknowledged condition if set
                    if level.unacknowledged_seconds and not viol.acknowledged:
                        if elapsed < level.unacknowledged_seconds:
                            continue
                    await self._dispatch_level(viol_id, rule_def, idx)

    async def _dispatch_level(self, violation_id: UUID, rule: RuleDefinition, level: int):
        # Find the EscalationLevel for this level (1-indexed)
        if level > len(rule.escalation_levels):
            return
        esc = rule.escalation_levels[level-1]
        for channel in esc.channels:
            celery_app.send_task("tasks.alerting.send_alert", args=[violation_id, channel, level])
        self._escalations_sent[violation_id] = level

# Global singleton (will be used by a background task)
escalation_state = EscalationState()