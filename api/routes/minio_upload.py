import hashlib
from fastapi import APIRouter, UploadFile, File, HTTPException
from minio import Minio
from core.config import settings

router = APIRouter()

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

    # Create bucket if not present
    if not minio_client.bucket_exists(settings.MINIO_BUCKET):
        minio_client.make_bucket(settings.MINIO_BUCKET)

    # Read file bytes and compute SHA‑256 hash
    file_bytes = await file.read()
    file_hash = hashlib.sha256(file_bytes).hexdigest()

    # Determine extension (default to jpg)
    ext = file.filename.split('.')[-1] if '.' in file.filename else 'jpg'
    object_name = f"uploaded/{file_hash}.{ext}"

    # If object already exists, just return its name (no duplicate)
    try:
        minio_client.stat_object(settings.MINIO_BUCKET, object_name)
        return {"object_name": object_name, "already_exists": True}
    except Exception:
        # Object doesn't exist – upload it
        pass

    try:
        minio_client.put_object(
            settings.MINIO_BUCKET,
            object_name,
            io.BytesIO(file_bytes),
            length=len(file_bytes),
            part_size=10 * 1024 * 1024,
            content_type=file.content_type,
        )
    except Exception as e:
        raise HTTPException(500, f"MinIO upload failed: {e}")

    return {"object_name": object_name, "already_exists": False}