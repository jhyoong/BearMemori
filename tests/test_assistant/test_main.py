"""Tests for assistant service main entry point wiring."""

import pytest
from unittest.mock import MagicMock, patch

from assistant_svc.main import build_components


@pytest.fixture
def mock_config():
    config = MagicMock()
    config.core_api_url = "http://test:8000"
    config.redis_url = "redis://localhost:6379"
    config.openai_api_key = "test-key"
    config.openai_base_url = "https://api.openai.com/v1"
    config.openai_model = "gpt-4o"
    config.context_window_tokens = 128000
    config.briefing_budget_tokens = 5000
    config.response_reserve_tokens = 4000
    config.session_timeout_seconds = 1800
    config.allowed_user_ids = "1,2,3"
    config.assistant_telegram_bot_token = "test-token"
    config.digest_default_hour = 8
    return config


class TestBuildComponents:
    def test_returns_all_components(self, mock_config):
        """build_components returns dict with all expected keys."""
        components = build_components(mock_config)
        expected_keys = {
            "redis", "core_client", "context_manager", "briefing_builder",
            "tool_registry", "openai_client", "agent", "interface",
            "digest_scheduler",
        }
        assert set(components.keys()) == expected_keys

    def test_tool_registry_has_all_tools(self, mock_config):
        """Tool registry has all 7 tools registered."""
        components = build_components(mock_config)
        registry = components["tool_registry"]
        expected_tools = {
            "search_memories", "get_memory", "list_tasks", "create_task",
            "list_reminders", "create_reminder", "list_events",
        }
        assert set(registry.tool_names()) == expected_tools

    def test_allowed_user_ids_parsed(self, mock_config):
        """Comma-separated user IDs are parsed into a set."""
        components = build_components(mock_config)
        interface = components["interface"]
        assert interface._allowed_user_ids == {1, 2, 3}

    def test_empty_allowed_user_ids(self, mock_config):
        """Empty allowed_user_ids string results in empty set."""
        mock_config.allowed_user_ids = ""
        components = build_components(mock_config)
        interface = components["interface"]
        assert interface._allowed_user_ids == set()

    def test_digest_scheduler_has_user_ids(self, mock_config):
        """Digest scheduler receives the parsed user IDs."""
        components = build_components(mock_config)
        digest = components["digest_scheduler"]
        assert set(digest._user_ids) == {1, 2, 3}
