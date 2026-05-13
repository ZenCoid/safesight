from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List
from minio import Minio
from core.config import settings
from api.routes.search import process_search  # reuse our VLM caller
import asyncio

router = APIRouter()

class ForensicRequest(BaseModel):
    query: str
    max_frames: int = 10

class ForensicResult(BaseModel):
    minio_key: str
    thumbnail_url: str
    vlm_reasoning: str
    timestamp: str

class ForensicResponse(BaseModel):
    results: List[ForensicResult]

@router.post("/forensic/search", response_model=ForensicResponse)
async def forensic_search(req: ForensicRequest):
    minio_client = Minio(
        settings.MINIO_ENDPOINT,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=False,
    )
    objects = list(minio_client.list_objects(settings.MINIO_BUCKET, recursive=True))
    # Take the most recent frames up to max_frames
    objects = sorted(objects, key=lambda o: o.last_modified, reverse=True)[:req.max_frames]

    results = []
    for obj in objects:
        # Run VLM
        parsed = await process_search(
            query=req.query,
            minio_key=obj.object_name,
            channel="none"  # we don't want alerts during forensic search
        )
        # Get a presigned URL for the thumbnail (valid for 1 hour)
        try:
            thumb_url = minio_client.presigned_get_object(settings.MINIO_BUCKET, obj.object_name)
        except:
            thumb_url = ""
        results.append(ForensicResult(
            minio_key=obj.object_name,
            thumbnail_url=thumb_url,
            vlm_reasoning=parsed.get("description", "No details"),
            timestamp=obj.last_modified.isoformat()
        ))
    return ForensicResponse(results=results)