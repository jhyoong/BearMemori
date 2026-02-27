"""Configuration for the assistant service."""

import logging

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class AssistantConfig(BaseSettings):
    """Assistant service settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    core_api_url: str = "http://core:8000"
    redis_url: str = "redis://redis:6379"
    openai_api_key: str = "not-needed"
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o"
    assistant_telegram_bot_token: str = ""
    assistant_allowed_user_ids: str = ""
    context_window_tokens: int = 128000
    briefing_budget_tokens: int = 5000
    response_reserve_tokens: int = 4000
    session_timeout_seconds: int = 1800
    digest_default_hour: int = 8


def load_config() -> AssistantConfig:
    """Load and return assistant configuration."""
    return AssistantConfig()
