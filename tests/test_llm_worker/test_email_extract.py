"""Tests for EmailExtractHandler."""

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

from worker.handlers.email_extract import EmailExtractHandler


class TestEmailExtractHandler:
    """Test cases for EmailExtractHandler."""

    @pytest.fixture
    def handler(self, mock_llm_client, mock_core_api, llm_worker_config):
        """Create handler with mocked dependencies."""
        return EmailExtractHandler(
            llm_client=mock_llm_client,
            core_api=mock_core_api,
            config=llm_worker_config,
        )

    async def test_email_extract_event_found(
        self, handler, mock_llm_client, mock_core_api
    ):
        """Test that event with high confidence creates notification."""
        # Mock LLM response with high confidence event
        mock_llm_client.complete = AsyncMock(
            return_value='{"events": [{"description": "Team meeting", "event_time": "2026-03-01T10:00:00Z", "confidence": 0.9}]}'
        )

        # Call handler
        result = await handler.handle(
            job_id="job-123",
            payload={"subject": "Meeting", "body": "Join us", "user_id": 12345},
            user_id=12345,
        )

        # Assert result contains first event's data
        assert result == {
            "description": "Team meeting",
            "event_date": "2026-03-01T10:00:00Z",
        }

        # Assert core_api.create_event was called with correct event_data
        mock_core_api.create_event.assert_called_once_with(
            event_data={
                "description": "Team meeting",
                "event_time": "2026-03-01T10:00:00Z",
                "user_id": 12345,
            }
        )

    async def test_email_extract_low_confidence(
        self, handler, mock_llm_client, mock_core_api
    ):
        """Test that event with low confidence does not create event."""
        # Mock LLM response with low confidence event
        mock_llm_client.complete = AsyncMock(
            return_value='{"events": [{"description": "Team meeting", "event_time": "2026-03-01T10:00:00Z", "confidence": 0.3}]}'
        )

        # Call handler
        result = await handler.handle(
            job_id="job-124",
            payload={"subject": "Meeting", "body": "Join us", "user_id": 12345},
            user_id=12345,
        )

        # Assert core_api.create_event was NOT called
        mock_core_api.create_event.assert_not_called()

        # Assert result is None
        assert result is None

    async def test_email_extract_no_events(
        self, handler, mock_llm_client, mock_core_api
    ):
        """Test that empty events list returns None."""
        # Mock LLM response with empty events
        mock_llm_client.complete = AsyncMock(return_value='{"events": []}')

        # Call handler
        result = await handler.handle(
            job_id="job-125",
            payload={"subject": "Meeting", "body": "Join us", "user_id": 12345},
            user_id=12345,
        )

        # Assert core_api.create_event was NOT called
        mock_core_api.create_event.assert_not_called()

        # Assert result is None
        assert result is None

    async def test_email_extract_multiple_events(
        self, handler, mock_llm_client, mock_core_api
    ):
        """Test that multiple high-confidence events creates first one returned."""
        # Mock LLM response with multiple high confidence events
        mock_llm_client.complete = AsyncMock(
            return_value='{"events": [{"description": "Team meeting", "event_time": "2026-03-01T10:00:00Z", "confidence": 0.9}, {"description": "Lunch", "event_time": "2026-03-01T12:00:00Z", "confidence": 0.85}]}'
        )

        # Call handler
        result = await handler.handle(
            job_id="job-126",
            payload={"subject": "Meeting", "body": "Join us", "user_id": 12345},
            user_id=12345,
        )

        # Assert create_event was called twice
        assert mock_core_api.create_event.call_count == 2

        # Assert result contains FIRST event's data
        assert result == {
            "description": "Team meeting",
            "event_date": "2026-03-01T10:00:00Z",
        }

    async def test_email_extract_mixed_confidence(
        self, handler, mock_llm_client, mock_core_api
    ):
        """Test that only high-confidence events (>0.7) create API calls."""
        # Mock LLM response with mixed confidence events
        mock_llm_client.complete = AsyncMock(
            return_value='{"events": [{"description": "Team meeting", "event_time": "2026-03-01T10:00:00Z", "confidence": 0.9}, {"description": "Lunch", "event_time": "2026-03-01T12:00:00Z", "confidence": 0.4}]}'
        )

        # Call handler
        result = await handler.handle(
            job_id="job-127",
            payload={"subject": "Meeting", "body": "Join us", "user_id": 12345},
            user_id=12345,
        )

        # Assert only high confidence event created
        mock_core_api.create_event.assert_called_once_with(
            event_data={
                "description": "Team meeting",
                "event_time": "2026-03-01T10:00:00Z",
                "user_id": 12345,
            }
        )

        # Assert result is the high confidence event
        assert result == {
            "description": "Team meeting",
            "event_date": "2026-03-01T10:00:00Z",
        }
