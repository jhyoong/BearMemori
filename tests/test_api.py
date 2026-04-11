from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from bearmemori.api.routes import create_app
from bearmemori.core.triage import TriageResult
from bearmemori.llm.client import LLMClient
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
        llm=MagicMock(spec=LLMClient),
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
    r = client.get("/memory/search", params={"query": "coffee", "top_k": 5})
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
    with patch("bearmemori.api.routes.run_triage", new_callable=AsyncMock) as mock_triage:
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


def test_create_memory_with_event_fields(client, db):
    response = client.post(
        "/memory/create",
        json={
            "category": "reminder",
            "title": "Call dentist",
            "content": "Schedule cleaning",
            "event_datetime": "2026-04-10T14:00:00+00:00",
        },
    )
    assert response.status_code == 200
    data = response.json()
    record_id = data["record_id"]
    record = db.get(record_id)
    assert record.event_fields is not None
    assert "2026-04-10" in record.event_fields.datetime
    assert record.event_fields.status == "pending"
    assert record.event_fields.recurrence is None


def test_create_memory_with_event_recurrence(client, db):
    response = client.post(
        "/memory/create",
        json={
            "category": "task",
            "title": "Weekly review",
            "content": "Review tasks",
            "event_datetime": "2026-04-07T09:00:00+00:00",
            "event_status": "pending",
            "event_recurrence": "FREQ=WEEKLY;BYDAY=MO",
        },
    )
    assert response.status_code == 200
    record = db.get(response.json()["record_id"])
    assert record.event_fields is not None
    assert record.event_fields.recurrence == "FREQ=WEEKLY;BYDAY=MO"


def test_create_memory_invalid_event_status(client):
    response = client.post(
        "/memory/create",
        json={
            "category": "reminder",
            "title": "Bad status",
            "content": "Test",
            "event_datetime": "2026-04-10T14:00:00+00:00",
            "event_status": "invalid",
        },
    )
    assert response.status_code == 422


def test_create_memory_no_event_fields_unchanged(client, db):
    """Creating without event fields still works as before."""
    response = client.post(
        "/memory/create",
        json={
            "category": "general",
            "title": "Plain memory",
            "content": "No events",
        },
    )
    assert response.status_code == 200
    record = db.get(response.json()["record_id"])
    assert record.event_fields is None


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
        llm=MagicMock(spec=LLMClient),
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
        llm=MagicMock(spec=LLMClient),
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


def test_due_events(client, db, vector_store):
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    _seed_memory(
        db,
        vector_store,
        id="mem_due1",
        category=MemoryCategory.REMINDER,
        title="Overdue reminder",
        content="Should have happened",
        event_fields=EventFields(datetime=past, status="pending"),
    )
    future = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    _seed_memory(
        db,
        vector_store,
        id="mem_future1",
        category=MemoryCategory.EVENT,
        title="Future event",
        content="Not due yet",
        event_fields=EventFields(datetime=future, status="pending"),
    )
    r = client.get("/memory/events/due")
    assert r.status_code == 200
    data = r.json()
    assert len(data["events"]) == 1
    assert data["events"][0]["id"] == "mem_due1"


def test_due_events_empty(client):
    r = client.get("/memory/events/due")
    assert r.status_code == 200
    assert r.json()["events"] == []


def test_recent_memories(client, db, vector_store):
    _seed_memory(db, vector_store, id="mem_recent1")
    since = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    r = client.get(f"/memory/recent?since={since}")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 1
    assert len(data["memories"]) == 1


def test_recent_memories_future_since(client, db, vector_store):
    _seed_memory(db, vector_store, id="mem_recent2")
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    r = client.get(f"/memory/recent?since={future}")
    assert r.status_code == 200
    assert r.json()["count"] == 0


def test_recent_memories_missing_since(client):
    r = client.get("/memory/recent")
    assert r.status_code == 422


def test_recent_memories_invalid_since(client):
    r = client.get("/memory/recent?since=not-a-date")
    assert r.status_code == 400


