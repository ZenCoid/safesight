from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from asyncio import Queue
import json
from typing import Dict

router = APIRouter()

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[str(websocket)] = websocket

    def disconnect(self, websocket: WebSocket):
        self.active_connections.pop(str(websocket), None)

    async def broadcast(self, data: dict):
        for ws in list(self.active_connections.values()):
            try:
                await ws.send_json(data)
            except:
                pass

manager = ConnectionManager()

@router.websocket("/overlay")
async def live_overlay(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive; data is pushed by the detection loop externally
            await websocket.receive_text()  # client can send pings
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# The ingestion pipeline can later call: manager.broadcast(detection_event.model_dump())