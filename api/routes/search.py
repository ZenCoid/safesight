import asyncio, logging, io, json
from pathlib import Path
from typing import Optional, List
import numpy as np
import openvino as ov
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from PIL import Image
from core.config import settings
from minio import Minio

logger = logging.getLogger(__name__)
router = APIRouter()

MODEL_PATH = Path("E:/safesight/models/qwen-3b-int4-genai").resolve()
DEVICE = "CPU"

_pipe = None
_lock = asyncio.Lock()

async def get_pipe():
    global _pipe
    async with _lock:
        if _pipe is None:
            logger.info(f"Loading VLMPipeline from {MODEL_PATH} …")
            import openvino_genai as ov_genai
            _pipe = ov_genai.VLMPipeline(str(MODEL_PATH), DEVICE)
            logger.info("✅ Pipeline loaded.")
    return _pipe

# ------------------------------------------------------------------
class SearchRequest(BaseModel):
    query: str
    minio_keys: List[str]
    camera_id: Optional[str] = None
    rule_id: Optional[str] = None

class SearchDetectionObject(BaseModel):
    class_name: str
    confidence: float
    bbox: List[float] = []
    additional_info: Optional[str] = None

class SearchResponse(BaseModel):
    detections: List[SearchDetectionObject]
    raw_answer: str
    camera_id: Optional[str] = None
    rule_id: Optional[str] = None

# ------------------------------------------------------------------
@router.post("/search", response_model=SearchResponse)
async def zero_shot_search(req: SearchRequest):
    if not req.minio_keys:
        raise HTTPException(400, "At least one minio_key is required.")
    pipe = await get_pipe()
    minio_client = Minio(settings.MINIO_ENDPOINT, access_key=settings.MINIO_ACCESS_KEY,
                         secret_key=settings.MINIO_SECRET_KEY, secure=False)

    all_detections, raw_answers = [], []
    for key in req.minio_keys:
        try:
            resp = minio_client.get_object(settings.MINIO_BUCKET, key)
            frame_bytes = resp.read()
            resp.close(); resp.release_conn()
        except Exception as e:
            logger.error(f"MinIO fetch failed: {e}")
            continue

        image = Image.open(io.BytesIO(frame_bytes)).convert("RGB")
        # Resize to safe limits (recommended by model card)
        image = image.resize((336, 336))
        image_data = np.array(image).reshape(1, 336, 336, 3).astype(np.uint8)
        image_tensor = ov.Tensor(image_data)

        prompt = (
            f"{req.query}\n"
            "Answer ONLY with a valid JSON object. No extra text.\n"
            'Format: {"present": true/false, "confidence": 0.0-1.0, "description": "short description"}'
        )
        result = pipe.generate(prompt, image=image_tensor, max_new_tokens=100)
        answer = result.texts[0]
        raw_answers.append(answer)

        try:
            parsed = json.loads(answer)
            present = bool(parsed.get("present", False))
            confidence = float(parsed.get("confidence", 0.7))
            description = parsed.get("description", "")
        except Exception:
            present = "true" in answer.lower()
            confidence = 0.7
            description = answer

        if present:
            all_detections.append(SearchDetectionObject(
                class_name=req.query, confidence=confidence,
                bbox=[], additional_info=description,
            ))

    return SearchResponse(detections=all_detections, raw_answer="\n".join(raw_answers),
                          camera_id=req.camera_id, rule_id=req.rule_id)