from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://user:pass@localhost:5432/safesight"
    REDIS_URL: str = "redis://localhost:6379/0"
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET: str = "safesight-clips"
    RFDETR_MODEL_PATH: str = "models/rfdetr_base.pth"
    TEACHER_MODEL_PATH: str = "models/teacher_best.pt"
    LOW_CONFIDENCE_THRESHOLD: float = 0.3
    PSEUDO_LABEL_BATCH_SIZE: int = 32

    # Twilio WhatsApp
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_WHATSAPP_NUMBER: str = ""   # e.g. "whatsapp:+14155238886"
    TWILIO_TO_NUMBER: str = ""         # recipient number, e.g. "whatsapp:+923001234567"

    class Config:
        env_file = ".env"

settings = Settings()