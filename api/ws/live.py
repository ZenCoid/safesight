from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import asyncio, json, random, time
from typing import Dict
from uuid import UUID

router = APIRouter()

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[str(id(websocket))] = websocket

    def disconnect(self, websocket: WebSocket):
        self.active_connections.pop(str(id(websocket)), None)

    async def broadcast_to_camera(self, camera_id: str, data: dict):
        # In practice, you'd filter by subscribed cameras.
        # Here we just send to all connections.
        for ws in list(self.active_connections.values()):
            try:
                await ws.send_json(data)
            except:
                pass

manager = ConnectionManager()

async def mock_detection_stream(camera_id: str):
    """Simulate detection events for a camera."""
    while True:
        # Generate a random detection
        det = {
            "camera_id": camera_id,
            "frame_id": random.randint(1000, 9999),
            "timestamp": time.time(),
            "objects": [
                {
                    "class_name": random.choice(["person", "helmet", "no-helmet", "fire"]),
                    "confidence": round(random.uniform(0.5, 0.99), 2),
                    "bbox": [round(random.uniform(0.1, 0.9), 2) for _ in range(4)]
                }
                for _ in range(random.randint(1, 3))
            ]
        }
        await manager.broadcast_to_camera(camera_id, det)
        await asyncio.sleep(1)

# When a camera is started, launch its mock stream (for demo)
active_mock_streams: Dict[str, asyncio.Task] = {}

@router.websocket("/overlay")
async def live_overlay(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("action") == "subscribe":
                cam_id = data["camera_id"]
                if cam_id not in active_mock_streams:
                    active_mock_streams[cam_id] = asyncio.create_task(mock_detection_stream(cam_id))
    except WebSocketDisconnect:
        manager.disconnect(websocket)