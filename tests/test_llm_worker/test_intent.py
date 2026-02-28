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

    @pytest.mark.asyncio
    async def test_search_intent_does_not_create_memory(
        self, handler, mock_llm_client, mock_core_api
    ):
        """Test that search intent does NOT create a memory.

        Given a search intent, the handler should:
        - NOT call core_api.create_memory
        - Return the search results without any memory_id
        """
        # Setup mock to track create_memory calls
        mock_core_api.create_memory = AsyncMock()
        mock_core_api.search = AsyncMock(
            return_value=[{"memory": {"id": "mem-1", "content": "Test result"}}]
        )

        original_ts = "2026-02-24T10:00:00Z"
        mock_llm_client.complete = AsyncMock(
            return_value='{"intent": "search", "query": "butter recipe", "keywords": ["butter", "recipe"]}'
        )

        result = await handler.handle(
            "job-search-001",
            {
                "message": "Find my butter recipe",
                "original_timestamp": original_ts,
                "user_id": 12345,
            },
            user_id=12345,
        )

        # Verify search intent does NOT call create_memory
        mock_core_api.create_memory.assert_not_called()

        # Verify search results are returned
        assert result is not None
        assert result.get("intent") == "search"
        assert "results" in result

    @pytest.mark.asyncio
    async def test_reminder_intent_creates_memory(
        self, handler, mock_llm_client, mock_core_api
    ):
        """Test that reminder intent creates a memory via Core API.

        Given a reminder intent, the handler should:
        - Call core_api.create_memory with the original message text
        - Add the returned memory_id to the result
        """
        # Setup mock to return a memory id (Core API returns "id", not "memory_id")
        mock_core_api.create_memory = AsyncMock(
            return_value={"id": "mem-reminder-123"}
        )

        original_ts = "2026-02-24T10:00:00Z"
        mock_llm_client.complete = AsyncMock(
            return_value='{"intent": "reminder", "action": "buy groceries", "time": "tomorrow", "resolved_time": "2026-02-25T10:00:00Z"}'
        )

        result = await handler.handle(
            "job-reminder-001",
            {
                "message": "Remind me to buy groceries",
                "original_timestamp": original_ts,
                "user_id": 12345,
            },
            user_id=12345,
        )

        # Verify create_memory was called with the message content
        mock_core_api.create_memory.assert_called_once()
        call_args = mock_core_api.create_memory.call_args
        # Should be called with content = message text
        assert (
            call_args.kwargs.get("content") == "Remind me to buy groceries"
            or call_args.args[0].get("content") == "Remind me to buy groceries"
        )

        # Verify memory_id is in result
        assert result is not None
        assert result.get("intent") == "reminder"
        assert result.get("memory_id") == "mem-reminder-123"

    @pytest.mark.asyncio
    async def test_task_intent_creates_memory(
        self, handler, mock_llm_client, mock_core_api
    ):
        """Test that task intent creates a memory via Core API.

        Given a task intent, the handler should:
        - Call core_api.create_memory with the original message text
        - Add the returned memory_id to the result
        """
        # Setup mock to return a memory_id
        mock_core_api.create_memory = AsyncMock(
            return_value={"id": "mem-task-456"}
        )

        original_ts = "2026-02-24T10:00:00Z"
        mock_llm_client.complete = AsyncMock(
            return_value='{"intent": "task", "description": "submit report", "due_time": "next week", "resolved_due_time": "2026-03-03T10:00:00Z"}'
        )

        result = await handler.handle(
            "job-task-001",
            {
                "message": "Create task to submit report",
                "original_timestamp": original_ts,
                "user_id": 12345,
            },
            user_id=12345,
        )

        # Verify create_memory was called with the message content
        mock_core_api.create_memory.assert_called_once()

        # Verify memory_id is in result
        assert result is not None
        assert result.get("intent") == "task"
        assert result.get("memory_id") == "mem-task-456"

    @pytest.mark.asyncio
    async def test_general_note_intent_creates_memory(
        self, handler, mock_llm_client, mock_core_api
    ):
        """Test that general_note intent creates a memory via Core API.

        Given a general_note intent, the handler should:
        - Call core_api.create_memory with the original message text
        - Add the returned memory_id to the result
        """
        # Setup mock to return a memory_id
        mock_core_api.create_memory = AsyncMock(
            return_value={"id": "mem-note-789"}
        )

        original_ts = "2026-02-24T10:00:00Z"
        mock_llm_client.complete = AsyncMock(
            return_value='{"intent": "general_note", "suggested_tags": ["ideas", "project"]}'
        )

        result = await handler.handle(
            "job-note-001",
            {
                "message": "Note: Great idea for the project",
                "original_timestamp": original_ts,
                "user_id": 12345,
            },
            user_id=12345,
        )

        # Verify create_memory was called with the message content
        mock_core_api.create_memory.assert_called_once()

        # Verify memory_id is in result
        assert result is not None
        assert result.get("intent") == "general_note"
        assert result.get("memory_id") == "mem-note-789"

    @pytest.mark.asyncio
    async def test_ambiguous_intent_creates_memory(
        self, handler, mock_llm_client, mock_core_api
    ):
        """Test that ambiguous intent creates a memory via Core API.

        Given an ambiguous intent, the handler should:
        - Call core_api.create_memory with the original message text (for followup context)
        - Add the returned memory_id to the result
        """
        # Setup mock to return a memory_id
        mock_core_api.create_memory = AsyncMock(
            return_value={"id": "mem-ambiguous-999"}
        )

        original_ts = "2026-02-24T10:00:00Z"
        mock_llm_client.complete = AsyncMock(
            return_value='{"intent": "ambiguous", "keywords": []}'
        )

        result = await handler.handle(
            "job-ambiguous-001",
            {
                "message": "do something",
                "original_timestamp": original_ts,
                "user_id": 12345,
            },
            user_id=12345,
        )

        # Verify create_memory was called with the message content
        mock_core_api.create_memory.assert_called_once()

        # Verify memory_id is in result
        assert result is not None
        assert result.get("intent") == "ambiguous"
        assert result.get("memory_id") == "mem-ambiguous-999"


