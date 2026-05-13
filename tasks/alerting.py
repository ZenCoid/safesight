import logging
import smtplib
import json
from email.message import EmailMessage
from core.celery_app import celery_app
from core.config import settings
from twilio.rest import Client

app = celery_app
logger = logging.getLogger(__name__)


@app.task(bind=True, max_retries=3, default_retry_delay=60)
def send_alert(self, violation_event_id, channel, escalation_level):
    """
    Dispatch alert via the given channel.
    Supported: whatsapp (Twilio template), email (SMTP).
    """
    if channel == 'whatsapp':
        _send_whatsapp(violation_event_id, escalation_level)
    elif channel == 'email':
        _send_email(violation_event_id, escalation_level)
    else:
        logger.info(
            f"ALERT: {violation_event_id} level {escalation_level} "
            f"via {channel} (not implemented)"
        )
    return f"Alert sent to {channel}"


def _send_whatsapp(violation_event_id, escalation_level):
    """Send WhatsApp message using the pre‑approved Twilio Content Template."""
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


def _send_email(violation_event_id, escalation_level):
    """Send email alert via SMTP."""
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