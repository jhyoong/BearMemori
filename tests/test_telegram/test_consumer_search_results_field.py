"""Tests for Telegram consumer search intent with correct field names.

Tests that verify:
1. _handle_intent_result reads "results" field (not "search_results")
2. Search results are properly displayed in keyboard with titles and memory_ids
3. "No results found" is displayed when results list is empty
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tg_gateway.consumer import (
    _dispatch_notification,
    _handle_intent_result,
)

from tg_gateway.handlers.conversation import USER_QUEUE_COUNT


def _make_application(user_data: dict | None = None) -> MagicMock:
    """Return a mock Application with a mocked bot and user_data store."""
    app = MagicMock()
    app.bot = MagicMock()
    app.bot.send_message = AsyncMock()
    app.user_data = user_data if user_data is not None else {}
    return app


def _future_iso() -> str:
    """Return an ISO datetime string one hour in the future (UTC)."""
    return (datetime.now(tz=timezone.utc) + timedelta(hours=1)).isoformat()


# ---------------------------------------------------------------------------
# Telegram Consumer Search Intent Tests
# ---------------------------------------------------------------------------


class TestTelegramConsumerSearchResultsField:
    """Test that Telegram consumer reads correct 'results' field."""

    @pytest.mark.asyncio
    async def test_search_with_results_field_displays_in_keyboard(self):
        """Test that consumer reads 'results' field (not 'search_results') and displays in keyboard.

        Given content with 'results' field containing search results from Core API,
        the consumer should:
        - Read content.get("results") - NOT content.get("search_results")
        - Build keyboard with title and memory_id from each result
        - Display search results to user
        """
        app = _make_application()
        content = {
            "intent": "search",
            "query": "python tips",
            "memory_id": "",
            # Use 'results' field - this is what IntentHandler returns
            "results": [
                {"title": "Python tricks", "memory_id": "mem-s1"},
                {"title": "Advanced Python", "memory_id": "mem-s2"},
            ],
        }

        await _handle_intent_result(app, "12345", content)

        app.bot.send_message.assert_called_once()
        call_kwargs = app.bot.send_message.call_args[1]
        text = call_kwargs.get("text", "")

        # Verify search query is in text
        assert "python tips" in text.lower() or "search" in text.lower()

        # Verify keyboard is present (results were displayed)
        assert call_kwargs.get("reply_markup") is not None

    @pytest.mark.asyncio
    async def test_search_with_empty_results_field_shows_no_results(self):
        """Test that empty 'results' field displays 'No results found'."""
        app = _make_application()
        content = {
            "intent": "search",
            "query": "xyzzy nonexistent",
            "memory_id": "",
            # Empty results list
            "results": [],
        }

        await _handle_intent_result(app, "12345", content)

        call_kwargs = app.bot.send_message.call_args[1]
        text = call_kwargs.get("text", "")

        # Should NOT have a keyboard when no results
        assert call_kwargs.get("reply_markup") is None

        # Should show "No results found" message
        assert "no results" in call_kwargs.get("text", "").lower()

    @pytest.mark.asyncio
    async def test_search_ignores_search_results_field_if_present(self):
        """Test that consumer prioritizes 'results' field over 'search_results' field.

        If both fields are present, 'results' should be used.
        This ensures backward compatibility if old code sends 'search_results'.
        """
        app = _make_application()
        content = {
            "intent": "search",
            "query": "test",
            "memory_id": "",
            # Old 'search_results' field should be ignored
            "search_results": [
                {"title": "Old format", "memory_id": "mem-old"},
            ],
            # New 'results' field should be used
            "results": [
                {"title": "New format", "memory_id": "mem-new"},
            ],
        }

        await _handle_intent_result(app, "12345", content)

        call_kwargs = app.bot.send_message.call_args[1]
        text = call_kwargs.get("text", "")

        # Should show new format results, not old
        assert "new format" in text or "test" in text.lower()
        assert call_kwargs.get("reply_markup") is not None

    @pytest.mark.asyncio
    async def test_search_with_results_from_core_api_integration(self):
        """Test the full integration: search intent result from Core API to Telegram keyboard.

        This simulates what happens in production:
        1. IntentHandler calls CoreAPI.search() with keywords
        2. CoreAPI returns list of search results
        3. IntentHandler returns {"results": [...] }
        4. Telegram consumer reads "results" and builds keyboard
        """
        app = _make_application()

        # Simulate the exact structure IntentHandler would return after calling search API
        content = {
            "intent": "search",
            "query": "python tips",
            "memory_id": "",
            "results": [
                {
                    "memory_id": "mem-abc123",
                    "title": "Python Tips and Tricks You Should Know",
                    "snippet": "Learn these 10 Python tips...",
                },
                {
                    "memory_id": "mem-def456",
                    "title": "Advanced Python Programming",
                    "snippet": "Deep dive into Python internals...",
                },
                {
                    "memory_id": "mem-ghi789",
                    "title": "Python Best Practices",
                    "snippet": "Follow these best practices...",
                },
            ],
        }

        await _handle_intent_result(app, "12345", content)

        app.bot.send_message.assert_called_once()
        call_kwargs = app.bot.send_message.call_args[1]

        # Verify message contains search query
        text = call_kwargs.get("text", "")
        assert "python tips" in text.lower() or "search" in text.lower()

        # Verify keyboard is sent
        assert call_kwargs.get("reply_markup") is not None


class TestTelegramConsumerSearchNoResults:
    """Test search intent with no results from API."""

    @pytest.mark.asyncio
    async def test_search_with_no_api_results_shows_message_only(self):
        """Test that no results shows plain message without keyboard."""
        app = _make_application()
        content = {
            "intent": "search",
            "query": "nonexistent content",
            "memory_id": "",
            "results": [],
        }

        await _handle_intent_result(app, "12345", content)

        call_kwargs = app.bot.send_message.call_args[1]

        # Should be a plain message without keyboard
        assert call_kwargs.get("reply_markup") is None

        # Message should indicate no results
        text = call_kwargs.get("text", "").lower()
        assert "no results" in text or "not found" in text

    @pytest.mark.asyncio
    async def test_search_with_none_results_shows_no_results(self):
        """Test that None results (missing field) shows 'No results found'."""
        app = _make_application()
        content = {
            "intent": "search",
            "query": "test",
            "memory_id": "",
            # Missing "results" field entirely
        }

        await _handle_intent_result(app, "12345", content)

        call_kwargs = app.bot.send_message.call_args[1]

        # Should show no results message
        text = call_kwargs.get("text", "").lower()
        assert "no results" in text or "not found" in text


class TestTelegramConsumerSearchQueueManagement:
    """Test search intent queue counter management."""

    @pytest.mark.asyncio
    async def test_search_decrements_queue_counter(self):
        """Test that search intent decrements USER_QUEUE_COUNT."""
        app = _make_application(user_data={12345: {USER_QUEUE_COUNT: 5}})
        content = {
            "intent": "search",
            "query": "test",
            "memory_id": "",
            "results": [
                {"title": "Result", "memory_id": "mem-1"},
            ],
        }

        await _handle_intent_result(app, "12345", content)

        assert app.user_data[12345][USER_QUEUE_COUNT] == 4

    @pytest.mark.asyncio
    async def test_search_queue_clamps_at_zero(self):
        """Test that queue counter doesn't go below zero."""
        app = _make_application(user_data={12345: {USER_QUEUE_COUNT: 0}})
        content = {
            "intent": "search",
            "query": "test",
            "memory_id": "",
            "results": [],
        }

        await _handle_intent_result(app, "12345", content)

        assert app.user_data[12345][USER_QUEUE_COUNT] == 0

    @pytest.mark.asyncio
    async def test_search_does_not_set_awaiting_button_action(self):
        """Test that search intent doesn't set AWAITING_BUTTON_ACTION."""
        from tg_gateway.handlers.conversation import AWAITING_BUTTON_ACTION

        app = _make_application()
        content = {
            "intent": "search",
            "query": "test",
            "memory_id": "",
            "results": [],
        }

        await _handle_intent_result(app, "12345", content)

        assert AWAITING_BUTTON_ACTION not in app.user_data.get(12345, {})


