import io
import cv2
import logging
import numpy as np
from minio import Minio
from core.config import settings
from core.celery_app import celery_app

logger = logging.getLogger(__name__)

CASCADE_PATH = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"

def apply_face_blur(image_bytes: bytes) -> bytes:
    np_arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    if img is None:
        logger.error("Failed to decode image for face blur")
        return image_bytes
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    face_cascade = cv2.CascadeClassifier(CASCADE_PATH)
    faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
    if len(faces) == 0:
        return image_bytes
    for (x, y, w, h) in faces:
        roi = img[y:y+h, x:x+w]
        blurred = cv2.GaussianBlur(roi, (99, 99), 30)
        img[y:y+h, x:x+w] = blurred
    _, jpeg = cv2.imencode('.jpg', img)
    return jpeg.tobytes()

@celery_app.task(name="tasks.privacy.redact_frame")
def redact_frame(object_name: str):
    minio_client = Minio(
        settings.MINIO_ENDPOINT,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=False,
    )
    try:
        resp = minio_client.get_object(settings.MINIO_BUCKET, object_name)
        original = resp.read()
        resp.close()
        resp.release_conn()
        blurred = apply_face_blur(original)
        minio_client.put_object(
            settings.MINIO_BUCKET, object_name,
            io.BytesIO(blurred), len(blurred),
            content_type='image/jpeg',
        )
        logger.info(f"Redacted faces in {object_name}")
    except Exception as e:
        logger.error(f"Redaction failed for {object_name}: {e}")