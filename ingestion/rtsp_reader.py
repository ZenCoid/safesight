import cv2
import asyncio
import logging
from typing import AsyncIterator
from uuid import UUID

logger = logging.getLogger(__name__)

class RTSPReader:
    def __init__(self, camera_id: UUID, rtsp_url: str, buffer_size: int = 10):
        self.camera_id = camera_id
        self.rtsp_url = rtsp_url
        self.cap = None
        self.buffer = asyncio.Queue(maxsize=buffer_size)
        self._running = False

    async def start(self):
        self._running = True
        gst_pipeline = (
            f"rtspsrc location={self.rtsp_url} latency=0 ! "
            "rtph264depay ! h264parse ! nvv4l2decoder ! videoconvert ! "
            "video/x-raw,format=BGR ! appsink drop=1"
        )
        self.cap = cv2.VideoCapture(gst_pipeline, cv2.CAP_GSTREAMER)
        if not self.cap.isOpened():
            raise RuntimeError(f"Cannot open RTSP stream: {self.rtsp_url}")
        asyncio.create_task(self._read_frames())

    async def _read_frames(self):
        loop = asyncio.get_event_loop()
        while self._running:
            ret, frame = await loop.run_in_executor(None, self.cap.read)
            if not ret:
                logger.warning(f"Camera {self.camera_id} frame read failed, retrying...")
                await asyncio.sleep(1)
                continue
            await self.buffer.put((self.camera_id, frame))

    async def get_frames(self) -> AsyncIterator:
        while self._running:
            cam_id, frame = await self.buffer.get()
            yield cam_id, frame

    async def stop(self):
        self._running = False
        if self.cap:
            self.cap.release()