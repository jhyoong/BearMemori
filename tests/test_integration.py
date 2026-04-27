from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from bearmemori.api.routes import create_app
from bearmemori.core.memory_service import MemoryService
from bearmemori.core.triage import TriageResult
from bearmemori.llm.client import LLMClient
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import EventFields, MemoryCategory, MemoryDraft
from bearmemori.storage.pending_store import PendingStore
from bearmemori.storage.vector_store import VectorStore


@pytest.fixture
def full_stack(tmp_path):
    db = MemoryDatabase(str(tmp_path / "test.db"))
    db.initialize()
    vs = VectorStore(persist_dir=str(tmp_path / "chroma"))
    vs.init()
    ps = PendingStore()
    memory_service = MemoryService(db=db, vector_store=vs)
    app = create_app(
        db=db,
        vector_store=vs,
        pending_store=ps,
        memory_service=memory_service,
        llm=MagicMock(spec=LLMClient),
    )
    return TestClient(app), db, vs, ps


def test_triage_confirm_retrieve_flow(full_stack):
    client, db, vs, ps = full_stack

    # 1. Triage proposes a memory
    draft = MemoryDraft(
        category=MemoryCategory.PROFILE,
        title="Coffee preference",
        content="User likes black coffee",
        tags=["coffee"],
    )
    with patch("bearmemori.api.routes.run_triage") as mock:
        mock.return_value = TriageResult(should_save=True, draft=draft)
        r = client.post(
            "/memory/triage",
            json={
                "conversation": [{"role": "user", "content": "I love black coffee"}],
            },
        )
    assert r.json()["should_save"] is True
    pending_id = r.json()["pending_id"]

    # 2. Confirm the pending memory
    r = client.post("/memory/confirm", json={"pending_id": pending_id})
    assert r.json()["status"] == "confirmed"
    record_id = r.json()["record_id"]

    # 3. Retrieve context
    r = client.get("/memory/retrieve", params={"query_context": "coffee"})
    assert "coffee" in r.json()["context_block"].lower()

    # 4. Search
    r = client.get("/memory/search", params={"query": "coffee"})
    assert len(r.json()["results"]) >= 1

    # 5. Get by ID
    r = client.get(f"/memory/{record_id}")
    assert r.json()["title"] == "Coffee preference"

    # 6. List
    r = client.get("/memory/list")
    assert len(r.json()["memories"]) == 1

    # 7. Delete
    r = client.delete(f"/memory/{record_id}")
    assert r.json()["status"] == "deleted"
    r = client.get(f"/memory/{record_id}")
    assert r.status_code == 404


def test_triage_no_save_flow(full_stack):
    client, db, vs, ps = full_stack

    with patch("bearmemori.api.routes.run_triage") as mock:
        mock.return_value = TriageResult(should_save=False)
        r = client.post(
            "/memory/triage",
            json={
                "conversation": [{"role": "user", "content": "Hello there"}],
            },
        )
    assert r.json()["should_save"] is False
    assert "pending_id" not in r.json()


def test_pending_dismiss_flow(full_stack):
    client, db, vs, ps = full_stack

    # Create pending directly
    r = client.post(
        "/memory/pending",
        json={
            "category": "general",
            "title": "Test info",
            "content": "Some test information",
        },
    )
    pending_id = r.json()["pending_id"]

    # Dismiss it
    r = client.delete(f"/memory/pending/{pending_id}")
    assert r.json()["status"] == "dismissed"

    # Confirm should fail now
    r = client.post("/memory/confirm", json={"pending_id": pending_id})
    assert r.status_code == 404


def test_event_with_upcoming(full_stack):
    client, db, vs, ps = full_stack

    future = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    draft = MemoryDraft(
        category=MemoryCategory.EVENT,
        title="Dentist appointment",
        content="Dentist at 2pm",
        event_fields=EventFields(datetime=future, status="pending"),
        tags=["health"],
    )
    with patch("bearmemori.api.routes.run_triage") as mock:
        mock.return_value = TriageResult(should_save=True, draft=draft)
        r = client.post(
            "/memory/triage",
            json={
                "conversation": [{"role": "user", "content": "I have a dentist appointment"}],
            },
        )
    pending_id = r.json()["pending_id"]
    client.post("/memory/confirm", json={"pending_id": pending_id})

    # Check upcoming events
    r = client.get("/memory/events/upcoming")
    assert len(r.json()["events"]) == 1
    assert r.json()["events"][0]["title"] == "Dentist appointment"

    # Check retrieve includes events
    r = client.get("/memory/retrieve", params={"query_context": "dentist"})
    assert "Upcoming Events" in r.json()["context_block"]
