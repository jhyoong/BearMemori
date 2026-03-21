from bearmemori.config import Settings


def test_settings_loads_defaults():
    settings = Settings(
        telegram_bot_token="test-token",
        llm_base_url="http://localhost:11434/v1",
        llm_model="llama3",
    )
    assert settings.telegram_bot_token == "test-token"
    assert settings.database_path == "bearmemori.db"
    assert settings.queue_max_size == 1000
    assert settings.followup_timeout_hours == 24
    assert settings.embedding_model == "nomic-embed-text"
