"""Tests for Telegram bot command handlers."""

import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram import Update
from telegram.ext import ContextTypes

# Add telegram directory to path so tg_gateway module is importable
telegram_dir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "telegram",
)
if telegram_dir not in sys.path:
    sys.path.insert(0, telegram_dir)


def _make_update(user_id: int = 12345, text: str = "/queue") -> MagicMock:
    """Return a minimal mock Update with a message."""
    update = MagicMock(spec=Update)
    update.message = MagicMock()
    update.message.text = text
    update.message.chat_id = 12345
    update.message.message_id = 1
    update.message.date = None
    update.message.reply_text = AsyncMock()
    user = MagicMock()
    user.id = user_id
    user.full_name = "Test User"
    update.message.from_user = user
    update.effective_user = user
    return update


def _make_context(
    user_data: dict | None = None, bot_data: dict | None = None
) -> MagicMock:
    """Return a minimal mock context with controllable user_data and bot_data."""
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.user_data = user_data if user_data is not None else {}
    context.bot_data = bot_data if bot_data is not None else {}
    return context


def _make_queue_stats(
    queued: int = 5,
    processing: int = 2,
    confirmed: int = 10,
    failed: int = 1,
    cancelled: int = 0,
    by_type: dict | None = None,
    oldest_age: int | None = 120,
) -> dict:
    """Helper to build queue stats dict."""
    return {
        "total_pending": queued,
        "by_status": {
            "queued": queued,
            "processing": processing,
            "confirmed": confirmed,
            "failed": failed,
            "cancelled": cancelled,
        },
        "by_type": by_type if by_type is not None else {"image_tag": 3, "intent_classify": 4},
        "oldest_queued_age_seconds": oldest_age,
    }


