import logging
from uuid import UUID
from typing import Optional
import redis.asyncio as aioredis
from core.config import settings
from schemas.rule_schema import RuleDefinition, MultiCameraLink

logger = logging.getLogger(__name__)

ARM_TTL_SECONDS = 120
DEFAULT_LOWERED_THRESHOLD = 0.3

async def _get_redis():
    return aioredis.from_url(settings.REDIS_URL, decode_responses=True)

async def arm_camera_for_rule(camera_id: UUID, rule_id: UUID, lowered_threshold: float = DEFAULT_LOWERED_THRESHOLD):
    """Store a temporary lowered confidence threshold for a specific rule on a camera."""
    r = await _get_redis()
    key = f"safesight:arm:{camera_id}:{rule_id}"
    await r.set(key, str(lowered_threshold), ex=ARM_TTL_SECONDS)
    logger.info(f"Armed camera {camera_id} rule {rule_id} with threshold {lowered_threshold} for {ARM_TTL_SECONDS}s")

async def get_armed_threshold(camera_id: UUID, rule_id: UUID) -> Optional[float]:
    """Retrieve the temporary threshold for a camera-rule pair, if any."""
    r = await _get_redis()
    key = f"safesight:arm:{camera_id}:{rule_id}"
    val = await r.get(key)
    if val:
        return float(val)
    return None

async def arm_camera_globally(camera_id: UUID, lowered_threshold: float = DEFAULT_LOWERED_THRESHOLD):
    """Arm a camera globally (lower threshold for all rules) by storing a camera-level override."""
    r = await _get_redis()
    key = f"safesight:arm:global:{camera_id}"
    await r.set(key, str(lowered_threshold), ex=ARM_TTL_SECONDS)
    logger.info(f"Globally armed camera {camera_id} with threshold {lowered_threshold} for {ARM_TTL_SECONDS}s")

async def get_global_armed_threshold(camera_id: UUID) -> Optional[float]:
    r = await _get_redis()
    key = f"safesight:arm:global:{camera_id}"
    val = await r.get(key)
    if val:
        return float(val)
    return None

async def process_cross_camera_links(trigger_rule: RuleDefinition, trigger_camera_id: UUID):
    """
    After a violation on trigger_rule/camera, arm linked target cameras
    according to the MultiCameraLink directives.
    """
    if not trigger_rule.multi_camera_links:
        return
    for link in trigger_rule.multi_camera_links:
        if link.trigger_camera_id != trigger_camera_id:
            continue
        if link.action == "increase_sensitivity":
            target_camera = link.target_camera_id
            # If specific rules are given, arm each of them
            if link.rule_ids:
                for rid in link.rule_ids:
                    await arm_camera_for_rule(target_camera, rid)
            else:
                # Otherwise arm the camera globally
                await arm_camera_globally(target_camera)
        # Future actions: enable_rule, disable_rule can be added here