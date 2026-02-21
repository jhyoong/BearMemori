"""Tests for FollowupHandler in LLM worker."""

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

from worker.handlers.followup import FollowupHandler


@pytest.fixture
def followup_handler(mock_llm_client, mock_core_api, llm_worker_config):
    """Create a FollowupHandler instance with mocked dependencies."""
    return FollowupHandler(
        llm_client=mock_llm_client,
        core_api=mock_core_api,
        config=llm_worker_config,
    )


class TestFollowupHandler:
    """Test cases for FollowupHandler."""

    @pytest.mark.asyncio
    async def test_followup_generates_question(self, followup_handler, mock_llm_client):
        """Test plain text response generates a question."""
        # Mock LLM returns a plain text response
        mock_llm_client.complete = AsyncMock(
            return_value="Could you specify which recipe you're looking for?"
        )

        # Call handler with job payload
        result = await followup_handler.handle(
            job_id="job-123",
            payload={"message": "butter recipe", "context": "no results"},
            user_id=12345,
        )

        # Assert result contains the question
        assert result == {
            "question": "Could you specify which recipe you're looking for?"
        }
        # Verify LLM was called
        mock_llm_client.complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_followup_with_context(self, followup_handler, mock_llm_client):
        """Test that context is included in the prompt."""
        # Mock LLM returns a response
        mock_llm_client.complete = AsyncMock(
            return_value="What category are you interested in?"
        )

        # Call handler with additional context
        result = await followup_handler.handle(
            job_id="job-456",
            payload={
                "message": "show me photos",
                "context": "user is looking at album 'Summer 2024'",
            },
            user_id=12345,
        )

        # Verify LLM was called with context included
        call_args = mock_llm_client.complete.call_args
        prompt = call_args[0][0]  # First positional argument

        # Check that both message and context are in the prompt
        assert "show me photos" in prompt
        assert "user is looking at album 'Summer 2024'" in prompt

    @pytest.mark.asyncio
    async def test_followup_strips_whitespace(self, followup_handler, mock_llm_client):
        """Test that whitespace is stripped from LLM response."""
        # Mock LLM returns response with extra whitespace
        mock_llm_client.complete = AsyncMock(return_value="  What do you mean?  \n")

        # Call handler
        result = await followup_handler.handle(
            job_id="job-789",
            payload={"message": "hello", "context": ""},
            user_id=12345,
        )

        # Assert whitespace is stripped
        assert result == {"question": "What do you mean?"}
        assert result["question"] == result["question"].strip()
