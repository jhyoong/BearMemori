"""Shared configuration settings for BearMemori services."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    redis_url: str = "redis://redis:6379"
    core_host: str = "0.0.0.0"
    core_port: int = 8000
    database_path: str = "/data/db/life_organiser.db"
    image_storage_path: str = "/data/images"
    core_api_url: str = "http://core:8000"


def load_config() -> Settings:
    """Load and return application settings."""
    return Settings()
