import os
import cv2
import asyncio
import logging
import platform
from concurrent.futures import ThreadPoolExecutor
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
        # Force TCP transport for reliability
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

        logger.info(f"Starting RTSP reader for {self.camera_id} at {self.rtsp_url}")

        # Open the capture in a thread to avoid blocking the event loop
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            self.cap = await loop.run_in_executor(pool, self._open_capture)

        if self.cap is None or not self.cap.isOpened():
            raise RuntimeError(f"Cannot open RTSP stream: {self.rtsp_url}")

        logger.info(f"RTSP stream opened successfully for {self.camera_id}")
        asyncio.create_task(self._read_frames())

    def _open_capture(self):
        # Set shorter timeout for opening (10 seconds)
        cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            logger.warning("FFMPEG backend failed, trying default backend")
            cap = cv2.VideoCapture(self.rtsp_url)
        # Set read timeout to 5 seconds to avoid hanging
        cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 10000)
        cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000)
        return cap

    async def _read_frames(self):
        loop = asyncio.get_running_loop()
        while self._running:
            ret, frame = await loop.run_in_executor(None, self.cap.read)
            if not ret:
                logger.warning(f"Camera {self.camera_id} frame read failed, retrying...")
                await asyncio.sleep(0.5)
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