# ---------------------------------------------------------------------------
# Specific phrase tests - exact examples from acceptance criteria
# ---------------------------------------------------------------------------


class TestIntentSpecificPhrases:
    """Test specific example phrases from acceptance criteria."""

    @pytest.mark.asyncio
    async def test_search_all_images_about_anime_no_memory_created(
        self, handler, mock_llm_client, mock_core_api
    ):
        """Test 'Search for all images about anime' does NOT create memory.

        Given a search query, the handler should:
        - NOT call core_api.create_memory
        - Call core_api.search with keywords
        - Return search results without memory_id
        """
        # Setup mock to track create_memory calls
        mock_core_api.create_memory = AsyncMock()
        mock_core_api.search = AsyncMock(
            return_value=[
                {"memory": {"id": "mem-1", "content": "Anime image 1"}},
                {"memory": {"id": "mem-2", "content": "Anime image 2"}},
            ]
        )

        original_ts = "2026-02-24T10:00:00Z"
        mock_llm_client.complete = AsyncMock(
            return_value='{"intent": "search", "query": "all images about anime", "keywords": ["anime", "images"]}'
        )

        result = await handler.handle(
            "job-search-anime-001",
            {
                "message": "Search for all images about anime",
                "original_timestamp": original_ts,
                "user_id": 12345,
            },
            user_id=12345,
        )

        # Verify search intent does NOT call create_memory
        mock_core_api.create_memory.assert_not_called()

        # Verify search is called with the keywords
        mock_core_api.search.assert_called_once()
        search_call = mock_core_api.search.call_args
        assert (
            "anime images" in str(search_call).lower()
            or "anime" in str(search_call).lower()
        )

        # Verify result contains search results
        assert result is not None
        assert result.get("intent") == "search"
        assert "results" in result
        assert len(result.get("results", [])) == 2
        # memory_id should be None for search (not created)
        assert result.get("memory_id") is None

    @pytest.mark.asyncio
    async def test_remind_me_to_call_mom_tomorrow_creates_memory(
        self, handler, mock_llm_client, mock_core_api
    ):
        """Test 'Remind me to call mom tomorrow' creates memory.

        Given a reminder intent, the handler should:
        - Call core_api.create_memory with the original message text
        - Return the memory_id in result
        """
        # Setup mock to return a memory_id
        mock_core_api.create_memory = AsyncMock(
            return_value={"id": "mem-reminder-mom-123"}
        )

        original_ts = "2026-02-24T10:00:00Z"
        mock_llm_client.complete = AsyncMock(
            return_value='{"intent": "reminder", "action": "call mom", "time": "tomorrow", "resolved_time": "2026-02-25T10:00:00Z"}'
        )

        result = await handler.handle(
            "job-reminder-mom-001",
            {
                "message": "Remind me to call mom tomorrow",
                "original_timestamp": original_ts,
                "user_id": 12345,
            },
            user_id=12345,
        )

        # Verify create_memory was called with the message content
        mock_core_api.create_memory.assert_called_once()
        call_args = mock_core_api.create_memory.call_args
        # Check content contains the reminder text
        content_arg = call_args.kwargs.get("content") or call_args.args[0].get(
            "content"
        )
        assert "call mom" in content_arg.lower()

        # Verify memory_id is in result
        assert result is not None
        assert result.get("intent") == "reminder"
        assert result.get("memory_id") == "mem-reminder-mom-123"
        # Verify action is extracted
        assert result.get("action") == "call mom"

    @pytest.mark.asyncio
    async def test_add_task_to_finish_report_by_friday_creates_memory(
        self, handler, mock_llm_client, mock_core_api
    ):
        """Test 'Add task to finish report by Friday' creates memory.

        Given a task intent, the handler should:
        - Call core_api.create_memory with the original message text
        - Return the memory_id in result
        """
        # Setup mock to return a memory_id
        mock_core_api.create_memory = AsyncMock(
            return_value={"id": "mem-task-report-456"}
        )

        original_ts = "2026-02-24T10:00:00Z"
        mock_llm_client.complete = AsyncMock(
            return_value='{"intent": "task", "description": "finish report", "due_time": "friday", "resolved_due_time": "2026-02-27T17:00:00Z"}'
        )

        result = await handler.handle(
            "job-task-report-001",
            {
                "message": "Add task to finish report by Friday",
                "original_timestamp": original_ts,
                "user_id": 12345,
            },
            user_id=12345,
        )

        # Verify create_memory was called with the message content
        mock_core_api.create_memory.assert_called_once()
        call_args = mock_core_api.create_memory.call_args
        # Check content contains the task description
        content_arg = call_args.kwargs.get("content") or call_args.args[0].get(
            "content"
        )
        assert "finish report" in content_arg.lower()

        # Verify memory_id is in result
        assert result is not None
        assert result.get("intent") == "task"
        assert result.get("memory_id") == "mem-task-report-456"
        # Verify description is extracted
        assert result.get("description") == "finish report"

    @pytest.mark.asyncio
    async def test_search_phrase_triggers_search_api(
        self, handler, mock_llm_client, mock_core_api
    ):
        """Test that search phrase triggers Core API search endpoint.

        Given a search query with keywords, the handler should:
        - Call core_api.search with keywords
        - Return search results
        """
        mock_core_api.create_memory = AsyncMock()
        mock_core_api.search = AsyncMock(
            return_value=[{"memory": {"id": "mem-1", "content": "Found result"}}]
        )

        original_ts = "2026-02-24T10:00:00Z"
        mock_llm_client.complete = AsyncMock(
            return_value='{"intent": "search", "query": "butter recipe", "keywords": ["butter", "recipe"]}'
        )

        result = await handler.handle(
            "job-search-recipe-001",
            {
                "message": "Find my butter recipe",
                "original_timestamp": original_ts,
                "user_id": 12345,
            },
            user_id=12345,
        )

        # Verify search was called
        mock_core_api.search.assert_called_once()
        # Verify search results are in response
        assert result is not None
        assert "results" in result
        assert len(result["results"]) == 1
