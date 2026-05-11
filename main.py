"""
SafeSight AI Platform - FastAPI Entry Point
"""
from fastapi import FastAPI
from core.database import engine, Base
from core.stream_manager import StreamManager
from api.routes import cameras, rules, alerts
from api.ws import live
import asyncio

app = FastAPI(title="SafeSight AI Platform")

# Global stream manager singleton (replace with DB-driven logic later)
stream_manager = StreamManager()

@app.on_event("startup")
async def startup():
    # Create all database tables (in production, use Alembic migrations)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Start RTSP readers for all enabled cameras (simplified)
    asyncio.create_task(stream_manager.start_all_from_db())

# REST routes
app.include_router(cameras.router, prefix="/cameras", tags=["cameras"])
app.include_router(rules.router, prefix="/rules", tags=["rules"])
app.include_router(alerts.router, prefix="/alerts", tags=["alerts"])
# WebSocket
app.include_router(live.router, prefix="/ws", tags=["live"])