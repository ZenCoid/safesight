import asyncio
import logging
from api.routes.search import process_search, create_violation_and_escalate, pinned_searches
from core.live_capture import latest_frame_per_camera

logger = logging.getLogger(__name__)

_confirmation_count: dict[str, int] = {}
CONFIRMATION_THRESHOLD = 3

async def pinned_search_loop():
    frame_counter = 0
    while True:
        await asyncio.sleep(5)
        frame_counter += 1
        for sid, ps in list(pinned_searches.items()):
            if frame_counter % ps.get("interval_frames", 10) != 0:
                continue

            keys = ps.get("minio_keys", [])
            camera_id = ps.get("camera_id")
            if not keys and camera_id:
                latest = latest_frame_per_camera.get(camera_id)
                if latest:
                    keys = [latest]
            if not keys:
                continue

            for key in keys:
                logger.info(f"Running pinned search {sid} on {key} (channel: {ps.get('channel')})")
                result = await process_search(
                    query=ps["query"],
                    minio_key=key,
                    camera_id=camera_id,
                    rule_id=ps.get("rule_id"),
                    channel=ps.get("channel", "whatsapp"),
                    allow_alert=False,
                )
                present = result.get("present", False)
                confirm_key = f"{ps['query']}::{camera_id or 'static'}"

                if present:
                    cnt = _confirmation_count.get(confirm_key, 0) + 1
                    _confirmation_count[confirm_key] = cnt
                    logger.info(f"Temporal window: {confirm_key} -> {cnt}/{CONFIRMATION_THRESHOLD}")
                    if cnt >= CONFIRMATION_THRESHOLD:
                        logger.info(f"Confirmed violation for {confirm_key} – creating alert")
                        await create_violation_and_escalate(
                            query=ps["query"],
                            minio_key=key,
                            raw_answer=result.get("raw_answer", ""),
                            confidence=result.get("confidence", 0.7),
                            description=result.get("description", ""),
                            camera_id=camera_id,
                            rule_id=ps.get("rule_id"),
                            channel=ps.get("channel", "whatsapp"),
                        )
                        del _confirmation_count[confirm_key]
                else:
                    if confirm_key in _confirmation_count:
                        del _confirmation_count[confirm_key]