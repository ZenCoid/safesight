import asyncio
import logging
from typing import Dict
from uuid import UUID
from sqlalchemy import select, update, func
from core.database import AsyncSessionLocal
from models.camera import Camera
from ingestion.rtsp_reader import RTSPReader

logger = logging.getLogger(__name__)

MAX_RECONNECT_DELAY = 60

class StreamManager:
    def __init__(self):
        self.readers: Dict[UUID, RTSPReader] = {}

    async def start_all_from_db(self):
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Camera).where(Camera.enabled == True)
            )
            cameras = result.scalars().all()
        for cam in cameras:
            asyncio.create_task(self._connect_camera_with_retry(cam))

    async def _connect_camera_with_retry(self, cam: Camera):
        delay = 1
        while True:
            try:
                reader = RTSPReader(cam.id, cam.rtsp_url)
                await reader.start()
                self.readers[cam.id] = reader
                await self._update_health(cam.id, "online")
                logger.info(f"Camera {cam.id} connected")
                return
            except Exception as e:
                logger.error(f"Camera {cam.id} connection failed: {e}. Retrying in {delay}s")
                await self._update_health(cam.id, "error")
                await asyncio.sleep(delay)
                delay = min(delay * 2, MAX_RECONNECT_DELAY)

    async def _update_health(self, camera_id: UUID, status: str):
        try:
            async with AsyncSessionLocal() as session:
                await session.execute(
                    update(Camera)
                    .where(Camera.id == camera_id)
                    .values(health_status=status, updated_at=func.now())
                )
                await session.commit()
        except Exception as e:
            logger.error(f"Failed to update health for camera {camera_id}: {e}")

    async def ensure_reader(self, camera_id: UUID, rtsp_url: str) -> RTSPReader:
        if camera_id in self.readers:
            return self.readers[camera_id]
        reader = RTSPReader(camera_id, rtsp_url)
        await reader.start()
        self.readers[camera_id] = reader
        await self._update_health(camera_id, "online")
        return reader

    async def stop_all(self):
        for reader in self.readers.values():
            await reader.stop()

stream_manager = StreamManager()