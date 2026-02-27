"""Tests for IntentHandler search intent behavior with Core API integration.

Tests that verify:
1. IntentHandler calls CoreAPIClient.search() when intent is "search"
2. Search results from API are returned in the "results" field
3. Keywords are extracted from the query
"""

import os
import sys
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


class TestIntentHandlerSearchIntegration:
    """Test cases for IntentHandler search intent with Core API integration."""

    @pytest.fixture
    def handler(self, mock_llm_client, mock_core_api, llm_worker_config):
        """Create IntentHandler instance with mocked dependencies."""
        return IntentHandler(
            llm_client=mock_llm_client,
            core_api=mock_core_api,
            config=llm_worker_config,
        )

    @pytest.mark.asyncio
    async def test_search_intent_calls_core_api_search_with_keywords(
        self, handler, mock_llm_client, mock_core_api
    ):
        """Test that search intent calls CoreAPIClient.search() with extracted keywords.

        Given a payload with search intent and keywords extracted from the query,
        the handler should:
        - Extract keywords from LLM response
        - Call core_api.search() with the keywords joined as query string
        - Return results from the API in the "results" field
        """
        original_ts = "2026-02-24T10:00:00Z"
        search_keywords = ["python", "tips"]
        search_query = "python tips"

        # Mock LLM returns search intent with keywords
        mock_llm_client.complete = AsyncMock(
            return_value='{"intent": "search", "keywords": ["python", "tips"]}'
        )

        # Mock CoreAPI search to return test results
        mock_search_results = [
            {"memory_id": "mem-1", "title": "Python Basics"},
            {"memory_id": "mem-2", "title": "Advanced Python Tips"},
        ]
        mock_core_api.search = AsyncMock(return_value=mock_search_results)

        result = await handler.handle(
            "job-001",
            {
                "message": "Find python tips",
                "original_timestamp": original_ts,
                "user_id": 12345,
            },
            user_id=12345,
        )

        # Verify search API was called with correct query (keywords joined) and user_id
        mock_core_api.search.assert_awaited_once_with(search_query, owner_user_id=12345)

        # Verify results are populated from API response
        assert result is not None
        assert result.get("intent") == "search"
        assert result.get("query") == "Find python tips"
        assert result.get("results") == mock_search_results

    @pytest.mark.asyncio
    async def test_search_intent_returns_empty_results_when_api_returns_empty(
        self, handler, mock_llm_client, mock_core_api
    ):
        """Test that search intent returns empty results when API returns empty list."""
        original_ts = "2026-02-24T10:00:00Z"

        mock_llm_client.complete = AsyncMock(
            return_value='{"intent": "search", "keywords": ["nonexistent"]}'
        )
        mock_core_api.search = AsyncMock(return_value=[])

        result = await handler.handle(
            "job-002",
            {
                "message": "Find nonexistent content",
                "original_timestamp": original_ts,
                "user_id": 12345,
            },
            user_id=12345,
        )

        assert result.get("results") == []

    @pytest.mark.asyncio
    async def test_search_intent_legacy_format_calls_search_api(
        self, handler, mock_llm_client, mock_core_api
    ):
        """Test that legacy format (query field) also calls search API."""
        search_keywords = ["butter", "recipe"]
        search_query = "butter recipe"

        mock_llm_client.complete = AsyncMock(
            return_value='{"intent": "search", "keywords": ["butter", "recipe"]}'
        )

        mock_search_results = [
            {"memory_id": "mem-legacy", "title": "Butter Cake Recipe"},
        ]
        mock_core_api.search = AsyncMock(return_value=mock_search_results)

        result = await handler.handle(
            "job-003",
            {"query": "butter recipe", "user_id": 12345},
            user_id=12345,
        )

        # Legacy format should also call search API
        mock_core_api.search.assert_awaited_once_with(search_query, owner_user_id=12345)
        assert result.get("results") == mock_search_results


