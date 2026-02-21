"""Tests for TaskMatchHandler."""

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

from worker.handlers.task_match import TaskMatchHandler


class TestTaskMatchHandler:
    """Test cases for TaskMatchHandler."""

    @pytest.fixture
    def handler(self, mock_llm_client, mock_core_api, llm_worker_config):
        """Create TaskMatchHandler instance with mocked dependencies."""
        return TaskMatchHandler(
            llm_client=mock_llm_client,
            core_api=mock_core_api,
            config=llm_worker_config,
        )

    @pytest.mark.asyncio
    async def test_task_match_found(self, handler, mock_llm_client, mock_core_api):
        """Test high confidence match returns result."""
        # Mock core_api.get_open_tasks returns tasks
        mock_core_api.get_open_tasks = AsyncMock(
            return_value=[{"id": "t-1", "description": "Buy groceries"}]
        )

        # Mock LLM returns match with high confidence
        mock_llm_client.complete = AsyncMock(
            return_value='{"matched_task_id": "t-1", "confidence": 0.9, "reason": "mentions groceries"}'
        )

        result = await handler.handle(
            "job-123",
            {
                "memory_id": "mem-1",
                "memory_content": "I bought groceries",
                "user_id": 12345,
            },
            user_id=12345,
        )

        assert result == {
            "task_id": "t-1",
            "task_description": "Buy groceries",
            "memory_id": "mem-1",
        }

    @pytest.mark.asyncio
    async def test_task_match_low_confidence(
        self, handler, mock_llm_client, mock_core_api
    ):
        """Test low confidence match returns None."""
        # Mock core_api.get_open_tasks returns tasks
        mock_core_api.get_open_tasks = AsyncMock(
            return_value=[{"id": "t-1", "description": "Buy groceries"}]
        )

        # Mock LLM returns low confidence
        mock_llm_client.complete = AsyncMock(
            return_value='{"matched_task_id": "t-1", "confidence": 0.3, "reason": "unclear match"}'
        )

        result = await handler.handle(
            "job-456",
            {
                "memory_id": "mem-2",
                "memory_content": "Some random note",
                "user_id": 12345,
            },
            user_id=12345,
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_task_match_no_tasks(self, handler, mock_llm_client, mock_core_api):
        """Test no open tasks returns None without calling LLM."""
        # Mock get_open_tasks returns empty list
        mock_core_api.get_open_tasks = AsyncMock(return_value=[])

        result = await handler.handle(
            "job-789",
            {
                "memory_id": "mem-3",
                "memory_content": "I need to buy things",
                "user_id": 12345,
            },
            user_id=12345,
        )

        assert result is None
        # Ensure LLM was NOT called
        mock_llm_client.complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_task_match_null_match(self, handler, mock_llm_client, mock_core_api):
        """Test null matched_task_id returns None."""
        # Mock core_api.get_open_tasks returns tasks
        mock_core_api.get_open_tasks = AsyncMock(
            return_value=[{"id": "t-1", "description": "Buy groceries"}]
        )

        # Mock LLM returns null matched_task_id
        mock_llm_client.complete = AsyncMock(
            return_value='{"matched_task_id": null, "confidence": 0.0, "reason": "no match"}'
        )

        result = await handler.handle(
            "job-101",
            {
                "memory_id": "mem-4",
                "memory_content": "Unrelated content",
                "user_id": 12345,
            },
            user_id=12345,
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_task_match_formats_task_list(
        self, handler, mock_llm_client, mock_core_api
    ):
        """Test prompt contains all task descriptions."""
        # Mock multiple tasks
        mock_core_api.get_open_tasks = AsyncMock(
            return_value=[
                {"id": "t-1", "description": "Buy groceries"},
                {"id": "t-2", "description": "Walk the dog"},
                {"id": "t-3", "description": "Finish report"},
            ]
        )

        # Mock LLM returns no match
        mock_llm_client.complete = AsyncMock(
            return_value='{"matched_task_id": null, "confidence": 0.0, "reason": "none"}'
        )

        await handler.handle(
            "job-202",
            {"memory_id": "mem-5", "memory_content": "Some memory", "user_id": 12345},
            user_id=12345,
        )

        # Verify LLM was called and check prompt contains tasks
        mock_llm_client.complete.assert_called_once()
        call_args = mock_llm_client.complete.call_args
        prompt = call_args[0][1]  # Second positional argument (model is first)

        # Check all task descriptions are in the prompt
        assert "Buy groceries" in prompt
        assert "Walk the dog" in prompt
        assert "Finish report" in prompt
