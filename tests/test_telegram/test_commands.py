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
        "by_type": by_type
        if by_type is not None
        else {"image_tag": 3, "intent_classify": 4},
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
        core_client.get_stream_health = AsyncMock(
            return_value={"streams": {"llm:image_tag": {"length": 3}}}
        )
        core_client.get_llm_health = AsyncMock(
            return_value={
                "status": "healthy",
                "consecutive_failures": 0,
                "last_check": "2026-03-01T00:00:00+00:00",
            }
        )
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
        core_client.get_stream_health = AsyncMock(
            return_value={
                "streams": {
                    "llm:image_tag": {"length": 3},
                    "llm:intent": {"length": 0},
                }
            }
        )
        core_client.get_llm_health = AsyncMock(
            return_value={
                "status": "healthy",
                "consecutive_failures": 0,
                "last_check": "2026-03-01T00:00:00+00:00",
            }
        )
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
        core_client.get_llm_health = AsyncMock(
            return_value={
                "status": "unhealthy",
                "consecutive_failures": 3,
                "last_check": "2026-03-01T12:00:00+00:00",
            }
        )
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
                queued=0,
                processing=0,
                confirmed=0,
                failed=0,
                cancelled=0,
                by_type={},
                oldest_age=None,
            )
        )
        core_client.get_stream_health = AsyncMock(return_value={"streams": {}})
        core_client.get_llm_health = AsyncMock(
            return_value={
                "status": "healthy",
                "consecutive_failures": 0,
                "last_check": "2026-03-01T00:00:00+00:00",
            }
        )
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
                    get_queue_stats=AsyncMock(return_value=_make_queue_stats(queued=3)),
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
                    get_queue_stats=AsyncMock(return_value=_make_queue_stats(queued=3)),
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
                    get_queue_stats=AsyncMock(return_value=_make_queue_stats(queued=0)),
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

    @pytest.mark.asyncio
    async def test_status_command_no_pending_conversation(self):
        """Test /status with no pending conversation shows only queue/healthy status."""
        from tg_gateway.handlers.command import status_command

        update = _make_update(user_id=12345, text="/status")
        context = _make_context(
            user_data={},  # No pending conversation states
            bot_data={
                "core_client": AsyncMock(
                    get_queue_stats=AsyncMock(return_value=_make_queue_stats(queued=2)),
                    get_llm_health=AsyncMock(
                        return_value={
                            "status": "healthy",
                            "consecutive_failures": 0,
                        }
                    ),
                )
            },
        )

        await status_command(update, context)

        reply = update.message.reply_text.call_args[0][0]
        # Should show queue status
        assert "Your Status" in reply
        assert "Pending messages:" in reply
        # Should not mention any pending conversation states
        assert "waiting" not in reply.lower()
        assert "/cancel" not in reply

    @pytest.mark.asyncio
    async def test_status_command_with_pending_tag_memory_id(self):
        """Test /status with PENDING_TAG_MEMORY_ID shows tags message and /cancel."""
        from tg_gateway.handlers.command import status_command

        update = _make_update(user_id=12345, text="/status")
        context = _make_context(
            user_data={PENDING_TAG_MEMORY_ID: "memory_123"},
            bot_data={
                "core_client": AsyncMock(
                    get_queue_stats=AsyncMock(return_value=_make_queue_stats(queued=1)),
                    get_llm_health=AsyncMock(
                        return_value={
                            "status": "healthy",
                            "consecutive_failures": 0,
                        }
                    ),
                )
            },
        )

        await status_command(update, context)

        reply = update.message.reply_text.call_args[0][0]
        assert "waiting" in reply.lower()
        assert "/cancel" in reply

    @pytest.mark.asyncio
    async def test_status_command_with_pending_task_memory_id(self):
        """Test /status with PENDING_TASK_MEMORY_ID shows task due date message and /cancel."""
        from tg_gateway.handlers.command import status_command

        update = _make_update(user_id=12345, text="/status")
        context = _make_context(
            user_data={PENDING_TASK_MEMORY_ID: "memory_456"},
            bot_data={
                "core_client": AsyncMock(
                    get_queue_stats=AsyncMock(return_value=_make_queue_stats(queued=1)),
                    get_llm_health=AsyncMock(
                        return_value={
                            "status": "healthy",
                            "consecutive_failures": 0,
                        }
                    ),
                )
            },
        )

        await status_command(update, context)

        reply = update.message.reply_text.call_args[0][0]
        assert "waiting" in reply.lower()
        assert "task" in reply.lower()
        assert "/cancel" in reply

    @pytest.mark.asyncio
    async def test_status_command_with_pending_reminder_memory_id(self):
        """Test /status with PENDING_REMINDER_MEMORY_ID shows reminder time message and /cancel."""
        from tg_gateway.handlers.command import status_command

        update = _make_update(user_id=12345, text="/status")
        context = _make_context(
            user_data={PENDING_REMINDER_MEMORY_ID: "memory_789"},
            bot_data={
                "core_client": AsyncMock(
                    get_queue_stats=AsyncMock(return_value=_make_queue_stats(queued=1)),
                    get_llm_health=AsyncMock(
                        return_value={
                            "status": "healthy",
                            "consecutive_failures": 0,
                        }
                    ),
                )
            },
        )

        await status_command(update, context)

        reply = update.message.reply_text.call_args[0][0]
        assert "waiting" in reply.lower()
        assert "reminder" in reply.lower()
        assert "/cancel" in reply

    @pytest.mark.asyncio
    async def test_status_command_with_pending_llm_conversation(self):
        """Test /status with PENDING_LLM_CONVERSATION shows LLM followup message and /cancel."""
        from tg_gateway.handlers.command import status_command

        update = _make_update(user_id=12345, text="/status")
        conversation_state = {
            "memory_id": "memory_llm_123",
            "original_text": "Test message",
            "followup_question": "What is this about?",
        }
        context = _make_context(
            user_data={PENDING_LLM_CONVERSATION: conversation_state},
            bot_data={
                "core_client": AsyncMock(
                    get_queue_stats=AsyncMock(return_value=_make_queue_stats(queued=1)),
                    get_llm_health=AsyncMock(
                        return_value={
                            "status": "healthy",
                            "consecutive_failures": 0,
                        }
                    ),
                )
            },
        )

        await status_command(update, context)

        reply = update.message.reply_text.call_args[0][0]
        assert "waiting" in reply.lower()
        assert "llm" in reply.lower() or "followup" in reply.lower()
        assert "/cancel" in reply


