from sqlalchemy import text
import asyncio
import time
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from core.database import engine, Base, AsyncSessionLocal
from core.stream_manager import StreamManager
from engine.escalation import escalation_state
from api.routes import cameras, rules, alerts
from api.ws import live

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

app = FastAPI(title="SafeSight AI Platform")

# ------------------------------------------------------------
# CORS – allow the React frontend to talk to the API
# ------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

stream_manager = StreamManager()

# ------------------------------------------------------------
# Database Heartbeat with 500ms latency alert
# ------------------------------------------------------------
async def db_heartbeat():
    """Periodically check DB connection latency. Alerts if > 500ms."""
    while True:
        try:
            start = time.monotonic()
            async with AsyncSessionLocal() as session:
                await session.execute(text("SELECT 1"))
            latency = (time.monotonic() - start) * 1000  # ms
            if latency > 500:
                logger.warning(f"⚠️ DB heartbeat latency {latency:.1f} ms exceeds 500 ms threshold!")
            else:
                logger.info(f"💓 DB heartbeat OK ({latency:.1f} ms)")
        except Exception as e:
            logger.error(f"❌ DB heartbeat failed: {e}")
        await asyncio.sleep(60)

# ------------------------------------------------------------
# Escalation background loop
# ------------------------------------------------------------
async def escalation_loop():
    """Run escalation state checks every 10 seconds."""
    while True:
        try:
            await escalation_state.tick()
        except Exception as e:
            logger.error(f"Escalation tick failed: {e}")
        await asyncio.sleep(10)

@app.on_event("startup")
async def startup():
    # Create tables (in development) – use Alembic for production
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Start stream manager
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(stream_manager.start_all_from_db())
    except RuntimeError:
        logger.error("No running event loop – cannot start stream manager")
    # Start escalation loop
    asyncio.create_task(escalation_loop())
    # Start DB heartbeat
    asyncio.create_task(db_heartbeat())

# REST routes
app.include_router(cameras.router, prefix="/cameras", tags=["cameras"])
app.include_router(rules.router, prefix="/rules", tags=["rules"])
app.include_router(alerts.router, prefix="/alerts", tags=["alerts"])
# WebSocket overlay
app.include_router(live.router, prefix="/ws", tags=["live"])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)