class TestIntentHandlerSearchPassesUserId:
    """Test that IntentHandler passes user_id as owner_user_id to core_api.search()."""

    @pytest.fixture
    def handler(self, mock_llm_client, mock_core_api, llm_worker_config):
        return IntentHandler(
            llm_client=mock_llm_client,
            core_api=mock_core_api,
            config=llm_worker_config,
        )

    @pytest.mark.asyncio
    async def test_search_passes_user_id_as_owner(
        self, handler, mock_llm_client, mock_core_api
    ):
        """IntentHandler must pass user_id as owner_user_id to core_api.search().

        The Core API /search endpoint requires owner as a mandatory query param.
        Without it every search returns 422 Unprocessable Entity.
        """
        mock_llm_client.complete = AsyncMock(
            return_value='{"intent": "search", "keywords": ["anime"]}'
        )
        mock_core_api.search = AsyncMock(return_value=[])

        await handler.handle(
            "job-uid",
            {"message": "Search for anime", "original_timestamp": "2026-02-27T10:00:00Z"},
            user_id=42,
        )

        mock_core_api.search.assert_awaited_once_with("anime", owner_user_id=42)

    @pytest.mark.asyncio
    async def test_search_normalizes_memory_search_result_format(
        self, handler, mock_llm_client, mock_core_api
    ):
        """IntentHandler must normalize MemorySearchResult nested format to flat format.

        Core API returns: [{"memory": {"id": "...", "content": "..."}, "score": 0.9}]
        Results in structured_result must be: [{"memory_id": "...", "title": "..."}]
        so the Telegram consumer can read r.get("title") and r.get("memory_id").
        """
        mock_llm_client.complete = AsyncMock(
            return_value='{"intent": "search", "keywords": ["anime"]}'
        )
        mock_core_api.search = AsyncMock(
            return_value=[
                {"memory": {"id": "mem-99", "content": "My anime list"}, "score": 0.9},
            ]
        )

        result = await handler.handle(
            "job-norm",
            {"message": "Search for anime", "original_timestamp": "2026-02-27T10:00:00Z"},
            user_id=1,
        )

        assert result is not None
        results = result.get("results", [])
        assert len(results) == 1
        assert results[0]["memory_id"] == "mem-99"
        assert results[0]["title"] == "My anime list"


class TestIntentHandlerSearchWithSingleKeyword:
    """Test search intent with single keyword extraction."""

    @pytest.fixture
    def handler(self, mock_llm_client, mock_core_api, llm_worker_config):
        return IntentHandler(
            llm_client=mock_llm_client,
            core_api=mock_core_api,
            config=llm_worker_config,
        )

    @pytest.mark.asyncio
    async def test_search_intent_single_keyword(
        self, handler, mock_llm_client, mock_core_api
    ):
        """Test that search intent works with single keyword."""
        original_ts = "2026-02-24T10:00:00Z"
        search_keywords = ["vacation"]
        search_query = "vacation"

        mock_llm_client.complete = AsyncMock(
            return_value='{"intent": "search", "keywords": ["vacation"]}'
        )

        mock_search_results = [
            {"memory_id": "mem-vacation", "title": "Hawaii Trip 2023"},
        ]
        mock_core_api.search = AsyncMock(return_value=mock_search_results)

        result = await handler.handle(
            "job-004",
            {
                "message": "Find my vacation photos",
                "original_timestamp": original_ts,
                "user_id": 12345,
            },
            user_id=12345,
        )

        mock_core_api.search.assert_awaited_once_with(search_query, owner_user_id=12345)
        assert result.get("results") == mock_search_results


class TestIntentHandlerSearchWithMultipleKeywords:
    """Test search intent with multiple keywords extraction."""

    @pytest.fixture
    def handler(self, mock_llm_client, mock_core_api, llm_worker_config):
        return IntentHandler(
            llm_client=mock_llm_client,
            core_api=mock_core_api,
            config=llm_worker_config,
        )

    @pytest.mark.asyncio
    async def test_search_intent_many_keywords(
        self, handler, mock_llm_client, mock_core_api
    ):
        """Test that search intent works with many keywords."""
        original_ts = "2026-02-24T10:00:00Z"
        search_keywords = ["python", "tips", "tricks", "advanced"]
        search_query = "python tips tricks advanced"

        mock_llm_client.complete = AsyncMock(
            return_value='{"intent": "search", "keywords": ["python", "tips", "tricks", "advanced"]}'
        )

        mock_search_results = [
            {"memory_id": "mem-1", "title": "Python Tips"},
            {"memory_id": "mem-2", "title": "Advanced Tricks"},
        ]
        mock_core_api.search = AsyncMock(return_value=mock_search_results)

        result = await handler.handle(
            "job-005",
            {
                "message": "Find python tips tricks advanced",
                "original_timestamp": original_ts,
                "user_id": 12345,
            },
            user_id=12345,
        )

        mock_core_api.search.assert_awaited_once_with(search_query, owner_user_id=12345)
        assert result.get("results") == mock_search_results
