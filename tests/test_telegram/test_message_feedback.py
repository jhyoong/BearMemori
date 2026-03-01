"""Tests for improved submission feedback in tg_gateway/handlers/message.py.

This module tests the _get_submission_feedback helper function which provides
smarter feedback messages based on LLM health status and queue depth.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from telegram.ext import ContextTypes

from tg_gateway.handlers.message import _get_submission_feedback


# ---------------------------------------------------------------------------
# Helpers / shared fixtures
# ---------------------------------------------------------------------------


def _make_context(
    user_data: dict | None = None, bot_data: dict | None = None
) -> MagicMock:
    """Return a minimal mock context with controllable user_data and bot_data."""
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.user_data = user_data if user_data is not None else {}
    context.bot_data = bot_data if bot_data is not None else {}
    return context


# ---------------------------------------------------------------------------
# Tests for _get_submission_feedback
# ---------------------------------------------------------------------------


class TestGetSubmissionFeedback:
    """Tests for the _get_submission_feedback helper function."""

    @pytest.mark.asyncio
    async def test_healthy_queue_empty_returns_processing(self):
        """When healthy and queue_count == 0, return 'Processing your message...'."""
        context = _make_context(user_data={"user_queue_count": 0})
        context.bot_data["redis"] = AsyncMock()
        context.bot_data["redis"].get = AsyncMock(return_value=b'{"status": "healthy"}')

        result = await _get_submission_feedback(context)

        assert result == "Processing your message..."
        context.bot_data["redis"].get.assert_awaited_once_with("llm:health_status")

    @pytest.mark.asyncio
    async def test_healthy_queue_nonempty_returns_added_to_queue_with_count(self):
        """When healthy and queue_count > 0, return 'Added to queue (X messages ahead)'."""
        context = _make_context(user_data={"user_queue_count": 3})
        context.bot_data["redis"] = AsyncMock()
        context.bot_data["redis"].get = AsyncMock(return_value=b'{"status": "healthy"}')

        result = await _get_submission_feedback(context)

        assert result == "Added to queue (3 messages ahead)"
        context.bot_data["redis"].get.assert_awaited_once_with("llm:health_status")

    @pytest.mark.asyncio
    async def test_unhealthy_returns_catching_up_message(self):
        """When unhealthy, return 'catching up' message regardless of queue count."""
        context = _make_context(user_data={"user_queue_count": 0})
        context.bot_data["redis"] = AsyncMock()
        context.bot_data["redis"].get = AsyncMock(
            return_value=b'{"status": "unhealthy", "last_heartbeat": 12345}'
        )

        result = await _get_submission_feedback(context)

        assert "catching up" in result.lower()
        context.bot_data["redis"].get.assert_awaited_once_with("llm:health_status")

    @pytest.mark.asyncio
    async def test_unhealthy_with_queue_returns_catching_up(self):
        """When unhealthy with items in queue, still return 'catching up' message."""
        context = _make_context(user_data={"user_queue_count": 5})
        context.bot_data["redis"] = AsyncMock()
        context.bot_data["redis"].get = AsyncMock(
            return_value=b'{"status": "unhealthy"}'
        )

        result = await _get_submission_feedback(context)

        assert "catching up" in result.lower()

    @pytest.mark.asyncio
    async def test_healthy_with_queue_count_1_returns_singular_message(self):
        """When healthy and queue_count == 1, return message with '1 message ahead'."""
        context = _make_context(user_data={"user_queue_count": 1})
        context.bot_data["redis"] = AsyncMock()
        context.bot_data["redis"].get = AsyncMock(return_value=b'{"status": "healthy"}')

        result = await _get_submission_feedback(context)

        assert "Added to queue (1 message ahead)" == result

    @pytest.mark.asyncio
    async def test_no_redis_client_falls_back_to_processing(self):
        """When no Redis client is available, fall back to 'Processing...' message."""
        context = _make_context(user_data={"user_queue_count": 0})
        context.bot_data = {}  # No redis in bot_data

        result = await _get_submission_feedback(context)

        assert result == "Processing your message..."

    @pytest.mark.asyncio
    async def test_redis_returns_none_falls_back_to_processing(self):
        """When Redis returns None for health status, fall back to 'Processing...'."""
        context = _make_context(user_data={"user_queue_count": 0})
        context.bot_data["redis"] = AsyncMock()
        context.bot_data["redis"].get = AsyncMock(return_value=None)

        result = await _get_submission_feedback(context)

        assert result == "Processing your message..."

    @pytest.mark.asyncio
    async def test_redis_returns_invalid_json_falls_back_to_processing(self):
        """When Redis returns invalid JSON, fall back to 'Processing...'."""
        context = _make_context(user_data={"user_queue_count": 0})
        context.bot_data["redis"] = AsyncMock()
        context.bot_data["redis"].get = AsyncMock(return_value=b'not valid json')

        result = await _get_submission_feedback(context)

        assert result == "Processing your message..."

    @pytest.mark.asyncio
    async def test_redis_returns_empty_status_falls_back_to_processing(self):
        """When health status is empty/missing, fall back to 'Processing...'."""
        context = _make_context(user_data={"user_queue_count": 0})
        context.bot_data["redis"] = AsyncMock()
        context.bot_data["redis"].get = AsyncMock(return_value=b'{}')

        result = await _get_submission_feedback(context)

        # Empty JSON means status is missing, falls back to healthy default (processing)
        assert result == "Processing your message..."

    @pytest.mark.asyncio
    async def test_queue_count_zero_with_health_status_returns_processing(self):
        """When queue_count is 0 (default) and health is healthy, return 'Processing...'."""
        context = _make_context(user_data={})  # No queue count set, defaults to 0
        context.bot_data["redis"] = AsyncMock()
        context.bot_data["redis"].get = AsyncMock(return_value=b'{"status": "healthy"}')

        result = await _get_submission_feedback(context)

        assert result == "Processing your message..."

    @pytest.mark.asyncio
    async def test_health_status_with_additional_fields(self):
        """When health status has additional fields, they are ignored."""
        context = _make_context(user_data={"user_queue_count": 0})
        context.bot_data["redis"] = AsyncMock()
        context.bot_data["redis"].get = AsyncMock(
            return_value=b'{"status": "healthy", "last_heartbeat": 12345, "uptime": 3600}'
        )

        result = await _get_submission_feedback(context)

        assert result == "Processing your message..."