import asyncio
import logging
import hashlib
import io
import cv2
from uuid import uuid4
from minio import Minio
import redis.asyncio as aioredis
from core.config import settings
from core.stream_manager import stream_manager
from tasks.privacy import redact_frame

logger = logging.getLogger(__name__)

latest_frame_per_camera: dict[str, str] = {}
_frame_lock = asyncio.Lock()

_privacy_redis = None

async def _get_privacy_redis():
    global _privacy_redis
    if _privacy_redis is None:
        _privacy_redis = aioredis.from_url(settings.REDIS_URL, decode_responses=False)
    return _privacy_redis

async def _is_privacy_enabled() -> bool:
    r = await _get_privacy_redis()
    val = await r.get("safesight:privacy:enabled")
    return val == b"1"

async def live_capture_loop():
    minio_client = Minio(
        settings.MINIO_ENDPOINT,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=False,
    )
    if not minio_client.bucket_exists(settings.MINIO_BUCKET):
        minio_client.make_bucket(settings.MINIO_BUCKET)

    while True:
        privacy_on = await _is_privacy_enabled()
        for camera_id, reader in stream_manager.readers.items():
            try:
                frame = None
                async for _, f in reader.get_frames():
                    frame = f
                    break
                if frame is None:
                    continue

                _, jpeg_bytes = cv2.imencode('.jpg', frame)
                frame_hash = hashlib.sha256(jpeg_bytes.tobytes()).hexdigest()
                object_name = f"live/{camera_id}/{uuid4()}.jpg"

                minio_client.put_object(
                    settings.MINIO_BUCKET,
                    object_name,
                    io.BytesIO(jpeg_bytes.tobytes()),
                    length=len(jpeg_bytes.tobytes()),
                    content_type='image/jpeg',
                )

                async with _frame_lock:
                    latest_frame_per_camera[str(camera_id)] = object_name

                # Trigger background face redaction if privacy is enabled
                if privacy_on:
                    redact_frame.delay(object_name)
                    logger.debug(f"Dispatched redaction for {object_name}")

                logger.debug(f"Captured frame for camera {camera_id} -> {object_name}")
            except Exception as e:
                logger.error(f"Live capture failed for camera {camera_id}: {e}")
        await asyncio.sleep(settings.LIVE_CAPTURE_INTERVAL_SECONDS)