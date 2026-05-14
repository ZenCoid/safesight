from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
from uuid import UUID
import cv2
import asyncio
from models.camera import Camera
from schemas.camera import CameraCreate, CameraRead
from core.database import AsyncSessionLocal
from core.stream_manager import stream_manager

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
    # Stop the RTSP reader if it exists and remove from stream manager
    reader = stream_manager.readers.pop(camera_id, None)
    if reader:
        await reader.stop()
    await db.delete(cam)
    await db.commit()
    return

# ---------------------------------------------------------------
# MJPEG stream endpoint
# ---------------------------------------------------------------
@router.get("/{camera_id}/stream")
async def stream_camera(camera_id: UUID, db: AsyncSession = Depends(get_db)):
    # Fetch camera from DB to get RTSP URL
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    cam = result.scalar_one_or_none()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    if not cam.enabled:
        raise HTTPException(status_code=400, detail="Camera is disabled")

    # Ensure the RTSP reader is running
    try:
        reader = await stream_manager.ensure_reader(camera_id, cam.rtsp_url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cannot start stream: {e}")

    async def frame_generator():
        async for _, frame in reader.get_frames():
            ret, jpeg = cv2.imencode('.jpg', frame)
            if not ret:
                continue
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' +
                   jpeg.tobytes() +
                   b'\r\n')
            await asyncio.sleep(0)   # yield to event loop

    return StreamingResponse(
        frame_generator(),
        media_type='multipart/x-mixed-replace; boundary=frame'
    )