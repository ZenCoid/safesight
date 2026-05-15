import asyncio
import logging
import io
import json
import hashlib
import os
import re
from pathlib import Path
from typing import Optional, List
import numpy as np
import openvino as ov
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from PIL import Image

from core.config import settings
from core.database import AsyncSessionLocal
from models.violation import ViolationEvent
from engine.escalation import escalation_state
from schemas.rule_schema import RuleDefinition
from minio import Minio

logger = logging.getLogger(__name__)
router = APIRouter()

MODEL_PATH = Path(settings.MODEL_SEARCH_PATH).resolve()
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

# Schemas (same as before, omitted for brevity but unchanged)
class SearchRequest(BaseModel):
    query: str = Field(..., max_length=500)
    minio_keys: List[str]
    camera_id: Optional[str] = None
    rule_id: Optional[str] = None

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
    query: str = Field(..., max_length=500)
    channel: str = "whatsapp"
    interval_frames: int = 10
    minio_keys: List[str]
    rule_id: Optional[str] = None
    camera_id: Optional[str] = None

    @field_validator('query')
    @classmethod
    def sanitize_pinned_query(cls, v):
        forbidden = ['__', 'exec(', 'import ', 'subprocess', 'os.', 'sys.']
        lower = v.lower()
        for token in forbidden:
            if token in lower:
                raise ValueError(f'Query contains forbidden pattern: {token}')
        if not re.match(r'^[\w\s\-_.,!?\'\"@#$%^&*()+=:;<>\[\]{}|\\/~`]+$', v):
            raise ValueError('Query contains invalid characters')
        return v

class PinnedSearchResponse(BaseModel):
    id: str
    query: str
    interval_frames: int
    channel: str

# ------------------------------------------------------------------
# Single frame processing (used for immediate search)
# ------------------------------------------------------------------
async def process_search(query: str, minio_key: str,
                         camera_id: Optional[str] = None,
                         rule_id: Optional[str] = None,
                         channel: str = "whatsapp",
                         allow_alert: bool = True) -> dict:
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
        return {"present": False, "confidence": 0.0, "description": str(e), "raw_answer": ""}

    image_hash = hashlib.sha256(frame_bytes).hexdigest()

    image = Image.open(io.BytesIO(frame_bytes)).convert("RGB")
    image_resized = image.resize((168, 168))
    image_data = np.array(image_resized).reshape(1, 168, 168, 3).astype(np.uint8)
    image_tensor = ov.Tensor(image_data)

    prompt = (
        f"Question: {query}\n"
        "You are an AI surveillance operator. Look at the image and answer with a JSON object.\n"
        "Focus on Human‑Object Interactions: Violence (weapons, fighting), Property (theft, vandalism), "
        "Public Safety (crowd, fire, accidents).\n"
        "If the described event is present, set 'present' to true and 'description' to a precise summary.\n"
        "If not, set 'present' to false and 'description' to what you actually see.\n"
        'Format: {"present": true/false, "confidence": 0.0-1.0, "description": "short string"}'
    )
    result = pipe.generate(prompt, image=image_tensor, max_new_tokens=40)
    answer = result.texts[0]

    logger.info(f"🔍 VLM answer for query='{query}' key='{minio_key}': {answer}")

    try:
        parsed = json.loads(answer)
    except Exception:
        present = "true" in answer.lower()
        parsed = {"present": present, "confidence": 0.7 if present else 0.3, "description": answer}

    logger.info(f"📊 Parsed result: present={parsed.get('present')}, confidence={parsed.get('confidence')}")

    present = parsed.get("present", False)
    description = parsed.get("description", "")
    confidence = parsed.get("confidence", 0.7)

    if present and channel in ("whatsapp", "email") and allow_alert:
        cache_key = f"{query}::{minio_key}"
        if await _can_alert(cache_key):
            logger.info("🚨 Creating violation + escalation")
            asyncio.create_task(
                create_violation_and_escalate(
                    query=query,
                    minio_key=minio_key,
                    raw_answer=answer,
                    confidence=confidence,
                    description=description,
                    camera_id=camera_id,
                    rule_id=rule_id,
                    channel=channel,
                    image_hash=image_hash,
                )
            )
        else:
            logger.info(f"⏭️ Skipping duplicate alert for {cache_key}")
    else:
        logger.info("✅ No violation or alerting disabled")

    return {"present": present, "confidence": confidence, "description": description, "raw_answer": answer}

