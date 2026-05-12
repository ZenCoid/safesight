import asyncio, logging
from api.routes.search import process_search, pinned_searches

logger = logging.getLogger(__name__)

async def pinned_search_loop():
    """Run all pinned searches periodically."""
    frame_counter = 0
    while True:
        await asyncio.sleep(5)
        frame_counter += 1
        for sid, ps in list(pinned_searches.items()):
            if frame_counter % ps.get("interval_frames", 10) != 0:
                continue
            for key in ps.get("minio_keys", []):
                logger.info(f"Running pinned search {sid} on {key} (channel: {ps.get('channel')})")
                await process_search(
                    query=ps["query"],
                    minio_key=key,
                    camera_id=ps.get("camera_id"),
                    rule_id=ps.get("rule_id"),
                    channel=ps.get("channel", "whatsapp"),
                )