from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
from models.alert import Alert
from schemas.alert import AlertRead  # we'll define
from core.database import AsyncSessionLocal

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
async def acknowledge_alert(alert_id: str, db: AsyncSession = Depends(get_db)):
    alert = await db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.sent = True  # or a separate 'acknowledged' field? We'll use sent for now.
    await db.commit()
    await db.refresh(alert)
    return alert