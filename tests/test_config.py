from bearmemori.config import Settings


def test_settings_loads_defaults():
    settings = Settings(
        telegram_bot_token="test-token",
        telegram_allowed_user_id=12345,
        llm_base_url="http://localhost:11434/v1",
        llm_model="llama3",
    )
    assert settings.telegram_bot_token == "test-token"
    assert settings.telegram_allowed_user_id == 12345
    assert settings.database_path == "bearmemori.db"
    assert settings.queue_max_size == 1000
    assert settings.followup_timeout_hours == 24
    assert settings.embedding_model == "nomic-embed-text"


def test_reminder_poll_interval_default(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_ID", "123")
    settings = Settings()
    assert settings.reminder_poll_interval_seconds == 60
