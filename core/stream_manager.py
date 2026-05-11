import asyncio
import logging
from typing import Dict
from uuid import UUID
from sqlalchemy import select
from core.database import AsyncSessionLocal
from models.camera import Camera
from ingestion.rtsp_reader import RTSPReader

logger = logging.getLogger(__name__)

class StreamManager:
    def __init__(self):
        self.readers: Dict[UUID, RTSPReader] = {}

    async def start_all_from_db(self):
        """Fetch all enabled cameras from DB and start their readers."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Camera).where(Camera.enabled == True))
            cameras = result.scalars().all()
            for cam in cameras:
                try:
                    reader = RTSPReader(cam.id, cam.rtsp_url)
                    await reader.start()
                    self.readers[cam.id] = reader
                    logger.info(f"Started reader for camera {cam.id}")
                except Exception as e:
                    logger.error(f"Failed to start camera {cam.id}: {e}")

    async def stop_all(self):
        for reader in self.readers.values():
            await reader.stop()