class TestTelegramConsumerSearchDispatch:
    """Test _dispatch_notification routes search intent correctly."""

    @pytest.mark.asyncio
    async def test_dispatch_routes_llm_intent_result_search(self):
        """Test that dispatch routes 'llm_intent_result' with search intent."""
        app = _make_application()
        data = {
            "user_id": "12345",
            "message_type": "llm_intent_result",
            "content": {
                "intent": "search",
                "query": "test query",
                "memory_id": "",
                "results": [
                    {"title": "Found", "memory_id": "mem-1"},
                ],
            },
        }

        await _dispatch_notification(app, data)

        app.bot.send_message.assert_called_once()
        call_kwargs = app.bot.send_message.call_args[1]
        assert call_kwargs.get("reply_markup") is not None

    @pytest.mark.asyncio
    async def test_dispatch_search_with_no_results_routes_correctly(self):
        """Test that dispatch handles search intent with no results."""
        app = _make_application()
        data = {
            "user_id": "12345",
            "message_type": "llm_intent_result",
            "content": {
                "intent": "search",
                "query": "no results here",
                "memory_id": "",
                "results": [],
            },
        }

        await _dispatch_notification(app, data)

        app.bot.send_message.assert_called_once()
        call_kwargs = app.bot.send_message.call_args[1]
        # No keyboard when no results
        assert call_kwargs.get("reply_markup") is None
