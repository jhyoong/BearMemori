"""Telegram Gateway configuration using pydantic-settings."""

import pydantic_settings


class TelegramConfig(pydantic_settings.BaseSettings):
    """Telegram Gateway configuration loaded from environment variables."""

    telegram_bot_token: str
    allowed_user_ids: str = ""
    core_api_url: str = "http://core:8000"
    redis_url: str = "redis://redis:6379"

    @property
    def allowed_ids_set(self) -> set[int]:
        """Parse comma-separated allowed_user_ids into a set of integers."""
        if not self.allowed_user_ids:
            return set()
        try:
            return {
                int(uid.strip())
                for uid in self.allowed_user_ids.split(",")
                if uid.strip()
            }
        except ValueError:
            return set()