class TestCoreClientUpdateSettings:
    @pytest.mark.asyncio
    async def test_update_settings_calls_put(self):
        from unittest.mock import patch, AsyncMock, MagicMock
        from tg_gateway.core_client import CoreClient
        from shared_lib.schemas import UserSettingsUpdate

        client = CoreClient(base_url="http://localhost:8083")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_success = True
        mock_response.json.return_value = {
            "user_id": 12345,
            "timezone": "Etc/GMT-8",
            "language": "en",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-03-01T00:00:00Z",
        }

        with patch.object(
            client._client, "put", new_callable=AsyncMock, return_value=mock_response
        ) as mock_put:
            result = await client.update_settings(
                12345, UserSettingsUpdate(timezone="Etc/GMT-8")
            )

        mock_put.assert_awaited_once_with(
            "/settings/12345",
            json={"timezone": "Etc/GMT-8"},
        )
        assert result.timezone == "Etc/GMT-8"


from tg_gateway.handlers.conversation import (
    PENDING_TAG_MEMORY_ID,
    PENDING_TASK_MEMORY_ID,
    PENDING_REMINDER_MEMORY_ID,
    PENDING_LLM_CONVERSATION,
)

from shared_lib.schemas import UserSettingsResponse
from datetime import datetime, timezone