class TestQueueCommand:
    """Tests for the /queue admin command."""

    @pytest.mark.asyncio
    async def test_queue_command_shows_stats(self):
        """Test /queue command displays queue statistics."""
        from tg_gateway.handlers.command import queue_command

        update = _make_update(user_id=12345, text="/queue")
        core_client = AsyncMock()
        core_client.get_queue_stats = AsyncMock(return_value=_make_queue_stats())
        core_client.get_stream_health = AsyncMock(return_value={
            "streams": {"llm:image_tag": {"length": 3}}
        })
        core_client.get_llm_health = AsyncMock(return_value={
            "status": "healthy",
            "consecutive_failures": 0,
            "last_check": "2026-03-01T00:00:00+00:00",
        })
        context = _make_context(bot_data={"core_client": core_client})

        await queue_command(update, context)

        update.message.reply_text.assert_awaited_once()
        reply = update.message.reply_text.call_args[0][0]
        assert "Queue Statistics" in reply
        assert "Pending: `5`" in reply
        assert "Processing: `2`" in reply
        assert "Confirmed: `10`" in reply
        assert "Failed: `1`" in reply

    @pytest.mark.asyncio
    async def test_queue_command_includes_stream_health(self):
        """Test /queue command includes stream health data."""
        from tg_gateway.handlers.command import queue_command

        update = _make_update(user_id=12345, text="/queue")
        core_client = AsyncMock()
        core_client.get_queue_stats = AsyncMock(return_value=_make_queue_stats())
        core_client.get_stream_health = AsyncMock(return_value={
            "streams": {
                "llm:image_tag": {"length": 3},
                "llm:intent": {"length": 0},
            }
        })
        core_client.get_llm_health = AsyncMock(return_value={
            "status": "healthy",
            "consecutive_failures": 0,
            "last_check": "2026-03-01T00:00:00+00:00",
        })
        context = _make_context(bot_data={"core_client": core_client})

        await queue_command(update, context)

        reply = update.message.reply_text.call_args[0][0]
        assert "Stream Health" in reply
        assert "llm:image_tag" in reply

    @pytest.mark.asyncio
    async def test_queue_command_includes_llm_health(self):
        """Test /queue command includes LLM health data."""
        from tg_gateway.handlers.command import queue_command

        update = _make_update(user_id=12345, text="/queue")
        core_client = AsyncMock()
        core_client.get_queue_stats = AsyncMock(return_value=_make_queue_stats())
        core_client.get_stream_health = AsyncMock(return_value={"streams": {}})
        core_client.get_llm_health = AsyncMock(return_value={
            "status": "unhealthy",
            "consecutive_failures": 3,
            "last_check": "2026-03-01T12:00:00+00:00",
        })
        context = _make_context(bot_data={"core_client": core_client})

        await queue_command(update, context)

        reply = update.message.reply_text.call_args[0][0]
        assert "LLM Health" in reply
        assert "Unhealthy" in reply
        assert "`3`" in reply

    @pytest.mark.asyncio
    async def test_queue_command_graceful_when_health_endpoints_fail(self):
        """Test /queue still works when stream/llm health endpoints fail."""
        from tg_gateway.handlers.command import queue_command

        update = _make_update(user_id=12345, text="/queue")
        core_client = AsyncMock()
        core_client.get_queue_stats = AsyncMock(return_value=_make_queue_stats())
        core_client.get_stream_health = AsyncMock(
            side_effect=Exception("stream-health unavailable")
        )
        core_client.get_llm_health = AsyncMock(
            side_effect=Exception("llm-health unavailable")
        )
        context = _make_context(bot_data={"core_client": core_client})

        await queue_command(update, context)

        # Should still show queue stats even if health endpoints fail
        update.message.reply_text.assert_awaited_once()
        reply = update.message.reply_text.call_args[0][0]
        assert "Queue Statistics" in reply
        assert "Pending: `5`" in reply

    @pytest.mark.asyncio
    async def test_queue_command_core_client_not_available(self):
        """Test /queue handles missing core_client gracefully."""
        from tg_gateway.handlers.command import queue_command

        update = _make_update(user_id=12345, text="/queue")
        context = _make_context(bot_data={})  # No core_client

        await queue_command(update, context)

        update.message.reply_text.assert_awaited_once()
        reply = update.message.reply_text.call_args[0][0]
        assert "Error: Core client not available" in reply

    @pytest.mark.asyncio
    async def test_queue_command_handles_api_error(self):
        """Test /queue handles API errors gracefully."""
        from tg_gateway.handlers.command import queue_command

        update = _make_update(user_id=12345, text="/queue")
        core_client = AsyncMock()
        core_client.get_queue_stats = AsyncMock(side_effect=Exception("API error"))
        context = _make_context(bot_data={"core_client": core_client})

        await queue_command(update, context)

        update.message.reply_text.assert_awaited_once()
        reply = update.message.reply_text.call_args[0][0]
        assert "Failed to get queue statistics" in reply

    @pytest.mark.asyncio
    async def test_queue_command_empty_by_type(self):
        """Test /queue handles empty by_type gracefully."""
        from tg_gateway.handlers.command import queue_command

        update = _make_update(user_id=12345, text="/queue")
        core_client = AsyncMock()
        core_client.get_queue_stats = AsyncMock(
            return_value=_make_queue_stats(
                queued=0, processing=0, confirmed=0,
                failed=0, cancelled=0, by_type={}, oldest_age=None,
            )
        )
        core_client.get_stream_health = AsyncMock(return_value={"streams": {}})
        core_client.get_llm_health = AsyncMock(return_value={
            "status": "healthy", "consecutive_failures": 0,
            "last_check": "2026-03-01T00:00:00+00:00",
        })
        context = _make_context(bot_data={"core_client": core_client})

        await queue_command(update, context)

        reply = update.message.reply_text.call_args[0][0]
        assert "None" in reply or "By Type" in reply


