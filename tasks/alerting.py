from celery_app import celery
import requests

@celery.task(bind=True, max_retries=3, default_retry_delay=60)
def send_whatsapp_alert(self, violation_event_id, phone_number, message):
    # Integrate with Twilio/Business API
    # ...
    pass

@celery.task
def trigger_siren(camera_location):
    # Call hardware API
    pass