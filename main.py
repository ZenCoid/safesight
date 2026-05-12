from sqlalchemy import text
import asyncio
import time
import logging
import shutil
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from core.database import engine, Base, AsyncSessionLocal
from core.stream_manager import stream_manager
from engine.escalation import escalation_state
from api.routes import cameras, rules, alerts, search          # 'live' removed from here
from api.ws import live as live_ws                             # already correct

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

app = FastAPI(title="SafeSight AI Platform")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------------------
# Disk Monitor (warns if free space < 5 GB)
# ------------------------------------------------------------
async def disk_monitor():
    while True:
        try:
            usage = shutil.disk_usage('.')
            free_gb = usage.free / (1024 ** 3)
            if free_gb < 5.0:
                logger.critical(f"⚠️ LOW DISK SPACE: {free_gb:.1f} GB free. MinIO snapshots paused!")
            else:
                logger.debug(f"Disk OK: {free_gb:.1f} GB free")
        except Exception as e:
            logger.error(f"Disk check failed: {e}")
        await asyncio.sleep(120)

# ------------------------------------------------------------
# Database Heartbeat
# ------------------------------------------------------------
async def db_heartbeat():
    while True:
        try:
            start = time.monotonic()
            async with AsyncSessionLocal() as session:
                await session.execute(text("SELECT 1"))
            latency = (time.monotonic() - start) * 1000
            if latency > 500:
                logger.warning(f"⚠️ DB heartbeat latency {latency:.1f} ms exceeds 500 ms threshold!")
            else:
                logger.info(f"💓 DB heartbeat OK ({latency:.1f} ms)")
        except Exception as e:
            logger.error(f"❌ DB heartbeat failed: {e}")
        await asyncio.sleep(60)

# ------------------------------------------------------------
# Escalation loop
# ------------------------------------------------------------
async def escalation_loop():
    while True:
        try:
            await escalation_state.tick()
        except Exception as e:
            logger.error(f"Escalation tick failed: {e}")
        await asyncio.sleep(10)

@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Start stream manager (uses global instance)
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(stream_manager.start_all_from_db())
    except RuntimeError:
        logger.error("No running event loop – cannot start stream manager")
    # Background tasks
    asyncio.create_task(escalation_loop())
    asyncio.create_task(db_heartbeat())
    asyncio.create_task(disk_monitor())

# REST routes
app.include_router(cameras.router, prefix="/cameras", tags=["cameras"])
app.include_router(rules.router, prefix="/rules", tags=["rules"])
app.include_router(alerts.router, prefix="/alerts", tags=["alerts"])
app.include_router(search.router, prefix="/v1", tags=["AI Search"])
# WebSocket
app.include_router(live_ws.router, prefix="/ws", tags=["live"])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)