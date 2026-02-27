"""Tests for Telegram bot menu commands setup in post_init."""

from unittest.mock import AsyncMock, patch

import pytest
from telegram import BotCommand


@pytest.mark.asyncio
async def test_post_init_calls_set_my_commands(mock_application):
    """Verify that post_init calls set_my_commands on the bot."""
    from tg_gateway.main import post_init

    # Patch TelegramConfig to avoid environment variable dependency
    with patch("tg_gateway.main.TelegramConfig") as mock_config:
        mock_config.return_value.telegram_bot_token = "test-token"
        mock_config.return_value.allowed_user_ids = "12345"
        mock_config.return_value.core_api_url = "http://test:8000"
        mock_config.return_value.redis_url = "redis://test:6379"

        # Call post_init
        await post_init(mock_application)

    # Verify set_my_commands was called
    mock_application.bot.set_my_commands.assert_awaited_once()


@pytest.mark.asyncio
async def test_post_init_commands_list_contains_all_5_commands(mock_application):
    """Verify that all 5 commands are registered in set_my_commands."""
    from tg_gateway.main import post_init

    with patch("tg_gateway.main.TelegramConfig") as mock_config:
        mock_config.return_value.telegram_bot_token = "test-token"
        mock_config.return_value.allowed_user_ids = "12345"
        mock_config.return_value.core_api_url = "http://test:8000"
        mock_config.return_value.redis_url = "redis://test:6379"

        await post_init(mock_application)

    # Get the commands passed to set_my_commands
    call_args = mock_application.bot.set_my_commands.await_args
    commands = call_args[0][0] if call_args else []

    # Verify we have exactly 5 commands
    assert len(commands) == 5, f"Expected 5 commands, got {len(commands)}"

    # Extract command codes
    command_codes = [cmd.command for cmd in commands]

    # Verify all required commands are present
    expected_commands = ["help", "find", "tasks", "pinned", "cancel"]
    for cmd in expected_commands:
        assert cmd in command_codes, f"Missing command: {cmd}"


@pytest.mark.asyncio
async def test_post_init_command_descriptions_correct(mock_application):
    """Verify that command descriptions are correct."""
    from tg_gateway.main import post_init

    with patch("tg_gateway.main.TelegramConfig") as mock_config:
        mock_config.return_value.telegram_bot_token = "test-token"
        mock_config.return_value.allowed_user_ids = "12345"
        mock_config.return_value.core_api_url = "http://test:8000"
        mock_config.return_value.redis_url = "redis://test:6379"

        await post_init(mock_application)

    # Get the commands passed to set_my_commands
    call_args = mock_application.bot.set_my_commands.await_args
    commands = call_args[0][0] if call_args else []

    # Create a dict for easy lookup
    commands_dict = {cmd.command: cmd.description for cmd in commands}

    # Verify each command has the correct description
    expected_descriptions = {
        "help": "Show this help message",
        "find": "Search memories",
        "tasks": "List your tasks",
        "pinned": "Show pinned memories",
        "cancel": "Cancel current action",
    }

    for cmd, expected_desc in expected_descriptions.items():
        assert cmd in commands_dict, f"Missing command: {cmd}"
        assert commands_dict[cmd] == expected_desc, (
            f"Command '{cmd}' description mismatch: "
            f"expected '{expected_desc}', got '{commands_dict[cmd]}'"
        )


@pytest.mark.asyncio
async def test_post_init_no_errors_on_command_setup(mock_application):
    """Verify that post_init does not raise errors during command setup."""
    from tg_gateway.main import post_init

    with patch("tg_gateway.main.TelegramConfig") as mock_config:
        mock_config.return_value.telegram_bot_token = "test-token"
        mock_config.return_value.allowed_user_ids = "12345"
        mock_config.return_value.core_api_url = "http://test:8000"
        mock_config.return_value.redis_url = "redis://test:6379"

        # This should not raise any exceptions
        try:
            await post_init(mock_application)
        except Exception as e:
            pytest.fail(f"post_init raised unexpected exception: {e}")

    # Verify set_my_commands was called without errors
    mock_application.bot.set_my_commands.assert_awaited_once()