def _make_settings_response(tz: str = "UTC") -> UserSettingsResponse:
    return UserSettingsResponse(
        user_id=12345,
        timezone=tz,
        language="en",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
    )


class TestTimezoneCommand:
    @pytest.mark.asyncio
    async def test_no_args_shows_current_timezone(self):
        from tg_gateway.handlers.command import timezone_command

        update = _make_update(text="/timezone")
        core_client = AsyncMock()
        core_client.get_settings = AsyncMock(
            return_value=_make_settings_response("Etc/GMT-8")
        )
        context = _make_context(bot_data={"core_client": core_client})
        context.args = []

        await timezone_command(update, context)

        reply = update.message.reply_text.call_args[0][0]
        assert "Etc/GMT-8" in reply
        assert "Local time:" in reply

    @pytest.mark.asyncio
    async def test_set_positive_offset(self):
        from tg_gateway.handlers.command import timezone_command

        update = _make_update(text="/timezone +8")
        core_client = AsyncMock()
        core_client.update_settings = AsyncMock(
            return_value=_make_settings_response("Etc/GMT-8")
        )
        context = _make_context(bot_data={"core_client": core_client})
        context.args = ["+8"]

        await timezone_command(update, context)

        core_client.update_settings.assert_awaited_once()
        reply = update.message.reply_text.call_args[0][0]
        assert "updated" in reply.lower()
        assert "Etc/GMT-8" in reply

    @pytest.mark.asyncio
    async def test_set_negative_offset(self):
        from tg_gateway.handlers.command import timezone_command

        update = _make_update(text="/timezone -5")
        core_client = AsyncMock()
        core_client.update_settings = AsyncMock(
            return_value=_make_settings_response("Etc/GMT+5")
        )
        context = _make_context(bot_data={"core_client": core_client})
        context.args = ["-5"]

        await timezone_command(update, context)

        core_client.update_settings.assert_awaited_once()
        reply = update.message.reply_text.call_args[0][0]
        assert "Etc/GMT+5" in reply

    @pytest.mark.asyncio
    async def test_set_iana_name_directly(self):
        from tg_gateway.handlers.command import timezone_command

        update = _make_update(text="/timezone Asia/Kolkata")
        core_client = AsyncMock()
        core_client.update_settings = AsyncMock(
            return_value=_make_settings_response("Asia/Kolkata")
        )
        context = _make_context(bot_data={"core_client": core_client})
        context.args = ["Asia/Kolkata"]

        await timezone_command(update, context)

        core_client.update_settings.assert_awaited_once()
        reply = update.message.reply_text.call_args[0][0]
        assert "Asia/Kolkata" in reply

    @pytest.mark.asyncio
    async def test_invalid_offset_shows_error(self):
        from tg_gateway.handlers.command import timezone_command

        update = _make_update(text="/timezone +99")
        core_client = AsyncMock()
        context = _make_context(bot_data={"core_client": core_client})
        context.args = ["+99"]

        await timezone_command(update, context)

        reply = update.message.reply_text.call_args[0][0]
        assert "range" in reply.lower()

    @pytest.mark.asyncio
    async def test_invalid_iana_name_shows_error(self):
        from tg_gateway.handlers.command import timezone_command

        update = _make_update(text="/timezone Fake/Zone")
        core_client = AsyncMock()
        context = _make_context(bot_data={"core_client": core_client})
        context.args = ["Fake/Zone"]

        await timezone_command(update, context)

        reply = update.message.reply_text.call_args[0][0]
        assert "unknown" in reply.lower() or "invalid" in reply.lower()

    @pytest.mark.asyncio
    async def test_no_core_client(self):
        from tg_gateway.handlers.command import timezone_command

        update = _make_update(text="/timezone")
        context = _make_context(bot_data={})
        context.args = []

        await timezone_command(update, context)

        reply = update.message.reply_text.call_args[0][0]
        assert "Error" in reply


