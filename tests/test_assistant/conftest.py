"""Shared fixtures for assistant service tests."""

import pytest_asyncio
import fakeredis.aioredis


@pytest_asyncio.fixture
async def mock_redis():
    """Fake Redis for assistant tests."""
    r = fakeredis.aioredis.FakeRedis()
    yield r
    await r.aclose()