def test_briefing_empty(client):
    r = client.get("/memory/briefing")
    assert r.status_code == 200
    data = r.json()
    assert data["due_now"]["count"] == 0
    assert data["due_now"]["items"] == []
    assert data["upcoming_events"]["count"] == 0
    assert data["upcoming_events"]["items"] == []
    assert data["needs_review"]["count"] == 0
    assert data["total_memories"] == 0
    assert data["recent_activity"]["created_last_24h"] == 0
    assert data["recent_activity"]["updated_last_24h"] == 0


def test_briefing_with_data(client, db, vector_store):
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    _seed_memory(
        db,
        vector_store,
        id="mem_b_due",
        category=MemoryCategory.REMINDER,
        title="Overdue",
        content="Past due",
        event_fields=EventFields(datetime=past, status="pending"),
    )
    future = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    _seed_memory(
        db,
        vector_store,
        id="mem_b_upcoming",
        category=MemoryCategory.EVENT,
        title="Future",
        content="Coming up",
        event_fields=EventFields(datetime=future, status="pending"),
    )
    _seed_memory(
        db,
        vector_store,
        id="mem_b_review",
        category=MemoryCategory.GENERAL,
        title="Review me",
        content="Needs review",
        needs_review=True,
    )
    _seed_memory(
        db,
        vector_store,
        id="mem_b_regular",
        category=MemoryCategory.PROFILE,
        title="Regular",
        content="Just a memory",
    )

    r = client.get("/memory/briefing")
    assert r.status_code == 200
    data = r.json()
    assert data["due_now"]["count"] == 1
    assert data["upcoming_events"]["count"] == 1
    assert data["needs_review"]["count"] == 1
    assert data["total_memories"] == 4
    assert data["recent_activity"]["created_last_24h"] == 4


def test_briefing_custom_event_days(client, db, vector_store):
    future = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    _seed_memory(
        db,
        vector_store,
        id="mem_b_3day",
        category=MemoryCategory.EVENT,
        title="3 day event",
        content="In 3 days",
        event_fields=EventFields(datetime=future, status="pending"),
    )
    far_future = (datetime.now(UTC) + timedelta(days=10)).isoformat()
    _seed_memory(
        db,
        vector_store,
        id="mem_b_10day",
        category=MemoryCategory.EVENT,
        title="10 day event",
        content="In 10 days",
        event_fields=EventFields(datetime=far_future, status="pending"),
    )

    r = client.get("/memory/briefing?event_days=5")
    assert r.status_code == 200
    data = r.json()
    assert data["upcoming_events"]["count"] == 1


def test_list_memories_pagination(client, db, vector_store):
    for i in range(5):
        _seed_memory(db, vector_store, id=f"mem_page{i}", title=f"Memory {i}")
    r = client.get("/memory/list?limit=2&offset=0")
    assert r.status_code == 200
    data = r.json()
    assert len(data["memories"]) == 2
    assert data["total"] == 5
    assert data["offset"] == 0
    assert data["limit"] == 2


def test_list_memories_pagination_offset(client, db, vector_store):
    for i in range(5):
        _seed_memory(db, vector_store, id=f"mem_off{i}", title=f"Memory {i}")
    r = client.get("/memory/list?limit=2&offset=2")
    data = r.json()
    assert len(data["memories"]) == 2
    assert data["total"] == 5
    assert data["offset"] == 2


def test_list_memories_pagination_last_page(client, db, vector_store):
    for i in range(5):
        _seed_memory(db, vector_store, id=f"mem_last{i}", title=f"Memory {i}")
    r = client.get("/memory/list?limit=2&offset=4")
    data = r.json()
    assert len(data["memories"]) == 1
    assert data["total"] == 5


def test_list_memories_pagination_with_category(client, db, vector_store):
    for i in range(3):
        _seed_memory(
            db,
            vector_store,
            id=f"mem_cat{i}",
            category=MemoryCategory.TASK,
            title=f"Task {i}",
        )
    _seed_memory(db, vector_store, id="mem_other", category=MemoryCategory.GENERAL)
    r = client.get("/memory/list?category=task&limit=2&offset=0")
    data = r.json()
    assert len(data["memories"]) == 2
    assert data["total"] == 3


def test_list_memories_default_pagination(client, db, vector_store):
    """Without explicit limit/offset, response still includes pagination metadata."""
    _seed_memory(db, vector_store, id="mem_def1")
    r = client.get("/memory/list")
    data = r.json()
    assert "total" in data
    assert "offset" in data
    assert "limit" in data
    assert data["total"] == 1
    assert data["offset"] == 0
    assert data["limit"] == 50


