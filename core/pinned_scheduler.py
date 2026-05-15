import asyncio
import logging
from api.routes.search import process_composite_search, pinned_searches

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

            camera_id = ps.get("camera_id")
            if not camera_id:
                continue

            logger.info(f"Running composite pinned search {sid} for camera {camera_id}")
            result = await process_composite_search(
                query=ps["query"],
                camera_id=str(camera_id),
                channel=ps.get("channel", "whatsapp"),
            )
            present = result.get("present", False)
            confirm_key = f"{ps['query']}::{camera_id}"

            if present:
                cnt = _confirmation_count.get(confirm_key, 0) + 1
                _confirmation_count[confirm_key] = cnt
                logger.info(f"Temporal window: {confirm_key} -> {cnt}/{CONFIRMATION_THRESHOLD}")
                if cnt >= CONFIRMATION_THRESHOLD:
                    logger.info(f"Confirmed violation for {confirm_key} – creating alert")
                    # Already escalated inside process_composite_search
                    del _confirmation_count[confirm_key]
            else:
                if confirm_key in _confirmation_count:
                    del _confirmation_count[confirm_key]