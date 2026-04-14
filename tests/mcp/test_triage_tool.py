from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bearmemori.core.memory_service import MemoryService
from bearmemori.llm.client import LLMClient
from bearmemori.mcp.server import _handle_triage_conversation, create_mcp_app
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import MemoryCategory, MemoryDraft
from bearmemori.storage.pending_store import PendingStore
from bearmemori.storage.vector_store import VectorStore


@pytest.fixture
def llm():
    return MagicMock(spec=LLMClient)


@pytest.fixture
def pending_store():
    return MagicMock(spec=PendingStore)


def test_create_mcp_app_accepts_llm_and_pending_store():
    """create_mcp_app() must accept llm and pending_store without error."""
    db = MagicMock(spec=MemoryDatabase)
    vector_store = MagicMock(spec=VectorStore)
    vector_store.search.return_value = []
    db.get_upcoming_events.return_value = []

    from bearmemori.config import Settings

    settings = MagicMock(spec=Settings)
    settings.webapp_secret = ""
    settings.user_timezone = "UTC"
    settings.image_storage_dir = ""

    memory_service = MagicMock(spec=MemoryService)

    app = create_mcp_app(
        db=db,
        vector_store=vector_store,
        settings=settings,
        llm=MagicMock(spec=LLMClient),
        pending_store=MagicMock(spec=PendingStore),
        memory_service=memory_service,
    )
    assert app is not None


@pytest.mark.asyncio
async def test_handle_triage_conversation_should_save(llm, pending_store):
    """When triage returns should_save=True, pending_store.add is called and response includes
    pending_id and draft."""
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

    with patch(
        "bearmemori.mcp.server.run_triage", new_callable=AsyncMock, return_value=mock_result
    ):
        response = await _handle_triage_conversation(
            conversation=[{"role": "user", "content": "I love black coffee"}],
            memory_hint=None,
            current_time=None,
            llm=llm,
            pending_store=pending_store,
            user_timezone="UTC",
        )

    assert response["should_save"] is True
    assert response["pending_id"] == "pend_abc123"
    assert "draft" in response
    pending_store.add.assert_called_once_with(draft)


@pytest.mark.asyncio
async def test_handle_triage_conversation_should_not_save(llm, pending_store):
    """When triage returns should_save=False, pending_store.add is not called."""
    from bearmemori.core.triage import TriageResult

    mock_result = TriageResult(should_save=False, reason="llm_decided_no")

    with patch(
        "bearmemori.mcp.server.run_triage", new_callable=AsyncMock, return_value=mock_result
    ):
        response = await _handle_triage_conversation(
            conversation=[{"role": "user", "content": "Hey there"}],
            memory_hint=None,
            current_time=None,
            llm=llm,
            pending_store=pending_store,
            user_timezone="UTC",
        )

    assert response["should_save"] is False
    assert response.get("reason") == "llm_decided_no"
    pending_store.add.assert_not_called()


@pytest.mark.asyncio
async def test_handle_triage_conversation_no_llm(pending_store):
    """When llm is None, the handler returns an error dict."""
    response = await _handle_triage_conversation(
        conversation=[{"role": "user", "content": "test"}],
        memory_hint=None,
        current_time=None,
        llm=None,
        pending_store=pending_store,
        user_timezone="UTC",
    )
    assert "error" in response


@pytest.mark.asyncio
async def test_handle_triage_conversation_no_pending_store(llm):
    """When pending_store is None, the handler returns an error dict."""
    response = await _handle_triage_conversation(
        conversation=[{"role": "user", "content": "test"}],
        memory_hint=None,
        current_time=None,
        llm=llm,
        pending_store=None,
        user_timezone="UTC",
    )
    assert "error" in response
