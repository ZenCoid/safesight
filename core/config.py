from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Infrastructure – must be set via environment / .env file
    DATABASE_URL: str = ""
    REDIS_URL: str = ""
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = ""
    MINIO_SECRET_KEY: str = ""
    MINIO_BUCKET: str = "safesight-clips"

    # Model paths
    RFDETR_MODEL_PATH: str = "models/rfdetr_base.pth"
    TEACHER_MODEL_PATH: str = "models/teacher_best.pt"
    LOW_CONFIDENCE_THRESHOLD: float = 0.3
    PSEUDO_LABEL_BATCH_SIZE: int = 32

    # Twilio WhatsApp
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_WHATSAPP_NUMBER: str = ""
    TWILIO_TO_NUMBER: str = ""
    TWILIO_CONTENT_SID: str = ""

    # SMTP Email
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""
    SMTP_TO: str = ""

    # Local AI Vision Model
    MODEL_SEARCH_PATH: str = "models/qwen-3b-int4"

    # Autonomous Live Capture
    LIVE_CAPTURE_INTERVAL_SECONDS: int = 10

    # Sovereign Training Pool
    TRAINING_POOL_DIR: str = "E:/safesight/training_pool"

    class Config:
        env_file = ".env"

settings = Settings()