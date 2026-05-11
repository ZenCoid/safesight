from celery import Celery
from core.config import settings

celery_app = Celery(
    "safesight_tasks",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL
)

# Optional: configure Celery beat for periodic tasks later
celery_app.conf.beat_schedule = {}
celery_app.conf.timezone = "UTC"