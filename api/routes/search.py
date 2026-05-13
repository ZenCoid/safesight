import asyncio, logging, io, json
from pathlib import Path
from typing import Optional, List
import numpy as np
import openvino as ov
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from PIL import Image

from core.config import settings
from core.database import AsyncSessionLocal
from models.violation import ViolationEvent
from engine.escalation import escalation_state
from schemas.rule_schema import RuleDefinition
from minio import Minio

logger = logging.getLogger(__name__)
router = APIRouter()

# ------------------------------------------------------------------
# Lazy‑loaded VLM pipeline
# ------------------------------------------------------------------
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
# Alert deduplication (prevent repeated WhatsApp/email spam)
# ------------------------------------------------------------------
_alert_cache: set[str] = set()
_alert_lock = asyncio.Lock()
ALERT_COOLDOWN_SECONDS = 120

async def _can_alert(cache_key: str) -> bool:
    async with _alert_lock:
        if cache_key in _alert_cache:
            logger.info(f"⚠️ Duplicate suppressed for {cache_key}")
            return False
        _alert_cache.add(cache_key)
        loop = asyncio.get_running_loop()
        loop.call_later(ALERT_COOLDOWN_SECONDS, lambda: _alert_cache.discard(cache_key))
        return True

# ------------------------------------------------------------------
# Schemas
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

class PinnedSearchRequest(BaseModel):
    query: str
    channel: str = "whatsapp"
    interval_frames: int = 10
    minio_keys: List[str]
    rule_id: Optional[str] = None
    camera_id: Optional[str] = None

class PinnedSearchResponse(BaseModel):
    id: str
    query: str
    interval_frames: int
    channel: str

# ------------------------------------------------------------------
# Core inference + auto‑escalation
# ------------------------------------------------------------------
async def process_search(query: str, minio_key: str,
                         camera_id: Optional[str] = None,
                         rule_id: Optional[str] = None,
                         channel: str = "whatsapp") -> dict:
    """Run VLM on a single MinIO frame, auto‑create violation if present
       and channel is a real alert channel."""
    pipe = await get_pipe()
    minio_client = Minio(settings.MINIO_ENDPOINT,
                         access_key=settings.MINIO_ACCESS_KEY,
                         secret_key=settings.MINIO_SECRET_KEY,
                         secure=False)

    try:
        resp = minio_client.get_object(settings.MINIO_BUCKET, minio_key)
        frame_bytes = resp.read()
        resp.close()
        resp.release_conn()
    except Exception as e:
        logger.error(f"Failed to fetch {minio_key}: {e}")
        return {"present": False, "confidence": 0.0, "description": str(e)}

    image = Image.open(io.BytesIO(frame_bytes)).convert("RGB")
    image = image.resize((168, 168))
    image_data = np.array(image).reshape(1, 168, 168, 3).astype(np.uint8)
    image_tensor = ov.Tensor(image_data)

    prompt = f"Question: {query}\nAnswer with JSON: {{\"present\": true/false, \"confidence\": 0.0-1.0, \"description\": \"short\"}}"
    result = pipe.generate(prompt, image=image_tensor, max_new_tokens=30)
    answer = result.texts[0]

    logger.info(f"🔍 VLM answer for query='{query}' key='{minio_key}': {answer}")

    try:
        parsed = json.loads(answer)
    except Exception:
        present = "true" in answer.lower()
        parsed = {"present": present, "confidence": 0.7 if present else 0.3, "description": answer}

    logger.info(f"📊 Parsed result: present={parsed.get('present')}, confidence={parsed.get('confidence')}")

    # Only create violation + escalate if channel is a real alert channel
    if parsed.get("present", False) and channel in ("whatsapp", "email"):
        cache_key = f"{query}::{minio_key}"
        if await _can_alert(cache_key):
            logger.info("🚨 Creating violation + escalation")
            asyncio.create_task(
                _create_violation_and_escalate(
                    query=query,
                    minio_key=minio_key,
                    raw_answer=answer,
                    confidence=parsed.get("confidence", 0.7),
                    description=parsed.get("description", ""),
                    camera_id=camera_id,
                    rule_id=rule_id,
                    channel=channel,
                )
            )
        else:
            logger.info(f"⏭️ Skipping duplicate alert for {cache_key}")
    else:
        logger.info(f"✅ No violation: VLM returned present=false or channel is not alertable")

    return parsed

