import logging
from core.celery_app import celery_app
from core.config import settings
from twilio.rest import Client

logger = logging.getLogger(__name__)

@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def send_alert(self, violation_event_id, channel, escalation_level):
    """
    Dispatch alert via the given channel.
    Currently implemented: whatsapp (Twilio).
    """
    if channel == 'whatsapp':
        try:
            client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
            message = client.messages.create(
                body=f"🚨 SafeSight Alert\nViolation: {violation_event_id}\nLevel: {escalation_level}",
                from_=settings.TWILIO_WHATSAPP_NUMBER,
                to=settings.TWILIO_TO_NUMBER,
            )
            logger.info(f"WhatsApp message sent: {message.sid}")
        except Exception as exc:
            logger.error(f"WhatsApp send failed: {exc}")
            self.retry(exc=exc)
    else:
        logger.info(f"ALERT: {violation_event_id} level {escalation_level} via {channel} (not implemented)")
    return f"Alert sent to {channel}"