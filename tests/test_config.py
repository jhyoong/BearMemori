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
    assert settings.embedding_model == "all-mpnet-base-v2"


def test_reminder_poll_interval_default(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_ID", "123")
    settings = Settings()
    assert settings.reminder_poll_interval_seconds == 60


def test_new_settings_defaults(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_ID", "123")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    s = Settings(_env_file=None)
    assert s.chroma_persist_dir == "chroma_data"
    assert s.embedding_model == "all-mpnet-base-v2"
    assert s.pending_ttl_seconds == 1800
    assert s.cleanup_interval_seconds == 300
    assert s.api_port == 8100
    assert s.llm_api_key == "not-needed"


def test_webapp_secret_default():
    settings = Settings(
        telegram_bot_token="test",
        telegram_allowed_user_id=123,
        _env_file=None,
    )
    assert settings.webapp_secret == ""


def test_image_storage_dir_default():
    """IMAGE_STORAGE_DIR defaults to data/images."""
    settings = Settings(
        telegram_bot_token="fake",
        telegram_allowed_user_id=1,
    )
    assert settings.image_storage_dir == "data/images"


def test_api_only_mode_defaults_false(monkeypatch):
    """API_ONLY_MODE should default to False for backwards compatibility."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_ID", "123")
    monkeypatch.delenv("API_ONLY_MODE", raising=False)
    s = Settings(_env_file=None)
    assert s.api_only_mode is False
