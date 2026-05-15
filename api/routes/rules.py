from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
from uuid import UUID, uuid4
import time
import asyncio
from minio import Minio
from core.config import settings
from models.rule import Rule
from schemas.rule_schema import RuleDefinition
from engine.rule_evaluator import RuleEvaluator
from core.database import AsyncSessionLocal
from ingestion.detector import RFDETRDetector

import logging
logger = logging.getLogger(__name__)

router = APIRouter()

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

@router.post("/", response_model=RuleDefinition, status_code=201)
async def create_rule(rule_def: RuleDefinition, db: AsyncSession = Depends(get_db)):
    db_rule = Rule(
        id=rule_def.rule_id,
        name=rule_def.rule_name,
        version=rule_def.version,
        enabled=rule_def.enabled,
        definition=rule_def.model_dump(mode='json')
    )
    db.add(db_rule)
    await db.commit()
    await db.refresh(db_rule)
    return RuleDefinition(**db_rule.definition)

@router.get("/", response_model=List[RuleDefinition])
async def list_rules(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Rule))
    rules = result.scalars().all()
    return [RuleDefinition(**r.definition) for r in rules]

@router.get("/{rule_id}", response_model=RuleDefinition)
async def get_rule(rule_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Rule).where(Rule.id == rule_id))
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    return RuleDefinition(**rule.definition)

@router.put("/{rule_id}", response_model=RuleDefinition)
async def update_rule(rule_id: UUID, rule_def: RuleDefinition, db: AsyncSession = Depends(get_db)):
    rule = await db.get(Rule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    rule.name = rule_def.rule_name
    rule.version = rule_def.version
    rule.enabled = rule_def.enabled
    rule.definition = rule_def.model_dump(mode='json')
    await db.commit()
    await db.refresh(rule)
    return RuleDefinition(**rule.definition)

@router.delete("/{rule_id}", status_code=204)
async def delete_rule(rule_id: UUID, db: AsyncSession = Depends(get_db)):
    rule = await db.get(Rule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    await db.delete(rule)
    await db.commit()
    return

# ------------------------------------------------------------------
# Rule Simulation – real detector on MinIO frames
# ------------------------------------------------------------------
@router.post("/simulate", summary="Simulate a rule against recent MinIO frames")
async def simulate_rule(rule_def: RuleDefinition):
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

    if not objects:
        return {
            "total_frames": 0,
            "alerts_fired": 0,
            "predicted_alert_density": 0.0,
            "message": "No frames found in MinIO warehouse."
        }

    objects.sort(key=lambda o: o.last_modified, reverse=True)
    objects = objects[:50]

    total_frames = len(objects)
    alerts_fired = 0

    # Use the real RF‑DETR detector (stub returns empty detections for now)
    detector = RFDETRDetector(settings.RFDETR_MODEL_PATH)
    evaluator = RuleEvaluator(rule_def)

    for obj in objects:
        try:
            # Fetch frame bytes from MinIO (non‑blocking)
            data = minio_client.get_object(settings.MINIO_BUCKET, obj.object_name)
            frame_bytes = data.read()
            data.close()
            data.release_conn()

            # Decode to OpenCV image
            np_arr = np.frombuffer(frame_bytes, np.uint8)
            frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if frame is None:
                continue

            # Run real detector (offloaded to thread)
            det_event = await loop.run_in_executor(
                None, detector.predict, frame, uuid4(), 1
            )

            if evaluator.evaluate(det_event):
                alerts_fired += 1
        except Exception as e:
            logger.error(f"Simulate frame evaluation error: {e}")

    density = alerts_fired / total_frames if total_frames > 0 else 0.0

    return {
        "total_frames": total_frames,
        "alerts_fired": alerts_fired,
        "predicted_alert_density": density,
    }