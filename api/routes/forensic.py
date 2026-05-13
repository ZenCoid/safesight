import io, json, logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List
from minio import Minio
from PIL import Image
import numpy as np
import openvino as ov

from core.config import settings
from api.routes.search import get_pipe

logger = logging.getLogger(__name__)
router = APIRouter()

class ForensicRequest(BaseModel):
    query: str
    max_frames: int = 10
    show_all: bool = False          # optional – set to true to see non‑matches too

class ForensicResult(BaseModel):
    minio_key: str
    thumbnail_url: str
    vlm_reasoning: str
    timestamp: str
    present: bool

class ForensicResponse(BaseModel):
    results: List[ForensicResult]

@router.post("/forensic/search", response_model=ForensicResponse)
async def forensic_search(req: ForensicRequest):
    pipe = await get_pipe()
    minio_client = Minio(
        settings.MINIO_ENDPOINT,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=False,
    )
    objects = list(minio_client.list_objects(settings.MINIO_BUCKET, recursive=True))
    objects = sorted(objects, key=lambda o: o.last_modified, reverse=True)[:req.max_frames]

    results = []
    for obj in objects:
        # Fetch image
        try:
            resp = minio_client.get_object(settings.MINIO_BUCKET, obj.object_name)
            frame_bytes = resp.read()
            resp.close()
            resp.release_conn()
        except Exception as e:
            logger.error(f"Failed to fetch {obj.object_name}: {e}")
            continue

        # Preprocess image
        image = Image.open(io.BytesIO(frame_bytes)).convert("RGB")
        image = image.resize((168, 168))
        image_data = np.array(image).reshape(1, 168, 168, 3).astype(np.uint8)
        image_tensor = ov.Tensor(image_data)

        # Prompt for forensic search
        prompt = (
            f"Question: {req.query}\n"
            "Look at the image and answer with a JSON object. "
            "If the answer is yes, set 'present' to true and 'description' to a short summary. "
            "If the answer is no, set 'present' to false and 'description' to a short explanation of what you actually see."
            'Format: {"present": true/false, "confidence": 0.0-1.0, "description": "short string"}'
        )
        result = pipe.generate(prompt, image=image_tensor, max_new_tokens=40)
        answer = result.texts[0]

        try:
            parsed = json.loads(answer)
        except Exception:
            parsed = {"present": False, "confidence": 0.0, "description": "Could not parse response"}

        # Skip non‑matches unless show_all is requested
        if not parsed.get("present", False) and not req.show_all:
            continue

        # Presigned URL for thumbnail
        try:
            thumb_url = minio_client.presigned_get_object(settings.MINIO_BUCKET, obj.object_name)
        except:
            thumb_url = ""

        results.append(ForensicResult(
            minio_key=obj.object_name,
            thumbnail_url=thumb_url,
            vlm_reasoning=parsed.get("description", "No details"),
            timestamp=obj.last_modified.isoformat(),
            present=parsed.get("present", False),
        ))

    return ForensicResponse(results=results)