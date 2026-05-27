import os
from dataclasses import dataclass


@dataclass
class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://ollive:ollive@localhost:5432/ollive",
    )
    ingestion_url: str = os.getenv("INGESTION_URL", "http://localhost:8002")
    default_provider: str = os.getenv("DEFAULT_PROVIDER", "openai")
    default_model: str = os.getenv("DEFAULT_MODEL", "gpt-4o-mini")
    context_window_turns: int = int(os.getenv("CONTEXT_WINDOW_TURNS", "10"))
    pii_redact: bool = os.getenv("PII_REDACT", "true").lower() == "true"
    store_raw_content: bool = os.getenv("STORE_RAW_CONTENT", "true").lower() == "true"
    default_system_prompt: str = os.getenv(
        "DEFAULT_SYSTEM_PROMPT",
        "You are a helpful, concise assistant.",
    )


settings = Settings()
