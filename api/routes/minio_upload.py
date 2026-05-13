from fastapi import APIRouter, UploadFile, File, HTTPException
from minio import Minio
from core.config import settings
import uuid

router = APIRouter()

@router.post("/upload")
async def upload_image(file: UploadFile = File(...)):
    """Upload an image to MinIO and return its object key."""
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(400, "Only image files are allowed.")

    minio_client = Minio(
        settings.MINIO_ENDPOINT,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=False,
    )

    if not minio_client.bucket_exists(settings.MINIO_BUCKET):
        minio_client.make_bucket(settings.MINIO_BUCKET)

    ext = file.filename.split('.')[-1] if '.' in file.filename else 'jpg'
    object_name = f"uploaded/{uuid.uuid4()}.{ext}"

    try:
        minio_client.put_object(
            settings.MINIO_BUCKET,
            object_name,
            file.file,
            length=-1,
            part_size=10 * 1024 * 1024,
            content_type=file.content_type,
        )
    except Exception as e:
        raise HTTPException(500, f"MinIO upload failed: {e}")

    return {"object_name": object_name}