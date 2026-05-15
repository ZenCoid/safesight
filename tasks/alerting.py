import logging
import smtplib
import json
from email.message import EmailMessage
from uuid import UUID

import redis
from core.celery_app import celery_app
from core.config import settings
from core.database import AsyncSessionLocal
from models.alert import Alert
from twilio.rest import Client
from celery.signals import task_failure

app = celery_app
logger = logging.getLogger(__name__)

REDIS_ALERT_CHANNEL = "safesight:alerts:status"


def _update_alert_status_sync(violation_event_id: str, channel: str, level: int, success: bool):
    """Synchronous helper – uses the *existing* event loop of the Celery worker.
    In modern Celery + redis, the worker already has an event loop running."""
    import asyncio

    async def _async():
        # Update the Alert record
        try:
            async with AsyncSessionLocal() as session:
                from sqlalchemy import select
                result = await session.execute(
                    select(Alert).where(
                        Alert.violation_event_id == UUID(violation_event_id),
                        Alert.channel == channel,
                        Alert.escalation_level == level
                    ).order_by(Alert.created_at.desc()).limit(1)
                )
                alert = result.scalar_one_or_none()
                if alert:
                    alert.sent = success
                    await session.commit()
        except Exception as e:
            logger.error(f"Failed to update alert status: {e}")

        # Publish to Redis for WebSocket broadcast
        try:
            r = redis.Redis.from_url(settings.REDIS_URL)
            payload = json.dumps({
                "violation_event_id": violation_event_id,
                "channel": channel,
                "escalation_level": level,
                "success": success,
            })
            r.publish(REDIS_ALERT_CHANNEL, payload)
        except Exception as e:
            logger.error(f"Failed to publish alert status to Redis: {e}")

    # Use the existing loop (Celery worker already has one for async tasks)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(_async())


@app.task(bind=True, max_retries=5, default_retry_delay=10)
def send_alert(self, violation_event_id, channel, escalation_level):
    """Dispatch alert via the given channel and record the result."""
    try:
        if channel == 'whatsapp':
            _send_whatsapp(violation_event_id, escalation_level)
        elif channel == 'email':
            _send_email(violation_event_id, escalation_level)
        else:
            logger.info(f"ALERT: {violation_event_id} level {escalation_level} via {channel} (not implemented)")
        _update_alert_status_sync(violation_event_id, channel, escalation_level, True)
        return f"Alert sent to {channel}"
    except Exception as exc:
        logger.error(f"Alert failed (attempt {self.request.retries+1}): {exc}")
        if self.request.retries == self.max_retries - 1:
            _update_alert_status_sync(violation_event_id, channel, escalation_level, False)
        countdown = 10 * (2 ** self.request.retries)
        raise self.retry(exc=exc, countdown=countdown)


def _send_whatsapp(violation_event_id, escalation_level):
    try:
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        message = client.messages.create(
            from_=settings.TWILIO_WHATSAPP_NUMBER,
            to=settings.TWILIO_TO_NUMBER,
            content_sid=settings.TWILIO_CONTENT_SID,
            content_variables=json.dumps({
                "1": str(violation_event_id),
                "2": str(escalation_level),
            }),
        )
        logger.info(f"WhatsApp template message sent: {message.sid}")
    except Exception as exc:
        logger.error(f"WhatsApp send failed: {exc}")
        raise


def _send_email(violation_event_id, escalation_level):
    try:
        msg = EmailMessage()
        msg.set_content(
            f"SafeSight Alert\n\n"
            f"Violation Event ID: {violation_event_id}\n"
            f"Escalation Level: {escalation_level}\n"
            f"Timestamp: {__import__('datetime').datetime.now().isoformat()}"
        )
        msg['Subject'] = f'🚨 SafeSight Violation #{violation_event_id[:8]}'
        msg['From'] = settings.SMTP_FROM
        msg['To'] = settings.SMTP_TO

        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            server.starttls()
            server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            server.send_message(msg)

        logger.info(f"Email sent to {settings.SMTP_TO}")
    except Exception as exc:
        logger.error(f"Email send failed: {exc}")
        raise


@task_failure.connect(sender=send_alert)
def alert_task_failure(sender, task_id, exception, args, kwargs, **extra):
    logger.critical(
        f"🔥 ALERT TASK FAILED PERMANENTLY – "
        f"task_id={task_id}, args={args}, exception={exception}"
    )