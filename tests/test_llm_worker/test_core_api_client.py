"""Tests for the Core API client."""

from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from worker.core_api_client import CoreAPIClient, CoreAPIError


@pytest.fixture
def mock_session():
    """Create a mock aiohttp ClientSession."""
    return MagicMock(spec=aiohttp.ClientSession)


async def test_update_job_success(mock_session):
    """Mock PATCH 200, verify correct URL and body."""
    mock_session.patch = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.text = AsyncMock(return_value="OK")
    mock_session.patch.return_value.__aenter__.return_value = mock_resp

    client = CoreAPIClient(base_url="http://localhost:8000", session=mock_session)
    await client.update_job(
        job_id="job-123",
        status="completed",
        result={"tags": ["tag1", "tag2"]},
    )

    mock_session.patch.assert_called_once()
    call_args = mock_session.patch.call_args
    assert call_args[0][0] == "http://localhost:8000/llm_jobs/job-123"


async def test_update_job_error(mock_session):
    """Mock PATCH 500, verify CoreAPIError raised."""
    mock_session.patch = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status = 500
    mock_resp.text = AsyncMock(return_value="Internal Server Error")
    mock_session.patch.return_value.__aenter__.return_value = mock_resp

    client = CoreAPIClient(base_url="http://localhost:8000", session=mock_session)
    with pytest.raises(CoreAPIError, match="PATCH.*returned 500"):
        await client.update_job(job_id="job-123", status="error")


async def test_add_tags_success(mock_session):
    """Mock POST 201, verify body is {"tags": [...], "status": "suggested"}."""
    mock_session.post = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status = 201
    mock_resp.text = AsyncMock(return_value="OK")
    mock_session.post.return_value.__aenter__.return_value = mock_resp

    client = CoreAPIClient(base_url="http://localhost:8000", session=mock_session)
    await client.add_tags(memory_id="mem-123", tags=["tag1", "tag2"])

    mock_session.post.assert_called_once()
    call_args = mock_session.post.call_args
    assert call_args[0][0] == "http://localhost:8000/memories/mem-123/tags"
    call_json = call_args[1]["json"]
    assert call_json == {"tags": ["tag1", "tag2"], "status": "suggested"}


async def test_create_event_success(mock_session):
    """Mock POST 201, verify returns parsed JSON."""
    mock_session.post = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status = 201
    mock_resp.text = AsyncMock(return_value="OK")
    mock_resp.json = AsyncMock(return_value={"id": "evt-456", "message": "created"})
    mock_session.post.return_value.__aenter__.return_value = mock_resp

    client = CoreAPIClient(base_url="http://localhost:8000", session=mock_session)
    result = await client.create_event(
        event_data={"owner_user_id": 1, "event_time": "2024-01-01T00:00:00Z", "description": "Test", "source_type": "email"}
    )

    assert result == {"id": "evt-456", "message": "created"}


async def test_get_open_tasks_success(mock_session):
    """Mock GET 200, verify query params include owner_user_id and state=NOT_DONE."""
    mock_session.get = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.text = AsyncMock(return_value="OK")
    mock_resp.json = AsyncMock(
        return_value=[
            {"id": 1, "title": "Task 1", "state": "NOT_DONE"},
            {"id": 2, "title": "Task 2", "state": "NOT_DONE"},
        ]
    )
    mock_session.get.return_value.__aenter__.return_value = mock_resp

    client = CoreAPIClient(base_url="http://localhost:8000", session=mock_session)
    tasks = await client.get_open_tasks(user_id=123)

    assert len(tasks) == 2
    assert tasks[0]["id"] == 1

    mock_session.get.assert_called_once()
    call_args = mock_session.get.call_args
    assert call_args[1]["params"]["owner_user_id"] == 123
    assert call_args[1]["params"]["state"] == "NOT_DONE"


async def test_get_open_tasks_empty(mock_session):
    """Mock GET 200 with [], verify returns empty list."""
    mock_session.get = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.text = AsyncMock(return_value="OK")
    mock_resp.json = AsyncMock(return_value=[])
    mock_session.get.return_value.__aenter__.return_value = mock_resp

    client = CoreAPIClient(base_url="http://localhost:8000", session=mock_session)
    tasks = await client.get_open_tasks(user_id=123)

    assert tasks == []