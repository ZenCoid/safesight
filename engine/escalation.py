import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
from uuid import UUID
from sqlalchemy import select
from models.violation import ViolationEvent
from models.rule import Rule
from models.alert import Alert
from core.database import AsyncSessionLocal
from schemas.rule_schema import RuleDefinition, EscalationLevel
from core.celery_app import celery_app

logger = logging.getLogger(__name__)

class EscalationState:
    """Tracks active violations and triggers alerts according to escalation levels."""
    def __init__(self):
        self._violations: Dict[UUID, datetime] = {}       # event_id -> start time
        self._escalations_sent: Dict[UUID, int] = {}      # event_id -> last level dispatched

    async def handle_violation_start(self, event_id: UUID, rule: RuleDefinition):
        """Called when a new violation is created."""
        self._violations[event_id] = datetime.now(timezone.utc)
        self._escalations_sent[event_id] = 0
        # Immediate Level 1 dispatch
        await self._dispatch_level(event_id, rule, 1)

    async def handle_violation_end(self, event_id: UUID):
        """Called when a violation is acknowledged or resolved."""
        self._violations.pop(event_id, None)
        self._escalations_sent.pop(event_id, None)

    async def tick(self):
        """Periodic check for pending escalation levels."""
        now = datetime.now(timezone.utc)
        for event_id, start_time in list(self._violations.items()):
            async with AsyncSessionLocal() as session:
                # Fetch violation event by event_id (not time)
                result = await session.execute(
                    select(ViolationEvent).where(ViolationEvent.event_id == event_id)
                )
                viol = result.scalar_one_or_none()
                if not viol or viol.acknowledged:
                    await self.handle_violation_end(event_id)
                    continue

                # Fetch the rule definition
                rule_result = await session.execute(
                    select(Rule).where(Rule.id == viol.rule_id)
                )
                rule_row = rule_result.scalar_one_or_none()
                if not rule_row:
                    continue
                rule_def = RuleDefinition(**rule_row.definition)

                elapsed = (now - start_time).total_seconds()
                last_level = self._escalations_sent.get(event_id, 0)

                # Check each level that hasn't been dispatched yet
                for idx, level in enumerate(rule_def.escalation_levels, start=1):
                    if idx <= last_level:
                        continue

                    should_fire = False
                    if level.unacknowledged_seconds is not None:
                        # Fire if violation is still unacknowledged after the specified time
                        if not viol.acknowledged and elapsed >= level.unacknowledged_seconds:
                            should_fire = True
                    else:
                        # Fire based on simple delay (including 0 second delay for immediate)
                        if elapsed >= level.delay_seconds:
                            should_fire = True

                    if should_fire:
                        await self._dispatch_level(event_id, rule_def, idx)
                        break  # dispatch one level per tick to respect order

    async def _dispatch_level(self, event_id: UUID, rule_def: RuleDefinition, level: int):
        if level > len(rule_def.escalation_levels):
            return
        esc = rule_def.escalation_levels[level - 1]
        for channel in esc.channels:
            celery_app.send_task("tasks.alerting.send_alert", args=[str(event_id), channel, level])
        self._escalations_sent[event_id] = level
        logger.info(f"Dispatched level {level} for violation {event_id} via {esc.channels}")

# Global singleton (will be used by background task)
escalation_state = EscalationState()