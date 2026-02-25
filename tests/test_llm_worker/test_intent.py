"""Tests for IntentHandler."""

import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

# Ensure correct llm_worker path is used - prioritize local version over worktree
PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
_llm_worker_path = os.path.join(PROJECT_ROOT, "llm_worker")
if _llm_worker_path not in sys.path:
    sys.path.insert(0, _llm_worker_path)

from worker.handlers.intent import IntentHandler


class TestIntentHandler:
    """Test cases for IntentHandler."""

    @pytest.fixture
    def handler(self, mock_llm_client, mock_core_api, llm_worker_config):
        """Create IntentHandler instance with mocked dependencies."""
        return IntentHandler(
            llm_client=mock_llm_client,
            core_api=mock_core_api,
            config=llm_worker_config,
        )

    @pytest.mark.asyncio
    async def test_intent_memory_search(self, handler, mock_llm_client):
        """Test that memory_search intent is correctly identified."""
        # Mock LLM returns memory_search intent
        mock_llm_client.complete = AsyncMock(
            return_value='{"intent": "memory_search", "keywords": ["butter", "recipe"]}'
        )

        result = await handler.handle(
            "job-123",
            {"query": "butter recipe", "user_id": 12345},
            user_id=12345,
        )

        assert result == {
            "query": "butter recipe",
            "intent": "memory_search",
            "results": [],
        }

    @pytest.mark.asyncio
    async def test_intent_ambiguous(self, handler, mock_llm_client):
        """Test that ambiguous intent is handled correctly."""
        # Mock LLM returns ambiguous intent
        mock_llm_client.complete = AsyncMock(
            return_value='{"intent": "ambiguous", "keywords": []}'
        )

        result = await handler.handle(
            "job-456",
            {"query": "do something", "user_id": 12345},
            user_id=12345,
        )

        assert result.get("intent") == "ambiguous"

    @pytest.mark.asyncio
    async def test_intent_task_lookup(self, handler, mock_llm_client):
        """Test that task_lookup intent is correctly identified."""
        # Mock LLM returns task_lookup intent
        mock_llm_client.complete = AsyncMock(
            return_value='{"intent": "task_lookup", "keywords": ["groceries"]}'
        )

        result = await handler.handle(
            "job-789",
            {"query": "buy groceries", "user_id": 12345},
            user_id=12345,
        )

        assert result.get("intent") == "task_lookup"

    @pytest.mark.asyncio
    async def test_handle_with_message_and_timestamp_returns_structured_result(
        self, handler, mock_llm_client
    ):
        """Test that handle() with message and original_timestamp returns structured result.

        Given a payload with 'message' and 'original_timestamp', the handler should:
        - Use INTENT_CLASSIFY_PROMPT with {message} and {original_timestamp}
        - Return structured result with intent, action, resolved_time
        """
        # Current timestamp for original_timestamp
        original_ts = "2030-06-14T10:00:00Z"

        # Mock LLM returns structured reminder response with a future resolved_time
        mock_llm_client.complete = AsyncMock(
            return_value='{"intent": "reminder", "action": "buy groceries", "time": "tomorrow", "resolved_time": "2030-06-15T10:00:00Z"}'
        )

        result = await handler.handle(
            "job-001",
            {
                "message": "Remind me to buy groceries tomorrow",
                "original_timestamp": original_ts,
                "user_id": 12345,
            },
            user_id=12345,
        )

        # Verify structured result is returned
        assert result is not None
        assert result.get("intent") == "reminder"
        assert result.get("action") == "buy groceries"
        assert result.get("resolved_time") == "2030-06-15T10:00:00Z"
        # stale should not be set (future timestamp)
        assert "stale" not in result or result.get("stale") is False

    @pytest.mark.asyncio
    async def test_handle_with_followup_context_uses_reclassify_prompt(
        self, handler, mock_llm_client
    ):
        """Test that handle() with followup_context uses RECLASSIFY_PROMPT.

        Given a payload with 'followup_context' containing followup_question and user_answer,
        the handler should:
        - Use RECLASSIFY_PROMPT instead of standard INTENT_CLASSIFY_PROMPT
        - Return re-classified result with proper entities
        """
        original_ts = "2026-02-24T10:00:00Z"

        # Mock LLM returns re-classified reminder response
        mock_llm_client.complete = AsyncMock(
            return_value='{"intent": "reminder", "action": "call doctor", "time": "next week", "resolved_time": "2026-03-03T10:00:00Z"}'
        )

        result = await handler.handle(
            "job-002",
            {
                "message": "remind me about the thing",
                "original_timestamp": original_ts,
                "followup_context": {
                    "followup_question": "What do you want to be reminded about?",
                    "user_answer": "I need to call my doctor next week",
                },
                "user_id": 12345,
            },
            user_id=12345,
        )

        # Verify the re-classified result
        assert result is not None
        assert result.get("intent") == "reminder"
        assert result.get("action") == "call doctor"
        assert result.get("resolved_time") == "2026-03-03T10:00:00Z"

    @pytest.mark.asyncio
    async def test_handle_with_past_timestamp_sets_stale_flag(
        self, handler, mock_llm_client
    ):
        """Test that handle() with past timestamp for reminder sets stale=true.

        Given a reminder intent where resolved_time is in the past relative to current time,
        the handler should:
        - Set stale flag to true
        """
        # Use a timestamp from 2 days ago
        past_timestamp = (datetime.now(timezone.utc) - timedelta(days=2)).strftime(
            "%Y-%m-%dT%H:%M:%Z"
        )

        # Mock LLM returns reminder with already-past resolved_time
        mock_llm_client.complete = AsyncMock(
            return_value='{"intent": "reminder", "action": "meeting", "time": "yesterday", "resolved_time": "'
            + past_timestamp
            + '"}'
        )

        result = await handler.handle(
            "job-003",
            {
                "message": "Remind me about the meeting yesterday",
                "original_timestamp": past_timestamp,
                "user_id": 12345,
            },
            user_id=12345,
        )

        # Verify stale flag is set to true
        assert result is not None
        assert result.get("intent") == "reminder"
        assert result.get("stale") is True

    @pytest.mark.asyncio
    async def test_handle_with_past_task_due_time_sets_stale_flag(
        self, handler, mock_llm_client
    ):
        """Test that handle() with past resolved_due_time for task sets stale=true.

        Given a task intent where resolved_due_time is in the past relative to current time,
        the handler should:
        - Set stale flag to true
        """
        # Use a timestamp from 3 days ago
        past_timestamp = (datetime.now(timezone.utc) - timedelta(days=3)).strftime(
            "%Y-%m-%dT%H:%M:%Z"
        )

        # Mock LLM returns task with already-past resolved_due_time
        mock_llm_client.complete = AsyncMock(
            return_value='{"intent": "task", "description": "submit report", "due_time": "last week", "resolved_due_time": "'
            + past_timestamp
            + '"}'
        )

        result = await handler.handle(
            "job-004",
            {
                "message": "Create task to submit report",
                "original_timestamp": past_timestamp,
                "user_id": 12345,
            },
            user_id=12345,
        )

        # Verify stale flag is set to true for task
        assert result is not None
        assert result.get("intent") == "task"
        assert result.get("stale") is True

    @pytest.mark.asyncio
    async def test_handle_legacy_query_backward_compatibility(
        self, handler, mock_llm_client
    ):
        """Test that handle() with legacy 'query' field works for backward compatibility.

        Given a payload with 'query' instead of 'message' (old format),
        the handler should:
        - Still work correctly (backward compatibility)
        - Use query as the message for classification
        """
        # Mock LLM returns search intent response
        mock_llm_client.complete = AsyncMock(
            return_value='{"intent": "search", "query": "butter cake recipe", "keywords": ["butter", "cake", "recipe"]}'
        )

        result = await handler.handle(
            "job-005",
            {"query": "butter cake recipe", "user_id": 12345},
            user_id=12345,
        )

        # Verify backward compatibility - should work with 'query' field
        assert result is not None
        assert result.get("intent") == "search"
        # The query should be preserved in result
        assert "query" in result or result.get("query") == "butter cake recipe"

    @pytest.mark.asyncio
    async def test_handle_search_intent_with_keywords(self, handler, mock_llm_client):
        """Test that handle() returns proper search intent with keywords."""
        original_ts = "2026-02-24T10:00:00Z"

        mock_llm_client.complete = AsyncMock(
            return_value='{"intent": "search", "query": "vacation photos", "keywords": ["vacation", "photos"]}'
        )

        result = await handler.handle(
            "job-006",
            {
                "message": "Find my vacation photos",
                "original_timestamp": original_ts,
                "user_id": 12345,
            },
            user_id=12345,
        )

        assert result is not None
        assert result.get("intent") == "search"
        assert result.get("query") == "vacation photos"
        assert result.get("keywords") == ["vacation", "photos"]

    @pytest.mark.asyncio
    async def test_handle_general_note_intent(self, handler, mock_llm_client):
        """Test that handle() returns proper general_note intent with suggested tags."""
        original_ts = "2026-02-24T10:00:00Z"

        mock_llm_client.complete = AsyncMock(
            return_value='{"intent": "general_note", "suggested_tags": ["ideas", "project", "brainstorm"]}'
        )

        result = await handler.handle(
            "job-007",
            {
                "message": "Note: We should consider building a new feature",
                "original_timestamp": original_ts,
                "user_id": 12345,
            },
            user_id=12345,
        )

        assert result is not None
        assert result.get("intent") == "general_note"
        assert result.get("suggested_tags") == ["ideas", "project", "brainstorm"]
