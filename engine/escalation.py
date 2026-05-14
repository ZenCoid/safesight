import json
import logging
from datetime import datetime, timezone
from typing import Dict, Optional
from uuid import UUID

import redis.asyncio as aioredis
from sqlalchemy import select
from models.violation import ViolationEvent
from models.rule import Rule
from models.alert import Alert
from core.database import AsyncSessionLocal
from core.config import settings
from schemas.rule_schema import RuleDefinition
from core.celery_app import celery_app

logger = logging.getLogger(__name__)

REDIS_KEY = "safesight:escalation:v2"

class EscalationState:
    def __init__(self):
        self._redis: Optional[aioredis.Redis] = None

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        return self._redis

    async def handle_violation_start(self, event_id: UUID, rule: RuleDefinition):
        r = await self._get_redis()
        now = datetime.now(timezone.utc).isoformat()
        data = {
            "start_time": now,
            "last_level": 0,
            "rule_id": str(rule.rule_id)
        }
        await r.hset(REDIS_KEY, str(event_id), json.dumps(data))
        await self._dispatch_level(event_id, rule, 1)

    async def handle_violation_end(self, event_id: UUID):
        r = await self._get_redis()
        await r.hdel(REDIS_KEY, str(event_id))

    async def tick(self):
        r = await self._get_redis()
        all_raw = await r.hgetall(REDIS_KEY)
        now = datetime.now(timezone.utc)

        for event_id_str, raw_data in all_raw.items():
            data = json.loads(raw_data)
            start_time = datetime.fromisoformat(data["start_time"])
            event_id = UUID(event_id_str)

            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(ViolationEvent).where(ViolationEvent.event_id == event_id)
                )
                viol = result.scalar_one_or_none()
                if not viol or viol.acknowledged:
                    await self.handle_violation_end(event_id)
                    continue

                rule_result = await session.execute(
                    select(Rule).where(Rule.id == UUID(data["rule_id"]))
                )
                rule_row = rule_result.scalar_one_or_none()
                if not rule_row:
                    continue
                rule_def = RuleDefinition(**rule_row.definition)

                elapsed = (now - start_time).total_seconds()
                last_level = data.get("last_level", 0)

                for idx, level in enumerate(rule_def.escalation_levels, start=1):
                    if idx <= last_level:
                        continue
                    should_fire = False
                    if level.unacknowledged_seconds is not None:
                        if not viol.acknowledged and elapsed >= level.unacknowledged_seconds:
                            should_fire = True
                    else:
                        if elapsed >= level.delay_seconds:
                            should_fire = True

                    if should_fire:
                        await self._dispatch_level(event_id, rule_def, idx)
                        data["last_level"] = idx
                        await r.hset(REDIS_KEY, event_id_str, json.dumps(data))
                        break

    async def _dispatch_level(self, event_id: UUID, rule_def: RuleDefinition, level: int):
        if level > len(rule_def.escalation_levels):
            return
        esc = rule_def.escalation_levels[level - 1]
        for channel in esc.channels:
            celery_app.send_task(
                "tasks.alerting.send_alert",
                args=[str(event_id), channel, level]
            )
        logger.info(f"Dispatched level {level} for violation {event_id} via {esc.channels}")

escalation_state = EscalationState()