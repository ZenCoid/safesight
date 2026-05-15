import asyncio
import json
import time
import logging
import psutil
import threading
from typing import Dict, Set
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from core.config import settings
from core.stream_manager import stream_manager
from ingestion.detector import RFDETRDetector

logger = logging.getLogger(__name__)
router = APIRouter()

# --------------------------------------------------------------------------
# Connection management
# --------------------------------------------------------------------------
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.subscriptions: Dict[str, Set[str]] = {}

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
telemetry_manager = ConnectionManager()

# --------------------------------------------------------------------------
# Global telemetry counters (simple thread‑safe increments)
# --------------------------------------------------------------------------
_hash_counter = 0
_hash_lock = threading.Lock()
_pseudo_labeling_active = False

def increment_hash_count():
    global _hash_counter
    with _hash_lock:
        _hash_counter += 1

def get_and_reset_hash_count():
    global _hash_counter
    with _hash_lock:
        val = _hash_counter
        _hash_counter = 0
    return val

def set_pseudo_labeling_active(active: bool):
    global _pseudo_labeling_active
    _pseudo_labeling_active = active

# --------------------------------------------------------------------------
# Null‑stream detector (real pipeline)
# --------------------------------------------------------------------------
_detector = None

def get_detector():
    global _detector
    if _detector is None:
        try:
            _detector = RFDETRDetector(settings.RFDETR_MODEL_PATH)
            logger.info("RF‑DETR detector loaded (stub)")
        except Exception as e:
            logger.error(f"Failed to load detector: {e}")
            _detector = None
    return _detector

async def real_time_detection_stream(camera_id: str, reader):
    detector = get_detector()
    if detector is None:
        logger.warning("No detector available – stream will not produce detections")
        return

    loop = asyncio.get_running_loop()
    frame_counter = 0
    async for _, frame in reader.get_frames():
        active_subs = {cid for subs in manager.subscriptions.values() for cid in subs}
        if camera_id not in active_subs:
            break
        frame_counter += 1
        t_start = time.monotonic()
        try:
            det_event = await loop.run_in_executor(
                None, detector.predict, frame, UUID(camera_id), frame_counter
            )
        except Exception as e:
            logger.error(f"Detector predict failed: {e}")
            continue
        latency_ms = (time.monotonic() - t_start) * 1000
        payload = {
            "camera_id": camera_id,
            "frame_id": det_event.frame_id,
            "timestamp": det_event.timestamp,
            "objects": [
                {
                    "class_name": obj.class_name,
                    "confidence": obj.confidence,
                    "bbox": obj.bbox,
                }
                for obj in det_event.objects
            ],
            "latency_ms": round(latency_ms, 2),
        }
        await manager.broadcast_to_camera(camera_id, payload)
        await asyncio.sleep(0.05)

# --------------------------------------------------------------------------
# Overlay WebSocket
# --------------------------------------------------------------------------
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
                reader = stream_manager.readers.get(UUID(cam_id))
                if reader:
                    asyncio.create_task(real_time_detection_stream(cam_id, reader))
            elif action == "unsubscribe" and cam_id:
                manager.unsubscribe(websocket, cam_id)
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# --------------------------------------------------------------------------
# Telemetry WebSocket
# --------------------------------------------------------------------------
@router.websocket("/telemetry")
async def telemetry_websocket(websocket: WebSocket):
    await telemetry_manager.connect(websocket)
    try:
        while True:
            cpu = psutil.cpu_percent()
            mem = psutil.virtual_memory()
            vlm_loaded = False
            try:
                from api.routes.search import _pipe
                vlm_loaded = _pipe is not None
            except:
                pass
            hash_rate = get_and_reset_hash_count() / 2.0  # per second (update interval 2s)
            payload = {
                "cpu_percent": cpu,
                "memory_used_gb": round(mem.used / (1024**3), 2),
                "detector_latency_ms": 0,
                "vlm_loaded": vlm_loaded,
                "hash_gen_per_sec": round(hash_rate, 2),
                "pseudo_labeling_active": _pseudo_labeling_active,
            }
            await websocket.send_json(payload)
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        telemetry_manager.disconnect(websocket)
    except Exception:
        telemetry_manager.disconnect(websocket)