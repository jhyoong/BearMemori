from unittest.mock import AsyncMock, MagicMock

import pytest

from bearmemori.config import Settings
from bearmemori.core.memory_service import MemoryService
from bearmemori.core.reflection import ReflectionTask
from bearmemori.llm.client import LLMClient
from bearmemori.mcp.server import create_mcp_app
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.pending_store import PendingStore
from bearmemori.storage.vector_store import VectorStore


@pytest.fixture
def mcp_deps():
    db = MagicMock(spec=MemoryDatabase)
    vector_store = MagicMock(spec=VectorStore)
    vector_store.search.return_value = []
    db.get_upcoming_events.return_value = []
    settings = MagicMock(spec=Settings)
    settings.webapp_secret = ""
    settings.user_timezone = "UTC"
    settings.image_storage_dir = ""
    llm = MagicMock(spec=LLMClient)
    pending_store = MagicMock(spec=PendingStore)
    memory_service = MagicMock(spec=MemoryService)
    reflection_task = MagicMock(spec=ReflectionTask)
    reflection_task.run_once = AsyncMock(
        return_value={
            "run_id": "ref_test",
            "triggered_by": "mcp",
            "started_at": "2026-04-11T03:00:00+00:00",
            "finished_at": "2026-04-11T03:00:01+00:00",
            "candidates_evaluated": 0,
            "archived": 0,
            "reranked": 0,
            "kept_unchanged": 0,
            "decisions": [],
        }
    )
    return db, vector_store, settings, llm, pending_store, reflection_task, memory_service


def test_create_mcp_app_accepts_reflection_task(mcp_deps):
    db, vector_store, settings, llm, pending_store, reflection_task, memory_service = mcp_deps
    app = create_mcp_app(
        db=db,
        vector_store=vector_store,
        settings=settings,
        llm=llm,
        pending_store=pending_store,
        reflection_task=reflection_task,
        memory_service=memory_service,
    )
    assert app is not None


def test_create_mcp_app_without_reflection_task(mcp_deps):
    db, vector_store, settings, llm, pending_store, _, memory_service = mcp_deps
    # Should still work with reflection_task=None
    app = create_mcp_app(
        db=db,
        vector_store=vector_store,
        settings=settings,
        llm=llm,
        pending_store=pending_store,
        memory_service=memory_service,
    )
    assert app is not None