class TestStatusCommand:
    """Tests for the /status user command."""

    @pytest.mark.asyncio
    async def test_status_command_shows_user_pending_and_health(self):
        """Test /status command displays user's pending count and health."""
        from tg_gateway.handlers.command import status_command

        update = _make_update(user_id=12345, text="/status")
        context = _make_context(
            bot_data={
                "core_client": AsyncMock(
                    get_queue_stats=AsyncMock(
                        return_value=_make_queue_stats(queued=3)
                    ),
                    get_llm_health=AsyncMock(
                        return_value={
                            "status": "healthy",
                            "consecutive_failures": 0,
                        }
                    ),
                )
            }
        )

        await status_command(update, context)

        update.message.reply_text.assert_awaited_once()
        reply = update.message.reply_text.call_args[0][0]
        assert "Your Status" in reply
        assert "Pending messages: `3`" in reply
        assert "LLM System Health" in reply
        assert "Healthy" in reply
        assert "Consecutive failures: `0`" in reply

    @pytest.mark.asyncio
    async def test_status_command_shows_unhealthy(self):
        """Test /status command shows unhealthy status when applicable."""
        from tg_gateway.handlers.command import status_command

        update = _make_update(user_id=12345, text="/status")
        context = _make_context(
            bot_data={
                "core_client": AsyncMock(
                    get_queue_stats=AsyncMock(
                        return_value=_make_queue_stats(queued=3)
                    ),
                    get_llm_health=AsyncMock(
                        return_value={
                            "status": "unhealthy",
                            "error": "connection refused",
                            "consecutive_failures": 5,
                        }
                    ),
                )
            }
        )

        await status_command(update, context)

        reply = update.message.reply_text.call_args[0][0]
        assert "Unhealthy" in reply
        assert "Consecutive failures: `5`" in reply

    @pytest.mark.asyncio
    async def test_status_command_core_client_not_available(self):
        """Test /status handles missing core_client gracefully."""
        from tg_gateway.handlers.command import status_command

        update = _make_update(user_id=12345, text="/status")
        context = _make_context(bot_data={})  # No core_client

        await status_command(update, context)

        update.message.reply_text.assert_awaited_once()
        reply = update.message.reply_text.call_args[0][0]
        assert "Error: Core client not available" in reply

    @pytest.mark.asyncio
    async def test_status_command_no_user(self):
        """Test /status handles missing user gracefully."""
        from tg_gateway.handlers.command import status_command

        update = MagicMock(spec=Update)
        update.message = MagicMock()
        update.message.text = "/status"
        update.message.chat_id = 12345
        update.message.message_id = 1
        update.message.date = None
        update.message.reply_text = AsyncMock()
        update.effective_user = None  # No user
        context = _make_context(bot_data={"core_client": AsyncMock()})

        await status_command(update, context)

        update.message.reply_text.assert_awaited_once()
        reply = update.message.reply_text.call_args[0][0]
        assert "Error: Could not identify user" in reply

    @pytest.mark.asyncio
    async def test_status_command_handles_api_error(self):
        """Test /status handles API errors gracefully."""
        from tg_gateway.handlers.command import status_command

        update = _make_update(user_id=12345, text="/status")
        core_client = AsyncMock()
        core_client.get_queue_stats = AsyncMock(side_effect=Exception("API error"))
        context = _make_context(bot_data={"core_client": core_client})

        await status_command(update, context)

        update.message.reply_text.assert_awaited_once()
        reply = update.message.reply_text.call_args[0][0]
        assert "Failed to get status information" in reply

    @pytest.mark.asyncio
    async def test_status_command_zero_pending(self):
        """Test /status handles zero pending count."""
        from tg_gateway.handlers.command import status_command

        update = _make_update(user_id=12345, text="/status")
        context = _make_context(
            bot_data={
                "core_client": AsyncMock(
                    get_queue_stats=AsyncMock(
                        return_value=_make_queue_stats(queued=0)
                    ),
                    get_llm_health=AsyncMock(
                        return_value={
                            "status": "healthy",
                            "consecutive_failures": 0,
                        }
                    ),
                )
            }
        )

        await status_command(update, context)

        reply = update.message.reply_text.call_args[0][0]
        assert "Pending messages: `0`" in reply
