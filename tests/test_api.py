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


@pytest.fixture
def client_with_images(db, vector_store, pending_store, tmp_path):
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    app = create_app(
        db=db,
        vector_store=vector_store,
        pending_store=pending_store,
        llm_base_url="http://localhost:11434/v1",
        llm_api_key="test",
        llm_model="test",
        image_storage_dir=str(image_dir),
    )
    return TestClient(app), image_dir


def test_get_image(client_with_images):
    client, image_dir = client_with_images
    img_file = image_dir / "test.jpg"
    img_file.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 10)  # minimal JPEG-like bytes
    response = client.get("/images/test.jpg")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"


def test_get_image_not_found(client_with_images):
    client, _ = client_with_images
    response = client.get("/images/nonexistent.jpg")
    assert response.status_code == 404


def test_get_image_no_storage_configured(db, vector_store, pending_store):
    app = create_app(
        db=db,
        vector_store=vector_store,
        pending_store=pending_store,
        llm_base_url="http://localhost:11434/v1",
        llm_api_key="test",
        llm_model="test",
        image_storage_dir="",
    )
    c = TestClient(app)
    response = c.get("/images/anything.jpg")
    assert response.status_code == 404


def test_get_image_path_traversal(client_with_images):
    client, _ = client_with_images
    response = client.get("/images/..%2Fsecret.txt")
    assert response.status_code in (400, 404)  # URL decoding may vary

    response = client.get("/images/%2e%2e%2fsecret.txt")
    assert response.status_code in (400, 404)


def test_delete_memory_removes_image(client_with_images, db, vector_store):
    client, image_dir = client_with_images

    # Create image file on disk
    img_file = image_dir / "mem_img1.jpg"
    img_file.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 10)

    # Create memory record with image_path
    record = MemoryRecord(
        id="mem_imgtest1",
        category=MemoryCategory.GENERAL,
        title="Image Memory",
        content="Has an image",
        created_at=datetime.now(UTC),
        tags=[],
        image_path=str(img_file),
    )
    db.create(record)
    vector_store.add(record)

    assert img_file.exists()

    response = client.delete("/memory/mem_imgtest1")
    assert response.status_code == 200
    assert response.json()["status"] == "deleted"
    assert not img_file.exists()


def test_bulk_delete_removes_images(client_with_images, db, vector_store):
    client, image_dir = client_with_images

    img1 = image_dir / "bulk_img1.jpg"
    img2 = image_dir / "bulk_img2.jpg"
    img1.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 10)
    img2.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 10)

    record1 = MemoryRecord(
        id="mem_bulk_img1",
        category=MemoryCategory.GENERAL,
        title="Bulk Image 1",
        content="Has an image",
        created_at=datetime.now(UTC),
        tags=[],
        image_path=str(img1),
    )
    record2 = MemoryRecord(
        id="mem_bulk_img2",
        category=MemoryCategory.GENERAL,
        title="Bulk Image 2",
        content="Has an image",
        created_at=datetime.now(UTC),
        tags=[],
        image_path=str(img2),
    )
    db.create(record1)
    db.create(record2)
    vector_store.add(record1)
    vector_store.add(record2)

    assert img1.exists()
    assert img2.exists()

    response = client.post(
        "/memory/bulk/delete",
        json={"record_ids": ["mem_bulk_img1", "mem_bulk_img2"]},
    )
    assert response.status_code == 200
    assert response.json()["deleted"] == 2
    assert not img1.exists()
    assert not img2.exists()


def test_delete_memory_no_image_path(client_with_images, db, vector_store):
    """Deleting a memory with no image_path should succeed without error."""
    client, _ = client_with_images
    record = MemoryRecord(
        id="mem_no_img",
        category=MemoryCategory.GENERAL,
        title="No Image",
        content="No image attached",
        created_at=datetime.now(UTC),
        tags=[],
    )
    db.create(record)
    vector_store.add(record)

    response = client.delete("/memory/mem_no_img")
    assert response.status_code == 200


def test_confirm_with_source_chat_id(client, db):
    draft = {
        "category": "reminder",
        "title": "Pack bag",
        "content": "Remind to pack bag",
        "tags": ["packing"],
        "event_fields": {"datetime": "2026-03-26T20:00:00+00:00", "status": "pending"},
    }
    r = client.post("/memory/pending", json=draft)
    pending_id = r.json()["pending_id"]

    r = client.post(
        "/memory/confirm",
        json={"pending_id": pending_id, "source_chat_id": "46646397"},
    )
    assert r.status_code == 200
    record_id = r.json()["record_id"]

    record = db.get(record_id)
    assert record.source is not None
    assert record.source.chat_id == "46646397"
    assert record.source.platform == "telegram"
    assert record.metadata["source_chat_id"] == "46646397"
