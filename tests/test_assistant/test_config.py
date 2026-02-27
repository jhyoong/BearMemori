"""Tests for assistant service configuration."""

import pytest
from assistant_svc.config import AssistantConfig, load_config


def test_config_defaults():
    """Config loads with default values."""
    config = AssistantConfig(
        _env_file=None,
        openai_api_key="test-key",
        assistant_telegram_bot_token="test-token",
    )
    assert config.core_api_url == "http://core:8000"
    assert config.redis_url == "redis://redis:6379"
    assert config.context_window_tokens == 128000
    assert config.briefing_budget_tokens == 5000
    assert config.session_timeout_seconds == 1800


def test_config_env_override(monkeypatch):
    """Config values can be overridden by environment variables."""
    monkeypatch.setenv("CORE_API_URL", "http://localhost:9000")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("ASSISTANT_TELEGRAM_BOT_TOKEN", "test-token")
    config = AssistantConfig(_env_file=None)
    assert config.core_api_url == "http://localhost:9000"
    assert config.openai_model == "gpt-4o-mini"
