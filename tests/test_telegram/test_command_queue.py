"""Tests for the /queue command Markdown parsing bug with underscores in stream names.

This test file specifically tests the bug where stream names containing underscores
(e.g., "llm:image_tag", "llm:intent", "llm:followup", "llm:task_match", "llm:email_extract")
cause Telegram's Markdown parser to fail with "Can't parse entities" error.
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from telegram.error import BadRequest

# Add telegram directory to path so tg_gateway module is importable
telegram_dir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "telegram",
)
if telegram_dir not in sys.path:
    sys.path.insert(0, telegram_dir)


def _make_update(user_id: int = 12345, text: str = "/queue") -> MagicMock:
    """Return a minimal mock Update with a message.

    The reply_text method is wrapped to validate Markdown parsing,
    which will raise BadRequest if the Markdown is invalid
    (e.g., unescaped underscores in stream names).
    """

    async def _mock_reply_text_impl(text: str, parse_mode: str | None = None, **kwargs):
        """Mock reply_text that validates Markdown when parse_mode is set."""
        if parse_mode == "Markdown":
            # Validate the Markdown - this will raise BadRequest if invalid
            _assert_markdown_parseable(text)
        return None

    # Wrap as AsyncMock to enable assert_awaited_once() method
    mock_reply_text = AsyncMock(side_effect=_mock_reply_text_impl)

    update = MagicMock(spec=Update)
    update.message = MagicMock()
    update.message.text = text
    update.message.chat_id = 12345
    update.message.message_id = 1
    update.message.date = None
    update.message.reply_text = mock_reply_text
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


import re


def _assert_markdown_parseable(text: str) -> None:
    """Assert that the given text can be parsed as Markdown without errors.

    This checks for common Markdown errors with underscores in stream names.
    Telegram's Markdown parser interprets unescaped underscores like "llm:image_tag"
    as italic markers, causing "Can't parse entities: can't find end of the entity" error.

    Args:
        text: The text to validate as Markdown.

    Raises:
        BadRequest: If the text cannot be parsed as valid Markdown.
    """
    # Check for unescaped underscores that appear in stream names like "llm:image_tag"
    # These underscores in text (not inside code blocks) cause Markdown parsing errors
    # Pattern matches underscore that's NOT preceded by backslash and NOT inside
    # backticks (code blocks), and is surrounded by word characters (alphanumeric or colon)

    # Find stream names with underscores (e.g., llm:image_tag)
    stream_with_underscore_pattern = r"(?:^|[^`])[a-zA-Z0-9]:[a-zA-Z0-9_]+(?=$|[^`])"
    matches = re.findall(stream_with_underscore_pattern, text, re.MULTILINE)

    # If there are stream names with underscores, they need to be escaped
    # Check if any are directly in the text without escaping
    problematic_pattern = r"(?<!`)(llm:[a-z_]+|notify:[a-z_]+)(?!`)"
    if re.search(problematic_pattern, text):
        # This is the bug - underscores in stream names are not escaped
        # Telegram will fail to parse this as Markdown
        raise Exception(
            "Markdown parsing error: Stream names with underscores "
            "(e.g., 'llm:image_tag') must be escaped or wrapped in code blocks "
            "to avoid Markdown italic formatting errors"
        )


class TestQueueCommandMarkdownUnderscores:
    """Tests for the /queue command with stream names containing underscores.

    These tests verify that stream names with underscores (like "llm:image_tag")
    don't cause Telegram Markdown parsing errors ("Can't parse entities").
    """

    @pytest.mark.asyncio
    async def test_queue_command_stream_names_with_underscores_no_markdown_error(self):
        """Test /queue command handles stream names with underscores without Markdown error.

        The bug is that stream names like "llm:image_tag" contain underscores which
        Telegram's Markdown parser interprets as italic formatting markers, causing
        "Can't parse entities: can't find end of the entity" error.

        This test verifies the command succeeds and stream names are visible in output.
        """
        from tg_gateway.handlers.command import queue_command

        update = _make_update(user_id=12345, text="/queue")
        core_client = AsyncMock()
        core_client.get_queue_stats = AsyncMock(return_value=_make_queue_stats())
        # Stream names with underscores that cause the Markdown parsing error
        core_client.get_stream_health = AsyncMock(
            return_value={
                "streams": {
                    "llm:image_tag": {"length": 3},
                    "llm:intent": {"length": 5},
                    "llm:followup": {"length": 2},
                    "llm:task_match": {"length": 1},
                    "llm:email_extract": {"length": 0},
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

        # This should NOT raise a Markdown parsing error
        await queue_command(update, context)

        # Verify reply was called successfully
        update.message.reply_text.assert_awaited_once()
        reply = update.message.reply_text.call_args[0][0]

        # Verify stream names are visible in output (not hidden by parsing error)
        assert "llm:image_tag" in reply
        assert "llm:intent" in reply
        assert "llm:followup" in reply
        assert "llm:task_match" in reply
        assert "llm:email_extract" in reply

    @pytest.mark.asyncio
    async def test_queue_command_single_stream_with_underscore(self):
        """Test /queue command handles single stream with underscore."""
        from tg_gateway.handlers.command import queue_command

        update = _make_update(user_id=12345, text="/queue")
        core_client = AsyncMock()
        core_client.get_queue_stats = AsyncMock(return_value=_make_queue_stats())
        core_client.get_stream_health = AsyncMock(
            return_value={
                "streams": {
                    "llm:image_tag": {"length": 10},
                }
            }
        )
        core_client.get_llm_health = AsyncMock(return_value={"status": "healthy"})
        context = _make_context(bot_data={"core_client": core_client})

        await queue_command(update, context)

        update.message.reply_text.assert_awaited_once()
        reply = update.message.reply_text.call_args[0][0]

        # Stream name should be visible
        assert "llm:image_tag" in reply

    @pytest.mark.asyncio
    async def test_queue_command_multiple_underscores_in_stream_name(self):
        """Test /queue command handles stream names with multiple underscores."""
        from tg_gateway.handlers.command import queue_command

        update = _make_update(user_id=12345, text="/queue")
        core_client = AsyncMock()
        core_client.get_queue_stats = AsyncMock(return_value=_make_queue_stats())
        # Test with multiple underscores - though unlikely, just to be safe
        core_client.get_stream_health = AsyncMock(
            return_value={
                "streams": {
                    "llm:image_tag": {"length": 3},
                    "llm:intent": {"length": 2},
                    "llm:followup": {"length": 1},
                }
            }
        )
        core_client.get_llm_health = AsyncMock(return_value={"status": "healthy"})
        context = _make_context(bot_data={"core_client": core_client})

        await queue_command(update, context)

        update.message.reply_text.assert_awaited_once()
        reply = update.message.reply_text.call_args[0][0]

        # All stream names should be visible without Markdown errors
        assert "llm:image_tag" in reply
        assert "llm:intent" in reply
        assert "llm:followup" in reply

    @pytest.mark.asyncio
    async def test_queue_command_queue_stats_display_correctly_with_underscore_streams(
        self,
    ):
        """Test /queue command shows queue stats correctly even with underscore stream names."""
        from tg_gateway.handlers.command import queue_command

        update = _make_update(user_id=12345, text="/queue")
        core_client = AsyncMock()
        core_client.get_queue_stats = AsyncMock(
            return_value=_make_queue_stats(
                queued=15,
                processing=3,
                confirmed=20,
                failed=2,
                cancelled=1,
            )
        )
        core_client.get_stream_health = AsyncMock(
            return_value={
                "streams": {
                    "llm:image_tag": {"length": 5},
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

        update.message.reply_text.assert_awaited_once()
        reply = update.message.reply_text.call_args[0][0]

        # Queue stats should be displayed correctly
        assert "Pending: `15`" in reply
        assert "Processing: `3`" in reply
        assert "Confirmed: `20`" in reply
        assert "Failed: `2`" in reply
        assert "Cancelled: `1`" in reply
        # And stream health should also be visible
        assert "llm:image_tag" in reply

    @pytest.mark.asyncio
    async def test_queue_command_all_known_stream_constants_display(self):
        """Test /queue command displays all known stream names from shared_lib.redis_streams."""
        from tg_gateway.handlers.command import queue_command

        update = _make_update(user_id=12345, text="/queue")
        core_client = AsyncMock()
        core_client.get_queue_stats = AsyncMock(return_value=_make_queue_stats())
        # Test with all stream constants from shared_lib/redis_streams.py
        core_client.get_stream_health = AsyncMock(
            return_value={
                "streams": {
                    "llm:image_tag": {"length": 3},
                    "llm:intent": {"length": 5},
                    "llm:followup": {"length": 2},
                    "llm:task_match": {"length": 1},
                    "llm:email_extract": {"length": 0},
                    "notify:telegram": {"length": 10},
                }
            }
        )
        core_client.get_llm_health = AsyncMock(return_value={"status": "healthy"})
        context = _make_context(bot_data={"core_client": core_client})

        await queue_command(update, context)

        update.message.reply_text.assert_awaited_once()
        reply = update.message.reply_text.call_args[0][0]

        # All stream names should be visible
        assert "llm:image_tag" in reply
        assert "llm:intent" in reply
        assert "llm:followup" in reply
        assert "llm:task_match" in reply
        assert "llm:email_extract" in reply
        assert "notify:telegram" in reply
