from fastapi import FastAPI
from core.database import engine, Base
from api.routes import cameras, rules, alerts
from api.ws import live
import asyncio

app = FastAPI(title="SafeSight AI Platform")

@app.on_event("startup")
async def startup():
    # create tables if not exist (use alembic in prod)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # start RTSP readers for all enabled cameras from DB (simplified)
    asyncio.create_task(stream_manager.start_all())

app.include_router(cameras.router, prefix="/cameras", tags=["cameras"])
app.include_router(rules.router, prefix="/rules", tags=["rules"])
app.include_router(alerts.router, prefix="/alerts", tags=["alerts"])
app.include_router(live.router, prefix="/ws", tags=["live"])