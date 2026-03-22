from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from bearmemori.api.routes import create_app
from bearmemori.core.triage import TriageResult
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import (
    EventFields,
    MemoryCategory,
    MemoryDraft,
    MemoryRecord,
)
from bearmemori.storage.pending_store import PendingStore
from bearmemori.storage.vector_store import VectorStore


@pytest.fixture
def db(tmp_path):
    d = MemoryDatabase(str(tmp_path / "test.db"))
    d.initialize()
    return d


@pytest.fixture
def vector_store(tmp_path):
    vs = VectorStore(persist_dir=str(tmp_path / "chroma"))
    vs.init()
    return vs


@pytest.fixture
def pending_store():
    return PendingStore()


@pytest.fixture
def client(db, vector_store, pending_store):
    app = create_app(
        db=db,
        vector_store=vector_store,
        pending_store=pending_store,
        llm_base_url="http://localhost:11434/v1",
        llm_api_key="test",
        llm_model="test",
    )
    return TestClient(app)


def _seed_memory(db, vector_store, **overrides):
    defaults = dict(
        id="mem_test1",
        category=MemoryCategory.PROFILE,
        title="Coffee preference",
        content="User likes black coffee",
        created_at=datetime.now(UTC),
        tags=["coffee"],
    )
    defaults.update(overrides)
    record = MemoryRecord(**defaults)
    db.create(record)
    vector_store.add(record)
    return record


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200


def test_list_memories(client, db, vector_store):
    _seed_memory(db, vector_store)
    r = client.get("/memory/list")
    assert r.status_code == 200
    assert len(r.json()["memories"]) == 1


def test_list_by_category(client, db, vector_store):
    _seed_memory(db, vector_store, id="mem_1", category=MemoryCategory.PROFILE)
    _seed_memory(db, vector_store, id="mem_2", category=MemoryCategory.EVENT)
    r = client.get("/memory/list?category=profile")
    assert len(r.json()["memories"]) == 1


def test_get_memory(client, db, vector_store):
    _seed_memory(db, vector_store)
    r = client.get("/memory/mem_test1")
    assert r.status_code == 200
    assert r.json()["title"] == "Coffee preference"


def test_get_nonexistent(client):
    r = client.get("/memory/nonexistent")
    assert r.status_code == 404


def test_delete_memory(client, db, vector_store):
    _seed_memory(db, vector_store)
    r = client.delete("/memory/mem_test1")
    assert r.status_code == 200
    assert r.json()["status"] == "deleted"


def test_search(client, db, vector_store):
    _seed_memory(db, vector_store)
    r = client.post("/memory/search", json={"query": "coffee", "top_k": 5})
    assert r.status_code == 200
    assert "results" in r.json()


def test_pending_confirm_flow(client):
    draft = {
        "category": "profile",
        "title": "Likes tea",
        "content": "User likes green tea",
        "tags": ["tea"],
    }
    r = client.post("/memory/pending", json=draft)
    assert r.status_code == 200
    pending_id = r.json()["pending_id"]

    r = client.post("/memory/confirm", json={"pending_id": pending_id})
    assert r.status_code == 200
    assert r.json()["status"] == "confirmed"

    record_id = r.json()["record_id"]
    r = client.get(f"/memory/{record_id}")
    assert r.status_code == 200


def test_dismiss_pending(client):
    draft = {"category": "general", "title": "Test", "content": "Test"}
    r = client.post("/memory/pending", json=draft)
    pending_id = r.json()["pending_id"]

    r = client.delete(f"/memory/pending/{pending_id}")
    assert r.status_code == 200
    assert r.json()["status"] == "dismissed"


def test_triage_endpoint(client):
    draft = MemoryDraft(
        category=MemoryCategory.PROFILE,
        title="Coffee",
        content="Likes coffee",
    )
    with patch("bearmemori.api.routes.run_triage") as mock_triage:
        mock_triage.return_value = TriageResult(
            should_save=True,
            draft=draft,
        )
        r = client.post(
            "/memory/triage",
            json={"conversation": [{"role": "user", "content": "I love coffee"}]},
        )
    assert r.status_code == 200
    assert r.json()["should_save"] is True
    assert "pending_id" in r.json()


def test_retrieve(client, db, vector_store):
    _seed_memory(db, vector_store)
    r = client.get("/memory/retrieve?query_context=coffee")
    assert r.status_code == 200
    assert "context_block" in r.json()


def test_upcoming_events(client, db, vector_store):
    future = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    _seed_memory(
        db,
        vector_store,
        id="mem_event",
        category=MemoryCategory.EVENT,
        title="Meeting",
        content="Team meeting",
        event_fields=EventFields(datetime=future, status="pending"),
    )
    r = client.get("/memory/events/upcoming")
    assert r.status_code == 200
    assert len(r.json()["events"]) == 1


def test_update_memory(client, db, sample_record):
    db.create(sample_record)
    response = client.put(
        f"/memory/{sample_record.id}",
        json={"title": "Updated Title", "needs_review": True},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "updated"

    retrieved = db.get(sample_record.id)
    assert retrieved.title == "Updated Title"
    assert retrieved.needs_review is True


def test_create_memory_direct(client):
    response = client.post(
        "/memory/create",
        json={
            "category": "general",
            "title": "Direct Memory",
            "content": "Created from webapp",
            "tags": ["test"],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "record_id" in data
    assert data["status"] == "created"


def test_bulk_delete(client, db, sample_record):
    record2 = sample_record.model_copy(update={"id": "mem_second123"})
    db.create(sample_record)
    db.create(record2)
    response = client.post(
        "/memory/bulk/delete",
        json={"record_ids": [sample_record.id, record2.id]},
    )
    assert response.status_code == 200
    assert response.json()["deleted"] == 2


def test_bulk_update(client, db, sample_record):
    record2 = sample_record.model_copy(update={"id": "mem_second123"})
    db.create(sample_record)
    db.create(record2)
    response = client.post(
        "/memory/bulk/update",
        json={
            "record_ids": [sample_record.id, record2.id],
            "updates": {"needs_review": False},
        },
    )
    assert response.status_code == 200


def test_list_memories_needs_review_filter(client, db, sample_record):
    db.create(sample_record)
    review_record = sample_record.model_copy(update={"id": "mem_review123", "needs_review": True})
    db.create(review_record)

    response = client.get("/memory/list?needs_review=true")
    assert response.status_code == 200
    data = response.json()
    assert len(data["memories"]) == 1


@pytest.fixture
def sample_record():
    return MemoryRecord(
        id="mem_test_sample",
        category=MemoryCategory.GENERAL,
        title="Sample Memory",
        content="Sample content",
        created_at=datetime.now(UTC),
        tags=["sample"],
    )
