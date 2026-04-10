from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "extra": "ignore"}

    telegram_bot_token: str = ""
    telegram_allowed_user_id: int = 0

    @model_validator(mode="after")
    def _require_telegram_unless_api_only(self) -> "Settings":
        if not self.api_only_mode:
            if not self.telegram_bot_token:
                raise ValueError("TELEGRAM_BOT_TOKEN is required when API_ONLY_MODE is not set")
            if self.telegram_allowed_user_id == 0:
                raise ValueError(
                    "TELEGRAM_ALLOWED_USER_ID is required when API_ONLY_MODE is not set"
                )
        return self

    llm_base_url: str = "http://localhost:11434/v1"
    llm_model: str = "llama3"
    llm_api_key: str = "not-needed"
    embedding_model: str = "all-mpnet-base-v2"
    database_path: str = "bearmemori.db"
    chroma_persist_dir: str = "chroma_data"
    pending_ttl_seconds: int = 1800
    cleanup_interval_seconds: int = 300
    queue_max_size: int = 1000
    followup_timeout_hours: int = 24
    reminder_poll_interval_seconds: int = 60
    retrieval_top_k: int = 5
    upcoming_events_days: int = 7
    api_port: int = 8100
    webapp_secret: str = ""
    llm_max_tokens: int = 4096
    triage_timeout_seconds: int = 3000
    webapp_secure_cookie: bool = False
    user_timezone: str = "UTC"
    image_storage_dir: str = "data/images"
    importance_high_threshold: int = 8
    importance_low_threshold: int = 2
    importance_relevance_weight: float = 0.5
    importance_weight: float = 0.5
    api_only_mode: bool = False
