"""Shared test fixtures for BearMemori core service tests."""

import os
import sys
from contextlib import asynccontextmanager

# Ensure correct paths for llm_worker tests
# Add llm_worker directory to path for "from worker.xxx" imports
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_llm_worker_path = os.path.join(PROJECT_ROOT, "llm_worker")
if _llm_worker_path not in sys.path:
    sys.path.insert(0, _llm_worker_path)

import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from core_svc.database import get_db, init_db
from core_svc.main import app


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
async def test_app(test_db, mock_redis, tmp_path):
    """Create a FastAPI test client with test DB and mock Redis."""
    original_lifespan = app.router.lifespan_context
    app.router.lifespan_context = _noop_lifespan

    # Set image storage path to temp directory for tests
    image_storage_dir = str(tmp_path / "images")
    os.makedirs(image_storage_dir, exist_ok=True)
    os.environ["IMAGE_STORAGE_PATH"] = image_storage_dir

    async def get_test_db():
        return test_db

    app.dependency_overrides[get_db] = get_test_db

    # Inject mock Redis into app state for routers that use request.app.state.redis
    app.state.redis = mock_redis

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client

    app.dependency_overrides.clear()
    # Clean up app state
    if hasattr(app.state, "redis"):
        del app.state.redis
    app.router.lifespan_context = original_lifespan
    # Clean up env
    os.environ.pop("IMAGE_STORAGE_PATH", None)


@pytest_asyncio.fixture
async def test_user(test_db):
    """Create a test user in the database."""
    await test_db.execute(
        "INSERT INTO users (telegram_user_id, display_name, is_allowed) VALUES (?, ?, ?)",
        (12345, "Test User", 1),
    )
    await test_db.commit()
    return 12345
