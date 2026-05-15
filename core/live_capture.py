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
from tasks.privacy import apply_face_blur

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

async def _run_blocking(func, *args):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, func, *args)

async def _put_minio_object(client: Minio, bucket: str, name: str, data: bytes, content_type: str):
    await _run_blocking(
        lambda: client.put_object(bucket, name, io.BytesIO(data), len(data), content_type=content_type)
    )

async def live_capture_loop():
    minio_client = Minio(
        settings.MINIO_ENDPOINT,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=False,
    )
    if not await _run_blocking(minio_client.bucket_exists, settings.MINIO_BUCKET):
        await _run_blocking(minio_client.make_bucket, settings.MINIO_BUCKET)

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
                data_to_upload = jpeg_bytes.tobytes()

                if privacy_on:
                    # Blur faces BEFORE uploading – offloaded to thread
                    data_to_upload = await asyncio.to_thread(apply_face_blur, data_to_upload)

                frame_hash = hashlib.sha256(data_to_upload).hexdigest()
                object_name = f"live/{camera_id}/{uuid4()}.jpg"

                await _put_minio_object(minio_client, settings.MINIO_BUCKET, object_name,
                                        data_to_upload, 'image/jpeg')

                async with _frame_lock:
                    latest_frame_per_camera[str(camera_id)] = object_name

                logger.debug(f"Captured frame for camera {camera_id} -> {object_name}")
            except Exception as e:
                logger.error(f"Live capture failed for camera {camera_id}: {e}")
        await asyncio.sleep(settings.LIVE_CAPTURE_INTERVAL_SECONDS)