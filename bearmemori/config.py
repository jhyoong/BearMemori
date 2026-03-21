from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "extra": "ignore"}

    telegram_bot_token: str
    llm_base_url: str = "http://localhost:11434/v1"
    llm_model: str = "llama3"
    embedding_model: str = "nomic-embed-text"
    database_path: str = "bearmemori.db"
    queue_max_size: int = 1000
    followup_timeout_hours: int = 24
