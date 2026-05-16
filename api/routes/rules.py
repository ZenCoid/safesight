from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
from uuid import UUID, uuid4
import time
import asyncio
import cv2
import numpy as np
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
# Rule Simulation – real detector on MinIO frames + heatmap data
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
            "alert_frames": [],
            "message": "No frames found in MinIO warehouse."
        }

    objects.sort(key=lambda o: o.last_modified, reverse=True)
    objects = objects[:50]

    total_frames = len(objects)
    alerts_fired = 0
    alert_frames = []  # list of dicts: {frame_index, timestamp, confidence}

    detector = RFDETRDetector(settings.RFDETR_MODEL_PATH)
    evaluator = RuleEvaluator(rule_def)

    for frame_idx, obj in enumerate(objects):
        try:
            # Fetch frame bytes from MinIO (non‑blocking)
            data = minio_client.get_object(settings.MINIO_BUCKET, obj.object_name)
            frame_bytes = data.read()
            data.close()
            data.release_conn()

            np_arr = np.frombuffer(frame_bytes, np.uint8)
            frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if frame is None:
                continue

            det_event = await loop.run_in_executor(
                None, detector.predict, frame, uuid4(), 1
            )

            if await evaluator.evaluate(det_event):
                alerts_fired += 1
                # Find the max confidence among objects matching the rule's modules
                modules_lower = [m.lower() for m in rule_def.detection_modules]
                max_conf = 0.0
                for d_obj in det_event.objects:
                    if d_obj.class_name.lower() in modules_lower:
                        if d_obj.confidence > max_conf:
                            max_conf = d_obj.confidence
                alert_frames.append({
                    "frame_index": frame_idx,
                    "timestamp": obj.last_modified.isoformat(),
                    "confidence": max_conf
                })
        except Exception as e:
            logger.error(f"Simulate frame evaluation error: {e}")

    density = alerts_fired / total_frames if total_frames > 0 else 0.0

    return {
        "total_frames": total_frames,
        "alerts_fired": alerts_fired,
        "predicted_alert_density": density,
        "alert_frames": alert_frames
    }