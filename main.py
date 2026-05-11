"""
SafeSight AI Platform - FastAPI Entry Point
"""
from fastapi import FastAPI
import asyncio
import logging
from core.database import engine, Base
from core.stream_manager import StreamManager
from engine.escalation import escalation_state
from api.routes import cameras, rules, alerts
from api.ws import live

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

app = FastAPI(title="SafeSight AI Platform")

stream_manager = StreamManager()

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
    # Create tables if not exist (use Alembic in production)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Start RTSP readers for all enabled cameras
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(stream_manager.start_all_from_db())
    except RuntimeError:
        logger.error("No running event loop – cannot start stream manager")
    # Start escalation background task
    asyncio.create_task(escalation_loop())

# REST routes
app.include_router(cameras.router, prefix="/cameras", tags=["cameras"])
app.include_router(rules.router, prefix="/rules", tags=["rules"])
app.include_router(alerts.router, prefix="/alerts", tags=["alerts"])
# WebSocket overlay
app.include_router(live.router, prefix="/ws", tags=["live"])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)