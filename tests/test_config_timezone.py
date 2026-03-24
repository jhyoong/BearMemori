"""Tests for USER_TIMEZONE config field."""

import os
from unittest.mock import patch


def test_settings_has_user_timezone_field():
    """Settings model should have a user_timezone field."""
    from bearmemori.config import Settings

    fields = Settings.model_fields
    assert "user_timezone" in fields, (
        f"Settings should have user_timezone field, has: {list(fields.keys())}"
    )


def test_user_timezone_defaults_to_utc():
    """USER_TIMEZONE defaults to UTC when not set."""
    with patch.dict(
        os.environ,
        {
            "TELEGRAM_BOT_TOKEN": "test",
            "TELEGRAM_ALLOWED_USER_ID": "123",
        },
        clear=True,
    ):
        from bearmemori.config import Settings

        settings = Settings()
        assert settings.user_timezone == "UTC"
