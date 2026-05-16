from fastapi import APIRouter, HTTPException, Query
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import select, and_
from models.violation import ViolationEvent
from core.database import AsyncSessionLocal
import uuid

router = APIRouter()

@router.get("/reports/compliance")
async def compliance_report(
    start_time: datetime = Query(..., description="Start time (ISO 8601)"),
    end_time: datetime = Query(..., description="End time (ISO 8601)"),
    camera_id: Optional[str] = None,
    rule_id: Optional[str] = None
):
    async with AsyncSessionLocal() as session:
        conditions = [ViolationEvent.time >= start_time, ViolationEvent.time <= end_time]
        if camera_id:
            try:
                cam_uuid = uuid.UUID(camera_id)
                conditions.append(ViolationEvent.camera_id == cam_uuid)
            except ValueError:
                raise HTTPException(status_code=400, detail="camera_id must be a valid UUID")
        if rule_id:
            try:
                rule_uuid = uuid.UUID(rule_id)
                conditions.append(ViolationEvent.rule_id == rule_uuid)
            except ValueError:
                raise HTTPException(status_code=400, detail="rule_id must be a valid UUID")

        stmt = select(ViolationEvent).where(and_(*conditions)).order_by(ViolationEvent.time)
        result = await session.execute(stmt)
        events = result.scalars().all()

        report_entries = []
        for ev in events:
            snapshot = ev.detection_snapshot or {}
            entry = {
                "event_id": str(ev.event_id),
                "timestamp": ev.time.isoformat(),
                "camera_id": str(ev.camera_id),
                "rule_id": str(ev.rule_id),
                "severity": ev.severity,
                "acknowledged": ev.acknowledged,
                "chain_of_custody": {
                    "sha256_hash": snapshot.get("image_hash", ""),
                    "vlm_reasoning": snapshot.get("description", ""),
                    "vlm_model": snapshot.get("vlm_model", "unknown"),
                    "confidence": snapshot.get("confidence", 0.0),
                    "snapshot": snapshot
                }
            }
            report_entries.append(entry)

        return {
            "report_generated_at": datetime.now(timezone.utc).isoformat(),
            "time_range": {
                "start": start_time.isoformat(),
                "end": end_time.isoformat()
            },
            "total_events": len(report_entries),
            "events": report_entries
        }