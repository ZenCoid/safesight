from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import asyncio, json, random, time
from typing import Dict, Set
from uuid import UUID

router = APIRouter()

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.subscriptions: Dict[str, Set[str]] = {}  # ws_id -> set of camera_ids

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        ws_id = str(id(websocket))
        self.active_connections[ws_id] = websocket
        self.subscriptions[ws_id] = set()

    def disconnect(self, websocket: WebSocket):
        ws_id = str(id(websocket))
        self.active_connections.pop(ws_id, None)
        self.subscriptions.pop(ws_id, None)

    def subscribe(self, websocket: WebSocket, camera_id: str):
        ws_id = str(id(websocket))
        if ws_id in self.subscriptions:
            self.subscriptions[ws_id].add(camera_id)

    def unsubscribe(self, websocket: WebSocket, camera_id: str):
        ws_id = str(id(websocket))
        if ws_id in self.subscriptions:
            self.subscriptions[ws_id].discard(camera_id)

    async def broadcast_to_camera(self, camera_id: str, data: dict):
        for ws_id, ws in self.active_connections.items():
            if camera_id in self.subscriptions.get(ws_id, set()):
                try:
                    await ws.send_json(data)
                except:
                    pass

manager = ConnectionManager()

async def mock_detection_stream(camera_id: str):
    while True:
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

active_mock_streams: Dict[str, asyncio.Task] = {}

@router.websocket("/overlay")
async def live_overlay(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            action = data.get("action")
            cam_id = data.get("camera_id")
            if action == "subscribe" and cam_id:
                manager.subscribe(websocket, cam_id)
                if cam_id not in active_mock_streams:
                    active_mock_streams[cam_id] = asyncio.create_task(mock_detection_stream(cam_id))
            elif action == "unsubscribe" and cam_id:
                manager.unsubscribe(websocket, cam_id)
                # If no more subscribers for this camera, cancel mock stream
                remaining = any(cam_id in subs for subs in manager.subscriptions.values())
                if not remaining and cam_id in active_mock_streams:
                    task = active_mock_streams.pop(cam_id)
                    task.cancel()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        # Clean up any dangling mock streams for this client
        for cam_id in list(active_mock_streams.keys()):
            remaining = any(cam_id in subs for subs in manager.subscriptions.values())
            if not remaining:
                task = active_mock_streams.pop(cam_id, None)
                if task:
                    task.cancel()