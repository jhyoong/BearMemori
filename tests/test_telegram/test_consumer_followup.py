"""Tests for storing full context in PENDING_LLM_CONVERSATION for ambiguous followup.

Covers:
- _handle_intent_result with intent="ambiguous" stores user_timezone, original_timestamp,
  source_chat_id, and source_message_id in the pending conversation state.
- Missing fields in incoming content result in None/empty values in stored dict.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from tg_gateway.consumer import _handle_intent_result
from tg_gateway.handlers.conversation import PENDING_LLM_CONVERSATION


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_application(user_data: dict | None = None) -> MagicMock:
    """Return a mock Application with a mocked bot and user_data store."""
    app = MagicMock()
    app.bot = MagicMock()
    app.bot.send_message = AsyncMock()
    app.user_data = user_data if user_data is not None else {}
    app.bot_data = {}
    return app


# ---------------------------------------------------------------------------
# _handle_intent_result — ambiguous intent context storage
# ---------------------------------------------------------------------------


class TestAmbiguousFollowupContext:
    """Tests for storing full context in PENDING_LLM_CONVERSATION."""

    @pytest.mark.asyncio
    async def test_ambiguous_stores_user_timezone_in_pending_conversation(self):
        """Test that user_timezone is stored when content contains user_timezone."""
        app = _make_application()
        content = {
            "intent": "ambiguous",
            "query": "Do the thing",
            "memory_id": "mem-a1",
            "followup_question": "Should I create a task or a reminder?",
            "user_timezone": "America/New_York",
            "original_timestamp": "2024-01-15T10:30:00",
            "source_chat_id": "123456",
            "source_message_id": "789",
        }

        await _handle_intent_result(app, "12345", content)

        pending = app.user_data[12345].get(PENDING_LLM_CONVERSATION)
        assert pending is not None
        assert "user_timezone" in pending
        assert pending["user_timezone"] == "America/New_York"

    @pytest.mark.asyncio
    async def test_ambiguous_stores_original_timestamp_in_pending_conversation(self):
        """Test that original_timestamp is stored when present in content."""
        app = _make_application()
        content = {
            "intent": "ambiguous",
            "query": "Do the thing",
            "memory_id": "mem-a2",
            "followup_question": "What exactly do you mean?",
            "user_timezone": "UTC",
            "original_timestamp": "2024-01-15T10:30:00",
            "source_chat_id": "123456",
            "source_message_id": "789",
        }

        await _handle_intent_result(app, "12345", content)

        pending = app.user_data[12345].get(PENDING_LLM_CONVERSATION)
        assert pending is not None
        assert "original_timestamp" in pending
        assert pending["original_timestamp"] == "2024-01-15T10:30:00"

    @pytest.mark.asyncio
    async def test_ambiguous_stores_source_chat_id_in_pending_conversation(self):
        """Test that source_chat_id is stored when present in content."""
        app = _make_application()
        content = {
            "intent": "ambiguous",
            "query": "do something",
            "memory_id": "mem-a3",
            "followup_question": "Please clarify.",
            "user_timezone": "Europe/London",
            "original_timestamp": "2024-02-20T14:00:00",
            "source_chat_id": "999888777",
            "source_message_id": "555",
        }

        await _handle_intent_result(app, "12345", content)

        pending = app.user_data[12345].get(PENDING_LLM_CONVERSATION)
        assert pending is not None
        assert "source_chat_id" in pending
        assert pending["source_chat_id"] == "999888777"

    @pytest.mark.asyncio
    async def test_ambiguous_stores_source_message_id_in_pending_conversation(self):
        """Test that source_message_id is stored when present in content."""
        app = _make_application()
        content = {
            "intent": "ambiguous",
            "query": "huh",
            "memory_id": "mem-a4",
            "followup_question": "Can you be more specific?",
            "user_timezone": "Asia/Tokyo",
            "original_timestamp": "2024-03-10T08:15:00",
            "source_chat_id": "111222333",
            "source_message_id": "444",
        }

        await _handle_intent_result(app, "12345", content)

        pending = app.user_data[12345].get(PENDING_LLM_CONVERSATION)
        assert pending is not None
        assert "source_message_id" in pending
        assert pending["source_message_id"] == "444"

    @pytest.mark.asyncio
    async def test_ambiguous_stores_all_four_new_fields_together(self):
        """Test that all four new fields (user_timezone, original_timestamp,
        source_chat_id, source_message_id) are stored together in pending conversation."""
        app = _make_application()
        content = {
            "intent": "ambiguous",
            "query": "remind me something",
            "memory_id": "mem-full1",
            "followup_question": "Task or reminder?",
            "user_timezone": "America/Los_Angeles",
            "original_timestamp": "2024-06-01T12:00:00",
            "source_chat_id": "777888999",
            "source_message_id": "111222",
        }

        await _handle_intent_result(app, "12345", content)

        pending = app.user_data[12345].get(PENDING_LLM_CONVERSATION)
        assert pending is not None
        # Verify all four new fields are present
        assert "user_timezone" in pending
        assert "original_timestamp" in pending
        assert "source_chat_id" in pending
        assert "source_message_id" in pending
        # Verify values
        assert pending["user_timezone"] == "America/Los_Angeles"
        assert pending["original_timestamp"] == "2024-06-01T12:00:00"
        assert pending["source_chat_id"] == "777888999"
        assert pending["source_message_id"] == "111222"
        # Verify existing fields are still present
        assert pending["memory_id"] == "mem-full1"
        assert pending["original_text"] == "remind me something"
        assert pending["followup_question"] == "Task or reminder?"


class TestAmbiguousFollowupMissingFields:
    """Tests for handling missing fields in incoming content."""

    @pytest.mark.asyncio
    async def test_ambiguous_missing_user_timezone_results_in_none(self):
        """Test that user_timezone is None when not provided in content."""
        app = _make_application()
        content = {
            "intent": "ambiguous",
            "query": "Do the thing",
            "memory_id": "mem-b1",
            "followup_question": "Should I create a task or a reminder?",
            # No user_timezone
            "original_timestamp": "2024-01-15T10:30:00",
            "source_chat_id": "123456",
            "source_message_id": "789",
        }

        await _handle_intent_result(app, "12345", content)

        pending = app.user_data[12345].get(PENDING_LLM_CONVERSATION)
        assert pending is not None
        assert "user_timezone" in pending
        assert pending["user_timezone"] is None

    @pytest.mark.asyncio
    async def test_ambiguous_missing_original_timestamp_results_in_none(self):
        """Test that original_timestamp is None when not provided in content."""
        app = _make_application()
        content = {
            "intent": "ambiguous",
            "query": "Do the thing",
            "memory_id": "mem-b2",
            "followup_question": "Should I create a task or a reminder?",
            "user_timezone": "America/New_York",
            # No original_timestamp
            "source_chat_id": "123456",
            "source_message_id": "789",
        }

        await _handle_intent_result(app, "12345", content)

        pending = app.user_data[12345].get(PENDING_LLM_CONVERSATION)
        assert pending is not None
        assert "original_timestamp" in pending
        assert pending["original_timestamp"] is None

    @pytest.mark.asyncio
    async def test_ambiguous_missing_source_chat_id_results_in_none(self):
        """Test that source_chat_id is None when not provided in content."""
        app = _make_application()
        content = {
            "intent": "ambiguous",
            "query": "Do the thing",
            "memory_id": "mem-b3",
            "followup_question": "Should I create a task or a reminder?",
            "user_timezone": "America/New_York",
            "original_timestamp": "2024-01-15T10:30:00",
            # No source_chat_id
            "source_message_id": "789",
        }

        await _handle_intent_result(app, "12345", content)

        pending = app.user_data[12345].get(PENDING_LLM_CONVERSATION)
        assert pending is not None
        assert "source_chat_id" in pending
        assert pending["source_chat_id"] is None

    @pytest.mark.asyncio
    async def test_ambiguous_missing_source_message_id_results_in_none(self):
        """Test that source_message_id is None when not provided in content."""
        app = _make_application()
        content = {
            "intent": "ambiguous",
            "query": "Do the thing",
            "memory_id": "mem-b4",
            "followup_question": "Should I create a task or a reminder?",
            "user_timezone": "America/New_York",
            "original_timestamp": "2024-01-15T10:30:00",
            "source_chat_id": "123456",
            # No source_message_id
        }

        await _handle_intent_result(app, "12345", content)

        pending = app.user_data[12345].get(PENDING_LLM_CONVERSATION)
        assert pending is not None
        assert "source_message_id" in pending
        assert pending["source_message_id"] is None

    @pytest.mark.asyncio
    async def test_ambiguous_all_fields_missing_results_in_none_for_all(self):
        """Test that all four new fields are None when none are provided in content."""
        app = _make_application()
        content = {
            "intent": "ambiguous",
            "query": "Do the thing",
            "memory_id": "mem-b5",
            "followup_question": "Should I create a task or a reminder?",
            # No user_timezone, original_timestamp, source_chat_id, source_message_id
        }

        await _handle_intent_result(app, "12345", content)

        pending = app.user_data[12345].get(PENDING_LLM_CONVERSATION)
        assert pending is not None
        # All four new fields should be present (as None)
        assert "user_timezone" in pending
        assert "original_timestamp" in pending
        assert "source_chat_id" in pending
        assert "source_message_id" in pending
        assert pending["user_timezone"] is None
        assert pending["original_timestamp"] is None
        assert pending["source_chat_id"] is None
        assert pending["source_message_id"] is None
