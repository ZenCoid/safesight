from fastapi import APIRouter, HTTPException, Query
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import select, and_
from models.violation import ViolationEvent
from core.database import AsyncSessionLocal
import json

router = APIRouter()

@router.get("/reports/compliance")
async def compliance_report(
    start_time: datetime = Query(..., description="Start time (ISO 8601)"),
    end_time: datetime = Query(..., description="End time (ISO 8601)"),
    camera_id: Optional[str] = None,
    rule_id: Optional[str] = None
):
    """
    Generate a compliance report listing all ViolationEvents within the given time range.
    Each entry includes the SHA‑256 image hash and VLM reasoning for tamper‑proof chain of custody.
    """
    async with AsyncSessionLocal() as session:
        conditions = [ViolationEvent.time >= start_time, ViolationEvent.time <= end_time]
        if camera_id:
            conditions.append(ViolationEvent.camera_id == camera_id)
        if rule_id:
            conditions.append(ViolationEvent.rule_id == rule_id)

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
                    "snapshot": snapshot   # full detection snapshot for audit
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