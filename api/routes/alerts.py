from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
from uuid import UUID
import uuid
from datetime import datetime, timezone

from models.alert import Alert
from models.violation import ViolationEvent
from models.rule import Rule
from schemas.alert import AlertRead
from schemas.rule_schema import RuleDefinition
from core.database import AsyncSessionLocal
from core.celery_app import celery_app
from engine.escalation import escalation_state

router = APIRouter()

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

@router.get("/", response_model=List[AlertRead])
async def list_alerts(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Alert).order_by(Alert.created_at.desc()).limit(100))
    alerts = result.scalars().all()
    return alerts

@router.post("/{alert_id}/acknowledge", response_model=AlertRead)
async def acknowledge_alert(alert_id: UUID, db: AsyncSession = Depends(get_db)):
    alert = await db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    viol = await db.get(ViolationEvent, alert.violation_event_id)
    if viol:
        viol.acknowledged = True
        await db.commit()
        await db.refresh(viol)
        # Notify escalation engine to stop timers and fire remaining levels
        await escalation_state.handle_violation_end(viol.event_id)

    alert.sent = True
    await db.commit()
    await db.refresh(alert)
    return alert


@router.post("/test-violation/{rule_id}", summary="Manually trigger a violation (for testing)")
async def trigger_test_violation(rule_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Rule).where(Rule.id == rule_id))
    rule_row = result.scalar_one_or_none()
    if not rule_row:
        raise HTTPException(status_code=404, detail="Rule not found")
    rule_def = RuleDefinition(**rule_row.definition)

    camera_id = rule_def.cameras[0] if rule_def.cameras else uuid.uuid4()

    fake_snapshot = {
        "camera_id": str(camera_id),
        "frame_id": 1,
        "timestamp": datetime.now(timezone.utc).timestamp(),
        "objects": [
            {"class_name": "person", "confidence": 0.95, "bbox": [0.3, 0.4, 0.6, 0.9]},
            {"class_name": "no-helmet", "confidence": 0.88, "bbox": [0.3, 0.4, 0.6, 0.9]}
        ],
        "raw_confidence_distribution": {}
    }

    violation = ViolationEvent(
        time=datetime.now(timezone.utc),
        event_id=uuid.uuid4(),
        rule_id=rule_id,
        camera_id=camera_id,
        detection_snapshot=fake_snapshot,
        severity="warning",
        acknowledged=False,
        clip_path=None
    )
    db.add(violation)
    await db.commit()
    await db.refresh(violation)

    alert_channels = rule_def.escalation_levels[0].channels if rule_def.escalation_levels else ["whatsapp"]
    for channel in alert_channels:
        alert = Alert(
            violation_event_id=violation.event_id,
            camera_id=camera_id,
            escalation_level=1,
            channel=channel,
            sent=False
        )
        db.add(alert)
    await db.commit()

    for channel in alert_channels:
        celery_app.send_task("tasks.alerting.send_alert", args=[str(violation.event_id), channel, 1])

    await escalation_state.handle_violation_start(violation.event_id, rule_def)

    return {
        "message": "Test violation created",
        "violation_event_id": str(violation.event_id),
        "rule_id": str(rule_id),
        "channels_triggered": alert_channels
    }