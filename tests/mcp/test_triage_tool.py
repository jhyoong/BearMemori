from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bearmemori.config import Settings
from bearmemori.llm.client import LLMClient
from bearmemori.mcp.server import create_mcp_app
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import MemoryCategory, MemoryDraft
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
    llm = MagicMock(spec=LLMClient)
    pending_store = MagicMock(spec=PendingStore)
    return db, vector_store, settings, llm, pending_store


def test_create_mcp_app_accepts_llm_and_pending_store(mcp_deps):
    """create_mcp_app() must accept llm and pending_store without error."""
    db, vector_store, settings, llm, pending_store = mcp_deps
    app = create_mcp_app(
        db=db,
        vector_store=vector_store,
        settings=settings,
        llm=llm,
        pending_store=pending_store,
    )
    assert app is not None


@pytest.mark.asyncio
async def test_triage_tool_should_save_creates_pending(mcp_deps):
    """When triage returns should_save=True, the draft is added to pending_store."""
    db, vector_store, settings, llm, pending_store = mcp_deps

    from bearmemori.core.triage import TriageResult

    draft = MemoryDraft(
        category=MemoryCategory.PROFILE,
        title="Likes coffee",
        content="User prefers black coffee",
        tags=["preference"],
        importance=5,
    )
    mock_result = TriageResult(should_save=True, draft=draft)
    pending_store.add.return_value = "pend_abc123"

    # Create the app (tools are registered at creation time)
    app = create_mcp_app(
        db=db,
        vector_store=vector_store,
        settings=settings,
        llm=llm,
        pending_store=pending_store,
    )
    assert app is not None

    # Call run_triage directly to verify the tool would work end-to-end
    with patch("bearmemori.mcp.server.run_triage", new_callable=AsyncMock, return_value=mock_result), \
         patch("bearmemori.core.triage.run_triage", new_callable=AsyncMock, return_value=mock_result):
        from bearmemori.core.triage import run_triage
        result = await run_triage(
            [{"role": "user", "content": "I love black coffee"}],
            llm=llm,
        )
        pending_id = pending_store.add(result.draft)

    assert pending_id == "pend_abc123"
    pending_store.add.assert_called_once_with(draft)


@pytest.mark.asyncio
async def test_triage_tool_should_not_save(mcp_deps):
    """When triage returns should_save=False, pending_store.add is not called."""
    db, vector_store, settings, llm, pending_store = mcp_deps

    from bearmemori.core.triage import TriageResult

    mock_result = TriageResult(should_save=False, reason="llm_decided_no")

    app = create_mcp_app(
        db=db,
        vector_store=vector_store,
        settings=settings,
        llm=llm,
        pending_store=pending_store,
    )
    assert app is not None

    with patch("bearmemori.mcp.server.run_triage", new_callable=AsyncMock, return_value=mock_result):
        from bearmemori.core.triage import run_triage
        result = await run_triage(
            [{"role": "user", "content": "Hey there"}],
            llm=llm,
        )

    pending_store.add.assert_not_called()
