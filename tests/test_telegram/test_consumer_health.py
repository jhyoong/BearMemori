"""Tests for LLM health change notifications in the Telegram consumer.

Covers:
- _dispatch_notification handling for llm_health_change messages
- Sending "catching up" message when LLM becomes unhealthy
- Sending "back online" message when LLM becomes healthy
- Notification delivery to all allowed users
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from tg_gateway.consumer import _dispatch_notification


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_application_with_config(allowed_ids: set[int]) -> MagicMock:
    """Return a mock Application with a mocked bot and config."""
    app = MagicMock()
    app.bot = MagicMock()
    app.bot.send_message = AsyncMock()
    app.user_data = {}
    # bot_data with config containing allowed_ids_set
    config = MagicMock()
    config.allowed_ids_set = allowed_ids
    app.bot_data = {"config": config}
    return app


def _make_application_without_config() -> MagicMock:
    """Return a mock Application without config (edge case)."""
    app = MagicMock()
    app.bot = MagicMock()
    app.bot.send_message = AsyncMock()
    app.user_data = {}
    app.bot_data = {}  # No config
    return app


# ---------------------------------------------------------------------------
# LLM Health Change Tests
# ---------------------------------------------------------------------------


class TestLlmHealthChangeNotification:
    """Tests for llm_health_change message handling."""

    @pytest.mark.asyncio
    async def test_unhealthy_sends_catching_up_message_to_all_allowed_users(self):
        """When LLM becomes unhealthy, send 'catching up' message to all allowed users."""
        allowed_ids = {12345, 67890, 11111}
        app = _make_application_with_config(allowed_ids)

        data = {
            "user_id": 0,  # Special value for broadcast
            "message_type": "llm_health_change",
            "content": {
                "new_status": "unhealthy",
                "previous_status": "healthy",
            },
        }

        await _dispatch_notification(app, data)

        # Should send to all 3 allowed users
        assert app.bot.send_message.call_count == 3

        # Verify each user received the message
        call_args_list = app.bot.send_message.call_args_list
        texts = [call[1]["text"] for call in call_args_list]

        for text in texts:
            assert "catching up" in text.lower()
            assert "LLM" in text or "system" in text.lower()

        # Verify all allowed user IDs received the message
        received_user_ids = {call[1]["chat_id"] for call in call_args_list}
        assert received_user_ids == allowed_ids

    @pytest.mark.asyncio
    async def test_healthy_sends_back_online_message_to_all_allowed_users(self):
        """When LLM becomes healthy, send 'back online' message to all allowed users."""
        allowed_ids = {12345, 67890}
        app = _make_application_with_config(allowed_ids)

        data = {
            "user_id": 0,
            "message_type": "llm_health_change",
            "content": {
                "new_status": "healthy",
                "previous_status": "unhealthy",
            },
        }

        await _dispatch_notification(app, data)

        # Should send to all 2 allowed users
        assert app.bot.send_message.call_count == 2

        # Verify each user received the message
        call_args_list = app.bot.send_message.call_args_list
        texts = [call[1]["text"] for call in call_args_list]

        for text in texts:
            assert "back online" in text.lower()
            assert "processing" in text.lower() or "queued" in text.lower()

        # Verify all allowed user IDs received the message
        received_user_ids = {call[1]["chat_id"] for call in call_args_list}
        assert received_user_ids == allowed_ids

    @pytest.mark.asyncio
    async def test_unhealthy_status_specific_message_content(self):
        """Test the exact message content for unhealthy status."""
        allowed_ids = {12345}
        app = _make_application_with_config(allowed_ids)

        data = {
            "user_id": 0,
            "message_type": "llm_health_change",
            "content": {
                "new_status": "unhealthy",
                "previous_status": "healthy",
            },
        }

        await _dispatch_notification(app, data)

        text = app.bot.send_message.call_args[1]["text"]
        # Check for key phrases in the message
        assert "catching up" in text.lower()
        assert "messages" in text.lower() or "processing" in text.lower()

    @pytest.mark.asyncio
    async def test_healthy_status_specific_message_content(self):
        """Test the exact message content for healthy status."""
        allowed_ids = {12345}
        app = _make_application_with_config(allowed_ids)

        data = {
            "user_id": 0,
            "message_type": "llm_health_change",
            "content": {
                "new_status": "healthy",
                "previous_status": "unhealthy",
            },
        }

        await _dispatch_notification(app, data)

        text = app.bot.send_message.call_args[1]["text"]
        # Check for key phrases in the message
        assert "back online" in text.lower()
        assert "processing" in text.lower() or "queued" in text.lower()

    @pytest.mark.asyncio
    async def test_unknown_status_does_not_send_messages(self):
        """When status is neither 'unhealthy' nor 'healthy', no messages are sent."""
        allowed_ids = {12345}
        app = _make_application_with_config(allowed_ids)

        data = {
            "user_id": 0,
            "message_type": "llm_health_change",
            "content": {
                "new_status": "unknown_status",
                "previous_status": "healthy",
            },
        }

        await _dispatch_notification(app, data)

        # No messages should be sent for unknown status
        assert app.bot.send_message.call_count == 0

    @pytest.mark.asyncio
    async def test_empty_allowed_ids_set_no_messages_sent(self):
        """When no users are allowed, no messages are sent."""
        allowed_ids = set()
        app = _make_application_with_config(allowed_ids)

        data = {
            "user_id": 0,
            "message_type": "llm_health_change",
            "content": {
                "new_status": "unhealthy",
                "previous_status": "healthy",
            },
        }

        await _dispatch_notification(app, data)

        assert app.bot.send_message.call_count == 0

    @pytest.mark.asyncio
    async def test_missing_config_no_messages_sent(self):
        """When config is missing, no messages are sent."""
        app = _make_application_without_config()

        data = {
            "user_id": 0,
            "message_type": "llm_health_change",
            "content": {
                "new_status": "unhealthy",
                "previous_status": "healthy",
            },
        }

        await _dispatch_notification(app, data)

        assert app.bot.send_message.call_count == 0

    @pytest.mark.asyncio
    async def test_missing_content_no_crash(self):
        """When content is missing, no crash occurs."""
        allowed_ids = {12345}
        app = _make_application_with_config(allowed_ids)

        data = {
            "user_id": 0,
            "message_type": "llm_health_change",
            # No content key
        }

        await _dispatch_notification(app, data)

        # Should not send any messages (no valid status)
        assert app.bot.send_message.call_count == 0

    @pytest.mark.asyncio
    async def test_missing_new_status_no_crash(self):
        """When new_status is missing, no crash occurs."""
        allowed_ids = {12345}
        app = _make_application_with_config(allowed_ids)

        data = {
            "user_id": 0,
            "message_type": "llm_health_change",
            "content": {
                # No new_status
                "previous_status": "healthy",
            },
        }

        await _dispatch_notification(app, data)

        # Should not send any messages (no valid status)
        assert app.bot.send_message.call_count == 0

    @pytest.mark.asyncio
    async def test_single_allowed_user_receives_message(self):
        """Test with exactly one allowed user."""
        allowed_ids = {99999}
        app = _make_application_with_config(allowed_ids)

        data = {
            "user_id": 0,
            "message_type": "llm_health_change",
            "content": {
                "new_status": "unhealthy",
                "previous_status": "healthy",
            },
        }

        await _dispatch_notification(app, data)

        assert app.bot.send_message.call_count == 1
        call = app.bot.send_message.call_args[1]
        assert call["chat_id"] == 99999
        assert "catching up" in call["text"].lower()