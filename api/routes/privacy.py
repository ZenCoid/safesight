from fastapi import APIRouter
import redis
from core.config import settings

router = APIRouter()
REDIS_PRIVACY_KEY = "safesight:privacy:enabled"

@router.post("/privacy/toggle")
async def toggle_privacy():
    r = redis.Redis.from_url(settings.REDIS_URL)
    current = r.get(REDIS_PRIVACY_KEY)
    new_status = b"1" if current != b"1" else b"0"
    r.set(REDIS_PRIVACY_KEY, new_status)
    return {"privacy_enabled": new_status == b"1"}

@router.get("/privacy/status")
async def get_privacy():
    r = redis.Redis.from_url(settings.REDIS_URL)
    val = r.get(REDIS_PRIVACY_KEY)
    return {"privacy_enabled": val == b"1"}