class TestCancelCommand:
    """Tests for the /cancel command to clear pending conversation states."""

    @pytest.mark.asyncio
    async def test_cancel_clears_pending_tag_memory_id(self):
        """Test /cancel clears PENDING_TAG_MEMORY_ID when set."""
        from tg_gateway.handlers.command import cancel_command

        update = _make_update(text="/cancel")
        context = _make_context(user_data={PENDING_TAG_MEMORY_ID: "memory_123"})

        await cancel_command(update, context)

        # Verify the pending state was removed
        assert PENDING_TAG_MEMORY_ID not in context.user_data

    @pytest.mark.asyncio
    async def test_cancel_clears_pending_task_memory_id(self):
        """Test /cancel clears PENDING_TASK_MEMORY_ID when set."""
        from tg_gateway.handlers.command import cancel_command

        update = _make_update(text="/cancel")
        context = _make_context(user_data={PENDING_TASK_MEMORY_ID: "memory_456"})

        await cancel_command(update, context)

        # Verify the pending state was removed
        assert PENDING_TASK_MEMORY_ID not in context.user_data

    @pytest.mark.asyncio
    async def test_cancel_clears_pending_reminder_memory_id(self):
        """Test /cancel clears PENDING_REMINDER_MEMORY_ID when set."""
        from tg_gateway.handlers.command import cancel_command

        update = _make_update(text="/cancel")
        context = _make_context(user_data={PENDING_REMINDER_MEMORY_ID: "memory_789"})

        await cancel_command(update, context)

        # Verify the pending state was removed
        assert PENDING_REMINDER_MEMORY_ID not in context.user_data

    @pytest.mark.asyncio
    async def test_cancel_clears_pending_llm_conversation(self):
        """Test /cancel clears PENDING_LLM_CONVERSATION when set."""
        from tg_gateway.handlers.command import cancel_command

        update = _make_update(text="/cancel")
        conversation_state = {
            "memory_id": "memory_123",
            "original_text": "Test message",
            "followup_question": "What is this about?",
        }
        context = _make_context(
            user_data={PENDING_LLM_CONVERSATION: conversation_state}
        )

        await cancel_command(update, context)

        # Verify the pending state was removed
        assert PENDING_LLM_CONVERSATION not in context.user_data

    @pytest.mark.asyncio
    async def test_cancel_clears_all_four_pending_states(self):
        """Test /cancel clears all four pending conversation states together."""
        from tg_gateway.handlers.command import cancel_command

        update = _make_update(text="/cancel")
        context = _make_context(
            user_data={
                PENDING_TAG_MEMORY_ID: "memory_tag_123",
                PENDING_TASK_MEMORY_ID: "memory_task_456",
                PENDING_REMINDER_MEMORY_ID: "memory_reminder_789",
                PENDING_LLM_CONVERSATION: {
                    "memory_id": "memory_llm_999",
                    "original_text": "Test",
                    "followup_question": "Question?",
                },
            }
        )

        await cancel_command(update, context)

        # Verify all pending states were removed
        assert PENDING_TAG_MEMORY_ID not in context.user_data
        assert PENDING_TASK_MEMORY_ID not in context.user_data
        assert PENDING_REMINDER_MEMORY_ID not in context.user_data
        assert PENDING_LLM_CONVERSATION not in context.user_data

    @pytest.mark.asyncio
    async def test_cancel_no_pending_states_no_error(self):
        """Test /cancel handles context with no pending states without error."""
        from tg_gateway.handlers.command import cancel_command

        update = _make_update(text="/cancel")
        context = _make_context(user_data={})

        # Should not raise any exception
        await cancel_command(update, context)

        # Should still respond to user
        update.message.reply_text.assert_awaited_once()
        reply = update.message.reply_text.call_args[0][0]
        assert "cancelled" in reply.lower()
