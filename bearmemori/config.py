from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "extra": "ignore"}

    telegram_bot_token: str
    telegram_allowed_user_id: int
    llm_base_url: str = "http://localhost:11434/v1"
    llm_model: str = "llama3"
    llm_api_key: str = "not-needed"
    embedding_model: str = "all-mpnet-base-v2"
    database_path: str = "bearmemori.db"
    chroma_persist_dir: str = "chroma_data"
    pending_ttl_seconds: int = 86400
    queue_max_size: int = 1000
    followup_timeout_hours: int = 24
    reminder_poll_interval_seconds: int = 60
    retrieval_top_k: int = 5
    upcoming_events_days: int = 7
    api_port: int = 8100
