import io
import json
import logging
import hashlib
import re
import asyncio
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional
from minio import Minio
from PIL import Image
import numpy as np
import openvino as ov
from api.routes.search import get_pipe, _get_minio_object
from api.ws.live import increment_hash_count   # new import

logger = logging.getLogger(__name__)
router = APIRouter()

class ForensicRequest(BaseModel):
    query: str = Field(..., max_length=500)
    max_frames: int = 10
    show_all: bool = False
    use_video_panels: bool = False   # optional flag to force panel mode

    @field_validator('query')
    @classmethod
    def sanitize_query(cls, v):
        forbidden = ['__', 'exec(', 'import ', 'subprocess', 'os.', 'sys.']
        lower = v.lower()
        for token in forbidden:
            if token in lower:
                raise ValueError(f'Query contains forbidden pattern: {token}')
        if not re.match(r'^[\w\s\-_.,!?\'\"@#$%^&*()+=:;<>\[\]{}|\\/~`]+$', v):
            raise ValueError('Query contains invalid characters')
        return v

class ForensicResult(BaseModel):
    minio_key: str
    thumbnail_url: str
    vlm_reasoning: str
    timestamp: str
    present: bool
    confidence: float = 0.0
    image_hash: str = ""

class ForensicResponse(BaseModel):
    results: List[ForensicResult]
    composite_used: bool = False

@router.post("/forensic/search", response_model=ForensicResponse)
async def forensic_search(req: ForensicRequest):
    pipe = await get_pipe()
    minio_client = Minio(
        settings.MINIO_ENDPOINT,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=False,
    )
    loop = asyncio.get_running_loop()
    max_list = 2000
    objects = []
    for idx, obj in enumerate(await loop.run_in_executor(
        None, lambda: list(minio_client.list_objects(settings.MINIO_BUCKET, recursive=True))
    )):
        objects.append(obj)
        if idx >= max_list:
            break
    objects.sort(key=lambda o: o.last_modified, reverse=True)
    results = []
    composite_used = False

    # Video Paneling: if not show_all and at least 4 frames, composite a 2x2 grid
    if not req.show_all and len(objects) >= 4 and not req.use_video_panels:
        # Use the 4 most recent frames
        frames = []
        panel_objects = objects[:4]
        for obj in panel_objects:
            try:
                fb = await _get_minio_object(minio_client, settings.MINIO_BUCKET, obj.object_name)
            except Exception:
                continue
            im = Image.open(io.BytesIO(fb)).convert("RGB").resize((84, 84))
            frames.append(im)
        if len(frames) == 4:
            canvas = Image.new("RGB", (168, 168))
            canvas.paste(frames[0], (0, 0))
            canvas.paste(frames[1], (84, 0))
            canvas.paste(frames[2], (0, 84))
            canvas.paste(frames[3], (84, 84))
            image_data = np.array(canvas).reshape(1, 168, 168, 3).astype(np.uint8)
            image_tensor = ov.Tensor(image_data)

            prompt = (
                f"Question: {req.query}\n"
                "You are an AI surveillance operator. Look at the image and answer with a JSON object.\n"
                "Focus on Human‑Object Interactions: Violence (weapons, fighting), Property (theft, vandalism), "
                "Public Safety (crowd, fire, accidents).\n"
                "If the described event is present, set 'present' to true and 'description' to a precise summary.\n"
                "If not, set 'present' to false and 'description' to what you actually see.\n"
                'Format: {"present": true/false, "confidence": 0.0-1.0, "description": "short string"}'
            )
            result = pipe.generate(prompt, image=image_tensor, max_new_tokens=40)
            answer = result.texts[0]

            try:
                parsed = json.loads(answer)
            except Exception:
                parsed = {"present": False, "confidence": 0.0, "description": "Could not parse response"}

            # Compute hash over the composite image (just for the result)
            composite_bytes = canvas.tobytes()
            image_hash = hashlib.sha256(composite_bytes).hexdigest()
            increment_hash_count()

            thumb_url = ""
            try:
                # Use the latest frame's thumbnail as representative
                thumb_url = await loop.run_in_executor(
                    None, minio_client.presigned_get_object, settings.MINIO_BUCKET, panel_objects[0].object_name
                )
            except:
                pass

            results.append(ForensicResult(
                minio_key="composite::" + panel_objects[0].object_name,
                thumbnail_url=thumb_url,
                vlm_reasoning=parsed.get("description", "No details"),
                timestamp=panel_objects[0].last_modified.isoformat(),
                present=parsed.get("present", False),
                confidence=parsed.get("confidence", 0.0),
                image_hash=image_hash,
            ))
            composite_used = True
    else:
        # Standard single‑frame search
        objects = objects[:req.max_frames]
        for obj in objects:
            try:
                frame_bytes = await _get_minio_object(minio_client, settings.MINIO_BUCKET, obj.object_name)
            except Exception:
                continue

            image_hash = hashlib.sha256(frame_bytes).hexdigest()
            increment_hash_count()

            image = Image.open(io.BytesIO(frame_bytes)).convert("RGB")
            image = image.resize((168, 168))
            image_data = np.array(image).reshape(1, 168, 168, 3).astype(np.uint8)
            image_tensor = ov.Tensor(image_data)

            prompt = (
                f"Question: {req.query}\n"
                "You are an AI surveillance operator. Look at the image and answer with a JSON object.\n"
                "Focus on Human‑Object Interactions: Violence (weapons, fighting), Property (theft, vandalism), "
                "Public Safety (crowd, fire, accidents).\n"
                "If the described event is present, set 'present' to true and 'description' to a precise summary.\n"
                "If not, set 'present' to false and 'description' to what you actually see.\n"
                'Format: {"present": true/false, "confidence": 0.0-1.0, "description": "short string"}'
            )
            result = pipe.generate(prompt, image=image_tensor, max_new_tokens=40)
            answer = result.texts[0]

            try:
                parsed = json.loads(answer)
            except Exception:
                parsed = {"present": False, "confidence": 0.0, "description": "Could not parse response"}

            if not parsed.get("present", False) and not req.show_all:
                continue

            try:
                thumb_url = await loop.run_in_executor(
                    None, minio_client.presigned_get_object, settings.MINIO_BUCKET, obj.object_name
                )
            except:
                thumb_url = ""

            results.append(ForensicResult(
                minio_key=obj.object_name,
                thumbnail_url=thumb_url,
                vlm_reasoning=parsed.get("description", "No details"),
                timestamp=obj.last_modified.isoformat(),
                present=parsed.get("present", False),
                confidence=parsed.get("confidence", 0.0),
                image_hash=image_hash,
            ))

    return ForensicResponse(results=results, composite_used=composite_used)