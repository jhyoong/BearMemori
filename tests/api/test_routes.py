import tempfile
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from bearmemori.api.routes import create_app
from bearmemori.core.memory_service import MemoryService
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import Actor, EventFields, MemoryCategory, MemoryRecord
from bearmemori.storage.pending_store import PendingStore
from bearmemori.storage.vector_store import VectorStore


@pytest.fixture
def test_client():
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        db = MemoryDatabase(f.name)
        db.initialize()
        vs = MagicMock(spec=VectorStore)
        vs.search.return_value = []
        ps = PendingStore()
        memory_service = MemoryService(db=db, vector_store=vs)
        app = create_app(db=db, vector_store=vs, pending_store=ps, memory_service=memory_service)
        yield TestClient(app), db


def test_upcoming_events_with_start_end_returns_occurrences(test_client):
    client, db = test_client
    # Create a weekly recurring event
    record = MemoryRecord(
        id="mem_api001",
        category=MemoryCategory.EVENT,
        title="Weekly meeting",
        content="Team sync",
        created_at=datetime.now(UTC),
        event_fields=EventFields(
            datetime="2026-04-07T10:00:00+00:00",
            status="pending",
            recurrence="FREQ=WEEKLY;BYDAY=TU",
        ),
    )
    db.create(record, actor=Actor.API)

    response = client.get(
        "/memory/events/upcoming",
        params={"start": "2026-04-01T00:00:00+00:00", "end": "2026-04-30T23:59:59+00:00"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "occurrences" in data
    assert len(data["occurrences"]) == 4  # 4 Tuesdays in April 2026


def test_upcoming_events_without_start_end_no_occurrences_field(test_client):
    client, db = test_client
    response = client.get("/memory/events/upcoming", params={"days": 7})
    assert response.status_code == 200
    data = response.json()
    assert "occurrences" not in data
    assert "events" in data
