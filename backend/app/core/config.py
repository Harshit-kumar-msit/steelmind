"""
Module: core/config.py
Purpose: Centralized configuration using pydantic-settings.
         All env vars are validated at startup. Import `settings` anywhere.
Inputs:  .env file or real environment variables
Outputs: A frozen Settings instance with all app configuration
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ─── App ─────────────────────────────────────────────────────────────
    app_name: str = "SteelMind API"
    version: str = "1.0.0"
    environment: str = "development"
    debug: bool = False
    log_level: str = "INFO"
    secret_key: str = Field(..., min_length=32)
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440

    # ─── LLM / Groq ──────────────────────────────────────────────────────
    groq_api_key: str = Field(...)
    groq_model: str = "llama-3.3-70b-versatile"
    groq_fast_model: str = "llama-3.1-8b-instant"
    groq_max_tokens: int = 2048
    groq_temperature: float = 0.3          # Low for factual maintenance answers
    groq_timeout: int = 30

    # ─── Database ────────────────────────────────────────────────────────
    database_url: str = Field(...)
    database_url_sync: str = ""
    database_pool_size: int = 10
    database_max_overflow: int = 20

    # ─── InfluxDB ────────────────────────────────────────────────────────
    influx_url: str = "http://localhost:8086"
    influx_token: str = Field(...)
    influx_org: str = "steelmind_org"
    influx_bucket: str = "sensor_data"

    # ─── Redis ───────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    redis_ttl_seconds: int = 300           # Cache TTL for sensor snapshots

    # ─── ChromaDB / RAG ──────────────────────────────────────────────────
    chroma_path: str = "./data/chroma_db"
    chroma_collection: str = "steelmind_knowledge"
    embedding_model: str = "nomic-ai/nomic-embed-text-v1.5"
    chunk_size: int = 512
    chunk_overlap: int = 64
    top_k_retrieval: int = 5

    # ─── Alert Thresholds ────────────────────────────────────────────────
    anomaly_warning_threshold: int = 50
    anomaly_critical_threshold: int = 75
    rul_warning_days: int = 30
    rul_critical_days: int = 7

    # ─── Notifications ───────────────────────────────────────────────────
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    slack_webhook_url: str = ""

    @property
    def is_development(self) -> bool:
        return self.environment == "development"

    @property
    def cors_origins(self) -> list[str]:
        if self.is_development:
            return ["http://localhost:3000", "http://localhost:5173"]
        return []


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
