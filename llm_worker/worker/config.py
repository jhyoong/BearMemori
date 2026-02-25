"""Configuration settings for the LLM Worker service."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMWorkerSettings(BaseSettings):
    """LLM Worker settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    llm_base_url: str = "http://localhost:8080/v1"
    llm_vision_model: str = "llava"
    llm_text_model: str = "mistral"
    llm_api_key: str = "not-needed"
    llm_max_retries: int = 5
    redis_url: str = "redis://redis:6379"
    core_api_url: str = "http://core:8000"
    image_storage_path: str = "/data/images"


def load_llm_worker_settings() -> LLMWorkerSettings:
    """Load and return LLM worker settings."""
    return LLMWorkerSettings()
