import asyncio
import hashlib
import io
from fastapi import APIRouter, UploadFile, File, HTTPException
from minio import Minio
from core.config import settings

router = APIRouter()

async def _run_blocking(func, *args):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, func, *args)

@router.post("/upload")
async def upload_image(file: UploadFile = File(...)):
    """Upload an image to MinIO, deduplicating by content hash."""
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(400, "Only image files are allowed.")

    minio_client = Minio(
        settings.MINIO_ENDPOINT,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=False,
    )

    # Ensure bucket exists (blocking call offloaded)
    if not await _run_blocking(minio_client.bucket_exists, settings.MINIO_BUCKET):
        await _run_blocking(minio_client.make_bucket, settings.MINIO_BUCKET)

    file_bytes = await file.read()
    file_hash = hashlib.sha256(file_bytes).hexdigest()

    ext = file.filename.split('.')[-1] if '.' in file.filename else 'jpg'
    object_name = f"uploaded/{file_hash}.{ext}"

    try:
        await _run_blocking(minio_client.stat_object, settings.MINIO_BUCKET, object_name)
        return {"object_name": object_name, "already_exists": True}
    except Exception:
        pass

    try:
        await _run_blocking(
            minio_client.put_object,
            settings.MINIO_BUCKET,
            object_name,
            io.BytesIO(file_bytes),
            len(file_bytes),
        )
    except Exception as e:
        raise HTTPException(500, f"MinIO upload failed: {e}")

    return {"object_name": object_name, "already_exists": False}