# ------------------------------------------------------------------
# Composite 2x2 video panel (always used for pinned searches)
# ------------------------------------------------------------------
async def process_composite_search(query: str, camera_id: str, channel: str = "whatsapp") -> dict:
    pipe = await get_pipe()
    minio_client = Minio(settings.MINIO_ENDPOINT,
                         access_key=settings.MINIO_ACCESS_KEY,
                         secret_key=settings.MINIO_SECRET_KEY,
                         secure=False)
    prefix = f"live/{camera_id}/"
    objects = list(minio_client.list_objects(settings.MINIO_BUCKET, prefix=prefix, recursive=True))
    if len(objects) < 4:
        latest = max(objects, key=lambda o: o.last_modified) if objects else None
        if not latest:
            return {"present": False, "confidence": 0.0, "description": "No frames available"}
        resp = minio_client.get_object(settings.MINIO_BUCKET, latest.object_name)
        frame_bytes = resp.read()
        resp.close()
        resp.release_conn()
        image = Image.open(io.BytesIO(frame_bytes)).convert("RGB").resize((168, 168))
    else:
        objects.sort(key=lambda o: o.last_modified, reverse=True)
        frames = []
        for obj in objects[:4]:
            resp = minio_client.get_object(settings.MINIO_BUCKET, obj.object_name)
            fb = resp.read()
            resp.close()
            resp.release_conn()
            im = Image.open(io.BytesIO(fb)).convert("RGB").resize((84, 84))
            frames.append(im)
        canvas = Image.new("RGB", (168, 168))
        canvas.paste(frames[0], (0, 0))
        canvas.paste(frames[1], (84, 0))
        canvas.paste(frames[2], (0, 84))
        canvas.paste(frames[3], (84, 84))
        image = canvas

    image_data = np.array(image).reshape(1, 168, 168, 3).astype(np.uint8)
    image_tensor = ov.Tensor(image_data)

    prompt = (
        f"Question: {query}\n"
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
    except:
        present = "true" in answer.lower()
        parsed = {"present": present, "confidence": 0.7 if present else 0.3, "description": answer}

    present = parsed.get("present", False)
    description = parsed.get("description", "")
    confidence = parsed.get("confidence", 0.7)

    if present and channel in ("whatsapp", "email"):
        if await _can_alert(f"{query}::composite::{camera_id}"):
            asyncio.create_task(
                create_violation_and_escalate(
                    query=query,
                    minio_key=objects[0].object_name if objects else "composite",
                    raw_answer=answer,
                    confidence=confidence,
                    description=description,
                    camera_id=camera_id,
                    rule_id=None,
                    channel=channel,
                    image_hash="",
                )
            )

    return {"present": present, "confidence": confidence, "description": description, "raw_answer": answer}

# ------------------------------------------------------------------
# Violation creation (with privacy redact if enabled)
# ------------------------------------------------------------------
async def create_violation_and_escalate(query: str, minio_key: str,
                                         raw_answer: str, confidence: float,
                                         description: str,
                                         camera_id: Optional[str],
                                         rule_id: Optional[str],
                                         channel: str,
                                         image_hash: str = ""):
    event_id = uuid4()
    snapshot = {
        "query": query,
        "minio_key": minio_key,
        "raw_answer": raw_answer,
        "confidence": confidence,
        "description": description,
        "vlm_model": "Qwen2.5-VL-3B-Instruct-ov-int4-genai",
        "image_hash": image_hash,
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

    # Sovereign Training Pool (with privacy check)
    try:
        training_dir = Path(settings.TRAINING_POOL_DIR)
        training_dir.mkdir(parents=True, exist_ok=True)
        minio_client = Minio(settings.MINIO_ENDPOINT,
                             access_key=settings.MINIO_ACCESS_KEY,
                             secret_key=settings.MINIO_SECRET_KEY,
                             secure=False)
        resp = minio_client.get_object(settings.MINIO_BUCKET, minio_key)
        frame_bytes = resp.read()
        resp.close()
        resp.release_conn()
        # Check privacy flag
        from redis import Redis
        r = Redis.from_url(settings.REDIS_URL)
        if r.get("safesight:privacy:enabled") == b"1":
            from tasks.privacy import apply_face_blur
            frame_bytes = apply_face_blur(frame_bytes)
        img_path = training_dir / f"{event_id}.jpg"
        img_path.write_bytes(frame_bytes)
        label_path = training_dir / f"{event_id}.txt"
        label_path.write_text(f"query: {query}\nvlm_reasoning: {description}\nconfidence: {confidence}\nimage_hash: {image_hash}\n")
        logger.info(f"📁 Training sample saved to {training_dir}")
    except Exception as e:
        logger.error(f"❌ Training pool save failed: {e}")

    # Escalation
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
# Immediate Search endpoint
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