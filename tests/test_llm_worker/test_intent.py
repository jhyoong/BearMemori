"""Tests for IntentHandler."""

import os
import sys

import pytest
from unittest.mock import AsyncMock

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