def test_list_memories_limit_capped(client, db, vector_store):
    """Limit above 200 is capped to 200."""
    _seed_memory(db, vector_store, id="mem_cap1")
    r = client.get("/memory/list?limit=500")
    data = r.json()
    assert data["limit"] == 200


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


def test_update_event_status(client, db, vector_store):
    future = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    _seed_memory(
        db,
        vector_store,
        id="mem_evt_upd",
        category=MemoryCategory.REMINDER,
        title="Call dentist",
        content="Schedule cleaning",
        event_fields=EventFields(datetime=future, status="pending"),
    )
    response = client.put(
        "/memory/mem_evt_upd",
        json={"event_status": "done"},
    )
    assert response.status_code == 200
    record = db.get("mem_evt_upd")
    assert record.event_fields.status == "done"


def test_update_event_status_on_non_event_memory(client, db, vector_store):
    _seed_memory(db, vector_store, id="mem_nonevent", category=MemoryCategory.GENERAL)
    response = client.put(
        "/memory/mem_nonevent",
        json={"event_status": "done"},
    )
    assert response.status_code == 400
    assert "non-event" in response.json()["detail"]


def test_update_occurrence_date_without_event_status(client, db, vector_store):
    future = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    _seed_memory(
        db,
        vector_store,
        id="mem_occ_no_status",
        category=MemoryCategory.EVENT,
        title="Meeting",
        content="Weekly",
        event_fields=EventFields(
            datetime=future, status="pending", recurrence="FREQ=WEEKLY;BYDAY=MO"
        ),
    )
    response = client.put(
        "/memory/mem_occ_no_status",
        json={"occurrence_date": "2026-04-07"},
    )
    assert response.status_code == 400
    assert "occurrence_date requires event_status" in response.json()["detail"]


def test_update_occurrence_date_on_non_recurring(client, db, vector_store):
    future = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    _seed_memory(
        db,
        vector_store,
        id="mem_nonrecur",
        category=MemoryCategory.EVENT,
        title="One-time event",
        content="No recurrence",
        event_fields=EventFields(datetime=future, status="pending"),
    )
    response = client.put(
        "/memory/mem_nonrecur",
        json={"event_status": "done", "occurrence_date": "2026-04-07"},
    )
    assert response.status_code == 400
    assert "recurring" in response.json()["detail"]


def test_update_occurrence_date_toggle_done(client, db, vector_store):
    future = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    _seed_memory(
        db,
        vector_store,
        id="mem_recur_toggle",
        category=MemoryCategory.EVENT,
        title="Weekly meeting",
        content="Sync",
        event_fields=EventFields(
            datetime=future, status="pending", recurrence="FREQ=WEEKLY;BYDAY=MO"
        ),
    )
    # Mark occurrence as done
    response = client.put(
        "/memory/mem_recur_toggle",
        json={"event_status": "done", "occurrence_date": "2026-04-07"},
    )
    assert response.status_code == 200
    record = db.get("mem_recur_toggle")
    assert "2026-04-07" in record.metadata["completed_occurrences"]

    # Mark same occurrence back to pending
    response = client.put(
        "/memory/mem_recur_toggle",
        json={"event_status": "pending", "occurrence_date": "2026-04-07"},
    )
    assert response.status_code == 200
    record = db.get("mem_recur_toggle")
    assert "2026-04-07" not in record.metadata["completed_occurrences"]


def test_update_event_datetime(client, db, vector_store):
    future = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    _seed_memory(
        db,
        vector_store,
        id="mem_dt_upd",
        category=MemoryCategory.EVENT,
        title="Meeting",
        content="Moved",
        event_fields=EventFields(datetime=future, status="pending"),
    )
    new_dt = (datetime.now(UTC) + timedelta(days=5)).isoformat()
    response = client.put(
        "/memory/mem_dt_upd",
        json={"event_datetime": new_dt},
    )
    assert response.status_code == 200
    record = db.get("mem_dt_upd")
    assert new_dt[:10] in record.event_fields.datetime