async def _create_violation_and_escalate(query: str, minio_key: str,
                                         raw_answer: str, confidence: float,
                                         description: str,
                                         camera_id: Optional[str],
                                         rule_id: Optional[str],
                                         channel: str):
    """Persist ViolationEvent and trigger escalation with the given channel."""
    event_id = uuid4()
    snapshot = {
        "query": query,
        "minio_key": minio_key,
        "raw_answer": raw_answer,
        "confidence": confidence,
        "description": description,
        "vlm_model": "Qwen2.5-VL-3B-Instruct-ov-int4-genai",
    }

    try:
        async with AsyncSessionLocal() as session:
            viol = ViolationEvent(
                time=datetime.now(timezone.utc),
                event_id=event_id,
                rule_id=rule_id or uuid4(),
                camera_id=camera_id or uuid4(),
                detection_snapshot=snapshot,
                severity="warning",
                acknowledged=False,
            )
            session.add(viol)
            await session.commit()
            await session.refresh(viol)
            logger.info(f"💾 ViolationEvent saved: {event_id}")
    except Exception as e:
        logger.error(f"❌ Failed to save ViolationEvent: {e}")
        return

    rule_def = RuleDefinition(
        rule_id=viol.rule_id,
        rule_name="VLM Auto‑Rule",
        version="1.0",
        enabled=True,
        cameras=[viol.camera_id],
        detection_modules=[query],
        zones=[],
        confidence_threshold=0.5,
        min_duration_seconds=0,
        cooldown_seconds=30,
        schedule=None,
        escalation_levels=[{
            "channels": [channel],
            "delay_seconds": 0,
            "unacknowledged_seconds": None
        }],
        multi_camera_links=[],
        condition=query,
    )
    try:
        await escalation_state.handle_violation_start(event_id, rule_def)
        logger.info(f"📤 Escalation triggered for {event_id} via {channel}")
    except Exception as e:
        logger.error(f"❌ Escalation failed: {e}")

# ------------------------------------------------------------------
# Immediate Search
# ------------------------------------------------------------------
@router.post("/search", response_model=SearchResponse)
async def zero_shot_search(req: SearchRequest):
    if not req.minio_keys:
        raise HTTPException(400, "At least one minio_key is required.")

    all_detections = []
    raw_answers = []

    for key in req.minio_keys:
        parsed = await process_search(
            query=req.query,
            minio_key=key,
            camera_id=req.camera_id,
            rule_id=req.rule_id,
        )
        raw_answers.append(json.dumps(parsed))
        if parsed.get("present", False):
            all_detections.append(
                SearchDetectionObject(
                    class_name=req.query,
                    confidence=parsed.get("confidence", 0.7),
                    bbox=[],
                    additional_info=parsed.get("description", ""),
                )
            )

    return SearchResponse(
        detections=all_detections,
        raw_answer="\n".join(raw_answers),
        camera_id=req.camera_id,
        rule_id=req.rule_id,
    )

# ------------------------------------------------------------------
# Pinned Search Management
# ------------------------------------------------------------------
pinned_searches: dict[str, dict] = {}

@router.post("/pinned", response_model=PinnedSearchResponse)
async def pin_search(req: PinnedSearchRequest):
    sid = str(uuid4())
    pinned_searches[sid] = {
        "id": sid,
        "query": req.query,
        "channel": req.channel,
        "interval_frames": req.interval_frames,
        "minio_keys": req.minio_keys,
        "rule_id": req.rule_id,
        "camera_id": req.camera_id,
    }
    logger.info(f"Pinned search {sid}: {req.query} every {req.interval_frames} frames via {req.channel}")
    return PinnedSearchResponse(**pinned_searches[sid])

@router.get("/pinned", response_model=List[PinnedSearchResponse])
async def list_pinned():
    return list(pinned_searches.values())

@router.delete("/pinned/{sid}")
async def unpin_search(sid: str):
    if sid in pinned_searches:
        del pinned_searches[sid]
    return {"status": "deleted"}