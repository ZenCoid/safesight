import asyncio
import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import redis.asyncio as aioredis
from core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

REDIS_ALERT_CHANNEL = "safesight:alerts:status"

class AlertConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                pass

manager = AlertConnectionManager()

async def redis_listener():
    """Listen to Redis channel and push messages to WebSocket clients."""
    redis = aioredis.from_url(settings.REDIS_URL)
    pubsub = redis.pubsub()
    await pubsub.subscribe(REDIS_ALERT_CHANNEL)
    logger.info(f"Subscribed to Redis channel {REDIS_ALERT_CHANNEL}")
    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                data = message["data"]
                await manager.broadcast(data)
    except asyncio.CancelledError:
        pass
    finally:
        await pubsub.unsubscribe(REDIS_ALERT_CHANNEL)
        await redis.close()


@router.websocket("/alerts")
async def alert_status_websocket(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        # Just keep the connection open; messages come from Redis listener
        while True:
            # We need to keep the connection alive; can also receive pings from client
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)