from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
from models.camera import Camera
from schemas.camera import CameraCreate, CameraRead
from core.database import AsyncSessionLocal

router = APIRouter()

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

@router.get("/", response_model=List[CameraRead])
async def list_cameras(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Camera))
    cameras = result.scalars().all()
    return cameras

@router.post("/", response_model=CameraRead, status_code=201)
async def create_camera(cam: CameraCreate, db: AsyncSession = Depends(get_db)):
    db_cam = Camera(**cam.model_dump())
    db.add(db_cam)
    await db.commit()
    await db.refresh(db_cam)
    return db_cam

@router.get("/{camera_id}", response_model=CameraRead)
async def get_camera(camera_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    cam = result.scalar_one_or_none()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    return cam

@router.delete("/{camera_id}", status_code=204)
async def delete_camera(camera_id: UUID, db: AsyncSession = Depends(get_db)):
    cam = await db.get(Camera, camera_id)
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    await db.delete(cam)
    await db.commit()
    return