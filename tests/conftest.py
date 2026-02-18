"""Shared test fixtures for BearMemori core service tests."""

from contextlib import asynccontextmanager

import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from core.database import get_db, init_db
from core.main import app


@asynccontextmanager
async def _noop_lifespan(application):
    """Replace the real lifespan with a no-op so tests control DB and Redis."""
    yield


@pytest_asyncio.fixture
async def test_db(tmp_path):
    """Create a temporary SQLite database with all migrations applied."""
    db_path = str(tmp_path / "test.db")
    db = await init_db(db_path)
    yield db
    await db.close()


@pytest_asyncio.fixture
async def mock_redis():
    """Create a fake Redis client for testing."""
    import fakeredis.aioredis

    redis_client = fakeredis.aioredis.FakeRedis()
    yield redis_client
    await redis_client.aclose()


@pytest_asyncio.fixture
async def test_app(test_db, mock_redis):
    """Create a FastAPI test client with test DB and mock Redis."""
    original_lifespan = app.router.lifespan_context
    app.router.lifespan_context = _noop_lifespan

    async def get_test_db():
        return test_db

    app.dependency_overrides[get_db] = get_test_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client

    app.dependency_overrides.clear()
    app.router.lifespan_context = original_lifespan


@pytest_asyncio.fixture
async def test_user(test_db):
    """Create a test user in the database."""
    await test_db.execute(
        "INSERT INTO users (telegram_user_id, display_name, is_allowed) VALUES (?, ?, ?)",
        (12345, "Test User", 1),
    )
    await test_db.commit()
    return 12345
