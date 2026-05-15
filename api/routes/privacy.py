from fastapi import APIRouter
import redis.asyncio as aioredis
from core.config import settings

router = APIRouter()
REDIS_PRIVACY_KEY = "safesight:privacy:enabled"

@router.post("/privacy/toggle")
async def toggle_privacy():
    r = aioredis.from_url(settings.REDIS_URL, decode_responses=False)
    current = await r.get(REDIS_PRIVACY_KEY)
    new_status = b"1" if current != b"1" else b"0"
    await r.set(REDIS_PRIVACY_KEY, new_status)
    return {"privacy_enabled": new_status == b"1"}

@router.get("/privacy/status")
async def get_privacy():
    r = aioredis.from_url(settings.REDIS_URL, decode_responses=False)
    val = await r.get(REDIS_PRIVACY_KEY)
    return {"privacy_enabled": val == b"1"}