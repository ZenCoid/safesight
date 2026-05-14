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
from api.routes import cameras, rules, alerts, search, minio_upload, forensic
from api.ws import live as live_ws
from api.ws import alerts as alerts_ws
from core.pinned_scheduler import pinned_search_loop
from core.live_capture import live_capture_loop
from core.config import settings
from minio import Minio

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

app = FastAPI(title="SafeSight AI Platform")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

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

async def escalation_loop():
    while True:
        try:
            await escalation_state.tick()
        except Exception as e:
            logger.error(f"Escalation tick failed: {e}")
        await asyncio.sleep(10)

async def ensure_timescale_retention():
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text(
                "SELECT remove_retention_policy('violation_events', if_exists => true);"
            ))
            await session.execute(text(
                "SELECT remove_compression_policy('violation_events', if_exists => true);"
            ))
            await session.execute(text(
                "SELECT add_retention_policy('violation_events', INTERVAL '30 days');"
            ))
            await session.execute(text(
                "ALTER TABLE violation_events SET (timescaledb.compress, timescaledb.compress_segmentby = 'camera_id');"
            ))
            await session.execute(text(
                "SELECT add_compression_policy('violation_events', INTERVAL '7 days');"
            ))
            await session.commit()
            logger.info("TimescaleDB retention & compression policies configured")
    except Exception as e:
        logger.error(f"TimescaleDB policy setup failed: {e}")

async def ensure_minio_bucket():
    try:
        client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=False,
        )
        if not client.bucket_exists(settings.MINIO_BUCKET):
            client.make_bucket(settings.MINIO_BUCKET)
            logger.info(f"MinIO bucket '{settings.MINIO_BUCKET}' created")
    except Exception as e:
        logger.error(f"MinIO bucket check failed: {e}")

@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(stream_manager.start_all_from_db())
    except RuntimeError:
        logger.error("No running event loop – cannot start stream manager")
    asyncio.create_task(escalation_loop())
    asyncio.create_task(db_heartbeat())
    asyncio.create_task(disk_monitor())
    asyncio.create_task(pinned_search_loop())
    asyncio.create_task(live_capture_loop())
    asyncio.create_task(ensure_timescale_retention())
    asyncio.create_task(ensure_minio_bucket())
    # Start the Redis listener for alert status broadcasts
    asyncio.create_task(alerts_ws.redis_listener())

app.include_router(cameras.router, prefix="/cameras", tags=["cameras"])
app.include_router(rules.router, prefix="/rules", tags=["rules"])
app.include_router(alerts.router, prefix="/alerts", tags=["alerts"])
app.include_router(search.router, prefix="/v1", tags=["AI Search"])
app.include_router(minio_upload.router, prefix="/minio", tags=["MinIO"])
app.include_router(forensic.router, prefix="/v1", tags=["Forensic"])
app.include_router(live_ws.router, prefix="/ws", tags=["live"])
app.include_router(alerts_ws.router, prefix="/ws", tags=["alert-status"])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)