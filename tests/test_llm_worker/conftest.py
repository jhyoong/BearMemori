"""Configure path and shared fixtures for llm_worker tests."""

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

# Add shared path for redis_streams
_shared_path = os.path.join(PROJECT_ROOT, "shared")
if _shared_path not in sys.path:
    sys.path.insert(0, _shared_path)

from worker.config import LLMWorkerSettings


@pytest.fixture
def mock_llm_client():
    """Create a mock LLM client with async methods."""
    client = AsyncMock()
    client.complete = AsyncMock(return_value="{}")
    client.complete_with_image = AsyncMock(return_value="{}")
    client.close = AsyncMock()
    return client


@pytest.fixture
def mock_core_api():
    """Create a mock Core API client with async methods."""
    client = AsyncMock()
    client.update_job = AsyncMock()
    client.add_tags = AsyncMock()
    client.create_event = AsyncMock()
    client.get_open_tasks = AsyncMock(return_value=[])
    return client


@pytest.fixture
def llm_worker_config():
    """Create an LLMWorkerSettings instance with test values."""
    return LLMWorkerSettings(
        llm_base_url="http://localhost:8080/v1",
        llm_api_key="test-key",
        llm_vision_model="test-vision",
        llm_text_model="test-text",
        llm_max_retries=3,
        redis_url="redis://localhost:6379",
        core_api_url="http://localhost:8000",
        image_storage_path="/tmp/test-images",
    )
