import os
from dataclasses import dataclass


@dataclass
class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://ollive:ollive@localhost:5432/ollive",
    )
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    log_stream: str = os.getenv("LOG_STREAM", "inference_logs")
    consumer_group: str = os.getenv("CONSUMER_GROUP", "ingestion-workers")
    consumer_name: str = os.getenv("CONSUMER_NAME", "worker-1")
    pii_redact: bool = os.getenv("PII_REDACT", "true").lower() == "true"


settings = Settings()
