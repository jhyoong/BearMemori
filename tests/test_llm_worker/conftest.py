"""Shared test fixtures for LLM worker tests."""

from unittest.mock import AsyncMock

import pytest
import pytest_asyncio


@pytest.fixture
def mock_llm_client():
    """Mock LLMClient with async methods."""
    client = AsyncMock()
    client.complete = AsyncMock(return_value="")
    client.complete_with_image = AsyncMock(return_value="")
    client.close = AsyncMock()
    return client


@pytest.fixture
def mock_core_api():
    """Mock CoreAPIClient with async methods."""
    client = AsyncMock()
    client.update_job = AsyncMock()
    client.add_tags = AsyncMock()
    client.create_event = AsyncMock(return_value={"id": "evt-1"})
    client.get_open_tasks = AsyncMock(return_value=[])
    return client


@pytest_asyncio.fixture
async def mock_redis():
    """Create a fake Redis client for testing."""
    import fakeredis.aioredis

    redis_client = fakeredis.aioredis.FakeRedis()
    yield redis_client
    await redis_client.aclose()


@pytest.fixture
def llm_worker_config():
    """Create a test config with defaults."""
    from worker.config import LLMWorkerSettings

    return LLMWorkerSettings(
        llm_base_url="http://localhost:8080/v1",
        llm_vision_model="test-vision",
        llm_text_model="test-text",
        llm_api_key="test-key",
        llm_max_retries=3,
        redis_url="redis://localhost:6379",
        core_api_url="http://localhost:8000",
        image_storage_path="/tmp/test-images",
    )